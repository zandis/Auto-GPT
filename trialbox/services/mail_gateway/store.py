"""mail-gateway state (schema ``mail`` of the trial database, D-126): intake log (idempotency + rate limit) and
sent-message index (reply-to-thread matching)."""

from __future__ import annotations

import os

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


class SendUncertain(RuntimeError):
    """A send with this key started and never finished: it may have reached the recipients. Never resent."""


class MailDB:
    def __init__(self, url: str | None = None) -> None:
        """``url``: the trial database (``TB_DB_URL`` when ``None``; :class:`~tb_common.db.DatabaseError` if unset)."""
        self.db = Database.connect(url or os.environ.get(ENV), "mail")
        self.db.migrate([SCHEMA_V1, SCHEMA_V2])

    def close(self) -> None:
        self.db.close()

    def intake(self, message_id: str) -> tuple[str, str | None] | None:
        row = self.db.fetchone("SELECT action, job_id FROM intake WHERE message_id = ?", (message_id,))
        return (str(row[0]), row[1]) if row else None

    def record_intake(
        self, message_id: str, sender: str, at: str, action: str, job_id: str | None, reason: str | None = None
    ) -> None:
        self.db.execute(
            "INSERT INTO intake (message_id, sender, received_at, action, job_id, reason) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT (message_id) DO UPDATE SET sender = EXCLUDED.sender, received_at = EXCLUDED.received_at, "
            "action = EXCLUDED.action, job_id = EXCLUDED.job_id, reason = EXCLUDED.reason",
            (message_id, sender, at, action, job_id, reason),
        )

    def jobs_since(self, sender: str, since_iso: str) -> int:
        n = self.db.fetchval(
            "SELECT count(*) FROM intake WHERE sender = ? AND action = 'job' AND received_at >= ?",
            (sender, since_iso),
            default=0,
        )
        return int(n)

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

    def finish_send(self, key: str, message_id: str, result_json: str, at: str) -> None:
        self.db.execute(
            "UPDATE send_keys SET state = 'sent', message_id = ?, result = ?, at = ? WHERE key = ?",
            (message_id, result_json, at, key),
        )

    def release_send(self, key: str) -> None:
        """The transport refused before accepting anything: the key may be used again."""
        self.db.execute("DELETE FROM send_keys WHERE key = ? AND state = 'sending'", (key,))

    def prune(self, before_iso: str) -> dict[str, int]:
        """Mail-log retention (D-138, ``retention.mail_log_days``): rows older than ``before_iso`` go. A send that
        never finished (``sending``) stays until a person resolves it. Returns the rows deleted per table."""
        with self.db.transaction() as tx:
            return {
                "intake": tx.execute("DELETE FROM intake WHERE received_at < ?", (before_iso,)),
                "sent": tx.execute("DELETE FROM sent WHERE sent_at < ?", (before_iso,)),
                "send_keys": tx.execute("DELETE FROM send_keys WHERE state = 'sent' AND at < ?", (before_iso,)),
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
