"""Self-hosted trace store v0 (spec v4 §8.14, LLM-45, LLM-46; S1-08).

* **Redaction at write.** Every string in a trace (prompt, output, attribute values) passes :meth:`Guard.redact`
  before it is stored (schema ``trace`` of the trial database, D-126); only the identifiers and enumerations
  listed in ``tracestore.yaml`` are stored as given.
* **Access log.** Every read, refusal and prune is logged in the store's own ``access_log`` table with user and
  purpose; a read needs a purpose and the ``trace:read`` role.
* **Retention.** :meth:`TraceStore.prune` deletes traces older than ``retention_days`` (90) by the injected clock;
  special-category traces use ``sc_retention_days``. In PRODUCTION neither is longer than
  ``production_retention_days`` (7; T-208, D-346).
* **No text for the suite.** A trace whose ``tb.study_id`` is in ``no_text_studies`` (the prompt-injection suite)
  keeps its call id, span, special-category mark and safe attributes only (T-208).
* **No D3/D4 text in PRODUCTION (T-605, D-431).** In PRODUCTION a trace whose ``tb.data_class`` is in
  ``production_no_text_classes`` keeps the prompt and the output as a sha256 and a size only, never as text.
* **Scheduled prune (T-605, D-431).** A write prunes when the last prune is older than ``prune_every_hours`` by the
  injected clock, so retention holds without an operator. Every prune touches only rows written under D-431
  (``policy`` 1); older rows wait for the owner's ruling on existing trace rows.
* **Not the audit trail.** Each trace carries ``call_id``, which resolves to the gateway's ledger record (LLM-46).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from guard.guard import Guard
from tb_common.config import environment_name
from tb_common.db import ENV, Database, Tx

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
    no_text_studies: frozenset[str] = frozenset()
    no_text_classes: frozenset[str] = frozenset()  # PRODUCTION only (T-605): hashes and sizes, no text
    prune_every_hours: float = 0.0  # 0: no prune on write

    @classmethod
    def load(cls, path: Path = SETTINGS_PATH, environment: str | None = None) -> TraceSettings:
        """The settings file; ``environment`` (default: ``TB_ENV``, PRODUCTION when unset) caps both retentions at
        ``production_retention_days`` in PRODUCTION."""
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        days, sc_days = int(doc["retention_days"]), int(doc["sc_retention_days"])
        env = environment if environment is not None else environment_name(os.environ)
        production = env.strip().upper() == "PRODUCTION"
        if production and doc.get("production_retention_days") is not None:
            cap = int(doc["production_retention_days"])
            days, sc_days = min(days, cap), min(sc_days, cap)
        no_text_classes = (doc.get("production_no_text_classes") or ()) if production else ()
        return cls(
            retention_days=days,
            sc_retention_days=sc_days,
            read_role=str(doc["read_role"]),
            safe_attributes=frozenset(str(x) for x in doc.get("safe_attributes") or ()),
            no_text_studies=frozenset(str(x) for x in doc.get("no_text_studies") or ()),
            no_text_classes=frozenset(str(x).upper() for x in no_text_classes),
            prune_every_hours=float(doc.get("prune_every_hours") or 0),
        )


SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS traces (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, call_id TEXT NOT NULL, ts TEXT NOT NULL, sc INTEGER NOT NULL,
  body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS traces_call ON traces(call_id);
CREATE INDEX IF NOT EXISTS traces_ts ON traces(ts);
CREATE TABLE IF NOT EXISTS access_log (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, ts TEXT NOT NULL, "user" TEXT NOT NULL, purpose TEXT NOT NULL,
  action TEXT NOT NULL, call_id TEXT, granted INTEGER NOT NULL, detail TEXT
);
"""
# T-605 (D-431): rows written from now on carry policy 1 and are the only rows a prune deletes; rows from before
# (policy 0) are kept as they are until the owner rules on existing trace rows
SCHEMA_V2 = "ALTER TABLE traces ADD COLUMN IF NOT EXISTS policy INTEGER NOT NULL DEFAULT 0"
POLICY = 1


def _digest(value: Any) -> dict[str, Any] | None:
    """A sha256 and a size of ``value`` (text or JSON), never the value itself."""
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "chars": len(text)}


