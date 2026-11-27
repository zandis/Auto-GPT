"""The card-protocol bench step (fallback form): instances of the cards that compile today become criteria, the rest
are refused with a reason code, and a line compiles only when every card on it does."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tb_contracts.criterion_ir import CriterionIRv3

from bench.invest_j4.instantiate import ALIASES, SET29, Uncompiled, instantiate
from bench.invest_j4.run import run

pytestmark = pytest.mark.nodb


def _inst(card: str, params: dict[str, Any], side: str = "inclusion") -> tuple[CriterionIRv3 | None, str]:
    return instantiate("J4-T", 1, side, "synthetic line", card, params, "0.1.0")


def test_the_set_is_the_29_graded_cards() -> None:
    assert len(SET29) == 29
    assert set(ALIASES.values()) <= SET29


def test_age_bounds_are_whole_years() -> None:
    c, how = _inst(
        "F01.age", {"min_age_years": 18, "lower_exclusive": True, "max_age_years": 75, "upper_exclusive": True}
    )
    assert c is not None and how == "coded"
    age = c.atoms[0].age
    assert age is not None and age.min == 19 and age.max == 74
    assert c.card_ref is not None and c.card_ref.card_id == "card.demo.age"


def test_sex_any_is_vacuous_and_an_exclusion_direction_is_refused() -> None:
    assert _inst("demo.sex", {"sex": "any"}) == (None, "vacuous")
    with pytest.raises(Uncompiled) as e:
        _inst("F01.sex", {"sex_allowed": "male"}, "exclusion")
    assert e.value.code == "param_unmapped"


@pytest.mark.parametrize(
    ("card", "params", "code"),
    [
        ("med.washout", {}, "card_outside_29"),
        ("lab.renal", {"equation": "mdrd4", "op": "<", "value": 40}, "calculator_missing"),
        ("lab.renal", {"op": "<", "value": 30, "invented": 1}, "param_unmapped"),
        ("cardiac.events", {"events": ["mi", "pci"]}, "valueset_missing"),
        ("hx.malignancy", {"exceptions": ["cervix_cis"]}, "param_unmapped"),
        ("proc.surgery", {}, "valueset_missing"),
    ],
)
def test_refusals_carry_a_reason_code(card: str, params: dict[str, Any], code: str) -> None:
    with pytest.raises(Uncompiled) as e:
        _inst(card, params, "exclusion")
    assert e.value.code == code


def test_a_line_compiles_only_when_every_card_on_it_does(tmp_path: Path) -> None:
    def rec(line: int, side: str, cards: list[dict[str, Any]]) -> dict[str, Any]:
        return {"nct": "NCT00000001", "line": line, "side": side, "text": f"line {line}",
                "proposal": {"cards": cards}}  # fmt: skip

    recs = [
        rec(1, "inclusion", [{"card": "F01.age", "params": {"min_age_years": 18}}]),
        rec(2, "exclusion", [{"card": "gout.diagnosis", "params": {"criteria_set": "x"}}, {"card": "med.washout", "params": {}}]),
        rec(3, "exclusion", []),
        rec(4, "exclusion", [{"card": "human.other-trial", "params": {}}]),
    ]  # fmt: skip
    src = tmp_path / "p.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in recs), "utf-8")
    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / "demo.age.yaml").write_text("version: 0.1.0\n", "utf-8")
    out = tmp_path / "out"
    run(src, cards, out)
    status = {r.split("\t")[1]: r.split("\t")[4] for r in (out / "lines.tsv").read_text("utf-8").splitlines()[1:]}
    assert status == {"1": "ok", "2": "uncompiled_construct", "3": "no_card", "4": "ok"}
    rows = [json.loads(x) for x in (out / "trial_stage.jsonl").read_text("utf-8").splitlines()]
    assert {r["stage"] for r in rows} == {"instantiate", "compile_sql", "compile_cql"}
    assert {r["reason_code"] for r in rows if r["status"] != "ok"} == {"card_outside_29", "no_card"}
    sql = next((out / "rulesets" / "J4-NCT00000001" / "sql").glob("*.sql")).read_text("utf-8")
    assert "J4-NCT00000001-INC-001" in sql and "J4-NCT00000001-EXC-002" not in sql
