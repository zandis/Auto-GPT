"""D-683: the opt-out worker on a box with the install's roles (D-378). Synthetic pseudonyms only.

The real ``deploy/docker/db-init/30-service-roles.sh`` runs against a throwaway cluster; the stores are made by
the box's admin, as the install does; the worker then runs as ``tb_orchestrator``, as it does on a box. Until this
card the tick asked "is there an OMOP store" over the opt-out register's connection, which works as the register's
group role and may not use the ``omop`` schema: the question raised, and the whole tick stopped before its first
step. The same question for the vector, pid-map and profile stores raised too.
"""

from __future__ import annotations

import ast
import os
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tb_common.db import Database
from tb_common.optout import OptOutRegister

from tests.unit.test_db_roles import _as, _run_script
from tests.unit.test_optout_worker import T0, A, Audit, B, C, Jobs, Lake, _batch, _live
from tools import pglocal

ROOT = Path(__file__).resolve().parents[2]
D, E, F = "a1b2c3d4e5f60004", "a1b2c3d4e5f60005", "a1b2c3d4e5f60006"
ALL = [A, B, C, D, E]  # the fixture's feed; F arrives with the adapter's dual write
NIGHT1, NIGHT2 = "2026-11-01", "2026-11-02"
# The tests share one cluster and must pass in any order: each asserts only on its own patients (the tick: A and B;
# the store that cannot be opened: D; the dual write: F; C and E are never opted out).


@pytest.fixture(scope="module")
def box() -> Iterator[str]:
    """A cluster with the role script applied and the stores a box has: the register (A opted out by the office),
    an OMOP store holding A to E, the pid map's staging with rows of A, C and D. Yields the orchestrator's URL."""
    if shutil.which("sh") is None:
        pytest.skip("no sh")
    try:
        pglocal.bindir()
    except RuntimeError as exc:
        pytest.skip(str(exc))
    base = Path(os.environ["TB_TEST_ROOT"]) if os.environ.get("TB_TEST_ROOT") else None
    if base is not None:
        base.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="tb-pgoptout-", dir=base))
    root.chmod(0o755)
    admin = pglocal.ensure(root)
    try:
        _run_script(root)
        reg = OptOutRegister(admin)
        reg.add(A, "office", "by letter", "office:t", T0)
        reg.close()
        from omop import schema
        from omop.load import load_batch

        with schema.connect(admin) as omop:
            load_batch(omop, "feed", NIGHT1, _batch(ALL), tz="Asia/Taipei")
        with Database.connect(admin, "pidmap") as pm:
            pm.execute("CREATE TABLE pending (pid TEXT, night TEXT)")
            pm.execute("INSERT INTO pending VALUES (?, 'n'), (?, 'n'), (?, 'n')", (A, C, D))
        yield _as(admin, "tb_orchestrator")
    finally:
        pglocal.stop(root)
        shutil.rmtree(root, ignore_errors=True)


def _orch(lake: Any) -> Any:
    return SimpleNamespace(
        cfg=SimpleNamespace(env=SimpleNamespace(tz="Asia/Taipei")),
        audit=Audit(),
        services=SimpleNamespace(lake=lake),
        db=Jobs(),
    )


def _omop_live(url: str, pid: str) -> int:
    with Database.connect(url, "omop") as db:
        return _live(db, pid)


def _pending(url: str) -> list[str]:
    with Database.connect(url, "pidmap") as db:
        return sorted(str(r[0]) for r in db.fetchall("SELECT pid FROM pending"))


def test_the_register_works_as_its_group_role_which_may_not_use_another_store(box: str) -> None:
    """Why the old question failed: PostgreSQL answers ``to_regclass`` about a schema the role may not use with an
    error, not with NULL."""
    import psycopg

    reg = OptOutRegister(box)
    try:
        assert reg.db.fetchval("SELECT current_user") == "tbs_optout"
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reg.db.fetchval("SELECT to_regclass(?)", ('"omop".tb_record',))
    finally:
        reg.close()


