"""Deep review 2026-11-13 (data), DATA-001 to DATA-003: a store's connection runs as its schema's group role on a box
(D-378, ``SET ROLE tbs_<schema>``), so a check of ANOTHER schema made through it must not need that schema's USAGE.

Before the fix, on a cluster set up by the real ``deploy/docker/db-init/30-service-roles.sh``:

* the opt-out worker's tick, as ``tb_orchestrator``, failed with "permission denied for schema omop" before it
  cleared any store (the nightly compose log's line; handover 2026-11-13 §3);
* ``tb_common.optout.with_survivors`` read ``has_schema_privilege`` as ``tbs_optout`` and returned the opted-out pid
  alone: the surviving pid of a merged chart stayed on every list (review MED-4 off on every box, failing open);
* the console's first-run page could never say the pid map was empty, so the chart-number rule could not be chosen.

These tests use the cluster of ``test_db_roles.py`` (the role script applied twice).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tb_common.db import Database

from tests.unit.test_db_roles import _as, roles_cluster  # noqa: F401 - the module's cluster fixture

OLD, NEW = "OLDPID0001", "NEWPID0001"


@pytest.fixture(scope="module")
def merged(roles_cluster: tuple[Path, str]) -> Iterator[str]:  # noqa: F811
    """The pid map holds one merge, OLD into NEW, made by the box's admin as a migration would."""
    url = roles_cluster[1]
    with Database.connect(url, "pidmap") as pm:
        pm.execute("CREATE TABLE IF NOT EXISTS pid_alias (old_pid TEXT PRIMARY KEY, pid TEXT NOT NULL)")
        pm.execute("INSERT INTO pid_alias VALUES (?, ?) ON CONFLICT DO NOTHING", (OLD, NEW))
    yield url


def test_table_exists_needs_no_usage_on_the_schema(merged: str) -> None:
    from tb_common.optout import OptOutRegister

    reg = OptOutRegister(_as(merged, "tb_orchestrator"))
    try:
        assert reg.db.fetchval("SELECT current_user") == "tbs_optout"
        with pytest.raises(Exception, match="permission denied"):  # what the old check ran into
            reg.db.fetchval("SELECT to_regclass('\"pidmap\".pid_alias')")
        assert reg.db.table_exists("pidmap", "pid_alias")
        assert not reg.db.table_exists("pidmap", "no_such_table")
        assert reg.db.may_use_schema("pidmap")  # tb_orchestrator's list names it
        assert not reg.db.may_use_schema("trace")  # the gateway's alone
    finally:
        reg.close()


@pytest.mark.parametrize("role", ["tb_orchestrator", "tb_console"])
def test_an_opt_out_under_a_merged_chart_hides_the_survivor(merged: str, role: str) -> None:
    from tb_common.optout import OptOutRegister, opted_out

    admin = OptOutRegister(merged)
    try:
        admin.add(OLD, "office", "", "console:office1", "2026-11-01T00:00:00+00:00")
    finally:
        admin.close()
    reg = OptOutRegister(_as(merged, role))
    try:
        assert reg.effective() >= {OLD, NEW}
    finally:
        reg.close()
    assert opted_out(_as(merged, role)) >= {OLD, NEW}


def test_the_worker_tick_as_the_orchestrator_runs(merged: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from datacore import optout_worker as w
    from omop import schema as omop_schema
    from tb_common.optout import OptOutRegister

    omop_schema.connect(merged).close()  # the box's OMOP store, made by the admin's migrate step
    admin = OptOutRegister(merged)  # this test's own opt-out, under the merged-away chart
    try:
        admin.add(OLD, "office", "", "console:office1", "2026-11-01T00:00:00+00:00")
    finally:
        admin.close()
    monkeypatch.setenv("TB_DB_URL", _as(merged, "tb_orchestrator"))
    events: list[tuple[str, Any]] = []
    removed: list[set[str]] = []

    class Audit:
        def append(self, ev: str, actor: Any = None, detail: Any = None) -> None:
            events.append((ev, detail))

    class Jobs:
        def pool_remove(self, pids: Any) -> int:
            removed.append(set(pids))
            return 0

        def pool_count(self, pids: Any) -> int:
            return 0

        def candidate_summaries(self) -> list[Any]:
            return []

    class Lake:
        def snapshot(self) -> None:
            return None

    orch = SimpleNamespace(
        cfg=SimpleNamespace(env=SimpleNamespace(tz="Asia/Taipei")),
        audit=Audit(),
        services=SimpleNamespace(lake=Lake()),
        db=Jobs(),
    )
    out = w.tick(orch)
    assert out is not None, events  # before: None, "optout.worker_failed" {"failed": ["tick"]}
    assert "tick" not in w.STATUS["failed"]
    assert ("optout.worker_failed", {"failed": ["tick"]}) not in events
    assert removed and NEW in set().union(*removed), removed  # the survivor of the merge is cleared too


def test_first_run_reads_the_pid_map_as_the_console(merged: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from console.firstrun import box_holds_patients

    monkeypatch.setenv("TB_DB_URL", _as(merged, "tb_console"))
    with Database.connect(merged, "pidmap") as pm:
        pm.execute("CREATE TABLE IF NOT EXISTS pid_map (pid TEXT PRIMARY KEY)")
        pm.execute("DELETE FROM pid_map")
    assert box_holds_patients() is False  # before: None (refused), read as "it holds patients"
    with Database.connect(merged, "pidmap") as pm:
        pm.execute("INSERT INTO pid_map VALUES ('P1')")
    assert box_holds_patients() is True
    assert os.environ["TB_DB_URL"].startswith("postgresql://tb_console@")
