"""OCR #1455 (1455-5): every writer of deploy/.env goes through tools/trialbox/private_file.replace_private."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.trialbox import private_file, svc_secrets

pytestmark = pytest.mark.nodb


def test_the_secrets_rotation_writes_the_box_file_by_the_one_helper(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("POSTGRES_PASSWORD=old\nTB_ENV=TEST\n", encoding="utf-8")
    env.chmod(0o600)
    victim = tmp_path / "elsewhere"
    victim.write_text("not the box's\n", encoding="utf-8")
    (tmp_path / "..env.tmp").symlink_to(victim)  # planted at the old writer's fixed temp name (".{name}.tmp")
    svc_secrets._set_env(env, {"POSTGRES_PASSWORD": "new"})
    assert victim.read_text(encoding="utf-8") == "not the box's\n"
    assert env.read_text(encoding="utf-8") == "POSTGRES_PASSWORD=new\nTB_ENV=TEST\n"
    assert env.stat().st_mode & 0o777 == 0o600


def test_root_makes_the_box_file_roots_whoever_owned_the_old_one(tmp_path: Path,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    env = tmp_path / ".env"
    env.write_text("TB_ENV=TEST\n", encoding="utf-8")
    if os.geteuid() == 0:  # run as root the old file is root's already: give it another user's uid, as on a box
        os.chown(env, 4243, 4243)
    owners: list[tuple[int, int]] = []  # private_file uses this same os module
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "chown", lambda p, uid, gid: owners.append((uid, gid)))
    private_file.replace_private(env, "TB_ENV=TEST\n")
    assert owners == [(0, 0)]  # the old .env is this test user's (as M-LH-1's uid 1000): not handed on
