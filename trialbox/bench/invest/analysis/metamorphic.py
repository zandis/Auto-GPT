"""Metamorphic invariants of the coded stages on a synthetic site (INVEST-1 §1.3), code only, no model.

A subsample of a synthetic hospital's CSV export is transformed and re-ingested; every live ruleset's coded cascade
runs on the base and on each variant, and the per-criterion verdicts are compared:

- ``irrelevant``: one extra diagnosis row per patient with a code no criterion reads -> unchanged
- ``shift``: every date and the reference date one day later -> unchanged (nothing moves relative to the index)
- ``duplicate``: every diagnosis, lab and medication row twice (a second record number) -> unchanged
- ``unit_case``: lab units spelled in another case (``mg/dL`` -> ``mg/dl``) -> unchanged
- ``delete_medication`` / ``delete_lab`` / ``delete_diagnosis``: every row of that table removed for half of the
  patients -> a criterion that reads only that table and was decided is now unknown or unchanged, never decided the
  other way (absence is not evidence on the screening path)

Synthetic data only; prints counts and criterion ids, never a row.

    python -m bench.invest.analysis.metamorphic --source <site dir> --work <dir> --out <file.json> [--patients 2000]
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

IRRELEVANT_ICD = "W61.62XA"  # struck by a duck: in no ruleset's value set
UNIT_CASE = {"mg/dL": "mg/dl", "g/dL": "g/dl", "mmol/L": "mmol/l", "umol/L": "umol/l", "U/L": "U/l", "mL/min": "ml/min"}
DELETE_TABLES = {
    "delete_medication": ("medication",),
    "delete_lab": ("lab", "vital"),
    "delete_diagnosis": ("diagnosis",),
}
DOMAINS = {"delete_medication": {"medication"}, "delete_lab": {"observation", "measurement"},
           "delete_diagnosis": {"condition"}}  # fmt: skip
INVARIANT = ("irrelevant", "shift", "duplicate", "unit_case")


def _read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames or []), list(r)


def _write(path: Path, cols: list[str], rows: Iterable[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def subsample(source: Path, dest: Path, patients: int) -> list[str]:
    """The first ``patients`` patients of ``source`` and every CSV row of theirs into ``dest`` (tables without a
    patient column are copied whole); ``meta.json`` gets the new counts. Returns the kept patient numbers."""
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    _cols, prows = _read(source / "patient.csv")
    keep = [r["mrn"] for r in prows[:patients]]
    kept = set(keep)
    counts: dict[str, int] = {}
    for f in sorted(source.glob("*.csv")):
        cols, rows = _read(f)
        if "mrn" in cols:
            rows = [r for r in rows if r["mrn"] in kept]
        _write(dest / f.name, cols, rows)
        counts[f.stem] = len(rows)
    meta = json.loads((source / "meta.json").read_text("utf-8")) if (source / "meta.json").exists() else {}
    meta["counts"] = counts
    (dest / "meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    return keep


def _shift_value(v: str) -> str:
    if not v:
        return v
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return (datetime.strptime(v, fmt) + timedelta(days=1)).strftime(fmt)
        except ValueError:
            continue
    return v


def _is_date_col(name: str) -> bool:
    return name.endswith(("_date", "_datetime", "_start", "_end")) or name in ("date", "datetime")


def transform(base: Path, dest: Path, kind: str, keep: list[str]) -> None:
    """Write variant ``kind`` of the site at ``base`` into ``dest``."""
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(base, dest)
    half = set(keep[::2])
    if kind == "irrelevant":
        cols, rows = _read(dest / "diagnosis.csv")
        first: dict[str, dict[str, str]] = {}
        for r in rows:
            first.setdefault(r["mrn"], r)
        extra = [{**r, "diag_no": f"X{r['diag_no']}", "icd10": IRRELEVANT_ICD} for r in first.values()]
        _write(dest / "diagnosis.csv", cols, rows + extra)
    elif kind == "shift":
        for f in dest.glob("*.csv"):
            cols, rows = _read(f)
            dcols = [c for c in cols if _is_date_col(c)]
            if dcols:
                _write(f, cols, ({**r, **{c: _shift_value(r[c]) for c in dcols}} for r in rows))
        meta = json.loads((dest / "meta.json").read_text("utf-8"))
        meta["ref_date"] = (date.fromisoformat(str(meta.get("ref_date", "2026-10-05"))) + timedelta(days=1)).isoformat()
        (dest / "meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    elif kind == "duplicate":
        for table, key in (("diagnosis", "diag_no"), ("lab", "lab_no"), ("medication", "rx_no")):
            cols, rows = _read(dest / f"{table}.csv")
            _write(dest / f"{table}.csv", cols, rows + [{**r, key: f"{r[key]}D"} for r in rows])
    elif kind == "unit_case":
        cols, rows = _read(dest / "lab.csv")
        _write(dest / "lab.csv", cols, ({**r, "unit": UNIT_CASE.get(r["unit"], r["unit"])} for r in rows))
    elif kind in DELETE_TABLES:
        for table in DELETE_TABLES[kind]:
            cols, rows = _read(dest / f"{table}.csv")
            _write(dest / f"{table}.csv", cols, (r for r in rows if r["mrn"] not in half))
    else:
        raise ValueError(f"unknown transform {kind!r}")
    if kind != "shift":
        meta = json.loads((dest / "meta.json").read_text("utf-8"))
        meta["counts"] = {f.stem: sum(1 for _ in f.open(encoding="utf-8")) - 1 for f in sorted(dest.glob("*.csv"))}
        (dest / "meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")


def verdicts(results: dict[str, Any]) -> dict[tuple[str, str, str], str]:
    """(ruleset, patient, criterion) -> T / F / U for every in-scope patient's evaluated criteria."""
    from orchestrator.scenarios.screen_cascade import verdict_of

    from bench.invest.match_adapter import _VERDICT

    out: dict[tuple[str, str, str], str] = {}
    for rid, res in results.items():
        for pid, t in res.traces.items():
            if not t.in_scope:
                continue
            for cid, o in t.outcomes.items():
                out[(rid, pid, cid)] = _VERDICT[verdict_of(o, False).verdict]
    return out


