"""NEW-SITE-4 (D-714): Reset of a practice space drops the OMOP store a publish made for it.

A space other than the hospital's own (``main``) has a lake of its own, a library lake in the orchestrator's
process. With the lake built from OMOP (``lake.source`` = ``omop``) a publish of that space makes and loads a store
of record ``omop_<hash of the space's lake folder>`` in the trial database, and an upload to the space can hold a
site's real rows. ``SiteSetup.reset`` deleted the space's rows and folder and left that store: the uploaded
patients stayed in the database after the space was "reset", and nothing else in the box drops such a store.

Synthetic data only."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from omop import schema
from sitesetup import help
from sitesetup.service import SiteSetup
from tb_common.db import Database, split_url

from tests.unit.test_db_roles import roles_cluster  # noqa: F401 - the fixture is used by name
from tests.unit.test_site_setup import svc  # noqa: F401 - the fixture is used by name

WS = "newsite"
OTHER = "othersite"


def _store_of(s: SiteSetup, ws: str) -> str:
    """The full schema name of the space's OMOP store in the trial database."""
    _, prefix = split_url(os.environ["TB_DB_URL"])
    return prefix + schema.schema_for(s.root / ws / "lake")


def _persons(name: str) -> int | None:
    """Rows of ``person`` in the store ``name``; None when there is no such store."""
    with Database.connect(os.environ["TB_DB_URL"], "auth") as db:
        if not db.fetchval("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = ?)", (name,)):
            return None
        return int(db.fetchval(f'SELECT count(*) FROM "{name}".person'))  # the test's own name


def _audit(tmp: Path, event: str) -> list[dict[str, Any]]:
    rows = [json.loads(x) for p in sorted((tmp / "audit").glob("*.jsonl")) for x in p.read_text().splitlines() if x]
    return [r for r in rows if r["event"] == event]


@pytest.fixture
def from_omop(svc: SiteSetup, monkeypatch: pytest.MonkeyPatch) -> SiteSetup:  # noqa: F811
    monkeypatch.setenv("TB_LAKE_SOURCE", "omop")  # no flag row in this database: the variable seeds the source
    return svc


def test_a_publish_of_a_practice_space_makes_a_store_and_reset_drops_it_and_only_it(
    from_omop: SiteSetup, tmp_path: Path
) -> None:
    s = from_omop
    inp = help.practice_inputs()
    s.add_sheet(WS, "dump", inp["dump"][0], inp["dump"][1], {}, "crc")
    s.add_sheet(OTHER, "dump", inp["dump"][0], inp["dump"][1], {}, "crc")
    mine, theirs = _store_of(s, WS), _store_of(s, OTHER)
    assert mine != theirs and mine.split("omop_")[-1] != ""
    assert (_persons(mine) or 0) >= 4 and (_persons(theirs) or 0) >= 4  # the uploaded patients are in the database
    s.reset(WS, "crc")
    assert _persons(mine) is None, "the space was reset and its patients are still in its OMOP store"
    assert (_persons(theirs) or 0) >= 4  # another space's store is not touched
    done = _audit(tmp_path, "setup.reset")
    assert done and done[-1]["detail"] == {"ws": WS, "omop_store": "dropped"}
    # the space can be used again: a new upload makes the store anew
    s.add_sheet(WS, "dump", inp["dump"][0], inp["dump"][1], {}, "crc")
    assert (_persons(mine) or 0) >= 4


