"""The OMOP equivalence test (D-151, WS-03.4/03.5, TST-GOLD-02): the lake built from OMOP must screen exactly as the
lake flattened from the NDJSON.

    python -m tools.omop_parity --dir /tmp/tb-omop-parity                     # every data set, every ruleset
    python -m tools.omop_parity --dir /tmp/tb-omop-parity --sets synthetic    # one data set
    python -m tools.omop_parity ... --json eval/omop_parity/report.json        # the committed evidence

For each data set the same NDJSON snapshot (and the same site inputs) is rebuilt twice through ``Lake.rebuild``:
``TB_LAKE_SOURCE=legacy`` and ``TB_LAKE_SOURCE=omop`` (loaded into its own ``omop`` schema, then exported). Then:

1. **the lake tables** are compared row for row (the Parquet files the screening engine reads, in order);
2. for **every committed ruleset** (``rulesets/*`` and the open-data rulesets of ``tests/fixtures/open_data``) on
   every data set: the FEAS funnel (start, remaining per step, unknowns, variants, the monthly first-eligible
   counts, the prevalent pool, the unknown-code-system and basis counts) and the **per-patient outcome** of the
   screening engine (``SqlEngine``: every criterion's verdict, evidence ids and reason, D-130 coverage and D-135
   widening included) for every patient of the lake.

Data sets: ``synthetic`` (``tools.synth_hospital`` profile ``ci``: a JP-style and a TW-style site, 2,500 patients
each, with planted site inputs: proposed, confirmed, suspected and refuted diagnoses, a proposed and a confirmed
medicine and lab, demographic facts and a birth-date disagreement), ``public`` (``tools.public_site``: the SIGIR and
MedTxt notes; MedTxt only when fetched) and ``mimic`` (the MIMIC-IV FHIR demo of ``tools/open_data_e2e.py``, when
fetched). Exit status 0 only when every comparison is identical and something was compared (DI-3: empty stores, no
ruleset, nothing screened or a skipped data set fail; `--allow-skip` accepts a data set that is not fetched). The run
writes only to schemas under a random prefix of its own and drops only those. Each lake is built with its source
forced (``lake.source.force``), so a ``lake.source`` flag seeded in that database cannot build both lakes from one
source, and each lake's ``source.jsonl`` must name the source it was built from. Calls no model, no network.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import secrets
import shutil
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

RULESETS = [p.parent for p in sorted((ROOT / "rulesets").glob("*/manifest.yaml"))] + [
    p.parent for p in sorted((ROOT / "tests/fixtures/open_data/rulesets").glob("*/manifest.yaml"))
]
SETS = ("synthetic", "public", "mimic")


@dataclass
class DataSet:
    name: str
    ndjson: Path  # the snapshot's NDJSON
    site: dict[str, list[dict[str, Any]]]  # the site's inputs (D-135)
    snapshot: str
    run_date: date
    tz: str


@contextlib.contextmanager
def _env(**kw: str | None) -> Iterator[None]:
    old = {k: os.environ.get(k) for k in kw}
    try:
        for k, v in kw.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def load_ruleset(directory: Path) -> Any:
    """A committed ruleset; one without approved SQL (the open-data ones) gets the compiler's template SQL."""
    from tb_common.ruleset import Ruleset

    rs = Ruleset.load(directory)
    if not rs.sql:
        from tools.open_data_e2e import load_ruleset as with_sql

        rs = with_sql(directory)
    return rs


# ------------------------------------------------------------------------------------------------ data sets
def _ingest(work: Path, kind: str, src: Path, snapshot: str, tz: str, mapping: str, site_id: str) -> Path:
    from adapter.pipeline import AdapterConfig, run_ingest

    from tools import pglocal

    sec = work / "sec"
    sec.mkdir(parents=True, exist_ok=True)
    if not (sec / "site_hmac.key").exists():
        (sec / "site_hmac.key").write_bytes(secrets.token_bytes(32))
    lake = work / f"ingest-{site_id}"
    cfg = AdapterConfig(
        lake_dir=lake,
        secrets_dir=sec,
        mapping_path=ROOT / "services/adapter/mapping" / mapping,
        site_id=site_id,
        tz=tz,
        audit_dir=work / "audit",
        db_url=pglocal.for_work(work),
        validation_max_pct=100.0,
    )
    rep = run_ingest(cfg, kind, str(src), snapshot=snapshot, load_fhir=False, rebuild_lake=False, validate=False)
    if rep.errors:
        raise RuntimeError(f"ingest {site_id}: {rep.errors[:3]}")
    return lake / "ndjson" / snapshot


