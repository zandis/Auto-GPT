"""The statement of applicability, ``docs/validation/soa.csv`` (card T-649c, deep review REG-031).

One row per ISO/IEC 27001:2022 Annex A control (5.1-5.37, 6.1-6.8, 7.1-7.14, 8.1-8.34: 93 rows). Each row says who
the control applies to (product, vendor, hospital, or none) and gives evidence that exists in the repository, or a
reason. The titles are our own short words; the standard's text is not copied.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent
SOA = ROOT / "docs" / "validation" / "soa.csv"
PACK = ROOT / "docs" / "plan" / "sites" / "it-security-pack.md"

COLUMNS = ["control", "theme", "title", "applies", "evidence", "reason"]
THEMES = {"5": ("organisational", 37), "6": ("people", 8), "7": ("physical", 14), "8": ("technological", 34)}
PARTIES = {"product", "vendor", "hospital"}


def expected_ids() -> list[str]:
    return [f"{t}.{n}" for t, (_, count) in THEMES.items() for n in range(1, count + 1)]


def load(path: Path = SOA) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def evidence_exists(item: str) -> bool:
    """A repository path (from ``trialbox/`` or the repository root), optionally ``path::test_name``."""
    name, _, test = item.partition("::")
    for base in (ROOT, REPO):
        path = (base / name).resolve()
        if path.is_relative_to(REPO) and path.exists():
            return (
                not test
                or re.search(rf"^\s*(async )?def {re.escape(test)}\(", path.read_text("utf-8"), re.M) is not None
            )
    return False


def problems(rows: list[dict[str, str]]) -> list[str]:
    out: list[str] = []
    for row in rows:
        cid = row["control"]
        applies = [p for p in row["applies"].split(";") if p]
        evidence = [e for e in row["evidence"].split(";") if e]
        reason = row["reason"].strip()
        if not row["title"].strip():
            out.append(f"{cid}: no title")
        if THEMES.get(cid.split(".")[0], ("",))[0] != row["theme"]:
            out.append(f"{cid}: theme {row['theme']!r}")
        if applies == ["none"]:
            if not reason:
                out.append(f"{cid}: excluded without a reason")
        elif not applies or set(applies) - PARTIES or len(set(applies)) != len(applies):
            out.append(f"{cid}: applies {row['applies']!r}")
        elif not evidence and not reason:
            out.append(f"{cid}: applies but has neither evidence nor a reason")
        out += [f"{cid}: evidence missing: {e}" for e in evidence if not evidence_exists(e)]
    return out


def test_columns() -> None:
    assert load()[0] == COLUMNS


def test_93_rows_unique_ids_in_annex_a_order() -> None:
    ids = [r["control"] for r in load()[1]]
    assert len(ids) == 93
    assert len(set(ids)) == 93, "control ids must be unique"
    assert ids == expected_ids()


def test_every_row_has_applies_and_evidence_or_a_reason() -> None:
    assert not problems(load()[1])


def test_the_check_finds_planted_faults() -> None:
    base = {"theme": "organisational", "title": "t", "applies": "product", "evidence": "", "reason": ""}
    rows = [
        {**base, "control": "5.1"},
        {**base, "control": "5.2", "evidence": "docs/no_such_file.md"},
        {**base, "control": "5.3", "applies": "none"},
        {**base, "control": "5.4", "applies": "auditor", "reason": "r"},
        {**base, "control": "5.5", "evidence": "tests/unit/test_soa.py::test_no_such_test"},
        {**base, "control": "5.6", "evidence": "tests/unit/test_soa.py::test_columns"},
        {**base, "control": "5.7", "applies": "none", "reason": "not in scope"},
        {**base, "control": "5.8", "evidence": "../.github/CODEOWNERS"},
    ]
    found = problems(rows)
    assert [p.split(":")[0] for p in found] == ["5.1", "5.2", "5.3", "5.4", "5.5"], found


def test_titles_are_short_and_our_own() -> None:
    # Short titles only: a long title would suggest copied control text.
    long = [r["control"] for r in load()[1] if len(r["title"]) > 60]
    assert not long, long


def test_it_pack_a9_names_the_soa() -> None:
    text = PACK.read_text(encoding="utf-8")
    a9 = text.split("### A.9 ", 1)[1].split("\n### ", 1)[0]
    assert "`docs/validation/soa.csv`" in a9
    for sec in ("### B.9 ", "### C.9 "):
        assert "docs/validation/soa.csv" in text.split(sec, 1)[1].split("\n### ", 1)[0], sec
