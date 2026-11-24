"""V-18b (D-1183, V18-01): the FHIR store keeps its ``$lookup`` and ``$validate-code`` answers for minutes, and no
operation of the pinned store clears them (``$reindex-terminology`` fails with its full-text search off). So after a
load that changed a system, ``deploy/terminology-update.sh`` (and an update's code-system step) restarts the store and
waits until it is healthy, and the report says so for the doctor. Shown on the pinned image: a code a new version
dropped stayed valid until the restart, then was not found (38 s)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tools import terminology_load as tl

ROOT = Path(__file__).resolve().parents[2]

LOADED: dict[str, object] = {"release": "TL-000000000001", "fhir": [{"key": "icd10cm", "state": "loaded", "detail": "ICD-10-CM 2027"},
                                                {"key": "atc", "state": "skipped", "detail": "absent", "absent": True}],
          "omop": [], "problems": []}  # fmt: skip
SAME: dict[str, object] = {**LOADED, "fhir": [{"key": "icd10cm", "state": "unchanged", "detail": "ICD-10-CM 2027"}]}


def _box(tmp_path: Path, report: dict[str, object], health: str) -> tuple[Path, Path, dict[str, str]]:
    """A copy of the update step beside the real tools, and a docker that logs each call, prints ``report`` for the
    load, and gives ``health`` for the store."""
    (tmp_path / "deploy").mkdir()
    shutil.copy(ROOT / "deploy/terminology-update.sh", tmp_path / "deploy/terminology-update.sh")
    (tmp_path / "tools").symlink_to(ROOT / "tools")
    calls = tmp_path / "calls"
    (tmp_path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "docker").write_text(
        "#!/bin/sh\n"
        f'echo "$*" >> {calls}\n'
        'case "$*" in\n'
        f'  *"terminology_load load"*) cat {tmp_path / "report.json"} ;;\n'
        '  *"ps -q fhir-store"*) echo c0ffee ;;\n'
        f"  inspect*) echo {health} ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (bin_ / "docker").chmod(0o755)
    env = {"PATH": f"{bin_}:{os.environ['PATH']}", "TB_FHIR_RESTART_TRIES": "2", "TB_FHIR_RESTART_STEP": "0"}
    return tmp_path / "deploy/site/terminology-load.json", calls, env


def _run(tmp_path: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(tmp_path / "deploy/terminology-update.sh"), "--readers-only"], env=env,
                          capture_output=True, text=True, check=False, timeout=60)  # fmt: skip


def test_a_load_that_changed_a_system_restarts_the_store_and_waits_until_it_answers(tmp_path: Path) -> None:
    report, calls, env = _box(tmp_path, LOADED, "healthy")
    r = _run(tmp_path, env)
    assert r.returncode == 0, r.stderr
    assert any(c.endswith("restart fhir-store") for c in calls.read_text("utf-8").splitlines())
    done = json.loads(report.read_text("utf-8"))["store_restart"]
    assert done["answered"] is True and done["systems"] == ["icd10cm"]
    assert tl.restart_line(json.loads(report.read_text("utf-8")))[0] == "PASS"


def test_a_load_that_changed_nothing_leaves_the_store_running(tmp_path: Path) -> None:
    report, calls, env = _box(tmp_path, SAME, "healthy")
    assert _run(tmp_path, env).returncode == 0
    assert not any("restart" in c for c in calls.read_text("utf-8").splitlines())
    assert "store_restart" not in json.loads(report.read_text("utf-8"))


def test_a_store_that_does_not_answer_again_is_a_warning_never_a_stop(tmp_path: Path) -> None:
    report, _calls, env = _box(tmp_path, LOADED, "starting")
    r = _run(tmp_path, env)
    assert r.returncode == 0 and "did not answer after its restart" in r.stderr
    rep = json.loads(report.read_text("utf-8"))
    assert rep["store_restart"]["answered"] is False
    assert tl.restart_line(rep) == ("WARN", tl.restart_line(rep)[1]) and "did not answer" in tl.restart_line(rep)[1]


@pytest.mark.parametrize(("report", "status"), [(LOADED, "WARN"), (SAME, "PASS")])
def test_the_doctor_warns_when_a_changed_system_was_not_followed_by_a_restart(
    tmp_path: Path, report: dict[str, object], status: str
) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / tl.REPORT).write_text(json.dumps(report), encoding="utf-8")
    got, said = tl.doctor_line(site, tmp_path / "not-here")
    assert got == "WARN"  # the terminology folder cannot be read here: the release was not compared
    assert ("was not restarted after loading icd10cm" in said) is (status == "WARN")


def test_an_update_restarts_the_store_after_its_code_systems(tmp_path: Path) -> None:
    """The update's code-system step (tools/trialbox/update.py) restarts the store the same way, through its own
    runner: a failed restart is in the report, never a stop of the update."""
    from tools.trialbox import update as up

    seen: list[list[str]] = []

    def run(cmd: list[str], **_: object) -> str:
        seen.append(cmd)
        if "up" in cmd:
            raise up.UpdateFailed("not healthy")
        return ""

    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    path = deploy / "site" / tl.REPORT
    path.write_text(json.dumps(LOADED), encoding="utf-8")
    up.ComposeBox(deploy, run=run)._restart_fhir_store(path)
    assert [c[-2:] for c in seen] == [["restart", "fhir-store"], ["900", "fhir-store"]]
    assert json.loads(path.read_text("utf-8"))["store_restart"]["answered"] is False
    assert [p.name for p in path.parent.iterdir()] == [tl.REPORT]  # written through a renamed temporary file


def test_the_report_is_written_whole_or_not_at_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """OCR pass (#639 7119659794): the restart's report is not rewritten in place. A write that fails before the
    rename leaves the earlier report as it was, and no temporary file beside it."""
    import os

    path = tmp_path / tl.REPORT
    tl.write_report(path, LOADED)
    before = path.read_bytes()

    def broken(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError, match="disk full"):
        tl.write_report(path, tl.restarted(LOADED, True, 38, "2026-11-24T00:00:00+00:00"))
    assert path.read_bytes() == before and [p.name for p in tmp_path.iterdir()] == [tl.REPORT]
    monkeypatch.undo()
    tl.write_report(path, tl.restarted(LOADED, True, 38, "2026-11-24T00:00:00+00:00"))
    assert json.loads(path.read_text("utf-8"))["store_restart"]["seconds"] == 38
    assert [p.name for p in tmp_path.iterdir()] == [tl.REPORT]