def planted_site_inputs(ndjson: Path, n: int = 40) -> dict[str, list[dict[str, Any]]]:
    """The site's own inputs for ``n`` patients of the snapshot, shaped as ``sitesetup.publish`` writes them: every
    basis (proposed, confirmed), a suspected and a refuted diagnosis, demographic facts, and a birth date that
    disagrees with the hospital's for every fifth patient (a conflict: the date must read as unknown)."""
    from adapter.ndjson import read_type
    from lake.flatten import BASIS, DEMOGRAPHIC

    pats = [p for p in read_type(ndjson, "Patient") if p.get("birthDate")][:n]
    out: dict[str, list[dict[str, Any]]] = {
        "Patient": [],
        "Condition": [],
        "Observation": [],
        "MedicationRequest": [],
        "Encounter": [],
    }

    def tag(r: dict[str, Any], basis: str | None) -> dict[str, Any]:
        if basis:
            r["meta"] = {"tag": [{"system": BASIS, "code": basis}]}
        return r

    icd = "http://hl7.org/fhir/sid/icd-10-cm"
    for i, p in enumerate(pats):
        pid, subject = p["id"], {"reference": f"Patient/{p['id']}"}
        day = f"2026-0{1 + i % 9}-1{i % 10}"
        basis = ("proposed", "confirmed")[i % 2]
        birth = p["birthDate"] if i % 5 else f"{int(p['birthDate'][:4]) - 1}{p['birthDate'][4:]}"
        out["Patient"].append({"resourceType": "Patient", "id": pid, "birthDate": birth})
        out["Encounter"].append(
            {
                "resourceType": "Encounter",
                "id": f"tbenc-{pid[:12]}-{day}",
                "status": "finished",
                "subject": subject,
                "period": {"start": day},
                "class": {"code": "AMB"},
            }
        )
        code = ("M10.9", "E11.9", "C50.9", "N18.4")[i % 4]
        out["Condition"].append(
            tag(
                {
                    "resourceType": "Condition",
                    "id": f"tbsf-c{i}",
                    "subject": subject,
                    "code": {"coding": [{"system": icd, "code": code}], "text": code},
                    "onsetDateTime": day,
                    "recordedDate": day,
                },
                basis,
            )
        )
        vs = ("provisional", "refuted", "differential", "confirmed")[i % 4]
        out["Condition"].append(
            {
                "resourceType": "Condition",
                "id": f"tbsf-v{i}",
                "subject": subject,
                "code": {"coding": [{"system": icd, "code": "C34.9"}]},
                "recordedDate": day,
                "verificationStatus": {"coding": [{"code": vs}]},
            }
        )
        out["MedicationRequest"].append(
            tag(
                {
                    "resourceType": "MedicationRequest",
                    "id": f"tbsf-m{i}",
                    "subject": subject,
                    "status": "active",
                    "intent": "order",
                    "authoredOn": day,
                    "medicationCodeableConcept": {
                        "coding": [
                            {"system": "http://www.whocc.no/atc", "code": ("M04AA01", "L04AX03")[i % 2]},
                            {"system": "urn:trialbox:local:drug", "code": f"LD{i}", "display": "local drug"},
                        ],
                        "text": "site drug",
                    },
                },
                basis,
            )
        )
        out["Observation"].append(
            tag(
                {
                    "resourceType": "Observation",
                    "id": f"tbsf-o{i}",
                    "subject": subject,
                    "status": "final",
                    "code": {"coding": [{"system": "http://loinc.org", "code": "3084-1"}], "text": "urate"},
                    "category": [{"coding": [{"code": "laboratory"}]}],
                    "effectiveDateTime": day,
                    **(
                        {"valueQuantity": {"value": 7.5 + i / 10, "unit": "mg/dL", "code": "mg/dL"}}
                        if i % 3
                        else {"valueString": "<0.3"}
                    ),
                },
                basis,
            )
        )
        out["Observation"].append(
            tag(
                {
                    "resourceType": "Observation",
                    "id": f"tbsf-d{i}",
                    "subject": subject,
                    "status": "final",
                    "code": {"coding": [{"system": DEMOGRAPHIC, "code": "birth_date"}]},
                    "valueString": birth,
                },
                basis,
            )
        )
    return out


