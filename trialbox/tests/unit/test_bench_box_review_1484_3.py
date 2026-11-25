"""The review of #1484 (H-116), 1484-3: the bytes the bench mark's check reads are the bytes of the file whose kind,
owner and mode it checked. Before, ``check`` looked at the record with ``lstat`` and then opened it again by name,
twice: a file swapped in between was taken as the mark."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.trialbox import benchbox

pytestmark = [pytest.mark.nodb]
WHEN = benchbox.datetime(2026, 11, 24, 12, 0, 0, tzinfo=benchbox.UTC)


def test_1484_3_a_record_swapped_in_after_the_owner_and_mode_check_is_not_the_mark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deploy = tmp_path / "bench" / "deploy"
    (deploy / "site").mkdir(parents=True)
    (deploy / ".env").write_text("TB_ENV=PRODUCTION\nTB_BENCH=1\n", encoding="utf-8")
    good = benchbox.write(deploy, WHEN)
    rec = deploy / benchbox.RECORD
    planted = tmp_path / "planted"
    planted.write_text(rec.read_text(encoding="utf-8").replace(good.at, "2030-01-01T00:00:00Z"), encoding="utf-8")
    planted.chmod(0o666)  # a file the check refuses when it is the record from the start
    real_lstat = Path.lstat
    swapped: list[int] = []

    def lstat_then_swap(self: Path) -> os.stat_result:
        st = real_lstat(self)
        if self == rec and not swapped:
            swapped.append(1)
            os.replace(planted, rec)  # between the look at the record and the read of it
        return st

    monkeypatch.setattr(Path, "lstat", lstat_then_swap)
    try:
        mark = benchbox.check(deploy)
    except benchbox.Refused:
        return  # the swapped-in file is refused: the bytes read are the bytes checked
    assert mark == good, f"a file swapped in after the check was taken as the mark: {mark}"
