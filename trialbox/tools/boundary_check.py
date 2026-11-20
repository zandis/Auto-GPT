"""The ``differential`` gate (T-711, D-480; TB-PLAN-06 §7.5): the three-engine boundary table.

The table (``criteria_compiler.equivalence.boundary``) holds synthetic patients on the edges of criteria of the
shipped rulesets, each with the answer of the **Python reference** (``tb_common.derived``). This tool runs it through

* the generated **SQL** of the ruleset on an in-process lake built from the cases' FHIR resources by the ingest's
  own steps (the offset step ``adapter.instants``, flatten, the lake), and
* **CQL** on the local engine (``tools/cql_eval.py``: a JDK and ``python -m tools.cql_eval --fetch``),

and fails when any two of the three answers differ. A case on which an engine parts from the reference today is in
:data:`KNOWN` with its finding: it is reported, does not fail, and fails when it starts to agree (the line is then
removed), so the list only shrinks. A missing CQL engine fails the gate (``--no-cql`` runs the two halves that need
no JDK, as the unit job does).

    python -m tools.boundary_check                   # all three; exit 1 on a disagreement
    python -m tools.boundary_check --no-cql --json out.json
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

from criteria_compiler.equivalence import boundary  # noqa: E402
from criteria_compiler.equivalence.boundary import Answer, Case, Table  # noqa: E402
from criteria_compiler.equivalence.edge import SITE_TZ  # noqa: E402
from tb_common.ruleset import Ruleset  # noqa: E402

SNAPSHOT = "2026-10-04"  # the name of the one snapshot the table's lake holds
Answers = dict[str, Answer]  # case key -> the engine's answer

# (case key, engine) -> the finding. An engine that parts from the Python reference on a case today. Strict: a
# line whose case agrees again fails the gate, and so does a line no case uses.
#: B-1 (found by this table, 2026-11-12): ``TB_Common."Swap"`` is ``Combine(Split(s, a), b)``; the engine's Split
#: drops the empty piece before a leading separator, so a unit code that *starts* with the micro sign loses it
#: ("µmol/l" becomes "mol/l") and is not recognised. The Python reference and SQL convert the unit; CQL gives no
#: value (unknown). SQL is the engine that screens, so no patient is decided wrongly; the equivalence gate at
#: approval would report the difference for a site whose feed writes such codes. The fix is in the CQL helper
#: template and needs every ruleset's CQL and ELM recompiled and approved again: not this card.
B1 = "B-1: CQL's Swap drops a leading micro sign, so the unit is not recognised (unknown); reference and SQL convert it"
#: B-2 (found by this table, 2026-11-12): ``tb_common.derived.DOMAIN`` declares no range for height and weight, so
#: the generated SQL computes BMI as ``weight / pow(height / 100, 2)`` on a recorded height of 0: DuckDB gives
#: infinity, and "BMI >= 27" is answered **met** on an impossible value (TB-PLAN-06 §7.4: an impossible value never
#: decides). CQL divides to null and the Python reference now gives no value (``derived_unit:height``; before this
#: card it raised ZeroDivisionError). SQL is the engine that screens. The shipped rulesets use BMI as an inclusion
#: only (GZQO-INC-03): such a patient is listed, not excluded; a BMI exclusion ("BMI > 40") would exclude on it.
#: The fix is a declared range (height and weight above 0) in ``DOMAIN``, which the SQL and CQL generators apply,
#: and every ruleset's SQL, CQL and ELM compiled and approved again: its own card.
B2 = (
    "B-2: the generated SQL divides by a height of 0 (infinity): BMI >= 27 is answered met; reference and CQL: no value"
)
KNOWN: dict[tuple[str, str], str] = {
    ("GZQO/GZQO-INC-08/b-egfr-umol-micro@2026-10-05", "cql"): B1,
    ("RA-BIO/RA-BIO-INC-05/b-das-crp-ugml@2026-10-05", "cql"): B1,
    ("GZQO/GZQO-INC-03/b-bmi-height-zero@2026-10-05", "sql"): B2,
}


def rulesets() -> dict[str, Ruleset]:
    return {rid: Ruleset.load(ROOT / "rulesets" / rid) for rid in boundary.RULESETS}


def table(rs: dict[str, Ruleset] | None = None) -> Table:
    return boundary.build(rs or rulesets())


def _as_ingested(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The resources after the ingest's offset step: every instant in the site's zone (``adapter.instants``)."""
    from adapter.instants import to_site_offset

    out = copy.deepcopy(resources)
    to_site_offset(out, ZoneInfo(SITE_TZ))
    return out


