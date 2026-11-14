"""NEW-B-37 (D-678; deep review DATA-026): the OMOP loader works in chunks of a declared bound.

``load_batch`` read the whole batch into memory: every resource, every record built from it, every stored record
to diff against. Measured before the change (synthetic): 1,000 dense patients, 559,056 resources, peaked at
5.4 GiB in one process, about 9.5 KB a resource, which is about 270 GiB at 50,000 dense patients against the
adapter's 6 GiB. Now the records are staged in the database a chunk at a time and every step reads them back in
chunks: the peak does not grow with the batch, and the store is the same whatever the chunk."""

from __future__ import annotations

import os
import random
import tracemalloc
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_omop_core import SNAP, _feed, feed_dir  # noqa: F401 (the module fixture of site A)

SNAP2 = "2026-10-05"
TZ = "Asia/Taipei"


def _url(db_url: str, prefix: str) -> str:
    return f"{db_url}{'&' if '?' in db_url else '?'}tb_prefix={prefix}{os.getpid()}_"


def _connect(db_url: str, prefix: str) -> Any:
    from omop import schema

    return schema.connect(_url(db_url, prefix))


#: what a load leaves, without the clock (changed_at, tombstoned_at and the like) and the load's own seconds
_TABLES = [
    "person", "visit_occurrence", "condition_occurrence", "drug_exposure", "measurement", "observation",
    "procedure_occurrence", "note", "death", "provider", "care_site", "tb_id_map", "tb_record", "tb_record_event",
    "tb_conflict", "tb_appointment", "tb_claim", "tb_consent", "concept",
]  # fmt: skip
_CLOCK = {"changed_at", "tombstoned_at", "recorded_at"}  # the clock; columns that default to now() are left out too


def _unclocked(v: Any) -> Any:
    """A JSON value without the clock (a record's before-image holds its ``changed_at``)."""
    if isinstance(v, dict):
        return {k: _unclocked(x) for k, x in v.items() if k not in _CLOCK and k != "created_at"}
    return v


def _dump(db: Any) -> dict[str, list[tuple[Any, ...]]]:
    out: dict[str, list[tuple[Any, ...]]] = {}
    for t in _TABLES:
        cols = [
            str(c)
            for (c,) in db.fetchall(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
                "AND table_name = ? AND coalesce(column_default, '') NOT LIKE '%now()%' "
                "AND coalesce(column_default, '') NOT ILIKE '%current_timestamp%' ORDER BY ordinal_position",
                (t,),
            )
            if str(c) not in _CLOCK
        ]
        if not cols:
            continue
        rows = db.fetchall(f"SELECT {', '.join(cols)} FROM {t}")
        out[t] = sorted((tuple(_unclocked(v) for v in r) for r in rows), key=repr)
    return out


def _night2(feed: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """The next night: a few records gone (tombstones), one changed (an update), the rest the same."""
    rnd = random.Random(7)
    out = {t: [dict(r) for r in rs if t == "Patient" or rnd.random() > 0.05] for t, rs in feed.items()}
    obs = out.get("Observation") or []
    if obs and "valueQuantity" in obs[0]:
        obs[0] = {**obs[0], "valueQuantity": {**obs[0]["valueQuantity"], "value": 999}}
    return out


def test_a_load_in_small_chunks_leaves_the_same_store_as_one_chunk(
    feed_dir: Path,  # noqa: F811
    db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from omop.load import load_batch

    feed = _feed(feed_dir)
    nights = [(SNAP, feed), (SNAP2, _night2(feed))]
    stores = {}
    for prefix, chunk in (("omopone", "100000000"), ("omopsmall", "37")):
        monkeypatch.setenv("TB_OMOP_LOAD_CHUNK", chunk)
        db = _connect(db_url, prefix)
        try:
            reports = [load_batch(db, "feed", snap, by, tz=TZ).as_dict() for snap, by in nights]
            stores[prefix] = (_dump(db), [{k: v for k, v in r.items() if k != "seconds"} for r in reports])
        finally:
            db.close()
    (one, rep_one), (small, rep_small) = stores["omopone"], stores["omopsmall"]
    assert rep_one == rep_small
    assert rep_one[1]["tombstoned"] > 0 and rep_one[1]["updated"] > 0  # the second night changes the store
    assert one.keys() == small.keys()
    for t in one:
        if one[t] != small[t]:
            a = [r for r in one[t] if r not in small[t]][:2]
            b = [r for r in small[t] if r not in one[t]][:2]
            diff = (
                [(i, x, y) for i, (x, y) in enumerate(zip(a[0], b[0], strict=False)) if x != y] if a and b else (a, b)
            )
            raise AssertionError(f"{t}: {diff}")


# ------------------------------------------------------------------------------------------------ the bound
class _Patients:
    """``n`` synthetic patients with ``per`` conditions each, read again each time it is iterated (as the NDJSON
    readers give them): the input never sits in memory whole."""

    def __init__(self, n: int, per: int, kind: str) -> None:
        self.n, self.per, self.kind = n, per, kind

    def __iter__(self) -> Iterator[dict[str, Any]]:
        for i in range(self.n):
            pid = f"p{i:06d}"
            if self.kind == "Patient":
                yield {"resourceType": "Patient", "id": pid, "gender": "female", "birthDate": "1960-01-01"}
                continue
            for j in range(self.per):
                yield {
                    "resourceType": "Condition",
                    "id": f"c{i:06d}-{j:02d}",
                    "subject": {"reference": f"Patient/{pid}"},
                    "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": f"E11.{j % 10}"}]},
                    "recordedDate": "2026-01-02",
                    "clinicalStatus": {"coding": [{"code": "active"}]},
                }


