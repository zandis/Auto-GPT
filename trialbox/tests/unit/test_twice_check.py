"""V-11: ``tools/twice_check.py`` holds the generated blocks of the "twice has one effect" page to its json, and a
planted fault (one count changed in the page, or in the json) is caught."""

from __future__ import annotations

import pytest

from tools import twice_check


def test_the_page_matches_its_json() -> None:
    assert twice_check.main(["--check"]) == 0


def test_a_planted_fault_is_caught() -> None:
    twice, findings = twice_check._load(twice_check.PAGE.with_suffix(""))
    want = twice_check.blocks(twice, findings)
    page = twice_check.PAGE.read_text()
    assert twice_check.check(page, want) == []
    n = f"{len(findings)} findings:"
    planted = page.replace(n, f"{len(findings) - 1} findings:", 1)
    assert planted != page and twice_check.check(planted, want) == ["verdict"]
    twice["step_twice"] = {**twice["step_twice"], "one_effect": False}  # the json moved, the page did not
    assert {"verdict", "cases"} <= set(twice_check.check(page, twice_check.blocks(twice, findings)))


def test_a_case_without_a_measured_answer_is_refused() -> None:
    twice, findings = twice_check._load(twice_check.PAGE.with_suffix(""))
    twice["step_twice"] = {k: v for k, v in twice["step_twice"].items() if k != "one_effect"}
    with pytest.raises(ValueError, match="step_twice"):
        twice_check.blocks(twice, findings)
