"""T-718 (D-486): ``trialbox update`` and ``trialbox migrate`` make the schemas no service owns before the services
start, as the box's admin, and the admin's URL is never on a command line. Synthetic values only."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tools.trialbox import update as up

URL = "postgresql://trialbox:synthetic-admin@db:5432/trialbox_wf"  # a test string


def _box(tmp_path: Path, env: str) -> tuple[up.ComposeBox, list[tuple[list[str], dict[str, str]]]]:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text(env)
    (deploy / ".env").chmod(0o600)
    calls: list[tuple[list[str], dict[str, str]]] = []

    def run(argv: Sequence[str], env: dict[str, str] | None = None, **_: Any) -> str:
        calls.append((list(argv), dict(env or {})))
        return ""

    return up.ComposeBox(deploy, run=run), calls


def test_the_update_migrates_the_owned_schemas_before_it_starts_the_services(tmp_path: Path) -> None:
    box, calls = _box(tmp_path, f"COMPOSE_PROFILES=stub\nTB_DB_URL={URL}\n")
    box.restart(up.Plan("b1", "", "", [], tmp_path / "stage"))
    step = next(i for i, (argv, _e) in enumerate(calls) if "orchestrator.migrate" in argv)
    start = next(i for i, (argv, _e) in enumerate(calls) if "up" in argv)
    assert step < start
    argv, env = calls[step]
    assert argv[-8:] == ["--no-deps", "-T", "-e", "TB_DB_URL", "orchestrator", "python", "-m", "orchestrator.migrate"]
    assert "run" in argv and "--rm" in argv
    assert env == {"TB_DB_URL": URL} and not any("synthetic-admin" in a for a in argv)


def test_the_host_command_runs_the_same_step_and_a_box_without_the_admin_url_runs_none(tmp_path: Path) -> None:
    box, calls = _box(tmp_path, f"TB_DB_URL={URL}\n")
    box.migrate_owned()
    assert len(calls) == 1 and calls[0][0][-2:] == ["-m", "orchestrator.migrate"]
    (tmp_path / "other").mkdir()
    box, calls = _box(tmp_path / "other", "X=1\n")
    box.migrate_owned()
    assert calls == []


def test_install_runs_the_step_after_the_roles_and_before_the_services() -> None:
    text = (Path(__file__).resolve().parents[2] / "deploy" / "install.sh").read_text(encoding="utf-8")
    roles = text.index("/docker-entrypoint-initdb.d/30-service-roles.sh")
    step = text.index("orchestrator python -m orchestrator.migrate")
    stack = text.index('"${UP_EXTRA[@]}" --wait')
    assert roles < step < stack
    line = text[text.rindex("\n", 0, text.rindex("TB_DB_URL=", 0, step)) : step]
    assert "run --rm --no-deps -T -e TB_DB_URL \\" in line  # the name only: the value is in the environment
