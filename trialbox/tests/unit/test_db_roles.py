"""D-378 (T-212c, CR-037): one PostgreSQL role per service, each reaching only its own schemas.

The real ``deploy/docker/db-init/30-service-roles.sh`` runs against a throwaway cluster of its own (roles are
cluster-wide, so never the session's shared one), twice, over a database that already holds a schema an earlier
release made as ``trialbox``. Then each service role reads its own schemas and is refused every other one. Passwords
are synthetic test strings.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from tb_common.db import Database

from tools import pglocal

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "docker" / "db-init" / "30-service-roles.sh"
COMPOSE = ROOT / "deploy" / "docker-compose.yml"


def _access() -> dict[str, list[str]]:
    """The script's list: service role -> the schemas it reaches."""
    text = SCRIPT.read_text(encoding="utf-8")
    block = text.split("-- BEGIN SERVICE SCHEMAS (D-378)", 1)[1].split("-- END SERVICE SCHEMAS", 1)[0]
    body = block.split(":= '", 1)[1].rsplit("';", 1)[0]
    data: dict[str, list[str]] = json.loads(body)
    return data


def _owned() -> list[str]:
    """The script's second list (D-486): the schemas with an owner, a writer and a reader role."""
    text = SCRIPT.read_text(encoding="utf-8")
    block = text.split("-- BEGIN OWNED SCHEMAS (D-486)", 1)[1].split("-- END OWNED SCHEMAS", 1)[0]
    return re.findall(r"'([a-z_]+)'", block.split("ARRAY[", 1)[1])


ACCESS = _access()
OWNED = _owned()
SCHEMAS = sorted({s for v in ACCESS.values() for s in v})
SENSITIVE = ("auth", "breakglass", "edc", "pidmap", "sae", "team")  # sessions and hashes, signatures, the pseudonym map


def _env_name(role: str) -> str:
    return "TB_DB_PW_" + role.removeprefix("tb_").upper()


def _as(url: str, user: str) -> str:
    return url.replace("postgresql://trialbox@", f"postgresql://{user}@", 1)


# ------------------------------------------------------------------------------------------------ pure checks
def test_the_list_is_well_formed() -> None:
    assert set(ACCESS) == {"tb_lake", "tb_criteria_compiler", "tb_adapter", "tb_orchestrator", "tb_mail_gateway",
                           "tb_gateway", "tb_console"}  # fmt: skip
    for role, schemas in ACCESS.items():
        assert schemas == sorted(set(schemas)), role
        assert all(re.fullmatch(r"[a-z][a-z0-9_]{0,58}", s) for s in schemas), role
        assert "app" in schemas, role  # the feature flags (tb_common.flags) are read by every service
    text = SCRIPT.read_text(encoding="utf-8")
    for role in ACCESS:  # every role's password comes from its environment variable, never from the file
        var = role.removeprefix("tb_")
        assert f'-v pw_{var}="${{{_env_name(role)}:-}}"' in text
        assert f"ALTER ROLE {role} PASSWORD :'pw_{var}';" in text
    assert os.access(SCRIPT, os.X_OK)


def test_cr037_the_edge_services_reach_no_account_signature_or_pseudonym_store() -> None:
    for role in ("tb_lake", "tb_criteria_compiler", "tb_mail_gateway", "tb_gateway"):
        assert not set(ACCESS[role]) & set(SENSITIVE), role
    assert not {"auth", "edc", "sae", "team", "breakglass"} & set(ACCESS["tb_adapter"])
    assert not {"auth", "breakglass", "sae", "team", "feedback", "trace"} & set(ACCESS["tb_orchestrator"])
    assert "trace" not in ACCESS["tb_console"] and "mail" not in ACCESS["tb_console"]


def test_d461_only_the_orchestrator_reaches_the_edc_schema() -> None:
    """T-720: the console never opens ``EdcStore``; an owner of ``edc`` could insert a signature row or drop the
    trail triggers (trust review F4)."""
    assert [role for role, schemas in ACCESS.items() if "edc" in schemas] == ["tb_orchestrator"]


