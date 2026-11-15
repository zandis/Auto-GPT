"""T-206b, part 1 (D-798): an opt-out clears the owed tables keyed by the pseudonym.

The erasure registry (T-727, D-465) listed 60 obligations still owed. This part takes the rows of an opted-out
patient out of the tables the registry marks as a plain clear: the site's contact outcomes, excluded-patient reviews
and the week a patient first appeared; the team's approach overrides, cross-department views, referrals and their
events; the not-matched sample; the orchestrator's PI feedback and NAV submissions; and the derived scores with their
input links, conflicts and the pseudonym in a batch's failed list. Another patient's rows stay. The clear is the
worker's (``clear_tables``), idempotent, counts only; its verify reads every table back.

Not in this part: the screening log's tables (marks, screening numbers, candidate events, REDCap records: LIFE-005
is frozen and OD-8 keeps a consented subject's), the uploaded set-up files, the recall hashes and the files.

Synthetic pseudonyms only."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from tb_common import erasure
from tb_common.db import Database
from tb_common.optout import OptOutRegister

A, C = "a1b2c3d4e5f6a001", "a1b2c3d4e5f6a003"  # A opts out; C never does
NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
PLAIN = ("site.contact_outcomes", "site.excluded_review", "site.weekly_seen", "team.approach_overrides",
         "team.candidate_views", "team.referral_events", "team.referrals", "tuned.tuned_patients", "orch.feedback",
         "orch.submissions", "derived.input_link", "derived.conflict", "derived.score_row")  # fmt: skip


def _stores(url: str) -> None:
    """The real tables, made by each store's own migrations."""
    from console import sitestore, teamstore
    from orchestrator import db as orch_db
    from tb_common import derived_store, notmatched

    for name, mig in (("site", sitestore.MIGRATIONS), ("team", teamstore.MIGRATIONS), ("tuned", notmatched.MIGRATIONS),
                      ("orch", orch_db.MIGRATIONS), ("derived", derived_store.MIGRATIONS)):  # fmt: skip
        with Database.connect(url, name) as db:
            db.migrate(mig)


_N = iter(range(1, 10_000))


def _row(db: Any, table: str, pid: str, **given: Any) -> int | None:
    """A synthetic row: ``pid`` and the given columns, every other required column a distinct dummy of its type."""
    cols = db.fetchall(
        "SELECT column_name, data_type, is_nullable, column_default, is_identity FROM information_schema.columns"
        " WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
        (db.schema, table),
    )
    vals: dict[str, Any] = {"pid": pid, **given}
    for name, typ, nullable, default, ident in cols:
        if name in vals or nullable == "YES" or default is not None or ident == "YES":
            continue
        n = next(_N)
        vals[name] = {"bigint": n, "integer": n, "smallint": 1, "boolean": True, "double precision": 1.0,
                      "date": "2026-01-01"}.get(typ, f"{name}-{n}")  # fmt: skip
    names = [c[0] for c in cols if c[0] in vals]
    has_id = any(c[0] == "id" for c in cols)
    sql = f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})"
    if has_id:
        return int(db.fetchval(sql + " RETURNING id", tuple(vals[c] for c in names)))
    db.execute(sql, tuple(vals[c] for c in names))
    return None


def _fill(url: str) -> None:
    for pid in (A, C):
        for key in PLAIN:
            schema, table = key.split(".")
            if schema == "derived":
                continue
            with Database.connect(url, schema) as db:
                _row(db, table, pid, ruleset="GZQO")
        with Database.connect(url, "derived") as db:
            dv = f"def-{pid}"
            db.execute("INSERT INTO definition (def_version, score_id, version, sha256, body, loaded_at)"
                       " VALUES (?, 'egfr', 1, 's', '{}', 'now')", (dv,))  # fmt: skip
            rid = _row(db, "score_row", pid, def_version=dv, value=1.0)
            _row(db, "input_link", pid, row_id=rid) if _has_pid(db, "input_link") else _row(db, "input_link", "",
                                                                                              row_id=rid)  # fmt: skip
            first = _row(db, "conflict", pid, row_id=rid, documented_id=f"d1-{pid}")
            _row(db, "conflict", pid, row_id=rid, documented_id=f"d2-{pid}", carried_from=first)
    with Database.connect(url, "derived") as db:
        db.execute("INSERT INTO batch_run (snapshot, mapping_version, defs, started_at, failed_pids)"
                   " VALUES ('2026-11-01', 'm', 'd', 'now', ?)", (json.dumps(sorted([A, C])),))  # fmt: skip


def _has_pid(db: Any, table: str) -> bool:
    return bool(db.fetchval("SELECT count(*) FROM information_schema.columns WHERE table_schema = ? AND"
                            " table_name = ? AND column_name = 'pid'", (db.schema, table)))  # fmt: skip


