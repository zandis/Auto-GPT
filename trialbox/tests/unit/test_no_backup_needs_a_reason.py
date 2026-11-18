"""D-1321 (plan 10 row 10G-3, review 16-18): ``--no-backup`` is refused on a PRODUCTION box unless a reason is given
(``--no-backup-reason REASON``), at both entries: ``tools/apply_update.sh`` and ``python -m tools.trialbox update``.
DEV, TEST and VALIDATION take it as before. The reason is audited as ``update.backup_skipped`` and written in the
history, as ``--allow-downgrade REASON`` is. Synthetic folders only."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools import update_status as us
from tools.trialbox import __main__ as tb_main
from tools.trialbox import update as up

ROOT = Path(__file__).resolve().parents[2]


def _install(tmp: Path, env_line: str | None, *, marker: bool = True, rehearsal_mark: bool = False) -> Path:
    """A copy of the shell entry in an install folder; the marker makes any run that passes the option check stop
    at the next refusal (exit 1, "an update is unfinished"), before anything is read or changed."""
    root = tmp / "install"
    (root / "tools").mkdir(parents=True)
    (root / "deploy/updates").mkdir(parents=True)
    (root / "tools/apply_update.sh").write_bytes((ROOT / "tools/apply_update.sh").read_bytes())
    if env_line is not None:
        (root / "deploy/.env").write_text(f"POSTGRES_PASSWORD=synthetic-only\n{env_line}\n", encoding="utf-8")
    if rehearsal_mark:
        (root / "deploy/site").mkdir(parents=True)
        (root / "deploy/site/rehearsal.json").write_text("{}", encoding="utf-8")
    if marker:
        (root / "deploy/updates" / us.MARKER).write_text(json.dumps({"bundle_id": "B1", "step": "apply"}))
    (tmp / "b.tar").write_bytes(b"")
    return root


def _sh(root: Path, tmp: Path, *opts: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", str(root / "tools/apply_update.sh"), str(tmp / "b.tar"), *opts],
                          capture_output=True, text=True, check=False)  # fmt: skip


@pytest.mark.parametrize("env_line", ["TB_ENV=PRODUCTION", "TB_ENV=production", "TB_ENV=SOMETHING", None])
def test_the_shell_entry_refuses_no_backup_without_a_reason_on_a_production_box(
    tmp_path: Path, env_line: str | None
) -> None:
    root = _install(tmp_path, env_line)
    r = _sh(root, tmp_path, "--no-backup")
    assert r.returncode == 2, r.stderr
    assert "--no-backup on a PRODUCTION box needs --no-backup-reason REASON" in r.stderr
    assert "an update is unfinished" not in r.stderr  # refused before anything else is read


def test_the_shell_entry_takes_no_backup_with_a_reason_on_a_production_box(tmp_path: Path) -> None:
    root = _install(tmp_path, "TB_ENV=PRODUCTION")
    r = _sh(root, tmp_path, "--no-backup", "--no-backup-reason", "vendor ticket 42: the backup share is down")
    assert r.returncode == 1 and "an update is unfinished" in r.stderr  # past the option check


@pytest.mark.parametrize("env_line", ["TB_ENV=DEV", "TB_ENV=TEST", "TB_ENV=VALIDATION", "TB_ENV='validation'"])
def test_the_shell_entry_takes_no_backup_as_before_off_production(tmp_path: Path, env_line: str) -> None:
    root = _install(tmp_path, env_line)
    r = _sh(root, tmp_path, "--no-backup")
    assert r.returncode == 1 and "an update is unfinished" in r.stderr, r.stderr


def test_a_rehearsal_box_with_no_environment_yet_is_test(tmp_path: Path) -> None:
    root = _install(tmp_path, None, rehearsal_mark=True)
    r = _sh(root, tmp_path, "--no-backup")
    assert r.returncode == 1 and "an update is unfinished" in r.stderr, r.stderr


def test_the_shell_entry_without_no_backup_is_unchanged_on_production(tmp_path: Path) -> None:
    root = _install(tmp_path, "TB_ENV=PRODUCTION")
    r = _sh(root, tmp_path)
    assert r.returncode == 1 and "an update is unfinished" in r.stderr


def test_a_reason_alone_or_an_empty_reason_is_a_usage_error(tmp_path: Path) -> None:
    root = _install(tmp_path, "TB_ENV=TEST")
    r = _sh(root, tmp_path, "--no-backup-reason", "why")
    assert r.returncode == 2 and "goes with --no-backup" in r.stderr
    r = _sh(root, tmp_path, "--no-backup", "--no-backup-reason", "")
    assert r.returncode != 0 and "needs a reason" in r.stderr


def _cli(deploy: Path, *opts: str) -> list[str]:
    return ["update", "--stage", str(deploy / "s"), "--summary", str(deploy / "s/summary.json"),
            "--deploy", str(deploy), *opts]  # fmt: skip


@pytest.mark.parametrize("env_line", ["TB_ENV=PRODUCTION", None])
def test_the_python_entry_refuses_no_backup_without_a_reason_on_a_production_box(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], env_line: str | None
) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    if env_line:
        (deploy / ".env").write_text(env_line + "\n", encoding="utf-8")
    called: list[Any] = []

    def fake(*a: Any, **k: Any) -> int:
        called.append((a, k))
        return 0

    monkeypatch.setattr(up, "main_apply", fake)
    assert tb_main.main(_cli(deploy, "--no-backup")) == 2
    assert "needs --no-backup-reason REASON" in capsys.readouterr().err and called == []
    assert tb_main.main(_cli(deploy, "--no-backup", "--no-backup-reason", "  ")) == 2 and called == []
    assert tb_main.main(_cli(deploy, "--no-backup", "--no-backup-reason", " ticket 42 ")) == 0
    assert called[-1][1] == {"backup": False, "no_backup_reason": "ticket 42"}
    assert tb_main.main(_cli(deploy)) == 0 and called[-1][1] == {"backup": True, "no_backup_reason": None}
    assert tb_main.main(_cli(deploy, "--no-backup-reason", "x")) == 2  # a reason alone


@pytest.mark.parametrize("env_line", ["TB_ENV=DEV", "TB_ENV=TEST", "TB_ENV=VALIDATION"])
def test_the_python_entry_takes_no_backup_as_before_off_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env_line: str
) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text(env_line + "\n", encoding="utf-8")
    called: list[Any] = []

    def fake(*a: Any, **k: Any) -> int:
        called.append(k)
        return 0

    monkeypatch.setattr(up, "main_apply", fake)
    assert tb_main.main(_cli(deploy, "--no-backup")) == 0
    assert called == [{"backup": False, "no_backup_reason": None}]


def test_the_demo_target_is_dev(tmp_path: Path) -> None:
    assert not up.no_backup_refused("demo", tmp_path / "deploy")
    assert up.no_backup_refused("compose", tmp_path / "deploy")  # no deploy/.env yet: PRODUCTION (D-127)


class _Box:
    """The update path's box, recording what it is asked to do (no docker, no database)."""

    name = "recorder"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.audits: list[tuple[str, dict[str, Any]]] = []

    def running(self) -> bool:
        return True

    def backup(self, plan: up.Plan, rb: Path) -> str:
        self.calls.append("backup")
        return "nas"

    def snapshot(self, plan: up.Plan, rb: Path, point: up.Point) -> None:
        self.calls.append("snapshot")

    def apply(self, plan: up.Plan, rb: Path, point: up.Point) -> list[str]:
        self.calls.append("apply")
        return []

    def restart(self, plan: up.Plan) -> None:
        self.calls.append("restart")

    def post_apply(self, plan: up.Plan) -> list[str]:
        return []

    def check(self, plan: up.Plan) -> str:
        return "healthy"

    def rollback(self, plan: up.Plan, rb: Path, point: up.Point) -> None:
        self.calls.append("rollback")

    def audit(self, event: str, plan: up.Plan, detail: dict[str, Any]) -> None:
        self.audits.append((event, detail))


