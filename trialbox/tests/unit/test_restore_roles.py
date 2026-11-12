"""RESTORE-ROLES (D-573): a restore puts every store back under its service's role. ``pg_restore --no-owner``
leaves each restored schema, table and function owned by ``trialbox``; the restore now runs the service-roles script
itself (``TB_DB_ROLES_CMD``), and the script moves functions as it moves tables. The drill's check does the whole
round on a throwaway cluster of its own with the real script: dump, restore, the script, then every service role
opens each store on its list as the store's group and reaches no other."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from tools import backup_drill, pglocal
from tools.trialbox import backup as bk

ROOT = Path(__file__).resolve().parents[2]
BOX = ROOT / "deploy" / "docker" / "db-init" / "30-service-roles.sh"
PLATFORM = ROOT / "deploy" / "platform" / "base" / "db-init" / "30-service-roles.sh"


def _pg() -> None:
    if shutil.which("sh") is None:
        pytest.skip("no sh")
    try:
        pglocal.bindir()
    except RuntimeError as exc:
        pytest.skip(str(exc))


# ------------------------------------------------------------------------------------------------ the command
@pytest.mark.nodb
def test_the_restore_runs_the_roles_command_and_says_what_came_of_it(tmp_path: Path) -> None:
    done = tmp_path / "done"
    ok = bk.reapply_service_roles({"TB_DB_ROLES_CMD": f"{sys.executable} -c \"open(r'{done}', 'w').write('x')\""})
    assert ok == {"state": "applied"} and done.read_text() == "x"
    none = bk.reapply_service_roles({})
    assert none["state"] == "not_configured" and "30-service-roles.sh" in none["run"]
    with pytest.raises(bk.BackupError, match="service roles.*planted failure"):
        bk.reapply_service_roles(
            {
                "TB_DB_ROLES_CMD": f"{sys.executable} -c \"import sys; print('planted failure', file=sys.stderr); sys.exit(3)\""
            }
        )
    with pytest.raises(bk.BackupError, match="service roles"):
        bk.reapply_service_roles({"TB_DB_ROLES_CMD": "/no/such/command"})


@pytest.mark.nodb
@pytest.mark.parametrize(
    ("env", "state", "complete"),
    [
        ({"TB_ENV": "PRODUCTION"}, "not_configured", False),
        ({}, "not_configured", False),  # TB_ENV unset is PRODUCTION
        ({"TB_ENV": "VALIDATION"}, "not_configured", False),
        ({"TB_ENV": "TEST"}, "not_configured", True),
        ({"TB_ENV": "PRODUCTION"}, "applied", True),
        ({"TB_ENV": "PRODUCTION"}, "not_restored", True),  # a backup without the trial database: nothing to move
    ],
)
def test_without_the_command_a_production_restore_is_not_complete(
    env: dict[str, str], state: str, complete: bool
) -> None:
    assert bk.roles_ok({"state": state}, env) is complete


@pytest.mark.nodb
def test_the_setting_is_declared_and_the_cli_and_the_runbook_say_the_line() -> None:
    from tb_common.config import DECLARED

    assert "TB_DB_ROLES_CMD" in DECLARED
    main = (ROOT / "tools" / "trialbox" / "__main__.py").read_text(encoding="utf-8")
    assert "service_roles" in main and "TB_DB_ROLES_CMD" in main
    page = (ROOT / "docs" / "runbook" / "05-updates-backup-restore-secrets.md").read_text(encoding="utf-8")
    assert "TB_DB_ROLES_CMD" in page and "run the role\nscript once after it" not in page


# ------------------------------------------------------------------------------------------------ the script
@pytest.mark.nodb
def test_both_copies_of_the_script_are_the_same_and_move_functions() -> None:
    text = BOX.read_text(encoding="utf-8")
    assert text == PLATFORM.read_text(encoding="utf-8")
    assert "pg_proc" in text and "ALTER %s %s OWNER TO %I" in text
    assert backup_drill.service_access(BOX)["tb_gateway"] == ["app", "trace"]


# ------------------------------------------------------------------------------------------------ the whole round
def test_after_a_restore_every_service_opens_its_stores_as_its_own_role(tmp_path: Path) -> None:
    """The drill's check, on a cluster of its own with the real script. It fails on the script without the
    function move ("must be owner of function") and without the roles command (the stores stay trialbox's)."""
    _pg()
    name, ok, detail = backup_drill.roles_after_restore(tmp_path / "cluster")
    assert ok, detail
    assert "every service" in name and "function" in detail


def test_the_check_fails_when_the_script_does_not_move_functions(tmp_path: Path) -> None:
    """The same round with the script as it was (tables, views and sequences only)."""
    _pg()
    text = BOX.read_text(encoding="utf-8")
    start = text.index("    -- D-573: functions, procedures and aggregates")
    end = text.index("    END LOOP;\n", start) + len("    END LOOP;\n")
    old = tmp_path / "30-service-roles.sh"
    old.write_text(text[:start] + text[end:], encoding="utf-8")
    _name, ok, detail = backup_drill.roles_after_restore(tmp_path / "cluster", script=old)
    assert not ok and "function" in detail


# ------------------------------------------------------------------------------------------------ inside the restore
def test_the_restore_itself_runs_the_command_after_the_trial_database(pg_cluster_url: str, tmp_path: Path) -> None:
    """The real `restore()`: with the command set it runs once and the result says applied; without it the result
    says the line to run and a restore on a box that runs for real is not complete; a failing command stops it."""
    import os
    from datetime import UTC, datetime
    from urllib.parse import urlsplit, urlunsplit

    import psycopg
    from tb_common.db import split_url

    dsn, _ = split_url(pg_cluster_url)
    name = f"tb_roles_{os.getpid()}_{datetime.now(UTC).strftime('%H%M%S%f')}"
    try:
        with psycopg.connect(dsn, autocommit=True) as con:
            con.execute(f'CREATE DATABASE "{name}"')
    except psycopg.Error as e:
        pytest.skip(f"cannot create a database here: {e}")
    parts = urlsplit(dsn)
    url = urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment))
    try:
        with psycopg.connect(url, autocommit=True) as con:
            con.execute("CREATE SCHEMA site; CREATE TABLE site.marks (pid text PRIMARY KEY, mark text)")
            con.execute("INSERT INTO site.marks VALUES ('P1', 'approach')")
        priv, pub = tmp_path / "k.key", tmp_path / "k.pub"
        bk.keygen(priv, pub)
        env = {"TB_DB_URL": url, "TB_SITE_ID": "CGMH"}
        f = bk.backup([tmp_path / "nas"], pub, env=env, dirs={})[0]
        ran = tmp_path / "ran"
        cmd = f"{sys.executable} -c \"open(r'{ran}', 'a').write('x')\""
        with_cmd = {**env, "TB_DB_ROLES_CMD": cmd}
        out = bk.restore(f, priv, env=with_cmd, dirs={}, public_key=pub, keep_to=tmp_path / "k1")
        assert out["service_roles"] == {"state": "applied"} and ran.read_text() == "x"
        assert bk.roles_ok(out["service_roles"], with_cmd)
        out = bk.restore(f, priv, env=env, dirs={}, public_key=pub, keep_to=tmp_path / "k2")  # no TB_ENV: PRODUCTION
        assert (
            out["service_roles"]["state"] == "not_configured" and "30-service-roles.sh" in out["service_roles"]["run"]
        )
        assert out["ok"] and out["warnings"] == [] and not out["complete"]  # a field of its own, and not complete
        assert not bk.roles_ok(out["service_roles"], env) and bk.roles_ok(out["service_roles"], {"TB_ENV": "TEST"})
        bad = f"{sys.executable} -c \"import sys; sys.exit('planted failure')\""
        with pytest.raises(bk.BackupError, match="service roles were not put back.*planted failure"):
            bk.restore(f, priv, env={**env, "TB_DB_ROLES_CMD": bad}, dirs={}, public_key=pub, keep_to=tmp_path / "k4")
    finally:
        with psycopg.connect(dsn, autocommit=True) as con:
            con.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


