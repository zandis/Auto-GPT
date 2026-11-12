"""T-112a (D-427, CR-067 first half, FIT-017 schema half): the ``dataops`` schema, the batch states of an ingest night
and the adapter's hook. One batch row per run; ``HELD`` is left only by a steward's accept or reject with a reason;
a batch row is never stored without its step and its audit event."""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path
from typing import Any

import psycopg
import pytest
from adapter.pipeline import night_event, run_ingest
from datacore.dataops import (
    FAILED,
    HELD,
    LANDED,
    LINE,
    MAPPED,
    PUBLISHED,
    REJECTED,
    STATES,
    VALIDATED,
    DataOps,
    DataOpsError,
    can_step,
    night_path,
)
from tb_common.audit import AuditFull, AuditLog

from tests.unit.test_dataflow_lake_p0 import _Bad, _cfg, _csv, _Lakes, _row

AT = "2026-11-11T02:00:00+09:00"


@pytest.fixture
def ops() -> Any:
    store = DataOps()
    yield store
    store.close()


def _audit(tmp_path: Path) -> AuditLog:
    return AuditLog(tmp_path / "audit", "UTC")


def _events(tmp_path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for f in sorted((tmp_path / "audit").glob("*.jsonl")) for x in f.read_text().splitlines()]


def _night(ops: DataOps, audit: Any, *, passed: bool = False, held: bool = True, snap: str = "2026-11-10") -> Any:
    batch, _rec = ops.record_night(audit, "ingest.held", source="csv", snapshot=snap, passed=passed, held=held,
                                   by="adapter", at=AT, actor="adapter", detail={"gate": {"outcome": "held"}})  # fmt: skip
    return batch


# ------------------------------------------------------------------------------------------- the state machine
def test_the_legal_steps_and_the_refused_ones() -> None:
    for a, b in pairwise(LINE):
        assert can_step(a, b) is None
    for s in LINE[:-1]:
        assert can_step(s, HELD) is None and can_step(s, FAILED) is None
    assert can_step(HELD, PUBLISHED) is None and can_step(HELD, REJECTED) is None
    assert can_step(LANDED, PUBLISHED) == "LANDED -> PUBLISHED is not a step"
    assert can_step(VALIDATED, LANDED) is not None  # never backwards
    for end in (PUBLISHED, FAILED, REJECTED):
        assert all(can_step(end, s) == f"{end} is final" for s in STATES)
    assert can_step("DONE", LANDED) is not None
    assert night_path(True, False) == LINE
    assert night_path(False, True) == (LANDED, HELD) and night_path(False, False) == (LANDED, FAILED)


def test_advance_walks_the_line_and_refuses_a_jump_and_a_held_night(ops: DataOps, tmp_path: Path) -> None:
    audit = _audit(tmp_path)
    b = _night(ops, audit, held=False)  # LANDED -> FAILED: final
    with pytest.raises(DataOpsError, match="FAILED is final"):
        ops.advance(audit, b.id, LANDED, by="adapter", at=AT)
    # a batch on the line, made by hand to step through it
    with ops.db.transaction() as tx:
        bid = tx.fetchval("INSERT INTO batch (source, snapshot, attempt, state, seq, started_at, changed_at, "
                          "changed_by) VALUES ('csv', '2026-11-09', 1, 'LANDED', 1, ?, ?, 'adapter') RETURNING id",
                          (AT, AT))  # fmt: skip
        tx.execute("INSERT INTO batch_step (batch, seq, new, who, at, audit_event, audit_ref) "
                   "VALUES (?, 1, 'LANDED', 'adapter', ?, 'ingest.held', 'x')", (bid, AT))  # fmt: skip
    with pytest.raises(DataOpsError, match="LANDED -> MAPPED is not a step"):
        ops.advance(audit, bid, MAPPED, by="adapter", at=AT)
    ops.advance(audit, bid, VALIDATED, by="adapter", at=AT)
    held = ops.advance(audit, bid, HELD, by="adapter", at=AT, reason="validation over the limit")
    assert held.state == HELD and held.seq == 3
    with pytest.raises(DataOpsError, match="left only by a steward"):
        ops.advance(audit, bid, PUBLISHED, by="adapter", at=AT)
    assert [s["new"] for s in ops.steps(bid)] == [LANDED, VALIDATED, HELD]