def _plan(tmp: Path) -> up.Plan:
    stage = tmp / "stage-B1"
    stage.mkdir(parents=True, exist_ok=True)
    compat = {"format": us.COMPAT_FORMAT, "bundle_id": "B1", "rows": [{}], "provides": {}}
    return up.Plan("B1", "f" * 64, "vendor", [], stage, release_seq=2, compat=compat,
                   trust_after={"format": us.TRUST_FORMAT, "keys": {"ed25519:" + "1" * 16: {}}})  # fmt: skip


def _history(updates: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (updates / "history.jsonl").read_text(encoding="utf-8").splitlines()]


def test_the_reason_is_audited_and_in_the_history(tmp_path: Path) -> None:
    box, updates = _Box(), tmp_path / "updates"
    plan = _plan(tmp_path)
    plan.no_backup_reason = "vendor ticket 42: the backup share is down"
    assert up.Updater(box, updates, say=lambda _m: None).run(plan, backup=False)["ok"]
    assert "backup" not in box.calls
    assert [e for e, _ in box.audits] == ["update.backup_skipped", "update.applied"]
    assert box.audits[0][1] == {"bundle_id": "B1", "reason": "vendor ticket 42: the backup share is down"}
    assert box.audits[1][1]["backup"] is False
    skipped = [h for h in _history(updates) if str(h.get("step", "")).startswith("backup skipped")]
    assert len(skipped) == 1 and "the backup share is down" in json.dumps(skipped[0])


def test_no_backup_without_a_reason_is_audited_as_before(tmp_path: Path) -> None:
    box, updates = _Box(), tmp_path / "updates"
    assert up.Updater(box, updates, say=lambda _m: None).run(_plan(tmp_path), backup=False)["ok"]
    assert [e for e, _ in box.audits] == ["update.applied"] and box.audits[0][1]["backup"] is False


def test_the_new_event_has_its_label_in_three_languages() -> None:
    from console import i18n_audit

    en, ja, zh = i18n_audit.EVENTS["update.backup_skipped"]
    assert en and ja and zh and len({en, ja, zh}) == 3