def compare(
    kind: str,
    base: dict[tuple[str, str, str], str],
    var: dict[tuple[str, str, str], str],
    domains: dict[tuple[str, str], set[str]],
) -> dict[str, Any]:
    """One transform's verdict comparison: how many answers were compared and which (ruleset, criterion) broke the
    invariant, with counts."""
    broke: dict[str, int] = defaultdict(int)
    compared = 0
    lost = 0
    for key, v in base.items():
        rid, _pid, cid = key
        # a delete compares a criterion reading only the emptied table, decided on the base (all patients: the
        # untouched half must not move either)
        if kind in DOMAINS and (v not in ("T", "F") or not (domains.get((rid, cid)) or {"none"}) <= DOMAINS[kind]):
            continue
        w = var.get(key)
        if w is None:  # out of scope in the variant (its index row went with the deletion)
            lost += 1
            continue
        compared += 1
        bad = (w != v) if kind in INVARIANT else (w in ("T", "F") and w != v)
        if bad:
            broke[f"{rid}/{cid}"] += 1
    return {"transform": kind, "compared": compared, "not_comparable": lost, "broken": sum(broke.values()),
            "criteria": dict(sorted(broke.items(), key=lambda kv: (-kv[1], kv[0]))), "pass": not broke}  # fmt: skip


def domains_of(rss: dict[str, Any]) -> dict[tuple[str, str], set[str]]:
    """(ruleset, criterion) -> the atom domains its coded logic reads."""
    from matching.cascade.engine import _atoms

    out: dict[tuple[str, str], set[str]] = {}
    for rid, rs in rss.items():
        for c in rs.active():
            atoms = _atoms(c.logic.model_dump(mode="json", by_alias=True, exclude_none=True))
            out[(rid, c.id)] = {str(a.get("domain")) for a in atoms if isinstance(a, dict) and a.get("domain")}
    return out


def screen_cascades(source: Path, work: Path, ids: tuple[str, ...], tz: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Ingest ``source``, run each ruleset's cascade with the night's screening settings and no judge (coded only)."""
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal

    from bench.invest.baseline import _cascade, _ingest
    from tools.cascade_e2e import load_trial

    lake_dir, run_date, snap = _ingest(source, work, tz)
    lake = LakeLocal(lake_dir, HashEmbedder(), tz)
    rss = {rid: load_trial(rid) for rid in ids}
    return rss, {rid: _cascade(lake, rss[rid], run_date, snap, None, 1, "metamorphic") for rid in ids}


def run(source: Path, work: Path, patients: int, ids: tuple[str, ...], tz: str,
        kinds: tuple[str, ...], cascades: Callable[..., Any] = screen_cascades) -> dict[str, Any]:  # fmt: skip
    """Subsample, build each variant, run the coded cascades, compare."""
    work.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="metamorphic-", dir=work))  # fresh per run, never the source
    site = work / "site-base"
    keep = subsample(source, site, patients)
    rss, res = cascades(site, work / "run-base", ids, tz)
    base = verdicts(res)
    doms = domains_of(rss)
    out = []
    for kind in kinds:
        transform(site, work / f"site-{kind}", kind, keep)
        _r, res_k = cascades(work / f"site-{kind}", work / f"run-{kind}", ids, tz)
        out.append(compare(kind, base, verdicts(res_k), doms))
    return {"patients": len(keep), "rulesets": list(ids), "base_answers": len(base), "transforms": out,
            "pass": all(t["pass"] for t in out)}  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    from bench.invest.dry_run import LIVE

    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--patients", type=int, default=2000)
    ap.add_argument("--tz", default="Asia/Taipei")
    ap.add_argument("--rulesets", default=",".join(LIVE))
    ap.add_argument("--transforms", default=",".join(INVARIANT + tuple(DELETE_TABLES)))
    a = ap.parse_args(argv)
    ids = tuple(x for x in a.rulesets.split(",") if x)
    result = run(a.source, a.work, a.patients, ids, a.tz, tuple(a.transforms.split(",")))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({t["transform"]: [t["compared"], t["broken"]] for t in result["transforms"]}))
    print("metamorphic:", "PASS" if result["pass"] else "FAIL")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
