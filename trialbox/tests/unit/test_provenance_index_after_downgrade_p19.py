"""P-19: the provenance index equals the audit chain after a night, an update and a downgrade.

The walk's doctor said ``provenance_index FAIL, 108 row(s) missing`` and the count did not move across an update and a
downgrade. The audit drain is the index's only writer, and it passed lines over in two ways that nothing wrote back:

* a downgrade (an update's rollback) puts the trial database back from the rollback point's dump, the provenance
  tables with it, while the chain keeps every line drained since: those lines' rows were gone for good (only a
  ``trialbox provenance --rebuild`` by hand wrote them);
* the drain asked once, at its start, whether the index's tables were there: tables made after that were not written
  until the drain was started again.

Now the drain, when it finds the database put back to an older point (its journal resync), writes the index rows of
the chain's lines drained from journal rows the database no longer holds, and it asks again for the tables while
they are not there. Older lines are never written back: their rows are in the index or were taken out at an opt-out,
which only ``trialbox provenance --rebuild`` may judge, with the register. Real drain, real tables, real ``pg_dump``
and ``pg_restore`` on the test cluster; fixed times for the events; synthetic pseudonyms only.
"""

from __future__ import annotations

import itertools
import json
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from tb_common import provenance_index as idx
from tb_common.audit_writer import Drain, _dsn

from tools import pglocal

TZ = "Asia/Taipei"
PID_A = "0ca5381cfa6bdf1c22961d65579f93b3"
PID_B = "1afe78d42518132b113c5858cedcbb54"
_N = itertools.count()
#: the journal's columns as the drain reads them (``audit_writer.JOURNAL_SQL`` without its roles and grants)
JOURNAL = """CREATE SCHEMA audit;
CREATE TABLE audit.journal (seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT clock_timestamp(), db_role text NOT NULL, event text NOT NULL, ts text NOT NULL,
  fields jsonb NOT NULL)"""