# ------------------------------------------------------------------------------------------- the steward's decision
def test_reject_keeps_the_previous_snapshot_and_accept_promotes(ops: DataOps, tmp_path: Path) -> None:
    audit = _audit(tmp_path)
    promoted: list[str] = []
    a, b = _night(ops, audit, snap="2026-11-08"), _night(ops, audit, snap="2026-11-09")
    assert [x.state for x in ops.held()] == [HELD, HELD]
    rej = ops.decide(audit, a.id, "reject", by="steward1", at=AT, reason="lab table empty at the source",
                     promote=lambda x: promoted.append(x.snapshot))  # fmt: skip
    assert rej.state == REJECTED and promoted == []  # reject never runs the promotion: CURRENT stays
    acc = ops.decide(audit, b.id, "accept", by="steward1", at=AT, reason="drop confirmed with the HIS team",
                     promote=lambda x: promoted.append(x.snapshot))  # fmt: skip
    assert acc.state == PUBLISHED and promoted == ["2026-11-09"]
    last = _events(tmp_path)[-1]
    assert last["event"] == "dataops.decide" and last["actor"] == "steward1"
    assert last["detail"]["decision"] == "accept" and last["detail"]["reason"] == "drop confirmed with the HIS team"
    step = ops.steps(b.id)[-1]
    assert (step["old"], step["new"], step["who"], step["audit_ref"]) == (HELD, PUBLISHED, "steward1", last["hash"])
    with pytest.raises(DataOpsError, match="not HELD"):
        ops.decide(audit, b.id, "reject", by="steward1", at=AT, reason="again")


def test_a_decision_needs_a_person_a_reason_and_a_known_word(ops: DataOps, tmp_path: Path) -> None:
    audit = _audit(tmp_path)
    b = _night(ops, audit)
    for kw, why in (({"decision": "accept", "by": "s", "reason": " "}, "reason"),
                    ({"decision": "accept", "by": "", "reason": "r"}, "by"),
                    ({"decision": "publish", "by": "s", "reason": "r"}, "decision")):  # fmt: skip
        with pytest.raises(DataOpsError) as err:
            ops.decide(audit, b.id, kw["decision"], by=kw["by"], at=AT, reason=kw["reason"])
        assert err.value.why == why
    assert ops.batch(b.id).state == HELD  # type: ignore[union-attr]


def test_a_failed_promotion_leaves_the_night_held_and_the_accept_in_the_audit(ops: DataOps, tmp_path: Path) -> None:
    """D-489 (review of T-723, HIGH-2): the accept is recorded before the publish starts and its end after it, so a
    publish whose end nobody read leaves a trace. (Before: nothing was written when the promotion failed.) The row
    stays HELD and gets no step."""
    audit = _audit(tmp_path)
    b = _night(ops, audit)
    n = len(_events(tmp_path))

    def boom(_b: Any) -> None:
        raise RuntimeError("lake refused")

    with pytest.raises(RuntimeError):
        ops.decide(audit, b.id, "accept", by="steward1", at=AT, reason="ok", promote=boom)
    assert ops.batch(b.id).state == HELD and len(ops.steps(b.id)) == 2  # type: ignore[union-attr]
    said = [e["detail"] for e in _events(tmp_path)[n:]]
    assert [(d["decision"], d["phase"], d.get("outcome")) for d in said] == [
        ("accept", "started", None), ("accept", "ended", "unknown")]  # fmt: skip


