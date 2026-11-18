"""H-23c (the integrator's ruling of 2026-11-18 on H23b-01): release 1.0's notes and the installer state SCREEN's
patient limit at the orchestrator's memory cap, and both name the figure the measurement gives, so neither drifts from
the findings file or from the other."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MEASURE = ROOT / "docs" / "plan" / "measurements"


def _finding() -> dict[str, Any]:
    data = json.loads((MEASURE / "size-test-2026-11-17-findings.json").read_text(encoding="utf-8"))
    (row,) = [f for f in data["findings"] if f["id"] == "H23b-01"]
    assert isinstance(row, dict)
    return row


def _limit() -> int:
    """The patients at which SCREEN's peak reaches the cap, on the line through the finding's two measured points,
    to the nearest thousand (the page's "near 45,000")."""
    claim = str(_finding()["claim"])
    m = re.search(r"(\d+(?:\.\d+)?) GiB cap", claim)
    assert m, claim
    cap = float(m.group(1))
    points = [(int(n.replace(",", "")), float(g)) for g, n in re.findall(r"(\d+\.\d+) GiB at ([\d,]+)", claim)]
    assert len(points) == 2, claim
    (n1, g1), (n2, g2) = points
    at_cap = n1 + (cap - g1) * (n2 - n1) / (g2 - g1)
    return round(at_cap / 1000) * 1000


def _known_limits() -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    start = text.index("### Known limits")
    return text[start : text.index("\n## ", start)]


def _install_summary() -> str:
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    start = text.index("TrialBox is running.")
    return text[start : text.index("\nEOT", start)]


def test_the_figure_is_the_measurement_pages() -> None:
    n = _limit()
    assert n == 45_000
    page = (MEASURE / "size-test-2026-11-17.md").read_text(encoding="utf-8")
    assert f"near {n:,}" in page and f"about {n:,}" in page


def test_the_release_notes_state_the_limit_with_its_basis() -> None:
    notes = _known_limits()
    assert f"about {_limit():,} patients" in notes and "H23b-01" in notes
    for fact in (
        "TB_MEM_ORCH",
        "4 GiB",
        "3 GiB",
        "stub model",
        "4.37 GiB",
        "8.22 GiB",
        "lower, not measured",
        "not a supported configuration",
        "TB_JOB_MAX_RESTARTS",
    ):
        assert fact in notes, fact


def test_the_installer_states_the_same_figure_in_its_summary() -> None:
    summary = _install_summary()
    line = next(x for x in summary.splitlines() if "Known limit:" in x)
    assert f"about {_limit():,} patients" in line
    assert "TB_MEM_ORCH" in summary and 'CHANGELOG.md, "Known limits"' in summary
    # a statement only: no variable is read and nothing branches on the site's patients
    assert "$" not in line and "read " not in summary