def synthetic(work: Path, ref: date = date(2026, 11, 1)) -> list[DataSet]:
    from tools.synth_hospital import run as synth_run

    snap = (ref - timedelta(days=1)).isoformat()
    synth_run(work / "synth", profile="ci", ref_date=ref)
    out = []
    for site in ("jp-a", "tw-a"):
        nd = _ingest(
            work,
            "csv",
            work / "synth" / site,
            snap,
            "Asia/Tokyo" if site == "jp-a" else "Asia/Taipei",
            "tw_core/demo_his.yaml",
            site,
        )
        tz = "Asia/Tokyo" if site == "jp-a" else "Asia/Taipei"
        out.append(DataSet(f"synthetic-{site}", nd, planted_site_inputs(nd), snap, ref, tz))
    shutil.rmtree(work / "synth", ignore_errors=True)
    return out


def public(work: Path) -> list[DataSet]:
    from tools import public_site as ps

    snap = (ps.REF - timedelta(days=1)).isoformat()
    sites: tuple[str, ...] = ("en", "ja") if (ROOT / ".cache" / "medtxt").exists() else ("en",)
    ps.build(work / "hospital", sites=sites)
    nd = _ingest(work, "csv", work / "hospital", snap, "Asia/Taipei", "tw_core/demo_his.yaml", "public")
    return [DataSet("public-" + "+".join(sites), nd, {}, snap, ps.REF, "Asia/Taipei")]


def mimic(work: Path) -> list[DataSet]:
    from tools import open_data_e2e as od

    if not od.data_available():
        return []
    ing = od.ingest(od.DATA_DIR, work)  # builds a legacy lake as a side effect; only its NDJSON is used here
    return [DataSet("mimic-iv-demo", ing.lake_dir / "ndjson" / od.SNAPSHOT, {}, od.SNAPSHOT, od.RUN_DATE, od.TZ)]


# ------------------------------------------------------------------------------------------------ the comparison
def build_lakes(ds: DataSet, work: Path, omop_url: str) -> dict[str, Path]:
    from embed_service.embedder import HashEmbedder
    from lake.source import force
    from lake.store import Lake

    lakes = {}
    for source in ("legacy", "omop"):
        d = work / f"lake-{source}"
        shutil.rmtree(d, ignore_errors=True)
        lake = Lake(d, ds.tz)
        if ds.site:
            lake.put_site(ds.site)
        # D-207: force the source, so a lake.source flag seeded in this database cannot build both lakes from one
        with _env(TB_LAKE_SOURCE=source, TB_OMOP_DB_URL=omop_url if source == "omop" else None), force(source):
            lake.rebuild(ds.snapshot, HashEmbedder(), ds.ndjson)
        lakes[source] = d
    return lakes


def compare_tables(lakes: dict[str, Path], snapshot: str) -> dict[str, Any]:
    import pyarrow.parquet as pq
    from lake.flatten import SCHEMAS

    out: dict[str, Any] = {}
    for name in SCHEMAS:
        a, b = (
            pq.read_table(lakes[s] / "parquet" / f"snapshot={snapshot}" / f"{name}.parquet") for s in ("legacy", "omop")
        )
        same = a.equals(b)
        first = None
        if not same:
            ra, rb = a.to_pylist(), b.to_pylist()
            first = next(
                ({"row": i, "legacy": x, "omop": y} for i, (x, y) in enumerate(zip(ra, rb, strict=False)) if x != y),
                {"legacy_rows": len(ra), "omop_rows": len(rb)},
            )
        out[name] = {"rows": a.num_rows, "omop_rows": b.num_rows, "identical": same, "first_difference": first}
    return out


