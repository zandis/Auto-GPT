"""mail-gateway state (schema ``mail`` of the trial database, D-126): intake log (idempotency + rate limit),
sent-message index (reply-to-thread matching) and the send keys, which are also the outbox (T-108c, D-401)."""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass

from tb_common.db import ENV, Database

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS intake (
  message_id TEXT PRIMARY KEY,
  sender TEXT NOT NULL,
  received_at TEXT NOT NULL,
  action TEXT NOT NULL,            -- job | reject | pending
  job_id TEXT,
  reason TEXT
);
CREATE INDEX IF NOT EXISTS intake_sender ON intake(sender, received_at);
CREATE TABLE IF NOT EXISTS sent (
  message_id TEXT PRIMARY KEY,
  job_id TEXT,
  subject TEXT NOT NULL,
  recipients TEXT NOT NULL,
  tag TEXT NOT NULL,
  sent_at TEXT NOT NULL
);
"""


# D-127 (review F-02): one row per idempotency key. "sending" is written before the transport is called and "sent"
# after it returned; a key found in "sending" belongs to a send that may or may not have left (a crash in between),
# so it is never sent again automatically: a person checks the mailbox and resolves it.
SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS send_keys (
  key TEXT PRIMARY KEY,
  state TEXT NOT NULL,
  message_id TEXT,
  job_id TEXT,
  result TEXT,
  at TEXT NOT NULL
)
"""


# T-108c (D-401, CR-085): the send keys are the outbox. A key leaves "sending" in the same call: "sent"; "queued" (the
# transport failed before the server could accept anything: DNS, connect, TLS, a 4xx; the gateway's dispatcher tries
# again with back-off); "failed" (refused for good, a 5xx, or too many tries); "uncertain" (the message may have
# left: never resent automatically). A "sending" row older than the stale limit belongs to a process that died; the
# dispatcher marks it "uncertain". A person ends "failed" and "uncertain" with ``trialbox mail resolve`` ("sent",
# "resend", "drop" to "dropped"). ``request`` holds the send request (attachments by object-store key) only while
# the mail may still be sent; it is cleared when the key is sent or dropped. ``intake.cmd``: the D-146 per-type
# limit counts one job type.
SCHEMA_V3 = """
ALTER TABLE send_keys ADD COLUMN IF NOT EXISTS request TEXT;
ALTER TABLE send_keys ADD COLUMN IF NOT EXISTS recipients TEXT;
ALTER TABLE send_keys ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE send_keys ADD COLUMN IF NOT EXISTS next_at TEXT;
ALTER TABLE send_keys ADD COLUMN IF NOT EXISTS last_error TEXT;
ALTER TABLE send_keys ADD COLUMN IF NOT EXISTS resolved_by TEXT;
CREATE INDEX IF NOT EXISTS send_keys_state ON send_keys(state, next_at);
ALTER TABLE intake ADD COLUMN IF NOT EXISTS cmd TEXT
"""
# Review L-4 (E2E P-10): ``hold_reason`` names why a queued key waits, as a code, so the start finds the keys held as
# "waits, not counted" (U-5) by it, not by the line a person reads.
SCHEMA_V4 = """
ALTER TABLE send_keys ADD COLUMN IF NOT EXISTS hold_reason TEXT
"""
# Review M-1: a key held under V3 has no code. The site-information holds of that time are the queued keys that name
# the page in their line (the page's gate line, always in English, or NO_RELAY); they get WAITS. The hold kept the
# key's earlier tries, as this release's hold does, so the count is not part of the test. Any other key keeps its NULL
# code and its retry time.
SCHEMA_V5 = """
UPDATE send_keys SET hold_reason = 'waits' WHERE state = 'queued' AND hold_reason IS NULL
AND last_error LIKE '%Information still needed%'
"""
MIGRATIONS = (SCHEMA_V1, SCHEMA_V2, SCHEMA_V3, SCHEMA_V4, SCHEMA_V5)
#: the ``hold_reason`` of a key held as "waits, not counted" (U-5, D-1280): the site information or the relay is needed
WAITS = "waits"

#: states a person still has to see: the dispatcher's queue and the two that wait for a decision
OPEN_STATES = ("sending", "queued", "uncertain", "failed")
#: a person's decision on a held key and the state it leads to
RESOLUTIONS = {"sent": "sent", "resend": "queued", "drop": "dropped"}


