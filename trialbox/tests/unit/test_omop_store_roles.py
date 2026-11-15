"""OMOP-STORE (D-721): a service makes no OMOP store of its own. Under the role script a store named for another
lake (``omop_<10 hex>``) had no group: the service that opened it first made it and owned it, and no other service
could open it (lane E, by running, 2026-11-13). A service now refuses to make one; the admin step makes it for the
OMOP group, and every service on ``omop``'s list opens it as that group."""

from __future__ import annotations

import os
import shlex
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from omop import load, schema
from omop.schema import OmopError

from tools import backup_drill, pglocal, role_paths
from tools.trialbox import backup as bk
from tools.trialbox import omop_store

ROOT = Path(__file__).resolve().parents[2]
ACCESS = backup_drill.service_access(role_paths.ROLES_SCRIPT)
ON_THE_LIST = sorted(r for r, schemas in ACCESS.items() if "omop" in schemas)
OFF_THE_LIST = sorted(r for r, schemas in ACCESS.items() if "omop" not in schemas)
OTHER_LAKE = Path("/srv/practice-b/lake")


def _as(url: str, role: str) -> str:
    return url.replace("postgresql://trialbox@", f"postgresql://{role}@", 1)


def _admin(url: str, sql: str, *params: Any) -> Any:
    import psycopg

    with psycopg.connect(url, autocommit=True) as con:
        row = con.execute(sql, params).fetchone()
        return row[0] if row else None


@pytest.fixture(scope="module")
def box() -> Iterator[str]:
    """A cluster of its own with the real role script applied, as the installer leaves a box."""
    if shutil.which("sh") is None:
        pytest.skip("no sh")
    try:
        pglocal.bindir()
    except RuntimeError as exc:
        pytest.skip(str(exc))
    base = Path(os.environ["TB_TEST_ROOT"]) if os.environ.get("TB_TEST_ROOT") else None
    if base is not None:
        base.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="tb-omopstore-", dir=base))
    root.chmod(0o755)
    url = pglocal.ensure(root)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(
        PATH=f"{pglocal.bindir()}:{env.get('PATH', '')}",
        PGHOST=str((root / "run").resolve()),
        POSTGRES_USER="postgres",
        TB_WF_DB=pglocal.DB,
        TB_DB_ROLES_CMD=f"sh {shlex.quote(str(role_paths.ROLES_SCRIPT))}",
    )
    try:
        assert bk.reapply_service_roles(env)["state"] == "applied"
        yield url
    finally:
        pglocal.stop(root)
        shutil.rmtree(root, ignore_errors=True)


def _exists(url: str, name: str) -> bool:
    return bool(_admin(url, "SELECT count(*) FROM pg_namespace WHERE nspname = %s", name))


