"""IR 3.1.0 (RULES-ARCH §2.2, R3 tier): card_ref outside the canonical hash, on_hit, Window.unit; all additive."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from tb_contracts.criterion_ir import (
    IR_VERSION,
    SCHEMA_DIR,
    CriterionIRv3,
    CriterionLibraryRecord,
    NotV1Expressible,
    canonical_hash,
    downgrade_to_v1,
    normalise,
    upgrade_v1,
    uses_3_1,
)

ROOT = Path(__file__).resolve().parents[2]
IR_FILES = sorted((ROOT / "rulesets").glob("*/ir/*.json"))
CARD = {"card_id": "lab.liver.alt_uln", "card_version": "1.0.0", "params": {"multiple": 3, "window_days": 180}}


def _base() -> dict[str, Any]:
    """A v1-expressible ALT criterion (3.0.0)."""
    return {
        "id": "SYN-EXC-01",
        "ruleset": "SYN/v1.0.0",
        "kind": "exclusion",
        "class": "structured",
        "text": {"source": "ALT > 120 U/L in the last 180 days"},
        "logic": "a1",
        "atoms": [
            {
                "id": "a1",
                "domain": "observation",
                "valueset": "VS_ALT",
                "quantifier": "latest",
                "value": {"op": ">", "num": 120, "unit": "U/L"},
                "window": {"from_days": -180, "to_days": 0, "anchor": "index"},
            }
        ],
    }


def _v31(**edits: Any) -> dict[str, Any]:
    d = _base()
    d["ir_version"] = "3.1.0"
    d.update(edits)
    return d


def test_version_constant_and_default() -> None:
    assert IR_VERSION == "3.1.0"
    assert CriterionIRv3.model_validate(_base()).ir_version == "3.0.0"  # a criterion without 3.1 stays 3.0.0
    assert CriterionIRv3.model_validate(_v31()).ir_version == "3.1.0"


def test_card_ref_is_outside_the_canonical_hash() -> None:
    plain = CriterionIRv3.model_validate(_base())
    carded = CriterionIRv3.model_validate(_v31(card_ref=CARD))
    assert carded.card_ref is not None and carded.card_ref.params == {"multiple": 3, "window_days": 180}
    assert "card_ref" not in normalise(carded) and normalise(carded)["ir_version"] == "3.0.0"
    assert canonical_hash(carded) == canonical_hash(plain)
    reversioned = _v31(card_ref={**CARD, "card_version": "1.1.0", "params": {"multiple": 3, "window_days": 180.0}})
    assert canonical_hash(CriterionIRv3.model_validate(reversioned)) == canonical_hash(plain)
    moved = _v31(card_ref=CARD)
    moved["atoms"][0]["value"]["num"] = 121
    assert canonical_hash(CriterionIRv3.model_validate(moved)) != canonical_hash(plain)  # the atoms still count


def test_on_hit_and_window_unit_enter_the_hash_unless_they_are_the_default() -> None:
    plain = canonical_hash(CriterionIRv3.model_validate(_base()))
    review = _v31()
    review["atoms"][0]["on_hit"] = "review"
    hours = _v31()
    hours["atoms"][0]["window"]["unit"] = "h"
    hashes = {canonical_hash(CriterionIRv3.model_validate(d)) for d in (review, hours)}
    assert len(hashes) == 2 and plain not in hashes
    assert normalise(CriterionIRv3.model_validate(review))["ir_version"] == "3.1.0"
    explicit = _v31()
    explicit["atoms"][0]["on_hit"] = "exclude"
    explicit["atoms"][0]["window"]["unit"] = "d"
    assert canonical_hash(CriterionIRv3.model_validate(explicit)) == plain


def test_3_1_constructs_need_the_3_1_version() -> None:
    on_hit = _base()
    on_hit["atoms"][0]["on_hit"] = "review"
    unit = _base()
    unit["atoms"][0]["window"]["unit"] = "h"
    for doc in ({**_base(), "card_ref": CARD}, on_hit, unit, {**_base(), "ir_version": "3.0.0", "card_ref": CARD}):
        with pytest.raises(ValidationError, match="need ir_version 3.1.0"):
            CriterionIRv3.model_validate(doc)
    for doc, bad in (
        (_v31(card_ref={**CARD, "card_version": "1.0"}), "card_version"),
        (_v31(card_ref={**CARD, "card_id": ""}), "card_id"),
        (_v31(card_ref={**CARD, "extra": 1}), "extra"),
        (_v31(ir_version="3.2.0"), "ir_version"),
    ):
        with pytest.raises(ValidationError, match=bad):
            CriterionIRv3.model_validate(doc)
    bad_hit = _v31()
    bad_hit["atoms"][0]["on_hit"] = "flag"
    bad_unit = _v31()
    bad_unit["atoms"][0]["window"]["unit"] = "w"
    for doc in (bad_hit, bad_unit):
        with pytest.raises(ValidationError):
            CriterionIRv3.model_validate(doc)


def test_uses_3_1_finds_every_construct() -> None:
    d = _v31(card_ref=CARD)
    d["atoms"][0]["on_hit"] = "review"
    d["atoms"].append(
        {
            "id": "cr",
            "domain": "observation",
            "valueset": "VS_CREAT",
            "change": {"kind": "ratio", "op": ">=", "num": 2,
                       "baseline": {"pick": "min", "window": {"from_days": -48, "to_days": 0, "unit": "h"}}},
        }
    )  # fmt: skip
    d["logic"] = {"op": "or", "args": ["a1", "cr"]}
    ir = CriterionIRv3.model_validate(d)
    assert uses_3_1(ir.model_dump(mode="json", by_alias=True, exclude_none=True)) == [
        "card_ref", "a1.on_hit", "cr.window.unit"
    ]  # fmt: skip
    assert uses_3_1(CriterionIRv3.model_validate(_base()).model_dump(mode="json", exclude_none=True)) == []


def test_downgrade_refuses_each_3_1_construct() -> None:
    assert downgrade_to_v1(CriterionIRv3.model_validate(_v31())) == downgrade_to_v1(
        CriterionIRv3.model_validate(_base())
    )  # a 3.1.0 label alone has a v1 form
    on_hit = _v31()
    on_hit["atoms"][0]["on_hit"] = "review"
    unit = _v31()
    unit["atoms"][0]["window"]["unit"] = "h"
    for doc, what in ((_v31(card_ref=CARD), "card_ref"), (on_hit, "on_hit"), (unit, "unit")):
        with pytest.raises(NotV1Expressible, match=what):
            downgrade_to_v1(CriterionIRv3.model_validate(doc))


@pytest.mark.parametrize("path", IR_FILES, ids=lambda p: f"{p.parent.parent.name}-{p.stem}")
def test_every_live_criterion_hashes_as_3_0_0(path: Path) -> None:
    v3 = upgrade_v1(json.loads(path.read_text("utf-8")))
    assert v3.ir_version == "3.0.0" and normalise(v3)["ir_version"] == "3.0.0"
    as_31 = v3.model_copy(update={"ir_version": "3.1.0"})
    assert canonical_hash(as_31) == canonical_hash(v3)


def test_schemas_carry_the_3_1_constructs() -> None:
    crit = Draft202012Validator(json.loads((SCHEMA_DIR / "criterion_ir.schema.json").read_text("utf-8")))
    doc = _v31(card_ref=CARD)
    doc["atoms"][0].update(on_hit="review")
    doc["atoms"][0]["window"]["unit"] = "h"
    assert not list(crit.iter_errors(doc))
    bad = copy.deepcopy(doc)
    bad["card_ref"]["card_version"] = "v1"
    assert list(crit.iter_errors(bad))
    ir = CriterionIRv3.model_validate(doc)
    rec = CriterionLibraryRecord.model_validate(
        {
            "lib_id": "cl_01JB7AAAAAAAAAAAAAAAAAAAAA",
            "canonical_hash": canonical_hash(ir),
            "kind": "exclusion",
            "class": "structured",
            "ir": ir,
            "seed_source": "site",
        }
    )
    lib = Draft202012Validator(json.loads((SCHEMA_DIR / "criterion_library_record.schema.json").read_text("utf-8")))
    assert not list(lib.iter_errors(rec.model_dump(mode="json", by_alias=True, exclude_none=True)))


# ------------------------------------------------------------------ 3.1 additions: anchors, anchor_text, bounds, subject
NEW_ANCHORS = ("enrollment", "consent", "first_dose", "last_dose", "end_of_study")
BOUNDS = {"lo": 10, "lo_incl": True, "hi": 20, "hi_incl": False, "unit": "U/L"}
ADDITIONS = ("subject", "anchor_text", "bounds", *NEW_ANCHORS)
USED = {"subject": "a1.subject", "anchor_text": "a1.window.anchor_text", "bounds": "a1.value.bounds"}


def _with(base: dict[str, Any], what: str) -> dict[str, Any]:
    """``base`` with one 3.1 addition on its atom."""
    d = copy.deepcopy(base)
    a = d["atoms"][0]
    if what == "subject":
        a["subject"] = "parent"
    elif what == "anchor_text":
        a["window"]["anchor_text"] = "start of the run-in period"
    elif what == "bounds":
        a["value"] = dict(BOUNDS)
    else:
        a["window"]["anchor"] = what
    return d


@pytest.mark.parametrize("what", ADDITIONS)
def test_each_addition_needs_3_1_and_is_listed(what: str) -> None:
    with pytest.raises(ValidationError, match="need ir_version 3.1.0"):
        CriterionIRv3.model_validate(_with(_base(), what))
    ir = CriterionIRv3.model_validate(_with(_v31(), what))
    assert uses_3_1(ir.model_dump(mode="json", by_alias=True, exclude_none=True)) == [
        USED.get(what, "a1.window.anchor")
    ]


def test_bounds_inside_value_if_count_as_3_1() -> None:
    d = _v31()
    d["atoms"].append({"id": "af", "domain": "condition", "valueset": "VS_AF"})
    d["atoms"][0]["value_if"] = [{"if_atom": "af", "value": dict(BOUNDS)}]
    d["logic"] = {"op": "and", "args": ["a1", "af"]}
    ir = CriterionIRv3.model_validate(d)
    assert uses_3_1(ir.model_dump(mode="json", by_alias=True, exclude_none=True)) == ["a1.value.bounds"]


def test_additions_and_the_hash() -> None:
    plain = canonical_hash(CriterionIRv3.model_validate(_base()))
    patient = _v31()
    patient["atoms"][0]["subject"] = "patient"
    assert canonical_hash(CriterionIRv3.model_validate(patient)) == plain  # the default written out
    assert normalise(CriterionIRv3.model_validate(patient))["ir_version"] == "3.0.0"
    hashes = {w: canonical_hash(CriterionIRv3.model_validate(_with(_v31(), w))) for w in ADDITIONS}
    assert plain not in hashes.values() and len(set(hashes.values())) == len(ADDITIONS)
    other = _with(_v31(), "anchor_text")
    other["atoms"][0]["window"]["anchor_text"] = "end of the run-in period"
    assert canonical_hash(CriterionIRv3.model_validate(other)) != hashes["anchor_text"]  # anchor_text is semantic
    between = _v31()
    between["atoms"][0]["value"] = {"op": "between", "num": 10, "num2": 20, "unit": "U/L"}
    assert canonical_hash(CriterionIRv3.model_validate(between)) != hashes["bounds"]


@pytest.mark.parametrize(
    ("value", "msg"),
    [
        ({"lo": 1}, "`lo` and `lo_incl` come together"),
        ({"lo_incl": True}, "`lo` and `lo_incl` come together"),
        ({"hi": 1}, "`hi` and `hi_incl` come together"),
        ({"hi_incl": False}, "`hi` and `hi_incl` come together"),
        ({"lo": 1, "lo_incl": True, "op": ">"}, "a bounded value has no op"),
        ({"hi": 1, "hi_incl": True, "num": 1}, "a bounded value has no num"),
        ({"hi": 1, "hi_incl": True, "num2": 1}, "a bounded value has no num2"),
        ({"lo": 1, "lo_incl": True, "codes": ["x"]}, "a bounded value has no codes"),
        ({"lo": 1, "lo_incl": True, "ref": {"kind": "uln", "multiple": 2}}, "a bounded value has no ref"),
        ({"lo": float("inf"), "lo_incl": True}, "bounds must be finite"),
        ({"lo": 3, "lo_incl": True, "hi": 2, "hi_incl": True}, "lo 3 is above hi 2"),
        ({"lo": 2, "lo_incl": True, "hi": 2, "hi_incl": False}, "the interval is empty"),
        ({"lo": 2, "lo_incl": False, "hi": 2, "hi_incl": True}, "the interval is empty"),
    ],
)
def test_bounded_value_rejections(value: dict[str, Any], msg: str) -> None:
    d = _v31()
    d["atoms"][0]["value"] = value
    with pytest.raises(ValidationError, match=msg):
        CriterionIRv3.model_validate(d)


@pytest.mark.parametrize(
    "value",
    [
        {"lo": 10, "lo_incl": True, "hi": 20, "hi_incl": True},
        {"lo": 10, "lo_incl": False, "hi": 20, "hi_incl": True},
        {"lo": 2, "lo_incl": True, "hi": 2, "hi_incl": True},
        {"hi": 20, "hi_incl": False, "unit": "U/L"},
        {"lo": 10, "lo_incl": True},
    ],
)
def test_bounded_value_accepted(value: dict[str, Any]) -> None:
    d = _v31()
    d["atoms"][0]["value"] = value
    assert CriterionIRv3.model_validate(d).atoms[0].value is not None


@pytest.mark.parametrize(
    ("what", "msg"),
    [
        ("subject", "atom a1: subject have no v1 form"),
        ("anchor_text", "atom a1: window.anchor_text has no v1 form"),
        ("bounds", "atom a1: value.hi, value.hi_incl, value.lo, value.lo_incl have no v1 form"),
        *((a, f"atom a1: window anchor {a} has no v1 form") for a in NEW_ANCHORS),
    ],
)
def test_downgrade_names_each_addition(what: str, msg: str) -> None:
    with pytest.raises(NotV1Expressible, match=msg):
        downgrade_to_v1(CriterionIRv3.model_validate(_with(_v31(), what)))


def test_schema_carries_the_additions() -> None:
    crit = Draft202012Validator(json.loads((SCHEMA_DIR / "criterion_ir.schema.json").read_text("utf-8")))
    doc = _v31()
    a = doc["atoms"][0]
    a.update(subject="donor", value=dict(BOUNDS))
    a["window"].update(anchor="last_dose", anchor_text="last dose of the prior biologic")
    assert not list(crit.iter_errors(doc))
    for key, bad in (("subject", "sibling"), ("anchor", "visit_3"), ("anchor_text", "")):
        wrong = copy.deepcopy(doc)
        node = wrong["atoms"][0] if key == "subject" else wrong["atoms"][0]["window"]
        node[key] = bad
        assert list(crit.iter_errors(wrong)), key
