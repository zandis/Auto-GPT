"""When the drill's first step (the box ran the whole path, e2e_simple) fails, the drill says which checks of
e2e_simple failed, with their detail, and leaves the work folder as the failed run left it. On 2026-11-13 the step
failed once in a train's run and the evidence was lost: the drill kept one bool and went on to wipe the folder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tools import backup_drill, e2e_simple, pglocal

pytestmark = pytest.mark.nodb


def _failed_run(work: Path, password: str, lang: str) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    (work / "left-by-the-run.txt").write_text("evidence", encoding="utf-8")
    good, bad = e2e_simple.Stage("criteria"), e2e_simple.Stage("mail")
    good.check("criteria compiled", True, "12 atoms")
    bad.check("the list went out", False, "no message in the outbox after 30 s: " + "x" * 400)
    bad.check("the report is attached", True)
    return {"ok": False, "stages": [good, bad], "seconds": 1.0}


def test_a_failed_first_step_names_the_failing_checks_and_keeps_the_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(pglocal, "for_work", lambda work: "postgresql://unused")
    monkeypatch.setattr(e2e_simple, "run", _failed_run)
    out = backup_drill.run(tmp_path)
    assert out["ok"] is False
    assert out["checks"][0][:2] == ("the box ran the whole path (e2e_simple)", False)
    named = [c for c in out["checks"] if c[0] == "e2e_simple: mail: the list went out"]
    assert len(named) == 1 and named[0][1] is False
    assert named[0][2].startswith("no message in the outbox after 30 s") and len(named[0][2]) > 400  # whole
    assert not [c for c in out["checks"] if "criteria" in c[0] or "attached" in c[0]]  # only what failed
    assert out["kept"] == str(tmp_path / "box-run")
    assert (tmp_path / "box-run" / "left-by-the-run.txt").read_text(encoding="utf-8") == "evidence"  # not wiped
    assert len(out["checks"]) == 2  # the drill stops there: backup, wipe and restore of a broken run prove nothing


def test_the_command_prints_them_and_where_the_folder_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(pglocal, "for_work", lambda work: "postgresql://unused")
    monkeypatch.setattr(e2e_simple, "run", _failed_run)
    assert backup_drill.main(["--dir", str(tmp_path / "drill")]) == 1
    text = capsys.readouterr().out
    assert "FAIL  the box ran the whole path (e2e_simple)" in text
    assert "FAIL  e2e_simple: mail: the list went out  (no message in the outbox after 30 s" in text
    assert f"the work folder is kept: {tmp_path / 'drill' / 'box-run'}" in text
    assert "backup drill FAILED" in text
