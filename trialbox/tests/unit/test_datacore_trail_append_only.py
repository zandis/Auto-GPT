"""EDC-009 (D-582): the data core's trail is append-only.

Before (deep review of 2026-11-12, case 10c): ``UPDATE history ...`` and ``DELETE FROM history ...`` were accepted.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from datacore import builtin
from datacore.store import DataCore, DataError
from datacore.sync import resolve, save_form

AT = "2026-11-08T10:00:00+09:00"
REFUSED = psycopg.errors.InsufficientPrivilege


@pytest.fixture
def dc() -> Iterator[DataCore]:
    core = DataCore()
    for q in builtin.builtin_questionnaires("GZQO"):
        core.put_form("GZQO", q, builtin.ORIGIN, AT)
    yield core
    core.close()


def _two_changes(dc: DataCore) -> None:
    dc.write("GZQO", "GZQO-0001", "v1", "vs_weight", "72.5", "crc", AT, "entry")
    dc.write("GZQO", "GZQO-0001", "v1", "vs_weight", "80", "crc", AT, "entry")


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE history SET new = 'x'",
        "UPDATE history SET \"by\" = 'someone else' WHERE field = 'vs_weight'",
        "DELETE FROM history",
        "DELETE FROM history WHERE field = 'vs_weight'",
        "TRUNCATE history",
    ],
)
def test_history_takes_inserts_only(dc: DataCore, sql: str) -> None:
    _two_changes(dc)
    before = dc.history("GZQO")
    assert [(h["old"], h["new"]) for h in before] == [(None, "72.5"), ("72.5", "80")]
    with pytest.raises(REFUSED, match="datacore.history is append-only"), dc.db.transaction() as tx:
        tx.execute(sql)
    assert dc.history("GZQO") == before
    dc.write("GZQO", "GZQO-0001", "v1", "vs_weight", "81", "crc", AT, "entry")  # the next change is still written
    assert len(dc.history("GZQO")) == 3


def test_a_whole_form_save_still_writes_its_history(dc: DataCore) -> None:
    out = save_form(dc, "GZQO", "GZQO-0001", "", "tb_consent",
                    {"ic_date": "2026-11-02", "ic_version": "v2.1", "ic_copy": "1", "ic_reconsent": "0"}, "crc", AT)  # fmt: skip
    assert out["changed"] == 4 and len(dc.history("GZQO")) == 4


@pytest.mark.parametrize("sql", ["UPDATE subject_step SET reason = 'x'", "DELETE FROM subject_step",
                                 "TRUNCATE subject_step"])  # fmt: skip
def test_a_subject_step_takes_inserts_only(dc: DataCore, sql: str) -> None:
    with dc.db.transaction() as tx:
        tx.execute("INSERT INTO subject_step (study, record, old, new, on_day, reason, note, who, at, source) "
                   "VALUES ('GZQO', 'GZQO-0001', '', 'screened', '2026-11-02', '', '', 'crc', ?, 'entry')", (AT,))  # fmt: skip
    with pytest.raises(REFUSED, match="datacore.subject_step is append-only"), dc.db.transaction() as tx:
        tx.execute(sql)
    assert dc.db.fetchval("SELECT count(*) FROM subject_step") == 1


def _conflict(dc: DataCore) -> int:
    dc.write("GZQO", "GZQO-0001", "v1", "vs_weight", "72.5", "crc", AT, "entry")
    cid = dc.add_conflict("GZQO", "GZQO-0001", "v1", "vs_weight", "trialbox", "redcap", "72.5", "80", AT)
    assert cid is not None
    return cid


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM conflict",
        "TRUNCATE conflict",
        "UPDATE conflict SET theirs = '72.5'",
        "UPDATE conflict SET trialbox = '80', resolved = 'trialbox', resolved_by = 'x', resolved_at = 'y'",
        "UPDATE conflict SET record = 'GZQO-0002'",
        "UPDATE conflict SET at = '2020-01-01'",
    ],
)
def test_an_open_conflict_can_only_be_closed(dc: DataCore, sql: str) -> None:
    cid = _conflict(dc)
    before = dc.conflict(cid)
    with pytest.raises(REFUSED, match="datacore.conflict"), dc.db.transaction() as tx:
        tx.execute(sql)
    assert dc.conflict(cid) == before


def test_closing_a_conflict_works_once_and_a_closed_one_is_never_changed(dc: DataCore) -> None:
    cid = _conflict(dc)
    out = resolve(dc, cid, "theirs", "crc2", AT)
    assert out and (dc.conflict(cid) or {})["resolved"] == "theirs"
    closed = dc.conflict(cid)
    with pytest.raises(DataError):  # the service's own refusal
        resolve(dc, cid, "trialbox", "crc3", AT)
    for sql in ("UPDATE conflict SET resolved = 'trialbox', resolved_by = 'crc3'",
                "UPDATE conflict SET resolved = NULL, resolved_by = NULL, resolved_at = NULL",
                "DELETE FROM conflict"):  # fmt: skip
        with pytest.raises(REFUSED, match="datacore.conflict"), dc.db.transaction() as tx:
            tx.execute(sql)
    assert dc.conflict(cid) == closed


def test_opening_the_store_twice_makes_the_triggers_once(dc: DataCore) -> None:
    again = DataCore()
    try:
        names = [str(r[0]) for r in again.db.fetchall(
            "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON "
            "n.oid = c.relnamespace WHERE n.nspname = current_schema() AND NOT t.tgisinternal AND "
            "c.relname IN ('history', 'subject_step', 'conflict') ORDER BY 1")]  # fmt: skip
    finally:
        again.close()
    assert names == ["conflict_close_only", "conflict_no_truncate", "history_append_only", "history_no_truncate",
                     "subject_step_append_only", "subject_step_no_truncate"]  # fmt: skip
