"""Durable steps and the transactional outbox under crashes (spec v4 §11.0, FR-WF-1, FR-WF-3, FR-WF-9; S1-05).

The kill loop runs a three-step workflow for many jobs and delivers the outbox through a MailHog-like sink, while a
seeded chaos source kills the "process" at every boundary: inside step bodies, between a step body and its commit,
after a claim, before and after the transport's external effect, inside the mark transaction and after it. Each
kill drops the dispatcher and its connection, advances the clock past the lease and starts a new incarnation from
the database file. The assertion is exactly one delivery per outbox row.
"""

from __future__ import annotations

import functools
import multiprocessing
import os
import random
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from orchestrator.db_pg import (
    OutboxMessage,
    SqliteBackend,
    StepBusy,
    StepResult,
    StepStore,
    canonical_json,
    open_backend,
    step_input_hash,
)
from orchestrator.outbox import (
    DELIVERED,
    PENDING,
    UNCERTAIN,
    Delivery,
    DeliveryStatus,
    Dispatcher,
    TransportRejected,
    outbox_rows,
)

LEASE_MS = 10_000
T0 = datetime(2026, 10, 25, 9, 0, tzinfo=ZoneInfo("Asia/Taipei"))


class SimulatedCrash(BaseException):
    """A kill -9 stand-in: not an Exception, so no handler in the code under test swallows it."""


class FakeClock:
    def __init__(self, start: datetime = T0) -> None:
        self.t = start

    def __call__(self) -> datetime:
        return self.t

    def advance(self, ms: int) -> None:
        self.t += timedelta(milliseconds=ms)


class Chaos:
    def __init__(self, rng: random.Random, p: float) -> None:
        self.rng = rng
        self.p = p
        self.kills: dict[str, int] = {}

    def maybe(self, point: str) -> None:
        if self.p and self.rng.random() < self.p:
            self.kills[point] = self.kills.get(point, 0) + 1
            raise SimulatedCrash(point)


class MailSink:
    """MailHog stand-in persisted in its own SQLite file, so it outlives dispatcher restarts. It records every
    delivery (duplicates included) and can be searched by idempotency key, like a Message-ID search."""

    def __init__(self, path: Path, chaos: Chaos | None = None, probe_supported: bool = True) -> None:
        self.path = path
        self.chaos = chaos
        self.probe_supported = probe_supported
        con = sqlite3.connect(path)
        con.execute(
            "CREATE TABLE IF NOT EXISTS deliveries (id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT,"
            " message_id TEXT, recipient TEXT, payload TEXT)"
        )
        con.commit()
        con.close()

    def send(self, d: Delivery) -> str:
        if self.chaos:
            self.chaos.maybe("transport_before_effect")
            if self.chaos.rng.random() < 0.05:
                raise TransportRejected("421 try again later")
        con = sqlite3.connect(self.path)
        con.execute(
            "INSERT INTO deliveries (idempotency_key, message_id, recipient, payload) VALUES (?, ?, ?, ?)",
            (d.idempotency_key, d.message_id, d.recipient, canonical_json(d.payload)),
        )
        con.commit()
        con.close()
        if self.chaos:
            self.chaos.maybe("transport_after_effect")  # the answer is lost with the process
            if self.chaos.rng.random() < 0.05:
                raise TimeoutError("SMTP answer lost")  # the answer is lost, the process lives
        return f"250 queued as {d.idempotency_key[:12]}"

    def probe(self, idempotency_key: str) -> DeliveryStatus:
        if not self.probe_supported:
            return DeliveryStatus.UNKNOWN
        return DeliveryStatus.DELIVERED if self.count(idempotency_key) else DeliveryStatus.NOT_DELIVERED

    def count(self, idempotency_key: str | None = None) -> int:
        con = sqlite3.connect(self.path)
        if idempotency_key is None:
            n = con.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]
        else:
            n = con.execute("SELECT COUNT(*) FROM deliveries WHERE idempotency_key = ?", (idempotency_key,)).fetchone()[
                0
            ]
        con.close()
        return int(n)

    def per_key(self) -> dict[str, int]:
        con = sqlite3.connect(self.path)
        rows = con.execute("SELECT idempotency_key, COUNT(*) FROM deliveries GROUP BY idempotency_key").fetchall()
        con.close()
        return {k: int(n) for k, n in rows}