@pytest.fixture
def box(pg_cluster_url: str) -> Iterator[str]:
    """A database of this test's own: the journal and the provenance index, as the role script makes them."""
    name = f"tb_p19_{os.getpid()}_{next(_N)}"
    with psycopg.connect(_dsn(pg_cluster_url), autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    dsn = psycopg.conninfo.make_conninfo(_dsn(pg_cluster_url), dbname=name)
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(JOURNAL)
    try:
        yield dsn
    finally:
        with psycopg.connect(_dsn(pg_cluster_url), autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


def _send(dsn: str, n: int, call: str, pid: str) -> None:
    """One night's model call and the verdict it was used for, as a service hands them to the journal."""
    ts = f"2026-11-{n:02d}T02:00:00+08:00"
    call_f = {"model": "m-judge", "prompt_version": "judge_v4", "input_sha": "i", "output_sha": "o",
              "detail": {"call_id": call, "build_sha": f"b{n}", "prompt_sha": "p" * 64}}  # fmt: skip
    ref = {"ruleset": "GZQO", "version": "1.0.0", "job": f"J{n}", "pid": pid, "crit": "N-INC-01"}
    use_f = {"detail": {"record_kind": "verdict", "record_ref": ref, "calls": [call]}}
    with psycopg.connect(dsn, autocommit=True) as c:
        for event, fields in (("llm.call", call_f), ("ai.used", use_f)):
            c.execute("INSERT INTO audit.journal (db_role, event, ts, fields) VALUES ('tb_orchestrator', %s, %s, %s)",
                      (event, ts, json.dumps(fields)))  # fmt: skip


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


def _pg(tool: str, *args: str) -> None:
    subprocess.run([str(pglocal.bindir() / tool), *args], check=True, capture_output=True, timeout=120)


def test_the_index_equals_the_chain_after_a_night_an_update_and_a_downgrade(box: str, tmp_path: Path) -> None:
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)  # a night
    assert _drain(box, chain) == 2
    assert _check(box, chain).ok
    dump = tmp_path / "rollback.dump"  # the update: its rollback point, then the box runs on the new release
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    _send(box, 21, "c2", PID_B)
    assert _drain(box, chain) == 2
    assert _check(box, chain).ok
    with psycopg.connect(box, autocommit=True) as c:  # the downgrade: the database back to the rollback point
        c.execute("DROP SCHEMA audit, provenance CASCADE")
    _pg("pg_restore", "-d", box, str(dump))
    _drain(box, chain)  # the drain starts again on the restored database (it records the resync)
    diff = _check(box, chain)
    assert diff.ok, diff.missing
    with psycopg.connect(box, autocommit=True) as c:
        assert sorted(r[0] for r in c.execute("SELECT call_id FROM provenance.model_calls")) == ["c1", "c2"]


def test_tables_made_after_the_drain_started_are_written_without_a_restart(box: str, tmp_path: Path) -> None:
    chain = tmp_path / "audit"
    d = Drain("postgresql://x@h/db", chain, TZ, connect=lambda: psycopg.connect(box, autocommit=True))
    d.open()
    try:
        assert not d.index
        with psycopg.connect(box, autocommit=True) as c:
            c.execute(idx.INDEX_SQL)  # the role script, run after the drain was up
        _send(box, 22, "c3", PID_A)
        assert d.step() == 2
        assert d.index
        with psycopg.connect(box, autocommit=True) as c:
            assert [r[0] for r in c.execute("SELECT call_id FROM provenance.model_calls")] == ["c3"]
    finally:
        d.con.close()


def test_a_use_row_taken_out_at_an_opt_out_is_not_written_back_at_a_start(box: str, tmp_path: Path) -> None:
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _send(box, 21, "c2", PID_B)
    _drain(box, chain)
    with psycopg.connect(box, autocommit=True) as c:
        assert idx.erase(c, [PID_B]) == 1  # the newest use row of the index
    _drain(box, chain)  # started again on the same database: nothing is written back
    assert _check(box, chain).missing == [("provenance.model_uses", _hash_of(chain, "c2", "ai.used"), "c2")]
    with psycopg.connect(box, autocommit=True) as c:
        assert idx.check(c, chain, erased=[PID_B]).ok


def _hash_of(chain: Path, call: str, event: str) -> str:
    recs: list[dict[str, Any]] = [r for r in idx.chain_records(chain) if r.get("event") == event]
    return next(str(r["hash"]) for r in recs if call in ((r.get("detail") or {}).get("calls") or []))


# --- review of P-19 (P19-R1 to R5, F1 to F5): each case below fails on the first change


def _opt_out(dsn: str, n: int, pid: str) -> None:
    """The opt-out desk's record of a patient's no, as the console hands it to the journal (``console.opt_out``)."""
    fields = {"actor": "console:office1", "detail": {"pid": pid, "action": "opt_out", "reason": "", "source": "paper",
                                                     "removed_from": "screening, candidate lists, exports"}}  # fmt: skip
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("INSERT INTO audit.journal (db_role, event, ts, fields) VALUES ('tb_console', 'console.opt_out', "
                  "%s, %s)", (f"2026-11-{n:02d}T09:00:00+08:00", json.dumps(fields)))  # fmt: skip


def _restore(dsn: str, dump: Path) -> None:
    """The downgrade: the database back to the rollback point (the register and the index with it)."""
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("DROP SCHEMA audit, provenance CASCADE")
    _pg("pg_restore", "-d", dsn, str(dump))


def _calls(dsn: str) -> list[str]:
    with psycopg.connect(dsn, autocommit=True) as c:
        return sorted(str(r[0]) for r in c.execute("SELECT call_id FROM provenance.model_calls"))


def test_an_opt_out_recorded_after_the_dump_stays_out_after_the_downgrade(box: str, tmp_path: Path) -> None:
    """P19-R1 / F1 (High): the register goes back with the dump, the chain keeps the opt-out: B's row is not re-made."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    dump = tmp_path / "rollback.dump"
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    _send(box, 21, "c2", PID_B)  # B's verdict, then B says no and the use row goes
    _opt_out(box, 22, PID_B)
    _drain(box, chain)
    with psycopg.connect(box, autocommit=True) as c:
        assert idx.erase(c, [PID_B]) == 1
    _restore(box, dump)
    _drain(box, chain)
    with psycopg.connect(box, autocommit=True) as c:
        assert [r[0] for r in c.execute("SELECT call_id FROM provenance.model_uses WHERE pid = %s", (PID_B,))] == []
        assert idx.check(c, chain, erased=[PID_B]).ok
    assert _calls(box) == ["c1", "c2"]  # the call rows name no patient: they are written back


def test_a_row_journaled_before_the_dump_and_drained_after_it_is_written_back(box: str, tmp_path: Path) -> None:
    """P19-R2 / F2: the journal's newest row is not the index's newest line (a backlog at the dump, and a row a
    service journals after the restore and before the drain starts)."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    _send(box, 21, "c2", PID_A)  # in the journal, not yet drained, when the dump is taken
    dump = tmp_path / "rollback.dump"
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    _drain(box, chain)
    _send(box, 22, "c3", PID_B)
    _drain(box, chain)
    _restore(box, dump)
    _send(box, 23, "c4", PID_B)  # another service is up before the drain
    _drain(box, chain)
    diff = _check(box, chain)
    assert diff.ok, diff.missing
    assert _calls(box) == ["c1", "c2", "c3", "c4"]


def test_a_dump_taken_before_the_first_journal_row_is_caught_up(box: str, tmp_path: Path) -> None:
    """P19-R3 / F2: the restored journal is empty (no newest row at all); every line drained since is written back."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    dump = tmp_path / "rollback.dump"
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    _restore(box, dump)
    _drain(box, chain)
    diff = _check(box, chain)
    assert diff.ok, diff.missing
    assert _calls(box) == ["c1"]


def test_a_catch_up_that_fails_part_way_is_tried_again_and_writes_each_row_once(
    box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P19-R4 / F3: a failure after the first write leaves the recovery pending; the running drain tries it again."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    dump = tmp_path / "rollback.dump"
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    _send(box, 21, "c2", PID_B)
    _send(box, 22, "c3", PID_A)
    _drain(box, chain)
    _restore(box, dump)
    real, writes = idx.add, itertools.count()

    def flaky(con: Any, rec: dict[str, Any], *a: Any, **k: Any) -> int:
        if next(writes) == 1:  # the catch-up's second line: the database went away for a moment
            raise psycopg.OperationalError("synthetic: the connection dropped")
        return real(con, rec, *a, **k)

    monkeypatch.setattr(idx, "add", flaky)
    monkeypatch.setattr(Drain, "RETRY", 0.0, raising=False)  # tried again at the next batch, not a minute later
    d = Drain("postgresql://x@h/db", chain, TZ, connect=lambda: psycopg.connect(box, autocommit=True))
    d.open()
    try:
        assert _calls(box) == ["c1", "c2"]  # the first line was written, the rest was not
        _send(box, 23, "c4", PID_B)
        assert d.step() == 2
    finally:
        d.con.close()
    diff = _check(box, chain)
    assert diff.ok, diff.missing
    assert _calls(box) == ["c1", "c2", "c3", "c4"]
    with psycopg.connect(box, autocommit=True) as c:
        uses = [r[0] for r in c.execute("SELECT call_id FROM provenance.model_uses ORDER BY call_id")]
    assert uses == ["c1", "c2", "c3", "c4"]


def test_a_line_whose_journal_time_cannot_be_read_is_not_passed_over(box: str, tmp_path: Path) -> None:
    """P19-R5: the catch-up does not judge a line by its journal time, so a naive or garbled one is written back."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    dump = tmp_path / "rollback.dump"
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    _send(box, 21, "c2", PID_B)
    _drain(box, chain)
    day = sorted(chain.glob("*.jsonl"))[-1]
    lines = day.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        rec = json.loads(line)
        if rec.get("event") == "llm.call" and (rec.get("detail") or {}).get("call_id") == "c2":
            rec["journal"]["at"] = "2026-11-21 02:00:00"  # no zone
            lines[i] = json.dumps(rec, sort_keys=True, ensure_ascii=False)
    day.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _restore(box, dump)
    _drain(box, chain)
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
