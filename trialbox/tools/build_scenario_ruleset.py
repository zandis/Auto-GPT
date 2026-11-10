"""Vendor build step for a PoC scenario ruleset on its own synthetic site (T-504; the form T-503 used for AD-MAB):
compile the protocol document through the real compiler (stub model = the cassette, real CQL translator), run the
compiler's own equivalence gate with the CQL engine in process (``tools.cql_eval``, D-321) instead of a FHIR server,
approve every criterion as ``tools/build_rulesets.py`` does, and write ``rulesets/<ID>/`` with its test set:

* ``tests/expected.json`` — the CQL verdicts per synthetic chart number of the test patients (every patient of the
  scenario's archetype and the gate's stratified sample), with the SQL-to-CQL agreement per criterion. The patients'
  FHIR resources are not committed (14 MB): the site is regenerated, byte for byte, by ``tools.synth_hospital``.

    python -m tools.cql_eval --fetch                       # once: the engine's jars (Maven)
    python -m tools.build_scenario_ruleset --ruleset RA-JAK --work /tmp/tb-rajak

Synthetic data only (``tools.synth_hospital``). Nothing at a site runs this.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

REF = date(2026, 11, 1)  # the synthetic sites' reference date (tools.synth_hospital default)
INDEX = REF + timedelta(days=1)
KEY = b"trialbox-test-site-key-0123456789abcdef"
# Where CQL may answer nothing although SQL answers (and only there): the derived scores. TB_Common's "UnitOf" calls
# ReplaceMatches, and CQL engine 5.4.0 (clinical-reasoning 4.13.0, the one HAPI 8.12 runs) returns the input wrapped
# in quotes when the pattern does not match (ReplaceMatches('abc', 'x', 'y') = "'abc'"), so no unit is recognised and
# every unit-converted component is null. The generator is not this card's (D-321); the build records the gap.
ENGINE_DEFECT = (
    "CQL engine 5.4.0 ReplaceMatches returns the input in quotes when nothing matches; TB_Common UnitOf then "
    "recognises no unit and the derived score is null under CQL (D-321)"
)
KNOWN = {"RA-JAK-INC-04": ENGINE_DEFECT, "RA-JAK-EXC-11": ENGINE_DEFECT}
# ruleset -> (protocol document, kind, synth profile, site id, time zone, archetype of the scenario's patients)
SCENARIOS: dict[str, dict[str, str]] = {
    "RA-JAK": {
        "gold": "tools.synth.rajak",
        "doc": "RA-JAK_試驗計畫書_v1.pdf",
        "kind": "trial",
        "profile": "tw-ra",
        "site": "DEMO-T",
        "tz": "Asia/Taipei",
        "archetype": "rajak",
    },
}


def prepare(work: Path, profile: str, site_id: str) -> dict[str, Any]:
    """The scenario's synthetic site, ingested into a local lake (cached in ``work``)."""
    from tests.inproc_box import ingest_site
    from tools.synth_hospital import run as synth_run

    synth = work / "synth"
    if not (synth / "summary.json").exists():
        res = synth_run(synth, profile=profile, ref_date=REF)
        if not res.passed:
            raise SystemExit("synthetic site checks failed:\n" + "\n".join(res.failures))
    summary = json.loads((synth / "summary.json").read_text(encoding="utf-8"))
    site = synth / summary["sites"][0]["dir"]
    sec = work / "sec"
    sec.mkdir(parents=True, exist_ok=True)
    (sec / "site_hmac.key").write_bytes(KEY)
    snapshot = (REF - timedelta(days=1)).isoformat()
    if not (work / "lake").exists():
        ingest_site(site, work / "lake", sec, snapshot, site_id=site_id)
    states = json.loads((site / "states.json").read_text(encoding="utf-8"))
    return {"site": site, "lake_dir": work / "lake", "ndjson": work / "lake" / "ndjson" / snapshot, "states": states}


