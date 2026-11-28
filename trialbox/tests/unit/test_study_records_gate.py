"""SAFE-1 A3: the backup is asked where records nobody can make again begin, a study opening (``study_records``),
not at the first night. A PRODUCTION box refuses that step while the backup target or key is missing or a stand-in;
a PoC box warns and goes on. The first real-data run is never refused for site items (its source is the hospital's
own system, and it can be run again). Synthetic values only."""

from __future__ import annotations

import pytest
from tb_common.site_needs import BY_KEY, LANGS, STEPS, gate

TARGET = {"TB_BACKUP_TARGETS": "/mnt/backup"}


def test_the_backup_is_needed_before_a_study_starts_its_records() -> None:
    for key in ("backup_target", "backup_key"):
        assert "study_records" in BY_KEY[key].before, key
    assert [n.key for n in BY_KEY.values() if "study_records" in n.before] == ["backup_target", "backup_key"]
    assert all(STEPS["study_records"][lang] for lang in LANGS)


@pytest.mark.parametrize(
    ("env", "files", "stand_ins", "want"),
    [
        ({}, (), (), [("backup_target", "missing"), ("backup_key", "missing")]),
        (TARGET, (), (), [("backup_key", "missing")]),
        ({}, ("backup_key",), (), [("backup_target", "missing")]),
        (TARGET, ("backup_key",), ("backup_target",), [("backup_target", "stand_in")]),
    ],
    ids=["neither", "no-key", "no-target", "target-stand-in"],
)
def test_production_refuses_a_study_opening_without_its_backup(
    env: dict[str, str], files: tuple[str, ...], stand_ins: tuple[str, ...], want: list[tuple[str, str]]
) -> None:
    g = gate("study_records", production=True, env=env, files=files, stand_ins=stand_ins)
    assert g.refused and [(n.key, s) for n, s in g.blocking] == want
    poc = gate("study_records", production=False, env=env, files=files, stand_ins=stand_ins)
    assert not poc.refused and [(n.key, s) for n, s in poc.warning] == want


def test_a_study_opens_with_its_backup_given() -> None:
    assert not gate("study_records", production=True, env=TARGET, files=("backup_key",)).refused
