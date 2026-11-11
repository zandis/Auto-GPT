"""The operations documents of T-635 (D-390): every page names its T-213b drill, and each site's tabletop lists it."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = ROOT / "docs" / "runbook"
SITES = ROOT / "docs" / "plan" / "sites"
DRILL = re.compile(r"^\*\*Drill \(T-213b\):\*\* `(test_runbook_(\d{2})_[a-z0-9_]+)`", re.M)
# the T-635 pages: the five sections and the parts written for OPS-074
PAGES = (
    "21-support-model-and-the-supervised-remote-session.md",
    "22-disaster-recovery-with-measured-rpo-and-rto.md",
    "23-key-inventory-and-the-lost-box-list.md",
    "24-patch-policy.md",
    "25-leavers.md",
    "04-morning-mail-missing.md",
    "04-disk-full.md",
    "04-gpu-fault.md",
    "12-certificate-renewal.md",
    "22-planned-power-cut.md",
    "22-moving-the-box.md",
    "22-replacing-hardware.md",
)
TABLETOPS = ("tabletop-record-japan.md", "tabletop-record-cgmh.md")


def drills() -> dict[str, str]:
    """page -> its drill name; each page names exactly one, numbered like the page."""
    out: dict[str, str] = {}
    for page in PAGES:
        found = DRILL.findall((RUNBOOK / page).read_text(encoding="utf-8"))
        assert len(found) == 1, f"{page}: names {len(found)} drills, not one"
        name, number = found[0]
        assert number == page[:2], f"{page}: drill {name} is numbered for another section"
        out[page] = name
    return out


def test_every_page_names_one_drill() -> None:
    names = list(drills().values())
    assert len(names) == len(set(names)), "two pages name the same drill"


def test_each_site_tabletop_lists_every_drill() -> None:
    names = set(drills().values())
    for tabletop in TABLETOPS:
        text = (SITES / tabletop).read_text(encoding="utf-8")
        missing = sorted(n for n in names if f"`{n}`" not in text)
        assert not missing, f"{tabletop} lacks {missing}"


def test_support_sheet_has_three_languages() -> None:
    text = (SITES / "support-sheet.md").read_text(encoding="utf-8")
    for heading in ("## A. English", "## B. 日本語", "## C. 繁體中文"):
        assert heading in text
    # the same subsections in each language
    for part in "ABC":
        assert len(re.findall(rf"^### {part}\.\d ", text, re.M)) == 5


def test_owner_defaults_are_marked() -> None:
    """Where TB-DR-09 Q1, Q2, Q5 or Q6 decides, the page says it is a default until the owner answers."""
    expected = {
        "21-support-model-and-the-supervised-remote-session.md": ("Q2", "Q6"),
        "22-disaster-recovery-with-measured-rpo-and-rto.md": ("Q5",),
        "22-replacing-hardware.md": ("Q5",),
        "24-patch-policy.md": ("Q1",),
    }
    for page, questions in expected.items():
        text = (RUNBOOK / page).read_text(encoding="utf-8")
        for q in questions:
            assert f"Default until the owner answers (TB-DR-09 {q})" in text or (
                f"default until the owner answers (TB-DR-09 {q})" in text
            ), f"{page}: no marked default for {q}"


def test_no_measured_number_is_claimed() -> None:
    """No restore has been measured on master: §22 keeps its measured column empty until T-213b fills it."""
    text = (RUNBOOK / "22-disaster-recovery-with-measured-rpo-and-rto.md").read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith("| RPO") or line.startswith("| RTO")]
    assert len(rows) == 4 and all(line.rstrip().endswith("| not measured yet |") for line in rows)
