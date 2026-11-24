"""H-124, the lifecycle review's Highs (lane LR, docs/reviews/lifecycle-deep-review-2026-11-24.md; the integrator's
7136231344 item 3): each reproduced at master, then its cell of the review's matrix filled.

* LR-9: after a power cut inside an update, the boot unit started the stack on a box between two releases. The start
  guard (``deploy/settings_guard.sh``, the unit's ExecStartPre) now refuses while the update's marker stands.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

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
