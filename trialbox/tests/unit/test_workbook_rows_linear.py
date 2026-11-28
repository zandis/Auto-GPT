"""MVP-B (REAL2 M-3): a site-made study's whole-hospital SCREEN spent about 50 minutes in "reporting" (one core at
100 %). The candidate workbook asked openpyxl for ``max_row`` after every row it wrote; openpyxl answers that by
walking every cell written so far, so a list of n rows cost n^2 (4,700 rows: 14 of the workbook's 26 s; the whole
hospital's 47,000 listed: about a hundred times that, again for each department's referral workbook). The workbooks
now count their own rows. The navigator workbook had the same loop. Synthetic data only."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

import pytest
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet
from orchestrator.reports import candidate_xlsx
from tb_common.ruleset import Ruleset
from tb_contracts import CandidateRow

from tests.unit.test_feas_unit import META

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
GZQO = Ruleset.load(ROOT / "rulesets" / "GZQO")
N = 300


def _rows(n: int) -> list[CandidateRow]:
    ids = [c.id for c in GZQO.active() if c.kind in ("inclusion", "exclusion")][:3]
    return [
        CandidateRow.model_validate(
            {
                "pid": f"{i:032x}",
                "tier": "high" if i % 10 == 0 else "review",
                "practitioner_id": f"DR-{i % 7}",
                "department": "RHEU",
                "next_appointment": datetime(2026, 12, 1, 9, tzinfo=UTC) if i % 5 == 0 else None,
                "criteria": [
                    {"id": c, "verdict": "pass", "evidence": {"resource_refs": [], "reason": f"row {i} crit {k}"}}
                    for k, c in enumerate(ids)
                ],
                "actions": [],
                "changed": [ids[0]] if i % 3 == 0 else None,
            }
        )
        for i in range(n)
    ]


def test_the_candidate_workbook_does_not_walk_its_cells_for_each_row(monkeypatch: pytest.MonkeyPatch) -> None:
    reads: list[int] = []
    real = Worksheet.max_row

    def counted(self: Worksheet) -> int:
        reads.append(1)
        return real.fget(self)  # type: ignore[attr-defined,no-any-return]

    monkeypatch.setattr(Worksheet, "max_row", property(counted))
    candidate_xlsx.render(_rows(N), GZQO, META, {}, {})
    assert len(reads) < 10, len(reads)  # was one a row (300) and more


def test_each_rows_comment_and_mark_are_on_that_row() -> None:
    rows = _rows(N)
    ws = load_workbook(io.BytesIO(candidate_xlsx.render(rows, GZQO, META, {}, {})))["candidates"]
    first = 7  # the first criterion's column
    for n, r in enumerate(rows, start=2):
        assert ws.cell(row=n, column=2).value == r.pid
        cell = ws.cell(row=n, column=first)
        assert cell.comment is not None and f"row {n - 2} crit 0" in cell.comment.text, (n, cell.comment)
        assert (cell.fill.fgColor.rgb == "00F8CBAD") == bool(r.changed), (n, cell.fill.fgColor.rgb)