STEPS = ("parse", "count", "reply")


def run_workflow(store: StepStore, job_id: str, chaos: Chaos, executions: dict[str, int]) -> None:
    """A three-step workflow: each step's external effect is an outbox row, never a call."""
    prev: dict[str, object] = {"job": job_id}
    for step in STEPS:
        ih = step_input_hash(prev, workflow="Demo", workflow_version="1", code_sha="c0de")

        def body(step: str = step, prev: dict[str, object] = prev) -> StepResult:
            executions[f"{job_id}/{step}"] = executions.get(f"{job_id}/{step}", 0) + 1
            chaos.maybe("step_body")
            out = {"step": step, "n": len(canonical_json(prev))}
            sends = [OutboxMessage("notice", f"crc-{job_id}@site.invalid", "email", {"job": job_id, "step": step})]
            if step == "reply":
                sends.append(OutboxMessage("copy", "office@site.invalid", "teams", {"job": job_id}, key="office"))
            chaos.maybe("before_step_commit")
            return StepResult(out, sends)

        prev = store.run_step(job_id, step, ih, body).output


def expected_rows(jobs: list[str]) -> int:
    return len(jobs) * (len(STEPS) + 1)


@dataclass
class LoopResult:
    rows: list[dict[str, Any]]
    steps: list[tuple[Any, ...]]
    sink: MailSink
    jobs: list[str]
    kills: dict[str, int]
    incarnations: int
    uncertain: list[dict[str, Any]]
    surfaced: list[str]
    executions: dict[str, int]


def kill_loop(
    tmp_path: Path, seed: int, p: float, probe: bool, n_jobs: int = 60, max_incarnations: int = 2000
) -> LoopResult:
    rng = random.Random(seed)
    chaos = Chaos(rng, p)
    clock = FakeClock()
    db = tmp_path / f"wf-{seed}.db"
    sink = MailSink(tmp_path / f"sink-{seed}.db", chaos, probe_supported=probe)
    jobs = [f"J{i:03d}" for i in range(n_jobs)]
    executions: dict[str, int] = {}
    surfaced: list[str] = []
    incarnations = 0
    while incarnations < max_incarnations:
        incarnations += 1
        backend = SqliteBackend(db)
        hook: Callable[[str, str], None] = lambda point, _m: chaos.maybe(point)  # noqa: E731
        try:
            store = StepStore(backend, owner=f"worker-{incarnations}", clock=clock, lease_ms=LEASE_MS)
            disp = Dispatcher(
                backend,
                {"email": sink, "teams": sink},
                owner=f"worker-{incarnations}",
                clock=clock,
                lease_ms=LEASE_MS,
                backoff_ms=1_000,
                max_attempts=1_000,
                hook=hook,
                on_uncertain=surfaced.append,
            )
            for job in jobs:
                run_workflow(store, job, chaos, executions)
            for _ in range(200):
                disp.dispatch_once(limit=7)
                clock.advance(2_000)  # lets back-off expire
                counts = disp.counts()
                if counts["pending"] == 0 and counts["claimed"] == 0:
                    break
            counts = disp.counts()
            if counts["pending"] == 0 and counts["claimed"] == 0:
                break
        except SimulatedCrash:
            pass
        finally:
            backend.close()
        clock.advance(LEASE_MS + 1)  # the restart takes longer than a lease
    backend = SqliteBackend(db)
    with backend.transaction() as tx:
        rows = outbox_rows(tx)
        steps = tx.fetchall("SELECT job_id, step, state FROM steps")
    disp = Dispatcher(backend, {"email": sink, "teams": sink}, owner="checker", clock=clock)
    uncertain = disp.uncertain()
    backend.close()
    return LoopResult(rows, steps, sink, jobs, chaos.kills, incarnations, uncertain, surfaced, executions)