def test_compose_gives_each_service_its_own_role_and_the_db_every_password() -> None:
    raw = COMPOSE.read_text(encoding="utf-8")
    services = yaml.safe_load(raw)["services"]
    db_env = services["db"]["environment"]
    for role in ACCESS:
        name = role.removeprefix("tb_").replace("_", "-")
        url = services[name]["environment"]["TB_DB_URL"]
        assert url.startswith(f"postgresql://{role}:${{{_env_name(role)}:-") and url.endswith("@db:5432/trialbox_wf")
        assert db_env[_env_name(role)].startswith(f"${{{_env_name(role)}:-")
    assert services["llm-stub"]["environment"]["TB_DB_URL"] == ""  # opens no database, gets no URL
    assert "LOGIN PASSWORD" in (SCRIPT.parent / "10-trialbox-wf.sh").read_text(encoding="utf-8")  # no CREATEDB


# ------------------------------------------------------------------------------------------------ the cluster
def _psql_env(root: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(
        PATH=f"{pglocal.bindir()}:{env.get('PATH', '')}",
        PGHOST=str((root / "run").resolve()),
        POSTGRES_USER="postgres",
        TB_WF_DB=pglocal.DB,
    )
    env.update({_env_name(r): f"synthetic-{r}" for r in ACCESS if r != "tb_gateway"})  # one left empty on purpose
    env.pop(_env_name("tb_gateway"), None)
    return env


def _run_script(root: Path) -> None:
    r = subprocess.run(["sh", str(SCRIPT)], env=_psql_env(root), capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr[-1500:]


def _superuser(root: Path, sql: str, db: str = "postgres") -> str:
    r = subprocess.run(
        [str(pglocal.bindir() / "psql"), "-U", "postgres", "-d", db, "-v", "ON_ERROR_STOP=1", "-tAqc", sql],
        env=_psql_env(root), capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture(scope="module")
def roles_cluster() -> Iterator[tuple[Path, str]]:
    """A cluster of its own with a `hapi` database and a pre-D-378 `auth` schema, the script applied twice."""
    if shutil.which("sh") is None:
        pytest.skip("no sh")
    try:
        pglocal.bindir()
    except RuntimeError as exc:
        pytest.skip(str(exc))
    base = Path(os.environ["TB_TEST_ROOT"]) if os.environ.get("TB_TEST_ROOT") else None
    if base is not None:
        base.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="tb-pgroles-", dir=base))
    root.chmod(0o755)
    url = pglocal.ensure(root)
    try:
        _superuser(root, "CREATE DATABASE hapi")
        with Database.connect(url, "auth") as db:  # what an older release left: owned by trialbox
            db.execute("CREATE TABLE users_old (id SERIAL PRIMARY KEY, name TEXT)")
            db.execute("INSERT INTO users_old (name) VALUES ('synthetic')")
        _run_script(root)
        _run_script(root)  # idempotent: install.sh runs it on every install and upgrade
        for schema in SCHEMAS:  # the box's admin (trialbox) makes one row in each store, as a migration would
            with Database.connect(url, schema) as db:
                db.execute("CREATE TABLE IF NOT EXISTS probe (k INT)")
                db.execute("INSERT INTO probe VALUES (1)")
        yield root, url
    finally:
        pglocal.stop(root)
        shutil.rmtree(root, ignore_errors=True)


def test_schemas_and_their_tables_belong_to_their_groups(roles_cluster: tuple[Path, str]) -> None:
    with Database.connect(roles_cluster[1], "auth") as db:
        owners: dict[str, str] = dict(db.fetchall(
            "SELECT c.relname, pg_get_userbyid(c.relowner) FROM pg_class c WHERE c.relnamespace = 'auth'::regnamespace "
            "AND c.relkind IN ('r', 'S')"
        ))  # fmt: skip
        assert owners == {"users_old": "tbs_auth", "users_old_id_seq": "tbs_auth", "probe": "tbs_auth"}
        assert db.fetchval("SELECT current_user") == "tbs_auth"  # tb_common.db took the group's role
        assert db.fetchval("SELECT name FROM users_old") == "synthetic"  # the old rows are kept
        rows = db.fetchall(
            "SELECT nspname, pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = ANY(?)", (SCHEMAS,)
        )
        # D-486 (T-718): a schema on the owned list belongs to its owner role, which no service is
        assert sorted(rows) == [(s, f"tbo_{s}" if s in OWNED else f"tbs_{s}") for s in SCHEMAS]


@pytest.mark.parametrize("role", sorted(ACCESS))
def test_a_service_role_reads_its_own_schemas_and_no_other(roles_cluster: tuple[Path, str], role: str) -> None:
    import psycopg
    from psycopg import errors

    dsn = _as(roles_cluster[1], role)
    with psycopg.connect(dsn, autocommit=True) as con:
        for schema in SCHEMAS:
            if schema in ACCESS[role]:
                assert con.execute(f'SELECT count(*) FROM "{schema}".probe').fetchone() == (1,), schema
            else:
                with pytest.raises(errors.InsufficientPrivilege):
                    con.execute(f'SELECT count(*) FROM "{schema}".probe')
                with pytest.raises(errors.InsufficientPrivilege):
                    con.execute(f'CREATE TABLE "{schema}".planted (k INT)')
        flags = con.execute(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s",
            (role,),
        ).fetchone()
        assert flags == (False, False, False, False, False)
    own = ACCESS[role][-1]
    with Database.connect(dsn, own) as db:  # a store as the service opens it: a migration's table is the group's
        db.migrate(["CREATE TABLE made_by_service (k INT)"])
        assert db.fetchval("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'made_by_service'::regclass") \
            == f"tbs_{own}"  # fmt: skip
    with pytest.raises(psycopg.OperationalError, match="permission denied"):  # the FHIR store's database is closed
        psycopg.connect(dsn.replace(f"/{pglocal.DB}", "/hapi"), autocommit=True).close()


def test_d461_a_console_in_the_edc_group_from_an_earlier_release_leaves_it(roles_cluster: tuple[Path, str]) -> None:
    """D-486 (T-718): and the group itself is left by everyone: what it owned becomes the owner role's, the
    orchestrator is the schema's writer."""
    root = roles_cluster[0]
    member = "SELECT count(*) FROM pg_auth_members WHERE roleid = 'tbs_edc'::regrole AND member = '{}'::regrole"
    # as the script before D-461 and D-486 left an older volume: one group, both services in it, its tables the group's
    _superuser(root, "CREATE ROLE tbs_edc NOLOGIN")
    _superuser(root, "GRANT tbs_edc TO tb_console, tb_orchestrator")
    _superuser(root, "CREATE TABLE edc.from_before (k INT); ALTER TABLE edc.from_before OWNER TO tbs_edc", pglocal.DB)
    assert _superuser(root, member.format("tb_console")) == "1"
    _run_script(root)
    assert _superuser(root, member.format("tb_console")) == "0"
    assert _superuser(root, member.format("tb_orchestrator")) == "0"
    assert _superuser(root, "SELECT pg_has_role('tb_orchestrator', 'tbw_edc', 'MEMBER')") == "t"
    assert _superuser(root, "SELECT pg_has_role('tb_console', 'tbw_edc', 'MEMBER')") == "f"
    assert _superuser(root, "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'edc.from_before'::regclass",
                      pglocal.DB) == "tbo_edc"  # fmt: skip


def test_nobody_but_the_superuser_creates_a_database_and_passwords_come_from_the_environment(
    roles_cluster: tuple[Path, str],
) -> None:
    import psycopg
    from psycopg import errors

    for user in ("trialbox", *ACCESS):
        with (
            psycopg.connect(_as(roles_cluster[1], user), autocommit=True) as con,
            pytest.raises(errors.InsufficientPrivilege),
        ):
            con.execute("CREATE DATABASE tb_should_not_exist")
    set_pw = _superuser(roles_cluster[0], "SELECT string_agg(rolname, ',' ORDER BY rolname) FROM pg_authid "
                              "WHERE rolname LIKE 'tb\\_%' AND rolpassword IS NOT NULL")  # fmt: skip
    assert set_pw.split(",") == sorted(r for r in ACCESS if r != "tb_gateway")  # an empty variable: no password


# ------------------------------------------------------------------------------------------------ T-718 (D-486)
EDC_KEY = b"synthetic-edc-sign-key-0123456789"  # a test string, not a secret
TRAIL = "switch_event"  # one of edc.store.APPEND_ONLY
ROW = ("INSERT INTO edc.switch_event (study, state, kind, reference, ack_date, reentry_pages, reentry_accuracy, "
       "by_user, role, at) VALUES ('GZQO', 'on', 'k', 'r', '2026-10-05', 0, 0, 'console:synthetic', 'admin', 't')")  # fmt: skip


@pytest.fixture(scope="module")
def edc_made(roles_cluster: tuple[Path, str]) -> tuple[Path, str]:
    """The EDC schema as the install step leaves it: its tables and trail triggers made by the box's admin."""
    from edc.store import EdcStore

    EdcStore(roles_cluster[1], EDC_KEY).close()  # trialbox: a member of the owner role, so this migrates
    return roles_cluster


def test_t718_no_service_role_owns_or_can_become_the_owner_of_the_edc_schema(edc_made: tuple[Path, str]) -> None:
    root = edc_made[0]
    owner = "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'edc'"
    assert _superuser(root, owner, pglocal.DB) == "tbo_edc"
    owners = _superuser(root, "SELECT DISTINCT pg_get_userbyid(relowner) FROM pg_class "
                              "WHERE relnamespace = 'edc'::regnamespace", pglocal.DB)  # fmt: skip
    assert owners == "tbo_edc"
    members = _superuser(root, "SELECT string_agg(pg_get_userbyid(member), ',') FROM pg_auth_members m "
                               "JOIN pg_roles r ON r.oid = m.roleid WHERE r.rolname LIKE 'tbo\\_%'")  # fmt: skip
    assert members == "trialbox"  # the host tools' admin (backup, restore, the migrate step) and nobody else
    for role in ACCESS:
        assert _superuser(root, f"SELECT pg_has_role('{role}', 'tbo_edc', 'MEMBER')") == "f", role
    old_group = _superuser(root, "SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid "
                                 "WHERE r.rolname = 'tbs_edc'")  # fmt: skip
    assert old_group == "0"  # the D-378 group of the schema, where an older volume has it, has no member left
    assert _superuser(root, "SELECT pg_has_role('tb_orchestrator', 'tbw_edc', 'MEMBER')") == "t"
    readers = _superuser(root, "SELECT count(*) FROM pg_auth_members WHERE roleid = 'tbr_edc'::regrole "
                               "AND member <> 'trialbox'::regrole")  # fmt: skip
    assert readers == "0"  # the reader role exists; no service reads the EDC schema without writing it


def test_t718_the_orchestrator_writes_the_edc_trail_and_cannot_drop_alter_or_disable_it(
    edc_made: tuple[Path, str],
) -> None:
    """The card's acceptance: a service role cannot drop, alter or disable a trigger (trust review F4)."""
    import psycopg
    from edc.store import APPEND_ONLY, EdcStore
    from psycopg import errors

    dsn = _as(edc_made[1], "tb_orchestrator")
    EdcStore(dsn, EDC_KEY).close()  # the service opens its store: it checks the schema, it makes nothing
    with psycopg.connect(dsn, autocommit=True) as con:
        con.execute(ROW)  # the trail still grows
        assert con.execute("SELECT count(*) FROM edc.switch_event").fetchone() == (1,)
        con.execute(
            "INSERT INTO edc.switch (study, state, by_user, at) VALUES ('GZQO', 'on', 'console:synthetic', 't')"
        )
        con.execute("UPDATE edc.switch SET state = 'off' WHERE study = 'GZQO'")  # a table that is no trail
        refused = [
            f"DROP TRIGGER {TRAIL}_append_only ON edc.{TRAIL}",
            f"DROP TRIGGER {TRAIL}_no_truncate ON edc.{TRAIL}",
            f"ALTER TABLE edc.{TRAIL} DISABLE TRIGGER {TRAIL}_append_only",
            f"ALTER TABLE edc.{TRAIL} DISABLE TRIGGER ALL",
            f"ALTER TABLE edc.{TRAIL} ADD COLUMN planted TEXT",
            f"ALTER TABLE edc.{TRAIL} OWNER TO tb_orchestrator",
            f"DROP TABLE edc.{TRAIL}",
            f"TRUNCATE edc.{TRAIL}",
            f"UPDATE edc.{TRAIL} SET reason = 'changed'",
            f"DELETE FROM edc.{TRAIL}",
            "CREATE OR REPLACE FUNCTION edc.edc_append_only() RETURNS trigger LANGUAGE plpgsql AS "
            "$$ BEGIN RETURN NEW; END $$",
            "DROP FUNCTION edc.edc_append_only() CASCADE",
            "CREATE TABLE edc.planted (k INT)",
            "DROP SCHEMA edc CASCADE",
            "SET ROLE tbo_edc",
            "SET ROLE tbs_edc",
        ]
        for sql in refused:
            with pytest.raises((errors.InsufficientPrivilege, errors.InvalidParameterValue, errors.UndefinedObject)):
                con.execute(sql)
        for table in APPEND_ONLY:  # every trail table, not only the one above
            with pytest.raises(errors.InsufficientPrivilege):
                con.execute(f"ALTER TABLE edc.{table} DISABLE TRIGGER USER")
        assert con.execute("SELECT count(*) FROM edc.switch_event").fetchone() == (1,)


def test_t718_a_service_does_not_migrate_an_owned_schema_and_refuses_one_that_is_behind(
    edc_made: tuple[Path, str],
) -> None:
    from edc.store import MIGRATIONS
    from tb_common.db import MigrationError

    dsn = _as(edc_made[1], "tb_orchestrator")
    with Database.connect(dsn, "edc") as db:
        assert db.fetchval("SELECT current_user") == "tb_orchestrator"  # no owner's role is taken
        assert db.migrate(list(MIGRATIONS)) == len(MIGRATIONS)  # up to date: a check, nothing made
        with pytest.raises(MigrationError, match="trialbox migrate"):
            db.migrate([*MIGRATIONS, "CREATE TABLE planted_by_service (k INT)"])
        assert db.fetchval("SELECT to_regclass('edc.planted_by_service')") is None
    with Database.connect(edc_made[1], "edc") as db:  # the box's admin: the migrate step makes it
        assert db.fetchval("SELECT current_user") == "tbo_edc"
        db.migrate([*MIGRATIONS, "CREATE TABLE made_by_the_step (k INT)"])
        assert db.fetchval("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'made_by_the_step'::regclass") \
            == "tbo_edc"  # fmt: skip
    with Database.connect(dsn, "edc") as db:  # and the writer reads and writes what the step made
        db.execute("INSERT INTO made_by_the_step VALUES (1)")


def test_t718_the_install_step_knows_every_owned_schema_and_adopts_what_a_restore_left(
    edc_made: tuple[Path, str],
) -> None:
    """A restore is made by the box's admin without owners or privileges (``--no-owner``): the step gives the
    tables back to the owner role and the writer its rights, and puts back a trigger the dump did not hold."""
    import psycopg
    from edc.store import MIGRATIONS
    from orchestrator import migrate

    assert sorted(migrate.OWNED) == sorted(OWNED)
    root, url = edc_made
    _superuser(root, "ALTER TABLE edc.switch OWNER TO trialbox; REVOKE ALL ON edc.switch FROM tbw_edc; "
                     f"DROP TRIGGER {TRAIL}_no_truncate ON edc.{TRAIL}", pglocal.DB)  # fmt: skip
    dsn = _as(url, "tb_orchestrator")
    with pytest.raises(Exception, match="trail triggers"):  # the service refuses a trail without its trigger
        from edc.store import EdcStore

        EdcStore(dsn, EDC_KEY)
    said: list[str] = []
    assert migrate.run(url, said.append) == 0 and said == [f"edc: version {len(MIGRATIONS)}"]
    owner = "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'edc.switch'::regclass"
    assert _superuser(root, owner, pglocal.DB) == "tbo_edc"
    with psycopg.connect(dsn, autocommit=True) as con:
        con.execute("UPDATE edc.switch SET state = 'on' WHERE study = 'GZQO'")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            con.execute(f"TRUNCATE edc.{TRAIL}")
    EdcStore(dsn, EDC_KEY).close()


# ------------------------------------------------------------------ T-718: the adversarial review's findings
def test_t718_review_a_rerun_of_the_role_script_does_not_give_the_writer_back_the_trail(
    edc_made: tuple[Path, str],
) -> None:
    """Review M2: the script granted INSERT, UPDATE, DELETE on every table at each run, so a run after the migrate
    step (every install and update) gave the writer back what the step had taken."""
    root = edc_made[0]
    _run_script(root)

    def has(table: str, right: str) -> str:
        return _superuser(root, f"SELECT has_table_privilege('tb_orchestrator', 'edc.{table}', '{right}')", pglocal.DB)

    assert [has(TRAIL, r) for r in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")] == ["t", "t", "f", "f", "f"]
    assert [has("_schema_version", r) for r in ("SELECT", "INSERT", "UPDATE", "DELETE")] == ["t", "f", "f", "f"]
    assert [has("switch", r) for r in ("INSERT", "UPDATE", "DELETE")] == ["t", "t", "t"]  # no trail: as before


def test_t718_review_a_service_taken_out_of_the_old_group_loses_its_open_sessions(
    edc_made: tuple[Path, str],
) -> None:
    """Review H1: on a box made before this card the orchestrator is a member of `tbs_edc` and works as it
    (`SET ROLE`). When the script moves it to the writer's role, a session opened before keeps `tbs_edc` and every
    statement fails until someone restarts the service. The script ends those sessions; the service reconnects."""
    import psycopg

    root, url = edc_made
    _superuser(root, "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tbs_edc') THEN "
                     "CREATE ROLE tbs_edc NOLOGIN; END IF; END $$; GRANT tbs_edc TO tb_orchestrator")  # fmt: skip
    old = psycopg.connect(_as(url, "tb_orchestrator"), autocommit=True)
    try:
        old.execute("SET ROLE tbs_edc")
        _run_script(root)
        with pytest.raises(psycopg.OperationalError):
            old.execute("SELECT 1")
    finally:
        old.close()
    assert _superuser(root, "SELECT pg_has_role('tb_orchestrator', 'tbs_edc', 'MEMBER')") == "f"
    with psycopg.connect(_as(url, "tb_orchestrator"), autocommit=True) as con:  # the service's next connection
        assert con.execute("SELECT count(*) >= 0 FROM edc.switch_event").fetchone() == (True,)
        # a session that was not in the old group is left alone by a rerun
        _run_script(root)
        assert con.execute("SELECT 1").fetchone() == (1,)


def test_t718_review_a_service_does_not_make_a_missing_owned_schema(edc_made: tuple[Path, str]) -> None:
    """Review M1: with the schema gone (a restore that died between its drop and its load) the service made it,
    and so owned it and its triggers. A schema that has an owner role in the cluster is the install step's."""
    from edc.store import EdcStore
    from tb_common.db import DatabaseError

    root, url = edc_made
    _superuser(root, "DROP SCHEMA edc CASCADE", pglocal.DB)
    try:
        with pytest.raises(DatabaseError, match="trialbox migrate"):
            EdcStore(_as(url, "tb_orchestrator"), EDC_KEY)
        assert _superuser(root, "SELECT count(*) FROM pg_namespace WHERE nspname = 'edc'", pglocal.DB) == "0"
    finally:  # as the runbook says after a restore: the role script, then the migrate step
        _run_script(root)
        EdcStore(url, EDC_KEY).close()
    assert _superuser(root, "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'edc'",
                      pglocal.DB) == "tbo_edc"  # fmt: skip
