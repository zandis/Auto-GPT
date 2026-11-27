"""P-33 (E2E R1): after five applied updates and downgrades the admin Operations page still said "Update bundle: none
applied yet ... No update has run on this box". The page reads the status the host's ops runner writes, and on the
box the runner's timer never ran (the poc profile installs no units), so nothing wrote it.

``trialbox update`` now writes that status at its end, applied or rolled back: the page names the bundle at once on
every box. The class (RC2/RC3): a state change the box made is visible on the page that reports it, without a
background unit having to run first."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.trialbox import ops as tb_ops
from tools.trialbox import update as tb_update
from tools.trialbox.__main__ import main as trialbox_main

pytestmark = pytest.mark.nodb


def _box(tmp: Path) -> Path:
    deploy = tmp / "deploy"
    (deploy / "updates").mkdir(parents=True)
    (deploy / ".env").write_text(f"TB_ENV=VALIDATION\nTB_OPS_DIR={tmp / 'ops'}\n", encoding="utf-8")
    return deploy


def _applied(deploy: Path, bundle: str, outcome: str) -> None:
    rows = [{"at": "2026-11-27T01:00:00+00:00", "bundle": bundle, "step": "backup", "ok": True}]
    if outcome == "applied":
        rows.append({"at": "2026-11-27T01:05:00+00:00", "bundle": bundle, "step": "audited update.applied", "ok": True})
    else:
        rows += [{"at": "2026-11-27T01:05:00+00:00", "bundle": bundle, "step": "check", "ok": False},
                 {"at": "2026-11-27T01:06:00+00:00", "bundle": bundle, "step": "rollback", "ok": True}]  # fmt: skip
    with (deploy / "updates" / "history.jsonl").open("a", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)


def _update(tmp: Path, deploy: Path, monkeypatch: pytest.MonkeyPatch, bundle: str, outcome: str) -> int:
    def apply(*_a: Any, **_k: Any) -> int:  # the update itself, as its history file records it
        _applied(deploy, bundle, outcome)
        return 0 if outcome == "applied" else 1

    monkeypatch.setattr(tb_update, "main_apply", apply)
    monkeypatch.delenv("TB_OPS_DIR", raising=False)
    return trialbox_main(["update", "--stage", str(tmp / "stage"), "--summary", str(tmp / "s.json"),
                          "--deploy", str(deploy), "--target", "compose"])  # fmt: skip


def _status(tmp: Path) -> dict[str, Any]:
    st: dict[str, Any] = json.loads((tmp / "ops" / "status.json").read_text(encoding="utf-8"))
    return st


def test_the_page_knows_the_update_without_the_ops_timer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deploy = _box(tmp_path)
    assert _update(tmp_path, deploy, monkeypatch, "trialbox-r1plus1", "applied") == 0
    st = _status(tmp_path)
    assert st["version"]["bundle"] == "trialbox-r1plus1"
    assert st["updates"][0]["outcome"] == "applied"


def test_a_rolled_back_update_is_on_the_page_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deploy = _box(tmp_path)
    assert _update(tmp_path, deploy, monkeypatch, "trialbox-bad", "rolled_back") == 1
    assert _status(tmp_path)["updates"][0]["outcome"] == "rolled_back"


def test_a_status_that_cannot_be_written_never_fails_the_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    deploy = _box(tmp_path)
    (tmp_path / "ops").write_text("a file where the folder goes", encoding="utf-8")
    assert _update(tmp_path, deploy, monkeypatch, "trialbox-r1plus1", "applied") == 0
    assert "not refreshed" in capsys.readouterr().err
    assert callable(tb_ops.refresh_status)
