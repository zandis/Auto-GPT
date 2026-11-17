"""Signed EDC events (contract version 1). The body is HMAC-SHA256. A repeated ``id`` is one event (D-1044: the id is
kept in the trial database, ``edc_backend.store``).

The payload names the record and the instrument. It does not carry field values, and this module does not log
the body.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
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


def event_secrets(environ: dict[str, str] | None = None) -> list[str]:
    """D-1045: ``current`` or ``current,previous``. While the EDC moves to a new secret both are accepted; the
    rotation ends when the setting holds the new one alone (``docs/data/13``, "Changing the event secret")."""
    return [part.strip() for part in event_secret(environ).split(",") if part.strip()][:2]


def event_dir(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    return (env.get("TB_EDC_EVENT_DIR") or "").strip()


def signature_ok(secret: str, body: bytes, header: str) -> bool:
    """``X-TrialBox-Signature: sha256=`` plus the hex HMAC-SHA256 of the raw body, under ``secret``: one secret, or
    ``current,previous`` during a rotation (D-1045; either matches)."""
    keys = [part.strip() for part in secret.split(",") if part.strip()][:2]
    if not keys or not header.lower().startswith("sha256="):
        return False
    given = header.split("=", 1)[1].strip().lower()
    ok = False
    for key in keys:  # every key is tried, so the time taken does not say which one matched
        ok |= hmac.compare_digest(hmac.new(key.encode(), body, hashlib.sha256).hexdigest(), given)
    return ok


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


def check(secret: str, body: bytes, header: str) -> dict[str, Any]:
    """The event, when its signature matches (else 401) and its shape is version 1 (else 400). Whether its id is new
    is the store's to say (``edc_backend.store.DoorStore.take_event``, D-1044)."""
    if not signature_ok(secret, body, header):
        raise EventRejected(401, "the event signature does not match")
    return parse_event(body)


def row_of(doc: dict[str, Any]) -> dict[str, str]:
    """What is kept of an event: its id, type, the EDC's project and record ids, the instrument and when; no value."""
    raw = doc.get("data")
    data: dict[str, Any] = raw if isinstance(raw, dict) else {}
    return {
        "id": str(doc.get("id")),
        "type": str(doc.get("type")),
        "project_id": str(doc.get("project_id") or ""),
        "record_id": str(doc.get("record_id") or ""),
        "instrument": str(data.get("instrument") or ""),
        "occurred_at": str(doc.get("occurred_at") or ""),
    }