class TraceStore:
    def __init__(
        self,
        url: str | None = None,
        guard: Guard | None = None,
        *,
        clock: Clock = utcnow,
        settings: TraceSettings | None = None,
    ) -> None:
        """``url``: the trial database (``TB_DB_URL`` when ``None``; :class:`~tb_common.db.DatabaseError` if unset).
        The traces live in its schema ``trace``."""
        self.guard = guard or Guard.from_settings()
        self.clock = clock
        self.settings = settings or TraceSettings.load()
        self.db = Database.connect(url or os.environ.get(ENV), "trace")
        self.db.migrate([SCHEMA_V1, SCHEMA_V2])
        self._last_prune: datetime | None = None

    def close(self) -> None:
        self.db.close()

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None:
            raise ValueError("trace store clock must be timezone-aware")
        return now.astimezone(UTC)  # one offset, so ISO strings order like instants

    def _log(self, tx: Tx, user: str, purpose: str, action: str, call_id: str | None, ok: bool) -> None:
        tx.execute(
            'INSERT INTO access_log (ts, "user", purpose, action, call_id, granted) VALUES (?, ?, ?, ?, ?, ?)',
            (self._now().isoformat(), user, purpose, action, call_id, int(ok)),
        )

    # ------------------------------------------------------------------------------------------------ write
    def _redact_trace(self, trace: dict[str, Any]) -> dict[str, Any]:
        raw = trace.get("attributes")
        attrs: dict[str, Any] = raw if isinstance(raw, dict) else {}
        if str(attrs.get("tb.study_id") or "") in self.settings.no_text_studies:  # T-208: no text at all
            safe = {k: v for k, v in attrs.items() if k in self.settings.safe_attributes}
            return {k: trace[k] for k in ("call_id", "span", "sc") if k in trace} | {"attributes": safe}
        if str(attrs.get("tb.data_class") or "").upper() in self.settings.no_text_classes:  # T-605: no D3/D4 text
            safe = {k: v for k, v in attrs.items() if k in self.settings.safe_attributes}
            kept = {k: trace[k] for k in ("call_id", "span", "sc") if k in trace} | {"attributes": safe}
            return kept | {f"{k}_digest": _digest(trace.get(k)) for k in ("prompt", "output") if k in trace}
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
        now = self._now()
        ts = now.isoformat()
        body["ts"] = ts
        self.db.execute(
            "INSERT INTO traces (call_id, ts, sc, body, policy) VALUES (?, ?, ?, ?, ?)",
            (call_id, ts, int(bool(trace.get("sc"))), json.dumps(body, ensure_ascii=False, sort_keys=True), POLICY),
        )
        every = self.settings.prune_every_hours
        if every > 0 and (self._last_prune is None or now - self._last_prune >= timedelta(hours=every)):
            self.prune()  # the schedule: no separate job to forget (T-605)
        return call_id

    # ------------------------------------------------------------------------------------------------ read
    def read(self, call_id: str, *, user: str, purpose: str, roles: frozenset[str]) -> list[dict[str, Any]]:
        ok = bool(user) and bool(purpose.strip()) and self.settings.read_role in roles
        with self.db.transaction() as tx:
            self._log(tx, user or "?", purpose, "read", call_id, ok)
            rows = tx.fetchall("SELECT body FROM traces WHERE call_id = ? ORDER BY id", (call_id,)) if ok else []
        if not ok:  # the refusal is logged (committed above) before it is raised
            raise TraceAccessDenied(f"trace read needs a user, a purpose and the {self.settings.read_role} role")
        return [json.loads(r[0]) for r in rows]

    def access_log(self) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            'SELECT ts, "user", purpose, action, call_id, granted, detail FROM access_log ORDER BY id'
        )
        keys = ("ts", "user", "purpose", "action", "call_id", "granted", "detail")
        return [dict(zip(keys, r, strict=True)) for r in rows]

    def count(self) -> int:
        return int(self.db.fetchval("SELECT COUNT(*) FROM traces", default=0))

    # ------------------------------------------------------------------------------------------------ retention
    def prune(self) -> int:
        """Delete traces past retention (90 days; sc traces sooner; 7 in PRODUCTION). Returns the number deleted;
        logged. Only rows written under D-431 (``policy`` 1) are deleted; older rows await the owner's ruling."""
        now = self._now()
        self._last_prune = now
        cut = (now - timedelta(days=self.settings.retention_days)).isoformat()
        cut_sc = (now - timedelta(days=self.settings.sc_retention_days)).isoformat()
        with self.db.transaction() as tx:
            # ISO strings in one offset; compared byte-wise as SQLite did
            n = tx.execute(
                'DELETE FROM traces WHERE policy >= ? AND (ts < ? COLLATE "C" OR (sc = 1 AND ts < ? COLLATE "C"))',
                (POLICY, cut, cut_sc),
            )
            tx.execute(
                'INSERT INTO access_log (ts, "user", purpose, action, call_id, granted, detail) '
                "VALUES (?, 'system', 'retention', 'prune', NULL, 1, ?)",
                (now.isoformat(), json.dumps({"deleted": n, "before": cut})),
            )
        return int(n)
