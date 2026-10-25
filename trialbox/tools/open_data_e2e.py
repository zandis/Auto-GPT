"""Open-data end-to-end run: MIMIC-IV FHIR demo -> adapter -> lake (DuckDB) -> FEAS, in process (docs/OPEN_DATA.md).

Pipeline (no compose stack, no network):

1. read the PhysioNet release files fetched by ``tools/fetch_open_data.py`` (``.cache/open_data/mimic-iv-fhir-demo``);
2. normalise MIMIC code systems and dates (``adapter.mapping.mimic.normalise``, table-driven);
3. ingest through the real adapter (``fhir_bulk`` source: pseudonymisation, NDJSON snapshot, structural validation
   sample) into a temporary lake, rebuilt with the hash embedder;
4. for each open-data ruleset (``tests/fixtures/open_data/rulesets/<ID>``: hand-written Criterion IR from the
   ClinicalTrials.gov text cached next to it) render the SQL with the compiler's template generator and run FEAS
   (``orchestrator.scenarios.feas_compute.compute``: funnel, unknowns, sensitivity variants, monthly incidence,
   simulation) plus per-criterion counts;
5. check invariants (monotone funnel, counts <= cohort, small-cell rounding of every released count, identical
   results on a second independent run) and write ``report.json`` and ``report.md``.

    python tools/open_data_e2e.py                     # writes .cache/open_data/report.{json,md}
    python tools/open_data_e2e.py --no-repro          # one run only (skip the second-run comparison)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / ".cache" / "open_data" / "mimic-iv-fhir-demo"
OUT_DIR = ROOT / ".cache" / "open_data"
RULESETS_DIR = ROOT / "tests" / "fixtures" / "open_data" / "rulesets"
RULESETS = ["EMPULSE", "STARRT-AKI"]
RUN_DATE = date(2026, 10, 1)
SNAPSHOT = "2026-09-30"
LOOKBACK_MONTHS = 36
TZ = "America/New_York"  # MIMIC timestamps carry US Eastern offsets
SMALL_CELL = 5
SITE_KEY = b"trialbox-open-data-demo-key-0123456789abcdef"  # fixed: reproducible pseudonyms (public demo data)
REQUIRED_FILES = [
    "MimicPatient.ndjson.gz",
    "MimicEncounter.ndjson.gz",
    "MimicCondition.ndjson.gz",
    "MimicObservationLabevents.ndjson.gz",
    "MimicMedicationRequest.ndjson.gz",
    "MimicMedication.ndjson.gz",
    "MimicMedicationMix.ndjson.gz",
    "MimicEncounterICU.ndjson.gz",
    "MimicProcedureICU.ndjson.gz",
    "MimicProcedure.ndjson.gz",
]
DATASET = {
    "name": "MIMIC-IV Clinical Database Demo on FHIR",
    "version": "2.1.0",
    "url": "https://physionet.org/content/mimic-iv-fhir-demo/2.1.0/",
    "licence": "Open Data Commons Open Database License v1.0 (ODbL)",
}


_T0 = time.monotonic()


def _log(msg: str) -> None:
    print(f"[open-data {time.monotonic() - _T0:6.1f}s] {msg}", file=sys.stderr, flush=True)


def data_available(data_dir: Path = DATA_DIR) -> bool:
    return all((data_dir / "fhir" / f).exists() for f in REQUIRED_FILES)


# ---------------------------------------------------------------------------------------------- ruleset
def load_ruleset(directory: Path) -> Any:
    """Hand-written ruleset + SQL rendered by the compiler's deterministic template generator (never hand SQL)."""
    from criteria_compiler.compile_sql.generator import SqlGenerator
    from criteria_compiler.terminology.mapper import Terminology, ValueSets
    from tb_common.ruleset import Ruleset

    rs = Ruleset.load(directory)
    rs.sql = SqlGenerator(rs.id, rs.version, ValueSets(rs.id, rs.valuesets, Terminology())).render(rs.active())
    return rs


# ---------------------------------------------------------------------------------------------- ingest
@dataclass
class Ingested:
    lake_dir: Path
    normalisation: dict[str, Any]
    ingest: dict[str, Any]


