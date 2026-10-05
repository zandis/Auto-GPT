"""Vendor build step: compile + approve a ruleset from its source document through the real pipeline and write the
approved artifacts to ``rulesets/<ID>/`` (checked in), including the synthetic equivalence test set:

* ``tests/patients.ndjson`` — FHIR resources (no notes) of the stratified sample, synthetic site A;
* ``tests/expected.json``   — CQL (HAPI) verdicts per synthetic MRN at the index date (the SQL regression oracle
  used by CPU CI, ``tests/integration/test_ruleset_expected.py``).

Requires the compose test stack (fhir-store + lake loaded with site A, test site key) — ``make up-test`` and an
adapter run. LLM: the stub (default, cassette = gold extraction) or ``--llm-url`` for a real model.

    python tools/build_rulesets.py --ruleset GZQO --doc tests/fixtures/protocols/GZQO_protocol_v3.pdf
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import tb_contracts as c
from tb_common.audit import AuditLog
from tb_common.crypto import pid_for_mrn
from tb_common.fhir import FhirEvaluator
from tb_common.llm import LlmClient
from tb_common.objstore import FsStore

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    from criteria_compiler.compile_cql.generator import CqlGenerator
    from criteria_compiler.compile_cql.translator import Translator
    from criteria_compiler.equivalence.gate import sql_evaluations, stratified_sample
    from criteria_compiler.repo import RulesetRepo
    from criteria_compiler.review import parse_review_xlsx
    from criteria_compiler.service import Compiler, CompilerDeps
    from criteria_compiler.terminology.mapper import Terminology
    from doc_parser.parser import parse
    from lake.client import LakeHttp

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ruleset", required=True)
    ap.add_argument("--doc", type=Path, required=True)
    ap.add_argument("--kind", default="trial")
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--index-date", default="2026-10-05")
    ap.add_argument("--fhir", default="http://127.0.0.1:8080/fhir")
    ap.add_argument("--lake", default="http://127.0.0.1:8013")
    ap.add_argument("--llm-url", default="", help="OpenAI-compatible endpoint; default = in-process stub")
    ap.add_argument("--key", type=Path, default=ROOT / ".cache" / "test-secrets" / "site_hmac.key")
    ap.add_argument("--synth", type=Path, default=ROOT / "tests" / "fixtures" / "synthetic_patients" / "site-a")
    ap.add_argument("--out", type=Path, default=ROOT / "rulesets")
    ap.add_argument("--approver", default="crc1@hospa.test")
    args = ap.parse_args(argv)
    index_date = date.fromisoformat(args.index_date)
    work = Path(tempfile.mkdtemp(prefix="tb-build-"))
    store = FsStore(work / "obj")
    audit = AuditLog(work / "audit")
    if args.llm_url:
        llm = LlmClient(args.llm_url, "trialbox", audit=audit)
    else:
        from fastapi.testclient import TestClient
        from llm_stub.app import app as stub

        llm = LlmClient("http://stub/v1", "trialbox-stub", audit=audit)
        llm.http = TestClient(stub)
    seed = work / "seed"
    shutil.copytree(args.out, seed, ignore=shutil.ignore_patterns(args.ruleset))
    lake = LakeHttp(args.lake)
    fhir = FhirEvaluator(args.fhir)
    deps = CompilerDeps(
        store=store,
        repo=RulesetRepo(work / "repo", seed),
        llm=llm,
        term=Terminology(),
        settings_thresholds={"equivalence_min_pct": 98.0, "tier_high_confidence": 0.75, "small_cell": 5},
        lake=lake,
        fhir=fhir,
        translator=Translator(),
        audit=audit,
        judge_model="qwen3.5-35b-a3b-q4",
    )
    comp = Compiler(deps)
    data = args.doc.read_bytes()
    store.put(f"attachments/build/{args.doc.name}", data)
    store.put("attachments/build/parsed.json", c.dump_json(parse(data, args.doc.name)).encode())
    res = comp.compile(
        c.CompileRequest(
            job_id="01JBUILD000000000000000000",
            ruleset=args.ruleset,
            parsed_doc_key="attachments/build/parsed.json",
            kind=args.kind,
            version=args.version,
            requested_by=args.approver,
            options={"index_date": args.index_date},
        )
    )
    print(
        f"compiled {args.ruleset} v{res.version}: {len(res.criteria)} criteria, equivalence "
        f"{res.tests.overall_pct}% (failing {res.tests.failing})"
    )
    assert res.review_xlsx_key is not None
    decisions, _ = parse_review_xlsx(store.get(res.review_xlsx_key))
    out = comp.approve(
        c.ApproveRequest(ruleset=args.ruleset, version=res.version, by=args.approver, decisions=decisions)
    )
    if out.status != "approved":
        print(f"approval blocked: {out.status} {out.blocking}")
        return 1
    target = args.out / args.ruleset
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(work / "repo" / args.ruleset, target)
    # synthetic equivalence test set (keyed by synthetic MRN so it does not depend on the site key)
    key = args.key.read_bytes()
    mrns = [r["mrn"] for r in csv.DictReader((args.synth / "patient.csv").open(encoding="utf-8"))]
    pid_to_mrn = {pid_for_mrn(key, m): m for m in mrns}
    from tb_common.ruleset import Ruleset

    rs = Ruleset.load(target)
    all_sql = sql_evaluations(lake, rs.sql, index_date)
    sample = stratified_sample(all_sql, f"{rs.id}|{rs.version}")
    exprs = CqlGenerator.expression_names(rs.active())
    cql = fhir.evaluate_many(rs.library, sample, index_date, exprs)
    expected: dict[str, Any] = {
        "ruleset": rs.id,
        "version": rs.version,
        "index_date": args.index_date,
        "engine": "hapi-cr 8.12 $evaluate",
        "source": "tests/fixtures/synthetic_patients/site-a (tools/make_fixtures.py defaults)",
        "patients": {pid_to_mrn[e.pid]: e.results for e in sorted(cql, key=lambda e: pid_to_mrn[e.pid])},
    }
    (target / "tests" / "expected.json").write_text(
        json.dumps(expected, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    _patients_ndjson(args.synth, key, set(sample), target / "tests" / "patients.ndjson")
    print(f"approved {out.tag}; wrote {target} (sample {len(sample)} patients)")
    return 0


def _patients_ndjson(synth: Path, key: bytes, pids: set[str], out: Path) -> None:
    from adapter.pipeline import AdapterConfig, run_ingest

    with tempfile.TemporaryDirectory() as td:
        sec = Path(td) / "sec"
        sec.mkdir()
        (sec / "site_hmac.key").write_bytes(key)
        cfg = AdapterConfig(
            lake_dir=Path(td) / "lake",
            secrets_dir=sec,
            mapping_path=ROOT / "services/adapter/mapping/tw_core/demo_his.yaml",
            site_id="DEMO-A",
        )
        run_ingest(cfg, "csv", str(synth), snapshot="2026-10-04", load_fhir=False, rebuild_lake=False, validate=False)
        lines = []
        for f in sorted((Path(td) / "lake" / "ndjson" / "2026-10-04").glob("*.ndjson")):
            if f.stem in ("DocumentReference",):
                continue
            for line in f.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                refs = json.dumps(r)
                if (r["resourceType"] == "Patient" and r["id"] in pids) or any(f"Patient/{p}" in refs for p in pids):
                    lines.append(line)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
