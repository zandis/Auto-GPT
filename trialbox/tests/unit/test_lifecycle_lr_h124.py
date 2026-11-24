"""H-124, the lifecycle review's Highs (lane LR, docs/reviews/lifecycle-deep-review-2026-11-24.md; the integrator's
7136231344 item 3): each reproduced at master, then its cell of the review's matrix filled.

* LR-9: after a power cut inside an update, the boot unit started the stack on a box between two releases. The start
  guard (``deploy/settings_guard.sh``, the unit's ExecStartPre) now refuses while the update's marker stands.
* LR-17: a first install that loaded its bundle and stopped before the stack ever ran refused the vendor's corrected
  release ("installed ... but not running"). A first load now marks its record (``loaded_only``), and install.sh's
  load takes the next release on a box that has that mark, no update history and no data volumes. A box that has run
  keeps its refusal word for word.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from tools import update_status as us
from tools.trialbox import update as up

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "deploy" / "settings_guard.sh"
UNIT = ROOT / "deploy" / "systemd" / "trialbox.service"


def _guard(deploy: Path) -> subprocess.CompletedProcess[str]:
    """The unit's ExecStartPre line, as systemd runs it (the real script, the box's deploy folder)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")}
    return subprocess.run(["/bin/sh", str(GUARD), str(deploy)], env=env, capture_output=True, text=True, check=False,
                          timeout=60)  # fmt: skip


def _box(tmp_path: Path, tb_env: str) -> Path:
    deploy = tmp_path / "deploy"
    (deploy / "updates").mkdir(parents=True)
    (deploy / ".env").write_text(f"TB_ENV={tb_env}\n", encoding="utf-8")
    return deploy


def test_lr9_the_unit_s_start_guard_is_settings_guard() -> None:
    pre = [ln for ln in UNIT.read_text(encoding="utf-8").splitlines() if ln.startswith("ExecStartPre=")]
    assert pre and "settings_guard.sh @TB_ROOT@/deploy" in pre[0]


@pytest.mark.parametrize("tb_env", ["PRODUCTION", "TEST"])
def test_lr9_the_box_does_not_start_while_an_update_is_unfinished(tmp_path: Path, tb_env: str) -> None:
    """A power cut (or kill -9) inside an update left its marker: at the next boot the start guard refuses, on every
    box (a box between two releases is not shown whole: H-94 depends (1)), and names the two commands."""
    deploy = _box(tmp_path, tb_env)
    (deploy / "updates" / "IN_PROGRESS.json").write_text(
        json.dumps({"bundle_id": "R2", "step": "migrate and restart", "release_seq": 2}), encoding="utf-8")  # fmt: skip
    r = _guard(deploy)
    assert r.returncode == 1, r.stdout + r.stderr
    said = " ".join(r.stderr.split())
    assert "update R2 is unfinished (step migrate and restart)" in said
    assert "tools/apply_update.sh status" in said and "tools/apply_update.sh rollback R2" in said
    assert "warning" not in said


def test_lr9_without_a_marker_the_box_starts_as_before(tmp_path: Path) -> None:
    r = _guard(_box(tmp_path, "PRODUCTION"))
    assert r.returncode == 0, r.stdout + r.stderr


def test_lr9_the_box_rehearsal_runs_the_guard_on_its_real_box() -> None:
    """The real path (the rule for a new guard on the start path): the box rehearsal's doctor phase plants a marker on
    the installed box and runs the unit's start guard, which must refuse."""
    text = (ROOT / "tools" / "rehearse_box" / "box.sh").read_text(encoding="utf-8")
    doctor = text[text.index("\ndoctor)\n") : text.index("\n  ;;\n", text.index("\ndoctor)\n"))]
    assert 'sh "$BOX/deploy/settings_guard.sh" "$BOX/deploy"' in doctor and "IN_PROGRESS.json" in doctor
    assert "update rehearsal-lr9 is unfinished" in doctor


