"""SETTINGS-FILE (D-888, lane G's box): every service mounts ``${TB_SETTINGS_FILE:-./settings.example.yaml}``, and
install.sh only exported TB_SETTINGS_FILE in its own process. A box started by anything else (the systemd unit, an
operator's `docker compose up`, an update's restart) ran on the EXAMPLE settings; on lane G's box the ingest then read
the example's /data/source/site-a. The installer now writes it to deploy/.env, which compose reads on every start, and
the start paths refuse a box whose site settings exist but would not be mounted."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "deploy" / "settings_guard.sh"
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
UNIT = (ROOT / "deploy" / "systemd" / "trialbox.service").read_text(encoding="utf-8")
APPLY = (ROOT / "tools" / "apply_update.sh").read_text(encoding="utf-8")

pytestmark = pytest.mark.nodb


def _deploy(tmp: Path, env: str | None, settings: bool = True) -> Path:
    d = tmp / "deploy"
    d.mkdir()
    if settings:
        (d / "settings.yaml").write_text("site: {id: SITE-A}\n", encoding="utf-8")
    if env is not None:
        (d / ".env").write_text(env, encoding="utf-8")
    return d


def _guard(deploy: Path, **env: str) -> subprocess.CompletedProcess[str]:
    base = {k: v for k, v in os.environ.items() if k != "TB_SETTINGS_FILE"}
    return subprocess.run(["sh", str(GUARD), str(deploy)], capture_output=True, text=True, env={**base, **env},
                          check=False)  # fmt: skip


@pytest.mark.parametrize("line", ["TB_SETTINGS_FILE=./settings.yaml\n", "TB_SETTINGS_FILE=settings.yaml\n"])
def test_the_sites_settings_named_in_the_env_file_start(tmp_path: Path, line: str) -> None:
    assert _guard(_deploy(tmp_path, "TB_ENV=VALIDATION\n" + line)).returncode == 0


@pytest.mark.parametrize("env", [None, "TB_ENV=VALIDATION\n", "TB_SETTINGS_FILE=./settings.example.yaml\n"])
def test_a_box_that_would_start_on_the_example_settings_is_refused(tmp_path: Path, env: str | None) -> None:
    res = _guard(_deploy(tmp_path, env))
    assert res.returncode == 1
    assert "example settings" in res.stderr and "TB_SETTINGS_FILE=./settings.yaml" in res.stderr


def test_the_environment_wins_as_it_does_for_compose(tmp_path: Path) -> None:
    deploy = _deploy(tmp_path, "TB_ENV=TEST\n")
    assert _guard(deploy, TB_SETTINGS_FILE="./settings.yaml").returncode == 0
    assert _guard(deploy, TB_SETTINGS_FILE="./settings.example.yaml").returncode == 1


def test_a_box_without_site_settings_is_not_refused(tmp_path: Path) -> None:
    """A first install loads the bundle before the wizard writes settings.yaml."""
    assert _guard(_deploy(tmp_path, None, settings=False)).returncode == 0


def test_the_installer_writes_it_to_the_env_file() -> None:
    block = INSTALL[INSTALL.index('chown "$(id -u):10001" deploy/settings.yaml') :][:400]
    assert 'envset TB_SETTINGS_FILE "./settings.yaml"' in block
    # a re-run (the repair of a box installed before this) passes the bundle step's guard: compose's own precedence
    bundle = INSTALL[: INSTALL.index('say "bundle: verify and load')]
    assert '[ -f deploy/settings.yaml ] && export TB_SETTINGS_FILE="./settings.yaml"' in bundle


def test_every_start_path_runs_the_guard() -> None:
    pre = [ln for ln in UNIT.splitlines() if ln.startswith("ExecStartPre=")]
    assert any("settings_guard.sh @TB_ROOT@/deploy" in ln for ln in pre)
    update = APPLY[: APPLY.index("python3 -m tools.trialbox update --stage")]
    assert 'sh "$ROOT/deploy/settings_guard.sh" "$ROOT/deploy"' in update


def test_the_rehearsal_restarts_without_the_installer_and_checks_the_mount() -> None:
    box = (ROOT / "tools" / "rehearse_box" / "box.sh").read_text(encoding="utf-8")
    body = box[box.index("\nreinstall)") : box.index(";;", box.index("\nreinstall)"))]
    assert "dc up -d --force-recreate" in body and "/etc/trialbox/settings.yaml" in body
    assert "deploy/settings.yaml" in body
