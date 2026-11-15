"""T-695 (D-752): update, stop and boot at scale (scale review F-09, F-10, F-24)."""

from __future__ import annotations

import contextlib
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.trialbox import bootwait, procgroup
from tools.trialbox import update as up

ROOT = Path(__file__).resolve().parents[2]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _orphan_maker(tmp: Path) -> tuple[list[str], Path]:
    """A shell that starts a long child and waits on it: the shape of ``sh apply_update.sh`` and its updater."""
    pidfile = tmp / "child.pid"
    return ["sh", "-c", f"sleep 300 & echo $! > {pidfile}; wait"], pidfile


def _gone(pid: int) -> bool:
    for _ in range(50):
        if not _alive(pid):
            return True
        with contextlib.suppress(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)
        time.sleep(0.1)
    return False


@pytest.mark.parametrize("runner", ["procgroup", "update", "ops"])
def test_a_limit_kills_the_whole_group_never_an_orphan_left(tmp_path: Path, runner: str) -> None:
    from tools.trialbox import ops

    argv, pidfile = _orphan_maker(tmp_path)
    with pytest.raises(subprocess.TimeoutExpired):
        if runner == "procgroup":
            procgroup.run(argv, timeout=1, stdout=subprocess.PIPE)
        elif runner == "update":
            up.run_cmd(argv, timeout=1)
        else:
            ops.run_cmd(argv, timeout=1)
    assert _gone(int(pidfile.read_text().strip())), "the child of the shell outlived the limit"


def test_a_command_inside_its_limit_answers_as_before() -> None:
    r = procgroup.run(["sh", "-c", "echo out; echo err >&2; exit 3"], timeout=10, stdout=subprocess.PIPE,
                      stderr=subprocess.PIPE, text=True)  # fmt: skip
    assert (r.returncode, r.stdout, r.stderr) == (3, "out\n", "err\n")


@pytest.mark.parametrize(("answer", "said"), [("2\n", r"2 job\(s\) running"), ("", "could not be counted")])
def test_the_update_never_stops_the_services_under_a_running_job(tmp_path: Path, answer: str, said: str) -> None:
    calls: list[str] = []

    def run(argv: list[str], **_: Any) -> str:
        line = " ".join(argv)
        calls.append(line)
        if "FROM orch.jobs" in line:
            if not answer:
                raise up.UpdateFailed("the database did not answer")
            return answer
        return "1000\n" if "pg_database_size" in line else ""

    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "backup.pub").write_text("k", encoding="utf-8")
    (tmp_path / ".env").write_text(f"TB_BACKUP_TARGETS={tmp_path / 'nas'}\n", encoding="utf-8")
    box = up.ComposeBox(tmp_path, run=run)
    with pytest.raises(up.UpdateFailed, match=said):
        box.backup(None, tmp_path / "rb")  # type: ignore[arg-type]
    assert not any(" stop " in f" {c} " for c in calls)


def test_the_database_has_time_for_its_shutdown_checkpoint_and_systemd_waits_for_it() -> None:
    svcs = bootwait.services([ROOT / "deploy" / "docker-compose.yml"])
    assert bootwait.seconds(svcs["db"]["stop_grace_period"]) >= 120  # F-10: the review's floor
    assert bootwait.stop_wait_s(svcs) >= 120
    unit = (ROOT / "deploy" / "systemd" / "trialbox.service").read_text(encoding="utf-8")
    assert "--wait-timeout @TB_BOOT_WAIT@" in unit and "TimeoutStopSec=@TB_STOP_LIMIT@" in unit
    sh = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert "tools.trialbox.bootwait --deploy deploy --stop" in sh and "@TB_STOP_LIMIT@#$(( STOP_WAIT + 10 ))" in sh


