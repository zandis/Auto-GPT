"""Red of lane G's frozen-commit run (#639, #649, 2026-11-16): on trec2023 all 16 exclusions came from coded criteria
and 10 were wrong (D-914).

* Nine: the patients have no coded row at all (their facts are a questionnaire in a note), and a coded inclusion
  ("on a DMARD for 180 days", "any receptor status", "received trastuzumab") read FALSE, which excludes. For a
  patient with no coded record of an atom's kind at all, an excluding answer now reads unknown with the reason
  ``no_record_of_kind`` (an inclusion's FALSE a record could make TRUE; an exclusion's TRUE under "none" a record could
  make FALSE): a person looks, nobody is excluded for a record that is not there. An answer that keeps the patient
  stands (no review is added). D-795's rule (a whole site), per patient. A patient with records of that kind, none
  matching, still reads FALSE.
* The tenth: "within 3 months" compiled as a duration of at least -90 days, met by everyone, so the exclusion fired
  for all. A duration of 0 days or less, an age below 0 and a reversed age range are compile errors now, so such a
  criterion goes to a person (``demote_uncompilable``).

A missing age or sex already reads unknown (``compile_sql.generator._demographic``): checked here too. Synthetic
fixture (the off-list one: 14 patients, 4 with medication rows).
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.semantics import CompileError, kind
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from matching.cascade.engine import CascadeConfig, run_cascade
from matching.recorded import NO_RECORD, Recorded
from orchestrator.scenarios.evaluate import SqlEngine
from tb_common import id_rule
from tb_common.reasons import CODES, LABELS
from tb_common.ruleset import Ruleset
from tb_contracts import Atom, CriterionIR

from tests.offlist_fixture import FIX, SNAPSHOT, index_date, offlist_ruleset

pytestmark = [pytest.mark.guard, pytest.mark.nodb]  # D-1119: the guard step of `checks`; no database

ROOT = Path(__file__).resolve().parents[2]
WITH_MEDS = {"OFF-ULT-A", "OFF-ULT-B", "OFF-ULT-C", "OFF-ULT-D"}


def _crit(cid: str, kind_: str, logic: dict[str, Any]) -> CriterionIR:
    return CriterionIR.model_validate(
        {"id": cid, "ruleset": "OFFL", "kind": kind_, "class": "structured", "text": cid, "logic": logic}
    )


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    from lake.store import Lake

    crit, vs, vsi, expected = offlist_ruleset()
    crit = [
        *crit,
        _crit(
            "OFFL-INC-08",
            "inclusion",
            {"domain": "demographic", "valueset": "NONE", "age": {"min": 18}, "sex": "female"},
        ),
    ]
    sql = SqlGenerator("OFFL", "1.0.0", vsi).render(crit)
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    manifest = base.model_copy(update={"id": "OFFL", "library": None, "criteria": [c.id for c in crit]})
    tmp = tmp_path_factory.mktemp("no-record")
    src = tmp / "src"
    src.mkdir()
    for f in FIX.glob("*.ndjson"):
        shutil.copy(f, src / f.name)
    id_rule.write_snapshot_record(src)  # D-1253: a snapshot of this release
    Lake(tmp / "lake").rebuild(SNAPSHOT, HashEmbedder(), src)
    lake = LakeLocal(tmp / "lake", HashEmbedder())
    pids = sorted({r["pid"] for r in lake.query("SELECT pid FROM patient", None, SNAPSHOT).to_pylist()})
    meds = {r["pid"] for r in lake.query("SELECT DISTINCT pid FROM medication", None, SNAPSHOT).to_pylist()}
    return {"rs": Ruleset(manifest=manifest, criteria=crit, valuesets=vs, sql=sql), "lake": lake, "pids": pids,
            "meds": meds, "day": index_date(expected)}  # fmt: skip


def test_each_patients_kinds_of_record_are_read(world: dict[str, Any]) -> None:
    rec = Recorded.load(world["lake"], world["pids"], SNAPSHOT)
    assert world["meds"] and set(world["pids"]) - world["meds"]  # some with medication rows, some without
    for p in world["pids"]:
        assert ("medication" in rec.domains[p]) == (p in world["meds"]), p
    inc = next(c for c in world["rs"].criteria if c.id == "OFFL-INC-02")  # the urate-lowering drug inclusion
    no_meds = next(p for p in world["pids"] if p not in world["meds"])
    assert rec.doubt(inc, no_meds, False) == ["medication"] and rec.doubt(inc, no_meds, True) == []
    assert rec.doubt(inc, sorted(world["meds"])[0], False) == []  # records of the kind: FALSE stands
    assert Recorded().doubt(inc, no_meds, False) == []  # not read: no check
    exc = inc.model_copy(update={"id": "OFFL-EXC-09", "kind": "exclusion"})
    assert rec.doubt(exc, no_meds, False) == []  # an exclusion's FALSE keeps the patient: it stands, no review added


def test_the_sql_engine_never_excludes_on_a_record_that_is_not_there(world: dict[str, Any]) -> None:
    rs = world["rs"]
    got = SqlEngine(world["lake"], SNAPSHOT).evaluate(rs, world["pids"], world["day"], [c.id for c in rs.criteria])
    for pid, ev in got.items():
        if pid in world["meds"]:
            assert (ev.reasons or {}).get("OFFL-INC-02") != NO_RECORD, pid
        else:
            assert ev.results["OFFL-INC-02"] is None and (ev.reasons or {}).get("OFFL-INC-02") == NO_RECORD, pid


def test_the_cascade_sends_it_to_a_person(world: dict[str, Any]) -> None:
    rs = world["rs"]
    cfg = CascadeConfig(study_id="OFFL", run_date=world["day"], index_mode="single", population=world["pids"],
                        semantics="v1", snapshot=None)  # fmt: skip
    res = run_cascade(world["lake"], rs, cfg)
    seen = 0
    for t in res.traces.values():
        o = t.outcomes.get("OFFL-INC-02")
        if t.in_scope and o is not None and t.pid not in world["meds"]:
            assert (o.status, o.reason) == ("unknown", NO_RECORD), t.pid
            assert t.exit_criterion != "OFFL-INC-02", t.pid
            seen += 1
    assert seen


def test_a_missing_age_or_sex_reads_unknown(world: dict[str, Any]) -> None:
    rs = world["rs"]
    rows = world["lake"].query("SELECT pid, birth_date, sex FROM patient", None, SNAPSHOT).to_pylist()
    got = SqlEngine(world["lake"], SNAPSHOT).evaluate(rs, world["pids"], world["day"], ["OFFL-INC-08"])
    for r in rows:
        if r["birth_date"] is None or r["sex"] not in ("male", "female"):
            v = got[r["pid"]].results["OFFL-INC-08"]
            assert v is None or (r["sex"] == "male" and v is False), r  # only a known male makes it FALSE


@pytest.mark.parametrize(
    ("atom", "why"),
    [
        ({"domain": "medication", "valueset": "VS_X", "duration": {"min_days": -90}}, "met by everyone"),
        ({"domain": "medication", "valueset": "VS_X", "duration": {"min_days": 0}}, "met by everyone"),
        ({"domain": "demographic", "valueset": "NONE", "age": {"min": 80, "max": 18}}, "reversed"),
        ({"domain": "demographic", "valueset": "NONE", "age": {"min": -1}}, "below 0"),
    ],
)
def test_a_bound_met_by_everyone_or_no_one_is_a_compile_error(atom: dict[str, Any], why: str) -> None:
    with pytest.raises(CompileError, match=why):
        kind(Atom.model_validate(atom))


def test_the_reason_is_a_code_with_three_labels() -> None:
    assert NO_RECORD in CODES and set(LABELS[NO_RECORD]) == {"en", "ja", "zh-TW"}
    assert date(2026, 1, 1)  # (the fixture's dates are synthetic)
