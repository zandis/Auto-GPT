"""Vendor build step: compile + approve a ruleset from its source document through the real pipeline and write the
approved artifacts to ``rulesets/<ID>/`` (checked in), including the synthetic equivalence test set:

* ``tests/patients.ndjson`` — FHIR resources (no notes) of the stratified sample, synthetic site A;
* ``tests/expected.json``   — CQL (HAPI) verdicts per synthetic MRN at the index date (the SQL regression oracle
  used by CPU CI, ``tests/integration/test_ruleset_expected.py``).

Requires the compose test stack (fhir-store + lake loaded with site A, test site key) — ``make up-test`` and an
adapter run. LLM: the stub (default, cassette = gold extraction) or ``--llm-url`` for a real model.

    python tools/build_rulesets.py --ruleset GZQO --doc tests/fixtures/protocols/GZQO_protocol_v3.pdf

Offline recompile and drift check (T-613a, D-322; no stack, no model). A shipped ruleset's ValueSets are what the
compiler's terminology step gives today for the concepts of its extraction cassette (the stub's gold extraction, the
same input the build above reads), against the terminology release the compiler resolves through
(``resolver.current_release()``). ``--recompile`` rewrites the ValueSets and everything derived from them (SQL, CQL,
ELM) and keeps the approved IR, the manifest and the recorded tests; ``--check`` (CI) fails when a committed ValueSet,
SQL or CQL file differs from that output and prints the change per ValueSet:

    python -m tools.build_rulesets --check                 # every shipped ruleset
    python -m tools.build_rulesets --recompile RA-BIO GZQO # or --recompile with no id: all of them
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, cast

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
    ap.add_argument("--ruleset")
    ap.add_argument("--doc", type=Path)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", nargs="*", metavar="ID", help="drift check of the shipped rulesets (default: all)")
    mode.add_argument("--recompile", nargs="*", metavar="ID", help="recompile shipped rulesets offline (default: all)")
    ap.add_argument("--kind", default="trial")
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--index-date", default="2026-10-05")
    ap.add_argument("--fhir", default=f"http://127.0.0.1:{os.environ.get('TB_HOST_FHIR_PORT', '8080')}/fhir")
    ap.add_argument("--lake", default=f"http://127.0.0.1:{os.environ.get('TB_HOST_LAKE_PORT', '8013')}")
    ap.add_argument("--llm-url", default="", help="OpenAI-compatible endpoint; default = in-process stub")
    ap.add_argument("--key", type=Path, default=ROOT / ".cache" / "test-secrets" / "site_hmac.key")
    ap.add_argument("--synth", type=Path, default=ROOT / "tests" / "fixtures" / "synthetic_patients" / "site-a")
    ap.add_argument("--out", type=Path, default=ROOT / "rulesets")
    ap.add_argument("--approver", default="crc1@hospa.test")
    args = ap.parse_args(argv)
    if args.check is not None or args.recompile is not None:
        ids = args.check if args.check is not None else args.recompile
        return offline(args.out, ids or shipped(args.out), write=args.recompile is not None)
    if not args.ruleset or not args.doc:
        ap.error("--ruleset and --doc are required (or --check / --recompile)")
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


CASSETTES = ROOT / "services" / "llm_stub" / "cassettes" / "ir_extract"


def shipped(rulesets_dir: Path) -> list[str]:
    """The shipped rulesets: every ``rulesets/<ID>/manifest.yaml`` (``profiles/`` holds no manifest)."""
    from tb_common.ruleset import list_rulesets

    return list_rulesets(rulesets_dir)


def _stub_concept_map(name: str, domain: str, cands: list[Any]) -> tuple[list[tuple[str, str, float]], bool]:
    """The stub's ``concept_map`` (what the build above uses when no ``--llm-url`` is given)."""
    from llm_stub.handlers import concept_map

    out = concept_map(
        {
            "concept": name,
            "domain": domain,
            "candidates": [{"code": x.code, "system": x.system, "display": x.display} for x in cands],
        }
    )
    choices = [(ch["code"], ch["system"], float(ch["confidence"])) for ch in out["choices"]]
    return choices, bool(out.get("needs_review")) or len(choices) > 1 or any(ch[2] < 0.9 for ch in choices)


def compiled_valuesets(rid: str, rs: Any, term: Any) -> dict[str, dict[str, Any]]:
    """The ValueSets the compiler gives today for the concepts of ``rid``'s extraction cassette, approved (``active``).
    Every ValueSet the committed IR names must be among them."""
    from criteria_compiler.ir_extract.postprocess import postprocess
    from criteria_compiler.semantics import atoms

    path = CASSETTES / f"{rid}.json"
    if not path.is_file():
        raise SystemExit(f"{rid}: no extraction cassette {path.relative_to(ROOT)}: it cannot be recompiled offline")
    extracted = c.LlmExtractOutput.model_validate_json(path.read_text(encoding="utf-8"))
    derived = {str(a.derived) for cr in rs.criteria for a in atoms(cr.logic) if a.derived}
    egfr = "egfr_jsn" if "egfr_jsn" in derived else "egfr"  # the site's plain-eGFR equation it was built with (D-149)
    post = postprocess(rid, extracted, term, rs.version, _stub_concept_map, egfr=egfr)
    named = {a.valueset for cr in rs.criteria for a in atoms(cr.logic)} - {"NONE"}
    missing = sorted(named - set(post.valuesets))
    if missing:
        raise SystemExit(f"{rid}: the IR names ValueSets the cassette no longer gives: {missing}")
    return {k: {**v, "status": "active"} for k, v in post.valuesets.items() if k in named}