def test_a_tick_as_the_orchestrators_role_reaches_every_store(box: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from datacore import optout_worker as w

    monkeypatch.setenv("TB_DB_URL", box)
    orch = _orch(Lake([(B, "rejected", None, "2026-11-01")]))  # the hospital registry refuses B
    out = w.tick(orch)
    assert out is not None, w.status()  # before: None, STATUS failed ["tick"], nothing of the tick ran
    assert out["failed"] == [] and w.status()["failed"] == []
    assert out["registry"] is not None and out["opted_out"] >= 2
    assert "skipped" not in out["stores"]["omop"]
    assert _omop_live(box, A) == 0 and _omop_live(box, B) == 0
    assert _omop_live(box, C) > 0 and _omop_live(box, E) > 0
    assert A not in _pending(box) and C in _pending(box)
    assert not [k for k in orch.db.pool if k[1] in (A, B)]
    assert out["stores"]["vec"] == {"skipped": 1} and out["stores"]["profile"] == {"skipped": 1}  # not on this box
    reg = OptOutRegister(box)
    try:
        assert {A, B} <= reg.active()  # B: the registry's refusal was copied
    finally:
        reg.close()


def test_an_omop_store_that_cannot_be_opened_is_named_and_the_other_stores_are_cleared(
    box: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacore import optout_worker as w

    monkeypatch.setenv("TB_DB_URL", box)
    reg = OptOutRegister(box)
    reg.add(D, "office", "by letter", "office:t", T0)
    reg.close()
    assert _omop_live(box, D) > 0 and D in _pending(box)

    def broken(reg: Any) -> Any:
        raise RuntimeError(f"cannot open the store for {D}")

    monkeypatch.setattr(w, "_omop_store", broken)
    orch = _orch(Lake([(B, "rejected", None, "2026-11-01")]))
    out = w.tick(orch)
    assert out is not None
    assert out["failed"] == ["omop"] and w.status()["failed"] == ["omop"]
    assert out["registry"] is not None  # the registry was read
    assert D not in _pending(box)  # the other stores were cleared in the same tick
    assert _omop_live(box, D) > 0  # and OMOP is not reported as cleared: it is in `failed`
    assert "omop" not in out["stores"]
    assert D not in str(out) and D not in str(orch.audit.events)
    monkeypatch.undo()
    monkeypatch.setenv("TB_DB_URL", box)
    again = w.tick(_orch(Lake([(B, "rejected", None, "2026-11-01")])))  # the next tick, the store opens: erased
    assert again is not None and again["failed"] == [] and _omop_live(box, D) == 0


def test_no_code_asks_whether_a_table_exists_over_another_stores_connection() -> None:
    """The class of this fault: ``to_regclass`` about a schema, asked on a connection that works as another
    schema's group role, raises on a box with roles and answers on a developer's database. Every use in the
    services and libraries is listed here with why it may ask; the list only shrinks."""
    listed = {
        "libs/tb_common/flags.py": (4, "the flags' own schema, on its own connection or one without a group role"),
        "libs/tb_common/optout.py": (2, "the register's own table; the pid map only after has_schema_privilege"),
        "services/orchestrator/scenarios/retention.py": (1, "the site store's own schema, on its connection"),
        "services/orchestrator/scheduler.py": (1, "the site store's own schema, on its connection"),
        "services/console/firstrun.py": (1, "the pid map over the console's auth connection: the console lane's"),
    }
    found: Counter[str] = Counter()
    for top in ("libs", "services"):
        for f in sorted((ROOT / top).rglob("*.py")):
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and "to_regclass" in node.value:
                    found[str(f.relative_to(ROOT))] += 1
    docs = {  # a docstring that explains the function is not a question
        k: sum(
            1
            for n in ast.walk(ast.parse((ROOT / k).read_text(encoding="utf-8")))
            if isinstance(n, ast.FunctionDef | ast.ClassDef | ast.Module)
            and "to_regclass" in (ast.get_docstring(n) or "")
        )
        for k in found
    }
    asked = {k: n - docs[k] for k, n in found.items() if n - docs[k]}
    assert asked == {k: n for k, (n, _) in listed.items()}
    assert "services/datacore/optout_worker.py" not in asked


def _as_role(box: str, role: str) -> str:
    return box.replace("tb_orchestrator@", f"{role}@", 1)


def _feed_now(db: Any) -> tuple[str, list[str]]:
    """The store's newest feed batch and its patients (the dual-write test adds a night and F)."""
    last = str(db.fetchval("SELECT max(batch) FROM tb_load WHERE source_kind = 'feed'"))
    return last, ([*ALL, F] if last == NIGHT2 else ALL)


@pytest.mark.parametrize("role", ["tb_adapter", "tb_lake", "tb_orchestrator"])
def test_a_service_loads_the_omop_store_under_the_role_script(box: str, role: str) -> None:
    """The load works in temporary tables, as the store's group role (``tb_common.db`` sets it). The script gave
    the right to make them to the service roles and took it from PUBLIC, so the group had none: no role could
    load the OMOP store on a box with roles. The same batch again inserts nothing (idempotent)."""
    from omop import schema
    from omop.load import load_batch

    with schema.connect(_as_role(box, role)) as db:
        assert db.fetchval("SELECT current_user") == "tbs_omop"
        assert db.fetchval("SELECT has_database_privilege(current_user, current_database(), 'TEMPORARY')") is True
        assert db.fetchval("SELECT has_database_privilege(current_user, current_database(), 'CREATE')") is False
        batch, pids = _feed_now(db)
        rep = load_batch(db, "feed", batch, _batch(pids), tz="Asia/Taipei")
        assert rep.inserted == 0


def test_the_export_as_of_a_time_runs_under_the_role_script(box: str) -> None:
    """``omop.export`` winds the store back in a temporary table: as the lake's role, as the lake serves it."""
    from omop import schema
    from omop.export import export_rows

    with schema.connect(_as_role(box, "tb_lake")) as db:
        rows = export_rows(db, as_of=datetime.now(UTC))
        assert {str(r["pid"]) for r in rows["patient"]} >= {C, E}
        before = export_rows(db, as_of=datetime(2020, 1, 1, tzinfo=UTC))
        assert before["patient"] == []


def test_an_athena_bundle_loads_under_the_role_script(box: str) -> None:
    """``omop athena`` (the host tool, the box's admin) stages the bundle's concepts in a temporary table."""
    from omop import schema, vocab_load

    bundle = ROOT / "tests" / "fixtures" / "vocab" / "athena-test"
    with schema.connect(_as_role(box, "trialbox")) as db:
        assert db.fetchval("SELECT current_user") == "tbs_omop"
        vocab_load.load_athena(db, bundle, by="test")
        assert vocab_load.athena_loaded(db)


def test_end_to_end_the_adapters_dual_write_loads_a_record_and_the_worker_erases_it(
    box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The proof nobody had: with the install's roles, the adapter (as ``tb_adapter``) writes a night into the OMOP
    store through the dual write, the office opts the patient out, and one tick of the worker (as
    ``tb_orchestrator``) takes the patient out of the store."""
    import json

    from adapter import dual_write
    from adapter.pipeline import AdapterConfig
    from datacore import optout_worker as w

    lake = tmp_path / "lake"
    night = lake / "ndjson" / NIGHT2
    night.mkdir(parents=True)
    for rtype, rows in _batch([*ALL, F]).items():
        (night / f"{rtype}.ndjson").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setenv("TB_LAKE_DIR", str(lake))  # the box's lake: the store is the schema `omop`
    monkeypatch.setenv("TB_OMOP_DUAL_WRITE", "on")
    monkeypatch.delenv("TB_OMOP_DB_URL", raising=False)
    cfg = AdapterConfig(
        lake_dir=lake, secrets_dir=tmp_path / "sec", mapping_path=tmp_path / "unused.yaml", site_id="DEMO-A",
        tz="Asia/Taipei", db_url=_as_role(box, "tb_adapter"),
    )  # fmt: skip
    summary = dual_write.load_night(cfg, NIGHT2, night)
    assert summary is not None and summary.state == "loaded", summary
    assert summary.schema_name == "omop" and summary.counts is not None
    assert _omop_live(box, F) > 0  # the record is in the store, written by the adapter's role

    monkeypatch.setenv("TB_DB_URL", box)
    reg = OptOutRegister(box)
    reg.add(F, "office", "by letter", "office:t", T0)
    reg.close()
    out = w.tick(_orch(Lake([(B, "rejected", None, "2026-11-01")])))
    assert out is not None and out["failed"] == [], out
    assert _omop_live(box, F) == 0 and _omop_live(box, E) > 0
    with Database.connect(box, "omop") as db:
        assert db.fetchval("SELECT count(*) FROM tb_withheld WHERE pid = ?", (F,)) == 1


def test_a_service_on_an_owned_schema_works_as_itself(box: str) -> None:
    """D-486: on an owned schema (``edc``) a service's session keeps its login role, which holds TEMPORARY itself:
    the owner, writer and reader roles are given nothing by D-683."""
    with Database.connect(box, "edc") as db:
        assert db.fetchval("SELECT current_user") == "tb_orchestrator"
        got: dict[str, bool] = dict(db.fetchall(
            "SELECT rolname, has_database_privilege(rolname, current_database(), 'TEMPORARY') FROM pg_roles "
            "WHERE rolname IN ('tbo_edc', 'tbw_edc', 'tbr_edc')"
        ))  # fmt: skip
        assert got and not any(got.values()), got
