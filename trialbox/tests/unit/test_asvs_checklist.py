"""Card V-3: the ASVS Level 2 checklist cannot rot silently (tools/asvs_checklist.py).

The page's generated parts (the counts, the V2-V4 summary, the findings table, the table of every line) equal the
json whole, every evidence file:line exists, every named test exists, and the two json files agree. The other tests
plant a fault each and show the check fails, so a green first test means something."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from tools import asvs_checklist as ac

pytestmark = pytest.mark.nodb


def test_the_checklist_page_and_its_evidence_agree() -> None:
    assert ac.problems() == []
    assert ac.main(["--check"]) == 0


def _copy(tmp_path: Path) -> tuple[Path, Path]:
    folder = tmp_path / ac.FOLDER.name
    shutil.copytree(ac.FOLDER, folder)
    page = folder.with_suffix(".md")
    shutil.copy(ac.PAGE, page)
    return folder, page


def test_the_check_fails_on_a_wrong_count_a_missing_line_and_a_lost_finding(tmp_path: Path) -> None:
    folder, page = _copy(tmp_path)
    page.write_text(page.read_text(encoding="utf-8").replace("| V4 | 7 |", "| V4 | 8 |"), encoding="utf-8")
    data = json.loads((folder / "checklist.json").read_text(encoding="utf-8"))
    data["requirements"][0]["line"] = 10**6
    data["requirements"][1]["finding"] = "V3-99"
    (folder / "checklist.json").write_text(json.dumps(data), encoding="utf-8")
    found = "\n".join(ac.problems(folder=folder, page=page))
    assert "the counts block differs" in found
    assert "the file has" in found
    assert "V3-99: named by the checklist, not in findings.json" in found


def test_the_check_fails_when_a_rows_verdict_is_changed_on_the_page(tmp_path: Path) -> None:
    folder, page = _copy(tmp_path)
    text = page.read_text(encoding="utf-8")
    changed = re.sub(r"(\| 3\.4\.4 \|[^\n]*?)\*\*does not meet\*\*", r"\1**meets**", text, count=1)
    assert changed != text
    page.write_text(changed, encoding="utf-8")
    assert "the rows block differs" in "\n".join(ac.problems(folder=folder, page=page))


def test_the_check_fails_when_a_findings_row_is_deleted_from_the_page(tmp_path: Path) -> None:
    folder, page = _copy(tmp_path)
    text = page.read_text(encoding="utf-8")
    changed = re.sub(r"\n\| V3-14 \|[^\n]*", "", text, count=1)
    assert changed != text
    page.write_text(changed, encoding="utf-8")
    assert "the findings block differs" in "\n".join(ac.problems(folder=folder, page=page))


def test_the_check_fails_when_the_summary_counts_are_changed(tmp_path: Path) -> None:
    folder, page = _copy(tmp_path)
    text = page.read_text(encoding="utf-8")
    changed = text.replace("**V4 Access control (9 lines):** 7 meets", "**V4 Access control (9 lines):** 9 meets", 1)
    assert changed != text
    page.write_text(changed, encoding="utf-8")
    assert "the summary block differs" in "\n".join(ac.problems(folder=folder, page=page))