def _feas(lake: Any, rs: Any, ds: DataSet) -> dict[str, Any]:
    from orchestrator.scenarios.feas_compute import FeasParams, compute

    _, raw = compute(
        lake, rs, FeasParams(run_date=ds.run_date, snapshot=ds.snapshot, lookback_months=36, iterations=50)
    )
    return {
        "start": raw.start_n,
        "remaining": raw.remaining,
        "unknown": raw.unknown,
        "variants": raw.variants,
        "first_eligible": raw.first_eligible,
        "prevalent": raw.prevalent,
        "prevalent_pids": sorted(raw.prevalent_pids),
        "unknown_system": raw.unknown_system,
        "basis": raw.basis,
    }


def _outcomes(lake: Any, rs: Any, ds: DataSet, pids: list[str]) -> dict[str, Any]:
    from orchestrator.scenarios.evaluate import SqlEngine

    ids = [c.id for c in rs.active()]
    ev = SqlEngine(lake, ds.snapshot).evaluate(rs, pids, ds.run_date, ids)
    return {pid: {"results": e.results, "evidence": e.evidence, "reasons": e.reasons} for pid, e in sorted(ev.items())}


def compare_screening(lakes: dict[str, Path], ds: DataSet) -> dict[str, Any]:
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal

    lk = {s: LakeLocal(d, HashEmbedder(), ds.tz) for s, d in lakes.items()}
    pids = sorted(str(r["pid"]) for r in lk["legacy"].query("SELECT pid FROM patient", [], ds.snapshot).to_pylist())
    out: dict[str, Any] = {}
    for d in RULESETS:
        rs = load_ruleset(d)
        feas = {s: _feas(lake, rs, ds) for s, lake in lk.items()}
        outc = {s: _outcomes(lake, rs, ds, pids) for s, lake in lk.items()}
        diff = sorted(p for p in pids if outc["legacy"].get(p) != outc["omop"].get(p))
        verdicts: dict[str, int] = {}
        for o in outc["legacy"].values():
            for v in o["results"].values():
                k = "met" if v is True else "not_met" if v is False else "unknown"
                verdicts[k] = verdicts.get(k, 0) + 1
        out[rs.id] = {
            "feas_identical": feas["legacy"] == feas["omop"],
            "feas": {"start": feas["legacy"]["start"], "remaining": feas["legacy"]["remaining"]},
            "feas_omop": None if feas["legacy"] == feas["omop"] else feas["omop"],
            "patients": len(pids),
            "patients_evaluated": len(outc["legacy"]),
            "verdicts": verdicts,
            "patients_different": len(diff),
            "first_different": [
                {"pid": p, "legacy": outc["legacy"].get(p), "omop": outc["omop"].get(p)} for p in diff[:3]
            ],
        }
    return out


def omop_summary(url: str, lake_dir: Path) -> dict[str, Any]:
    from omop import dqd, schema

    db = schema.connect(url, schema.schema_for(lake_dir))
    try:
        counts = {
            t: int(db.fetchval(f"SELECT count(*) FROM {t}"))
            for t in (
                "person",
                "visit_occurrence",
                "condition_occurrence",
                "drug_exposure",
                "measurement",
                "observation",
                "procedure_occurrence",
                "note",
                "death",
                "fact_relationship",
                "concept",
                "tb_record",
            )
        }
        counts["local_concepts"] = int(db.fetchval("SELECT count(*) FROM concept WHERE concept_id >= 2100000000"))
        counts["conflicts_open"] = int(db.fetchval("SELECT count(*) FROM tb_conflict WHERE state = 'open'"))
        res = dqd.run(db)
        return {
            "rows": counts,
            "dqd": dqd.summary(res),
            "dqd_not_pass": [
                {
                    k: r[k]
                    for k in (
                        "checkName",
                        "cdmTableName",
                        "cdmFieldName",
                        "numViolatedRows",
                        "numDenominatorRows",
                        "status",
                        "notes",
                    )
                }
                for r in res
                if r["status"] != "pass"
            ],
        }
    finally:
        db.close()


