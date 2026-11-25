"""INT-R1 (deep check row R1): a medication look-back read the order date only.

"Within N days" of a medication counted an order only when its order date fell in the window, so a patient whose
order was written before the window but whose supply ran into it was read as not on the medicine. Now, in the SQL and
in the CQL, a dated order also counts when its supply period, [therapy start, therapy end] as the lake reads it
(``lake.flatten`` ``therapy``: the bounds period, else the validity period, else the order date plus the expected
supply duration in days or weeks), overlaps the window. Both ends are inclusive: a supply ending on the window's first
day counts. The last covered day of a supply is its start plus its days less one. An order
before the window with no end may have run into it: unknown (ruled on #639's card INT-R1), never a silent no; an
undated order stays unknown, as before. Only bounded look-backs (a window with a first day) change.

Synthetic FHIR orders; the lake in-process; the local CQL engine where it is fetched.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.compile_cql.generator import CqlGenerator, render_common
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.semantics import Kind, atoms, compiled, kind, window
from criteria_compiler.terminology.mapper import SYSTEMS, Concept, Terminology, ValueSets, valueset
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake
from tb_common.ruleset import Ruleset
from tb_contracts import Atom, CriterionIR

ROOT = Path(__file__).resolve().parents[2]
ATC = SYSTEMS["atc"]
IDX = date(2026, 10, 5)  # the 90-day window is 2026-07-07 .. 2026-10-05


def _order(pid: str, mid: str, system: str, code: str, authored: str | None, **extra: Any) -> dict[str, Any]:
    r: dict[str, Any] = {
        "resourceType": "MedicationRequest",
        "id": mid,
        "status": "active",
        "intent": "order",
        "subject": {"reference": f"Patient/{pid}"},
        "medicationCodeableConcept": {"coding": [{"system": system, "code": code}]},
    }
    if authored:
        r["authoredOn"] = authored
    r.update(extra)
    return r


def _supply(days: float, unit: str = "d") -> dict[str, Any]:
    return {"dispenseRequest": {"expectedSupplyDuration": {"value": days, "unit": unit, "code": unit}}}


def _orders(system: str, code: str, from_days: int = -90, tag: str = "") -> list[dict[str, Any]]:
    """One order per patient case, dated from the window's first day ``lo`` (2026-07-07 for 90 days)."""
    lo = IDX + timedelta(days=from_days)

    def at(n: int) -> str:
        return (lo + timedelta(days=n)).isoformat()

    def o(pid: str, authored: str | None, **extra: Any) -> dict[str, Any]:
        return _order(pid, f"m{tag}-{pid}", system, code, authored, **extra)

    return [
        o("P-IN", at(5)),  # ordered inside the window: met, before and after
        o("P-IN-SUPPLY", at(5), **_supply(30)),
        o("P-REACH", at(-17), **_supply(30)),  # before the window, supply to lo + 13: met (was not)
        o("P-REACH-WK", at(-17), **_supply(4, "wk")),  # 4 weeks: to lo + 11
        o("P-VALIDITY", at(-67), dispenseRequest={"validityPeriod": {"start": at(-67), "end": at(25)}}),
        o(
            "P-BOUNDS",
            at(-97),
            dosageInstruction=[{"timing": {"repeat": {"boundsPeriod": {"start": at(-97), "end": at(3)}}}}],
        ),
        o("P-ENDED", at(-67), **_supply(30)),  # supply to lo - 37, before the window: not met
        o("P-NOSUPPLY", at(-17)),  # no end: it may have run into the window: unknown (the ruling)
        o("P-OPEN", at(-67), dispenseRequest={"validityPeriod": {"start": at(-67)}}),  # started, no end: unknown
        o("P-LASTDAY", IDX.isoformat()),  # ordered on the window's last day: met
        o("P-AFTER", (IDX + timedelta(days=1)).isoformat()),  # ordered the day after it: not met
        o("P-EDGE", at(-29), **_supply(30)),  # the last covered day is lo, the window's first day: met
        o("P-EDGE-1", at(-30), **_supply(30)),  # the last covered day is the day before: not met
        o("P-UNDATED", None, **_supply(30)),  # no order date and no period: unknown, as before
        o("P-UNDATED-PERIOD", None, dispenseRequest={"validityPeriod": {"start": at(-67), "end": at(25)}}),  # the same
        o("P-UNIT", at(-17), dispenseRequest={"expectedSupplyDuration": {"value": 30, "unit": " Days "}}),  # unit text
        o("P-MONTHS", at(-17), **_supply(3, "mo")),  # a unit the lake does not read: no end: unknown
    ]