def ingest(data_dir: Path, work: Path) -> Ingested:
    from adapter.mapping.mimic.normalise import MimicNormaliser, MimicTables
    from adapter.pipeline import AdapterConfig, run_ingest
    from adapter.validate.validator import StructuralValidator
    from embed_service.embedder import HashEmbedder
    from lake.store import Lake
    from tb_common.timeutil import add_months, month_ends
    from tb_contracts import RebuildResult, dump

    idx = month_ends(RUN_DATE, LOOKBACK_MONTHS)
    # last-encounter start lands inside the FEAS population window, away from its edges
    window_start = add_months(idx[0], -1)
    norm = MimicNormaliser(MimicTables.load(), window_start + timedelta(days=45), idx[-1] - timedelta(days=20))
    bulk = work / "bulk"
    written = norm.run(data_dir / "fhir", bulk)  # streams: the release never sits in memory as a whole
    _log(f"normalised: {written}")
    secrets = work / "secrets"
    secrets.mkdir(parents=True, exist_ok=True)
    (secrets / "site_hmac.key").write_bytes(SITE_KEY)
    lake_dir = work / "lake"

    def rebuild(snap: str, nd: Path) -> RebuildResult:
        st = Lake(lake_dir, TZ).rebuild(snap, HashEmbedder(), nd)
        return RebuildResult(
            snapshot=st.snapshot, tables=st.tables, chunks=st.chunks, embedded_new=st.embedded_new, seconds=st.seconds
        )

    cfg = AdapterConfig(
        lake_dir=lake_dir,
        secrets_dir=secrets,
        mapping_path=work / "unused-mapping.yaml",  # fhir_bulk needs no site mapping
        site_id="MIMIC-DEMO",
        tz=TZ,
        rebuild=rebuild,
        validation_max_pct=100.0,  # MIMIC is not TW Core: the structural error rate is reported, not gated
        sample_fraction=0.01,  # the adapter default (SPEC §3.1: 1 % sample)
    )
    report = run_ingest(
        cfg, "fhir_bulk", str(bulk), snapshot=SNAPSHOT, load_fhir=False, validator=StructuralValidator()
    )
    if report.errors and any("lake rebuild failed" in e for e in report.errors):
        raise RuntimeError(f"ingest failed: {report.errors}")
    _log(f"ingested snapshot {SNAPSHOT}: passed={report.passed} errors={report.errors}")
    body = dump(report)
    ingest_summary = {
        "counts": body["counts"],
        "missing_required": body.get("missing_required", {}),
        "validation": {k: body["validation"][k] for k in ("validator", "sampled", "errors", "error_pct")},
        "lake_tables": body.get("lake", {}).get("tables", {}),
        "errors": body.get("errors", []),
    }
    return Ingested(lake_dir, norm.report.as_dict(), ingest_summary)


# ---------------------------------------------------------------------------------------------- FEAS
def per_criterion(lake: Any, rs: Any, params: list[Any]) -> dict[str, dict[str, int]]:
    """Distinct patients (FEAS population) with the criterion TRUE / known (not NULL) at one or more month-ends."""
    from tb_contracts import CriterionIR

    crits: list[CriterionIR] = [c for c in rs.active() if c.class_ == "structured" and f'"C_{c.id}"' in rs.sql]
    cols = []
    for i, c in enumerate(crits):
        col = f'"C_{c.id}"'
        cols.append(f"bool_or({col} IS TRUE) AS m{i}, bool_or({col} IS NOT NULL) AS k{i}")
    sql = (
        f"WITH r AS (SELECT * FROM (\n{rs.sql}\n)),\n"
        "pop AS (SELECT DISTINCT e.pid FROM encounter e\n"
        "  WHERE CAST(e.start AS DATE) BETWEEN CAST($3 AS DATE) AND CAST($4 AS DATE))\n"
        "SELECT r.pid, " + ", ".join(cols) + " FROM r JOIN pop ON pop.pid = r.pid GROUP BY r.pid ORDER BY r.pid"
    )
    table = lake.query(sql, params, SNAPSHOT).to_pydict()
    return {
        c.id: {
            "met": sum(1 for x in table[f"m{i}"] if x),
            "known": sum(1 for x in table[f"k{i}"] if x),
            "unknown": sum(1 for x in table[f"k{i}"] if not x),
        }
        for i, c in enumerate(crits)
    }


