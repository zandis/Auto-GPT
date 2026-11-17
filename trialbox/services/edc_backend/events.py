"""Signed EDC events (contract version 1). The body is HMAC-SHA256. A repeated ``id`` is one event.

The payload names the record and the instrument. It does not carry field values, and this module does not log
the body.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from pathlib import Path
from typing import Any

SPEC = "trialbox.edc.event.v1"
TYPES = frozenset({"record.saved", "form.completed", "query.opened", "ae.reported"})
REREAD = frozenset({"record.saved", "form.completed", "ae.reported"})


class EventRejected(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def event_secret(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    return (env.get("TB_EDC_EVENT_SECRET") or "").strip()


def event_dir(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    return (env.get("TB_EDC_EVENT_DIR") or "").strip()


def signature_ok(secret: str, body: bytes, header: str) -> bool:
    """``X-TrialBox-Signature: sha256=`` plus the hex HMAC-SHA256 of the raw body."""
    if not secret or not header.lower().startswith("sha256="):
        return False
    given = header.split("=", 1)[1].strip().lower()
    mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, given)


class EventLog:
    """Ids already accepted. A second delivery of the same id does not run the hook again."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return list(raw) if isinstance(raw, list) else []

    def has(self, event_id: str) -> bool:
        with self._lock:
            return any(str(row.get("id")) == event_id for row in self._read())

    def add(self, row: dict[str, Any]) -> None:
        with self._lock:
            rows = self._read()
            rows.append(row)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            os.chmod(self.path, 0o600)


def parse_event(body: bytes) -> dict[str, Any]:
    try:
        doc = json.loads(body)
    except ValueError as exc:
        raise EventRejected(400, "the event is not JSON") from exc
    if not isinstance(doc, dict) or doc.get("spec") != SPEC:
        raise EventRejected(400, "the event spec is not trialbox.edc.event.v1")
    if str(doc.get("type") or "") not in TYPES or not str(doc.get("id") or "").strip():
        raise EventRejected(400, "the event type or id is missing")
    return doc


def check(secret: str, body: bytes, header: str, log: EventLog) -> tuple[dict[str, Any], bool]:
    """``(event, fresh)``. A bad signature is 401. A repeated id is not fresh. Nothing is stored yet."""
    if not signature_ok(secret, body, header):
        raise EventRejected(401, "the event signature does not match")
    doc = parse_event(body)
    return doc, not log.has(str(doc["id"]))


def remember(log: EventLog, doc: dict[str, Any]) -> None:
    raw = doc.get("data")
    data: dict[str, Any] = raw if isinstance(raw, dict) else {}
    log.add(
        {
            "id": str(doc.get("id")),
            "type": str(doc.get("type")),
            "project_id": str(doc.get("project_id") or ""),
            "record_id": str(doc.get("record_id") or ""),
            "instrument": str(data.get("instrument") or ""),
            "occurred_at": str(doc.get("occurred_at") or ""),
        }
    )
