"""10G-42 (c): the page of SQL sites has one row for every place ruff's S608 finds, file by file.

The sites are found by one command, run from ``trialbox/`` (the command of review 21's M 3, narrowed to S608):

    ruff check --isolated --select S608 libs services deploy

The page ``docs/handover/sql-sites-classified-2026-11-18.md`` classifies each site in a table row that starts with
the site's place in backticks (``| `services/x.py:12` | ...``). The test compares the number of rows per file with the
number of sites ruff finds per file, so a moved line does not fail it but a new or removed site does: the page is
then out of date and the new site must be classified. The findings file holds the page's class 3 sites only.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "handover" / "sql-sites-classified-2026-11-18.md"
FINDINGS = ROOT / "docs" / "handover" / "sql-sites-classified-2026-11-18" / "findings.json"
ROW = re.compile(r"^\| `(?P<file>[^`:]+):(?P<line>\d+)` \|")
CLASSES = {"1", "2", "3", "not SQL"}


def _ruff_sites() -> list[tuple[str, int]]:
    out = subprocess.run(  # a fixed argv, no shell
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--isolated",
            "--select",
            "S608",
            "--output-format",
            "json",
            "--exit-zero",
            "libs",
            "services",
            "deploy",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [(str(Path(d["filename"]).resolve().relative_to(ROOT)), d["location"]["row"]) for d in json.loads(out)]


def _page_rows() -> list[tuple[str, int, list[str]]]:
    rows = []
    for text in PAGE.read_text(encoding="utf-8").splitlines():
        m = ROW.match(text)
        if m:
            cells = [c.strip() for c in text.strip().strip("|").split("|")]
            rows.append((m["file"], int(m["line"]), cells))
    return rows


def test_the_page_has_one_row_per_site_file_by_file() -> None:
    sites = _ruff_sites()
    rows = _page_rows()
    assert sites, "ruff found no S608 site: the command or the tree changed"
    assert len(rows) == len(sites)
    assert Counter(f for f, _, _ in rows) == Counter(f for f, _ in sites)


def test_every_row_has_a_class_and_every_class_3_row_a_finding() -> None:
    rows = _page_rows()
    for f, line, cells in rows:
        assert cells[4] in CLASSES, f"{f}:{line}: class {cells[4]!r}"
    third = {f"{f}:{line}" for f, line, cells in rows if cells[4] == "3"}
    findings = json.loads(FINDINGS.read_text(encoding="utf-8"))["findings"]
    assert {x["place"] for x in findings} == third
    for x in findings:
        assert x["severity"] in {"High", "Medium", "Low"}