def run_feas(lake_dir: Path, ruleset_ids: list[str]) -> dict[str, Any]:
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from orchestrator.scenarios.feas_compute import FeasParams, compute, raw_json
    from tb_common.smallcell import round_count
    from tb_common.timeutil import add_months, month_ends
    from tb_contracts import dump

    lake = LakeLocal(lake_dir, HashEmbedder(), TZ)
    idx = month_ends(RUN_DATE, LOOKBACK_MONTHS)
    params: list[Any] = [[d.isoformat() for d in idx], None, add_months(idx[0], -1).isoformat(), idx[-1].isoformat()]
    out: dict[str, Any] = {}
    for rid in ruleset_ids:
        rs = load_ruleset(RULESETS_DIR / rid)
        result, raw = compute(
            lake,
            rs,
            FeasParams(run_date=RUN_DATE, snapshot=SNAPSHOT, lookback_months=LOOKBACK_MONTHS, small_cell=SMALL_CELL),
        )
        _log(f"FEAS {rid}: start_n={raw.start_n} remaining={raw.remaining}")
        pc = per_criterion(lake, rs, params)
        by_id = rs.by_id()
        out[rid] = {
            "nct_id": rs.manifest.nct_id,
            "title": rs.manifest.title,
            "criteria": [
                {
                    "id": c.id,
                    "kind": c.kind,
                    "class": c.class_,
                    "label": c.label,
                    "applied": any(f.criterion_id == c.id and f.applied for f in result.funnel),
                }
                for c in rs.active()
            ],
            "released": dump(result),
            "per_criterion_released": {
                k: {"met": round_count(v["met"], SMALL_CELL), "unknown": round_count(v["unknown"], SMALL_CELL)}
                for k, v in pc.items()
            },
            "raw": {**json.loads(raw_json(raw)), "per_criterion": pc},
            "sql_sha256": hashlib.sha256(rs.sql.encode()).hexdigest(),
        }
        assert all(c in by_id for c in rs.manifest.criteria)
    return out


# ---------------------------------------------------------------------------------------------- invariants
def _released_ok(value: Any, threshold: int = SMALL_CELL) -> bool:
    if isinstance(value, str):
        return value == f"<{threshold}"
    return isinstance(value, int) and value >= 0 and value % threshold == 0


def check_invariants(trial: dict[str, Any], n_patients: int) -> list[str]:
    """Problems found in one trial's FEAS output (empty list = all invariants hold)."""
    problems: list[str] = []
    raw = trial["raw"]
    rel = trial["released"]
    applied = [c["id"] for c in trial["criteria"] if c["applied"] and c["kind"] in ("inclusion", "exclusion")]
    rem = [raw["remaining"][cid] for cid in applied]
    if raw["start_n"] > n_patients:
        problems.append(f"start_n {raw['start_n']} > {n_patients} patients")
    if any(r > raw["start_n"] for r in rem):
        problems.append("a funnel step exceeds start_n")
    if rem != sorted(rem, reverse=True):
        problems.append(f"funnel not monotone: {rem}")
    counts = [raw["start_n"], raw["prevalent"], *raw["remaining"].values(), *raw["unknown"].values()]
    counts += list(raw["variants"].values()) + [v for pc in raw["per_criterion"].values() for v in pc.values()]
    if any(not 0 <= n <= n_patients for n in counts):
        problems.append(f"a count is outside 0..{n_patients}")
    if raw["prevalent"] > (rem[-1] if rem else raw["start_n"]):
        problems.append("prevalent exceeds the final funnel count")
    if sum(raw["first_eligible"].values()) != (rem[-1] if rem else 0):
        problems.append("first-eligible months do not add up to the final funnel count")
    released = [rel["start_n"]]
    for f in rel["funnel"]:
        released += [f["remaining"], f["dropped"]] + ([f["unknown"]] if "unknown" in f else [])
    released += [s["remaining"] for s in rel["sensitivity"]] + [m["n"] for m in rel["monthly_new"]]
    released += [v for pc in trial["per_criterion_released"].values() for v in pc.values()]
    bad = [v for v in released if not _released_ok(v)]
    if bad:
        problems.append(f"released counts not small-cell rounded: {bad[:10]}")
    return problems


def digest(trials: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(trials, sort_keys=True, default=str).encode()).hexdigest()


