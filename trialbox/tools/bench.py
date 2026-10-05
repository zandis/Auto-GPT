"""Performance bench for SPEC §11.3 (reference: x86 + one 32 GB GPU; GB10 within 2×). DECISIONS D-80.

Each task runs the real code path at a size this host can hold, then projects linearly to the §11.3 size:

* ingest — 50k patients delta / night, ≤ 2 h: CSV → mapping → NDJSON → lake (+ HL7 validator on the 1 % sample)
* feas — 300k × 36 month-ends × 25 criteria, ≤ 30 min: FEAS SQL on a lake amplified to 300k patients
* screen — 1,000 × 25 CQL + 300 × 5 note criteria, ≤ 3 h: GZQO CQL on fhir-store for every loaded patient
* microbatch — 100 × 5 time-sensitive criteria, ≤ 10 min: SCREEN pool → MICROBATCH (in process)
* nav — 500 × 15 criteria + 50 drafts + 50 bundles, ≤ 1 h: NAV RA-BIO + ONC-OSI with drafts, bundles, validator
* compile — 25-criterion protocol incl. equivalence, ≤ 20 min: GZQO protocol → IR → CQL/SQL → equivalence on HAPI

LLM time (``judge``, ``ir_extract``, ``draft_doc``) is measured with whatever endpoint ``--llm-url`` names; without
one the stub answers instantly and the report marks the LLM share as *not measured* (no GPU on the host).

    python tools/bench.py --tasks all --out bench/                    # needs `make up-test` for screen/compile
    python tools/bench.py --tasks feas,ingest --ingest-patients 20000 # CPU-only subset
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in ("libs", "services", "."):
    sys.path.insert(0, str(ROOT / p))

TARGETS: dict[str, tuple[str, float]] = {
    "ingest": ("50,000 patients (nightly delta)", 2 * 3600),
    "feas": ("300,000 patients × 36 month-ends × 25 criteria", 30 * 60),
    "screen": ("1,000 scoped × 25 CQL criteria + 300 × 5 note criteria", 3 * 3600),
    "microbatch": ("100 patients × 5 time-sensitive criteria", 10 * 60),
    "nav": ("500 patients × 15 criteria + 50 drafts + 50 bundles", 3600),
    "compile": ("25-criterion protocol incl. equivalence test", 20 * 60),
}
KEY = b"trialbox-test-site-key-0123456789abcdef"
LLM: dict[str, str] = {"url": "", "model": ""}  # --llm-url / --llm-model: a real endpoint instead of the stub


def _llm_client() -> Any:
    from tb_common.llm import LlmClient

    if LLM["url"]:
        return LlmClient(LLM["url"], LLM["model"] or "trialbox")
    from fastapi.testclient import TestClient
    from llm_stub.app import app as stub

    llm = LlmClient("http://stub/v1", "stub")
    llm.http = TestClient(stub)
    return llm


RUN = date(2026, 10, 5)


@dataclass
class Result:
    task: str
    target_size: str
    target_s: float
    measured_size: str
    measured_s: float
    projected_s: float
    passed: bool
    notes: list[str] = field(default_factory=list)


def _result(task: str, measured: str, seconds: float, factor: float, notes: list[str]) -> Result:
    size, target = TARGETS[task]
    projected = seconds * factor
    return Result(task, size, target, measured, round(seconds, 1), round(projected, 1), projected <= target, notes)


# ------------------------------------------------------------------------------------------------------------ tasks
def bench_ingest(work: Path, n: int) -> tuple[Result, Path]:
    from adapter.pipeline import AdapterConfig, run_ingest
    from adapter.validate.validator import Hl7Validator, StructuralValidator
    from embed_service.embedder import HashEmbedder
    from lake.store import Lake
    from tb_contracts import RebuildResult

    from tools.make_fixtures import write_site
    from tools.synth.generator import generate

    src = work / "site"
    write_site(generate(42, "BENCH", RUN, n, "3"), src)
    sec = work / "sec"
    sec.mkdir(parents=True, exist_ok=True)
    (sec / "site_hmac.key").write_bytes(KEY)
    lake_dir = work / "lake"

    def rebuild(snap: str, nd: Path) -> RebuildResult:
        st = Lake(lake_dir).rebuild(snap, HashEmbedder(), nd)
        return RebuildResult(
            snapshot=st.snapshot, tables=st.tables, chunks=st.chunks, embedded_new=st.embedded_new, seconds=st.seconds
        )

    cfg = AdapterConfig(
        lake_dir=lake_dir,
        secrets_dir=sec,
        mapping_path=ROOT / "services/adapter/mapping/tw_core/demo_his.yaml",
        site_id="BENCH",
        rebuild=rebuild,
    )
    validator = Hl7Validator.from_env() or StructuralValidator()
    t0 = time.perf_counter()
    rep = run_ingest(cfg, "csv", str(src), snapshot="2026-10-04", load_fhir=False, validator=validator)
    dt = time.perf_counter() - t0
    notes = [
        f"{sum(rep.counts.values()):,} resources; validator {rep.validation.validator} on {rep.validation.sampled} "
        f"sampled ({rep.validation.errors} errors)",
        "fhir-store load not included (HAPI bulk load runs in parallel with the lake rebuild in production)",
        "notes embedded with the hash embedder (bge-m3 on GPU in production)",
    ]
    import resource

    peak_gb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20
    notes.append(
        f"peak memory {peak_gb:.1f} GB at {n:,} patients (the batch is held in memory: ≈{peak_gb / n * 50_000:.0f} GB "
        "projected for 50k; reference hosts have 128 GB, or ingest in chunks with --since, D-80)"
    )
    if not rep.passed:
        notes.append(f"ingest report not passed: {(rep.errors or [])[:2]}")
    # keep only the DuckDB snapshot (FEAS amplifies it); the exports, NDJSON and parquet are not needed any more
    for d in (src, lake_dir / "ndjson", lake_dir / "parquet"):
        shutil.rmtree(d, ignore_errors=True)
    return _result("ingest", f"{n:,} patients", dt, 50_000 / n, notes), lake_dir


ID_COLS = {"pid", "eid", "oid", "cid", "mid", "prid", "rid", "did", "aid", "kid", "consid", "chunk_key"}


def amplify(lake_dir: Path, out_dir: Path, copies: int) -> int:
    """A lake snapshot with every patient copied ``copies`` times (ids suffixed), for FEAS at hospital scale."""
    import duckdb
    from lake.flatten import SCHEMAS
    from lake.store import Lake

    snap = Lake(lake_dir).current()
    assert snap
    (out_dir / "db").mkdir(parents=True, exist_ok=True)
    for sub in ("ndjson", "parquet"):
        (out_dir / sub).mkdir(exist_ok=True)
    target = out_dir / "db" / f"{snap}.duckdb"
    target.unlink(missing_ok=True)
    con = duckdb.connect(str(target))
    con.execute(f"ATTACH '{lake_dir / 'db' / f'{snap}.duckdb'}' AS src (READ_ONLY)")
    for name, cols in SCHEMAS.items():
        sel = ", ".join(f"{c} || '~' || i AS {c}" if c in ID_COLS else f'"{c}"' for c, _ in cols)
        con.execute(f"CREATE TABLE {name} AS SELECT {sel} FROM src.{name}, range({copies}) r(i)")
    con.execute("CREATE TABLE document_chunk AS SELECT * FROM src.document_chunk WHERE false")
    con.execute("CREATE TABLE lake_meta AS SELECT * FROM src.lake_meta")
    n = int(con.execute("SELECT count(*) FROM patient").fetchone()[0])  # type: ignore[index]
    con.close()
    (out_dir / "CURRENT").write_text(snap)
    return n


def bench_feas(work: Path, lake_dir: Path | None, patients: int) -> Result:
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from orchestrator.scenarios import feas_compute as fc
    from tb_common.ruleset import Ruleset

    if lake_dir is None:  # no ingest step: amplify the 600-patient fixture lake
        from tests.inproc_box import ingest_site

        sec = work / "sec-feas"
        sec.mkdir(parents=True, exist_ok=True)
        (sec / "site_hmac.key").write_bytes(KEY)
        lake_dir = work / "lake-feas"
        ingest_site(ROOT / "tests/fixtures/synthetic_patients/site-a", lake_dir, sec, "2026-10-04")
    import duckdb

    base = duckdb.connect(str(lake_dir / "db" / f"{(lake_dir / 'CURRENT').read_text().strip()}.duckdb"), True)
    have = int(base.execute("SELECT count(*) FROM patient").fetchone()[0])  # type: ignore[index]
    base.close()
    copies = max(1, math.ceil(patients / have))
    big = work / "lake-amplified"
    total = amplify(lake_dir, big, copies)
    rs = Ruleset.load(ROOT / "rulesets" / "GZQO")
    lake = LakeLocal(big, HashEmbedder())
    p = fc.FeasParams(run_date=RUN, snapshot=lake.snapshot() or "", lookback_months=36)
    t0 = time.perf_counter()
    _, raw = fc.compute(lake, rs, p)
    sim = fc.simulate(prevalent=raw.prevalent, monthly_rate=1.0, reach=0.6, accept=0.35, capacity=None)
    dt = time.perf_counter() - t0
    crit = len(rs.active())
    return _result(
        "feas",
        f"{total:,} patients × 36 month-ends × {crit} criteria",
        dt,
        (300_000 / total) * (25 / crit),
        [f"funnel start {raw.start_n:,}; simulation P50 {sim['mid']}", f"lake amplified ×{copies} from {have:,}"],
    )


def bench_screen(fhir_url: str, lake_url: str) -> Result:
    from criteria_compiler.compile_cql.generator import CqlGenerator
    from lake.client import LakeHttp
    from orchestrator.scenarios.evaluate import CqlEngine
    from tb_common.fhir import FhirEvaluator
    from tb_common.ruleset import Ruleset

    rs = Ruleset.load(ROOT / "rulesets" / "GZQO")
    pids = [r["pid"] for r in LakeHttp(lake_url).query("SELECT pid FROM patient ORDER BY pid").to_pylist()]
    eng = CqlEngine(FhirEvaluator(fhir_url))
    eng.ensure_loaded(rs)
    structured = [c.id for c in rs.active() if c.class_ == "structured"]
    t0 = time.perf_counter()
    out = eng.evaluate(rs, pids, RUN, structured)
    dt = time.perf_counter() - t0
    assert len(out) == len(pids)
    n_expr = len(CqlGenerator.expression_names([c for c in rs.active() if c.id in structured]))
    return _result(
        "screen",
        f"{len(pids):,} patients × {len(structured)} CQL criteria ({n_expr} expressions)",
        dt,
        (1000 / len(pids)) * (25 / len(structured)),
        [
            "CQL share only; the 300 × 5 note-criterion judge calls need the GPU model "
            "(measured in microbatch / nav with --llm-url)",
            f"fhir-store {fhir_url}, {FhirEvaluator(fhir_url).workers} concurrent $evaluate",
        ],
    )


def _box(work: Path) -> Any:
    from tests.inproc_box import ingest_site, make_box

    sec = work / "sec-box"
    sec.mkdir(parents=True, exist_ok=True)
    (sec / "site_hmac.key").write_bytes(KEY)
    ingest_site(ROOT / "tests/fixtures/synthetic_patients/site-a", work / "lake-box", sec, "2026-10-04")
    box = make_box(work / "box", work / "lake-box", sec, RUN)
    if LLM["url"]:  # judge / draft_doc on the real model
        from dataclasses import replace

        box.orch.services = replace(box.orch.services, llm=_llm_client())
    return box


def bench_microbatch(work: Path) -> Result:
    box = _box(work / "mb")
    box.mail("SCREEN GZQO version=1.0.0")
    box.orch.drain()
    pool = box.orch.db.pool("GZQO")
    box.orch.create(__import__("tb_contracts").JobCreate(type="MICROBATCH", ruleset="GZQO", requested_by="scheduler"))
    t0 = time.perf_counter()
    box.orch.drain()
    dt = time.perf_counter() - t0
    job = box.orch.db.find(type_="MICROBATCH")[0]
    scoped = (job.metrics.patients_scoped if job.metrics else None) or len(pool)
    return _result(
        "microbatch",
        f"{scoped} patients re-evaluated (pool {len(pool)} + first-Monday incident scope)",
        dt,
        100 / max(scoped, 1),
        [f"job {job.state}", f"note criteria judged by {LLM['url'] or 'the stub (GPU judge not measured)'}"],
    )


def bench_nav(work: Path) -> Result:
    box = _box(work / "nav")
    t0 = time.perf_counter()
    for subject, sender in (
        ("NAV RA-BIO dept=RHEU", "nurse-rheu@hospa.test"),
        ("NAV ONC-OSI dept=ONC", "nurse-onc@hospa.test"),
    ):
        box.mail(subject, sender=sender)
        box.orch.drain()
    dt = time.perf_counter() - t0
    jobs = box.orch.db.find(type_="NAV")
    scoped = sum((j.metrics.patients_scoped or 0) if j.metrics else 0 for j in jobs)
    files = [o.filename for j in jobs for o in j.outputs or []]
    drafts = sum(1 for f in files if f.startswith("draft_"))
    bundles = sum(1 for f in files if f.startswith("twpas_") and "validation" not in f)
    from adapter.validate.validator import Hl7Validator

    return _result(
        "nav",
        f"{scoped} patients, {drafts} drafts, {bundles} bundles",
        dt,
        max(500 / max(scoped, 1), 50 / max(drafts, 1), 50 / max(bundles, 1)),
        [
            f"HL7 validator: {'yes' if Hl7Validator.from_env() else 'no (structural)'}; pre-check needs fhir-store",
            f"draft_doc paragraphs and note criteria by {LLM['url'] or 'the stub (GPU model not measured)'}",
        ],
    )


def bench_compile(work: Path, fhir_url: str, lake_url: str) -> Result:
    import tb_contracts as c
    from criteria_compiler.compile_cql.translator import Translator
    from criteria_compiler.repo import RulesetRepo
    from criteria_compiler.service import Compiler, CompilerDeps
    from criteria_compiler.terminology.mapper import Terminology
    from doc_parser.parser import parse
    from lake.client import LakeHttp
    from tb_common.fhir import FhirEvaluator
    from tb_common.objstore import FsStore

    store = FsStore(work / "obj")
    llm = _llm_client()
    seed = work / "seed"
    shutil.copytree(ROOT / "rulesets", seed, ignore=shutil.ignore_patterns("GZQO"))
    comp = Compiler(
        CompilerDeps(
            store=store,
            repo=RulesetRepo(work / "repo", seed),
            llm=llm,
            term=Terminology(),
            settings_thresholds={"equivalence_min_pct": 98.0},
            lake=LakeHttp(lake_url),
            fhir=FhirEvaluator(fhir_url),
            translator=Translator(),
        )
    )
    doc = ROOT / "tests/fixtures/protocols/GZQO_protocol_v3.pdf"
    t0 = time.perf_counter()
    store.put("attachments/bench/parsed.json", c.dump_json(parse(doc.read_bytes(), doc.name)).encode())
    res = comp.compile(
        c.CompileRequest(
            job_id="01JBENCH00000000000000000",
            ruleset="GZQO",
            parsed_doc_key="attachments/bench/parsed.json",
            requested_by="bench",
            options={"index_date": RUN.isoformat()},
        )
    )
    dt = time.perf_counter() - t0
    n = len(res.criteria)
    return _result(
        "compile",
        f"{n} criteria, equivalence {res.tests.overall_pct}% on {res.tests.sample_size} patients",
        dt,
        25 / n,
        [f"ir_extract / concept_map by {LLM['url'] or 'the stub (GPU model not measured)'}"],
    )


# ------------------------------------------------------------------------------------------------------------- main
def markdown(results: list[Result], host: dict[str, Any]) -> str:
    lines = [
        f"Host: {host['machine']}, {host['cpus']} CPUs, {host['mem_gb']} GB RAM, GPU: {host['gpu']}, "
        f"LLM: {host['llm']}",
        "",
        "| task | §11.3 size | target | measured | time | projected to target size | pass |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append(
            f"| {r.task} | {r.target_size} | {r.target_s / 60:.0f} min | {r.measured_size} | {r.measured_s:.1f} s | "
            f"{r.projected_s / 60:.1f} min | {'yes' if r.passed else 'NO'} |"
        )
    lines.append("")
    lines += [f"- **{r.task}**: " + "; ".join(r.notes) for r in results if r.notes]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", default="all", help=f"comma list of {', '.join(TARGETS)} or all")
    ap.add_argument("--out", type=Path, default=ROOT / "bench")
    ap.add_argument("--ingest-patients", type=int, default=50_000)
    ap.add_argument("--feas-patients", type=int, default=300_000)
    ap.add_argument("--fhir", default="http://127.0.0.1:8080/fhir")
    ap.add_argument("--lake", default="http://127.0.0.1:8013")
    ap.add_argument("--llm-url", default="", help="real OpenAI-compatible endpoint (else the stub)")
    ap.add_argument("--llm-model", default="", help="served model name at --llm-url")
    args = ap.parse_args(argv)
    LLM.update(url=args.llm_url, model=args.llm_model)
    tasks = list(TARGETS) if args.tasks == "all" else [t.strip() for t in args.tasks.split(",")]
    work = Path(tempfile.mkdtemp(prefix="tb-bench-"))
    results: list[Result] = []
    lake_dir: Path | None = None
    try:
        for t in tasks:
            print(f"[bench] {t} …", flush=True)
            if t == "ingest":
                r, lake_dir = bench_ingest(work / "ingest", args.ingest_patients)
            elif t == "feas":
                r = bench_feas(work / "feas", lake_dir, args.feas_patients)
            elif t == "screen":
                r = bench_screen(args.fhir, args.lake)
            elif t == "microbatch":
                r = bench_microbatch(work)
            elif t == "nav":
                r = bench_nav(work)
            elif t == "compile":
                r = bench_compile(work / "compile", args.fhir, args.lake)
            else:
                raise SystemExit(f"unknown task {t}")
            results.append(r)
            print(f"[bench] {t}: {r.measured_s:.1f} s for {r.measured_size} → {r.projected_s / 60:.1f} min", flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    mem = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    host = {
        "machine": f"{platform.machine()} {platform.system()} {platform.release()}",
        "cpus": os.cpu_count(),
        "mem_gb": round(mem),
        "gpu": (shutil.which("nvidia-smi") and "nvidia-smi present") or "none",
        "llm": args.llm_url or "stub (LLM time not measured)",
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "bench_report.json").write_text(
        json.dumps({"host": host, "results": [asdict(r) for r in results]}, indent=1) + "\n", encoding="utf-8"
    )
    md = markdown(results, host)
    (args.out / "bench_report.md").write_text(md, encoding="utf-8")
    print(md)
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
