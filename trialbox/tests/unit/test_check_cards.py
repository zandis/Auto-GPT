"""check_cards v2: card fixtures through the product's own SQL compiler on a tiny in-memory lake, T/F/U per fixture."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.cards import Card, Fixture

from tools.check_cards import FixtureError, check, lake, main, run_fixture

pytestmark = pytest.mark.nodb

LOINC, ICD, ATC = "http://loinc.org", "http://hl7.org/fhir/sid/icd-10", "http://www.whocc.no/atc"
VS: dict[str, Any] = {
    "VS_ALT": {"url": "urn:tb:vs:VS_ALT", "compose": {"include": [{"system": LOINC, "concept": [{"code": "1742-6"}]}]}},
    "VS_AF": {"url": "urn:tb:vs:VS_AF", "compose": {"include": [{"system": ICD, "concept": [{"code": "I48"}]}]}},
    "VS_MTX": {"url": "urn:tb:vs:VS_MTX", "compose": {"include": [{"system": ATC, "concept": [{"code": "L01BA01"}]}]}},
}  # fmt: skip
W = {"from_days": "-{{days}}", "to_days": 0, "anchor": "index"}
DAYS = {"days": {"type": "integer", "min": 1, "max": 3650, "default": 180}}
ALT = {"table": "observation", "oid": "o1", "code": "1742-6", "system": LOINC, "effective": "2026-10-01", "unit": "U/L"}
AF = {"table": "condition", "cid": "c1", "code": "I48", "system": ICD, "onset": "2026-09-01", "status": "active"}
MTX = {"table": "medication", "mid": "m1", "atc": "L01BA01", "start": "2026-09-01", "end": "2026-09-30",
       "authored": "2026-09-01", "status": "active"}  # fmt: skip


def _card(card_id: str, atom: dict[str, Any], fixtures: list[dict[str, Any]], params: Any = None) -> dict[str, Any]:
    return {
        "card_id": card_id,
        "version": "1.0.0",
        "params": DAYS if params is None else params,
        "ir_template": {"id": "CARD-EXC-01", "ruleset": "CARD", "kind": "exclusion", "class": "structured",
                        "text": {"source": card_id}, "logic": "a1", "atoms": [atom]},
        "fixtures": fixtures,
    }  # fmt: skip


# fmt: off
CARDS = [
    _card(
        "lab.alt_uln",
        {"id": "a1", "domain": "observation", "valueset": "VS_ALT", "quantifier": "latest",
         "value": {"op": ">", "ref": {"kind": "uln", "multiple": 3}}, "window": W},
        [
            {"name": "150 against its own ULN 40", "facts": [{**ALT, "value_num": 150, "ref_high": 40}], "expect": "T"},
            {"name": "100 against its own ULN 40", "facts": [{**ALT, "value_num": 100, "ref_high": 40}], "expect": "F"},
            {"name": "no reference range anywhere", "facts": [{**ALT, "value_num": 150}], "expect": "U"},
            {"name": "no result", "facts": [], "expect": "U"},
        ],
    ),
    _card(
        "dx.af",
        {"id": "a1", "domain": "condition", "valueset": "VS_AF", "quantifier": "any", "window": W},
        [
            {"name": "inside the window", "facts": [AF], "expect": "T"},
            {"name": "before the window", "facts": [{**AF, "onset": "2020-01-01"}], "expect": "F"},
            {"name": "a later index date moves it out", "facts": [AF], "index_date": "2027-06-01", "expect": "F"},
            {"name": "a wider window brings it back", "params": {"days": 365}, "facts": [AF],
             "index_date": "2027-06-01", "expect": "T"},
        ],
    ),
    _card(
        "demo.age_min",
        {"id": "a1", "domain": "demographic", "valueset": "NONE", "age": {"min": "{{years}}"}},
        [
            {"name": "adult", "facts": [{"table": "patient", "birth_date": "1970-01-01", "sex": "female"}], "expect": "T"},
            {"name": "child", "facts": [{"table": "patient", "birth_date": "2015-01-01", "sex": "female"}], "expect": "F"},
        ],
        params={"years": {"type": "integer", "min": 0, "max": 120, "default": 18}},
    ),
    _card(
        "med.mtx_cumulative",
        {"id": "a1", "domain": "medication", "valueset": "VS_MTX", "quantifier": "any", "window": W,
         "medication": {"dose": {"op": ">=", "num": 100, "unit": "mg", "basis": "cumulative"}}},
        [
            {"name": "150 mg", "facts": [{**MTX, "quantity": 150, "dose_unit": "mg", "days_supply": 30}], "expect": "T"},
            {"name": "50 mg", "facts": [{**MTX, "quantity": 50, "dose_unit": "mg", "days_supply": 30}], "expect": "F"},
            {"name": "no dose recorded", "facts": [MTX], "expect": "U"},
        ],
    ),
]
# fmt: on


@pytest.mark.parametrize("doc", CARDS, ids=[c["card_id"] for c in CARDS])
def test_every_fixture_agrees_with_the_compiler(doc: dict[str, Any]) -> None:
    rows = check(Card.model_validate(doc), VS)
    assert [(r["fixture"], r["got"]) for r in rows] == [(f["name"], f["expect"]) for f in doc["fixtures"]]
    assert {r["ok"] for r in rows} == {"yes"}


def test_a_wrong_expectation_is_a_named_disagreement() -> None:
    doc = json.loads(json.dumps(CARDS[1]))
    doc["fixtures"][0]["expect"] = "F"
    row = check(Card.model_validate(doc), VS)[0]
    assert (row["expect"], row["got"], row["ok"]) == ("F", "T", "no")


def test_a_construct_the_compiler_refuses_is_an_error_row_not_a_verdict() -> None:
    doc = json.loads(json.dumps(CARDS[3]))
    doc["ir_template"]["atoms"][0]["medication"]["route"] = ["47625008"]
    row = check(Card.model_validate(doc), VS)[0]
    assert row["got"].startswith("error: ") and "no_route_mapping" in row["got"] and row["ok"] == "no"


@pytest.mark.parametrize(
    ("fact", "msg"),
    [
        ({"table": "note", "text": "on methotrexate"}, "a note fact has no lake relation the SQL compiler reads"),
        ({"table": "lab"}, "no lake table 'lab'"),
        ({**ALT, "colour": "red"}, "observation has no column colour"),
        ({**ALT, "src_table": "x"}, "observation has no column src_table"),  # provenance is the lake's, not a fact's
    ],
)
def test_a_fact_the_lake_cannot_hold_is_refused(fact: dict[str, Any], msg: str) -> None:
    with pytest.raises(FixtureError, match=msg):
        lake([fact])


def test_a_patient_outside_the_base_cohort_is_refused() -> None:
    card = Card.model_validate(CARDS[1])
    dead = Fixture(name="x", facts=[{"table": "patient", "birth_date": "1970-01-01", "deceased": True}], expect="F")
    with pytest.raises(FixtureError, match="0 result rows for the fixture patient"):
        run_fixture(card, dead, VS)


def _tree(tmp_path: Path, cards: list[dict[str, Any]]) -> tuple[Path, Path]:
    cards_dir, vs_dir = tmp_path / "cards", tmp_path / "vs"
    vs_dir.mkdir()
    for name, doc in VS.items():
        (vs_dir / f"{name}.json").write_text(json.dumps(doc), encoding="utf-8")
    for doc in cards:
        p = cards_dir / doc["card_id"] / f"{doc['version']}.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(doc), encoding="utf-8")
    return cards_dir, vs_dir


def test_the_command_exits_by_agreement(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cards_dir, vs_dir = _tree(tmp_path / "good", CARDS)
    assert main(["--cards", str(cards_dir), "--valuesets", str(vs_dir)]) == 0
    assert "13 of 13 fixtures agree with the compiler" in capsys.readouterr().err
    bad = json.loads(json.dumps(CARDS[0]))
    bad["fixtures"][2]["expect"] = "T"
    cards_dir, vs_dir = _tree(tmp_path / "bad", [bad])
    assert main(["--cards", str(cards_dir), "--valuesets", str(vs_dir)]) == 1
    assert "3 of 4 fixtures agree" in capsys.readouterr().err