# ------------------------------------------------------------------------------------------------ the review of #376
@pytest.mark.nodb
def test_review_the_roles_step_comes_after_the_running_jobs_are_failed_and_the_opt_outs_kept() -> None:
    """HIGH-1: the command ran before `fail_running_jobs`; when it failed, the restored queue kept its running jobs
    and the message sent the operator to run the command and start the services, which would run them again."""
    text = (ROOT / "tools" / "trialbox" / "backup.py").read_text(encoding="utf-8")
    body = text[text.index("def restore(") :]
    order = [body.index(x) for x in ("fail_running_jobs(srcs[", "keep()\n", "roles = reapply_service_roles(env)")]
    assert order == sorted(order)
    with pytest.raises(bk.BackupError) as e:
        bk.reapply_service_roles({"TB_DB_ROLES_CMD": f'{sys.executable} -c "import sys; sys.exit(2)"'})
    assert "run this restore again" in str(e.value)  # not: run the command and start the services


@pytest.mark.nodb
def test_review_the_roles_line_is_printed_before_any_early_exit_of_the_command() -> None:
    """MED-2: the line came after the returns for a missing pack and for events to re-apply: on a fresh box the
    operator never saw it."""
    main = (ROOT / "tools" / "trialbox" / "__main__.py").read_text(encoding="utf-8")
    assert main.index("the service roles were not put back") < main.index("the reference data is NOT loaded")


@pytest.mark.nodb
def test_review_the_environment_is_read_by_the_one_rule_and_a_platform_restore_needs_no_roles() -> None:
    """LOW-6: `production ` with a space counted as not for real. MED-4: the platform's services sign in as
    trialbox; its restore job is not "not complete" for a step it does not need."""
    assert not bk.roles_ok({"state": "not_configured"}, {"TB_ENV": " production "})
    assert bk.roles_ok({"state": "not_configured"}, {"TB_ENV": "dev"})
    assert bk.reapply_service_roles({"TB_DB_ROLES_CMD": bk.ROLES_NOT_NEEDED}) == {"state": "not_needed"}
    assert bk.roles_ok({"state": "not_needed"}, {})
    day2 = (ROOT / "tools" / "trialbox" / "platform_day2.py").read_text(encoding="utf-8")
    assert "bk.ROLES_NOT_NEEDED" in day2
    page = (ROOT / "docs" / "runbook" / "05-updates-backup-restore-secrets.md").read_text(encoding="utf-8")
    assert "from the release folder" in page and "clears the service roles' passwords" in page
