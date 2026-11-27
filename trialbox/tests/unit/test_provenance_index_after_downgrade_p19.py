"""P-19: the provenance index after a night, an update and a downgrade: detect and refuse (P19-DESIGN-3).

The walk's doctor said ``provenance_index FAIL, 108 row(s) missing`` and the count did not move across an update and a
downgrade: a downgrade puts the trial database back from the rollback point's dump, the provenance tables with it,
while the chain keeps every line drained since.

The index is never repaired in place. A restore or a downgrade empties it before the swap and sets the marker in the
audit directory (``PROVENANCE_STATE``) to rebuild-required: the update tool's one site, the backup restore, and the
drain itself on a journal resync or a failed index write. Until one rebuild from the chain completes, the search and
the drain's index writes are refused, naming ``trialbox provenance --rebuild``; the opt-out register is never coupled
to the index, and every row the rebuild writes goes through the register's trigger, so a consent change made at any
moment wins. Real drain, real tables, real ``pg_dump``, ``pg_restore`` and ``update.RESTORE_SH`` on the test cluster;
fixed times for the events; synthetic pseudonyms only.
"""

from __future__ import annotations

import itertools
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import psycopg
import pytest
from tb_common import provenance_index as idx
from tb_common.audit import AuditLog
from tb_common.audit_writer import Drain, _dsn
from tb_common.optout import REGISTRY_ACTOR, OptOutRegister

from tests.unit.test_provenance_index import REGISTER, register
from tools import pglocal
from tools.trialbox import update as up

TZ = "Asia/Taipei"
PID_A = "0ca5381cfa6bdf1c22961d65579f93b3"
PID_B = "1afe78d42518132b113c5858cedcbb54"
PID_C = "7f3e9a1c5b2d48e6a0c4f81b39d76e25"
OPT_OUT = "console.opt_out"  # the console's journal event of an opt-out (services/console/team.py)
_N = itertools.count()
#: the journal's columns as the drain reads them (``audit_writer.JOURNAL_SQL`` without its roles and grants)
JOURNAL = """CREATE SCHEMA audit;
CREATE TABLE audit.journal (seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT clock_timestamp(), db_role text NOT NULL, event text NOT NULL, ts text NOT NULL,
  fields jsonb NOT NULL)"""


