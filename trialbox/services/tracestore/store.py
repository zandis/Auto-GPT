"""Self-hosted trace store v0 (spec v4 §8.14, LLM-45, LLM-46; S1-08).

* **Redaction at write.** Every string in a trace (prompt, output, attribute values) passes :meth:`Guard.redact`
  before it touches disk; only the identifiers and enumerations listed in ``tracestore.yaml`` are stored as given.
* **Access log.** Every read, refusal and prune is logged in the store's own ``access_log`` table with user and
  purpose; a read needs a purpose and the ``trace:read`` role.
* **Retention.** :meth:`TraceStore.prune` deletes traces older than ``retention_days`` (90) by the injected clock;
  special-category traces use ``sc_retention_days``.
* **Not the audit trail.** Each trace carries ``call_id``, which resolves to the gateway's ledger record (LLM-46).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from guard.guard import Guard

SETTINGS_PATH = Path(__file__).resolve().parent / "tracestore.yaml"
Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(UTC)


class TraceAccessDenied(PermissionError):
    pass


@dataclass(frozen=True)
class TraceSettings:
    retention_days: int
    sc_retention_days: int
    read_role: str
    safe_attributes: frozenset[str]

    @classmethod
    def load(cls, path: Path = SETTINGS_PATH) -> TraceSettings:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(
            retention_days=int(doc["retention_days"]),
            sc_retention_days=int(doc["sc_retention_days"]),
            read_role=str(doc["read_role"]),
            safe_attributes=frozenset(str(x) for x in doc.get("safe_attributes") or ()),
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
  id INTEGER PRIMARY KEY AUTOINCREMENT, call_id TEXT NOT NULL, ts TEXT NOT NULL, sc INTEGER NOT NULL, body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS traces_call ON traces(call_id);
CREATE INDEX IF NOT EXISTS traces_ts ON traces(ts);
CREATE TABLE IF NOT EXISTS access_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, user TEXT NOT NULL, purpose TEXT NOT NULL,
  action TEXT NOT NULL, call_id TEXT, granted INTEGER NOT NULL, detail TEXT
);
"""


class TraceStore:
    def __init__(
        self,
        path: Path,
        guard: Guard | None = None,
        *,
        clock: Clock = utcnow,
        settings: TraceSettings | None = None,
    ) -> None:
        self.path = path
        self.guard = guard or Guard.from_settings()
        self.clock = clock
        self.settings = settings or TraceSettings.load()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(_SCHEMA)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path)
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None:
            raise ValueError("trace store clock must be timezone-aware")
        return now.astimezone(UTC)  # one offset, so ISO strings order like instants

    def _log(self, db: sqlite3.Connection, user: str, purpose: str, action: str, call_id: str | None, ok: bool) -> None:
        db.execute(
            "INSERT INTO access_log (ts, user, purpose, action, call_id, granted) VALUES (?, ?, ?, ?, ?, ?)",
            (self._now().isoformat(), user, purpose, action, call_id, int(ok)),
        )

    # ------------------------------------------------------------------------------------------------ write
    def _redact_trace(self, trace: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, val in trace.items():
            if key in ("call_id", "span", "sc"):
                out[key] = val
            elif key == "attributes" and isinstance(val, dict):
                out[key] = {
                    k: (v if k in self.settings.safe_attributes else self.guard.redact_obj(v)) for k, v in val.items()
                }
            else:
                out[key] = self.guard.redact_obj(val)
        return out

    def write(self, trace: dict[str, Any]) -> str:
        """Store one trace (redacted). ``call_id`` is required; ``sc: true`` marks special-category content."""
        call_id = str(trace.get("call_id") or "")
        if not call_id:
            raise ValueError("a trace needs tb.call_id (LLM-46)")
        body = self._redact_trace(trace)
        ts = self._now().isoformat()
        body["ts"] = ts
        with self._db() as db:
            db.execute(
                "INSERT INTO traces (call_id, ts, sc, body) VALUES (?, ?, ?, ?)",
                (call_id, ts, int(bool(trace.get("sc"))), json.dumps(body, ensure_ascii=False, sort_keys=True)),
            )
        return call_id

    # ------------------------------------------------------------------------------------------------ read
    def read(self, call_id: str, *, user: str, purpose: str, roles: frozenset[str]) -> list[dict[str, Any]]:
        ok = bool(user) and bool(purpose.strip()) and self.settings.read_role in roles
        with self._db() as db:
            self._log(db, user or "?", purpose, "read", call_id, ok)
            if not ok:
                db.commit()
                raise TraceAccessDenied(f"trace read needs a user, a purpose and the {self.settings.read_role} role")
            rows = db.execute("SELECT body FROM traces WHERE call_id = ? ORDER BY id", (call_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def access_log(self) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute(
                "SELECT ts, user, purpose, action, call_id, granted, detail FROM access_log ORDER BY id"
            ).fetchall()
        keys = ("ts", "user", "purpose", "action", "call_id", "granted", "detail")
        return [dict(zip(keys, r, strict=True)) for r in rows]

    def count(self) -> int:
        with self._db() as db:
            return int(db.execute("SELECT COUNT(*) FROM traces").fetchone()[0])

    # ------------------------------------------------------------------------------------------------ retention
    def prune(self) -> int:
        """Delete traces past retention (90 days; sc traces sooner). Returns the number deleted; logged."""
        now = self._now()
        cut = (now - timedelta(days=self.settings.retention_days)).isoformat()
        cut_sc = (now - timedelta(days=self.settings.sc_retention_days)).isoformat()
        with self._db() as db:
            n = db.execute("DELETE FROM traces WHERE ts < ? OR (sc = 1 AND ts < ?)", (cut, cut_sc)).rowcount
            db.execute(
                "INSERT INTO access_log (ts, user, purpose, action, call_id, granted, detail) "
                "VALUES (?, 'system', 'retention', 'prune', NULL, 1, ?)",
                (now.isoformat(), json.dumps({"deleted": n, "before": cut})),
            )
        return int(n)