def test_the_store_is_found_where_the_publish_made_it_when_omop_has_a_database_of_its_own(
    from_omop: SiteSetup, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review's case: ``TB_OMOP_DB_URL`` names where the OMOP stores are (``omop.schema.db_url``). Reset read
    ``TB_DB_URL`` only, looked in the wrong place, left the patients and audited "none"."""
    dsn, prefix = split_url(os.environ["TB_DB_URL"])
    sep = "&" if "?" in dsn else "?"
    monkeypatch.setenv("TB_OMOP_DB_URL", f"{dsn}{sep}tb_prefix={prefix}om_")
    s = from_omop
    inp = help.practice_inputs()
    s.add_sheet(WS, "dump", inp["dump"][0], inp["dump"][1], {}, "crc")
    name = f"{prefix}om_" + schema.schema_for(s.root / WS / "lake")
    assert (_persons(name) or 0) >= 4 and _persons(_store_of(s, WS)) is None  # made where OMOP lives
    s.reset(WS, "crc")
    assert _persons(name) is None
    assert _audit(tmp_path, "setup.reset")[-1]["detail"] == {"ws": WS, "omop_store": "dropped"}
    with Database.connect(os.environ["TB_DB_URL"], "auth") as db:  # asking made no schema in the OMOP database
        made = db.fetchval("SELECT count(*) FROM pg_namespace WHERE nspname = ?", (f"{prefix}om_sitesetup",))
    assert made == 0


def test_no_publish_of_the_space_can_run_while_it_is_reset(from_omop: SiteSetup) -> None:
    """The review's case: a publish between the drop and the deletion of the rows made the store anew, with the
    patients in it, and the audit said "dropped". Reset holds the lock a publish takes, from first to last."""
    import threading

    s = from_omop
    inp = help.practice_inputs()
    s.add_sheet(WS, "dump", inp["dump"][0], inp["dump"][1], {}, "crc")
    free: list[bool] = []
    real = s.store.reset

    def during(ws: str) -> None:
        def other() -> None:
            got = s._lock.acquire(blocking=False)
            free.append(got)
            if got:
                s._lock.release()

        t = threading.Thread(target=other)
        t.start()
        t.join()
        real(ws)

    s.store.reset = during  # type: ignore[method-assign]
    s.reset(WS, "crc")
    assert free == [False]
    assert _persons(_store_of(s, WS)) is None


def test_a_store_that_cannot_be_dropped_stops_the_reset_before_anything_is_deleted(
    from_omop: SiteSetup, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = from_omop
    inp = help.practice_inputs()
    s.add_sheet(WS, "dump", inp["dump"][0], inp["dump"][1], {}, "crc")
    real = Database.execute

    def refused(self: Database, sql: str, *a: Any, **k: Any) -> Any:
        if sql.startswith("DROP SCHEMA"):
            raise RuntimeError("permission denied for schema")
        return real(self, sql, *a, **k)

    monkeypatch.setattr(Database, "execute", refused)
    with pytest.raises(RuntimeError):
        s.reset(WS, "crc")
    assert len(s.store.inputs(WS)) == 1 and (s.root / WS).is_dir()  # the space is as it was
    assert (_persons(_store_of(s, WS)) or 0) >= 4 and _audit(tmp_path, "setup.reset") == []


def test_reset_of_a_space_that_never_had_a_store_says_so_and_makes_none(svc: SiteSetup, tmp_path: Path) -> None:  # noqa: F811
    inp = help.practice_inputs()
    svc.add_sheet(WS, "dump", inp["dump"][0], inp["dump"][1], {}, "crc")  # the default source: no OMOP store
    name = _store_of(svc, WS)
    assert _persons(name) is None
    svc.reset(WS, "crc")
    assert _persons(name) is None  # asking made nothing
    assert _audit(tmp_path, "setup.reset")[-1]["detail"] == {"ws": WS, "omop_store": "none"}


def test_the_hospitals_own_store_is_never_the_one_dropped(svc: SiteSetup) -> None:  # noqa: F811
    from sitesetup.store import SetupError

    with pytest.raises(SetupError):
        svc.reset("main", "crc")
    assert schema.schema_for(svc.root / WS / "lake") != schema.SCHEMA


def test_under_the_service_roles_the_orchestrator_owns_such_a_store_and_can_drop_it(
    roles_cluster: tuple[Path, str],  # noqa: F811
) -> None:
    """Who may open a practice space's store on a box (the real role script): the orchestrator's own login role
    makes it and owns it, with no group role, so the orchestrator opens it and no other service does; the box's
    admin role (a member of every service role, for backups) reaches it too. Reset, which runs as the
    orchestrator, can drop it. Stated as it is (D-714): the role model for it is lane D's to judge."""
    from tests.unit.test_db_roles import _as

    url = roles_cluster[1]
    name = "omop_0123456789"
    with Database.connect(_as(url, "tb_orchestrator"), name) as db:
        db.execute("CREATE TABLE person (person_id BIGINT)")
        assert db.fetchval("SELECT current_user") == "tb_orchestrator"  # no group role to take
    with Database.connect(url, "auth") as admin:
        owner = admin.fetchval("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = ?", (name,))
        may = {r: admin.fetchval("SELECT has_schema_privilege(?, ?, 'USAGE')", (r, name))
               for r in ("tb_orchestrator", "tb_console", "tb_adapter", "tb_lake", "trialbox")}  # fmt: skip
    assert owner == "tb_orchestrator"
    assert may == {"tb_orchestrator": True, "tb_console": False, "tb_adapter": False, "tb_lake": False,
                   "trialbox": True}, may  # fmt: skip
    with Database.connect(_as(url, "tb_orchestrator"), name) as db:
        db.execute(f'DROP SCHEMA "{name}" CASCADE')
    with Database.connect(url, "auth") as admin:
        assert not admin.fetchval("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = ?)", (name,))