@pytest.fixture
def box(pg_cluster_url: str) -> Iterator[str]:
    """A database of this test's own: the journal, the opt-out register and (run by each test) the provenance index,
    as the role script makes them."""
    name = f"tb_p19_{os.getpid()}_{next(_N)}"
    with psycopg.connect(_dsn(pg_cluster_url), autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    dsn = psycopg.conninfo.make_conninfo(_dsn(pg_cluster_url), dbname=name)
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(JOURNAL)
        c.execute(REGISTER)
    try:
        yield dsn
    finally:
        with psycopg.connect(_dsn(pg_cluster_url), autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            admin.execute(f'DROP DATABASE IF EXISTS "{name}_tbrb" WITH (FORCE)')
            admin.execute(f'DROP DATABASE IF EXISTS "{name}_tbold" WITH (FORCE)')


def _fields(n: int, call: str, pid: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The fields of one night's model call and of the verdict it was used for."""
    call_f = {"model": "m-judge", "prompt_version": "judge_v4", "input_sha": "i", "output_sha": "o",
              "detail": {"call_id": call, "build_sha": f"b{n}", "prompt_sha": "p" * 64}}  # fmt: skip
    ref = {"ruleset": "GZQO", "version": "1.0.0", "job": f"J{n}", "pid": pid, "crit": "N-INC-01"}
    return call_f, {"detail": {"record_kind": "verdict", "record_ref": ref, "calls": [call]}}


def _put(dsn: str, n: int, event: str, fields: dict[str, Any]) -> None:
    """One row a service hands to the journal, at 02:00 of day ``n`` (the chain's day file ``2026-11-<n>``)."""
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("INSERT INTO audit.journal (db_role, event, ts, fields) VALUES ('tb_orchestrator', %s, %s, %s)",
                  (event, f"2026-11-{n:02d}T02:00:00+08:00", json.dumps(fields)))  # fmt: skip


def _send(dsn: str, n: int, call: str, pid: str) -> None:
    """One night's model call and the verdict it was used for, as a service hands them to the journal."""
    call_f, use_f = _fields(n, call, pid)
    _put(dsn, n, "llm.call", call_f)
    _put(dsn, n, "ai.used", use_f)


def _drain(dsn: str, chain: Path) -> int:
    """The audit-writer service started (as after an update or a downgrade) and run until the journal is empty."""
    d = Drain("postgresql://x@h/db", chain, TZ, connect=lambda: psycopg.connect(dsn, autocommit=True))
    d.open()
    try:
        return d.run(once=True, alive=None)
    finally:
        d.con.close()


def _check(dsn: str, chain: Path) -> idx.Diff:
    with psycopg.connect(dsn, autocommit=True) as c:
        return idx.check(c, chain)


def _rebuild(dsn: str, chain: Path) -> tuple[int, int]:
    """``trialbox provenance --rebuild``: the index written again from the chain, then the marker says verified."""
    with psycopg.connect(dsn, autocommit=True) as c:
        return idx.rebuild(c, chain)


def _ready(dsn: str, chain: Path) -> None:
    """The role script's index, and the one rebuild an install runs (an empty chain: the marker says verified)."""
    chain.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _rebuild(dsn, chain)


def _clean(chain: Path) -> bool:
    return idx.read_marker(chain).clean


def _pg(tool: str, *args: str) -> None:
    subprocess.run([str(pglocal.bindir() / tool), *args], check=True, capture_output=True, timeout=120)


def _dump(dsn: str, tmp_path: Path) -> Path:
    dump = tmp_path / "rollback.dump"
    _pg("pg_dump", "-Fc", "-f", str(dump), dsn)
    return dump


def _opt_out(dsn: str, n: int, pid: str) -> int:
    """The opt-out desk's no: the register's row, the opt-out worker's :func:`idx.erase`, the journal's
    ``console.opt_out``. The use rows erased."""
    fields = {"actor": "console:office1", "detail": {"pid": pid, "action": "opt_out", "reason": "", "source": "paper",
                                                     "removed_from": "screening, candidate lists, exports"}}  # fmt: skip
    at = f"2026-11-{n:02d}T09:00:00+08:00"
    with psycopg.connect(dsn, autocommit=True) as c:
        register(c, pid, "opt_out", at)
        gone = idx.erase(c, [pid]) if idx.installed(c) else 0
        c.execute("INSERT INTO audit.journal (db_role, event, ts, fields) VALUES ('tb_console', %s, %s, %s)",
                  (OPT_OUT, at, json.dumps(fields)))  # fmt: skip
    return gone


def _restore(dsn: str, dump: Path) -> None:
    """A hand restore (not the update tool): the database back to the rollback point, then the live register's rows
    applied again. Nothing sets the marker: the drain's resync is the backstop."""
    cols = "id, pid, action, source, note, by, at"
    with psycopg.connect(dsn, autocommit=True) as c:
        live = c.execute(f"SELECT {cols} FROM optout.optout_events").fetchall()
        c.execute("DROP SCHEMA audit, provenance, optout CASCADE")
    _pg("pg_restore", "-d", dsn, str(dump))
    with psycopg.connect(dsn, autocommit=True) as c:
        c.cursor().executemany(f"INSERT INTO optout.optout_events ({cols}) OVERRIDING SYSTEM VALUE "
                               "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING", live)  # fmt: skip


def _val(c: Any, sql: str, args: tuple[Any, ...] = ()) -> Any:
    row = c.execute(sql, args).fetchone()
    assert row is not None
    return row[0]


def _calls(dsn: str) -> list[str]:
    with psycopg.connect(dsn, autocommit=True) as c:
        return sorted(str(r[0]) for r in c.execute("SELECT call_id FROM provenance.model_calls"))


def _uses(dsn: str, pid: str | None = None) -> list[str]:
    """The calls of the index's use rows (of one patient, or all), sorted."""
    with psycopg.connect(dsn, autocommit=True) as c:
        rows = c.execute("SELECT call_id FROM provenance.model_uses WHERE %(p)s::text IS NULL OR pid = %(p)s",
                         {"p": pid}).fetchall()  # fmt: skip
    return sorted(str(r[0]) for r in rows)


def _chain_calls(chain: Path) -> list[str]:
    return [str(r["detail"]["call_id"]) for r in idx.chain_records(chain) if r.get("event") == "llm.call"]


def _url(dsn: str) -> str:
    """The test's database as a ``TB_DB_URL`` (what ``OptOutRegister`` and ``trialbox provenance`` take)."""
    d = psycopg.conninfo.conninfo_to_dict(dsn)
    who, db = quote(str(d.pop("user")), safe=""), d.pop("dbname")
    return f"postgresql://{who}@/{db}?" + urlencode({k: str(v) for k, v in d.items()})


def _register(dsn: str) -> OptOutRegister:
    """The opt-out register as the console and the registry's worker open it (``tb_common.optout``: its own
    migration, in place of the fixture's hand-made table)."""
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("DROP SCHEMA optout CASCADE")
    return OptOutRegister(_url(dsn))


def _rollback(dsn: str, dump: Path, tmp_path: Path, *, ok: bool = True) -> subprocess.CompletedProcess[str]:
    """The update's rollback of the trial database as ``ComposeBox.restore_databases`` runs it in the db container:
    ``update.RESTORE_SH`` under dash, the dump on stdin. Nothing of the live register is kept by this helper."""
    d = psycopg.conninfo.conninfo_to_dict(dsn)
    pgdata = tmp_path / "pgdata"  # the script's folder is under PGDATA, as on the db volume
    pgdata.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(PGDATA=str(pgdata), POSTGRES_USER=str(d["user"]), PATH=f"{pglocal.bindir()}:{env.get('PATH', '')}")
    for key, var in (("host", "PGHOST"), ("port", "PGPORT"), ("password", "PGPASSWORD")):
        if d.get(key):
            env[var] = str(d[key])
    with dump.open("rb") as fh:
        r = subprocess.run([shutil.which("dash") or "sh", "-c", up.RESTORE_SH, "tb-restore", str(d["user"]),
                            str(d["dbname"]), up.RESET_SQL], stdin=fh, env=env, capture_output=True,
                           check=False)  # fmt: skip
    out = subprocess.CompletedProcess(r.args, r.returncode, r.stdout.decode(), r.stderr.decode())
    if ok:
        assert r.returncode == 0, out.stderr[-1200:]
    return out


def _events_of(dsn: str, pid: str) -> list[tuple[str, str]]:
    with psycopg.connect(dsn, autocommit=True) as c:
        return [(str(a), str(b)) for a, b in c.execute(
            "SELECT action, by FROM optout.optout_events WHERE pid = %s ORDER BY id", (pid,)).fetchall()]  # fmt: skip


def _slipped(dsn: str, pid: str) -> None:
    """A use row of ``pid`` that the trigger never saw (what ``pg_restore`` loads before the trigger exists)."""
    with psycopg.connect(dsn, autocommit=True) as c, c.transaction():
        c.execute("ALTER TABLE provenance.model_uses DISABLE TRIGGER model_uses_withhold")
        c.execute("INSERT INTO provenance.model_uses (rec_hash, call_id, event, record_kind, record_ref, pid, at) "
                  "VALUES ('h9', 'c9', 'used', 'verdict', '{}', %s, '2026-11-20T02:00:00+08:00')", (pid,))  # fmt: skip
        c.execute("ALTER TABLE provenance.model_uses ENABLE TRIGGER model_uses_withhold")


def _flaky_add(monkeypatch: pytest.MonkeyPatch, which: int = 1) -> None:
    """The ``which``-th line written fails once: the database went away for a moment."""
    real, writes = idx.add, itertools.count()

    def flaky(con: Any, rec: dict[str, Any], *a: Any, **k: Any) -> int:
        if next(writes) == which:
            raise psycopg.OperationalError("synthetic: the connection dropped")
        return real(con, rec, *a, **k)

    monkeypatch.setattr(idx, "add", flaky)


# --- the drain, the hand restore and the resync (the backstop): converted from the catch-up's tests


def test_the_index_equals_the_chain_after_a_night_an_update_and_a_downgrade(box: str, tmp_path: Path) -> None:
    chain = tmp_path / "audit"
    _ready(box, chain)
    _send(box, 20, "c1", PID_A)  # a night
    assert _drain(box, chain) == 2
    assert _check(box, chain).ok
    dump = _dump(box, tmp_path)  # the update: its rollback point, then the box runs on the new release
    _send(box, 21, "c2", PID_B)
    assert _drain(box, chain) == 2
    assert _check(box, chain).ok
    _restore(box, dump)  # the downgrade by hand: the database back to the rollback point
    _drain(box, chain)  # the drain starts again on the restored database (it records the resync)
    assert not _clean(chain)
    _rebuild(box, chain)
    diff = _check(box, chain)
    assert diff.ok, diff.missing
    assert _calls(box) == ["c1", "c2"]


def test_a_hand_restore_is_caught_by_the_resync(box: str, tmp_path: Path) -> None:
    """Backstop: a ``pg_restore`` without the update tool sets no marker; the drain's start sees the journal is not
    the chain's, records ``audit.journal_resync`` and requires the rebuild."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    dump = _dump(box, tmp_path)
    _send(box, 21, "c2", PID_A)
    _drain(box, chain)
    _restore(box, dump)
    assert _clean(chain)
    _drain(box, chain)
    assert any(r.get("event") == "audit.journal_resync" for r in idx.chain_records(chain))
    m = idx.read_marker(chain)
    assert (m.clean, m.reason) == (False, "journal resync")


def test_tables_made_after_the_drain_started_are_written_without_a_restart(box: str, tmp_path: Path) -> None:
    chain = tmp_path / "audit"
    chain.mkdir()
    d = Drain("postgresql://x@h/db", chain, TZ, connect=lambda: psycopg.connect(box, autocommit=True))
    d.open()
    try:
        assert not d.index
        _ready(box, chain)  # the role script and the install's rebuild, run after the drain was up
        _send(box, 22, "c3", PID_A)
        assert d.step() == 2
        assert d.index
        assert _calls(box) == ["c3"]
    finally:
        d.con.close()


def test_a_use_row_taken_out_at_an_opt_out_is_not_written_back_at_a_start(box: str, tmp_path: Path) -> None:
    chain = tmp_path / "audit"
    _ready(box, chain)
    _send(box, 20, "c1", PID_A)
    _send(box, 21, "c2", PID_B)
    _drain(box, chain)
    assert _opt_out(box, 22, PID_B) == 1  # the newest use row of the index
    _drain(box, chain)  # started again on the same database: nothing is written back
    assert _uses(box, PID_B) == []
    assert _check(box, chain).ok


def test_an_opt_out_recorded_after_the_dump_stays_out_after_the_downgrade(box: str, tmp_path: Path) -> None:
    """P19-R1 / F1 (High): the dump's register is older than the opt-out; the live register, applied again after the
    restore, keeps B's row out of the rebuild."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    dump = _dump(box, tmp_path)
    _send(box, 21, "c2", PID_B)  # B's verdict, then B says no and the use row goes
    _drain(box, chain)
    assert _opt_out(box, 22, PID_B) == 1
    _drain(box, chain)
    _restore(box, dump)
    _drain(box, chain)
    _rebuild(box, chain)
    assert _uses(box, PID_B) == []
    assert _check(box, chain).ok
    assert _calls(box) == ["c1", "c2"]  # the call rows name no patient: they are written back


def test_a_row_journaled_before_the_dump_and_drained_after_it_is_written_back(box: str, tmp_path: Path) -> None:
    """P19-R2 / F2: the journal's newest row is not the index's newest line (a backlog at the dump, and a row a
    service journals after the restore and before the drain starts)."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    _send(box, 21, "c2", PID_A)  # in the journal, not yet drained, when the dump is taken
    dump = _dump(box, tmp_path)
    _drain(box, chain)
    _send(box, 22, "c3", PID_B)
    _drain(box, chain)
    _restore(box, dump)
    _send(box, 23, "c4", PID_B)  # another service is up before the drain
    _drain(box, chain)
    _rebuild(box, chain)
    diff = _check(box, chain)
    assert diff.ok, diff.missing
    assert _calls(box) == ["c1", "c2", "c3", "c4"]


def test_a_dump_taken_before_the_first_journal_row_is_rebuilt(box: str, tmp_path: Path) -> None:
    """P19-R3 / F2: the restored journal is empty (no newest row at all); the rebuild writes every line since."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    dump = _dump(box, tmp_path)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    _restore(box, dump)
    _drain(box, chain)
    assert not _clean(chain)
    _rebuild(box, chain)
    diff = _check(box, chain)
    assert diff.ok, diff.missing
    assert _calls(box) == ["c1"]


def test_a_rebuild_that_fails_part_way_is_run_again_and_writes_each_row_once(
    box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P19-R4 / F3: a failure after the first day's write leaves the marker required with that day done; the next
    rebuild writes the rest, each row once."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    dump = _dump(box, tmp_path)
    _send(box, 21, "c2", PID_B)
    _send(box, 22, "c3", PID_A)
    _drain(box, chain)
    _restore(box, dump)
    _drain(box, chain)
    _flaky_add(monkeypatch, which=2)  # the first line of the second day
    with pytest.raises(psycopg.OperationalError):
        _rebuild(box, chain)
    m = idx.read_marker(chain)
    assert (m.clean, m.done_through) == (False, "2026-11-20.jsonl")
    assert _calls(box) == ["c1"]
    _send(box, 23, "c4", PID_B)
    _drain(box, chain)
    assert "c4" not in _calls(box)  # refused while required
    _rebuild(box, chain)
    diff = _check(box, chain)
    assert diff.ok, diff.missing
    assert _calls(box) == ["c1", "c2", "c3", "c4"]
    assert _uses(box) == ["c1", "c2", "c3", "c4"]


def test_a_line_whose_journal_time_cannot_be_read_is_not_passed_over(box: str, tmp_path: Path) -> None:
    """P19-R5 (D7): the rebuild does not judge a line by its journal time, so a naive one is written back. The edit
    must find the line it changes (review P19-D7: it could pass without its premise)."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    dump = _dump(box, tmp_path)
    _send(box, 21, "c2", PID_B)
    _drain(box, chain)
    day = sorted(chain.glob("*.jsonl"))[-1]
    lines, edited = day.read_text(encoding="utf-8").splitlines(), 0
    for i, line in enumerate(lines):
        rec = json.loads(line)
        if rec.get("event") == "llm.call" and (rec.get("detail") or {}).get("call_id") == "c2":
            rec["journal"]["at"] = "2026-11-21 02:00:00"  # no zone
            lines[i] = json.dumps(rec, sort_keys=True, ensure_ascii=False)
            edited += 1
    assert edited == 1
    day.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _restore(box, dump)
    _drain(box, chain)
    _rebuild(box, chain)
    assert _calls(box) == ["c1", "c2"]


def test_index_not_installed_is_said_once_not_at_every_batch(
    box: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """F5: the drain asks before each batch while the tables are missing; it says so at its start only."""
    caplog.set_level("INFO", logger="tb.audit_writer")
    d = Drain("postgresql://x@h/db", tmp_path / "audit", TZ, connect=lambda: psycopg.connect(box, autocommit=True))
    d.open()
    try:
        for n in (20, 21):
            _send(box, n, f"c{n}", PID_A)
            assert d.step() == 2
    finally:
        d.con.close()
    assert sum("provenance index not installed" in r.getMessage() for r in caplog.records) == 1


def test_a_registry_refusal_in_the_register_is_withheld_at_the_rebuild(
    box: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """D1: the opt-out worker's copy of a registry refusal is a register row; its audit event holds counts only. The
    rebuild withholds B's use row with no pseudonym written anywhere new."""
    caplog.set_level("DEBUG")
    chain = tmp_path / "audit"
    _ready(box, chain)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    dump = _dump(box, tmp_path)
    _send(box, 21, "c2", PID_B)
    _drain(box, chain)
    with psycopg.connect(box, autocommit=True) as c:  # the worker's copy; no console.opt_out anywhere
        register(c, PID_B, "opt_out", "2026-11-22T03:00:00+08:00", source="emr", by=REGISTRY_ACTOR)
    _restore(box, dump)
    _drain(box, chain)
    _rebuild(box, chain)
    assert _uses(box, PID_B) == []
    assert _check(box, chain).ok
    assert _calls(box) == ["c1", "c2"]
    assert not any(r.get("event") == OPT_OUT for r in idx.chain_records(chain))
    assert PID_B not in (chain / idx.STATE).read_text(encoding="utf-8")
    assert PID_B not in caplog.text


def test_a_use_row_in_the_dump_is_not_served_after_the_restore(box: str, tmp_path: Path) -> None:
    """D2: B's use row is in the dump and B opts out after it: a hand restore puts the row back; the drain's resync
    refuses the search until the rebuild, which leaves it out."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    _send(box, 20, "c1", PID_A)
    _send(box, 21, "c2", PID_B)
    _drain(box, chain)
    dump = _dump(box, tmp_path)
    assert _opt_out(box, 22, PID_B) == 1
    _drain(box, chain)
    _restore(box, dump)
    assert _uses(box, PID_B) == ["c2"]  # back from the dump, before the drain starts
    _drain(box, chain)
    with psycopg.connect(box, autocommit=True) as c, pytest.raises(idx.ProvenanceRebuildRequired):
        idx.search(c, directory=chain, model="m-judge")
    _rebuild(box, chain)
    assert _uses(box, PID_B) == []
    assert _clean(chain)
    assert _check(box, chain).ok


def test_a_restore_with_a_matching_cursor_is_still_rebuilt(box: str, tmp_path: Path) -> None:
    """D3: c2 is in the journal, undrained, at the dump, and drained after it: the restored journal holds the chain's
    last row exactly, so there is no resync; the update tool's marker requires the rebuild all the same."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    _send(box, 21, "c2", PID_A)
    dump = _dump(box, tmp_path)
    _drain(box, chain)
    up.mark_rebuild_required(chain)
    _rollback(box, dump, tmp_path)
    _drain(box, chain)  # no new event in between
    assert not any(r.get("event") == "audit.journal_resync" for r in idx.chain_records(chain))
    assert (_calls(box), _clean(chain)) == ([], False)
    _rebuild(box, chain)
    assert _calls(box) == ["c1", "c2"]
    assert _uses(box) == ["c1", "c2"]
    assert _check(box, chain).ok


def test_a_partial_rebuild_and_a_batch_are_finished_by_the_next_rebuild(
    box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D4: the rebuild fails part way and the drain drains a new row before it is run again: the row is not indexed
    while the marker says required (the drain's start, still on the restored journal, requires it again), and the
    next rebuild (a fresh process) writes every row."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    dump = _dump(box, tmp_path)
    _send(box, 21, "c2", PID_B)
    _send(box, 22, "c3", PID_A)
    _drain(box, chain)
    _restore(box, dump)
    _flaky_add(monkeypatch, which=0)
    _drain(box, chain)
    with pytest.raises(psycopg.OperationalError):
        _rebuild(box, chain)
    monkeypatch.undo()
    _send(box, 23, "c4", PID_B)
    assert _drain(box, chain) == 2
    assert "c4" not in _calls(box)
    between = idx.read_marker(chain)
    assert (between.clean, between.reason, between.attempts) == (False, "journal resync", 1)
    _rebuild(box, chain)
    assert _clean(chain)
    assert _calls(box) == ["c1", "c2", "c3", "c4"]
    assert _uses(box) == ["c1", "c2", "c3", "c4"]


def test_a_failed_probe_at_the_resync_requires_the_rebuild(
    box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """D5: the probe for the tables fails once at the start: the resync still requires the rebuild, the log says the
    index could not be read (not that it is absent), and the rebuild writes every row once the probe answers."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    dump = _dump(box, tmp_path)
    _send(box, 21, "c2", PID_A)
    _drain(box, chain)
    _restore(box, dump)
    real, once = idx.installed, iter([True])

    def probe(con: Any) -> bool:
        if next(once, False):
            raise psycopg.OperationalError("synthetic: the probe timed out")
        return real(con)

    monkeypatch.setattr(idx, "installed", probe)
    caplog.set_level("INFO", logger="tb.audit_writer")
    d = Drain("postgresql://x@h/db", chain, TZ, connect=lambda: psycopg.connect(box, autocommit=True))
    d.open()
    try:
        assert idx.read_marker(chain).reason == "journal resync"
        assert "could not be read" in caplog.text and "not installed" not in caplog.text
        _send(box, 22, "c3", PID_A)
        assert d.step() == 2
        assert d.index and "c3" not in _calls(box)
    finally:
        d.con.close()
    _rebuild(box, chain)
    assert _calls(box) == ["c1", "c2", "c3"]
    assert _check(box, chain).ok


def test_a_lift_releases_only_rows_after_it(box: str, tmp_path: Path) -> None:
    """D6: A's use before the opt-out and the one while it held stay out after the lift; the one after it is
    written, live and after the downgrade's rebuild, and the check expects exactly that."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    dump = _dump(box, tmp_path)  # before all of it
    _send(box, 20, "c1", PID_A)  # u1
    _drain(box, chain)
    assert _opt_out(box, 21, PID_A) == 1
    _send(box, 22, "c2", PID_A)  # u2, while A is out
    _drain(box, chain)
    with psycopg.connect(box, autocommit=True) as c:
        register(c, PID_A, "lift", "2026-11-23T09:00:00+08:00")
    _send(box, 24, "c3", PID_A)  # u3, after the lift
    _drain(box, chain)
    assert _uses(box, PID_A) == ["c3"]
    _restore(box, dump)
    _drain(box, chain)
    _rebuild(box, chain)
    assert _uses(box, PID_A) == ["c3"]
    assert _check(box, chain).ok
    assert _calls(box) == ["c1", "c2", "c3"]


def test_the_rebuild_writes_a_line_with_a_naive_journal_time(box: str, tmp_path: Path) -> None:
    """D7: the record itself carries the naive journal time (its hash is valid), and the rebuild writes its rows."""
    log = AuditLog(tmp_path / "audit", TZ)
    for n, call, at in ((20, "c1", "2026-11-20T02:00:00+08:00"), (21, "c2", "2026-11-21 02:00:00")):
        call_f, use_f = _fields(n, call, PID_A)
        ts = datetime.fromisoformat(f"2026-11-{n:02d}T02:00:00+08:00")
        log.append("llm.call", ts=ts, journal={"seq": 2 * n, "at": at}, **call_f)
        log.append("ai.used", ts=ts, journal={"seq": 2 * n + 1, "at": at}, **use_f)
    (c2,) = [r for r in idx.chain_records(log.directory) if (r.get("detail") or {}).get("call_id") == "c2"]
    assert c2["journal"]["at"] == "2026-11-21 02:00:00"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
        assert idx.rebuild(c, log.directory) == (2, 2)
    assert _calls(box) == ["c1", "c2"]
    assert _uses(box) == ["c1", "c2"]


def test_an_opt_out_between_the_restore_and_the_rebuild_is_withheld(box: str, tmp_path: Path) -> None:
    """N1 (the restore and the rebuild race): the console is up first and B opts out before the rebuild; its insert
    of B's line reads the live register and is withheld."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    dump = _dump(box, tmp_path)
    _send(box, 21, "c2", PID_B)
    _drain(box, chain)
    _restore(box, dump)
    assert _opt_out(box, 22, PID_B) == 0  # nothing of B's in the restored index yet
    _drain(box, chain)
    _rebuild(box, chain)
    assert _uses(box, PID_B) == []
    assert "c2" in _calls(box)
    assert _check(box, chain).ok


def test_a_line_with_two_calls_is_written_whole_or_not_at_all(
    box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N2: a verdict that used two calls gives two use rows; a failure between them leaves neither, so a line hash in
    the index means the whole line, and a retry writes both."""
    log = AuditLog(tmp_path / "audit", TZ)
    ts = datetime.fromisoformat("2026-11-21T02:00:00+08:00")
    calls = [log.append("llm.call", ts=ts, **_fields(21, c, PID_A)[0]) for c in ("c2", "c3")]
    ref = {"ruleset": "GZQO", "version": "1.0.0", "job": "J21", "pid": PID_A, "crit": "N-INC-01"}
    used = log.append("ai.used", ts=ts, detail={"record_kind": "verdict", "record_ref": ref, "calls": ["c2", "c3"]})
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
        for rec in calls:
            idx.add(c, rec)
        real, uses = c.execute, itertools.count()

        def second_fails(sql: Any, *a: Any, **k: Any) -> Any:
            if "INSERT INTO provenance.model_uses" in str(sql) and next(uses) == 1:
                raise psycopg.OperationalError("synthetic: the connection dropped")
            return real(sql, *a, **k)

        monkeypatch.setattr(c, "execute", second_fails)
        with pytest.raises(psycopg.OperationalError):
            idx.add(c, used)
        monkeypatch.undo()
        held = {str(r[0]) for t in idx.TABLES for r in c.execute(idx._KEYS[t]).fetchall()}
        assert used["hash"] not in held
        assert idx.add(c, used) == 2
        assert idx.check(c, log.directory).ok
    assert _uses(box) == ["c2", "c3"]


def test_a_line_of_which_one_row_is_missing_is_completed(box: str, tmp_path: Path) -> None:
    """P19-N2: a line written half by the old autocommit loop (one of its two use rows) is completed by the rebuild,
    which writes rows, not line hashes."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    call_f, use_f = _fields(20, "c2", PID_A)
    _put(box, 20, "llm.call", call_f)
    _put(box, 20, "llm.call", {**call_f, "detail": {**call_f["detail"], "call_id": "c3"}})
    _put(box, 20, "ai.used", {"detail": {**use_f["detail"], "calls": ["c2", "c3"]}})
    _drain(box, chain)
    with psycopg.connect(box, autocommit=True) as c:
        c.execute("DELETE FROM provenance.model_uses WHERE call_id = 'c3'")
        assert idx.rebuild(c, chain) == (2, 2)
        assert idx.check(c, chain).ok
    assert _uses(box) == ["c2", "c3"]


def test_the_doctor_check_agrees_with_the_writer(box: str, tmp_path: Path) -> None:
    """§1: A is out, B's opt-out was lifted, C never opted out: what the trigger wrote is what the check expects,
    before and after a rebuild."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    with psycopg.connect(box, autocommit=True) as c:
        register(c, PID_A, "opt_out", "2026-11-19T09:00:00+08:00")
        register(c, PID_B, "opt_out", "2026-11-19T09:00:00+08:00")
        register(c, PID_B, "lift", "2026-11-21T09:00:00+08:00")
    _send(box, 20, "c1", PID_A)
    _send(box, 20, "c2", PID_B)  # before B's lift
    _send(box, 22, "c3", PID_B)  # after it
    _send(box, 22, "c4", PID_C)
    _drain(box, chain)
    assert (_uses(box, PID_A), _uses(box, PID_B), _uses(box, PID_C)) == ([], ["c3"], ["c4"])
    with psycopg.connect(box, autocommit=True) as c:
        assert idx.check(c, chain).ok
        idx.rebuild(c, chain)
        assert idx.check(c, chain).ok
    assert (_uses(box, PID_A), _uses(box, PID_B), _uses(box, PID_C)) == ([], ["c3"], ["c4"])


def test_an_old_role_script_writes_no_unfiltered_index(
    box: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """§6.3: the tables without the register's trigger (a box on the old role script) are not the index: the drain
    writes the chain alone and says so."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
        c.execute("DROP TRIGGER model_uses_withhold ON provenance.model_uses")
        assert not idx.installed(c)
    caplog.set_level("INFO", logger="tb.audit_writer")
    _send(box, 20, "c1", PID_A)
    assert _drain(box, chain) == 2
    assert _calls(box) == [] and _uses(box) == []
    assert [r["event"] for r in idx.chain_records(chain) if r.get("event") in ("llm.call", "ai.used")] == [
        "llm.call",
        "ai.used",
    ]
    assert "provenance index not installed" in caplog.text


@pytest.mark.parametrize("how", ["disabled", "elsewhere"])
def test_a_trigger_that_does_not_filter_the_index_is_not_installed(box: str, how: str) -> None:
    """P19-X4 (High) / F5: a disabled trigger (an interrupted data restore leaves one) or one of the same name on
    another table is no filter: the drain must not write the index."""
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
        assert idx.installed(c)
        if how == "disabled":
            c.execute("ALTER TABLE provenance.model_uses DISABLE TRIGGER model_uses_withhold")
        else:
            c.execute("DROP TRIGGER model_uses_withhold ON provenance.model_uses")
            c.execute("CREATE TABLE provenance.elsewhere (pid text, at timestamptz)")
            c.execute("CREATE TRIGGER model_uses_withhold BEFORE INSERT ON provenance.elsewhere FOR EACH ROW "
                      "EXECUTE FUNCTION provenance.withhold()")  # fmt: skip
        assert not idx.installed(c)


# --- P19-DESIGN-3 §7 (reviews 1584 codex Y1 to Y10, D7; opus G1 to G8): the update tool's restore


@pytest.mark.parametrize("dump", ["post_p19_dump", "tables_only_dump"])
def test_a_rollback_leaves_the_index_empty_and_required(box: str, tmp_path: Path, dump: str) -> None:
    """Y1, G1, D2 (High): B's use row is in the dump and B opts out after it. The rollback point was made by this
    release, or by the release before P-19 (the tables, no functions, no trigger). The update's own rollback empties
    the index before the swap, whatever made the dump, and says so; the marker requires the rebuild."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    reg = _register(box)
    try:
        _send(box, 20, "c1", PID_A)
        _send(box, 21, "c2", PID_B)
        _drain(box, chain)
        assert _uses(box, PID_B) == ["c2"]
        if dump == "tables_only_dump":
            with psycopg.connect(box, autocommit=True) as c:
                c.execute("DROP TRIGGER model_uses_withhold ON provenance.model_uses")
                c.execute("DROP FUNCTION provenance.withhold(), provenance.withheld(text, timestamptz)")
        point = _dump(box, tmp_path)
        if dump == "tables_only_dump":  # the update installs this release's index
            with psycopg.connect(box, autocommit=True) as c:
                c.execute(idx.INDEX_SQL)
        assert reg.add(PID_B, "paper", "", "console:office1", "2026-11-22T09:00:00+08:00")
    finally:
        reg.close()
    up.mark_rebuild_required(chain)  # ComposeBox.rollback: after stop, before anything goes back
    r = _rollback(box, point, tmp_path)
    assert (_uses(box), _calls(box)) == ([], [])  # before any drain
    m = idx.read_marker(chain)
    assert (m.clean, m.reason) == (False, "update rollback")
    assert up.restore_said(r.stdout) == {"register_events_kept": 1, "provenance_index": "emptied; rebuild required"}
    assert _events_of(box, PID_B) == [("opt_out", "console:office1")]
    _drain(box, chain)
    assert _uses(box) == []  # nothing is written while required
    if dump == "tables_only_dump":  # the release before P-19 serves an empty index, never the dump's rows
        with pytest.raises(idx.RebuildRefused, match="not installed"):
            _rebuild(box, chain)
        assert _uses(box) == []
        return
    _rebuild(box, chain)
    assert (_uses(box, PID_B), _uses(box, PID_A), _calls(box)) == ([], ["c1"], ["c1", "c2"])
    assert _check(box, chain).ok and _clean(chain)


def test_a_rollback_copies_the_live_register_whole_with_its_ids(box: str, tmp_path: Path) -> None:
    """Y2 (High): the dump holds B's opt-out; then the same actor lifts it and opts B out again at the same stored
    time. The rollback, run twice, keeps the live register's ids, so the authority's tie order (at, id) still ends
    on the opt-out; a new event is inserted after them (the sequence moved on)."""
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    reg = _register(box)
    at = "2026-11-21T09:00:00+08:00"
    try:
        assert reg.add(PID_B, "paper", "", "console:office1", at)
        point = _dump(box, tmp_path)
        assert reg.lift(PID_B, "", "console:office1", at)
        assert reg.add(PID_B, "paper", "", "console:office1", at)
    finally:
        reg.close()
    ids = "SELECT id, pid, action, by, at FROM optout.optout_events ORDER BY id"
    with psycopg.connect(box, autocommit=True) as c:
        live = c.execute(ids).fetchall()
    _rollback(box, point, tmp_path)
    _rollback(box, point, tmp_path)
    with psycopg.connect(box, autocommit=True) as c:
        assert c.execute(ids).fetchall() == live
        assert _val(c, "SELECT provenance.withheld(%s, now())", (PID_B,)) is True
    reg = OptOutRegister(_url(box))
    try:
        assert reg.add(PID_C, "paper", "", "console:office1", "2026-11-22T09:00:00+08:00")
    finally:
        reg.close()
    with psycopg.connect(box, autocommit=True) as c:
        assert _val(c, "SELECT max(id) FROM optout.optout_events WHERE pid = %s", (PID_C,)) > max(r[0] for r in live)


def test_a_rebuild_refuses_a_second_register_schema(box: str, tmp_path: Path) -> None:
    """Y3, G6 (High): the index's filter reads ``optout.optout_events``; a register of the same name elsewhere (a
    prefixed one) is refused by name, the marker untouched and the search still refused."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    idx.require_rebuild(chain, "update rollback")
    before = (chain / idx.STATE).read_bytes()
    with psycopg.connect(box, autocommit=True) as c:
        c.execute("CREATE SCHEMA x_optout")
        c.execute("CREATE TABLE x_optout.optout_events (LIKE optout.optout_events)")
        c.execute("INSERT INTO x_optout.optout_events (id, pid, action, by, at) VALUES (1, %s, 'opt_out', "
                  "'console:office1', '2026-11-21T09:00:00+08:00')", (PID_B,))  # fmt: skip
        with pytest.raises(idx.RebuildRefused, match=r"x_optout\.optout_events"):
            idx.rebuild(c, chain)
        assert (chain / idx.STATE).read_bytes() == before
        with pytest.raises(idx.ProvenanceRebuildRequired):
            idx.search(c, directory=chain, model="m-judge")


@pytest.mark.parametrize("how", ["no_folder", "not_writable"])
def test_a_marker_that_cannot_be_written_stops_the_rollback_before_the_restore(tmp_path: Path, how: str) -> None:
    """Y4 (High): the marker cannot be written (no audit folder where the host looks; a folder that will not take
    it): ``ComposeBox.rollback`` raises ``UpdateFailed`` after stopping the services and before any image, model or
    database is touched, so the live database and its rows stay as they are and no ``_tbrb`` database is made."""
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    audit = tmp_path / "audit-data"
    if how == "not_writable":  # a directory where the marker goes: no writer, root included, can replace it
        (audit / idx.STATE).mkdir(parents=True)
    (deploy / ".env").write_text(f"TB_AUDIT_HOST_DIR={audit}\n", encoding="utf-8")
    ran: list[list[str]] = []

    def run(argv: Any, **_k: Any) -> str:
        ran.append(list(argv))
        return ""

    with pytest.raises(up.UpdateFailed, match="provenance marker could not be written"):
        up.ComposeBox(deploy, run=run).rollback(None, tmp_path, None)  # type: ignore[arg-type]
    assert len(ran) == 1 and "stop" in ran[0]
    assert not any("tb-restore" in a for argv in ran for a in argv)


def test_the_drain_pauses_and_heartbeats_while_the_rebuild_runs(
    box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Y5, G5 (High): the rebuild holds the writer's lock from its first chain read to its verified marker. The
    drain's step meanwhile appends nothing (it returns at once) and its heartbeat is touched; after the rebuild it
    writes the line and its rows. No temporary marker file is left."""
    chain = tmp_path / "audit"
    chain.mkdir()
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _send(box, 21, "c2", PID_A)
    _drain(box, chain)
    paused, go = threading.Event(), threading.Event()
    real = idx._write_marker

    def hold(directory: Path, body: dict[str, Any]) -> None:
        real(directory, body)
        if body.get("done_through") and not paused.is_set():
            paused.set()
            go.wait(60)

    monkeypatch.setattr(idx, "_write_marker", hold)
    t = threading.Thread(target=_rebuild, args=(box, chain))
    t.start()
    assert paused.wait(60)
    d = Drain("postgresql://x@h/db", chain, TZ, connect=lambda: psycopg.connect(box, autocommit=True))
    d.open()
    try:
        _send(box, 22, "c3", PID_A)
        alive = tmp_path / "alive"
        t0 = time.monotonic()
        assert d.run(once=True, alive=alive) == 0
        assert time.monotonic() - t0 < 1.0
        assert alive.exists() and "c3" not in _chain_calls(chain)
        go.set()
        t.join(60)
        assert d.run(once=True, alive=alive) == 2
    finally:
        go.set()
        d.con.close()
    assert _calls(box) == ["c1", "c2", "c3"]
    assert _clean(chain)
    assert list(chain.glob(f".{idx.STATE}*")) == []


def test_a_rollback_copies_a_partitioned_register(box: str, tmp_path: Path) -> None:
    """Y6 (High): the live register is a partitioned table, the refusal in one of its partitions: the rollback finds
    the parent and copies it."""
    with psycopg.connect(box, autocommit=True) as c:
        c.execute("DROP SCHEMA optout CASCADE")
        c.execute("CREATE SCHEMA optout")
        c.execute("CREATE TABLE optout.optout_events (id bigserial, pid text NOT NULL, action text NOT NULL, "
                  "source text, note text, by text NOT NULL, at text COLLATE \"C\" NOT NULL) PARTITION BY HASH (pid)")  # fmt: skip
        for i in (0, 1):
            c.execute(f"CREATE TABLE optout.optout_events_p{i} PARTITION OF optout.optout_events "
                      f"FOR VALUES WITH (MODULUS 2, REMAINDER {i})")  # fmt: skip
    point = _dump(box, tmp_path)
    with psycopg.connect(box, autocommit=True) as c:
        register(c, PID_B, "opt_out", "2026-11-21T09:00:00+08:00")
        assert _val(c, "SELECT relkind FROM pg_class WHERE oid = 'optout.optout_events'::regclass") == "p"
    _rollback(box, point, tmp_path)
    assert _events_of(box, PID_B) == [("opt_out", "console:office1")]


@pytest.mark.parametrize("live", ["empty_skips", "nonempty_fails_before_swap"])
def test_an_empty_live_register_with_no_table_in_the_dump_rolls_back(box: str, tmp_path: Path, live: str) -> None:
    """Y7 (High): the rollback point predates the register's first opening. An empty live register is skipped and
    the rollback goes through; one with an event refuses before the swap (fail closed), the live database kept."""
    with psycopg.connect(box, autocommit=True) as c:
        c.execute("DROP SCHEMA optout CASCADE")
    point = _dump(box, tmp_path)
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(REGISTER)
        if live == "nonempty_fails_before_swap":
            register(c, PID_B, "opt_out", "2026-11-21T09:00:00+08:00")
    r = _rollback(box, point, tmp_path, ok=False)
    dbname = str(psycopg.conninfo.conninfo_to_dict(box)["dbname"])
    with psycopg.connect(box, autocommit=True) as c:
        there = _val(c, "SELECT to_regclass('optout.optout_events')")
        tbrb = _val(c, "SELECT count(*) FROM pg_database WHERE datname = %s", (f"{dbname}_tbrb",))
    if live == "empty_skips":
        assert r.returncode == 0, r.stderr[-1200:]
        assert there is None  # the restored database, as the dump had it
        assert up.restore_said(r.stdout)["register_events_kept"] == 0
    else:
        assert r.returncode != 0
        assert there is not None and _events_of(box, PID_B) == [("opt_out", "console:office1")]
    assert tbrb == 0


def test_the_drain_requires_autocommit_and_releases_the_consent_lock(box: str, tmp_path: Path) -> None:
    """Y8 (High), N3, X5: a drain on a connection that is not autocommit is refused at its start, naming it. On an
    autocommit one, a drained use line commits with its line: another session's erase does not wait on the lock."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    d = Drain("postgresql://x@h/db", chain, TZ, connect=lambda: psycopg.connect(box))
    with pytest.raises(RuntimeError, match="autocommit"):
        d.open()
    d.con.close()
    d = Drain("postgresql://x@h/db", chain, TZ, connect=lambda: psycopg.connect(box, autocommit=True))
    d.open()
    try:
        _send(box, 20, "c1", PID_B)
        assert d.step() == 2
        with psycopg.connect(box, autocommit=True) as w:
            w.execute("SET lock_timeout = '2s'")
            assert idx.erase(w, [PID_B]) == 1
    finally:
        d.con.close()


def test_a_failed_probe_leaves_the_connection_usable(box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Y9, N3: the probe at the start meets a real database error; the next step drains and indexes on the same
    connection."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    real, once = idx.installed, iter([True])

    def probe(con: Any) -> bool:
        if next(once, False):
            con.execute("SELECT * FROM provenance.no_such_table")
        return real(con)

    monkeypatch.setattr(idx, "installed", probe)
    d = Drain("postgresql://x@h/db", chain, TZ, connect=lambda: psycopg.connect(box, autocommit=True))
    d.open()
    try:
        assert not d.index
        _send(box, 20, "c1", PID_A)
        assert d.step() == 2
    finally:
        d.con.close()
    assert (_calls(box), _uses(box)) == (["c1"], ["c1"])


def test_a_failed_index_write_requires_a_rebuild(box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Y10, X3, X7: one index write fails: the marker requires the rebuild (named), the rest of the batch and the
    later lines are not written past the gap, and a later failure does not put the first one's time off. A use row
    the trigger never saw (X3's slipped row) is gone after the rebuild, which writes every row once."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    with psycopg.connect(box, autocommit=True) as c:
        register(c, PID_B, "opt_out", "2026-11-19T09:00:00+08:00")
    _flaky_add(monkeypatch, which=0)
    d = Drain("postgresql://x@h/db", chain, TZ, connect=lambda: psycopg.connect(box, autocommit=True))
    d.open()
    try:
        _send(box, 20, "c1", PID_A)
        assert d.step() == 2
        first = idx.read_marker(chain)
        assert (first.clean, first.reason) == (False, "index write failed")
        _send(box, 21, "c2", PID_A)
        assert d.step() == 2
    finally:
        d.con.close()
    assert (_calls(box), _uses(box)) == ([], [])
    assert idx.read_marker(chain).since == first.since
    _slipped(box, PID_B)
    assert _rebuild(box, chain) == (2, 2)
    assert (_calls(box), _uses(box), _uses(box, PID_B)) == (["c1", "c2"], ["c1", "c2"], [])
    assert _check(box, chain).ok and _clean(chain)


def test_an_opt_out_never_touches_the_index(box: str, tmp_path: Path) -> None:
    """G3, (v) (High if true): with no index at all an opt-out and a lift are recorded, with the marker required too;
    the rebuild then leaves B out. (A keeper that cannot read the register, on the box's own roles:
    ``test_provenance_roles.test_a_rebuild_refuses_while_the_keeper_cannot_read_the_register``.)"""
    chain = tmp_path / "audit"
    chain.mkdir()
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    reg = _register(box)
    try:
        _send(box, 20, "c1", PID_B)
        _drain(box, chain)
        idx.require_rebuild(chain, "update rollback")
        with psycopg.connect(box, autocommit=True) as c:
            c.execute("ALTER SCHEMA provenance RENAME TO provenance_away")  # no index at all
        assert reg.add(PID_B, "paper", "", "console:office1", "2026-11-21T09:00:00+08:00")
        assert reg.lift(PID_B, "", "console:office1", "2026-11-22T09:00:00+08:00")
        assert reg.add(PID_B, "paper", "", "console:office1", "2026-11-23T09:00:00+08:00")
        assert not _clean(chain)
        with psycopg.connect(box, autocommit=True) as c:
            c.execute("ALTER SCHEMA provenance_away RENAME TO provenance")
    finally:
        reg.close()
    _rebuild(box, chain)
    assert (_uses(box, PID_B), _calls(box)) == ([], ["c1"])


def test_an_opt_out_during_rebuild_required_wins_at_rebuild(box: str, tmp_path: Path) -> None:
    """(i): the index emptied by a restore and the marker required; B's uses are in the chain. B opts out (the
    register alone), then the rebuild: B has no use row, the call rows are there, the check agrees."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    reg = _register(box)
    try:
        _send(box, 20, "c1", PID_A)
        _send(box, 21, "c2", PID_B)
        _drain(box, chain)
        idx.require_rebuild(chain, "update rollback")
        with psycopg.connect(box, autocommit=True) as c:
            c.execute(up.RESTORE_EMPTY_INDEX_SQL)
        assert reg.add(PID_B, "paper", "", "console:office1", "2026-11-22T09:00:00+08:00")
    finally:
        reg.close()
    _rebuild(box, chain)
    assert (_uses(box, PID_B), _uses(box, PID_A), _calls(box)) == ([], ["c1"], ["c1", "c2"])
    assert _check(box, chain).ok


def test_an_opt_out_during_the_rebuild_wins(box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """(i), R3: B opts out between the rebuild's day files and the opt-out worker erases: the day already written
    loses B's row to the erase, the next day's row is withheld by the trigger; the check agrees."""
    chain = tmp_path / "audit"
    chain.mkdir()
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    reg = _register(box)
    try:
        _send(box, 20, "c1", PID_B)
        _send(box, 21, "c2", PID_B)
        _drain(box, chain)
        real = idx._write_marker
        said: list[bool] = []

        def between_days(directory: Path, body: dict[str, Any]) -> None:
            real(directory, body)
            if body.get("done_through") == "2026-11-20.jsonl":
                assert _uses(box, PID_B) == ["c1"]
                said.append(reg.add(PID_B, "paper", "", "console:office1", "2026-11-22T09:00:00+08:00"))
                with psycopg.connect(box, autocommit=True) as w:  # the opt-out worker
                    said.append(idx.erase(w, [PID_B]) == 1)

        monkeypatch.setattr(idx, "_write_marker", between_days)
        _rebuild(box, chain)
    finally:
        reg.close()
    assert said == [True, True]
    assert (_uses(box, PID_B), _calls(box)) == ([], ["c1", "c2"])
    assert _check(box, chain).ok


#: a rebuild in a process of its own that kills itself (SIGKILL): in the second day file, after its first line's rows
#: and before that day's transaction commits ("in_day"), or after that day committed and before the marker says so
#: ("after_commit")
_KILLED = """
import os, signal, sys
from pathlib import Path
import psycopg
from tb_common import provenance_index as idx

dsn, chain, where = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
real_add, real_mark = idx.add, idx._write_marker

def add(con, rec):
    n = real_add(con, rec)
    if where == "in_day" and str(rec.get("ts", "")).startswith("2026-11-21"):
        os.kill(os.getpid(), signal.SIGKILL)
    return n

def mark(directory, body):
    if where == "after_commit" and body.get("done_through") == "2026-11-21.jsonl":
        os.kill(os.getpid(), signal.SIGKILL)
    real_mark(directory, body)

idx.add, idx._write_marker = add, mark
with psycopg.connect(dsn, autocommit=True) as con:
    idx.rebuild(con, chain)
"""


class _Spy:
    """The rebuild's connection, every statement kept (the resumed rebuild must not empty the tables)."""

    def __init__(self, con: Any) -> None:
        self.con, self.autocommit = con, con.autocommit
        self.said: list[str] = []

    def execute(self, sql: Any, *a: Any, **k: Any) -> Any:
        self.said.append(str(sql))
        return self.con.execute(sql, *a, **k)

    def transaction(self) -> Any:
        return self.con.transaction()


@pytest.mark.parametrize("where", ["in_day", "after_commit"])
def test_kill_9_mid_rebuild_is_resumed_by_the_next(box: str, tmp_path: Path, where: str) -> None:
    """(iii): three day files; the rebuild is killed in the second. The first day is committed and recorded, nothing
    of the second is in the index (or, killed after its commit, the marker does not say it), and the marker is not
    clean. The next rebuild empties nothing, skips what is recorded, writes every row once and says verified."""
    chain = tmp_path / "audit"
    chain.mkdir()
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    for n, call in ((20, "c1"), (21, "c2"), (22, "c3")):
        _send(box, n, call, PID_A)
    _drain(box, chain)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
    r = subprocess.run([sys.executable, "-c", _KILLED, box, str(chain), where], env=env, capture_output=True,
                       text=True, timeout=120, check=False)  # fmt: skip
    assert r.returncode == -signal.SIGKILL, r.stderr[-1500:]
    m = idx.read_marker(chain)
    assert (m.clean, m.done_through) == (False, "2026-11-20.jsonl")
    assert _calls(box) == (["c1"] if where == "in_day" else ["c1", "c2"])
    with psycopg.connect(box, autocommit=True) as c:
        spy = _Spy(c)
        assert idx.rebuild(spy, chain) == (3, 3)
    assert not any(s.startswith("DELETE") for s in spy.said)
    assert (_calls(box), _uses(box)) == (["c1", "c2", "c3"], ["c1", "c2", "c3"])
    assert _clean(chain) and _check(box, chain).ok


def test_only_search_and_index_writes_are_refused(box: str, tmp_path: Path) -> None:
    """(ii): while required, the search is refused with the operator's text and the drain writes the chain line but
    no row; the opt-out worker's erase and the register's write go on."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    reg = _register(box)
    try:
        _send(box, 20, "c1", PID_A)
        _drain(box, chain)
        idx.require_rebuild(chain, "update rollback")
        with psycopg.connect(box, autocommit=True) as c, pytest.raises(idx.ProvenanceRebuildRequired) as e:
            idx.search(c, directory=chain, model="m-judge")
        m = idx.read_marker(chain)
        assert str(e.value) == m.text == idx.TEXT.format(reason="update rollback", since=m.since)
        assert m.text.endswith("run trialbox provenance --rebuild")
        _send(box, 21, "c2", PID_A)
        assert _drain(box, chain) == 2
        assert "c2" in _chain_calls(chain) and _calls(box) == ["c1"]
        with psycopg.connect(box, autocommit=True) as c:
            assert idx.erase(c, [PID_A]) == 1
        assert reg.add(PID_B, "paper", "", "console:office1", "2026-11-22T09:00:00+08:00")
    finally:
        reg.close()


def test_search_needs_the_audit_directory(box: str) -> None:
    """G8: no caller is served without the marker's answer."""
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
        with pytest.raises(TypeError):
            idx.search(c, model="m-judge")  # type: ignore[call-arg]


def test_an_unreadable_marker_is_required(tmp_path: Path) -> None:
    """G7: no file, bad JSON, the version-1 marker, a file this process may not read: required, the reason named.
    A written marker is readable by every service (0644)."""
    assert idx.read_marker(tmp_path).reason == "no marker"
    for body, reason in (("{", "not JSON"), (json.dumps({"version": 1, "state": "clean"}), "version 1")):
        (tmp_path / idx.STATE).write_text(body, encoding="utf-8")
        m = idx.read_marker(tmp_path)
        assert not m.clean and reason in m.reason, m
    idx.require_rebuild(tmp_path, "update rollback")
    assert (tmp_path / idx.STATE).stat().st_mode & 0o777 == 0o644
    if os.geteuid() != 0:  # root reads a mode-000 file
        (tmp_path / idx.STATE).chmod(0)
        m = idx.read_marker(tmp_path)
        assert not m.clean and "PermissionError" in m.reason


def test_the_doctor_fails_while_required_and_names_the_command(
    box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """(iv): the doctor and ``trialbox provenance --check`` fail with the operator's text before any database work;
    after the rebuild both pass."""
    from tools.trialbox import doctor
    from tools.trialbox import provenance as cli

    chain = tmp_path / "audit"
    _ready(box, chain)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    idx.require_rebuild(chain, "update rollback")
    text = idx.read_marker(chain).text
    env = {"TB_DB_URL": _url(box), "TB_AUDIT_DIR": str(chain)}
    argv = ["--check", "--audit-dir", str(chain), "--db-url", _url(box)]

    def no_database(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("the database was asked before the marker")

    with monkeypatch.context() as mp:
        mp.setattr(psycopg, "connect", no_database)
        row = doctor.check_provenance_index(doctor.DoctorInputs(env=env))
        assert (row.status, row.detail) == ("FAIL", text)
        capsys.readouterr()
        assert cli.main(argv) == 1
        assert capsys.readouterr().out.strip() == text
    _rebuild(box, chain)
    assert doctor.check_provenance_index(doctor.DoctorInputs(env=env)).status == "PASS"
    assert cli.main(argv) == 0


def test_the_cli_search_refuses_while_required(box: str, tmp_path: Path, capsys: Any) -> None:
    """P19-X1 (High): ``trialbox provenance --search`` asks the marker in its audit directory: refused with the
    operator's text while required, answered after ``--rebuild``."""
    from tools.trialbox import provenance as cli

    chain = tmp_path / "audit"
    _ready(box, chain)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    args = ["--audit-dir", str(chain), "--db-url", _url(box)]
    argv = ["--search", "--model", "m-judge", *args]
    idx.require_rebuild(chain, "journal resync")
    capsys.readouterr()
    assert cli.main(argv) == 1
    out = capsys.readouterr()
    assert "call c1" not in out.out and "run trialbox provenance --rebuild" in out.err
    assert cli.main(["--rebuild", *args]) == 0
    assert cli.main(argv) == 0
    assert "call c1" in capsys.readouterr().out


def test_an_interrupted_rebuild_serves_nothing_until_it_is_run_again(
    box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P19-X8: a rebuild stopped half way (Ctrl-C) never leaves a partial index under a verified marker: the search
    is refused until the next rebuild, which writes it whole."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    _send(box, 20, "c1", PID_A)
    _send(box, 21, "c2", PID_B)
    _drain(box, chain)
    real, writes = idx.add, itertools.count()

    def stopped(con: Any, rec: dict[str, Any]) -> int:
        if next(writes) == 2:
            raise KeyboardInterrupt
        return real(con, rec)

    monkeypatch.setattr(idx, "add", stopped)
    with pytest.raises(KeyboardInterrupt):
        _rebuild(box, chain)
    assert not _clean(chain)
    with psycopg.connect(box, autocommit=True) as c, pytest.raises(idx.ProvenanceRebuildRequired):
        idx.search(c, directory=chain, model="m-judge")
    monkeypatch.undo()
    _rebuild(box, chain)
    assert (_calls(box), _uses(box)) == (["c1", "c2"], ["c1", "c2"])


def test_a_rollback_empties_the_index_even_when_the_rebuild_cannot_run(box: str, tmp_path: Path) -> None:
    """F2: a rebuild that cannot run (here: a second register schema) leaves no withheld row in the index: the
    restore emptied it before the swap, and the marker stays required."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    with psycopg.connect(box, autocommit=True) as c:
        register(c, PID_B, "opt_out", "2026-11-21T09:00:00+08:00")
    _slipped(box, PID_B)
    point = _dump(box, tmp_path)
    up.mark_rebuild_required(chain)
    _rollback(box, point, tmp_path)
    with psycopg.connect(box, autocommit=True) as c:
        c.execute("CREATE SCHEMA x_optout")
        c.execute("CREATE TABLE x_optout.optout_events (LIKE optout.optout_events)")
    with pytest.raises(idx.RebuildRefused):
        _rebuild(box, chain)
    assert _uses(box, PID_B) == []
    assert idx.read_marker(chain).reason == "update rollback"


def test_the_rebuild_counts_the_rows_it_wrote(box: str, tmp_path: Path) -> None:
    """F6: a use row the register withholds is not a row of the index: the rebuild says so, and so does its marker."""
    chain = tmp_path / "audit"
    _ready(box, chain)
    with psycopg.connect(box, autocommit=True) as c:
        register(c, PID_A, "opt_out", "2026-11-19T09:00:00+08:00")
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    assert _rebuild(box, chain) == (1, 0)
    assert json.loads((chain / idx.STATE).read_text(encoding="utf-8"))["rows"] == [1, 0]


def test_a_backup_restore_empties_the_index_and_keeps_the_register_alone(box: str, tmp_path: Path) -> None:
    """X2, backup: the backup restore's register writer (``backup.keep_optouts``) writes the register alone, with no
    index in the database at all; the restore empties the index (``backup.empty_index``)."""
    from tools.trialbox import backup as bk

    src = bk.DbSource("trialbox_wf", box, ())
    live = [(PID_B, "opt_out", "paper", None, "console:office1", "2026-11-22T01:00:00+00:00")]
    gone, back = bk.keep_optouts(src, live)
    assert (len(gone), back) == (1, 1)
    assert _events_of(box, PID_B) == [("opt_out", "console:office1")]
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _slipped(box, PID_B)  # the backup's use row of B
    bk.empty_index(src)
    assert _uses(box) == []


def test_a_backup_restore_requires_a_rebuild_whatever_the_restored_marker_says(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backup (§4 writer 2): the backed-up audit folder carries a verified marker; after the restore the marker
    requires the rebuild, named."""
    from tests.unit.test_restore_hold import _backup_and_restore

    audit = tmp_path / "audit"
    audit.mkdir()
    idx._write_marker(audit, {"verified": True, "built_at": "2026-11-20T00:00:00+00:00"})
    assert _clean(audit)
    _out, audit, _f, _p = _backup_and_restore(tmp_path, db_url, monkeypatch, late_events=False)
    m = idx.read_marker(audit)
    assert (m.clean, m.reason) == (False, "backup restore")


def test_rebuild_time_at_the_declared_site_size(box: str, tmp_path: Path) -> None:
    """§3: the rebuild's wall time at the lead's declared site size (``TB_P19_SITE_LINES`` chain lines) is within
    ``TB_P19_REBUILD_BUDGET_S``. No figure is invented: without both, nothing is measured."""
    lines, budget = os.environ.get("TB_P19_SITE_LINES"), os.environ.get("TB_P19_REBUILD_BUDGET_S")
    if not lines or not budget:
        pytest.skip("TB_P19_SITE_LINES and TB_P19_REBUILD_BUDGET_S are not declared (P19-DESIGN-3 §3)")
    log = AuditLog(tmp_path / "audit", TZ)
    for i in range(int(lines) // 2):
        call_f, use_f = _fields(20, f"c{i}", PID_A if i % 2 else PID_B)
        ts = datetime.fromisoformat(f"2026-11-{1 + i * 28 // max(int(lines) // 2, 1):02d}T02:00:00+08:00")
        log.append("llm.call", ts=ts, **call_f)
        log.append("ai.used", ts=ts, **use_f)
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
        t0 = time.monotonic()
        idx.rebuild(c, log.directory)
        took = time.monotonic() - t0
    print(f"rebuild of {lines} chain lines: {took:.1f} s")
    assert took <= float(budget)