PIDS = [
    "P-IN",
    "P-IN-SUPPLY",
    "P-REACH",
    "P-REACH-WK",
    "P-VALIDITY",
    "P-BOUNDS",
    "P-ENDED",
    "P-NOSUPPLY",
    "P-OPEN",
    "P-LASTDAY",
    "P-AFTER",
    "P-EDGE",
    "P-EDGE-1",
    "P-UNDATED",
    "P-UNDATED-PERIOD",
    "P-UNIT",
    "P-MONTHS",
    "P-NONE",
]
# what an "any order in the window" atom answers per patient
MET: dict[str, bool | None] = {
    "P-IN": True,
    "P-IN-SUPPLY": True,
    "P-REACH": True,
    "P-REACH-WK": True,
    "P-VALIDITY": True,
    "P-BOUNDS": True,
    "P-ENDED": False,
    "P-NOSUPPLY": None,
    "P-OPEN": None,
    "P-LASTDAY": True,
    "P-AFTER": False,
    "P-EDGE": True,
    "P-EDGE-1": False,
    "P-UNDATED": None,
    "P-UNDATED-PERIOD": None,
    "P-UNIT": True,
    "P-MONTHS": None,
    "P-NONE": False,
}
VS = {"VS_ANTICOAG": valueset("MS", "VS_ANTICOAG", "anticoagulant", [Concept(ATC, "B01AF01", "rivaroxaban")], "1.0.0")}


def _crit(cid: str, kind_: str, quantifier: str) -> CriterionIR:
    atom = {
        "domain": "medication",
        "quantifier": quantifier,
        "valueset": "VS_ANTICOAG",
        "window": {"anchor": "index", "from_days": -90, "to_days": 0},
    }
    return CriterionIR.model_validate(
        {"id": cid, "ruleset": "MS", "kind": kind_, "class": "structured", "text": cid, "logic": atom}
    )


CRIT = [_crit("MS-EXC-01", "exclusion", "any"), _crit("MS-INC-01", "inclusion", "none")]
IDS = [c.id for c in CRIT]
EXPECTED = {p: {"MS-EXC-01": m, "MS-INC-01": None if m is None else not m} for p, m in MET.items()}


def _lake(tmp: Path, orders: list[dict[str, Any]], pids: list[str]) -> tuple[LakeLocal, list[str]]:
    nd = tmp / "ndjson"
    nd.mkdir(parents=True)
    pats = [json.dumps({"resourceType": "Patient", "id": p, "birthDate": "1960-01-01", "gender": "male"}) for p in pids]
    (nd / "Patient.ndjson").write_text("\n".join(pats) + "\n", encoding="utf-8")
    (nd / "MedicationRequest.ndjson").write_text("\n".join(map(json.dumps, orders)) + "\n", encoding="utf-8")
    (nd / "Observation.ndjson").write_text("", encoding="utf-8")
    Lake(tmp / "lake").rebuild(IDX.isoformat(), HashEmbedder(), nd)
    return LakeLocal(tmp / "lake", HashEmbedder()), pats


def _sql(lake: LakeLocal, sql: str, ids: list[str]) -> dict[str, dict[str, bool | None]]:
    rows = lake.query(sql, [[IDX.isoformat()], None]).to_pylist()
    return {r["pid"]: {k[2:]: v for k, v in r.items() if k[2:] in ids and k.startswith("C_")} for r in rows}


