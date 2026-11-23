"""U5-2b (card U-5, D-1280): the one gate every step that needs site information passes before it runs
(``tb_common.site_needs.gate``).

On a PRODUCTION box a step is refused while an item it needs is missing, not usable, or a stand-in, and the refusal
names each item in the page's language. On a PoC box the same items are warnings and the step goes on. A step whose
items are all given passes on either box. Synthetic values only."""

from __future__ import annotations

import pytest
from tb_common.site_needs import BY_KEY, LANGS, STEPS, gate, state

OFFICE = {"TB_SAE_OFFICE_MAILBOX": "office@hospa.test"}


def test_a_value_the_callers_check_cannot_use_is_unusable_not_given() -> None:
    office = BY_KEY["office_mailbox"]
    assert state(office, env=OFFICE, unusable={"office_mailbox"}) == "unusable"
    assert state(office, env={}, unusable={"office_mailbox"}) == "missing"  # missing comes first


@pytest.mark.parametrize("how", ["missing", "stand_in", "unusable"])
def test_production_refuses_a_step_whose_item_is_not_given_and_names_it(how: str) -> None:
    env = {} if how == "missing" else OFFICE
    g = gate(
        "study_open",
        production=True,
        env=env,
        stand_ins={"office_mailbox"} if how == "stand_in" else (),
        unusable={"office_mailbox"} if how == "unusable" else (),
    )
    assert g.refused and [(n.key, s) for n, s in g.blocking] == [("office_mailbox", how)] and not g.warning
    for lang in LANGS:
        line = g.message(lang)
        assert STEPS["study_open"][lang] in line and BY_KEY["office_mailbox"].title[lang] in line, lang


def test_a_poc_box_warns_and_goes_on_with_the_same_items() -> None:
    g = gate("study_open", production=False, env={})
    assert not g.refused and [n.key for n, _ in g.warning] == ["office_mailbox"]
    assert "goes on with stand-ins" in g.message("en")


@pytest.mark.parametrize("production", [True, False])
def test_a_step_whose_items_are_given_passes_on_either_box(production: bool) -> None:
    g = gate("study_open", production=production, env=OFFICE)
    assert not g.refused and not g.warning and g.message() == ""


def test_every_item_a_step_needs_is_named_once_in_the_lists_order() -> None:
    g = gate("first_real_night", production=True, env={})
    keys = [n.key for n, _ in g.blocking]
    assert keys == [n.key for n in BY_KEY.values() if "first_real_night" in n.before]
    assert len(set(keys)) == len(keys)


def test_an_unknown_language_gives_the_english_words() -> None:
    assert gate("mail_out", production=True, env={}).message("fr").startswith("Not done:")