def build(rid: str, work: Path, out: Path) -> dict[str, Any]:
    import tb_contracts as c
    from criteria_compiler.compile_cql.generator import CqlGenerator
    from criteria_compiler.compile_cql.translator import Translator
    from criteria_compiler.equivalence.gate import sql_evaluations, stratified_sample
    from criteria_compiler.repo import RulesetRepo
    from criteria_compiler.review import parse_review_xlsx
    from criteria_compiler.service import Compiler, CompilerDeps
    from criteria_compiler.terminology.mapper import Terminology
    from doc_parser.parser import parse
    from embed_service.embedder import HashEmbedder
    from fastapi.testclient import TestClient
    from lake.client import LakeLocal
    from llm_stub.app import app as stub
    from tb_common.audit import AuditLog
    from tb_common.crypto import pid_for_mrn
    from tb_common.llm import LlmClient
    from tb_common.objstore import FsStore
    from tb_common.ruleset import Ruleset

    from tools import cql_eval

    sc = SCENARIOS[rid]
    site = prepare(work, sc["profile"], sc["site"])
    lake = LakeLocal(site["lake_dir"], HashEmbedder())
    fhir = cql_eval.LocalFhir(site["ndjson"])
    mrn_of = {pid_for_mrn(KEY, m): m for m in site["states"]}

    gold_mod = importlib.import_module(sc["gold"])
    gold = {p: gold_mod.expected(site["states"][m]) for p, m in mrn_of.items()
            if site["states"][m].get("archetype") == sc["archetype"]}  # fmt: skip

    def gate(criteria: list[Any], sql: str, library: str, index_date: date, seed: str) -> c.EquivalenceReport:
        """The approval gate: SQL against the planted gold of every patient of the archetype (as T-503). The CQL
        side is run after approval, on the test patients, and recorded beside it (see ``record``)."""
        got = {e.pid: e.results for e in sql_evaluations(lake, sql, index_date)}
        per: dict[str, float] = {}
        for crit in criteria:
            if crit.class_ not in ("structured", "mixed"):
                continue
            pairs = [(got[p].get(crit.id), g[crit.id]) for p, g in gold.items() if crit.id in g]
            per[crit.id] = round(100.0 * sum(a == b for a, b in pairs) / len(pairs), 2) if pairs else 100.0
        failing = sorted(k for k, v in per.items() if v < 98.0)
        return c.EquivalenceReport(
            overall_pct=round(sum(per.values()) / max(1, len(per)), 2),
            per_criterion=per,
            failing=failing,
            sample_size=len(gold),
            disagreements=[],
            engine=f"duckdb sql vs the generator's planted gold ({sc['profile']} site); CQL recorded in "
            f"tests/expected.json ({cql_eval.ENGINE})",
        )

    tmp = work / f"compile-{rid}"
    shutil.rmtree(tmp, ignore_errors=True)
    store, audit = FsStore(tmp / "obj"), AuditLog(tmp / "audit")
    llm = LlmClient("http://stub/v1", "trialbox-stub", audit=audit)
    llm.http = TestClient(stub)
    seed = tmp / "seed"
    shutil.copytree(ROOT / "rulesets", seed, ignore=shutil.ignore_patterns(rid))
    comp = Compiler(
        CompilerDeps(
            store=store,
            repo=RulesetRepo(tmp / "repo", seed),
            llm=llm,
            term=Terminology(),
            settings_thresholds={"equivalence_min_pct": 98.0, "tier_high_confidence": 0.75, "small_cell": 5},
            tz=sc["tz"],
            lake=lake,
            translator=Translator(),
            audit=audit,
            judge_model="qwen3.5-35b-a3b-q4",
            equivalence=gate,
        )
    )
    doc = ROOT / "tests" / "fixtures" / "protocols" / sc["doc"]
    store.put(f"attachments/build/{doc.name}", doc.read_bytes())
    store.put("attachments/build/parsed.json", c.dump_json(parse(doc.read_bytes(), doc.name)).encode())
    res = comp.compile(
        c.CompileRequest(
            job_id="01JBUILD000000000000000000",
            ruleset=rid,
            parsed_doc_key="attachments/build/parsed.json",
            kind=sc["kind"],  # type: ignore[arg-type]
            version="1.0.0",
            requested_by="crc1@hospa.test",
            options={"index_date": INDEX.isoformat()},
        )
    )
    print(f"compiled {rid}: {len(res.criteria)} criteria; gate {res.tests.overall_pct}% failing {res.tests.failing}")
    if res.warnings:
        print("  warnings:", res.warnings)
    assert res.review_xlsx_key is not None
    decisions, _ = parse_review_xlsx(store.get(res.review_xlsx_key))
    ok = comp.approve(c.ApproveRequest(ruleset=rid, version=res.version, by="crc1@hospa.test", decisions=decisions))
    if ok.status != "approved":
        raise SystemExit(f"approval blocked: {ok.status} {getattr(ok, 'blocking', None)}")
    target = out / rid
    labels = target / "labels.yaml"
    keep = labels.read_bytes() if labels.exists() else None  # the shipped words are not the compiler's (D-309)
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(tmp / "repo" / rid, target)
    if keep is not None:
        labels.write_bytes(keep)
    # the test patients: every patient of the scenario's archetype and the gate's stratified sample
    rs = Ruleset.load(target)
    sql = {e.pid: e.results for e in sql_evaluations(lake, rs.sql, INDEX)}
    gate = stratified_sample([c.PatientEvaluation(pid=p, index_date=INDEX, engine="sql", results=r)
                              for p, r in sql.items()], f"{rs.id}|{rs.version}")  # fmt: skip
    arch = {p for p, m in mrn_of.items() if site["states"][m].get("archetype") == sc["archetype"]}
    pids = sorted(arch | set(gate))
    exprs = CqlGenerator.expression_names(rs.active())
    fhir.load(cql_eval.libraries(rs), rs.valuesets.values())
    cql = {e.pid: e.results for e in fhir.evaluate_many(rs.library, pids, INDEX, exprs)}
    agreement = record(cql, sql, pids)
    print(f"  test patients {len(pids)}: SQL and CQL per criterion {agreement['per_criterion']}")
    expected = {
        "ruleset": rs.id,
        "version": rs.version,
        "index_date": INDEX.isoformat(),
        "engine": cql_eval.ENGINE,
        "agreement": agreement,
        "source": f"tools.synth_hospital --profile {sc['profile']} --ref-date {REF.isoformat()} (site "
        f"{site['site'].name}; its {sc['archetype']} patients and the gate's stratified sample)",
        "patients": {mrn_of[p]: cql[p] for p in pids},
    }
    (target / "tests" / "expected.json").write_text(
        json.dumps(expected, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"  wrote {target}")
    return {"pids": pids, "agreement": agreement}


def record(cql: dict[str, dict[str, Any]], sql: dict[str, dict[str, Any]], pids: list[str]) -> dict[str, Any]:
    """Per criterion, the share of test patients on which SQL and CQL give the same verdict. A difference is accepted
    only where CQL answers nothing for a derived score (the engine's ``ReplaceMatches`` defect, ``KNOWN``); any other
    difference stops the build."""
    per: dict[str, float] = {}
    other = []
    for cid in sorted({k for p in pids for k in cql[p]}):
        same = sum(cql[p].get(cid) == sql[p].get(cid) for p in pids)
        per[cid] = round(100.0 * same / len(pids), 2)
        for p in pids:
            if cql[p].get(cid) != sql[p].get(cid) and not (cid in KNOWN and cql[p].get(cid) is None):
                other.append((p, cid, cql[p].get(cid), sql[p].get(cid)))
    if other:
        raise SystemExit(f"SQL and CQL differ beyond the known engine defect: {other[:10]}")
    return {
        "patients": len(pids),
        "per_criterion": per,
        "all_equal": all(v == 100.0 for v in per.values()),
        "known_differences": {k: KNOWN[k] for k in sorted(KNOWN) if per.get(k, 100.0) < 100.0},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ruleset", required=True, choices=sorted(SCENARIOS))
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "rulesets")
    a = ap.parse_args(argv)
    os.environ["TB_TZ"] = str(SCENARIOS[a.ruleset]["tz"])  # the synthetic site's site.tz as TB_TZ (D-315)
    a.work.mkdir(parents=True, exist_ok=True)
    build(a.ruleset, a.work, a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
