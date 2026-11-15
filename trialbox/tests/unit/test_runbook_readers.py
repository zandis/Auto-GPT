"""T-735a (D-729): every RUNBOOK page names its reader; IT gets one page; the other install forms are one part.

T-735's acceptance: "every page names its reader". A page of ``docs/runbook/`` says who it is for on a
``**Reader:**`` line under its title, naming one or more of the known readers; ``tools.doclint`` fails a page without
one. The RUNBOOK's section table says the same in its Audience column. IT's one page (the address, the data
connection, the firewall line) is in ``docs/handover/`` in the three languages."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tools import doclint

ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = ROOT / "docs" / "RUNBOOK.md"
PAGES = sorted((ROOT / "docs" / "runbook").glob("*.md"))

pytestmark = pytest.mark.nodb


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_every_runbook_page_names_its_reader(page: Path) -> None:
    rel = f"docs/runbook/{page.name}"
    assert doclint.reader_problems(rel, page.read_text(encoding="utf-8")) == []


def test_doclint_fails_a_page_without_a_reader_or_with_an_unknown_one() -> None:
    rel = "docs/runbook/99-x.md"
    assert doclint.reader_problems(rel, "# 99. X\n\nText.\n") == [
        f"{rel}:1: reader: no '**Reader:**' line under the title (one or more of: {', '.join(doclint.READERS)})"
    ]
    got = doclint.reader_problems(rel, "# 99. X\n\n**Reader:** the cleaner.\n")
    assert len(got) == 1 and "names no known reader" in got[0]
    assert doclint.reader_problems(rel, "# 99. X\n\n**Reader:** the box owner, with Aimedics.\n") == []


def test_doclint_runs_the_reader_rule_on_the_runbook() -> None:
    assert not [e for e in doclint.check_sections("docs/RUNBOOK.md") if ": reader:" in e]


def test_the_section_table_names_the_reader_of_each_section() -> None:
    rows = doclint.numbers_table(RUNBOOK.read_text(encoding="utf-8"))
    assert rows
    table = RUNBOOK.read_text(encoding="utf-8").split(doclint.NUMBERS, 1)[1]
    audiences = re.findall(r"^\| \d+ \| [^|]+\| [^|]+\| ([^|]+)\|", table, flags=re.M)
    assert len(audiences) == len(rows)
    assert all(a.strip() for a in audiences)
    assert not any(a.strip() == "site" for a in audiences)  # "site" said IT and the owner at once: it names one now
    assert any("owner" in a for a in audiences) and any("IT" in a for a in audiences)


def test_the_other_install_forms_are_one_part() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    head = text.split(doclint.BEGIN, 1)[0]
    assert "**Other install forms**" in head
    part = head.split("**Other install forms**", 1)[1].split("\n\n", 1)[0]
    for n in (8, 9, 10, 17, 26):
        assert f"§{n}" in part, n


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_it_has_one_page_in_each_language(lang: str) -> None:
    page = ROOT / "docs" / "handover" / f"it-one-page.{lang}.md"
    text = page.read_text(encoding="utf-8")
    assert doclint.check_doc(f"docs/handover/{page.name}") == []
    assert "**Reader:**" in text.splitlines()[2]
    assert len(text.splitlines()) <= 60  # one page
    for needed in ("443", "TB_TLS_HOSTNAME", "network-sheet"):
        assert needed in text, needed