def _count(url: str, key: str, pid: str) -> int:
    schema, table = key.split(".")
    with Database.connect(url, schema) as db:
        if table == "input_link" and not _has_pid(db, table):
            return int(db.fetchval("SELECT count(*) FROM input_link l JOIN score_row s ON s.id = l.row_id"
                                   " WHERE s.pid = ?", (pid,)))  # fmt: skip
        return int(db.fetchval(f"SELECT count(*) FROM {table} WHERE pid = ?", (pid,)))


def _env(url: str) -> Any:
    from datacore.optout_worker import WorkerEnv

    reg = OptOutRegister(url)
    return WorkerEnv(register=reg, audit=None, now=NOW)


def test_the_owed_tables_lose_the_opted_out_patient_and_keep_the_others(db_url: str) -> None:
    from datacore.optout_worker import clear_tables, verify_tables

    _stores(db_url)
    _fill(db_url)
    env = _env(db_url)
    before = verify_tables(frozenset({A}), env)
    assert set(before) == set(PLAIN) | {"derived.batch_run"} and all(before.values())
    out = clear_tables(frozenset({A}), env)
    assert A not in json.dumps(out) and sum(out.values()) >= len(PLAIN)  # counts only, never who
    assert verify_tables(frozenset({A}), env) == dict.fromkeys(before, 0)
    for key in PLAIN:
        assert _count(db_url, key, C) >= 1, key  # another patient's rows stay
    with Database.connect(db_url, "derived") as db:
        assert json.loads(db.fetchval("SELECT failed_pids FROM batch_run")) == [C]
    assert sum(clear_tables(frozenset({A}), env).values()) == 0  # idempotent
    env.register.close()


def test_a_box_without_a_store_skips_it(db_url: str) -> None:
    from datacore.optout_worker import clear_tables, verify_tables

    env = _env(db_url)  # no store made: nothing to clear, nothing left
    assert sum(clear_tables(frozenset({A}), env).values()) == 0
    assert not any(verify_tables(frozenset({A}), env).values())
    env.register.close()


def test_the_registry_no_longer_owes_the_cleared_tables() -> None:
    owed = {k for k, _card, _what in erasure.owed()}
    cleared = set(PLAIN) | {"derived.batch_run"}
    assert not cleared & owed
    assert all(erasure.entries()[k].clear == "owed_tables" for k in cleared)
    assert set(erasure.tables_of("owed_tables")) == cleared
    for key in ("site.pi_marks", "site.screening_no", "orch.candidate_events", "study.rc_record"):
        assert key in owed  # LIFE-005 is frozen: the screening log's tables wait


@pytest.mark.parametrize("key", ["site.pi_marks", "orch.candidate_events"])
def test_the_screening_logs_tables_are_not_touched(db_url: str, key: str) -> None:
    from datacore.optout_worker import clear_tables

    _stores(db_url)
    schema, table = key.split(".")
    with Database.connect(db_url, schema) as db:
        _row(db, table, A, ruleset="GZQO")
    env = _env(db_url)
    clear_tables(frozenset({A}), env)
    assert _count(db_url, key, A) == 1
    env.register.close()


# ---------------------------------------------------------------------------------------------- on a box's roles
@pytest.fixture(scope="module")
def roles_box() -> Any:
    """A cluster with the install's role script (D-378) and the stores made by the box's admin, as the install makes
    them; yields (admin URL, the orchestrator's URL): the worker runs as ``tb_orchestrator`` on a box."""
    import os
    import shutil
    import tempfile
    from pathlib import Path

    from tests.unit.test_db_roles import _as, _run_script
    from tools import pglocal

    if shutil.which("sh") is None:
        pytest.skip("no sh")
    try:
        pglocal.bindir()
    except RuntimeError as exc:
        pytest.skip(str(exc))
    base = Path(os.environ["TB_TEST_ROOT"]) if os.environ.get("TB_TEST_ROOT") else None
    if base is not None:
        base.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="tb-pgowed-", dir=base))
    root.chmod(0o755)
    admin = pglocal.ensure(root)
    try:
        _run_script(root)
        OptOutRegister(admin).close()
        _stores(admin)
        _fill(admin)
        yield admin, _as(admin, "tb_orchestrator")
    finally:
        pglocal.stop(root)
        shutil.rmtree(root, ignore_errors=True)


def test_the_clear_works_as_the_orchestrators_role(roles_box: tuple[str, str]) -> None:
    from datacore.optout_worker import clear_tables, verify_tables

    admin, orch = roles_box
    env = _env(orch)
    clear_tables(frozenset({A}), env)
    assert not any(verify_tables(frozenset({A}), env).values())
    for key in PLAIN:
        assert _count(admin, key, C) >= 1, key
    env.register.close()
