"""T-735b (D-732): every handover page names its reader too, as the RUNBOOK's pages do (D-729).

``docs/handover/`` is what leaves the vendor with the box: the owner's pages, the install checklist, IT's one page,
the network sheet. Each Markdown page has a ``**Reader:**`` line under its title; ``tools.doclint`` fails one
without it. The network sheet is generated, so its reader line comes from ``tools/network_sheet.py``."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import doclint, network_sheet

ROOT = Path(__file__).resolve().parents[2]
PAGES = sorted((ROOT / "docs" / "handover").glob("*.md"))

pytestmark = pytest.mark.nodb


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_every_handover_page_names_its_reader(page: Path) -> None:
    assert doclint.reader_problems(f"docs/handover/{page.name}", page.read_text(encoding="utf-8")) == []


def test_doclint_runs_the_reader_rule_on_the_handover_pages() -> None:
    assert doclint.handover_problems() == []
    assert "docs/handover" in doclint.READER_FOLDERS


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_the_generated_network_sheet_names_hospital_it(lang: str) -> None:
    md = network_sheet.render_md(["deploy/docker-compose.yml"], None, lang)
    assert md.splitlines()[2].startswith("**Reader:** hospital IT")
    assert "<b>Reader:</b> hospital IT" in network_sheet.render_html(["deploy/docker-compose.yml"], None, lang)