@pytest.mark.req("FR-WF-1", "FR-WF-9")
@pytest.mark.parametrize("seed", [11, 2026, 90210])
def test_kill_loop_exactly_one_delivery_per_outbox_row(tmp_path: Path, seed: int) -> None:
    r = kill_loop(tmp_path, seed, p=0.04, probe=True)
    rows, sink, kills = r.rows, r.sink, r.kills
    # the chaos really hit every kind of boundary
    for point in ("step_body", "before_step_commit", "claimed", "before_send", "transport_after_effect", "in_mark"):
        assert kills.get(point, 0) > 0, (point, kills)
    assert len(rows) == expected_rows(r.jobs)  # no duplicate enqueue from replayed or re-run steps
    assert all(row["state"] == DELIVERED for row in rows), [row for row in rows if row["state"] != DELIVERED]
    per_key = sink.per_key()
    assert set(per_key) == {row["idempotency_key"] for row in rows}
    assert all(n == 1 for n in per_key.values()), {k: n for k, n in per_key.items() if n != 1}
    assert sink.count() == len(rows)
    assert len(r.steps) == len(r.jobs) * len(STEPS)
    assert all(s[2] == "done" for s in r.steps)
    assert all(n >= 1 for n in r.executions.values())  # bodies may re-run before commit; their effects did not
    assert r.uncertain == []


@pytest.mark.req("FR-WF-1")
def test_without_probe_never_resends_uncertain_rows(tmp_path: Path) -> None:
    """A channel that cannot answer "did it arrive?" turns every lost answer into ``uncertain``: never re-sent
    automatically, surfaced, and moved on only by a person."""
    r = kill_loop(tmp_path, 7, p=0.03, probe=False)
    rows, sink = r.rows, r.sink
    per_key = sink.per_key()
    assert all(n == 1 for n in per_key.values())  # at most one delivery, ever
    uncertain = r.uncertain
    assert uncertain, "the chaos should have produced lost answers"
    assert {u["msg_id"] for u in uncertain} <= set(r.surfaced)
    for row in rows:
        assert row["state"] in (DELIVERED, UNCERTAIN)
        if row["state"] == DELIVERED:
            assert per_key.get(row["idempotency_key"]) == 1
    # more dispatch rounds do not touch uncertain rows
    sink.chaos = None
    backend = SqliteBackend(tmp_path / "wf-7.db")
    clock = FakeClock(T0 + timedelta(days=1))
    disp = Dispatcher(backend, {"email": sink, "teams": sink}, owner="later", clock=clock)
    before = sink.count()
    disp.run_until_idle()
    assert sink.count() == before
    # a person decides: confirm one delivered (it is in the sink), explicitly resend one that is not
    in_sink = [u for u in uncertain if per_key.get(u["idempotency_key"])]
    not_in_sink = [u for u in uncertain if not per_key.get(u["idempotency_key"])]
    for u in in_sink:
        assert disp.resolve(u["msg_id"], "delivered", actor="research-office")
    for u in not_in_sink:
        assert disp.resolve(u["msg_id"], "resend", actor="research-office")
    disp.run_until_idle()
    assert disp.counts()[DELIVERED] == len(rows)
    assert all(n == 1 for n in sink.per_key().values())
    assert not disp.resolve(rows[0]["msg_id"], "resend", actor="x")  # only uncertain rows can be resolved
    backend.close()


# ----------------------------------------------------------------------------- real process kills
def _notify(i: int) -> StepResult:
    return StepResult({"i": i}, [OutboxMessage("notice", "a@site.invalid", "email", {"i": i})])


