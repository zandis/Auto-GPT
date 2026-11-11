"""The CQL path in CI (T-619a, STD-070, T-STD-11): the shipped rulesets through the pinned jars, and the edge cases.

Build-time and CI only, like ``tools/cql_eval.py``: it needs a JDK, the translator jars (``make jvm-deps``) and the
local CQL engine (``python -m tools.cql_eval --fetch``; ``TB_CQL_LOCAL_LIB`` may point at a copy). Three checks:

1. **Translate.** Each of the five rulesets with a recorded test set (``tests/patients.ndjson``) is translated with
   the pinned cql-to-elm 5.4.0 jars, with no error, and the ELM equals the committed ``cql/elm`` files.
2. **Evaluate.** The local engine (the one HAPI FHIR 8.12 runs) answers each ruleset's test set as
   ``tests/expected.json`` records; that file is the SQL engine's regression oracle too
   (``tests/integration/test_ruleset_expected.py``), so SQL and CQL agree on the equivalence fixture.
3. **Edge cases** (``criteria_compiler.equivalence.edge``): a time stamp at 23:30 UTC on a window edge and censored
   results ("<", ">"). The fixture goes through the ingest's offset step (``adapter.instants``), then into an
   in-process lake (SQL) and the local engine (CQL); the equivalence gate's ``compare`` must find no disagreement,
   and both must give the fixture's answers. Without the offset step the UTC case must still part the engines (the
   case is a real edge, not a fixture that agrees by luck).

    python -m tools.cql_path_check                    # all three; exit 1 on any failure
    python -m tools.cql_path_check --only edge --json out.json
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# the rulesets with a recorded test set (patients and verdicts); AD-MAB, NEUR-COH and RA-JAK are recorded on their own
# synthetic sites and checked by their own tests
FIVE = ("GOUT-COH", "GZQO", "ONC-OSI", "RA-BIO", "RA-COH")


def translate(rid: str) -> list[str]:
    """Problems of translating ruleset ``rid`` with the pinned jars: translator errors, or ELM unlike the committed."""
    from criteria_compiler.compile_cql.translator import TranslationError, Translator, fhirhelpers_source
    from tb_common.ruleset import Ruleset

    rs = Ruleset.load(ROOT / "rulesets" / rid)
    sources = {**rs.cql, "FHIRHelpers": fhirhelpers_source()}
    try:
        got = Translator().translate(sources)
    except TranslationError as exc:
        return [f"{rid}: {m}" for m in exc.messages[:10]]
    out = []
    for name in sorted(rs.cql):
        committed = rs.elm.get(name)
        if committed is None:
            out.append(f"{rid}: no committed ELM for {name}")
        elif json.loads(committed) != json.loads(got.elm[name]):
            out.append(
                f"{rid}: the ELM of {name} differs from the pinned translator's (python -m tools.build_rulesets)"
            )
    return out


def evaluate(rid: str) -> tuple[int, int, list[Any]]:
    from tools import cql_eval

    return cql_eval.check(rid)


def _sql(resources: list[dict[str, Any]], rs: Any, index: date, tz: str) -> list[Any]:
    from criteria_compiler.equivalence.gate import sql_evaluations
    from embed_service.embedder import HashEmbedder
    from lake.store import Lake

    with tempfile.TemporaryDirectory(prefix="tb-edge-") as td:
        nd = Path(td) / "ndjson"
        nd.mkdir()
        by_type: dict[str, list[str]] = {}
        for r in resources:
            by_type.setdefault(r["resourceType"], []).append(json.dumps(r, ensure_ascii=False))
        for rtype, lines in by_type.items():
            (nd / f"{rtype}.ndjson").write_text("\n".join(lines) + "\n", encoding="utf-8")
        lake = Lake(Path(td) / "lake", tz=tz)
        lake.rebuild("2026-10-04", HashEmbedder(), nd)
        return sql_evaluations(cast(Any, lake), rs.sql, index)  # the in-process lake answers the gate's query


def _cql(resources: list[dict[str, Any]], rs: Any, index: date, exprs: list[str]) -> list[Any]:
    from tb_common.fhir import FhirEvaluator

    from tools import cql_eval

    lines = [json.dumps(r, ensure_ascii=False) for r in resources]
    lines += [json.dumps(v) for v in rs.valuesets.values()] + [json.dumps(x) for x in cql_eval.libraries(rs)]
    pids = sorted(r["id"] for r in resources if r["resourceType"] == "Patient")
    bodies = cql_eval.run(lines, rs.library, rs.library_version, index, exprs, pids)
    return [FhirEvaluator.parse(str(b["id"]), index, b, exprs) for b in bodies]


def edge() -> dict[str, Any]:
    """Run the edge fixture through both engines, with and without the ingest's offset step."""
    from adapter.instants import to_site_offset
    from criteria_compiler.compile_cql.generator import CqlGenerator
    from criteria_compiler.equivalence import edge as fx
    from criteria_compiler.equivalence.gate import compare
    from tb_common.ruleset import Ruleset

    rs = Ruleset.load(ROOT / "rulesets" / fx.RULESET)
    crit = [c for c in rs.ordered() if c.id == fx.CRITERION]
    exprs = CqlGenerator.expression_names(rs.ordered())
    raw = fx.resources()
    site = copy.deepcopy(raw)
    shifted = to_site_offset(site, ZoneInfo(fx.SITE_TZ))
    want = fx.expected()
    out: dict[str, Any] = {"criterion": fx.CRITERION, "index_date": fx.INDEX_DATE.isoformat(), "shifted": shifted}
    for label, res in (("site_offset", site), ("as_sent", raw)):
        sql = _sql(res, rs, fx.INDEX_DATE, fx.SITE_TZ)
        cql = _cql(res, rs, fx.INDEX_DATE, exprs)
        rep = compare(crit, cql, sql, threshold_pct=100.0, engine="cqf-fhir-cql (local) vs duckdb")
        out[label] = {
            "sql": {e.pid: e.results.get(fx.CRITERION) for e in sql if e.pid in want},
            "cql": {e.pid: e.results.get(fx.CRITERION) for e in cql if e.pid in want},
            "agreement_pct": rep.per_criterion.get(fx.CRITERION),
            "failing": rep.failing,
            "disagreements": [(d.pid, d.cql, d.sql) for d in rep.disagreements or []],
        }
    site_run, sent = out["site_offset"], out["as_sent"]
    problems = []
    if site_run["failing"]:
        problems.append(f"SQL and CQL disagree on the edge fixture: {site_run['disagreements']}")
    for engine in ("sql", "cql"):
        bad = {p: (site_run[engine].get(p), v) for p, v in want.items() if site_run[engine].get(p) != v}
        if bad:
            problems.append(f"{engine} answers differ from the fixture's (got, want): {bad}")
    if sent["sql"].get("edge-utc") == sent["cql"].get("edge-utc"):
        problems.append("the UTC case agrees without the offset step: it no longer tests the edge")
    out["problems"] = problems
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", choices=("translate", "evaluate", "edge"), action="append")
    ap.add_argument("--json", type=Path, help="write the results here")
    a = ap.parse_args(argv)
    steps = a.only or ["translate", "evaluate", "edge"]
    report: dict[str, Any] = {}
    failed = False
    if "translate" in steps:
        report["translate"] = {rid: translate(rid) for rid in FIVE}
        for rid, problems in report["translate"].items():
            print(f"translate {rid}: {'ok' if not problems else '; '.join(problems)}")
            failed |= bool(problems)
    if "evaluate" in steps:
        report["evaluate"] = {}
        for rid in FIVE:
            agree, total, bad = evaluate(rid)
            report["evaluate"][rid] = {"agree": agree, "total": total, "first_differences": bad[:5]}
            print(f"evaluate {rid}: {agree}/{total} verdicts as recorded{'' if not bad else f'; {bad[:5]}'}")
            failed |= agree != total or total == 0
    if "edge" in steps:
        report["edge"] = edge()
        e = report["edge"]
        print(f"edge {e['criterion']} at {e['index_date']}: SQL {e['site_offset']['sql']}")
        print(f"edge {e['criterion']} at {e['index_date']}: CQL {e['site_offset']['cql']}")
        print(f"edge without the offset step: disagreements {e['as_sent']['disagreements']}")
        for p in e["problems"]:
            print(f"edge: {p}")
        failed |= bool(e["problems"])
    if a.json:
        a.json.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    print("CQL path: FAIL" if failed else "CQL path: PASS")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
