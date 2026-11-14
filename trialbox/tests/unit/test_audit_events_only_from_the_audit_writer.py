"""NEW-SEC-2 (D-718): an ``audit.*`` event reaches the chain only from the audit's own writer.

The deep review of 2026-11-13 (SEC-10): any service may write ``audit.*`` events. The family was shared with the
console and the orchestrator, and every other service's row of it was only marked. A compromised console could send
a forged ``audit.signing_key_rotated``: ``verify --heads`` then read it as a key rotation, failed for good, and the
nightly signer refused to sign again.

The chain's own records (``audit.anchored``, ``audit.repaired``, ``audit.reanchored``, ``audit.head_signed``,
``audit.signing_key_rotated``, ``audit.journal_resync``) are written by the chain's writer itself: the drain, the
file writer, the host's signer. None comes through the journal. Now a journal row of the family from any service
role is written under ``journal.reserved_name`` with the name it was sent as, flagged; and ``verify`` takes a key
rotation only from a record the chain's writer wrote, never from one that came through the journal (a chain
written before this fix may hold one). Synthetic data only."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from tb_common import audit_writer
from tb_common.audit import ROTATED_EVENT, AuditLog, verify
from tb_common.audit_writer import ROLE_EVENTS, Drain, flagged
from tb_common.crypto import ed25519_generate

from tests.unit.test_audit_drain_malformed_row import _Con

AT = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
SERVICES = sorted(r for r in ROLE_EVENTS if r != "tb_audit_writer") + ["tb_somebody_new"]


def _lines(d: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for p in sorted(d.glob("*.jsonl")) for x in p.read_text().splitlines() if x]


def _forged_rotation() -> dict[str, Any]:
    _, pub = ed25519_generate()
    return {"actor": "console:mallory", "detail": {"old_key_id": "k-old", "new_key_id": "k-new",
                                                   "new_public": pub.decode(), "endorsement":
                                                   base64.b64encode(b"x" * 64).decode()}}  # fmt: skip


def test_no_service_role_has_the_audit_family() -> None:
    for role in SERVICES[:-1]:
        assert "audit" not in ROLE_EVENTS[role], role
        assert audit_writer.foreign(role, ROTATED_EVENT) == "role", role
    assert audit_writer.foreign("tb_audit_writer", ROTATED_EVENT) == ""


@pytest.mark.parametrize("role", SERVICES)
def test_a_services_audit_event_is_written_under_another_name_and_flagged(tmp_path: Path, role: str) -> None:
    rows = [
        (1, AT, "tb_console", "console.login", AT.isoformat(), {"actor": "console:a"}),
        (2, AT, role, ROTATED_EVENT, AT.isoformat(), _forged_rotation()),
        (3, AT, role, "audit.head_signed", AT.isoformat(), {"actor": "x", "detail": {"lines": 1}}),
        (4, AT, "tb_console", "console.denied", AT.isoformat(), {"actor": "console:b"}),
    ]
    drain = Drain("postgresql://x@h/db", tmp_path, "Asia/Taipei", connect=lambda: _Con(rows))
    drain.open()
    assert drain.run(once=True, alive=None) == 4
    lines = _lines(tmp_path)
    # the host's nightly signer records its head from the orchestrator's container: that one name, nothing else
    signer = ["audit.head_signed"] if role == "tb_orchestrator" else []
    assert [r["event"] for r in lines if str(r["event"]).startswith("audit.") and r.get("journal")] == signer
    kept = [r for r in lines if r["event"] == "journal.reserved_name"]
    assert [r["detail"]["sent_event"] for r in kept] == [ROTATED_EVENT, "audit.head_signed"][: 2 - len(signer)]
    assert all("reserved" in r["journal"]["flag"] and r["journal"]["role"] == role for r in kept)
    assert {r["seq"] for r in flagged(tmp_path)} >= ({2} if signer else {2, 3})  # what audit_verify --foreign lists
    res = verify(tmp_path)
    assert res.ok, res.errors  # the forged rotation is no rotation: nothing for verify to fail on


def test_the_audit_writer_and_the_administrator_keep_their_own_family(tmp_path: Path) -> None:
    rows = [(1, AT, "tb_audit_writer", "audit.journal_note", AT.isoformat(), {"actor": "drain"}),
            (2, AT, "trialbox", "audit.reanchored", AT.isoformat(), {"actor": "trialbox:repair"})]  # fmt: skip
    drain = Drain("postgresql://x@h/db", tmp_path, "Asia/Taipei", connect=lambda: _Con(rows))
    drain.open()
    drain.run(once=True, alive=None)
    assert [r["event"] for r in _lines(tmp_path) if r.get("journal")] == ["audit.journal_note", "audit.reanchored"]


def test_verify_takes_a_key_rotation_only_from_the_chains_own_writer(tmp_path: Path) -> None:
    """A chain written before this fix may hold a forged rotation that came through the journal: verify does not
    take it as a rotation (it notes it), and a head signed by the trusted key still verifies."""
    log = AuditLog(tmp_path / "audit", "UTC")
    log.append("console.login", actor="console:a", detail={})
    share = tmp_path / "share"
    share.mkdir()
    priv, pub = ed25519_generate()
    head = log.sign_head(priv, pub, [share])
    forged = _forged_rotation()
    log.append(ROTATED_EVENT, actor=forged["actor"], detail=forged["detail"],
               journal={"seq": 9, "role": "tb_console", "at": AT.isoformat()})  # fmt: skip
    from tb_common.audit import read_public_keys, read_signed_heads

    res = verify(
        tmp_path / "audit", signed_heads=read_signed_heads(share), trusted_keys=read_public_keys([share / "keys"])
    )
    assert res.ok, res.errors
    assert any("not taken as a key rotation" in n for n in res.notes), res.notes
    assert head["lines"] >= 1