@dataclass(frozen=True)
class KeyRow:
    """One send key (no mail body: ``request`` is read only by :meth:`MailDB.take`)."""

    key: str
    state: str
    job_id: str | None
    message_id: str | None
    result: str | None
    recipients: str
    attempts: int
    next_at: str | None
    last_error: str | None
    at: str


class SendUncertain(RuntimeError):
    """A send with this key started and never finished: it may have reached the recipients. Never resent."""


class MailDB:
    def __init__(self, url: str | None = None) -> None:
        """``url``: the trial database (``TB_DB_URL`` when ``None``; :class:`~tb_common.db.DatabaseError` if unset)."""
        self.db = Database.connect(url or os.environ.get(ENV), "mail")
        self.db.migrate(list(MIGRATIONS))

    def close(self) -> None:
        self.db.close()

    def intake(self, message_id: str) -> tuple[str, str | None] | None:
        row = self.db.fetchone("SELECT action, job_id FROM intake WHERE message_id = ?", (message_id,))
        return (str(row[0]), row[1]) if row else None

    def record_intake(
        self,
        message_id: str,
        sender: str,
        at: str,
        action: str,
        job_id: str | None,
        reason: str | None = None,
        cmd: str | None = None,
    ) -> None:
        self.db.execute(
            "INSERT INTO intake (message_id, sender, received_at, action, job_id, reason, cmd) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT (message_id) DO UPDATE SET sender = EXCLUDED.sender, received_at = EXCLUDED.received_at, "
            "action = EXCLUDED.action, job_id = EXCLUDED.job_id, reason = EXCLUDED.reason, cmd = EXCLUDED.cmd",
            (message_id, sender, at, action, job_id, reason, cmd),
        )

    def jobs_since(self, sender: str, since_iso: str, cmd: str | None = None) -> int:
        """Jobs ``sender`` started since ``since_iso``; with ``cmd`` only that job type (D-146 J-02). A row from
        before the type was recorded counts for every type."""
        if cmd is None:
            n = self.db.fetchval(
                "SELECT count(*) FROM intake WHERE sender = ? AND action = 'job' AND received_at >= ?",
                (sender, since_iso),
                default=0,
            )
        else:
            n = self.db.fetchval(
                "SELECT count(*) FROM intake WHERE sender = ? AND action = 'job' AND received_at >= ? "
                "AND (cmd = ? OR cmd IS NULL)",
                (sender, since_iso, cmd.upper()),
                default=0,
            )
        return int(n)

    def rejects_since(self, sender: str, since_iso: str) -> int:
        """Refusals of mail from ``sender`` since ``since_iso`` (the cap on refusal replies to one address)."""
        return int(
            self.db.fetchval(
                "SELECT count(*) FROM intake WHERE sender = ? AND action = 'reject' AND received_at >= ?",
                (sender, since_iso),
                default=0,
            )
        )

    def sent_to_since(self, since_iso: str) -> Counter[str]:
        """Mails sent to each recipient since ``since_iso`` (the per-recipient limit, T-108c)."""
        rows = self.db.fetchall("SELECT recipients FROM sent WHERE sent_at >= ?", (since_iso,))
        return Counter(r for (rcpts,) in rows for r in str(rcpts).split(",") if r)

    def record_sent(
        self, message_id: str, job_id: str | None, subject: str, recipients: list[str], tag: str, at: str
    ) -> None:
        self.db.execute(
            "INSERT INTO sent (message_id, job_id, subject, recipients, tag, sent_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT (message_id) DO UPDATE SET job_id = EXCLUDED.job_id, subject = EXCLUDED.subject, "
            "recipients = EXCLUDED.recipients, tag = EXCLUDED.tag, sent_at = EXCLUDED.sent_at",
            (message_id, job_id, subject, ",".join(recipients), tag, at),
        )

    def claim_send(self, key: str, job_id: str | None, at: str) -> str | None:
        """Reserve ``key`` for a send. ``None``: go ahead. A JSON result: already sent (return it, send nothing).
        Raises :class:`SendUncertain` when an earlier send with this key never finished."""
        with self.db.transaction() as tx:
            n = tx.execute(
                "INSERT INTO send_keys (key, state, job_id, at) VALUES (?, 'sending', ?, ?) "
                "ON CONFLICT (key) DO NOTHING",
                (key, job_id, at),
            )
            if n == 1:
                return None
            row = tx.fetchone("SELECT state, result FROM send_keys WHERE key = ?", (key,))
        if row and row[0] == "sent":
            return str(row[1])
        raise SendUncertain(f"send {key[:12]} started earlier and did not finish: check the mailbox, then resolve it")

    def get(self, key: str) -> KeyRow | None:
        rows = self._rows("WHERE key = ?", (key,))
        return rows[0] if rows else None

    def open_keys(self) -> list[KeyRow]:
        """Every key that is not finished: queued, waiting for a person, or in flight (oldest first)."""
        marks = ",".join("?" * len(OPEN_STATES))
        return self._rows(f'WHERE state IN ({marks}) ORDER BY at COLLATE "C", key COLLATE "C"', OPEN_STATES)

    def counts(self) -> dict[str, int]:
        rows = self.db.fetchall("SELECT state, count(*) FROM send_keys GROUP BY state")
        out = dict.fromkeys(OPEN_STATES, 0)
        out.update({str(s): int(n) for s, n in rows if str(s) in OPEN_STATES})
        return out

    def _rows(self, where: str, params: tuple[object, ...]) -> list[KeyRow]:
        rows = self.db.fetchall(
            "SELECT key, state, job_id, message_id, result, COALESCE(recipients, ''), attempts, next_at, last_error, "
            f"at FROM send_keys {where}",
            params,
        )
        return [
            KeyRow(str(k), str(st), j, m, r, str(rc), int(n or 0), nx, err, str(at))
            for k, st, j, m, r, rc, n, nx, err, at in rows
        ]

    def finish_send(self, key: str, message_id: str, result_json: str, at: str) -> None:
        self.db.execute(
            "UPDATE send_keys SET state = 'sent', message_id = ?, result = ?, at = ?, request = NULL, next_at = NULL "
            "WHERE key = ?",
            (message_id, result_json, at, key),
        )

    def hold(
        self,
        key: str,
        state: str,
        *,
        request_json: str,
        message_id: str,
        result_json: str,
        recipients: list[str],
        attempts: int,
        next_at: str | None,
        error: str,
        at: str,
        reason: str | None = None,
    ) -> None:
        """Move a key that is not sent to ``queued``, ``failed`` or ``uncertain``, keeping what a later send needs."""
        if state not in ("queued", "failed", "uncertain"):
            raise ValueError(f"not a held state: {state}")
        rcpts = ",".join(recipients)
        self.db.execute(
            "UPDATE send_keys SET state = ?, request = ?, message_id = ?, result = ?, recipients = ?, attempts = ?, "
            "next_at = ?, last_error = ?, hold_reason = ?, at = ? WHERE key = ?",
            (state, request_json, message_id, result_json, rcpts, attempts, next_at, error[:500], reason, at, key),
        )

    def due(self, now_iso: str | None, limit: int = 50) -> list[str]:
        """Queued keys whose next try is due (all queued keys with ``now_iso`` None: a person said send now)."""
        due = "" if now_iso is None else "AND (next_at IS NULL OR next_at <= ?) "
        rows = self.db.fetchall(
            f"SELECT key FROM send_keys WHERE state = 'queued' {due}"
            'ORDER BY next_at COLLATE "C", key COLLATE "C" LIMIT ?',
            (limit,) if now_iso is None else (now_iso, limit),
        )
        return [str(r[0]) for r in rows]

    def wake(self) -> int:
        """Queued keys held as "waits, not counted" (``hold_reason`` WAITS, whatever line they carry) are due now;
        how many."""
        return self.db.execute(
            "UPDATE send_keys SET next_at = NULL WHERE state = 'queued' AND hold_reason = ?", (WAITS,)
        )

    def take(self, key: str, at: str) -> tuple[str, str | None, int] | None:
        """Claim a queued key for one try (``queued`` to ``sending``); ``(request, message_id, attempts)``, or None
        when another dispatcher took it first."""
        with self.db.transaction() as tx:
            n = tx.execute(
                "UPDATE send_keys SET state = 'sending', at = ? WHERE key = ? AND state = 'queued'", (at, key)
            )
            if n != 1:
                return None
            row = tx.fetchone("SELECT request, message_id, attempts FROM send_keys WHERE key = ?", (key,))
        if row is None or row[0] is None:
            return None
        return str(row[0]), row[1], int(row[2] or 0)

    def stale_sending(self, before_iso: str) -> list[str]:
        """Keys left in ``sending`` since before ``before_iso``: their process died between the claim and the mark.
        They become ``uncertain`` (the message may have left), so no key stays in ``sending``."""
        with self.db.transaction() as tx:
            rows = tx.fetchall(
                "SELECT key FROM send_keys WHERE state = 'sending' AND at < ?" + " FOR UPDATE SKIP LOCKED",
                (before_iso,),
            )
            keys = [str(r[0]) for r in rows]
            for k in keys:
                tx.execute(
                    "UPDATE send_keys SET state = 'uncertain', last_error = ? WHERE key = ? AND state = 'sending'",
                    ("the send started and never finished (the process stopped)", k),
                )
        return keys

    def resolve(self, key: str, decision: str, actor: str, at: str) -> str | None:
        """A person's decision on a held key. ``sent`` (it did arrive), ``resend`` (send it again now) or ``drop``.
        Returns the state before, or None when the key is not held (unknown, in flight, already sent or dropped)."""
        target = RESOLUTIONS[decision]
        with self.db.transaction() as tx:
            row = tx.fetchone("SELECT state, request FROM send_keys WHERE key = ? FOR UPDATE", (key,))
            if row is None or row[0] not in ("queued", "uncertain", "failed"):
                return None
            if decision == "resend" and row[1] is None:
                return None  # nothing kept to send again
            keep = target == "queued"
            tx.execute(
                "UPDATE send_keys SET state = ?, resolved_by = ?, at = ?, next_at = ?, attempts = CASE WHEN ? THEN 0 "
                "ELSE attempts END, request = CASE WHEN ? THEN request ELSE NULL END WHERE key = ?",
                (target, actor, at, at if keep else None, keep, keep, key),
            )
        return str(row[0])

    def release_send(self, key: str) -> None:
        """The transport refused before accepting anything: the key may be used again."""
        self.db.execute("DELETE FROM send_keys WHERE key = ? AND state = 'sending'", (key,))

    def prune(self, before_iso: str) -> dict[str, int]:
        """Mail-log retention (D-138, ``retention.mail_log_days``): rows older than ``before_iso`` go. A send that is
        not finished (queued, uncertain, failed) stays until it is sent or a person resolves it. Returns the rows
        deleted per table."""
        with self.db.transaction() as tx:
            return {
                "intake": tx.execute("DELETE FROM intake WHERE received_at < ?", (before_iso,)),
                "sent": tx.execute("DELETE FROM sent WHERE sent_at < ?", (before_iso,)),
                "send_keys": tx.execute(
                    "DELETE FROM send_keys WHERE state IN ('sent', 'dropped') AND at < ?", (before_iso,)
                ),
            }

    def sent(self, message_id: str) -> tuple[str | None, str] | None:
        row = self.db.fetchone("SELECT job_id, subject FROM sent WHERE message_id = ?", (message_id,))
        return (row[0], str(row[1])) if row else None

    def thread(self, job_id: str) -> list[dict[str, str]]:
        """Inbound and outbound mail of one job, oldest first: metadata only (subject, parties, time, tag)."""
        with self.db.transaction() as tx:
            inbound = tx.fetchall(
                "SELECT message_id, sender, received_at, action, COALESCE(reason, '') FROM intake WHERE job_id = ? "
                'ORDER BY received_at COLLATE "C", message_id COLLATE "C"',
                (job_id,),
            )
            outbound = tx.fetchall(
                "SELECT message_id, subject, recipients, tag, sent_at FROM sent WHERE job_id = ? "
                'ORDER BY sent_at COLLATE "C", message_id COLLATE "C"',
                (job_id,),
            )
        items = [
            {
                "direction": "in",
                "at": str(at),
                "subject": "",
                "party": str(sender),
                "tag": str(action),
                "message_id": str(mid),
                "note": str(reason),
            }
            for mid, sender, at, action, reason in inbound
        ] + [
            {
                "direction": "out",
                "at": str(at),
                "subject": str(subject),
                "party": str(rcpts),
                "tag": str(tag),
                "message_id": str(mid),
                "note": "",
            }
            for mid, subject, rcpts, tag, at in outbound
        ]
        return sorted(items, key=lambda i: i["at"])