def _codes(vs: dict[str, Any] | None) -> set[tuple[str, str]]:
    if not vs:
        return set()
    return {(inc["system"], x["code"]) for inc in vs["compose"]["include"] for x in inc.get("concept", [])}


def _families(vs: dict[str, Any] | None) -> list[str]:
    return [str(e.get("valueString")) for e in (vs or {}).get("extension") or []]


def vs_changes(old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]]) -> list[str]:
    """One line per ValueSet that differs: codes before and after, codes added and removed, the families."""
    out = []
    for name in sorted(set(old) | set(new)):
        a, b = old.get(name), new.get(name)
        if a == b:
            continue
        ca, cb = _codes(a), _codes(b)
        added, removed = sorted(cb - ca), sorted(ca - cb)
        line = f"{name}: {len(ca)} -> {len(cb)} codes (+{len(added)} -{len(removed)})"
        if a is None or b is None:
            line += " (new)" if a is None else " (no longer compiled)"
        fa, fb = _families(a), _families(b)
        if fa != fb:
            line += f"; families {', '.join(fa) or 'none'} -> {', '.join(x.split('|')[-1] for x in fb) or 'none'}"
        if not added and not removed and fa == fb:
            line += "; same codes, other displays or metadata"
        if removed:
            line += f"; removed {', '.join(code for _, code in removed[:10])}"
        out.append(line)
    return out


def offline(rulesets_dir: Path, ids: list[str], write: bool) -> int:
    """``--check`` (``write`` False) or ``--recompile``: see the module docstring."""
    from criteria_compiler.compile_cql.translator import Translator
    from criteria_compiler.review import json_bytes
    from criteria_compiler.service import Compiler, CompilerDeps
    from criteria_compiler.terminology import resolver
    from tb_common.ruleset import Ruleset

    term = resolver.terminology()
    deps = CompilerDeps(
        store=cast(Any, None),
        repo=cast(Any, None),
        llm=cast(Any, None),
        term=term,
        settings_thresholds={},
        translator=Translator() if write else None,
    )
    comp = Compiler(deps)
    print(f"terminology release {term.release}")
    drift = 0
    for rid in ids:
        target = rulesets_dir / rid
        rs = Ruleset.load(target)
        vs = compiled_valuesets(rid, rs, term)
        scopes = c.dump(rs.manifest).get("scopes") or {}
        lookback = int((scopes.get("feas") or {}).get("lookback_months") or 36)
        art = comp.build_artifacts(rid, rs.version, rs.ordered(), vs, lookback)
        files: dict[str, bytes] = {f"valuesets/{n}.json": json_bytes(v) for n, v in vs.items()}
        files[f"sql/{rid}.sql"] = art.sql.encode("utf-8")
        files.update({f"cql/{n}.cql": t.encode("utf-8") for n, t in art.cql.items()})
        if write:
            files.update({f"cql/elm/{n}.json": t.encode("utf-8") for n, t in art.elm.items() if n != "FHIRHelpers"})
        have = {
            p.relative_to(target).as_posix(): p.read_bytes()
            for sub in ("valuesets", "sql", "cql")
            for p in (target / sub).rglob("*")
            if p.is_file() and (write or not p.relative_to(target).as_posix().startswith("cql/elm/"))
        }
        changed = sorted(p for p in set(files) | set(have) if files.get(p) != have.get(p))
        lines = vs_changes(dict(rs.valuesets), vs)
        if not changed:
            print(f"{rid}: equal to the compiler's output")
            continue
        drift += 1
        print(f"{rid}: {len(changed)} file(s) differ from the compiler's output: {', '.join(changed)}")
        print("\n".join(f"  {ln}" for ln in lines))
        if write:
            for p in changed:
                dest = target / p
                if p in files:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(files[p])
                else:
                    dest.unlink()
            print(f"  rewrote {rid}")
    if drift and not write:
        print(
            f"{drift} shipped ruleset(s) drifted from the compiler: run `python -m tools.build_rulesets --recompile` "
            "(then check tests/expected.json and the goldens)"
        )
        return 1
    return 0


def _patients_ndjson(synth: Path, key: bytes, pids: set[str], out: Path) -> None:
    from adapter.pipeline import AdapterConfig, run_ingest

    from tools import pglocal

    with tempfile.TemporaryDirectory() as td:
        sec = Path(td) / "sec"
        sec.mkdir()
        (sec / "site_hmac.key").write_bytes(key)
        cfg = AdapterConfig(
            lake_dir=Path(td) / "lake",
            secrets_dir=sec,
            mapping_path=ROOT / "services/adapter/mapping/tw_core/demo_his.yaml",
            site_id="DEMO-A",
            db_url=pglocal.for_work(Path(td)),  # the pid map: TB_DB_URL, or a throwaway local database
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
