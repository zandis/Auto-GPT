"""The console's "Backup" on a site box starts the services again (review 2026-11-11-scale-timeouts, F-03).

``ComposeBox.backup`` stops every Python service for the dump and leaves them stopped on success: the update path
starts them in its later restart step. The operations runner has no later step, so a backup asked for on the console
left the orchestrator, the gateway and the console down until somebody started them by hand; at 50,000 patients the
dump alone takes tens of minutes, at 500,000 hours. Docker is a recording fake; the runner under test is the real one.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import pytest

from tools.trialbox import ops as tb_ops
from tools.trialbox import update as up
from tools.trialbox.update import PY_SERVICES, UpdateFailed


def _box(mp: pytest.MonkeyPatch, tmp_path: Path, fail_on: str = "") -> tuple[tb_ops.Box, list[list[str]]]:
    deploy, target = tmp_path / "deploy", tmp_path / "nas"
    (deploy / "secrets").mkdir(parents=True)
    target.mkdir()
    (deploy / "secrets" / "backup.pub").write_text("age1fake\n", encoding="utf-8")
    (deploy / ".env").write_text(f"TB_BACKUP_TARGETS={target}\n", encoding="utf-8")
    calls: list[list[str]] = []

    def run(argv: Any, stdout_file: Path | None = None, **_: Any) -> str:
        calls.append([str(a) for a in argv])
        if fail_on and fail_on in calls[-1]:
            raise UpdateFailed(f"{fail_on} failed")
        if stdout_file is not None:
            Path(stdout_file).write_bytes(b"dump")
        return ""

    # the runner makes its ComposeBox itself (the update path's command runner, not the operations runner's)
    mp.setattr(up, "ComposeBox", functools.partial(up.ComposeBox, run=run))
    return tb_ops.Box("compose", deploy, {"TB_BACKUP_TARGETS": str(target)}), calls


def _compose_verbs(calls: list[list[str]]) -> list[str]:
    return [next(a for a in c if a in ("stop", "start")) for c in calls if "stop" in c or "start" in c]


def test_a_console_backup_starts_the_services_it_stopped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    box, calls = _box(monkeypatch, tmp_path)
    tb_ops.OpsRunner(box, tb_ops.OpsDir(tmp_path / "ops")).do_backup({})
    assert _compose_verbs(calls) == ["stop", "start"]
    start = next(c for c in calls if "start" in c)
    assert set(PY_SERVICES) <= set(start)


def test_a_failed_console_backup_starts_them_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    box, calls = _box(monkeypatch, tmp_path, fail_on="pg_dump")
    with pytest.raises(UpdateFailed):
        tb_ops.OpsRunner(box, tb_ops.OpsDir(tmp_path / "ops")).do_backup({})
    assert _compose_verbs(calls) == ["stop", "start"]