def _cql(gen: CqlGenerator, crits: list[CriterionIR], vs: dict[str, Any], lines: list[str], pids: list[str]) -> Any:
    from criteria_compiler.compile_cql.translator import Translator, available, fhirhelpers_source
    from tb_common.fhir import FhirEvaluator, library_resource

    from tools import cql_eval

    if not (available() and cql_eval.available()):
        pytest.skip("CQL translator or local CQL engine not available (python -m tools.cql_eval --fetch)")
    cql = gen.render(crits)
    tr = Translator().translate({"FHIRHelpers": fhirhelpers_source(), "TB_Common": render_common(), gen.library: cql})
    version = next(x for x in cql.splitlines() if x.startswith("library ")).split(" version ")[1].strip().strip("'")
    libs = [
        library_resource("TB_Common", "1.0.0", render_common(), tr.elm.get("TB_Common")),
        library_resource(gen.library, version, cql, tr.elm.get(gen.library)),
    ]
    exprs = CqlGenerator.expression_names(crits)
    ids = [c.id for c in crits]
    bodies = cql_eval.run(
        [*lines, *(json.dumps(v) for v in vs.values()), *map(json.dumps, libs)], gen.library, version, IDX, exprs, pids
    )
    got = {}
    for body in bodies:
        pid = str(body.get("id"))
        got[pid] = {k: v for k, v in FhirEvaluator.parse(pid, IDX, body, exprs).results.items() if k in ids}
    return got


@pytest.fixture(scope="module")
def setup(tmp_path_factory: pytest.TempPathFactory) -> tuple[LakeLocal, list[str]]:
    lake, pats = _lake(tmp_path_factory.mktemp("med-supply"), _orders(ATC, "B01AF01"), PIDS)
    return lake, [*pats, *map(json.dumps, _orders(ATC, "B01AF01"))]


def test_the_sql_counts_a_supply_that_reaches_into_the_look_back(setup: tuple[LakeLocal, list[str]]) -> None:
    lake, _ = setup
    sql = SqlGenerator("MS", "1.0.0", ValueSets("MS", VS, Terminology())).render(CRIT)
    assert _sql(lake, sql, IDS) == EXPECTED


def test_the_cql_says_the_same(setup: tuple[LakeLocal, list[str]]) -> None:
    _, lines = setup
    gen = CqlGenerator("MS", "1.0.0", ValueSets("MS", VS, Terminology()))
    assert _cql(gen, CRIT, VS, lines, PIDS) == EXPECTED


def test_an_unbounded_medication_atom_compiles_as_before() -> None:
    """Only a look-back with a first day changes: "ever" already counts every order up to the index date."""
    atom = {"domain": "medication", "quantifier": "any", "valueset": "VS_ANTICOAG"}
    ever = CriterionIR.model_validate(
        {"id": "MS-EXC-02", "ruleset": "MS", "kind": "exclusion", "class": "structured", "text": "t", "logic": atom}
    )
    vsi = ValueSets("MS", VS, Terminology())
    assert '"end"' not in SqlGenerator("MS", "1.0.0", vsi).render([ever])
    assert "expectedSupplyDuration" not in CqlGenerator("MS", "1.0.0", vsi).render([ever])


def _lookbacks() -> list[tuple[Ruleset, list[CriterionIR]]]:
    out = []
    for d in sorted((ROOT / "rulesets").iterdir()):
        if not (d / "manifest.yaml").is_file():
            continue
        rs = Ruleset.load(d)
        crits = [
            c
            for c in rs.criteria
            if any(
                a.domain == "medication"
                and kind(a) is Kind.PRESENCE
                and a.window is not None
                and a.window.from_days is not None
                for a in atoms(c.logic)
            )
        ]
        if crits:
            out.append((rs, crits))
    return out