def run_sql(t: Table, rs: dict[str, Ruleset]) -> Answers:
    """The generated SQL of each ruleset over one in-process lake of its cases, at each index date."""
    from criteria_compiler.equivalence.gate import sql_evaluations
    from embed_service.embedder import HashEmbedder
    from lake.store import Lake

    out: Answers = {}
    for rid in boundary.RULESETS:
        with tempfile.TemporaryDirectory(prefix="tb-boundary-") as td:
            nd = Path(td) / "ndjson"
            nd.mkdir()
            by_type: dict[str, list[str]] = {}
            for r in _as_ingested(t.resources[rid]):
                by_type.setdefault(r["resourceType"], []).append(json.dumps(r, ensure_ascii=False))
            for rtype, lines in by_type.items():
                (nd / f"{rtype}.ndjson").write_text("\n".join(lines) + "\n", encoding="utf-8")
            from tb_common import id_rule

            id_rule.write_snapshot_record(nd)  # D-1253: a snapshot of this release says its id rule
            lake = Lake(Path(td) / "lake", tz=SITE_TZ)
            lake.rebuild(SNAPSHOT, HashEmbedder(), nd)
            for index in t.index_dates(rid):
                got = {e.pid: e.results for e in sql_evaluations(cast(Any, lake), rs[rid].sql, index)}
                _collect(out, t, rid, index, got)
    return out


def run_cql(t: Table, rs: dict[str, Ruleset]) -> Answers:
    """The ruleset's CQL on the local engine over the same resources, at each index date."""
    from criteria_compiler.compile_cql.generator import CqlGenerator
    from tb_common.fhir import FhirEvaluator

    from tools import cql_eval

    out: Answers = {}
    for rid in boundary.RULESETS:
        r = rs[rid]
        res = _as_ingested(t.resources[rid])
        lines = [json.dumps(x, ensure_ascii=False) for x in res]
        lines += [json.dumps(v) for v in r.valuesets.values()] + [json.dumps(x) for x in cql_eval.libraries(r)]
        pids = sorted(x["id"] for x in res if x["resourceType"] == "Patient")
        exprs = CqlGenerator.expression_names(r.ordered())
        for index in t.index_dates(rid):
            bodies = cql_eval.run(lines, r.library, r.library_version, index, exprs, pids)
            got = {str(b["id"]): FhirEvaluator.parse(str(b["id"]), index, b, exprs).results for b in bodies}
            _collect(out, t, rid, index, got)
    return out


def _collect(out: Answers, t: Table, rid: str, index: date, got: dict[str, Any]) -> None:
    for c in t.of(rid):
        if c.index == index:
            if c.pid not in got or c.criterion not in got[c.pid]:
                raise RuntimeError(f"{c.key}: the engine gave no answer for the case")
            out[c.key] = got[c.pid][c.criterion]


def compare(t: Table, engines: dict[str, Answers], known: dict[tuple[str, str], str] | None = None) -> dict[str, Any]:
    """Every case against every engine. ``problems``: a disagreement that is not known, a known one that agrees
    again, a known line no case uses."""
    known = KNOWN if known is None else known
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    seen: set[tuple[str, str]] = set()
    for c in t.cases:
        row: dict[str, Any] = {"case": c.key, "group": c.group, "edge": c.edge, "reference": c.expected}
        for name, answers in engines.items():
            got = answers[c.key]
            row[name] = got
            why = known.get((c.key, name))
            if why is not None:
                seen.add((c.key, name))
            if got != c.expected and why is None:
                problems.append(f"{c.key} ({c.edge}): {name} says {got!r}, the reference {c.expected!r}")
            elif got == c.expected and why is not None:
                problems.append(f"{c.key}: {name} agrees with the reference again; remove its KNOWN line ({why})")
            elif why is not None:
                row.setdefault("known", {})[name] = why
        rows.append(row)
    for key in sorted(set(known) - seen):
        if key[1] in engines:
            problems.append(f"KNOWN line {key} matches no case: remove it")
    return {"cases": len(t.cases), "engines": sorted(engines), "rows": rows, "problems": problems,
            "known": sorted(f"{k[0]} [{k[1]}]: {v}" for k, v in known.items() if k in seen)}  # fmt: skip


def check(cql: bool = True) -> dict[str, Any]:
    rs = rulesets()
    t = table(rs)
    engines = {"sql": run_sql(t, rs)}
    if cql:
        engines["cql"] = run_cql(t, rs)
    return compare(t, engines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-cql", action="store_true", help="the Python reference and SQL only (no JDK)")
    ap.add_argument("--json", type=Path, help="write the full report here")
    a = ap.parse_args(argv)
    if not a.no_cql:
        from tools import cql_eval

        if not cql_eval.available():
            print("differential: the local CQL engine is not there (python -m tools.cql_eval --fetch): FAIL")
            return 1
    report = check(cql=not a.no_cql)
    if a.json:
        a.json.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    by_group: dict[str, int] = {}
    for row in report["rows"]:
        by_group[row["group"]] = by_group.get(row["group"], 0) + 1
    print(f"differential: {report['cases']} cases ({', '.join(f'{g} {n}' for g, n in sorted(by_group.items()))}); "
          f"engines: reference, {', '.join(report['engines'])}")  # fmt: skip
    for k in report["known"]:
        print(f"known: {k}")
    for p in report["problems"]:
        print(f"differential: {p}")
    print("differential: " + ("FAIL" if report["problems"] else "PASS"))
    return 1 if report["problems"] else 0


def cases() -> list[Case]:
    return table().cases


if __name__ == "__main__":
    raise SystemExit(main())