@pytest.mark.parametrize("role", schema.LAKE_SHARERS)
def test_a_service_refuses_to_make_a_second_lakes_store(box: str, role: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_LAKE_DIR", "/data/lake")
    # a lake no other test of the module makes a store for: in random order (the nightly) the admin's test may have
    # made OTHER_LAKE's store already, and then there is nothing to refuse (NIGHT-ORDER, D-733)
    lake = Path(f"/srv/never-made-by-{role}/lake")
    name = schema.schema_for(lake)
    assert name.startswith("omop_") and name != "omop" and name != schema.schema_for(OTHER_LAKE)
    with pytest.raises(OmopError) as stop:
        schema.connect(_as(box, role), name, lake_dir=lake)
    said = str(stop.value)
    assert name in said and str(lake) in said  # which store, which folder
    assert "TB_LAKE_DIR" in said and "/data/lake" in said  # what the box's lake is
    assert "trialbox omop-store" in said  # who makes it
    assert not _exists(box, name)  # and nothing was made


def test_a_lake_service_started_without_its_lake_folder_refuses_and_makes_nothing(
    box: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The trap: ``lake/app.py`` falls back to /data/lake when ``TB_LAKE_DIR`` is not set, ``schema_for`` then sees
    no box lake and names the store ``omop_<hex>``: the lake's own, read by nobody else."""
    monkeypatch.delenv("TB_LAKE_DIR", raising=False)
    folder = Path("/data/lake")
    name = schema.schema_for(folder)
    assert name != "omop"
    with pytest.raises(OmopError, match="TB_LAKE_DIR is not set"):
        schema.connect(_as(box, "tb_lake"), name, lake_dir=folder)
    assert not _exists(box, name)


def test_the_orchestrator_makes_a_site_spaces_store_and_it_is_its_own(
    box: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Found by lane B2 from the lake's side: ``SiteSetup.lake(ws)`` for a space other than ``main`` is a lake under
    the orchestrator's data folder, rebuilt in the orchestrator's process, which has no ``TB_LAKE_DIR``. With the
    OMOP lake source it makes ``omop_<hash>`` as ``tb_orchestrator``. Only that process reads a space's lake, so
    the store is the orchestrator's own and it must go on making it: the refusal is not for it."""
    import psycopg
    from lake.source import lake_rows

    monkeypatch.delenv("TB_LAKE_DIR", raising=False)
    monkeypatch.setenv("TB_DB_URL", _as(box, "tb_orchestrator"))
    folder = Path("/data/orch/sitesetup/practice/lake")
    name = schema.schema_for(folder)
    rows = lake_rows(role_paths._patient(), {}, tz="Asia/Taipei", snapshot="2000-01-02", source="omop", lake_dir=folder)
    assert sum(len(list(v)) for v in rows.values()) > 0
    owner = "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = %s"
    assert _admin(box, owner, name) == "tb_orchestrator"
    for other in ("tb_lake", "tb_adapter", "tb_console"):
        with (
            psycopg.connect(_as(box, other), autocommit=True) as con,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            con.execute(f'SELECT count(*) FROM "{name}".person')
    with psycopg.connect(_as(box, "tb_orchestrator"), autocommit=True) as con:  # what a Reset of the space owes
        con.execute(f'DROP SCHEMA "{name}" CASCADE')
    assert not _exists(box, name)


@pytest.mark.parametrize("maker", ["trialbox", "tb_gateway"])
def test_the_admins_step_does_not_call_a_store_made_by_someone_else_ready(
    box: str, maker: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Found by the review, by running: a store first opened by a host tool as the admin is the admin's; a service
    off the list can make a schema of that name (it has CREATE on the database). The step said "the store is X"
    and no service could open it."""
    import psycopg

    monkeypatch.setenv("TB_LAKE_DIR", "/data/lake")
    folder = Path(f"/srv/made-by-{maker}/lake")
    name = schema.schema_for(folder)
    with psycopg.connect(_as(box, maker), autocommit=True) as con:
        con.execute(f'CREATE SCHEMA "{name}"')
    with pytest.raises(omop_store.NotTheGroups) as stop:
        omop_store.make(box, folder)
    said = str(stop.value)
    assert name in said and maker in said and "tbs_omop" in said
    assert _admin(box, "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = %s", name) == maker


def test_the_command_exits_1_on_a_store_that_is_not_the_groups(
    box: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import psycopg

    monkeypatch.setenv("TB_LAKE_DIR", "/data/lake")
    monkeypatch.setenv("TB_DB_URL", box)
    folder = Path("/srv/made-by-the-lake-before-this-card/lake")
    name = schema.schema_for(folder)
    with psycopg.connect(_as(box, "tb_lake"), autocommit=True) as con:
        con.execute(f'CREATE SCHEMA "{name}"')
    assert omop_store.main_action(folder) == 1
    assert "tb_lake" in capsys.readouterr().err


def test_the_refusal_is_for_the_two_services_that_share_a_lake_and_no_other() -> None:
    assert schema.LAKE_SHARERS == ("tb_lake", "tb_adapter")
    assert set(schema.LAKE_SHARERS) <= set(ON_THE_LIST)


def test_the_two_services_that_name_a_store_by_its_lake_say_which_folder() -> None:
    for path, call in (
        ("services/lake/source.py", "schema.connect(url, schema.schema_for(lake_dir), lake_dir=lake_dir)"),
        ("services/adapter/dual_write.py", "schema.connect(_omop_url(cfg), name, lake_dir=cfg.lake_dir)"),
    ):
        assert call in (ROOT / path).read_text(encoding="utf-8"), path


def test_the_admin_makes_it_and_every_service_on_omops_list_works_in_it_as_the_group(
    box: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_LAKE_DIR", "/data/lake")
    name = omop_store.make(box, OTHER_LAKE)
    assert name == schema.schema_for(OTHER_LAKE)
    owner = "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = %s"
    assert _admin(box, owner, name) == "tbs_omop"
    assert omop_store.make(box, OTHER_LAKE) == name  # a second run changes nothing
    writer = schema.connect(_as(box, "tb_adapter"), name, lake_dir=OTHER_LAKE)
    try:
        assert writer.fetchval("SELECT current_user") == "tbs_omop"
        load.load_batch(writer, "feed", "2000-01-02", role_paths._patient())
    finally:
        writer.close()
    for role in ON_THE_LIST:
        db = schema.connect(_as(box, role), name, lake_dir=OTHER_LAKE)
        try:
            assert db.fetchval("SELECT current_user") == "tbs_omop", role
            assert db.fetchval("SELECT count(*) FROM person") == 1, role
        finally:
            db.close()
    owners = "SELECT count(*) FROM pg_class c WHERE c.relnamespace = %s::regnamespace AND c.relkind = 'r' " \
             "AND pg_get_userbyid(c.relowner) <> 'tbs_omop'"  # fmt: skip
    assert _admin(box, owners, name) == 0  # what the migration and the load made is the group's, not a service's


@pytest.mark.parametrize("role", OFF_THE_LIST)
def test_a_service_off_omops_list_opens_neither_store(box: str, role: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_LAKE_DIR", "/data/lake")
    name = omop_store.make(box, OTHER_LAKE)
    with pytest.raises(Exception) as stop:
        schema.connect(_as(box, role), name, lake_dir=OTHER_LAKE).close()
    assert "no schema has been selected" in str(stop.value) or "permission denied" in str(stop.value)
    theirs = (
        "SELECT count(*) FROM pg_class c WHERE c.relnamespace = %s::regnamespace AND pg_get_userbyid(c.relowner) = %s"
    )
    assert _admin(box, theirs, name, role) == 0  # it made nothing there
    import psycopg

    with psycopg.connect(_as(box, role), autocommit=True) as con, pytest.raises(psycopg.errors.InsufficientPrivilege):
        con.execute(f'SELECT count(*) FROM "{name}".person')


def test_the_boxs_own_store_is_made_by_a_service_as_before(box: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """``omop`` is on the list: the role script made the schema for its group, and the first service fills it."""
    monkeypatch.setenv("TB_LAKE_DIR", "/data/lake")
    assert schema.schema_for(Path("/data/lake")) == "omop"
    db = schema.connect(_as(box, "tb_adapter"), lake_dir=Path("/data/lake"))
    try:
        assert db.fetchval("SELECT current_user") == "tbs_omop"
    finally:
        db.close()


def test_without_the_role_script_a_tool_makes_any_store_it_names(db_url: str) -> None:
    """Goldens, the parity tool, the in-process boxes and the tests: a database without the role script has no
    OMOP group, and whoever opens a store makes it, as before."""
    name = schema.schema_for(Path("/tmp/another-lake-of-a-tool"))
    db = schema.connect(db_url, name, lake_dir=Path("/tmp/another-lake-of-a-tool"))
    try:
        assert db.fetchval("SELECT count(*) FROM person") == 0
    finally:
        db.close()


def test_the_drill_has_the_lines_for_a_second_lakes_store_and_a_site_spaces() -> None:
    names = [name for name, _ in role_paths.PATHS]
    assert any("a second lake's OMOP store" in n for n in names)
    assert any("a site space's OMOP store as tb_orchestrator" in n for n in names)