def test_the_boot_wait_is_the_longest_start_period_and_retries(tmp_path: Path) -> None:
    (tmp_path / "a.yml").write_text(yaml.safe_dump({"services": {
        "db": {"healthcheck": {"test": ["CMD", "true"], "interval": "10s", "timeout": "5s", "retries": 10}},
        "verifier": {"healthcheck": {"test": ["CMD", "true"], "start_period": "900s", "interval": "30s",
                                     "timeout": "10s", "retries": 5}},
        "plain": {"image": "x"},
    }}), encoding="utf-8")  # fmt: skip
    (tmp_path / "b.yml").write_text(yaml.safe_dump({"services": {
        "verifier": {"healthcheck": {"start_period": "1m"}, "stop_grace_period": "2m30s"}}}), encoding="utf-8")  # fmt: skip
    svcs = bootwait.services([tmp_path / "a.yml"])
    assert bootwait.start_wait_s(svcs) == 900 + 5 * 40  # F-24: the verifier's start period is not the whole wait
    both = bootwait.services([tmp_path / "a.yml", tmp_path / "b.yml"])  # a later file's fields win
    assert bootwait.start_wait_s(both) == 60 + 5 * 40 and bootwait.stop_wait_s(both) == 150
    assert bootwait.stop_wait_s(svcs) == bootwait.STOP_DEFAULT_S


def test_the_update_waits_as_long_as_the_compose_files_allow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_INSTALL_UP_TIMEOUT", raising=False)
    (tmp_path / "docker-compose.yml").write_text(yaml.safe_dump({"services": {"m": {"healthcheck": {
        "test": ["CMD", "true"], "start_period": "1200s", "interval": "10s", "timeout": "5s", "retries": 4}}}}),
        encoding="utf-8")  # fmt: skip
    (tmp_path / ".env").write_text("", encoding="utf-8")
    assert up.ComposeBox(tmp_path, run=lambda *a, **k: "").up_wait() == 1260
    monkeypatch.setenv("TB_INSTALL_UP_TIMEOUT", "77")
    assert up.ComposeBox(tmp_path, run=lambda *a, **k: "").up_wait() == 77


def test_the_whole_update_is_limited_from_the_databases_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.trialbox import backup_schedule as bsch

    monkeypatch.setenv("TB_INSTALL_UP_TIMEOUT", "100")
    gb = 2**30

    def run(argv: list[str], **_: Any) -> str:
        line = " ".join(argv)
        return f"{(50 if '-d trialbox_wf' in line else 10) * gb}\n" if "pg_database_size" in line else ""

    (tmp_path / ".env").write_text("", encoding="utf-8")
    monkeypatch.setattr(bsch, "volume_bytes", lambda env, _: 40 * gb)
    box = up.ComposeBox(tmp_path, run=run)
    cfg = bsch.config(tmp_path, box.env)
    want = up.APPLY_FIXED_S + 2 * sum(cfg.timeout(n) or 0 for n in (50 * gb, 10 * gb, 100 * gb)) + 300
    assert box.apply_limit_s() == int(want) and box.apply_limit_s() > up.APPLY_FIXED_S  # type: ignore[operator]
    monkeypatch.setattr(bsch, "volume_bytes", lambda env, _: None)
    assert box.apply_limit_s() is None  # a size not known: no limit, each step keeps its own (D-455)


def test_a_compose_value_from_a_setting_is_read_with_the_box_s_value(tmp_path: Path) -> None:
    (tmp_path / "a.yml").write_text(yaml.safe_dump({"services": {"m": {
        "healthcheck": {"test": ["CMD", "true"], "start_period": "${TB_X_START:-100s}", "interval": "10s",
                        "timeout": "5s", "retries": 2}, "stop_grace_period": "${TB_X_STOP:-30s}"}}}), encoding="utf-8")  # fmt: skip
    assert bootwait.start_wait_s(bootwait.services([tmp_path / "a.yml"])) == 130
    svcs = bootwait.services([tmp_path / "a.yml"], {"TB_X_START": "400s", "TB_X_STOP": "1m"})
    assert bootwait.start_wait_s(svcs) == 430 and bootwait.stop_wait_s(svcs) == 60