PREFIX = re.compile(r"[a-z][a-z0-9]*_(?:[a-z0-9]+_)*")  # a tb_prefix this tool makes: a plain schema-name start


def with_prefix(url: str, prefix: str) -> str:
    """``url`` (same server and database) with ``prefix`` as its only ``tb_prefix``; built with ``urlencode``, never by
    appending text to the URL. An empty or unusual prefix is refused."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    from tb_common.db import split_url

    if not PREFIX.fullmatch(prefix) or len(prefix) > 32:
        raise ValueError(f"omop parity: refusing the schema prefix {prefix!r}")
    parts = urlsplit(split_url(url)[0])
    query = [*parse_qsl(parts.query, keep_blank_values=True), ("tb_prefix", prefix)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def private_url(url: str) -> tuple[str, str]:
    """``(url, prefix)`` for one run: the caller's server and database with a freshly minted random prefix
    ``par<8 hex>_`` (never the caller's own prefix, never empty). DI-3: the run writes only there and drops only the
    schemas it made."""
    prefix = f"par{secrets.token_hex(4)}_"
    return with_prefix(url, prefix), prefix


def _schemas(url: str) -> set[str]:
    import psycopg
    from tb_common.db import split_url

    with psycopg.connect(split_url(url)[0], autocommit=True) as con:
        return {str(r[0]) for r in con.execute("SELECT nspname FROM pg_namespace")}


def _drop_own(url: str, prefix: str, before: set[str]) -> list[str]:
    """Drop the schemas this run created (by name: there now, not there before, under its own random prefix)."""
    import psycopg
    from tb_common.db import split_url

    created = sorted(n for n in _schemas(url) - before if n.startswith(prefix))
    with psycopg.connect(split_url(url)[0], autocommit=True) as con:
        for n in created:
            con.execute(f'DROP SCHEMA "{n}" CASCADE')
    return created


def recorded_source(lake: Path, snapshot: str) -> str | None:
    """The source the last rebuild of ``snapshot`` recorded in ``<lake>/source.jsonl`` (``lake.source``); None when
    it recorded none."""
    log = lake / "source.jsonl"
    if not log.exists():
        return None
    said = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
    mine = [str(e.get("source")) for e in said if e.get("snapshot") == snapshot]
    return mine[-1] if mine else None


def failures(entry: dict[str, Any]) -> list[str]:
    """Why a data set's comparison proves nothing (DI-3): two empty stores, or nothing screened, compare equal."""
    out = []
    persons = int(entry["omop"]["rows"]["person"])
    patients = int(entry["tables"]["patient"]["rows"])
    if not persons:
        out.append("the OMOP store has no persons")
    if not patients:
        out.append("the legacy lake has no patients")
    if persons != patients:
        out.append(f"the OMOP store has {persons} persons, the legacy lake {patients} patients")
    if not entry["screening"]:
        out.append("no ruleset was screened")
    for rid, r in entry["screening"].items():
        if not r["patients_evaluated"]:
            out.append(f"{rid}: no patient evaluated")
    for source, said in (entry.get("recorded_source") or {}).items():
        if said != source:
            out.append(f"the {source} lake was meant to come from {source}, its rebuild recorded {said}")
    return out


BUILDERS = {"synthetic": synthetic, "public": public, "mimic": mimic}


def run(base: Path, sets: tuple[str, ...] = SETS, allow_skip: bool = False) -> dict[str, Any]:
    from tools import pglocal

    base.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"rulesets": [d.name for d in RULESETS], "sets": {}, "failures": []}
    fail: list[str] = report["failures"]
    if not RULESETS:
        fail.append("no ruleset to compare")
    with _env(TB_DB_URL=os.environ.get("TB_DB_URL")):  # the caller's environment is put back as it was
        for name in sets:
            work = base / name
            shutil.rmtree(work, ignore_errors=True)
            work.mkdir(parents=True)
            url, prefix = private_url(pglocal.for_work(work))
            before = _schemas(url)
            if any(n.startswith(prefix) for n in before):
                raise RuntimeError(f"omop parity: schemas named {prefix}* already exist; refusing to run")
            t0 = time.perf_counter()
            try:
                with _env(TB_DB_URL=url):  # the ingest's pid map and the flag store: this run's schemas only
                    _one_set(name, work, url, prefix, report, allow_skip)
            except BaseException as exc:  # clean up, but never let a clean-up error hide why the run failed
                try:
                    _drop_own(url, prefix, before)
                except Exception as drop_exc:
                    exc.add_note(f"omop parity: schemas {prefix}* were not dropped ({drop_exc!r}); drop them by hand")
                raise
            else:
                report.setdefault("schemas_dropped", {})[name] = len(_drop_own(url, prefix, before))
            finally:
                shutil.rmtree(work, ignore_errors=True)
            report.setdefault("seconds", {})[name] = round(time.perf_counter() - t0, 1)
    if not any("skipped" not in v for v in report["sets"].values()):
        fail.append("no data set was compared")
    report["identical"] = not fail and all(
        v.get("identical", False) for v in report["sets"].values() if "skipped" not in v
    )
    return report