# ------------------------------------------------------------------------------------------- one transaction
def test_a_batch_row_without_its_step_is_refused(ops: DataOps) -> None:
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation), ops.db.transaction() as tx:
        tx.execute("INSERT INTO batch (source, snapshot, attempt, state, seq, started_at, changed_at, changed_by) "
                   "VALUES ('csv', '2026-11-07', 1, 'PUBLISHED', 1, ?, ?, 'someone')", (AT, AT))  # fmt: skip
    assert ops.batches() == []


def test_an_audit_that_refuses_stores_nothing(ops: DataOps) -> None:
    class Full:
        def append(self, event: str, **fields: Any) -> dict[str, Any]:
            raise AuditFull("disk full")

    with pytest.raises(AuditFull):
        _night(ops, Full())
    assert ops.batches() == []


def test_the_trail_is_append_only(ops: DataOps, tmp_path: Path) -> None:
    b = _night(ops, _audit(tmp_path))
    with pytest.raises(psycopg.errors.InsufficientPrivilege), ops.db.transaction() as tx:
        tx.execute("UPDATE batch_step SET who = 'x' WHERE batch = ?", (b.id,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege), ops.db.transaction() as tx:
        tx.execute("DELETE FROM batch_step WHERE batch = ?", (b.id,))


# ------------------------------------------------------------------------------------------- the adapter's hook
def test_every_night_has_a_row_and_one_over_the_validation_limit_is_held(tmp_path: Path) -> None:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    _csv(tmp_path / "n1", [_row("D1", "2026-09-01")])
    assert run_ingest(cfg, "csv", str(tmp_path / "n1"), snapshot="2026-10-01", load_fhir=False, validate=False).passed
    _csv(tmp_path / "n2", [_row("D1", "2026-09-01"), _row("D9", "2026-10-01")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "n2"), snapshot="2026-10-02", load_fhir=False,
                     validator=_Bad())  # type: ignore[arg-type]  # fmt: skip
    assert rep.held and lakes.lake.current() == "2026-10-01"  # D-149: CURRENT unchanged
    ops = DataOps()
    try:
        rows = ops.batches()
        assert [(r.snapshot, r.state, r.attempt) for r in rows] == [("2026-10-01", PUBLISHED, 1),
                                                                    ("2026-10-02", HELD, 1)]  # fmt: skip
        assert [s["new"] for s in ops.steps(rows[0].id)] == list(LINE)
        assert rows[1].detail["gate"]["outcome"]  # why it was held, for the steward (no row text)
        events = [e for e in _events(tmp_path) if e["event"].startswith("ingest.")]
        assert [e["event"] for e in events] == ["ingest.done", "ingest.held"]
        assert events[1]["detail"]["batch"] == {"id": rows[1].id, "attempt": 1, "state": HELD}
        # T-723 (D-489): the row is opened at the start (its own ``dataops.step`` event) and closed by the night's
        steps = ops.steps(rows[1].id)
        assert [(s["new"], s["audit_event"]) for s in steps] == [("LANDED", "dataops.step"), (HELD, "ingest.held")]
        assert steps[1]["audit_ref"] == events[1]["hash"]
        # a re-run of the held night is the next attempt; the held one stays for the steward
        rep = run_ingest(cfg, "csv", str(tmp_path / "n2"), snapshot="2026-10-02", load_fhir=False, validate=False)
        assert rep.passed
        assert [(r.state, r.attempt) for r in ops.batches(source="csv")][1:] == [(HELD, 1), (PUBLISHED, 2)]
    finally:
        ops.close()


def test_an_unreachable_store_still_writes_the_nights_event(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg.db_url = "postgresql://127.0.0.1:1/tb_nodb?connect_timeout=1"
    night_event(cfg, "ingest.failed", snapshot="2026-10-03", source="csv", passed=False, held=False,
                actor="adapter", detail={"error": "OSError"})  # fmt: skip
    ev = _events(tmp_path)[-1]
    assert ev["event"] == "ingest.failed" and ev["detail"] == {"error": "OSError", "batch": None}
