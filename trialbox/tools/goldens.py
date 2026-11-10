"""Committed goldens (T-006, WS-03.1, TST-GOLD-01, D-205): the merge gate for every data-core branch.

    python -m tools.goldens --check                                    # profile ci (5k), BOTH lake sources
    python -m tools.goldens --check --source omop                      # one source (or TB_LAKE_SOURCE=omop)
    python -m tools.goldens --write --reason "D-2xx: why the numbers move"
    python -m tools.goldens --write --profile 50k --from-report <run-5 report.json> --reason "D-2xx: run 5"
    python -m tools.goldens --check --profile 50k --from-report <report.json>   # a later run against the golden

``tests/golden/`` holds what the data core must keep producing from fixed synthetic inputs:

* ``funnels/<ruleset>@ci.json`` the FEAS funnel of every committed ruleset (start, remaining per step, unknowns,
  variants, the monthly first-eligible counts, the prevalent pool) on every data set;
* ``screen/<ruleset>@ci.candidates.json`` the SCREEN candidate set after the coded filters (S1: the pids, and per
  criterion the met / not met / unknown counts and a hash of every patient's verdicts, evidence and reasons);
* ``feas/basis@ci.json`` the FEAS basis table (D-135: coded, confirmed, proposed per step) and the unknown code
  systems (D-130) per ruleset and data set;
* ``lake/tables@ci.json`` every lake table of every data set: rows, and a hash per column (a time-zone or a deletes
  drift moves a column hash even when no funnel moves); the chunk table ``document_chunk`` (text, tokens, sha) the
  same way, and the schema version and sha its ``lake_meta`` declares;
* ``lake/schema@<version>.json`` the lake schema (``lake.flatten.SCHEMAS``, the chunk columns, ``schema_sha``);
* ``funnels/<ruleset>@50k.json`` written only from a run-5 artefact (``--from-report``), never generated locally.

The data sets (profile ``ci``, about 5,450 patients, no model, no network): ``synthetic-jp-a`` and ``synthetic-tw-a``
(``tools.synth_hospital`` profile ``ci``, seed 42: CGRD-style CSV feeds of 2,500 patients each, Asia/Tokyo and
Asia/Taipei, with the planted site inputs of ``tools.omop_parity``: proposed, confirmed, suspected and refuted
diagnoses, a birth-date conflict); ``synthetic-jp-a-deletes`` (the next night of the JP site, rebuilt into the same
lake with a tenth of its clinical records and half of the site's inputs gone and every seventh remaining
Observation and Condition corrected: the OMOP store tombstones and updates them); ``synthetic-jp-a-restored`` (the
night after, everything back as on the first night: tombstones lifted; lake tables only); ``ssmix2-jp`` (400
synthetic patients written as SS-MIX2 standardized and extended storage by ``tools.ssmix2_export``, HL7 v2 read
through the JP Core mapping, D-137); ``public-en`` (the 53 SIGIR notes of ``tools.public_site``: a notes-only
site). The site key is fixed, so the pseudonyms are the same on every machine.

A golden is JSON sorted by key; its ``meta`` names the generator and its seed, the ruleset version, the lake schema
version, the git HEAD that wrote it and the reason. ``--check`` compares everything but ``meta.head`` and
``meta.reason`` and prints, per file, the changed values by path (``synthetic-jp-a.remaining.GOUT-COH-INC-03: 371 ->
370``) and a unified diff. A deliberate change regenerates the goldens in the same pull request with ``--write
--reason "D-nnn: ..."``; ``--write`` without a reason naming a decision that exists is refused, both sources must
agree before anything is written, and a golden nothing computes any more is removed.

**The lake source is forced, never inherited.** The data sets are generated once and every lake is built once per
source with ``lake.source.force``, so neither a ``lake.source`` flag nor ``TB_LAKE_SOURCE`` can make the run build
from another source than the one it reports; the check then verifies it (the OMOP store holds the persons and the
tombstones, or no OMOP store exists, and the lake's own ``source.jsonl`` names the source). The run works in
database schemas of its own (a private ``tb_prefix``, also inside a ``TB_DB_URL`` that is already set) and drops
only those.
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

GOLDEN_DIR = ROOT / "tests" / "golden"
PROFILES = ("ci", "50k")
SEED = 42  # tools.synth_hospital's default seed, profile ci
REF = date(2026, 11, 1)
#: the synthetic sites' pseudonym key: fixed, so a pid is the same on every machine (synthetic data only)
SITE_KEY = hashlib.sha256(b"trialbox goldens: synthetic site key, never a real site").digest()
#: meta fields that say who wrote a golden and why (and, at 50k, which run); every other field is compared
VOLATILE_META = ("head", "reason", "written_with_source", "run_ids", "git")
REASON_RE = re.compile(r"\bD-\d{3}\b")


# ------------------------------------------------------------------------------------------------ canonical JSON
def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False, default=str) + "\n"


def sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def git_head() -> str:
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    return out.stdout.strip() or "unknown"


# ------------------------------------------------------------------------------------------------ the lake schema
def schema_golden() -> tuple[str, dict[str, Any]]:
    from lake.flatten import SCHEMAS
    from lake.store import CHUNK_COLUMNS, LAKE_SCHEMA_VERSION, MIN_READABLE_SCHEMA, schema_sha

    body = {
        "meta": {"lake_schema_version": LAKE_SCHEMA_VERSION},
        "version": LAKE_SCHEMA_VERSION,
        "min_readable": MIN_READABLE_SCHEMA,
        "schema_sha": schema_sha(),
        "tables": {name: [list(c) for c in cols] for name, cols in SCHEMAS.items()},
        "document_chunk": [list(c) for c in CHUNK_COLUMNS],
    }
    return f"lake/schema@{LAKE_SCHEMA_VERSION}.json", json.loads(json.dumps(body, default=str))


# ------------------------------------------------------------------------------------------------ the data sets
@dataclass
class Prepared:
    """One data set before any lake is built: its NDJSON and site inputs (built once, used for every lake source)."""

    name: str
    kind: str  # what the set stands for (source kind)
    ndjson: Path
    site: dict[str, list[dict[str, Any]]] | None  # None: the lake gets no site inputs at all
    snapshot: str
    run_date: date
    tz: str
    into: str | None = None  # a later night: rebuilt into the lake of this earlier set
    rulesets: bool = True  # False: only the lake tables are pinned


@dataclass
class Built:
    name: str
    kind: str
    lake: Path
    snapshot: str
    run_date: date
    tz: str
    site_inputs: dict[str, int] = field(default_factory=dict)
    rulesets: bool = True
    # the OMOP store behind the lake right after this set's rebuild (a later night changes it): None = no store
    store: dict[str, int] | None = None


def _fixed_key(work: Path) -> None:
    sec = work / "sec"
    sec.mkdir(parents=True, exist_ok=True)
    (sec / "site_hmac.key").write_bytes(SITE_KEY)


def _drop(rows: list[dict[str, Any]], every: int) -> list[dict[str, Any]]:
    return [r for i, r in enumerate(rows) if i % every != every - 1]


def _modify(row: dict[str, Any]) -> bool:
    """Change one record in place the way a source corrects it (same id, another value); False when the record has
    nothing this knows how to change."""
    if row.get("resourceType") == "Observation" and isinstance(row.get("valueQuantity"), dict):
        v = row["valueQuantity"].get("value")
        if isinstance(v, int | float) and not isinstance(v, bool):
            row["valueQuantity"]["value"] = round(v + 1, 6)
            return True
    if row.get("resourceType") == "Condition" and isinstance(row.get("recordedDate"), str):
        try:
            d = date.fromisoformat(row["recordedDate"][:10])
        except ValueError:
            return False
        row["recordedDate"] = (d - timedelta(days=1)).isoformat() + row["recordedDate"][10:]
        return True
    return False


def next_night(ndjson: Path, out: Path) -> dict[str, int]:
    """The next night's feed: the same snapshot with a tenth of the clinical records gone (deleted at the source)
    and every seventh remaining Observation and Condition corrected (same id, another value or date). Patients stay
    (removing a person is the opt-out path's job, never a feed delta's). Returns how many were deleted and changed."""
    out.mkdir(parents=True, exist_ok=True)
    n = {"deleted": 0, "modified": 0}
    for f in sorted(ndjson.glob("*.ndjson")):
        rows = [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
        if f.stem != "Patient":
            kept = _drop(rows, 10)
            n["deleted"] += len(rows) - len(kept)
            rows = kept
            for i, r in enumerate(rows):
                if i % 7 == 3 and _modify(r):
                    n["modified"] += 1
        (out / f.name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return n


def prepare(work: Path) -> list[Prepared]:
    """Every data set's NDJSON and site inputs in ``work`` (generated and ingested once, whatever the lake source)."""
    import inspect

    from tools import omop_parity as parity
    from tools import public_site as ps
    from tools.ssmix2_export import export
    from tools.synth_hospital import run as synth_run

    default_seed = inspect.signature(synth_run).parameters["seed"].default
    if default_seed != SEED:  # parity.synthetic generates with the default seed: the goldens' meta must not lie
        raise RuntimeError(f"tools.synth_hospital's default seed is {default_seed}, the goldens say {SEED}")
    _fixed_key(work)
    out: list[Prepared] = []
    for ds in parity.synthetic(work, REF):
        out.append(Prepared(ds.name, "csv feed + site inputs", ds.ndjson, ds.site, ds.snapshot, ds.run_date, ds.tz))
        if ds.name == "synthetic-jp-a":
            # the next night into the same lake: records deleted and corrected at the source, half of the site's
            # inputs withdrawn (the OMOP store tombstones what is gone) ...
            snap2 = REF.isoformat()
            nd2 = work / "night2" / snap2
            changed = next_night(ds.ndjson, nd2)
            if not (changed["deleted"] and changed["modified"]):
                raise RuntimeError(f"the next night must delete and modify records, got {changed}")
            site2 = {k: _drop(v, 2) for k, v in ds.site.items()}
            out.append(
                Prepared(
                    f"{ds.name}-deletes",
                    "deletes (tombstones) + corrections",
                    nd2,
                    site2,
                    snap2,
                    REF + timedelta(days=1),
                    ds.tz,
                    into=ds.name,
                )
            )
            # ... and the night after, everything back as on the first night: a tombstoned record that returns
            snap3 = (REF + timedelta(days=1)).isoformat()
            out.append(
                Prepared(
                    f"{ds.name}-restored",
                    "restored (tombstones lifted)",
                    ds.ndjson,
                    ds.site,
                    snap3,
                    REF + timedelta(days=2),
                    ds.tz,
                    into=ds.name,
                    rulesets=False,
                )
            )
    # SS-MIX2 standardized and extended storage (HL7 v2, JP Core mapping): 400 synthetic patients, D-137
    snap = (REF - timedelta(days=1)).isoformat()
    synth_run(work / "synth-ss", profile="ci", sites="jp-ss:JP:400", ref_date=REF, seed=SEED)
    export(work / "synth-ss" / "jp-ss", work / "ssmix2")
    nd = parity._ingest(work, "ssmix2", work / "ssmix2", snap, "Asia/Tokyo", "jp_core/ssmix2_site.yaml", "jp-ss")
    out.append(Prepared("ssmix2-jp", "SS-MIX2 storage (HL7 v2)", nd, None, snap, REF, "Asia/Tokyo"))
    shutil.rmtree(work / "synth-ss", ignore_errors=True)
    shutil.rmtree(work / "ssmix2", ignore_errors=True)

    snap = (ps.REF - timedelta(days=1)).isoformat()
    ps.build(work / "hospital", sites=("en",))  # never MedTxt: whether it was fetched must not change a golden
    nd = parity._ingest(work, "csv", work / "hospital", snap, "Asia/Taipei", "tw_core/demo_his.yaml", "public")
    out.append(Prepared("public-en", "notes only (public text)", nd, None, snap, ps.REF, "Asia/Taipei"))
    return out


