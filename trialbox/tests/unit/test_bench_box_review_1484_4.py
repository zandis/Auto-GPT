"""The review of #1484 (H-116), 1484-4: the bench mark's check refuses a test box's folder even when a record that
holds is there (before, only ``write`` was tested on a test box; the check's own refusal could go unnoticed)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools.trialbox import benchbox

pytestmark = [pytest.mark.nodb]
WHEN = datetime(2026, 11, 24, 12, 0, 0, tzinfo=UTC)


def test_1484_4_a_test_box_folder_never_holds_the_bench_mark(tmp_path: Path) -> None:
    deploy = tmp_path / "box" / "deploy"
    (deploy / "site").mkdir(parents=True)
    (deploy / ".env").write_text("TB_ENV=PRODUCTION\nTB_BENCH=1\n", encoding="utf-8")
    assert benchbox.write(deploy, WHEN) is not None
    (deploy / benchbox.TEST_RECORD).write_text("TB_TEST_BOX=t\n", encoding="utf-8")
    with pytest.raises(benchbox.Refused, match="this folder is a test box"):
        benchbox.check(deploy)