def _child(db: str, sink_path: str, incarnation: int, seed: int) -> None:  # pragma: no cover - runs in a fork
    rng = random.Random(seed * 1000 + incarnation)
    clock = FakeClock(T0 + timedelta(milliseconds=incarnation * (LEASE_MS + 1)))

    def hook(point: str, _msg: str) -> None:
        if rng.random() < 0.08:
            os._exit(137)

    class KillingSink(MailSink):
        def send(self, d: Delivery) -> str:
            hook("transport_before_effect", d.msg_id)
            receipt = super().send(d)
            hook("transport_after_effect", d.msg_id)
            return receipt

    backend = SqliteBackend(db)
    sink = KillingSink(Path(sink_path))
    disp = Dispatcher(backend, {"email": sink}, owner=f"proc-{incarnation}", clock=clock, lease_ms=LEASE_MS, hook=hook)
    disp.run_until_idle(limit=3)
    backend.close()
    os._exit(0)


@pytest.mark.req("FR-WF-1")
def test_process_kill_loop_exactly_once(tmp_path: Path) -> None:
    """The dispatcher process is killed with ``os._exit`` (no cleanup, no rollback handler) at random points."""
    db, sink_path = tmp_path / "wf.db", tmp_path / "sink.db"
    backend = SqliteBackend(db)
    store = StepStore(backend, owner="seed", clock=FakeClock())
    for i in range(30):
        store.run_step(
            f"K{i:02d}",
            "notify",
            "h",
            functools.partial(_notify, i),
        )
    backend.close()
    MailSink(sink_path)
    ctx = multiprocessing.get_context("fork")
    exits: list[int | None] = []
    for incarnation in range(1, 200):
        p = ctx.Process(target=_child, args=(str(db), str(sink_path), incarnation, 5))
        p.start()
        p.join(60)
        exits.append(p.exitcode)
        backend = SqliteBackend(db)
        disp = Dispatcher(backend, {}, owner="check", clock=FakeClock())
        counts = disp.counts()
        backend.close()
        if p.exitcode == 0 and counts[PENDING] == 0 and counts["claimed"] == 0:
            break
    assert 137 in exits and exits[-1] == 0
    per_key = MailSink(sink_path).per_key()
    backend = SqliteBackend(db)
    with backend.transaction() as tx:
        rows = outbox_rows(tx)
    backend.close()
    assert len(rows) == 30 and all(r["state"] == DELIVERED for r in rows)
    assert set(per_key) == {r["idempotency_key"] for r in rows}
    assert all(n == 1 for n in per_key.values())


# ----------------------------------------------------------------------------- step semantics
@pytest.mark.req("FR-WF-3")
def test_done_step_is_replayed_not_rerun(tmp_path: Path) -> None:
    backend = SqliteBackend(tmp_path / "s.db")
    store = StepStore(backend, owner="w1", clock=FakeClock())
    calls: list[int] = []

    def body() -> StepResult:
        calls.append(1)
        return StepResult({"b": [1, 2.5, "é"], "a": None}, [OutboxMessage("k", "r@x.invalid", "email", {"x": 1})])

    ih = step_input_hash({"q": 1}, workflow="W", workflow_version="2", code_sha="abc")
    first = store.run_step("J", "s", ih, body)
    again = StepStore(backend, owner="w2", clock=FakeClock()).run_step("J", "s", ih, body)
    assert calls == [1] and not first.replayed and again.replayed
    assert canonical_json(again.output) == canonical_json(first.output)
    assert again.msg_ids == first.msg_ids and len(first.msg_ids) == 1
    with backend.transaction() as tx:
        assert len(outbox_rows(tx)) == 1
    # a different input hash (new inputs, version, code or model) is a different step
    ih2 = step_input_hash({"q": 1}, workflow="W", workflow_version="3", code_sha="abc")
    ih3 = step_input_hash(
        {"q": 1}, workflow="W", workflow_version="2", code_sha="abc", model={"model_sha": "m1", "prompt": "p1"}
    )
    assert len({ih, ih2, ih3}) == 3
    store.run_step("J", "s", ih2, body)
    assert calls == [1, 1]
    backend.close()


