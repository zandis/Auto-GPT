"""U5-2 (card U-5, the integrator's go on #639): ``deploy/site/needs/stand-ins.json``, the keys of the values the box put in
place of the hospital's own (``tb_common.site_needs``: ``read_stand_ins``, ``write_stand_ins``, ``mark``).

Keys only, never a value; mode 0600; a link is refused when written and not read; a key the list does not know is
refused when written and named when read; the nightly backup's host part carries the file. Synthetic values only."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from tb_common import site_needs
from tb_common.site_needs import STAND_INS, mark, read_stand_ins, state, write_stand_ins


def test_no_file_is_no_stand_in(tmp_path: Path) -> None:
    assert read_stand_ins(tmp_path) == (frozenset(), [])


def test_written_keys_are_read_back_sorted_once_and_with_mode_0600(tmp_path: Path) -> None:
    write_stand_ins(tmp_path, ["site_name", "office_mailbox", "site_name"])
    path = tmp_path / STAND_INS
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"format": site_needs.STAND_INS_FORMAT, "keys": ["office_mailbox", "site_name"]}
    assert read_stand_ins(tmp_path) == (frozenset({"office_mailbox", "site_name"}), [])
    assert [p.name for p in path.parent.iterdir()] == [path.name]  # no temporary file left beside it


def test_a_key_the_list_does_not_know_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="smtp_password"):
        write_stand_ins(tmp_path, ["office_mailbox", "smtp_password"])
    assert not (tmp_path / STAND_INS).exists()


def test_a_link_in_its_place_is_refused_and_not_read(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text(json.dumps({"format": site_needs.STAND_INS_FORMAT, "keys": ["site_name"]}))
    (tmp_path / STAND_INS).parent.mkdir(parents=True)
    (tmp_path / STAND_INS).symlink_to(elsewhere)
    keys, problems = read_stand_ins(tmp_path)
    assert keys == frozenset() and problems and "link" in problems[0]
    with pytest.raises(OSError, match="link"):
        write_stand_ins(tmp_path, ["office_mailbox"])
    assert json.loads(elsewhere.read_text())["keys"] == ["site_name"]


@pytest.mark.parametrize(
    "body",
    ["not json", json.dumps(["site_name"]), json.dumps({"format": "other/1", "keys": ["site_name"]})],
)
def test_a_file_that_is_not_the_list_reads_as_none_and_says_so(tmp_path: Path, body: str) -> None:
    (tmp_path / STAND_INS).parent.mkdir(parents=True)
    (tmp_path / STAND_INS).write_text(body)
    keys, problems = read_stand_ins(tmp_path)
    assert keys == frozenset() and len(problems) == 1


def test_an_unknown_key_in_the_file_is_named_and_left_out(tmp_path: Path) -> None:
    (tmp_path / STAND_INS).parent.mkdir(parents=True)
    (tmp_path / STAND_INS).write_text(
        json.dumps({"format": site_needs.STAND_INS_FORMAT, "keys": ["site_name", "made_up"]})
    )
    keys, problems = read_stand_ins(tmp_path)
    assert keys == frozenset({"site_name"}) and problems == [
        f"{STAND_INS} names an item the list does not know: made_up"
    ]


def test_mark_adds_and_takes_off_and_the_state_follows(tmp_path: Path) -> None:
    env = {"TB_SAE_OFFICE_MAILBOX": "admin@hospa.test"}
    office = site_needs.BY_KEY["office_mailbox"]
    assert mark(tmp_path, "office_mailbox", stand_in=True) == frozenset({"office_mailbox"})
    assert state(office, env=env, stand_ins=read_stand_ins(tmp_path)[0]) == "stand_in"
    assert mark(tmp_path, "office_mailbox", stand_in=False) == frozenset()
    assert state(office, env=env, stand_ins=read_stand_ins(tmp_path)[0]) == "given"


def test_the_nightly_backups_host_part_carries_the_list(tmp_path: Path) -> None:
    from tools.trialbox import backup_schedule

    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    (deploy / ".env").write_text(f"TB_SITE_ID=DEMO-A\nTB_DOCKER_VOLUMES={tmp_path / 'none'}\n")
    write_stand_ins(deploy, ["office_mailbox"])
    ops = backup_schedule.ComposeOps(deploy, lambda *a, **k: "")
    dest = tmp_path / "work" / "host"
    taken = ops.host_files(dest)
    assert "site" in taken
    copied = dest / STAND_INS
    assert json.loads(copied.read_text(encoding="utf-8"))["keys"] == ["office_mailbox"]
    assert os.path.getsize(copied) == os.path.getsize(deploy / STAND_INS)
