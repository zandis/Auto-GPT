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


ACCESS = _access()
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


def _superuser(root: Path, sql: str) -> str:
    r = subprocess.run(
        [str(pglocal.bindir() / "psql"), "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-tAqc", sql],
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
        assert sorted(rows) == [(s, f"tbs_{s}") for s in SCHEMAS]


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
    root = roles_cluster[0]
    member = "SELECT pg_has_role('tb_console', 'tbs_edc', 'MEMBER')"
    _superuser(root, "GRANT tbs_edc TO tb_console")  # as the script before D-461 left it
    assert _superuser(root, member) == "t"
    _run_script(root)
    assert _superuser(root, member) == "f"
    assert _superuser(root, "SELECT pg_has_role('tb_orchestrator', 'tbs_edc', 'MEMBER')") == "t"


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
