"""D-648: the alliance store keeps a record of every table it stored, written with the table.

A re-run of a COHORT MERGE rebuilds the alliance tables as they stood when the merge ran. Until now it worked out
what each earlier merge had stored from how that job ended (D-666), and a merge that was stopped while it ran left
no answer: every later merge's re-run then said it could not. The record is written in the transaction that stores
the table, so it says what the store holds after every ending of a merge: each error the merge can raise, at each
table; a cancel; a kill between two tables. The job's end adds nothing to it."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from orchestrator import core
from orchestrator import db as orch_db
from orchestrator.clients import StepFailed
from orchestrator.core import Cancelled, Orchestrator, Services
from orchestrator.db import JobDB
from orchestrator.scenarios import cohort
from tb_common.audit import AuditLog
from tb_common.config import Config, load_env, load_settings
from tb_common.crypto import sha256_bytes
from tb_common.db import DatabaseError
from tb_common.objstore import FsStore
from tb_common.routing import RoutingViolation
from tb_contracts import JobCreate, JobFile, SendRequest, SendResult

ROOT = Path(__file__).resolve().parents[2]
SENDER = "crc1@hospa.test"
SITES = ("HOSP-B", "HOSP-C", "HOSP-D")
COLS = ("site_id", "disease", "quarter", "criterion_id", "criterion_label", "n", "n_contactable", "definition_version")


def _table(site: str, n: int = 12, quarter: str = "2026Q3") -> list[dict[str, Any]]:
    return [
        {"site_id": site, "disease": "gout", "quarter": quarter, "criterion_id": f"GOUT-COH-INC-0{i}",
         "criterion_label": "痛風の診断", "n": n + i, "n_contactable": "<5", "definition_version": "GOUT-COH@1.0.0"}
        for i in (1, 2)
    ]  # fmt: skip


class _Mail:
    def __init__(self) -> None:
        self.fail: BaseException | None = None

    def send(self, req: SendRequest) -> SendResult:
        if self.fail is not None:
            raise self.fail
        return SendResult(message_id="<1@t>", sent_to=req.to, encrypted=bool(req.encrypt))


class _Box:
    """An orchestrator with the real COHORT scenario on a store schema of its own."""

    n = 0

    def __init__(self, tmp_path: Path, schema: str | None = None) -> None:
        _Box.n += 1
        self.dir = tmp_path / f"box{_Box.n}"
        cfg = Config(
            env=load_env(dotenv=tmp_path / "x.env", environ={}),
            settings=load_settings(ROOT / "deploy/settings.example.yaml"),
        )
        self.mail = _Mail()
        self.db = JobDB(schema=schema or f"orch_rec_{_Box.n}")
        self.store = FsStore(tmp_path / "obj")
        services = Services(lake=None, parser=None, compiler=None, mail=self.mail, llm=None, verifier=None)  # type: ignore[arg-type]
        self.orch = Orchestrator(
            cfg, self.db, self.store, AuditLog(self.dir / "audit"), services, {"COHORT": cohort.run},
            self.dir / "rulesets", self.dir, today=lambda: date(2026, 11, 13), workers=0, async_notify=False,
        )  # fmt: skip

    def merge(self, tables: list[list[dict[str, Any]]]) -> str:
        files = []
        for i, rows in enumerate(tables):
            data = cohort.to_csv(rows)
            key = f"inputs/{_Box.n}-{len(self.db.find(type_='COHORT'))}/t{i}.csv"
            self.store.put(key, data)
            files.append(JobFile(filename=f"cohort_table_{i}.csv", sha256=sha256_bytes(data), minio_key=key))
        req = JobCreate(type="COHORT", ruleset="MERGE", requested_by=SENDER, inputs=files)
        return self.orch.create(req, notify=False).job_id

    def held(self) -> dict[str, list[dict[str, Any]]]:
        """The alliance tables as the store holds them: every row, by site."""
        with self.db.tx() as tx:
            got = tx.fetchall(f"SELECT {', '.join(COLS)} FROM cohort_tables ORDER BY seq")
        out: dict[str, list[dict[str, Any]]] = {}
        for r in got:
            d = dict(zip(COLS, r, strict=True))
            d["n"], d["n_contactable"] = json.loads(d["n"]), json.loads(d["n_contactable"])
            out.setdefault(d["site_id"], []).append(d)
        return out


@pytest.fixture
def box(tmp_path: Path) -> Iterator[Callable[[], _Box]]:
    made: list[_Box] = []

    def make() -> _Box:
        made.append(_Box(tmp_path))
        return made[-1]

    yield make
    for b in made:
        b.db.drop()


def _canon(held: dict[str, list[dict[str, Any]]]) -> list[str]:
    return sorted(json.dumps(r, sort_keys=True, ensure_ascii=False) for rows in held.values() for r in rows)


def _record_is_the_store(b: _Box, job_id: str, tmp_path: Path) -> list[dict[str, Any]]:
    """The record of the one job that ran says what the store holds: the same sites, the same tables (by hash), and
    the record alone, replayed into an empty store, gives the same rows."""
    record = b.db.cohort_stored(job_id)
    assert record is not None  # the job is from after the record began
    held = b.held()
    last = {r["site_id"]: r for r in record}  # a table stored twice (a restart): the later one stands
    assert set(last) == set(held)
    for site, rows in held.items():
        assert last[site]["table_sha256"] == orch_db.cohort_table_hash(rows), site
    scratch = JobDB(schema=f"{b.db.schema}_replay")
    try:
        assert cohort.replay_stored(b.db, scratch, job_id) is True
        with scratch.tx() as tx:
            got = tx.fetchall(f"SELECT {', '.join(COLS)}, received_from, job_id FROM cohort_tables ORDER BY seq")
        with b.db.tx() as tx:
            want = tx.fetchall(f"SELECT {', '.join(COLS)}, received_from, job_id FROM cohort_tables ORDER BY seq")
        assert sorted(map(tuple, got)) == sorted(map(tuple, want))
    finally:
        scratch.drop()
    return record


# every error the merge can meet, by where it stops: an error of the scenario's own, a programming error, the
# object store's, the old reader's, the database's, a routing refusal, a cancel, and the process dying
ERRORS: tuple[Callable[[], BaseException], ...] = (
    lambda: StepFailed("running", "stopped"),
    lambda: RuntimeError("stopped"),
    lambda: KeyError("inputs/gone"),
    lambda: OSError("disk"),
    lambda: UnicodeDecodeError("utf-8", b"\xa4", 0, 1, "invalid start byte"),
    lambda: DatabaseError("connection lost"),
    lambda: RoutingViolation("refused"),
    lambda: Cancelled("cancelled"),
    KeyboardInterrupt,
    lambda: SystemExit(1),
)
#: where a merge can stop, and how many of its three tables the store then holds (``k``: the table it stops at)
PER_TABLE = {"read": 0, "parse": 0, "refusal": 0, "stored": 1}
AFTER_TABLES = ("rows", "publish", "mail")


def _fault(b: _Box, mp: pytest.MonkeyPatch, where: str, k: int, exc: BaseException) -> None:
    """Make the merge stop with ``exc`` at ``where``, at its table number ``k`` (0, 1, 2)."""
    seen = {"n": 0}

    def at(real: Callable[..., Any], after: bool = False) -> Callable[..., Any]:
        def wrapped(*a: Any, **kw: Any) -> Any:
            mine = seen["n"] == k
            seen["n"] += 1
            if mine and not after:
                raise exc
            out = real(*a, **kw)
            if mine:
                raise exc
            return out

        return wrapped

    if where == "read":
        mp.setattr(b.store, "get", at(b.store.get))
    elif where == "parse":
        mp.setattr(cohort, "parse_csv", at(cohort.parse_csv))
    elif where == "refusal":
        mp.setattr(cohort, "merge_refusal", at(cohort.merge_refusal))
    elif where == "stored":
        mp.setattr(b.db, "cohort_store", at(b.db.cohort_store, after=True))
    elif where == "rows":
        k = 0
        mp.setattr(b.db, "cohort_rows", at(b.db.cohort_rows))
    elif where == "publish":
        k = 0
        mp.setattr(core.Ctx, "publish", at(core.Ctx.publish))
    elif where == "mail":
        b.mail.fail = exc
    else:  # pragma: no cover
        raise AssertionError(where)


def _run(b: _Box, job_id: str) -> None:
    try:
        b.orch.run(job_id)
    except (KeyboardInterrupt, SystemExit):
        pass  # the process died: nothing after this line of the merge ran, and nobody ended the job
    except Exception:
        assert b.mail.fail is not None  # only a mail server that fails the "failed" mail too gets this far


@pytest.mark.parametrize("where", [*PER_TABLE, *AFTER_TABLES])
def test_after_every_ending_of_a_merge_the_record_says_what_the_store_holds(
    where: str, box: Callable[[], _Box], tmp_path: Path
) -> None:
    for k in range(3) if where in PER_TABLE else (0,):
        for make in ERRORS:
            exc = make()
            b = box()
            job_id = b.merge([_table(s) for s in SITES])
            with pytest.MonkeyPatch.context() as mp:
                _fault(b, mp, where, k, exc)
                _run(b, job_id)
            record = _record_is_the_store(b, job_id, tmp_path)
            expected = k + PER_TABLE[where] if where in PER_TABLE else 3
            assert [r["site_id"] for r in record] == list(SITES[:expected]), (where, k, type(exc).__name__)
            job = b.db.get(job_id)
            assert job is not None
            if where != "mail" or isinstance(exc, (KeyboardInterrupt, SystemExit)):
                assert job.state != "done", (where, k, type(exc).__name__)


def test_a_merge_that_ends_well_and_one_refused_at_the_start_are_recorded_as_they_stored(
    box: Callable[[], _Box], tmp_path: Path
) -> None:
    b = box()
    done = b.merge([_table(s) for s in SITES])
    b.orch.run(done)
    assert b.db.get(done).state == "done"  # type: ignore[union-attr]
    assert [r["site_id"] for r in _record_is_the_store(b, done, tmp_path)] == list(SITES)
    c = box()
    bad = c.merge([[{**r, "quarter": "not a quarter"} for r in _table("HOSP-B")]])
    c.orch.run(bad)
    assert c.db.get(bad).state == "failed"  # type: ignore[union-attr]
    assert c.db.cohort_stored(bad) == [] and c.held() == {}  # after the record began, and it stored nothing


def test_a_cancel_asked_for_while_the_tables_are_read_ends_the_job_with_the_record_whole(
    box: Callable[[], _Box], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = box()
    job_id = b.merge([_table(s) for s in SITES])
    real = b.db.cohort_store

    def store_then_cancel(*a: Any, **kw: Any) -> None:
        real(*a, **kw)
        b.db.request_cancel(job_id)

    monkeypatch.setattr(b.db, "cohort_store", store_then_cancel)
    b.orch.run(job_id)
    job = b.db.get(job_id)
    assert job is not None and job.state == "failed" and job.error is not None and job.error.step == "cancelled"
    # a merge looks for a cancel when it changes state, so it stops after its last table: all three are stored
    assert [r["site_id"] for r in _record_is_the_store(b, job_id, tmp_path)] == list(SITES)


def test_a_merge_killed_between_two_tables_and_run_again_records_both_runs(
    box: Callable[[], _Box], tmp_path: Path
) -> None:
    b = box()
    job_id = b.merge([_table(s) for s in SITES])
    with pytest.MonkeyPatch.context() as mp:
        _fault(b, mp, "read", 1, KeyboardInterrupt())
        _run(b, job_id)
    job = b.db.get(job_id)
    assert job is not None and job.state == "running"  # nobody ended it
    assert [r["site_id"] for r in _record_is_the_store(b, job_id, tmp_path)] == ["HOSP-B"]
    b.orch.run(job_id)  # the box starts again and runs the unfinished job from its first table
    assert b.db.get(job_id).state == "done"  # type: ignore[union-attr]
    record = _record_is_the_store(b, job_id, tmp_path)
    assert [r["site_id"] for r in record] == ["HOSP-B", *SITES]
    assert [r["seq"] for r in record] == sorted(r["seq"] for r in record)


def test_the_table_and_its_record_are_stored_together_or_not_at_all(box: Callable[[], _Box], tmp_path: Path) -> None:
    b = box()
    first = b.merge([_table("HOSP-B", n=12)])
    b.orch.run(first)
    before = _canon(b.held())
    # a table whose rows cannot all be stored (the same criterion twice): its record must not stay, and the rows
    # it would have replaced must still be there
    twice = _table("HOSP-B", n=40)
    twice.append(dict(twice[0]))
    with pytest.raises(Exception, match="cohort_tables_pkey"):
        b.db.cohort_store(twice, "J-ROWS", SENDER)
    assert _canon(b.held()) == before
    assert b.db.cohort_stored_all() == b.db.cohort_stored(first)
    # a record that cannot be written (its table is gone): the rows must not stay either
    with b.db.tx() as tx:
        tx.execute("ALTER TABLE cohort_stored RENAME TO cohort_stored_away")
    with pytest.raises(Exception, match="cohort_stored"):
        b.db.cohort_store(_table("HOSP-B", n=40), "J-RECORD", SENDER)
    assert _canon(b.held()) == before


def test_the_record_keeps_the_table_itself_and_notices_a_changed_one(box: Callable[[], _Box]) -> None:
    b = box()
    rows = _table("HOSP-B", n=12)
    job_id = b.merge([rows])
    b.orch.run(job_id)
    b.db.cohort_store(_table("DEMO-A"), "J-OWN", "self:DEMO-A")  # the root's own run is recorded too
    (one,) = b.db.cohort_stored(job_id) or []
    assert one["rows"] == rows and one["received_from"] == SENDER and one["site_id"] == "HOSP-B"
    assert one["table_sha256"] == orch_db.cohort_table_hash(list(reversed(rows)))  # the order of the rows is not in it
    assert one["table_sha256"] != orch_db.cohort_table_hash([{**rows[0], "n": 99}, rows[1]])
    assert [(r["site_id"], r["job_id"]) for r in b.db.cohort_stored_all()] == [("HOSP-B", job_id), ("DEMO-A", "J-OWN")]
    with b.db.tx() as tx:
        tx.execute("UPDATE cohort_stored SET rows = replace(rows, '13', '31') WHERE job_id = ?", (job_id,))
    scratch = JobDB(schema=f"{b.db.schema}_x")
    try:
        with pytest.raises(cohort.RecordChanged, match=job_id):
            cohort.replay_stored(b.db, scratch, job_id)
        with scratch.tx() as tx:
            assert tx.fetchall("SELECT 1 FROM cohort_tables") == []
    finally:
        scratch.drop()


def test_a_later_merge_run_again_after_a_stopped_one_gives_what_its_first_run_gave(
    box: Callable[[], _Box], tmp_path: Path
) -> None:
    """A merge is killed after its first table; a later merge reads the store as that left it; then a site sends a
    new table. The later merge, run again on tables rebuilt from the record alone, publishes the same bytes."""
    b = box()
    stopped = b.merge([_table("HOSP-B", n=12), _table("HOSP-C", n=7), _table("HOSP-D", n=3)])
    with pytest.MonkeyPatch.context() as mp:
        _fault(b, mp, "read", 1, SystemExit(1))
        _run(b, stopped)
    later = b.merge([_table("HOSP-C", n=9)])
    b.orch.run(later)
    first = b.db.get(later)
    assert first is not None and first.state == "done" and first.outputs
    after = b.merge([_table("HOSP-B", n=30), _table("HOSP-D", n=5)])  # what a re-run must not see
    b.orch.run(after)

    again = _Box(tmp_path, schema=f"{b.db.schema}_rerun")
    try:
        for earlier in (stopped,):  # every COHORT job before the one run again, in order
            assert cohort.replay_stored(b.db, again.db, earlier) is True
        assert set(again.held()) == {"HOSP-B"}  # the stopped merge stored one table, and the record says which
        again.db.put(first.model_copy(update={"state": "received", "outputs": [], "error": None}), queued=False)
        second = again.orch.run(later)
        assert second.state == "done"
        assert [(o.filename, o.sha256) for o in second.outputs or []] == [
            (o.filename, o.sha256) for o in first.outputs or []
        ]
        data = again.store.get((second.outputs or [])[0].minio_key).decode("utf-8-sig")
        assert "HOSP-D" not in data and ",30," not in data
    finally:
        again.db.drop()


def test_a_job_from_before_the_record_has_none_and_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A box that ran merges before this release: those jobs have no record, which is not "stored nothing"."""
    schema = "orch_rec_before"
    with monkeypatch.context() as mp:
        mp.setattr(orch_db, "MIGRATIONS", orch_db.MIGRATIONS[:3])
        old = _Box(tmp_path, schema=schema)
        before = old.merge([_table("HOSP-B")])
        with old.db.tx() as tx:  # as the release before stored it
            tx.execute(
                "INSERT INTO cohort_tables (site_id, disease, quarter, criterion_id, definition_version, "
                "criterion_label, n, n_contactable, received_from, job_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("HOSP-B", "gout", "2026Q3", "C-1", "GOUT-COH@1.0.0", "x", "12", "0", SENDER, before),
            )
    new = _Box(tmp_path, schema=schema)  # this release starts on that store
    try:
        assert new.db.cohort_stored(before) is None
        scratch = JobDB(schema=f"{schema}_x")
        try:
            assert cohort.replay_stored(new.db, scratch, before) is False
        finally:
            scratch.drop()
        since = new.merge([_table("HOSP-C")])
        new.orch.run(since)
        assert [r["site_id"] for r in new.db.cohort_stored(since) or []] == ["HOSP-C"]
        assert new.db.cohort_stored("no such job") is None
    finally:
        new.db.drop()