def build_sets(work: Path, prepared: list[Prepared], source: str) -> list[Built]:
    """Build every data set's lake in ``work`` from ``source`` (forced: a ``lake.source`` flag or ``TB_LAKE_SOURCE``
    cannot make this build from another source); return them in order."""
    from embed_service.embedder import HashEmbedder
    from lake.source import force
    from lake.store import Lake
    from omop import schema as omop_schema

    out: list[Built] = []
    for p in prepared:
        lake = Lake(work / f"lake-{source}-{p.into or p.name}", p.tz)
        if p.site is not None:
            lake.put_site(p.site)
        with force(source):
            lake.rebuild(p.snapshot, HashEmbedder(), p.ndjson)
        store = omop_store(omop_schema.db_url() or "", lake.dir)
        out.append(Built(p.name, p.kind, lake.dir, p.snapshot, p.run_date, p.tz, _n(p.site or {}), p.rulesets, store))
    return out


def _n(site: dict[str, list[Any]]) -> dict[str, int]:
    return {k: len(v) for k, v in sorted(site.items())}


# ------------------------------------------------------------------------------------------------ what is pinned
def table_digest(lake: Path, snapshot: str) -> dict[str, Any]:
    """Rows and a hash per column of every lake table of one snapshot, of its chunk table (``document_chunk``: the
    text, the tokens and the sha the retrieval reads) and the schema its ``lake_meta`` declares."""
    import duckdb
    import pyarrow.parquet as pq
    from lake.flatten import SCHEMAS
    from lake.store import CHUNK_COLUMNS

    out: dict[str, Any] = {}
    for name in SCHEMAS:
        t = pq.read_table(lake / "parquet" / f"snapshot={snapshot}" / f"{name}.parquet")
        cols = {c: sha(t.column(c).to_pylist()) for c in t.column_names}
        out[name] = {"rows": t.num_rows, "sha": sha(t.to_pylist()), "columns": cols}
    con = duckdb.connect(str(lake / "db" / f"{snapshot}.duckdb"), read_only=True)
    try:
        names = [c for c, _ in CHUNK_COLUMNS]
        rows = con.execute(f"SELECT {', '.join(names)} FROM document_chunk ORDER BY chunk_key").fetchall()
        out["document_chunk"] = {
            "rows": len(rows),
            "sha": sha(rows),
            "columns": {c: sha([r[i] for r in rows]) for i, c in enumerate(names)},
        }
        meta = con.execute("SELECT snapshot, schema_version, schema_sha FROM lake_meta").fetchone()
        out["lake_meta"] = dict(zip(("snapshot", "schema_version", "schema_sha"), meta or (), strict=False))
    finally:
        con.close()
    return out


