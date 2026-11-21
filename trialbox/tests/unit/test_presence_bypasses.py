"""A matching edit to the inventory cannot authorize a new release site."""

from __future__ import annotations

from collections import Counter
from textwrap import dedent

import pytest

from tools.presence_bypasses import INVENTORY, ROOT, Site, base_ceiling, inventory, scan, working_sites


@pytest.mark.guard
def test_presence_inventory_matches_code_and_cannot_grow() -> None:
    actual = working_sites()
    recorded = inventory((ROOT / INVENTORY).read_bytes())
    assert_ratchet(actual, recorded, base_ceiling())


def assert_ratchet(actual: Counter[Site], recorded: Counter[Site], base: Counter[Site]) -> None:
    assert actual == recorded, {"new": actual - recorded, "stale": recorded - actual}
    assert not (growth := recorded - base), growth


def sites(code: str) -> Counter[Site]:
    return Counter(scan("services/example.py", dedent(code)))


@pytest.mark.parametrize(
    "statement",
    [
        "return Make.model_validate(raw)",
        "validate = Make.model_validate\nreturn validate(raw)",
        "return Make.model_construct(**raw)",
        "return dict(class_='structured', logic=part)",
        "return {'class': 'mixed', 'logic': part}",
        "build = dict\nreturn build(class_='structured', logic=part)",
        "patch = dict(class_='mixed')\nreturn raw.model_copy(update=patch)",
        "raw['criteria'][0]['class'] = 'structured'",
        "c = raw['criteria'][0]\nc.class_ = 'mixed'",
        "key = 'class'\nraw[key] = state",
        "raw['criteria'][0]['logic']['args'][0]['quantifier'] = 'any'",
        "part = raw['logic']['args'][0]\npart['domain'] = 'condition'",
        "raw.logic.args[0].valueset = 'VS_GOUT'",
        "part = raw.get('logic').get('args')[0]\npart['valueset'] = 'VS_GOUT'",
        "getattr(raw, 'logic').args.clear()",
        "del raw.logic.args[0].value",
        "return raw | {'logic': part}",
        "raw['review'] = None",
        "return raw.model_copy(update={'review': None})",
        "items = raw['logic']['args']\nitems.append(part)",
        "change = raw['logic'].update\nchange(quantifier='any')",
        "raw.setdefault('class', 'structured')",
        "setattr(raw, 'class_', 'mixed')",
        "raw['criteria'][0] |= {'class': 'structured'}",
        "raw['review']['status'] = 'approved'",
        "for item in raw.logic.args:\n    item.quantifier = 'any'",
        "change = raw.review.update\nchange(status='approved')",
        "return Make.model_validate({'class': 'human', **raw})",
        "return dict(**{'class': state, 'logic': part})",
        "return dict([('class', 'mixed'), ('logic', part)])",
        "raw['review'].pop('status')",
    ],
)
def test_finds_bypass_forms(statement: str) -> None:
    code = "from tb_contracts import CriterionIR as Make\ndef release(raw, part, state):\n"
    assert sites(code + "\n".join("    " + line for line in statement.splitlines()))


def test_gate_controls_the_emitted_value() -> None:
    prefix = "from criteria_compiler.ir_extract.postprocess import admit_presence as gate\n"
    prefix += "from tb_contracts import CriterionIR as IR\n"
    assert not sites(prefix + "def release(raw):\n    return gate(IR.model_validate(raw), *evidence)")
    guarded = "def release(raw):\n    candidate = IR.model_validate(raw)\n    return gate(candidate, *evidence)"
    assert not sites(prefix + guarded)
    # Merely calling the gate cannot license a raw return or a second output in the same function.
    bypass = guarded.replace("return gate", "gate") + "\n    return candidate"
    assert sites(prefix + bypass)
    assert sites(prefix + guarded.replace("return gate", "destination.append(candidate)\n    return gate"))


def test_new_write_in_an_existing_function_counts_again() -> None:
    first = "def release(raw):\n    raw['class'] = 'structured'\n"
    base = sites(first)
    grown = sites(first + "    raw['other']['class'] = 'mixed'")
    assert (grown - base).total() == 1
    assert (base - grown) == Counter()


def test_human_and_value_comparisons_are_not_executable_presence() -> None:
    assert not sites("""
        from tb_contracts import CriterionIR as Make
        def release(raw):
            human = Make.model_validate(dict(raw, class_="human"))
            return human, {"class": "structured", "logic": {"domain": "observation", "value": {"op": "<", "num": 2}}}
    """)


def test_stale_row_and_paired_code_and_inventory_growth_both_fail() -> None:
    initial = sites("def old(raw):\n    raw['class'] = 'structured'")
    changed = initial + sites("def new(raw):\n    raw.logic.args.clear()")
    with pytest.raises(AssertionError):
        assert_ratchet(initial, changed, changed)
    with pytest.raises(AssertionError):
        assert_ratchet(changed, changed, initial)
    assert_ratchet(initial, initial, changed)