@pytest.mark.req("FR-WF-9")
def test_step_lease_excludes_other_workers_until_expiry(tmp_path: Path) -> None:
    backend = SqliteBackend(tmp_path / "s.db")
    clock = FakeClock()
    a = StepStore(backend, owner="a", clock=clock, lease_ms=LEASE_MS)
    b = StepStore(backend, owner="b", clock=clock, lease_ms=LEASE_MS)

    def crash() -> StepResult:
        raise SimulatedCrash("worker a dies mid-step")

    with pytest.raises(SimulatedCrash):
        a.run_step("J", "s", "h", crash)
    with pytest.raises(StepBusy):
        b.run_step("J", "s", "h", lambda: StepResult({"by": "b"}))
    clock.advance(LEASE_MS + 1)
    out = b.run_step("J", "s", "h", lambda: StepResult({"by": "b"}))
    assert out.output == {"by": "b"}
    row = b.get("J", "s", "h")
    assert row is not None and row[0] == "done" and row[2] == 2  # attempts: a, then b
    backend.close()


@pytest.mark.req("FR-WF-1")
def test_rejections_back_off_then_fail(tmp_path: Path) -> None:
    class Refusing:
        sent = 0

        def send(self, d: Delivery) -> str:
            raise TransportRejected("550 mailbox unavailable")

        def probe(self, key: str) -> DeliveryStatus:
            return DeliveryStatus.NOT_DELIVERED

    backend = SqliteBackend(tmp_path / "s.db")
    clock = FakeClock()
    StepStore(backend, owner="w", clock=clock).run_step(
        "J", "s", "h", lambda: StepResult({}, [OutboxMessage("k", "r@x.invalid", "email", {})])
    )
    disp = Dispatcher(backend, {"email": Refusing()}, owner="d", clock=clock, max_attempts=3, backoff_ms=1000)
    assert disp.dispatch_once().retried
    assert not disp.dispatch_once().retried  # backing off: not yet due
    clock.advance(2_000)
    assert disp.dispatch_once().retried
    clock.advance(4_000)
    assert disp.dispatch_once().failed
    assert disp.counts()["failed"] == 1
    backend.close()


def test_open_backend_urls(tmp_path: Path) -> None:
    b = open_backend(f"sqlite://{tmp_path}/x.db")
    assert isinstance(b, SqliteBackend) and b.path == f"{tmp_path}/x.db"
    b.close()
    m = open_backend("sqlite:///:memory:")
    assert isinstance(m, SqliteBackend) and m.path == ":memory:"
    m.close()
    with pytest.raises(ValueError, match="unsupported"):
        open_backend("mysql://h/db")


# ----------------------------------------------------------------------------- PostgreSQL (optional)
@pytest.mark.req("FR-WF-1", "FR-WF-9")
@pytest.mark.skipif(not os.environ.get("TB_PG_DSN"), reason="set TB_PG_DSN to a disposable PostgreSQL database")
def test_postgres_backend_same_semantics(tmp_path: Path) -> None:
    pytest.importorskip("psycopg")
    backend = open_backend(os.environ["TB_PG_DSN"])
    with backend.transaction() as tx:
        tx.execute("DROP TABLE IF EXISTS steps")
        tx.execute("DROP TABLE IF EXISTS outbox")
    clock = FakeClock()
    store = StepStore(backend, owner="pg", clock=clock)
    for i in range(5):
        store.run_step(f"P{i}", "s", "h", functools.partial(_notify, i))
    sink = MailSink(tmp_path / "sink.db")
    disp = Dispatcher(backend, {"email": sink}, owner="pg-d", clock=clock)
    disp.run_until_idle()
    assert disp.counts()[DELIVERED] == 5 and all(n == 1 for n in sink.per_key().values())
    assert store.run_step("P0", "s", "h", lambda: StepResult({"i": -1})).replayed
    backend.close()
