"""U5-6 (card U-5, D-1280): the study-open gate. A study that reports serious adverse events opens on a PRODUCTION
box only with the trial office's own mailbox: missing, or only the first administrator's mail standing in for it
(marked in the read-only list ``site_needs.MOUNTED``), it is refused, and the refusal names the page, not a setting.
A PoC box opens with the stand-in (U5-01). Synthetic data only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tb_common import site_needs

import tests.console.test_console_app as _app
import tests.console.test_lifecycle_pages as _life
from tests.console.test_role_pages import _csrf

# the fixtures, found by name: the box, and the lifecycle box built on it
box = _app.box
lb = _life.lb
login, name_pi, PW = _app.login, _app.name_pi, _life.PW


def _open(
    lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch, env: str, mounted: Path, *, backup_target: bool = True
) -> tuple[int, str]:
    from console import study_setup

    if backup_target:  # SAFE-1 A3: a study opens with its backup given
        monkeypatch.setenv("TB_BACKUP_TARGETS", "/mnt/backup")
    else:
        monkeypatch.delenv("TB_BACKUP_TARGETS", raising=False)
    monkeypatch.setattr(site_needs, "MOUNTED", mounted)
    name_pi(lb, "pi")
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/setup/sae", data={"csrf": csrf, "rule_set": "tw_trial"}, follow_redirects=True)
    c.post("/studies/GZQO/state", data={"csrf": csrf, "state": "paused", "reason": "set-up"}, follow_redirects=False)
    monkeypatch.setattr(study_setup, "environment_name", lambda _env: env)
    page = c.get("/studies/GZQO/state").text
    r = c.post("/studies/GZQO/state", data={"csrf": _csrf(page), "state": "open"}, follow_redirects=False)
    return int(r.status_code), r.text


def _mount(tmp_path: Path, keys: list[str], *, backup_key: bool = True) -> Path:
    if backup_key:  # SAFE-1 A3: the host has the backup key (host-given.json, as backup-keygen writes it)
        (tmp_path / "secrets").mkdir(parents=True, exist_ok=True)
        (tmp_path / "secrets" / "backup.pub").write_text("synthetic public key\n", encoding="utf-8")
    site_needs.write_host_given(tmp_path)
    site_needs.write_stand_ins(tmp_path, keys)
    return (tmp_path / site_needs.STAND_INS).parent


def test_production_refuses_the_first_administrators_mail_standing_in(
    lb: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TB_SAE_OFFICE_MAILBOX", "admin@hospa.test")
    status, text = _open(lb, monkeypatch, "PRODUCTION", _mount(tmp_path, ["office_mailbox"]))
    assert status == 409 and "Information still needed" in text and "TB_SAE_OFFICE_MAILBOX" not in text


def test_production_opens_with_the_offices_own_mailbox(
    lb: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TB_SAE_OFFICE_MAILBOX", "office@hospa.test")
    assert _open(lb, monkeypatch, "PRODUCTION", _mount(tmp_path, []))[0] == 303


def test_a_poc_box_opens_with_the_stand_in(
    lb: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TB_SAE_OFFICE_MAILBOX", "admin@hospa.test")
    assert _open(lb, monkeypatch, "VALIDATION", _mount(tmp_path, ["office_mailbox"]))[0] == 303


def test_no_mount_reads_as_no_stand_in(tmp_path: Path) -> None:
    assert site_needs.read_mounted_stand_ins(tmp_path / "absent") == frozenset()


# ------------------------------------------------------------------------------------------------ SAFE-1 A3
def test_production_does_not_open_a_study_without_the_backup_key(
    lb: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A study that opens starts records nobody can make again: a PRODUCTION box waits for the backup."""
    monkeypatch.setenv("TB_SAE_OFFICE_MAILBOX", "office@hospa.test")
    status, text = _open(lb, monkeypatch, "PRODUCTION", _mount(tmp_path, [], backup_key=False))
    assert status == 409 and "no backup target or backup key yet" in text and "Information still needed" in text
    assert "TB_BACKUP" not in text


def test_production_does_not_open_a_study_without_the_backup_target(
    lb: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TB_SAE_OFFICE_MAILBOX", "office@hospa.test")
    status, text = _open(lb, monkeypatch, "PRODUCTION", _mount(tmp_path, []), backup_target=False)
    assert status == 409 and "no backup target or backup key yet" in text


def test_a_poc_box_opens_a_study_without_the_backup(
    lb: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TB_SAE_OFFICE_MAILBOX", "office@hospa.test")
    assert _open(lb, monkeypatch, "VALIDATION", _mount(tmp_path, [], backup_key=False))[0] == 303
