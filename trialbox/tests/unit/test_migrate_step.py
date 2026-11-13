"""T-718 (D-486): ``trialbox update`` and ``trialbox migrate`` make the schemas no service owns before the services
start, as the box's admin, and the admin's URL is never on a command line. Synthetic values only."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tools.trialbox import update as up

WORD = "synthetic-admin"  # a test string, not a password of anything
URL = "postgresql://" + "trialbox:" + WORD + "@db:5432/trialbox_wf"


def _box(tmp_path: Path, env: str) -> tuple[up.ComposeBox, list[tuple[list[str], dict[str, str]]]]:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text(env)
    (deploy / ".env").chmod(0o600)
    calls: list[tuple[list[str], dict[str, str]]] = []

    def run(argv: Sequence[str], env: dict[str, str] | None = None, **_: Any) -> str:
        calls.append((list(argv), dict(env or {})))
        return ""

    script = deploy / "docker" / "db-init" / "30-service-roles.sh"  # the release's own script, as a box has it
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/bin/sh\n", encoding="utf-8")
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
    assert env == {"TB_DB_URL": URL} and not any(WORD in a for a in argv)


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


def test_the_update_sets_the_roles_before_it_migrates(tmp_path: Path) -> None:
    """Review H1: `trialbox update` ran the migrate step but never the role script, so a box updated in place kept
    the schema under the old group, with the service as its owner, and nothing said so."""
    box, calls = _box(tmp_path, f"COMPOSE_PROFILES=stub\nTB_DB_URL={URL}\n")
    box.restart(up.Plan("b1", "", "", [], tmp_path / "stage"))
    roles = next(i for i, (argv, _e) in enumerate(calls) if argv[-1].endswith("30-service-roles.sh"))
    step = next(i for i, (argv, _e) in enumerate(calls) if "orchestrator.migrate" in argv)
    assert roles < step
    argv, env = calls[roles]
    # D-541 on D-624: the script runs in the database container, which is on this release's settings by then and
    # holds every role's password in its own environment; nothing is handed over on this call
    assert argv[-4:] == ["exec", "-T", "db", "/docker-entrypoint-initdb.d/30-service-roles.sh"]
    assert env == {} and not any(WORD in a for a in argv)


def test_the_update_gives_the_fhir_store_a_password_before_the_database_step(tmp_path: Path) -> None:
    """NEW-TRUST-1 (D-541): a box installed before this card has no `TB_DB_PW_FHIR_STORE`. A pre-start step writes
    one to `deploy/.env` (0600, never printed, never an argument, in no call's environment); the database container
    is then put on the release's settings and the role script reads it there. A second run keeps the value."""
    from tools.trialbox import prestart

    box, calls = _box(tmp_path, f"COMPOSE_PROFILES=stub\nTB_DB_URL={URL}\nPOSTGRES_PASSWORD=synthetic-admin-000\n")
    env_file = tmp_path / "deploy" / ".env"
    names = [n for n, _ in prestart.STEPS]
    assert "FHIR store password" in names  # a host-side step: before every step that needs the database
    assert [n for n, _ in prestart.DB_STEPS][:2] == ["database", "service roles"]
    lines = prestart._run(tmp_path / "deploy", "pre-start", box) + prestart._run(tmp_path / "deploy", "db-up", box)
    made = [ln.split("=", 1)[1] for ln in env_file.read_text().splitlines() if ln.startswith("TB_DB_PW_FHIR_STORE=")]
    assert len(made) == 1 and len(made[0]) >= 32 and made[0] != "synthetic-admin-000"
    assert oct(env_file.stat().st_mode & 0o777) == "0o600"
    assert "pre-start: FHIR store password: made now" in lines and not any(made[0] in ln for ln in lines)
    assert not any(made[0] in a for argv, _e in calls for a in argv)
    assert not any(made[0] in e.values() for _argv, e in calls)
    db = next(i for i, (argv, _e) in enumerate(calls) if argv[-1] == "db" and "up" in argv)
    roles = next(i for i, (argv, _e) in enumerate(calls) if argv[-1].endswith("30-service-roles.sh"))
    assert db < roles  # the container takes the new setting before the script reads it
    box2, _ = _box_again(tmp_path)
    assert box2.ensure_fhir_password() is False
    again = [ln.split("=", 1)[1] for ln in env_file.read_text().splitlines() if ln.startswith("TB_DB_PW_FHIR_STORE=")]
    assert again == made


def test_a_placeholder_password_is_replaced_and_a_tree_without_the_command_still_gets_one(tmp_path: Path) -> None:
    box, _calls = _box(tmp_path, "TB_DB_PW_FHIR_STORE=change-me-fhir\n")
    assert box.ensure_fhir_password() is True
    assert "change-me" not in (tmp_path / "deploy" / ".env").read_text()
    (tmp_path / "b").mkdir()
    box, _calls = _box(tmp_path / "b", "X=1\n")
    box.resolve_pins = lambda: None  # type: ignore[method-assign]
    box.pre_start()  # no host tree with the command: the updater's own fallback
    assert "TB_DB_PW_FHIR_STORE=" in (tmp_path / "b" / "deploy" / ".env").read_text()


def _box_again(tmp_path: Path) -> tuple[up.ComposeBox, list[tuple[list[str], dict[str, str]]]]:
    calls: list[tuple[list[str], dict[str, str]]] = []

    def run(argv: Sequence[str], env: dict[str, str] | None = None, **_: Any) -> str:
        calls.append((list(argv), dict(env or {})))
        return ""

    return up.ComposeBox(tmp_path / "deploy", run=run), calls


def test_a_box_without_the_admin_url_still_gets_the_fhir_password(tmp_path: Path) -> None:
    """Review L3: the compose file asks for the role's password whatever else the box has."""
    box, calls = _box(tmp_path, "X=1\n")
    assert box.ensure_fhir_password() is True and box.set_roles() is False
    assert "TB_DB_PW_FHIR_STORE=" in (tmp_path / "deploy" / ".env").read_text()
    assert calls == []  # no database step on such a box