def _peak(db_url: str, prefix: str, n: int) -> int:
    from omop.load import load_batch

    db = _connect(db_url, prefix)
    try:
        by = {"Patient": _Patients(n, 0, "Patient"), "Condition": _Patients(n, 20, "Condition")}
        tracemalloc.start()
        try:
            load_batch(db, "feed", SNAP, by, tz=TZ)
            return tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
    finally:
        db.close()


def test_the_peak_does_not_grow_with_the_batch(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Four times the patients, the same chunk: the peak stays (before: it grew about four times)."""
    monkeypatch.setenv("TB_OMOP_LOAD_CHUNK", "500")
    small = _peak(db_url, "omoppeaks", 100)
    big = _peak(db_url, "omoppeakb", 400)
    assert big < small * 1.6, (small, big)


# ------------------------------------------------------------------------------------- refusals and interruptions
def test_a_date_of_another_calendar_in_a_late_chunk_refuses_the_batch_and_writes_nothing(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from omop.load import load_batch
    from omop.schema import OmopError

    monkeypatch.setenv("TB_OMOP_LOAD_CHUNK", "50")
    db = _connect(db_url, "omoproc")
    try:
        conds = list(_Patients(30, 5, "Condition"))
        conds[-1] = {**conds[-1], "recordedDate": "0115-01-02"}  # a ROC year, in the last chunk
        with pytest.raises(OmopError, match="refused, nothing loaded"):
            load_batch(db, "feed", SNAP, {"Patient": list(_Patients(30, 0, "Patient")), "Condition": conds}, tz=TZ)
        assert db.fetchval("SELECT count(*) FROM tb_record") == 0
        assert db.fetchval("SELECT count(*) FROM person") == 0
        assert db.fetchval("SELECT count(*) FROM tb_load WHERE source_kind = 'feed-refused'") == 1
    finally:
        db.close()


def test_a_load_cut_in_a_later_chunk_leaves_the_store_as_it_was_and_the_next_load_ends_the_same(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Interrupt test: the staged rows and the chunks written so far are in the load's one transaction."""
    from omop import load as L

    monkeypatch.setenv("TB_OMOP_LOAD_CHUNK", "40")
    by = {"Patient": list(_Patients(20, 0, "Patient")), "Condition": list(_Patients(20, 6, "Condition"))}
    db = _connect(db_url, "omopcut")
    try:
        L.load_batch(db, "feed", SNAP, by, tz=TZ)
        before = _dump(db)
        night2 = {"Patient": by["Patient"], "Condition": by["Condition"][5:]}
        real = L._write
        calls = [0]

        def cut(*a: Any, **k: Any) -> Any:
            calls[0] += 1
            if calls[0] == 3:
                raise KeyboardInterrupt("the process was stopped")
            return real(*a, **k)

        monkeypatch.setattr(L, "_write", cut)
        with pytest.raises(KeyboardInterrupt):
            L.load_batch(db, "feed", SNAP2, night2, tz=TZ)
        assert calls[0] == 3  # cut after two chunks were written
        assert _dump(db) == before
        monkeypatch.setattr(L, "_write", real)
        rep = L.load_batch(db, "feed", SNAP2, night2, tz=TZ)
        assert rep.tombstoned == 5 and rep.inserted == 0
    finally:
        db.close()


def test_the_locks_a_load_holds_do_not_grow_with_its_chunks(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The review: every chunk made its temporary tables again, and a table made in a transaction keeps its lock to
    the commit; site A at chunk 8 ran PostgreSQL's shared lock table out (and another session's migration with it).
    The locks the load's transaction holds before its tombstones are the same for 10 chunks and for 100."""
    from omop import load as L

    by = {"Patient": list(_Patients(50, 0, "Patient")), "Condition": list(_Patients(50, 20, "Condition"))}
    held: dict[str, int] = {}
    real = L._tombstone

    def count(tx: Any, *a: Any, **k: Any) -> Any:
        held[os.environ["TB_OMOP_LOAD_CHUNK"]] = int(
            tx.fetchval("SELECT count(*) FROM pg_locks WHERE pid = pg_backend_pid()")
        )
        return real(tx, *a, **k)

    monkeypatch.setattr(L, "_tombstone", count)
    for chunk, prefix in (("105", "omoplocka"), ("11", "omoplockb")):  # 1,050 records: 10 chunks, then about 100
        monkeypatch.setenv("TB_OMOP_LOAD_CHUNK", chunk)
        db = _connect(db_url, prefix)
        try:
            L.load_batch(db, "feed", SNAP, by, tz=TZ)
        finally:
            db.close()
    assert held["11"] <= held["105"] + 5, held