def test_every_shipped_medication_look_back_answers_the_same_in_both_engines(tmp_path: Path) -> None:
    """The invariant: every shipped criterion with a medication look-back, through the SQL and the CQL, on the same
    synthetic patients (one order per patient case per ValueSet the criterion names), gives the same answers."""
    found = _lookbacks()
    assert sum(len(c) for _, c in found) == 11, [c.id for _, cs in found for c in cs]
    # GZQO-EXC-11 is a note criterion: its medication logic is a proxy shown to a person, run by neither engine
    found = [(rs, compiled(crits)) for rs, crits in found if compiled(crits)]
    assert sum(len(c) for _, c in found) == 10
    for rs, crits in found:
        vsi = ValueSets(rs.id, rs.valuesets, Terminology())
        orders = []
        looks = {(a.valueset, window(a).from_days) for c in crits for a in atoms(c.logic) if a.domain == "medication"}
        assert len({v for v, _ in looks}) == len(looks), looks  # one window per ValueSet: the cases fit it
        for name, from_days in sorted(looks, key=str):
            assert from_days is not None
            system, code = vsi.codes(name)[0]
            orders += _orders(system, code, from_days, name)
        lake, pats = _lake(tmp_path / rs.id, orders, PIDS)
        ids = [c.id for c in crits]
        sql = _sql(lake, SqlGenerator(rs.id, rs.version, vsi).render(crits), ids)
        cql = _cql(CqlGenerator(rs.id, rs.version, vsi), crits, rs.valuesets, [*pats, *map(json.dumps, orders)], PIDS)
        assert sql == cql, rs.id
        for c in crits:  # a single-atom look-back: the order before the window whose supply reaches in counts
            if isinstance(c.logic, Atom):
                hit = c.logic.quantifier != "none"
                assert (
                    sql["P-REACH"][c.id] is hit
                    and sql["P-NOSUPPLY"][c.id] is None
                    and sql["P-ENDED"][c.id] is (not hit)
                ), c.id


def test_the_last_covered_day_is_start_plus_days_less_one(tmp_path: Path) -> None:
    cases = {"a": _supply(30), "b": _supply(1), "c": _supply(0), "d": _supply(2, "wk")}
    orders = [_order("P-1", k, ATC, "B01AF01", "2026-08-01", **x) for k, x in cases.items()]
    lake, _ = _lake(tmp_path, orders, ["P-1"])
    rows = lake.query('SELECT mid, "end" AS e FROM medication', []).to_pylist()
    assert {r["mid"]: str(r["e"]) for r in rows} == {
        "a": "2026-08-30",
        "b": "2026-08-01",
        "c": "2026-08-01",
        "d": "2026-08-14",
    }


DURATION: dict[str, tuple[dict[str, Any], bool | None]] = {  # ordered 2026-06-20; "at least 90 days", 180-day look-back
    "P-D90": (_supply(90), True),  # the 90th day is covered
    "P-D89": (_supply(89), False),
    "P-DB": (
        {"dosageInstruction": [{"timing": {"repeat": {"boundsPeriod": {"start": "2026-06-20", "end": "2026-09-28"}}}}]},
        True,
    ),
    "P-DBV": (
        {
            "dosageInstruction": [
                {"timing": {"repeat": {"boundsPeriod": {"start": "2026-06-20", "end": "2026-06-30"}}}}
            ],
            "dispenseRequest": {"validityPeriod": {"start": "2026-06-20", "end": "2026-09-28"}},
        },
        False,
    ),
    "P-DV": ({"dispenseRequest": {"validityPeriod": {"start": "2026-06-20", "end": "2026-09-28"}}}, True),
    "P-DO": ({}, None),  # no end: unknown (D-275)
}


def test_a_duration_reads_the_same_period_in_both_engines(tmp_path: Path) -> None:
    orders = [_order(p, f"m-{p}", ATC, "B01AF01", "2026-06-20", **x) for p, (x, _) in DURATION.items()]
    lake, pats = _lake(tmp_path, orders, list(DURATION))
    crit = CriterionIR.model_validate(
        {
            "id": "MS-INC-09",
            "ruleset": "MS",
            "kind": "inclusion",
            "class": "structured",
            "text": "t",
            "logic": {
                "domain": "medication",
                "valueset": "VS_ANTICOAG",
                "duration": {"min_days": 90, "gap_days": 30},
                "window": {"anchor": "index", "from_days": -180, "to_days": 0},
            },
        }
    )
    vsi = ValueSets("MS", VS, Terminology())
    want = {p: {"MS-INC-09": v} for p, (_, v) in DURATION.items()}
    assert _sql(lake, SqlGenerator("MS", "1.0.0", vsi).render([crit]), ["MS-INC-09"]) == want
    got = _cql(CqlGenerator("MS", "1.0.0", vsi), [crit], VS, [*pats, *map(json.dumps, orders)], list(DURATION))
    assert got == want
