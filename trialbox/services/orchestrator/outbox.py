"""Transactional outbox dispatcher (spec v4 §11.0, FR-WF-1, FR-WF-9; sprint task S1-05).

Steps never call a channel. They enqueue outbox rows in the same transaction as their result
(:class:`orchestrator.db_pg.StepStore`). This dispatcher delivers the rows:

``pending → claimed → delivered``; ``claimed → pending`` (transport refused before accepting, retried with backoff);
``claimed → failed`` (refused ``max_attempts`` times); ``claimed → uncertain`` (the answer was lost and the transport
cannot say whether the message arrived).

States map onto §11.0 as ``claimed`` = ``sending``, ``delivered`` = ``sent``.

* **Claim with a lease.** Rows are claimed in a short transaction (``FOR UPDATE SKIP LOCKED`` on PostgreSQL) with a
  ``lease_until``. The lease is re-checked and renewed immediately before the send.
* **Idempotency key.** Every delivery carries the row's idempotency key and an RFC 5322 ``Message-ID`` derived from
  it, so the receiving side can de-duplicate and the dispatcher can ask it whether a message arrived.
* **Crash recovery.** A ``claimed`` row whose lease expired belongs to a dispatcher that died somewhere between the
  claim and the mark. The transport is probed by idempotency key: ``delivered`` marks it delivered (no resend),
  ``not_delivered`` returns it to ``pending``, anything else makes it ``uncertain``.
* **``uncertain`` is never re-sent automatically** (v1 D-86). Such rows are reported (:meth:`Dispatcher.uncertain`,
  ``on_uncertain``) and only a person's decision (:meth:`Dispatcher.resolve`) moves them on.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol

from tb_common import timeutil

from orchestrator.db_pg import SCHEMA, Clock, SqlBackend, Tx, apply_schema, epoch_ms

PENDING = "pending"
CLAIMED = "claimed"
DELIVERED = "delivered"
UNCERTAIN = "uncertain"
FAILED = "failed"
STATES = (PENDING, CLAIMED, DELIVERED, UNCERTAIN, FAILED)

Hook = Callable[[str, str], None]
Resolution = Literal["delivered", "resend", "failed"]


class DeliveryStatus(StrEnum):
    DELIVERED = "delivered"
    NOT_DELIVERED = "not_delivered"
    UNKNOWN = "unknown"


class TransportRejected(Exception):
    """The channel refused the message before accepting it (it was certainly not delivered); retry later."""


@dataclass(frozen=True)
class Delivery:
    msg_id: str
    idempotency_key: str
    message_id: str
    job_id: str
    kind: str
    recipient: str
    channel: str
    payload: dict[str, Any]
    payload_ref: str | None
    attempt: int


class Transport(Protocol):
    """A delivery channel (SMTP, Teams, LINE, a Hermes relay …)."""

    def send(self, delivery: Delivery) -> str:
        """Deliver; return the channel's receipt. Raise :class:`TransportRejected` when the channel certainly did
        not accept the message. Any other exception means the outcome is unknown."""
        ...

    def probe(self, idempotency_key: str) -> DeliveryStatus:
        """Ask the channel whether a message with this key arrived. Return ``UNKNOWN`` if it cannot tell."""
        ...


def message_id_for(idempotency_key: str, domain: str = "trialbox.invalid") -> str:
    return f"<{idempotency_key}@{domain}>"


@dataclass
class DispatchReport:
    delivered: list[str] = field(default_factory=list)
    retried: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    uncertain: list[str] = field(default_factory=list)
    recovered: list[str] = field(default_factory=list)


_COLS = (
    "msg_id, idempotency_key, job_id, kind, recipient, channel, payload, payload_ref, attempts, state, lease_owner,"
    " lease_until"
)


def _noop(_point: str, _msg_id: str) -> None:
    return None


class Dispatcher:
    """Delivers outbox rows through per-channel transports. One instance per worker process."""

    def __init__(
        self,
        backend: SqlBackend,
        transports: Mapping[str, Transport],
        owner: str,
        clock: Clock = timeutil.now,
        lease_ms: int = 60_000,
        max_attempts: int = 5,
        backoff_ms: int = 30_000,
        hook: Hook = _noop,
        on_uncertain: Callable[[str], None] | None = None,
        domain: str = "trialbox.invalid",
    ) -> None:
        self.backend = backend
        self.transports = dict(transports)
        self.owner = owner
        self.clock = clock
        self.lease_ms = lease_ms
        self.max_attempts = max_attempts
        self.backoff_ms = backoff_ms
        self.hook = hook
        self.on_uncertain = on_uncertain
        self.domain = domain
        apply_schema(backend, SCHEMA)

    # ------------------------------------------------------------------------------------------------ queries
    def counts(self) -> dict[str, int]:
        with self.backend.transaction() as tx:
            rows = tx.fetchall("SELECT state, COUNT(*) FROM outbox GROUP BY state")
        out = dict.fromkeys(STATES, 0)
        out.update({str(s): int(n) for s, n in rows})
        return out

    def uncertain(self) -> list[dict[str, Any]]:
        """Rows waiting for a person's decision (surfaced to the research office)."""
        with self.backend.transaction() as tx:
            rows = tx.fetchall(
                "SELECT msg_id, idempotency_key, job_id, kind, recipient, channel, attempts, last_error FROM outbox"
                " WHERE state = ? ORDER BY created_ms, msg_id",
                (UNCERTAIN,),
            )
        keys = ("msg_id", "idempotency_key", "job_id", "kind", "recipient", "channel", "attempts", "last_error")
        return [dict(zip(keys, r, strict=True)) for r in rows]

    # ------------------------------------------------------------------------------------------------ dispatch
    def dispatch_once(self, limit: int = 50) -> DispatchReport:
        report = DispatchReport()
        self.recover_expired(report)
        for row in self._claim(limit):
            self._deliver(row, report)
        return report

    def run_until_idle(self, max_rounds: int = 1000, limit: int = 50) -> DispatchReport:
        total = DispatchReport()
        for _ in range(max_rounds):
            r = self.dispatch_once(limit)
            for name in ("delivered", "retried", "failed", "uncertain", "recovered"):
                getattr(total, name).extend(getattr(r, name))
            if not (r.delivered or r.retried or r.recovered or r.failed or r.uncertain):
                break
        return total

    def _now_ms(self) -> int:
        return epoch_ms(self.clock())

    def _claim(self, limit: int) -> list[tuple[Any, ...]]:
        now_ms = self._now_ms()
        with self.backend.transaction() as tx:
            rows = tx.fetchall(
                f"SELECT {_COLS} FROM outbox WHERE state = ? AND next_attempt_ms <= ?"
                " ORDER BY created_ms, msg_id LIMIT ?" + self.backend.lock_suffix,
                (PENDING, now_ms, limit),
            )
            for r in rows:
                tx.execute(
                    "UPDATE outbox SET state = ?, lease_owner = ?, lease_until = ?, attempts = attempts + 1"
                    " WHERE msg_id = ? AND state = ?",
                    (CLAIMED, self.owner, now_ms + self.lease_ms, r[0], PENDING),
                )
        return [(*r[:8], int(r[8]) + 1, *r[9:]) for r in rows]

    def _delivery(self, row: tuple[Any, ...]) -> Delivery:
        msg_id, key, job_id, kind, recipient, channel, payload, payload_ref, attempts = row[:9]
        return Delivery(
            msg_id=msg_id,
            idempotency_key=key,
            message_id=message_id_for(key, self.domain),
            job_id=job_id,
            kind=kind,
            recipient=recipient,
            channel=channel,
            payload=dict(json.loads(payload)),
            payload_ref=payload_ref,
            attempt=int(attempts),
        )

    def _renew(self, msg_id: str) -> bool:
        """Re-check and extend our lease just before the external call."""
        now_ms = self._now_ms()
        with self.backend.transaction() as tx:
            return (
                tx.execute(
                    "UPDATE outbox SET lease_until = ? WHERE msg_id = ? AND state = ? AND lease_owner = ?"
                    " AND lease_until > ?",
                    (now_ms + self.lease_ms, msg_id, CLAIMED, self.owner, now_ms),
                )
                == 1
            )

    def _deliver(self, row: tuple[Any, ...], report: DispatchReport) -> None:
        d = self._delivery(row)
        self.hook("claimed", d.msg_id)
        transport = self.transports.get(d.channel)
        if transport is None:
            self._set_failed(d.msg_id, f"no transport for channel {d.channel}", report)
            return
        if not self._renew(d.msg_id):
            return  # lease lost while waiting; whoever holds the row now decides
        self.hook("before_send", d.msg_id)
        try:
            receipt = transport.send(d)
        except TransportRejected as e:
            self._retry_or_fail(d, f"rejected: {e}", report)
            return
        except Exception as e:  # the answer was lost: the message may or may not have arrived
            self._settle_unknown(d.msg_id, d.idempotency_key, transport, f"{type(e).__name__}: {e}", report)
            return
        self.hook("after_send", d.msg_id)
        self._mark_delivered(d.msg_id, receipt, report)

    def _mark_delivered(self, msg_id: str, receipt: str, report: DispatchReport) -> None:
        now = self.clock()
        with self.backend.transaction() as tx:
            n = tx.execute(
                "UPDATE outbox SET state = ?, delivered_at = ?, receipt = ?, lease_owner = NULL, lease_until = NULL"
                " WHERE msg_id = ? AND state IN (?, ?)",
                (DELIVERED, timeutil.iso(now), receipt, msg_id, CLAIMED, UNCERTAIN),
            )
            self.hook("in_mark", msg_id)
        if n:
            report.delivered.append(msg_id)
        self.hook("marked", msg_id)

    def _retry_or_fail(self, d: Delivery, error: str, report: DispatchReport) -> None:
        if d.attempt >= self.max_attempts:
            self._set_failed(d.msg_id, error, report)
            return
        next_ms = self._now_ms() + self.backoff_ms * (2 ** (d.attempt - 1))
        with self.backend.transaction() as tx:
            tx.execute(
                "UPDATE outbox SET state = ?, next_attempt_ms = ?, last_error = ?, lease_owner = NULL,"
                " lease_until = NULL WHERE msg_id = ? AND state = ?",
                (PENDING, next_ms, error, d.msg_id, CLAIMED),
            )
        report.retried.append(d.msg_id)

    def _set_failed(self, msg_id: str, error: str, report: DispatchReport) -> None:
        with self.backend.transaction() as tx:
            tx.execute(
                "UPDATE outbox SET state = ?, last_error = ?, lease_owner = NULL, lease_until = NULL"
                " WHERE msg_id = ? AND state = ?",
                (FAILED, error, msg_id, CLAIMED),
            )
        report.failed.append(msg_id)

    def _settle_unknown(self, msg_id: str, key: str, transport: Transport, error: str, report: DispatchReport) -> None:
        """The outcome of a send is unknown: ask the channel, and never guess."""
        try:
            status = transport.probe(key)
        except Exception:
            status = DeliveryStatus.UNKNOWN
        if status is DeliveryStatus.DELIVERED:
            self._mark_delivered(msg_id, "probe: delivered", report)
            return
        with self.backend.transaction() as tx:
            if status is DeliveryStatus.NOT_DELIVERED:
                n = tx.execute(
                    "UPDATE outbox SET state = ?, next_attempt_ms = ?, last_error = ?, lease_owner = NULL,"
                    " lease_until = NULL WHERE msg_id = ? AND state = ?",
                    (PENDING, self._now_ms(), error, msg_id, CLAIMED),
                )
                if n:
                    report.retried.append(msg_id)
                return
            n = tx.execute(
                "UPDATE outbox SET state = ?, last_error = ?, lease_owner = NULL, lease_until = NULL"
                " WHERE msg_id = ? AND state = ?",
                (UNCERTAIN, error, msg_id, CLAIMED),
            )
        if n:
            report.uncertain.append(msg_id)
            if self.on_uncertain is not None:
                self.on_uncertain(msg_id)

    def recover_expired(self, report: DispatchReport | None = None) -> list[str]:
        """Settle rows left ``claimed`` by a dispatcher whose lease expired (it crashed or stalled)."""
        report = report if report is not None else DispatchReport()
        now_ms = self._now_ms()
        with self.backend.transaction() as tx:
            rows = tx.fetchall(
                "SELECT msg_id, idempotency_key, channel FROM outbox WHERE state = ? AND lease_until <= ?"
                " ORDER BY created_ms, msg_id" + self.backend.lock_suffix,
                (CLAIMED, now_ms),
            )
            for msg_id, _key, _channel in rows:
                tx.execute(
                    "UPDATE outbox SET lease_owner = ?, lease_until = ? WHERE msg_id = ?",
                    (self.owner, now_ms + self.lease_ms, msg_id),
                )
        out: list[str] = []
        for msg_id, key, channel in rows:
            self.hook("recover", msg_id)
            transport = self.transports.get(channel)
            if transport is None:
                self._set_failed(msg_id, f"no transport for channel {channel}", report)
                continue
            self._settle_unknown(msg_id, key, transport, "lease expired before the delivery was recorded", report)
            report.recovered.append(msg_id)
            out.append(msg_id)
        return out

    # ------------------------------------------------------------------------------------------------ people
    def resolve(self, msg_id: str, decision: Resolution, actor: str) -> bool:
        """A person's decision on an ``uncertain`` row: confirm delivered, explicitly resend, or give up."""
        now = self.clock()
        target = {"delivered": DELIVERED, "resend": PENDING, "failed": FAILED}[decision]
        with self.backend.transaction() as tx:
            n = tx.execute(
                "UPDATE outbox SET state = ?, next_attempt_ms = ?, resolved_by = ?, resolution = ?,"
                " delivered_at = CASE WHEN ? = 'delivered' THEN ? ELSE delivered_at END"
                " WHERE msg_id = ? AND state = ?",
                (target, epoch_ms(now), actor, decision, target, timeutil.iso(now), msg_id, UNCERTAIN),
            )
        return n == 1


def outbox_rows(tx: Tx) -> list[dict[str, Any]]:
    """All rows (tests and the admin view)."""
    rows = tx.fetchall(f"SELECT {_COLS} FROM outbox ORDER BY created_ms, msg_id")
    keys = [c.strip() for c in _COLS.split(",")]
    return [dict(zip(keys, r, strict=True)) for r in rows]


__all__ = [
    "CLAIMED",
    "DELIVERED",
    "FAILED",
    "PENDING",
    "STATES",
    "UNCERTAIN",
    "Delivery",
    "DeliveryStatus",
    "DispatchReport",
    "Dispatcher",
    "Transport",
    "TransportRejected",
    "message_id_for",
    "outbox_rows",
]