def ruleset_numbers(
    lk: Any, rs: Any, b: Built, pids: list[str]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """``(funnel, candidates, basis)`` of one ruleset on one data set."""
    from orchestrator.scenarios.evaluate import FILTERED, SqlEngine, structured_candidate

    from tools import omop_parity as parity

    f = parity._feas(lk, rs, b)  # type: ignore[arg-type]  # duck-typed: snapshot, run_date
    funnel = {
        "start": f["start"],
        "remaining": f["remaining"],
        "unknown": f["unknown"],
        "variants": f["variants"],
        "first_eligible": f["first_eligible"],
        "prevalent": f["prevalent"],
        "prevalent_pids_sha": sha(f["prevalent_pids"]),
    }
    basis = {"basis": f["basis"], "unknown_system": f["unknown_system"]}
    active = [c for c in rs.active() if c.kind in ("inclusion", "exclusion")]
    structured = [c.id for c in active if c.class_ in FILTERED]
    evals = SqlEngine(lk, b.snapshot).evaluate(rs, pids, b.run_date, [c.id for c in rs.active()])
    verdicts: dict[str, dict[str, int]] = {}
    for ev in evals.values():
        for cid, v in ev.results.items():
            k = "met" if v is True else "not_met" if v is False else "unknown"
            verdicts.setdefault(cid, {"met": 0, "not_met": 0, "unknown": 0})[k] += 1
    cands = sorted(p for p in pids if structured_candidate(rs, evals.get(p), set(structured)))
    outcomes = {
        pid: {"results": e.results, "evidence": e.evidence, "reasons": e.reasons} for pid, e in sorted(evals.items())
    }
    candidates = {
        "patients": len(pids),
        "structured_criteria": structured,
        "candidates": len(cands),
        "candidate_pids": cands,
        "verdicts": verdicts,
        "outcomes_sha": sha(outcomes),
    }
    return funnel, candidates, basis


def compute(work: Path, prepared: list[Prepared], source: str) -> tuple[dict[str, dict[str, Any]], list[Built]]:
    """Every ``ci`` golden, computed now from lakes built from ``source``: ``{relative path: body}``."""
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from lake.store import LAKE_SCHEMA_VERSION

    from tools import omop_parity as parity

    built = build_sets(work, prepared, source)
    meta = {"generator": "tools.synth_hospital profile ci + tools.public_site en", "seed": SEED,
            "ref_date": REF.isoformat(), "lake_schema_version": LAKE_SCHEMA_VERSION, "profile": "ci"}  # fmt: skip
    files: dict[str, dict[str, Any]] = {}
    tables: dict[str, Any] = {}
    basis_all: dict[str, Any] = {}
    rulesets = [parity.load_ruleset(d) for d in parity.RULESETS]
    for rs in rulesets:
        m = {**meta, "ruleset": rs.id, "ruleset_version": rs.version}
        files[f"funnels/{rs.id}@ci.json"] = {"meta": m, "sets": {}}
        files[f"screen/{rs.id}@ci.candidates.json"] = {"meta": m, "sets": {}}
    for b in built:
        lk = LakeLocal(b.lake, HashEmbedder(), b.tz)
        tables[b.name] = {
            "kind": b.kind, "snapshot": b.snapshot, "run_date": b.run_date.isoformat(), "tz": b.tz,
            "site_inputs": b.site_inputs, "tables": table_digest(b.lake, b.snapshot),
        }  # fmt: skip
        if not b.rulesets:
            continue
        pids = sorted(str(r["pid"]) for r in lk.query("SELECT pid FROM patient", [], b.snapshot).to_pylist())
        for rs in rulesets:
            funnel, cands, basis = ruleset_numbers(lk, rs, b, pids)
            files[f"funnels/{rs.id}@ci.json"]["sets"][b.name] = funnel
            files[f"screen/{rs.id}@ci.candidates.json"]["sets"][b.name] = cands
            basis_all.setdefault(rs.id, {"ruleset_version": rs.version, "sets": {}})["sets"][b.name] = basis
    files["feas/basis@ci.json"] = {"meta": meta, "rulesets": basis_all}
    files["lake/tables@ci.json"] = {"meta": meta, "sets": tables}
    rel, body = schema_golden()
    files[rel] = body
    return {k: json.loads(json.dumps(v, default=str)) for k, v in files.items()}, built


# ------------------------------------------------------------------------------------------------ the 50k goldens
def from_report(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The 50k goldens from a run's ``report.json`` (``tools.complete_run``, schema ``tb-complete-run/*``): per part,
    the SCREEN funnel, tiers and list size of the e2e study and its FEAS funnel when the part reports one. Refused
    for anything but a finished run of at least 50,000 patients with a run id."""
    if not str(report.get("schema", "")).startswith("tb-complete-run/"):
        raise ValueError("not a tools.complete_run report (schema tb-complete-run/*)")
    run_ids = [str(r) for r in report.get("run_ids") or [] if r]
    if not run_ids:
        raise ValueError("the report names no run id: the 50k goldens come from one identified run")
    if int(report.get("patients") or 0) < 50_000:
        raise ValueError(f"the report is a run of {report.get('patients')} patients, not 50k")
    from tools.e2e_simple import TRIAL

    parts: dict[str, Any] = {}
    for row in report.get("parts") or []:
        scr = row.get("screen")
        if not scr:
            continue
        parts[str(row.get("tag"))] = {
            "screen_funnel": dict(scr.get("funnel") or []),
            "tiers": scr.get("tiers"),
            "listed": scr.get("listed"),
            **({"feas": row["feas"]} if row.get("feas") else {}),
        }
    if not parts:
        raise ValueError("the report has no part with a SCREEN funnel")
    meta = {"profile": "50k", "run_ids": run_ids, "patients": int(report["patients"]),
            "git": (report.get("git") or {}).get("head"), "report_schema": report["schema"]}  # fmt: skip
    return {f"funnels/{TRIAL}@50k.json": {"meta": meta, "parts": parts}}


# ------------------------------------------------------------------------------------------------ the comparison
def _strip(body: dict[str, Any]) -> dict[str, Any]:
    out = dict(body)
    if isinstance(out.get("meta"), dict):
        out["meta"] = {k: v for k, v in out["meta"].items() if k not in VOLATILE_META}
    return out


def changes(a: Any, b: Any, path: str = "") -> list[str]:
    """The changed values by path, golden ``a`` -> now ``b`` (sorted lists of strings compare as sets)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[str] = []
        for k in sorted(set(a) | set(b), key=str):
            p = f"{path}.{k}" if path else str(k)
            if k not in b:
                out.append(f"{p}: removed (was {_short(a[k])})")
            elif k not in a:
                out.append(f"{p}: added ({_short(b[k])})")
            else:
                out.extend(changes(a[k], b[k], p))
        return out
    if isinstance(a, list) and isinstance(b, list) and a != b:
        if all(isinstance(x, str) for x in a + b):
            gone, new = sorted(set(a) - set(b)), sorted(set(b) - set(a))
            if gone or new:
                return [f"{path}: {len(a)} -> {len(b)} (-{len(gone)} {gone[:3]}, +{len(new)} {new[:3]})"]
        return [f"{path}: {_short(a)} -> {_short(b)}"]
    if a != b:
        return [f"{path}: {_short(a)} -> {_short(b)}"]
    return []


def _short(v: Any) -> str:
    s = json.dumps(v, ensure_ascii=False, default=str, sort_keys=True)
    return s if len(s) <= 80 else s[:77] + "..."


@dataclass
class Result:
    ok: bool
    lines: list[str]


def compare(golden_dir: Path, computed: dict[str, dict[str, Any]], profile: str = "ci") -> Result:
    """Every computed golden against its committed file, and every committed file of the profile against what was
    computed (a missing ruleset, a stale schema version)."""
    lines: list[str] = []
    committed = _committed(golden_dir, profile)
    for rel in sorted(set(committed) | set(computed)):
        if rel not in computed:
            lines.append(f"FAIL {rel}: committed, but nothing computes it now (a ruleset or a schema version gone)")
            continue
        if rel not in committed:
            lines.append(f"FAIL {rel}: no committed golden (a new ruleset or schema version: --write it)")
            continue
        old = _strip(json.loads(committed[rel].read_text(encoding="utf-8")))
        new = _strip(computed[rel])
        if old == new:
            continue
        ch = changes(old, new)
        lines.append(f"FAIL {rel}: {len(ch)} value(s) changed")
        lines.extend(f"  {c}" for c in ch[:40])
        if len(ch) > 40:
            lines.append(f"  ... and {len(ch) - 40} more")
        diff = difflib.unified_diff(
            dumps(old).splitlines(), dumps(new).splitlines(), f"golden/{rel}", f"now/{rel}", lineterm="", n=2
        )
        lines.extend(list(diff)[:200])
    return Result(not lines, lines)


def decision_known(reason: str) -> bool:
    """The reason names a decision that exists: a file ``docs/decisions/D-nnn-*.md`` or an entry of
    ``docs/DECISIONS.md`` (the decisions merged before the one-file-per-decision rule)."""
    ids = REASON_RE.findall(reason or "")
    legacy = ROOT / "docs" / "DECISIONS.md"
    body = legacy.read_text(encoding="utf-8") if legacy.exists() else ""
    return any(list((ROOT / "docs" / "decisions").glob(f"{i}-*.md")) or re.search(rf"\b{i}\b", body) for i in ids)


def _committed(golden_dir: Path, profile: str) -> dict[str, Path]:
    return {
        str(p.relative_to(golden_dir)): p
        for p in sorted(golden_dir.rglob("*.json"))
        if f"@{profile}" in p.name or (profile == "ci" and p.parent.name == "lake" and p.name.startswith("schema@"))
    }


def write(
    golden_dir: Path, computed: dict[str, dict[str, Any]], reason: str, source: str | None, prune: str | None = None
) -> list[str]:
    """Write the goldens that changed (meta: the HEAD and the reason); an unchanged golden keeps its file. With
    ``prune`` (a profile), a committed golden of that profile that nothing computes any more (a ruleset removed, an
    old schema version) is deleted, so nobody has to edit ``tests/golden`` by hand."""
    if not reason or not REASON_RE.search(reason):
        raise ValueError('--write needs --reason naming the decision that moves the numbers ("D-nnn: why")')
    if not decision_known(reason):
        raise ValueError(f"--reason names no decision that exists in docs/decisions or docs/DECISIONS.md: {reason!r}")
    head = git_head()
    wrote = []
    for rel, body in sorted(computed.items()):
        path = golden_dir / rel
        if path.exists() and _strip(json.loads(path.read_text(encoding="utf-8"))) == _strip(body):
            continue
        out = dict(body)
        out["meta"] = {**body.get("meta", {}), "head": head, "reason": reason}
        if source:
            out["meta"]["written_with_source"] = source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps(out), encoding="utf-8")
        wrote.append(rel)
    if prune:
        for rel, path in _committed(golden_dir, prune).items():
            if rel not in computed:
                path.unlink()
                wrote.append(f"{rel} (removed: nothing computes it now)")
    return wrote


# ------------------------------------------------------------------------------------------------ the lake source
SOURCE_CHOICES = ("legacy", "omop", "both")


def sources_for(choice: str | None) -> tuple[str, ...]:
    """The lake sources of this run: ``--source``; else ``TB_LAKE_SOURCE`` when it is set (one source); else both,
    which is the gate: a branch that breaks only the OMOP loader or export must not pass on the legacy lake alone."""
    from lake.source import SOURCES, lake_source

    if choice in (None, ""):
        choice = lake_source() if (os.environ.get("TB_LAKE_SOURCE") or "").strip() else "both"
    return tuple(SOURCES) if choice == "both" else (str(choice),)


def omop_store(url: str, lake: Path) -> dict[str, int] | None:
    """Persons and tombstoned records in the OMOP store behind ``lake``; None when that lake has no OMOP store (it
    was flattened from the NDJSON)."""
    import psycopg
    from omop.schema import schema_for
    from tb_common.db import split_url

    dsn, prefix = split_url(url)
    name = prefix + schema_for(lake)
    with psycopg.connect(dsn, autocommit=True) as con:
        reg = con.execute("SELECT to_regclass(%s)", (f'"{name}".person',)).fetchone()
        if not reg or reg[0] is None:
            return None
        persons = con.execute(f'SELECT count(*) FROM "{name}".person').fetchone()
        gone = con.execute(f"SELECT count(*) FROM \"{name}\".tb_record WHERE status = 'tombstoned'").fetchone()
        return {"persons": int(persons[0]) if persons else 0, "tombstoned": int(gone[0]) if gone else 0}


def check_source(source: str, built: list[Built]) -> list[str]:
    """The lakes came from ``source``: from OMOP, every lake's store held its persons right after its rebuild, the
    deletes set's store held tombstones and the restored set's store held none (they were lifted); flattened, no
    lake has an OMOP store. And each lake wrote ``source`` into its ``source.jsonl``."""
    bad = []
    for b in built:
        st = b.store
        if source == "omop" and not (st and st["persons"]):
            bad.append(f"FAIL source: {b.name} was meant to come from OMOP, but its OMOP store holds no person")
        elif source == "omop" and st and b.kind.startswith("deletes") and not st["tombstoned"]:
            bad.append(f"FAIL source: {b.name} deleted records at the source, but the OMOP store tombstoned none")
        elif source == "omop" and st and b.kind.startswith("restored") and st["tombstoned"]:
            bad.append(f"FAIL source: {b.name} restored every record, but {st['tombstoned']} are still tombstoned")
        if source == "legacy" and st is not None:
            bad.append(f"FAIL source: {b.name} was meant to be flattened (legacy), but an OMOP store was loaded")
        log = b.lake / "source.jsonl"
        said = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x] if log.exists() else []
        mine = [e["source"] for e in said if e.get("snapshot") == b.snapshot]
        if mine[-1:] != [source]:
            bad.append(
                f"FAIL source: {b.name} was meant to come from {source}, its rebuild recorded {mine[-1:] or None}"
            )
    return bad


