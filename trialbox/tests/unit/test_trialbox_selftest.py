"""OPS-033: ``trialbox selftest`` runs the pair canary with the box's compose files, without ``make``."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.trialbox import selftest
from tools.trialbox.__main__ import main as cli

ROOT = Path(__file__).resolve().parents[2]


def _box(tmp_path: Path, env: str) -> Path:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    for name in ("docker-compose.yml", "docker-compose.secrets.yml", "docker-compose.identity.yml"):
        (deploy / name).write_text("services: {}\n", encoding="utf-8")
    (deploy / ".env").write_text(env, encoding="utf-8")
    return deploy


def test_selftest_uses_compose_file_and_profiles_from_deploy_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TB_COMPOSE", raising=False)
    deploy = tmp_path / "deploy"
    files = f"{deploy}/docker-compose.yml:{deploy}/docker-compose.secrets.yml:docker-compose.identity.yml"
    _box(tmp_path, f"TB_ENV=PRODUCTION\nCOMPOSE_PROFILES=gpu\nCOMPOSE_FILE={files}\n")
    seen: list[list[str]] = []

    def run(cmd: list[str]) -> int:
        seen.append(cmd)
        return 0

    assert selftest.main(deploy, run=run) == 0
    (cmd,) = seen
    assert cmd[:4] == ["docker", "compose", "--project-directory", str(deploy)]
    fs = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-f"]
    # every overlay of COMPOSE_FILE, in order; a relative entry is under the deploy folder
    assert fs == [str(deploy / "docker-compose.yml"), str(deploy / "docker-compose.secrets.yml"),
                  str(deploy / "docker-compose.identity.yml")]  # fmt: skip
    assert cmd[cmd.index("--profile") + 1] == "gpu"
    assert cmd[-6:] == ["exec", "-T", "orchestrator", "python", "-m", "orchestrator.selftest"]


def test_selftest_returns_the_canary_exit_code_and_fails_on_a_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("TB_COMPOSE", raising=False)
    deploy = _box(tmp_path, "COMPOSE_FILE=docker-compose.yml:docker-compose.gone.yml\n")
    assert selftest.main(deploy, run=lambda cmd: 0) == 1
    assert "compose file not found" in capsys.readouterr().err
    (deploy / ".env").write_text("COMPOSE_FILE=docker-compose.yml\n", encoding="utf-8")
    assert selftest.main(deploy, run=lambda cmd: 3) == 3
    assert "the pair canary exited 3" in capsys.readouterr().out


def test_selftest_without_compose_file_uses_the_base_file_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TB_COMPOSE", "docker compose -p tb")
    deploy = _box(tmp_path, "TB_ENV=DEV\n")
    assert cli(["selftest", "--deploy", str(deploy), "--dry-run"]) == 0
    out, err = capsys.readouterr()
    assert out.strip() == (
        f"docker compose -p tb -f {deploy / 'docker-compose.yml'} exec -T orchestrator python -m orchestrator.selftest"
    )
    assert "no COMPOSE_FILE" in err


def test_make_selftest_goes_through_the_host_command() -> None:
    """The Makefile target no longer names the base compose file alone."""
    make = (ROOT / "Makefile").read_text(encoding="utf-8")
    body = make.split("\nselftest:\n", 1)[1].split("\n\n", 1)[0]
    assert "tools.trialbox selftest" in body and "docker-compose.yml" not in body
