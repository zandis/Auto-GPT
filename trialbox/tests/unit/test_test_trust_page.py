"""The test-trust page's blocks match its JSON (card V-4), and each planted change is caught."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from tools import test_trust


def test_the_page_matches_its_json() -> None:
    assert test_trust.check() == []
    assert test_trust.main(["--check"]) == 0


def _copy(tmp_path: Path) -> Path:
    page = tmp_path / test_trust.PAGE.name
    shutil.copy(test_trust.PAGE, page)
    shutil.copytree(test_trust.PAGE.with_suffix(""), page.with_suffix(""))
    return page


@pytest.mark.parametrize("name", test_trust.NAMES)
def test_a_changed_digit_in_any_block_is_caught(tmp_path: Path, name: str) -> None:
    page = _copy(tmp_path)
    text = page.read_text(encoding="utf-8")
    start = text.index(f"<!-- test-trust:begin {name} -->")
    end = text.index(f"<!-- test-trust:end {name} -->")
    digit = re.search(r"\d", text[start + len(name) + 25 : end])
    assert digit, name
    at = start + len(name) + 25 + digit.start()
    page.write_text(text[:at] + str((int(text[at]) + 1) % 10) + text[at + 1 :], encoding="utf-8")
    assert name in test_trust.check(page)
    assert test_trust.main(["--check", "--page", str(page)]) == 1
    test_trust.write(page)
    assert test_trust.check(page) == []


def _edit(page: Path, name: str, change: object) -> None:
    path = page.with_suffix("") / f"{name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)  # type: ignore[operator]
    path.write_text(json.dumps(data), encoding="utf-8")


def test_a_changed_nightly_score_is_caught(tmp_path: Path) -> None:
    page = _copy(tmp_path)
    _edit(page, "mutation", lambda d: d["ci_nightly_2026_11_16"].update(score=99.0))
    assert {"verdict", "nightly"} <= set(test_trust.check(page))


def test_a_changed_severity_is_caught(tmp_path: Path) -> None:
    page = _copy(tmp_path)
    _edit(page, "findings", lambda d: d["findings"][0].update(severity="Low"))
    assert "findings" in test_trust.check(page)


def test_a_survivor_that_is_no_survivor_is_caught(tmp_path: Path) -> None:
    page = _copy(tmp_path)
    _edit(page, "survivors", lambda d: d["survivors"][0].update(mutant="libs/tb_common/quotes.py:1:1:const:+1"))
    test_trust.write(page)  # even with the table rewritten, the id must be a survivor of mutation.json
    assert test_trust.check(page) == ["survivors"]


def test_a_removed_block_is_caught(tmp_path: Path) -> None:
    page = _copy(tmp_path)
    text = page.read_text(encoding="utf-8")
    page.write_text(text.replace("<!-- test-trust:begin coverage -->", "<!-- coverage -->"), encoding="utf-8")
    assert "coverage" in test_trust.check(page)