# ------------------------------------------------------------------------------------------------ LR-17
def _stage(tmp_path: Path, bid: str, seq: int, model: str) -> tuple[Path, Path]:
    """A verified stage as apply_update.sh leaves it (the summary beside the staged manifest): one model file."""
    stage = tmp_path / f"stage-{bid}"
    (stage / "model/judge").mkdir(parents=True)
    (stage / "model/judge/config.json").write_text(model)
    body = json.dumps({"bundle": bid}).encode()
    (stage / "manifest.json").write_bytes(body)
    compat = {"format": us.COMPAT_FORMAT, "bundle_id": bid, "rows": [{}]}
    summary = stage / "summary.json"
    summary.write_text(json.dumps({"bundle_id": bid, "signer": "v", "files": [], "release_seq": seq,
                                   "manifest_sha256": hashlib.sha256(body).hexdigest(), "compat": compat,
                                   "trust_sha256": None}))  # fmt: skip
    return stage, summary


def _docker(tmp_path: Path, volumes: str) -> str:
    """A stand-in docker: `volume ls` answers the compose project's volumes (none: the stack never ran)."""
    f = tmp_path / "docker-stand-in"
    f.write_text(f"#!/bin/sh\ncase \"$*\" in *\"volume ls\"*) printf '%s' '{volumes}';; esac\nexit 0\n")
    f.chmod(0o755)
    return str(f)


@pytest.fixture()
def first_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """install.sh's first load of release B1 on a fresh host (TB_SKIP_AUDIT, the box not running), then nothing: the
    install stopped before the stack ever ran."""
    deploy = tmp_path / "deploy"
    monkeypatch.setenv("TB_MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("TB_COMPOSE", "false")  # `compose ps` fails: not running
    monkeypatch.setenv("TB_DOCKER", _docker(tmp_path, ""))
    monkeypatch.setenv("TB_SKIP_AUDIT", "1")
    stage, summary = _stage(tmp_path, "B1", 1, "first")
    assert up.main_apply(stage, summary, "compose", deploy) == 0
    assert us.installed(deploy / "updates")["bundle_id"] == "B1"
    return deploy


def test_lr17_a_loaded_never_started_box_takes_the_corrected_release(first_load: Path, tmp_path: Path) -> None:
    """Reproduced at master: refused, "installed ... but not running; start it" (it never ran and cannot start)."""
    stage, summary = _stage(tmp_path, "B2", 2, "corrected")
    assert up.main_apply(stage, summary, "compose", first_load) == 0
    assert us.installed(first_load / "updates")["bundle_id"] == "B2"
    assert (tmp_path / "models/judge/config.json").read_text() == "corrected"


def test_lr17_a_box_that_has_run_keeps_its_refusal(
    first_load: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same record, but the stack ran (its data volumes exist): refused as before, nothing loaded."""
    monkeypatch.setenv("TB_DOCKER", _docker(tmp_path, "trialbox_pgdata"))
    stage, summary = _stage(tmp_path, "B2", 2, "corrected")
    assert up.main_apply(stage, summary, "compose", first_load) == 1
    assert "but not running (crashed, restarting, or its compose ps failed); start it" in capsys.readouterr().out
    assert us.installed(first_load / "updates")["bundle_id"] == "B1"
    assert (tmp_path / "models/judge/config.json").read_text() == "first"


def test_lr17_only_install_sh_s_load_takes_it(
    first_load: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain update (not install.sh's load) on the never-started box is refused as before: start it first."""
    monkeypatch.delenv("TB_SKIP_AUDIT")
    stage, summary = _stage(tmp_path, "B2", 2, "corrected")
    assert up.main_apply(stage, summary, "compose", first_load) == 1
    assert us.installed(first_load / "updates")["bundle_id"] == "B1"


def test_lr17_a_record_without_the_first_load_s_mark_keeps_its_refusal(first_load: Path, tmp_path: Path) -> None:
    """A box installed before H-124 (its record has no loaded_only): refused as before, whatever its volumes say."""
    rec = us.installed(first_load / "updates")
    rec.pop("loaded_only", None)
    us.write_atomic(first_load / "updates" / us.INSTALLED, rec)
    stage, summary = _stage(tmp_path, "B2", 2, "corrected")
    assert up.main_apply(stage, summary, "compose", first_load) == 1