@contextlib.contextmanager
def workdir(given: Path | None, keep: bool) -> Iterator[Path]:
    if given is not None:
        shutil.rmtree(given, ignore_errors=True)
        given.mkdir(parents=True)
        path = given
    else:
        base = os.environ.get("TB_TEST_ROOT") or None
        if base:
            Path(base).mkdir(parents=True, exist_ok=True)
        path = Path(tempfile.mkdtemp(prefix="tb-goldens-", dir=base))
    try:
        yield path
    finally:
        if not keep:
            shutil.rmtree(path, ignore_errors=True)


def private_url(preset: str, work: Path) -> tuple[str, str]:
    """``(url, prefix)``: the database of ``preset`` with a ``tb_prefix`` that belongs to this run alone (the
    preset's own prefix, then ``g<hash>_``), so the run sees no flag or store of anybody else and its clean-up can
    only drop what it made."""
    from urllib.parse import quote

    from tb_common.db import split_url

    dsn, pre = split_url(preset)
    prefix = f"{pre}g{hashlib.sha1(f'{work.resolve()}:{os.getpid()}'.encode()).hexdigest()[:10]}_"
    return f"{dsn}{'&' if '?' in dsn else '?'}tb_prefix={quote(prefix)}", prefix


@contextlib.contextmanager
def private_db(work: Path) -> Iterator[str]:
    """The run's own database schemas, dropped at the end, and the environment as it was. With ``TB_DB_URL`` set (a
    box, CI with a Postgres service) the run still gets its own prefix in that database: it never reads the box's
    flags, never loads into the box's stores, and never drops a schema it did not create. ``TB_OMOP_DB_URL`` is
    unset for the run, so the OMOP stores are in the same private schemas."""
    from tools import pglocal

    saved = {k: os.environ.get(k) for k in ("TB_DB_URL", "TB_OMOP_DB_URL")}
    os.environ.pop("TB_OMOP_DB_URL", None)
    base = saved["TB_DB_URL"]
    if not base:
        os.environ.pop("TB_DB_URL", None)
        base = pglocal.for_work(work)  # the shared throwaway cluster
    url, prefix = private_url(base, work)
    os.environ["TB_DB_URL"] = url
    try:
        yield url
    finally:
        with contextlib.suppress(Exception):
            pglocal.drop_prefix(url, prefix)  # this run's schemas only; an empty prefix is refused there
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def run_ci(work: Path, sources: tuple[str, ...]) -> tuple[dict[str, dict[str, dict[str, Any]]], list[str]]:
    """``({source: goldens computed from that source}, problems)``: the data sets are generated and ingested once,
    then every lake is built and measured once per source."""
    computed: dict[str, dict[str, dict[str, Any]]] = {}
    problems: list[str] = []
    with private_db(work):
        prepared = prepare(work)
        for source in sources:
            computed[source], built = compute(work, prepared, source)
            problems += check_source(source, built)
            for b in {b.lake: b for b in built}.values():  # the lakes are measured: free the disk for the next source
                shutil.rmtree(b.lake, ignore_errors=True)
    return computed, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="compare with tests/golden (exit 0 identical, 1 not)")
    mode.add_argument("--write", action="store_true", help="regenerate the goldens (needs --reason)")
    ap.add_argument("--profile", choices=PROFILES, default="ci")
    ap.add_argument("--source", choices=SOURCE_CHOICES, help="the lake source(s) to build from (default: "
                    "TB_LAKE_SOURCE when set, else both)")  # fmt: skip
    ap.add_argument("--reason", default="", help='"D-nnn: why the numbers move" (required with --write)')
    ap.add_argument("--from-report", type=Path, help="a run's report.json (the only source of the 50k goldens)")
    ap.add_argument("--golden-dir", type=Path, default=GOLDEN_DIR)
    ap.add_argument("--dir", type=Path, help="work directory (default: a new temporary one, removed at the end)")
    ap.add_argument("--keep", action="store_true", help="keep the work directory")
    a = ap.parse_args(argv)
    if a.write and not REASON_RE.search(a.reason or ""):
        print('refused: --write needs --reason naming the decision that moves the numbers ("D-nnn: why")')
        return 2
    if a.write and not decision_known(a.reason):
        print(f"refused: --reason names no decision that exists in docs/decisions or docs/DECISIONS.md: {a.reason!r}")
        return 2
    os.environ.setdefault("TB_ENV", "DEV")
    t0 = time.perf_counter()
    if a.profile == "50k":
        if a.from_report is None:
            have = sorted(a.golden_dir.glob("funnels/*@50k.json"))
            if a.write:
                print("refused: the 50k goldens are written only from a run's report (--from-report), never here")
                return 2
            for p in have:
                meta = json.loads(p.read_text(encoding="utf-8")).get("meta", {})
                if not meta.get("run_ids"):
                    print(f"FAIL {p.name}: no run id in the file")
                    return 1
            print(f"50k goldens: {len(have)} file(s){'' if have else ' (none yet: they come from run 5, T-004)'}; "
                  "nothing to compare without --from-report")  # fmt: skip
            return 0
        computed50 = from_report(json.loads(a.from_report.read_text(encoding="utf-8")))
        if a.write:
            print("\n".join(f"wrote {r}" for r in write(a.golden_dir, computed50, a.reason, None)) or "unchanged")
            return 0
        res = compare(a.golden_dir, computed50, "50k")
        print("\n".join(res.lines) or "50k goldens: identical")
        return 0 if res.ok else 1
    sources = sources_for(a.source)
    with workdir(a.dir, a.keep) as work:
        computed, problems = run_ci(work, sources)
    took = time.perf_counter() - t0
    first = computed[sources[0]]
    said = "+".join(sources)
    if a.write:
        for other in sources[1:]:  # one set of goldens for every source: they must agree before anything is written
            for rel in sorted(set(first) | set(computed[other])):
                ch = changes(_strip(first.get(rel, {})), _strip(computed[other].get(rel, {})))
                problems += [f"FAIL {rel}: {sources[0]} and {other} disagree: {c}" for c in ch[:20]]
        if problems:
            print("\n".join(problems))
            print("nothing written")
            return 1
        wrote = write(a.golden_dir, first, a.reason, said, prune="ci")
        print("\n".join(f"wrote {r}" for r in wrote) or "every golden unchanged")
        print(f"{len(first)} goldens, lake source {said}, {took:.0f} s")
        return 0
    lines = list(problems)
    ok = not problems
    for source in sources:
        res = compare(a.golden_dir, computed[source], "ci")
        lines += [f"[{source}] {x}" for x in res.lines]
        ok = ok and res.ok
    print("\n".join(lines))
    print(f"{'IDENTICAL' if ok else 'DIFFERENT'}: {len(first)} goldens, lake source {said}, {took:.0f} s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
