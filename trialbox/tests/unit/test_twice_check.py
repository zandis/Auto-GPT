"""V-11: ``tools/twice_check.py`` holds the generated blocks of the "twice has one effect" page to its json, and a
planted fault (one count changed in the page) is caught."""

from __future__ import annotations

from tools import twice_check


def test_the_page_matches_its_json() -> None:
    assert twice_check.main(["--check"]) == 0


def test_a_planted_fault_is_caught() -> None:
    want = twice_check.blocks(*twice_check._load(twice_check.PAGE.with_suffix("")))
    page = twice_check.PAGE.read_text()
    assert twice_check.check(page, want) == []
    planted = page.replace("7 findings:", "6 findings:", 1)
    assert planted != page and twice_check.check(planted, want) == ["verdict"]
    twice, findings = twice_check._load(twice_check.PAGE.with_suffix(""))
    twice["step_twice"] = {**twice["step_twice"], "steps_added": 2}  # the json moved, the page did not
    assert "cases" in twice_check.check(page, twice_check.blocks(twice, findings))
