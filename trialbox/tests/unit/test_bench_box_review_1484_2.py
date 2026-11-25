"""The review of #1484 (H-116), 1484-2: every start asks the bench mark's check about any TB_BENCH line the check
reads, not only one at the very start of the line."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.test_bench_box_h116 import _box, _guard
from tools.trialbox import benchbox

pytestmark = [pytest.mark.nodb]


@pytest.mark.parametrize(
    "line", [" TB_BENCH=1", "export TB_BENCH=1", "TB_BENCH = 1"], ids=["indented", "export", "spaced"]
)
def test_1484_2_every_start_asks_for_a_tb_bench_line_the_check_reads(tmp_path: Path, line: str) -> None:
    """A TB_BENCH line the mark's check reads, with no record: the start is refused, as it is for ``TB_BENCH=1`` at
    the start of the line (before, the start's trigger missed it and went on)."""
    deploy = _box(tmp_path, f"TB_ENV=PRODUCTION\n{line}\n")
    with pytest.raises(benchbox.Refused, match="with no record"):
        benchbox.check(deploy)
    r = _guard(deploy)
    assert r.returncode == 1 and "TrialBox REFUSED to start: this box's bench mark is refused" in r.stderr, r