def _one_set(name: str, work: Path, url: str, prefix: str, report: dict[str, Any], allow_skip: bool) -> None:
    dsets = BUILDERS[name](work)
    if not dsets:
        report["sets"][name] = {"skipped": "data not fetched"}
        if not allow_skip:
            report["failures"].append(f"{name}: skipped (data not fetched; --allow-skip to accept)")
    for i, ds in enumerate(dsets):
        omop_url = with_prefix(url, f"{prefix}omop{i}_")  # one more private level per data set
        w = work / ds.name
        lakes = build_lakes(ds, w, omop_url)
        entry: dict[str, Any] = {
            "snapshot": ds.snapshot,
            "site_inputs": {k: len(v) for k, v in ds.site.items()},
            "tables": compare_tables(lakes, ds.snapshot),
            "screening": compare_screening(lakes, ds),
            "omop": omop_summary(omop_url, lakes["omop"]),
            "recorded_source": {src: recorded_source(d, ds.snapshot) for src, d in lakes.items()},
        }
        entry["failures"] = failures(entry)
        report["failures"].extend(f"{ds.name}: {f}" for f in entry["failures"])
        entry["identical"] = (
            not entry["failures"]
            and all(t["identical"] for t in entry["tables"].values())
            and all(r["feas_identical"] and r["patients_different"] == 0 for r in entry["screening"].values())
        )
        report["sets"][ds.name] = entry
        shutil.rmtree(w, ignore_errors=True)


def table(report: dict[str, Any]) -> str:
    lines = []
    for name, e in report["sets"].items():
        if "skipped" in e:
            lines.append(f"{name}: skipped ({e['skipped']})")
            continue
        rows = sum(t["rows"] for t in e["tables"].values())
        same = sum(1 for t in e["tables"].values() if t["identical"])
        lines.append(f"{name}: lake {same}/{len(e['tables'])} tables identical ({rows:,} rows); DQD {e['omop']['dqd']}")
        for rid, r in e["screening"].items():
            lines.append(
                f"  {rid:12} FEAS {'=' if r['feas_identical'] else 'DIFF'} start {r['feas']['start']:>5}  "
                f"patients {r['patients']:>5}, different {r['patients_different']}  {r['verdicts']}"
            )
    lines.extend(f"FAILED: {f}" for f in report.get("failures", []))
    lines.append("IDENTICAL" if report["identical"] else "DIFFERENT")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path("/tmp/tb-omop-parity"))
    ap.add_argument("--sets", default=",".join(SETS))
    ap.add_argument("--json", type=Path)
    ap.add_argument("--allow-skip", action="store_true", help="a data set whose data is not fetched is not a failure")
    a = ap.parse_args(argv)
    os.environ.setdefault("TB_ENV", "DEV")
    rep = run(a.dir, tuple(s for s in a.sets.split(",") if s), a.allow_skip)
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(rep, indent=1, default=str, ensure_ascii=False) + "\n", encoding="utf-8")
    print(table(rep))
    return 0 if rep["identical"] else 1


if __name__ == "__main__":
    sys.exit(main())
