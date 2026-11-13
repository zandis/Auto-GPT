"""T-717b (D-547): the console's signing key is a pre-start step of its own.

T-717 (D-485) made the key inside the updater's model-key step, so the log named no such step and a box that is
not a GPU box read "model key: in place, or not a GPU box" while a key was made. Lane D's rule (UPDATE-PRESTART):
what a release needs on the host before its stack starts is a named step in ``tools/trialbox/prestart.py``, run by
the new release's tree on an update and by ``install.sh`` on a fresh install."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.trialbox import prestart
from tools.trialbox import svc_secrets as sx
from tools.trialbox import update as up

ROOT = Path(__file__).resolve().parents[2]
STEP = "actor signing key"

pytestmark = pytest.mark.nodb


def _old_box(tmp_path: Path) -> Path:
    """A box with per-service tokens from before T-717: no ``actor-sign.key``."""
    deploy = tmp_path / "deploy"
    sx.init(deploy, uid=None)
    sx.actor_sign_key_path(deploy).unlink()
    (deploy / ".env").write_text("TB_SITE_ID=T\n", encoding="utf-8")
    return deploy


def _command(deploy: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": "libs:services:."}
    return subprocess.run([sys.executable, "-m", "tools.trialbox", "pre-start", "--deploy", str(deploy)], cwd=ROOT,
                          capture_output=True, text=True, env=env, check=False)  # fmt: skip


def test_the_step_is_named_and_comes_after_the_two_every_release_ran() -> None:
    assert [n for n, _ in prestart.STEPS][:3] == ["image pins", "model key", STEP]


def test_the_command_makes_the_key_and_says_so_then_keeps_it(tmp_path: Path) -> None:
    deploy = _old_box(tmp_path)
    r = _command(deploy)
    assert r.returncode == 0, r.stderr
    assert f"pre-start: {STEP}: made now" in r.stdout, r.stdout
    made = sx.actor_sign_key_path(deploy).read_text(encoding="utf-8").strip()
    assert len(made) == 64 and sx.actor_keys_path(deploy).read_text(encoding="utf-8").split() == [made]
    assert made not in r.stdout + r.stderr  # the key is never printed
    again = _command(deploy)
    assert again.returncode == 0 and f"pre-start: {STEP}: in place" in again.stdout
    assert sx.actor_sign_key_path(deploy).read_text(encoding="utf-8").strip() == made


def test_a_box_without_per_service_tokens_gets_no_key(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("TB_SITE_ID=T\n", encoding="utf-8")
    r = _command(deploy)
    assert r.returncode == 0 and f"pre-start: {STEP}: no per-service tokens on this box" in r.stdout
    assert not sx.actor_sign_key_path(deploy).exists()


def test_the_model_key_step_makes_no_signing_key(tmp_path: Path) -> None:
    """One step, one thing: the model-key step's line is then true for a box that is not a GPU box."""
    deploy = _old_box(tmp_path)
    box = up.ComposeBox(deploy)
    box.ensure_model_key()
    assert not sx.actor_sign_key_path(deploy).exists()
    assert box.ensure_actor_key() is True and sx.actor_sign_key_path(deploy).exists()


def test_a_tree_from_before_the_command_still_gets_the_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The updater's own fallback (a host tree without ``prestart.py``) runs the steps in this process: the key
    must be among them, or a box whose tree lost the command starts a console that cannot sign."""
    deploy = _old_box(tmp_path)
    box = up.ComposeBox(deploy)
    monkeypatch.setattr(box, "resolve_pins", lambda: None)
    assert not (deploy.parent / "tools" / "trialbox" / "prestart.py").exists()
    box.pre_start()
    assert sx.actor_sign_key_path(deploy).exists()


def test_a_key_that_cannot_be_written_stops_the_update_with_its_reason(tmp_path: Path) -> None:
    """The review: a step fails by raising ``UpdateFailed`` (the contract), so the operator reads the step and the
    reason, not the tail of a traceback."""
    deploy = _old_box(tmp_path)
    sx.actor_sign_key_path(deploy).mkdir()  # the write cannot succeed
    with pytest.raises(up.UpdateFailed, match="the console's signing key could not be written"):
        up.ComposeBox(deploy).ensure_actor_key()
    r = _command(deploy)
    assert r.returncode == 1 and "Traceback" not in r.stderr
    # the step is named before its reason since UPDATE-DBUP (D-624)
    assert "pre-start: failed: actor signing key: the console's signing key could not be written" in r.stderr


def test_the_step_is_what_calls_the_key_maker() -> None:
    """The older pin (``test_actor_key_apart``) reads the updater's text; this one holds the step to the call."""
    made: list[str] = []

    class Box:
        def ensure_actor_key(self) -> bool:
            made.append("asked")
            return True

    step = dict(prestart.STEPS)[STEP]
    assert step(Box()) == "made now" and made == ["asked"]  # type: ignore[arg-type]
