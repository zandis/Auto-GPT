"""Rule cards: load, parameter validation, the outlier flag, card_ref, and what the hashes cover."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.cards import Card, CardError, card_hash, instantiate, load
from tb_contracts.criterion_ir import CriterionIRv3, canonical_hash

CARD: dict[str, Any] = {
    "card_id": "lab.liver.alt_uln",
    "version": "1.0.0",
    "title": "ALT above a multiple of the upper limit of normal",
    "sources": ["tpl_3f2a", "tpl_91c0"],
    "params": {
        "multiple": {"type": "number", "min": 1, "max": 10, "default": 3, "observed_p10_p90": [2.5, 5]},
        "window_days": {"type": "integer", "min": 1, "max": 3650, "observed_p10_p90": [28, 180]},
        "pick": {"type": "string", "values": ["latest", "any"], "default": "latest"},
    },
    "ir_template": {
        "id": "CARD-EXC-01",
        "ruleset": "CARD/v0.0.0",
        "kind": "exclusion",
        "class": "structured",
        "text": {"source": "ALT > {{multiple}} x ULN within {{window_days}} days"},
        "logic": "a1",
        "atoms": [
            {
                "id": "a1",
                "domain": "observation",
                "valueset": "VS_ALT",
                "quantifier": "{{pick}}",
                "value": {"op": ">", "ref": {"kind": "uln", "multiple": "{{multiple}}"}},
                "window": {"from_days": "-{{window_days}}", "to_days": 0, "anchor": "index"},
            }
        ],
    },
    "fixtures": [{"name": "4x ULN yesterday", "params": {"window_days": 90}, "facts": [], "expect": "T"}],
}


def _write(root: Path, doc: dict[str, Any]) -> Path:
    p = root / doc["card_id"] / f"{doc['version']}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")
    return root


def _card(**edits: Any) -> Card:
    d = copy.deepcopy(CARD)
    d.update(edits)
    return Card.model_validate(d)


def test_load_and_instantiate(tmp_path: Path) -> None:
    card = load("lab.liver.alt_uln", "1.0.0", _write(tmp_path, CARD))
    ir = instantiate(card, {"window_days": 90}, criterion_id="GZQO-EXC-13", ruleset="GZQO")
    assert isinstance(ir, CriterionIRv3) and ir.ir_version == "3.1.0"
    assert (ir.id, ir.ruleset) == ("GZQO-EXC-13", "GZQO")
    assert ir.text.source == "ALT > 3 x ULN within 90 days"  # spliced into text
    a = ir.atoms[0]
    assert a.quantifier == "latest" and a.window is not None and a.window.from_days == -90  # typed in place, negated
    assert a.value is not None and a.value.ref is not None and a.value.ref.multiple == 3
    assert ir.card_ref is not None and ir.card_ref.model_dump() == {
        "card_id": "lab.liver.alt_uln",
        "card_version": "1.0.0",
        "params": {"multiple": 3, "window_days": 90, "pick": "latest"},
    }
    assert ir.canonical_hash == canonical_hash(ir) and not ir.flags


def test_the_instance_hash_is_the_hash_of_its_atoms() -> None:
    ir = instantiate(_card(), {"window_days": 90})
    plain = ir.model_dump(mode="json", by_alias=True, exclude_none=True)
    for k in ("card_ref", "canonical_hash"):
        plain.pop(k)
    plain["ir_version"] = "3.0.0"
    assert ir.canonical_hash == canonical_hash(CriterionIRv3.model_validate(plain))  # card_ref is outside the hash
    v2 = _card(version="1.1.0", title="renamed", sources=["tpl_new"])
    again = instantiate(v2, {"window_days": 90})
    assert again.canonical_hash == ir.canonical_hash and again.card_ref and again.card_ref.card_version == "1.1.0"
    assert instantiate(_card(), {"window_days": 91}).canonical_hash != ir.canonical_hash  # the atoms count


@pytest.mark.parametrize(
    ("params", "msg"),
    [
        ({"window_days": 90, "dose": 1}, "unknown params dose"),
        ({}, "param window_days has no value and no default"),
        ({"window_days": 90.0}, "param window_days: 90.0 is not integer"),
        ({"window_days": True}, "param window_days: True is not integer"),
        ({"window_days": 90, "multiple": "3"}, "param multiple: '3' is not number"),
        ({"window_days": 0}, r"param window_days: 0 is outside \[1.0, 3650.0\]"),
        ({"window_days": 90, "multiple": 11}, r"param multiple: 11 is outside \[1.0, 10.0\]"),
        ({"window_days": 90, "pick": "first"}, "param pick: 'first' is not one of latest, any"),
    ],
)
def test_params_are_validated(params: dict[str, Any], msg: str) -> None:
    with pytest.raises(CardError, match=msg):
        instantiate(_card(), params)


def test_a_value_outside_the_observed_centiles_is_flagged_not_refused() -> None:
    inside = instantiate(_card(), {"window_days": 180, "multiple": 2.5})
    assert not inside.flags  # the centiles are inclusive
    outside = instantiate(_card(), {"window_days": 365, "multiple": 8})
    assert outside.flags == ["param_outside_p10_p90:multiple", "param_outside_p10_p90:window_days"]
    plain = outside.model_copy(update={"flags": None})
    assert outside.canonical_hash == canonical_hash(plain)  # the flags are outside the hash
    no_centiles = copy.deepcopy(CARD)
    del no_centiles["params"]["window_days"]["observed_p10_p90"]
    assert not instantiate(Card.model_validate(no_centiles), {"window_days": 9999}).flags


def test_card_hash_leaves_out_the_provenance() -> None:
    base = card_hash(_card())
    refreshed = copy.deepcopy(CARD)
    refreshed["sources"] = ["tpl_other"]
    refreshed["params"]["multiple"]["observed_p10_p90"] = [2, 4]
    assert card_hash(Card.model_validate(refreshed)) == base
    for path, value in ((("params", "multiple", "max"), 20), (("params", "multiple", "default"), 2)):
        moved = copy.deepcopy(CARD)
        node = moved
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = value
        assert card_hash(Card.model_validate(moved)) != base, path
    template = copy.deepcopy(CARD)
    template["ir_template"]["atoms"][0]["valueset"] = "VS_AST"
    assert card_hash(Card.model_validate(template)) != base


def test_load_refuses_a_broken_card(tmp_path: Path) -> None:
    with pytest.raises(CardError, match=r"no card lab.liver.alt_uln@9.9.9"):
        load("lab.liver.alt_uln", "9.9.9", _write(tmp_path, CARD))
    wrong = _write(tmp_path / "w", {**CARD, "version": "2.0.0"})
    (wrong / "lab.liver.alt_uln" / "2.0.0.json").rename(wrong / "lab.liver.alt_uln" / "1.0.0.json")
    with pytest.raises(CardError, match="holds lab.liver.alt_uln@2.0.0"):
        load("lab.liver.alt_uln", "1.0.0", wrong)
    orphan = copy.deepcopy(CARD)
    orphan["ir_template"]["text"]["source"] += " {{unit}}"
    with pytest.raises(CardError, match="slots without a param: unit"):
        load("lab.liver.alt_uln", "1.0.0", _write(tmp_path / "o", orphan))
    unused = copy.deepcopy(CARD)
    unused["params"]["route"] = {"type": "string"}
    with pytest.raises(CardError, match="params no slot uses: route"):
        load("lab.liver.alt_uln", "1.0.0", _write(tmp_path / "u", unused))


def test_a_rendering_that_is_not_valid_ir_is_refused() -> None:
    bad = copy.deepcopy(CARD)
    bad["params"]["pick"]["values"] = ["latest", "sometimes"]
    with pytest.raises(CardError, match="renders an invalid criterion"):
        instantiate(Card.model_validate(bad), {"window_days": 90, "pick": "sometimes"})
