"""The test-trust page's tables match its JSON (card V-4), and a planted change is caught."""

from __future__ import annotations

import shutil
from pathlib import Path

from tools import test_trust


def test_the_page_matches_its_json() -> None:
    assert test_trust.check() == []
    assert test_trust.main(["--check"]) == 0


def _copy(tmp_path: Path) -> Path:
    page = tmp_path / test_trust.PAGE.name
    shutil.copy(test_trust.PAGE, page)
    shutil.copytree(test_trust.PAGE.with_suffix(""), page.with_suffix(""))
    return page


def test_a_changed_count_in_the_page_is_caught(tmp_path: Path) -> None:
    page = _copy(tmp_path)
    text = page.read_text(encoding="utf-8")
    start = text.index("<!-- test-trust:begin mutation -->")
    row = text.index("| **all run here** |", start)
    cells = text[row:].split("\n", 1)[0].split(" | ")
    cells[3] = str(int(cells[3]) + 1)  # one more killed mutant than the tool wrote
    page.write_text(text[:row] + " | ".join(cells) + text[row + len(text[row:].split("\n", 1)[0]) :], "utf-8")
    assert test_trust.check(page) == ["mutation"]
    assert test_trust.main(["--check", "--page", str(page)]) == 1
    test_trust.write(page)
    assert test_trust.check(page) == []


def test_a_changed_json_is_caught(tmp_path: Path) -> None:
    page = _copy(tmp_path)
    path = page.with_suffix("") / "findings.json"
    path.write_text(path.read_text(encoding="utf-8").replace('"Medium"', '"Low"', 1), encoding="utf-8")
    assert test_trust.check(page) == ["findings"]


def test_a_removed_block_is_caught(tmp_path: Path) -> None:
    page = _copy(tmp_path)
    text = page.read_text(encoding="utf-8")
    page.write_text(text.replace("<!-- test-trust:begin coverage -->", "<!-- coverage -->"), encoding="utf-8")
    assert test_trust.check(page) == ["coverage"]
