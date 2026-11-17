"""Card V-3: the ASVS Level 2 checklist cannot rot silently (tools/asvs_checklist.py).

The page's count table equals checklist.json, every evidence file:line exists, every named test exists, and the
two json files agree. The second test shows the check fails on a planted fault, so a green first test means
something."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tools import asvs_checklist as ac

pytestmark = pytest.mark.nodb


def test_the_checklist_page_and_its_evidence_agree() -> None:
    assert ac.problems() == []
    assert ac.main(["--check"]) == 0


def test_the_check_fails_on_a_wrong_count_a_missing_line_and_a_lost_finding(tmp_path: Path) -> None:
    folder = tmp_path / ac.FOLDER.name
    shutil.copytree(ac.FOLDER, folder)
    page = folder.with_suffix(".md")
    page.write_text(ac.PAGE.read_text(encoding="utf-8").replace("| V4 | 9 |", "| V4 | 8 |"), encoding="utf-8")
    data = json.loads((folder / "checklist.json").read_text(encoding="utf-8"))
    data["requirements"][0]["line"] = 10**6
    data["requirements"][1]["finding"] = "V3-99"
    (folder / "checklist.json").write_text(json.dumps(data), encoding="utf-8")
    found = "\n".join(ac.problems(folder=folder, page=page))
    assert "count table differs" in found
    assert "the file has" in found
    assert "V3-99: named by the checklist, not in findings.json" in found
