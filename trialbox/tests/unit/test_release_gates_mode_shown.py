"""I-7 (D-884, the integrator's option (a)): the gates' vuln mode, already in release.json (``gates.vuln_mode``), is
said where people read the release: the box's installed record and `apply_update.sh status`, the install summary and
`tools.release check`. "report" is never read as a green release."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_release_dirty_refused import EnvBox, _release, _upd, _with
from tools import release
from tools import update_status as us

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.nodb


def _rel(mode: str | None) -> dict[str, Any]:
    rel = _release(False)
    if mode is not None:
        rel["gates"] = {"vuln_mode": mode}
    return rel


@pytest.mark.parametrize("mode", ["block", "report"])
def test_the_installed_record_keeps_the_gates_mode(tmp_path: Path, mode: str) -> None:
    assert _upd(EnvBox("TEST"), tmp_path).run(_with(tmp_path, _rel(mode)))["ok"]
    assert us.installed(tmp_path / "updates")["vuln_mode"] == mode


def test_a_release_without_gates_records_no_mode(tmp_path: Path) -> None:
    assert _upd(EnvBox("TEST"), tmp_path).run(_with(tmp_path, _rel(None)))["ok"]
    assert "vuln_mode" not in us.installed(tmp_path / "updates")


def _status(installed: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> str:
    us._print_status({"installed": installed, "in_progress": False, "trusted_keys": [], "history": [],
                      "left_over_rollback_points": []})  # fmt: skip
    return capsys.readouterr().out


def test_status_says_report_mode_is_not_a_green_release(capsys: pytest.CaptureFixture[str]) -> None:
    out = _status({"release_seq": 3, "bundle_id": "b", "vuln_mode": "report"}, capsys)
    assert "release gates: report" in out and "not a green release" in out
    out = _status({"release_seq": 3, "bundle_id": "b", "vuln_mode": "block"}, capsys)
    assert "release gates: block" in out and "not a green release" not in out
    assert "release gates" not in _status({"release_seq": 0, "bundle_id": None}, capsys)


def _bundle(path: Path, mode: str) -> Path:
    with tarfile.open(path, "w") as tf:
        data = json.dumps({"gates": {"vuln_mode": mode}}).encode()
        info = tarfile.TarInfo("release.json")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return path


@pytest.mark.parametrize(("mode", "said"), [("block", "gates block"), ("report", "gates report: not a green release")])
def test_release_check_names_the_mode(tmp_path: Path, mode: str, said: str) -> None:
    assert release.gates_mode_line(_bundle(tmp_path / "b.tar", mode)) == said


def test_release_check_prints_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.setattr(release, "check_bundle", lambda _b: [])
    assert release.main(["check", str(_bundle(tmp_path / "b.tar", "report"))]) == 0
    assert "release check: PASS (b.tar; gates report: not a green release)" in capsys.readouterr().out


def test_the_install_summary_has_a_release_gates_line() -> None:
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    summary = text[text.index("TrialBox is running.") : text.index("EOT", text.index("TrialBox is running."))]
    assert "Release gates:" in summary and "$GATES_MODE" in summary
    assert "updates/installed.json" in text[text.index("GATES_MODE=") : text.index("GATES_MODE=") + 400]