# ---------------------------------------------------------------------------------------------- report
def run(data_dir: Path = DATA_DIR, repro: bool = True) -> dict[str, Any]:
    if not data_available(data_dir):
        raise FileNotFoundError(f"open data not found in {data_dir}: run `python tools/fetch_open_data.py` first")
    fetched = data_dir / "FETCHED.json"
    files = json.loads(fetched.read_text("utf-8")).get("files", {}) if fetched.exists() else {}
    runs: list[tuple[Ingested, dict[str, Any]]] = []
    for _ in range(2 if repro else 1):
        with tempfile.TemporaryDirectory(prefix="tb-open-data-") as td:
            ing = ingest(data_dir, Path(td))
            runs.append((ing, run_feas(ing.lake_dir, RULESETS)))
    ing, trials = runs[0]
    n_patients = int(ing.ingest["counts"].get("Patient", 0))
    invariants = {rid: check_invariants(t, n_patients) for rid, t in trials.items()}
    reproducible = None if not repro else digest(runs[0][1]) == digest(runs[1][1])
    return {
        "dataset": {**DATASET, "files_sha256": files},
        "run": {
            "run_date": RUN_DATE.isoformat(),
            "snapshot": SNAPSHOT,
            "lookback_months": LOOKBACK_MONTHS,
            "tz": TZ,
            "small_cell": SMALL_CELL,
        },
        "normalisation": ing.normalisation,
        "ingest": ing.ingest,
        "patients": n_patients,
        "trials": trials,
        "invariants": invariants,
        "reproducible": reproducible,
        "results_sha256": digest(trials),
        "passed": all(not v for v in invariants.values()) and reproducible is not False,
    }


def markdown(report: dict[str, Any]) -> str:
    r = report["run"]
    lines = [
        "# TrialBox open-data end-to-end (MIMIC-IV FHIR demo)",
        "",
        f"Dataset: {report['dataset']['name']} v{report['dataset']['version']} ({report['dataset']['licence']}), "
        f"{report['patients']} patients. Run date {r['run_date']}, snapshot {r['snapshot']}, "
        f"{r['lookback_months']} month-ends, small cell {r['small_cell']}.",
        "",
        f"Result: {'PASS' if report['passed'] else 'FAIL'} (reproducible: {report['reproducible']}); "
        f"results sha256 `{report['results_sha256'][:16]}`.",
        "",
        "Normalisation: "
        + ", ".join(f"{k} {v}" for k, v in report["normalisation"]["counts"].items() if not k.endswith("dropped")),
        "",
    ]
    for rid, t in report["trials"].items():
        rel = t["released"]
        raw = t["raw"]
        lines += [
            f"## {rid} ({t['nct_id']})",
            "",
            t["title"],
            "",
            f"Population (≥1 encounter in the lookback): released {rel['start_n']}, exact {raw['start_n']}.",
            "",
            "| step | criterion | class | applied | remaining (released) | remaining (exact) | met alone (exact) |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        cls = {c["id"]: c["class"] for c in t["criteria"]}
        for i, f in enumerate(rel["funnel"], start=1):
            cid = f["criterion_id"]
            exact = raw["remaining"].get(cid, "—")
            met = raw["per_criterion"].get(cid, {}).get("met", "—")
            lines.append(
                f"| {i} | {cid} {f['label']} | {cls.get(cid, '')} | {'yes' if f.get('applied') else 'no'} | "
                f"{f['remaining']} | {exact} | {met} |"
            )
        sens = ", ".join(f"{s['variant']}: {s['remaining']}" for s in rel["sensitivity"])
        lines += ["", f"Sensitivity (released): {sens}.", ""]
        if report["invariants"][rid]:
            lines += ["Invariant failures: " + "; ".join(report["invariants"][rid]), ""]
    lines += [
        "Exact counts are shown because the data are a public demo; TrialBox releases only the rounded column.",
        "",
    ]
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=1, sort_keys=True, default=str) + "\n", "utf-8")
    (out_dir / "report.md").write_text(markdown(report), "utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=DATA_DIR)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--no-repro", action="store_true", help="skip the second independent run")
    args = ap.parse_args(argv)
    try:
        report = run(args.data, repro=not args.no_repro)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    write_outputs(report, args.out)
    print(markdown(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
