"""Red of lane G's P1b run (#639, 2026-11-16), D-945: "Age outside of range specified" (NCT00606840), an exclusion, was
compiled as the inclusion's range itself (min 18, max 35), so it excluded every patient inside the range.

* An exclusion whose whole logic is an age range and whose line says outside / not within / 範囲外 / 以外 is the
  range's complement, flagged. The model's own ``not(range)`` keeps its meaning through the negated-exclusion rewrite.
* An exclusion that is an age range and does not say so goes to a person; so does one bound whose line points the
  other way ("under 18" compiled as at least 18).
* A patient with no birth date answers unknown either way.

Synthetic lines; the SQL on an in-process lake.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.terminology.mapper import Terminology, ValueSets
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake
from tb_common import id_rule
from tb_contracts import BoolExpr, LlmExtractOutput

RANGE = {"domain": "demographic", "age": {"min": 18, "max": 35}, "quantifier": "all"}


def _one(text: str, logic: dict[str, Any], kind: str = "exclusion", inclusion: dict[str, Any] | None = None) -> Any:
    crit = [{"kind": kind, "class": "structured", "text": text, "logic": logic, "concept_candidates": []}]
    if inclusion is not None:
        crit.insert(0, {"kind": "inclusion", "class": "structured", "text": "Age", "logic": inclusion,
                        "concept_candidates": []})  # fmt: skip
    post = pp.postprocess("T", LlmExtractOutput.model_validate({"criteria": crit}), Terminology(), "1.0.0")
    c = post.criteria[-1]
    return c, post.warnings


# lane G's P1b run, NCT00606840: the stored ir_extract output (the integrator's root-cause review, #639); public data
P1B_INC = {"domain": "demographic", "age": {"min": 18, "max": 35}}
P1B_EXC = {"domain": "demographic", "quantifier": "all", "age": {"min": 18, "max": 35}, "derived": "egfr"}


def test_p1b_nct00606840_outside_of_range_specified_never_excludes_a_25_year_old(tmp_path: Path) -> None:
    c, _ = _one("Age outside of range specified", P1B_EXC, inclusion=P1B_INC)
    assert isinstance(c.logic, BoolExpr) and c.logic.op == "not" and "age_range_inverted" in (c.flags or [])
    got = _on_lake(tmp_path, c, [("AGED25", "2001-06-01"), ("AGED50", "1976-06-01"), ("NOBIRTH", None)])
    assert got == {"AGED25": False, "AGED50": True, "NOBIRTH": None}


def test_an_outside_range_from_nowhere_goes_to_a_person() -> None:
    c, _ = _one("Age outside of range specified", RANGE)  # no inclusion range, no numbers in the line
    assert c.class_ == "human" and "age_range_exclusion" in (c.flags or [])
    c, _ = _one("Age outside of range specified", RANGE, inclusion={"domain": "demographic", "age": {"min": 20}})
    assert c.class_ == "human"  # not the inclusion's range


@pytest.mark.parametrize(
    ("text", "logic", "inclusion"),
    [
        ("Age 18 to 35", RANGE, P1B_INC),  # the inclusion's range again, as an exclusion
        ("Adults", {"domain": "demographic", "age": {"min": 18}}, {"domain": "demographic", "age": {"min": 18}}),
    ],
)
def test_an_exclusion_that_restates_the_inclusions_age_goes_to_a_person(
    text: str, logic: dict[str, Any], inclusion: dict[str, Any]
) -> None:
    c, _ = _one(text, logic, inclusion=inclusion)
    assert c.class_ == "human" and "exclusion_restates_inclusion" in (c.flags or [])


def test_a_narrower_exclusion_under_an_inclusion_is_ordinary() -> None:
    c, _ = _one("Age over 75", {"domain": "demographic", "age": {"min": 76}},
                inclusion={"domain": "demographic", "age": {"min": 18}})  # fmt: skip
    assert c.class_ == "structured" and not c.flags


@pytest.mark.parametrize(
    "text",
    ["Age not within 18 to 35 years", "年齢が18歳から35歳の範囲外",
     "18歳以上35歳以下以外", "年齡不在18至35歲範圍內", "Age outside 18-35 years", "Ages outside the range of 18-35"],
)  # fmt: skip
def test_an_age_range_said_outside_is_its_complement(text: str) -> None:
    c, warnings = _one(text, RANGE)
    assert isinstance(c.logic, BoolExpr) and c.logic.op == "not", text
    assert "age_range_inverted" in (c.flags or []) and c.class_ == "structured"
    assert any("outside the range" in w for w in warnings)


def test_the_models_own_complement_survives_the_negated_exclusion_rewrite() -> None:
    c, _ = _one("Age outside of range specified", {"op": "not", "args": [RANGE]}, inclusion=P1B_INC)
    assert isinstance(c.logic, BoolExpr) and c.logic.op == "not"  # not(range): what the line says


@pytest.mark.parametrize(
    ("text", "logic"),
    [
        ("Aged 18 to 35", RANGE),  # an exclusion of a range that does not say outside: a person reads it
        ("Age outside of range specified", RANGE),  # outside, but the range is from nowhere
        ("Age under 18 years", {"domain": "demographic", "age": {"min": 18}}),  # "under 18" as at least 18
        ("Older than 75", {"domain": "demographic", "age": {"max": 75}}),
        ("18歳未満", {"domain": "demographic", "age": {"min": 18}}),
        # review of D-945: symbols, "75+", a line pointing both ways, and an outside word that is not about age
        ("Age ≥ 75 years", {"domain": "demographic", "age": {"max": 75}}),
        ("Age ≤ 17", {"domain": "demographic", "age": {"min": 17}}),
        ("年齢 ≦ 17歳", {"domain": "demographic", "age": {"min": 17}}),
        ("75歳≧", {"domain": "demographic", "age": {"max": 75}}),
        ("Elderly patients 75+", {"domain": "demographic", "age": {"max": 75}}),
        ("Age < 18 or > 65", {"domain": "demographic", "age": {"min": 65}}),
        ("20歳未満又は65歳超", {"domain": "demographic", "age": {"min": 65}}),
        ("Age 18-65 and not in remission", RANGE),
        ("aged 60-70 beyond first-line therapy", RANGE),
        ("Age >=18 and <=65 not in school", RANGE),
    ],
)
def test_an_age_line_that_may_exclude_the_wrong_side_goes_to_a_person(text: str, logic: dict[str, Any]) -> None:
    c, warnings = _one(text, logic)
    assert c.class_ == "human" and c.human_question, text
    assert {"age_range_exclusion", "age_direction"} & set(c.flags or []) and "needs_review" in (c.flags or [])
    assert any("wrong side" in w for w in warnings)


@pytest.mark.parametrize(
    ("text", "logic"),
    [
        ("Age under 18 years", {"domain": "demographic", "age": {"max": 17}}),
        ("Older than 75", {"domain": "demographic", "age": {"min": 76}}),
        ("Pregnant", {"domain": "demographic", "sex": "female"}),
        ("以下の条件: 18歳未満", {"domain": "demographic", "age": {"max": 17}}),  # 以下の is "the following"
        ("超音波で確認された 75歳以上", {"domain": "demographic", "age": {"min": 75}}),  # 超音波 is not above
    ],
)
def test_an_age_line_on_its_own_side_is_left_alone(text: str, logic: dict[str, Any]) -> None:
    c, _ = _one(text, logic)
    assert c.class_ == "structured" and not {"age_range_exclusion", "age_direction", "age_range_inverted"} & set(
        c.flags or []
    )


def _on_lake(tmp_path: Path, c: Any, people: list[tuple[str, str | None]]) -> dict[str, Any]:
    nd = tmp_path / "nd"
    nd.mkdir()
    pats = [{"resourceType": "Patient", "id": pid, "gender": "male", **({"birthDate": b} if b else {})}
            for pid, b in people]  # fmt: skip
    (nd / "Patient.ndjson").write_text("\n".join(json.dumps(p) for p in pats) + "\n", encoding="utf-8")
    (nd / "Observation.ndjson").write_text("", encoding="utf-8")
    id_rule.write_snapshot_record(nd)  # D-1253: a snapshot of this release
    Lake(tmp_path / "lake").rebuild("2026-10-05", HashEmbedder(), nd)
    sql = SqlGenerator("T", "1.0.0", ValueSets("T", {}, Terminology())).render([c])
    rows = LakeLocal(tmp_path / "lake", HashEmbedder()).query(sql, [[date(2026, 10, 5).isoformat()], None]).to_pylist()
    return {r["pid"]: r[f"C_{c.id}"] for r in rows}


def test_inside_outside_and_no_birth_date_on_the_lake(tmp_path: Path) -> None:
    c, _ = _one("Age outside 18 to 35 years", RANGE)
    got = _on_lake(tmp_path, c, [("IN", "2000-01-01"), ("OUT", "1950-01-01"), ("NOBIRTH", None)])
    assert got == {"IN": False, "OUT": True, "NOBIRTH": None}  # excluded outside the range only; no birth: unknown
