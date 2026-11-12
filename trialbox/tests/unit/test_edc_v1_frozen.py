"""D-461 (T-720, trust review F4 / TR-9): a version-1 EDC signature counts only when it is on the list frozen and
signed with the EDC key at the migration; ``sig_version`` defaults to 2. Synthetic data only (``tests.edc_kit``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from edc.store import SIG_VERSION, EdcStore, _legacy_sha, draft_sha, frozen_mac

from tests import edc_kit as k


def _signed(tmp_path: Path) -> Any:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    for d in svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc"):
        if d["state"] == "drafted":
            svc.decide(k.STUDY, d["id"], "confirm", by="crc")
    svc.sign(k.STUDY, k.RECORD, "", signer="crc", printed_name="Chen Mei", role="coordinator", meaning="transcribed",
             meaning_text="I checked each value.", lang="en", seen=k.seen(svc), method="password")  # fmt: skip
    return svc


def _forge(store: EdcStore, d: dict[str, Any], value: str) -> int:
    """The forgery of the trust review (F4): a database writer without the key changes a signed value, re-makes its
    hash (no key needed), inserts a signature row without naming a version and points the draft at it. No trigger
    is bypassed: ``signature`` only grows and ``draft`` may be updated."""
    changed = {**d, "final": value}
    sha = draft_sha(changed)
    with store.db.transaction() as tx:
        sid = int(tx.fetchval(
            "INSERT INTO signature (study, record, visit, signer, printed_name, role, meaning, meaning_text, lang, "
            "method, at, content_sha, drafts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
            (d["study"], d["record"], d["visit"], "crc", "Chen Mei", "coordinator", "transcribed", "x", "en",
             "password", "2026-11-09T10:00:00+00:00", _legacy_sha({int(d["id"]): sha}),
             json.dumps({str(d["id"]): sha}))))  # fmt: skip
        tx.execute("UPDATE draft SET final = ?, signed_sha = ?, signature_id = ? WHERE id = ?",
                   (value, sha, sid, int(d["id"])))  # fmt: skip
    return sid


def test_a_version_1_row_inserted_by_a_writer_without_the_key_is_never_sent(tmp_path: Path) -> None:
    svc = _signed(tmp_path)
    weight = next(d for d in svc.store.drafts(k.STUDY, k.RECORD) if d["item"] == "weight")
    sid = _forge(svc.store, weight, "99")
    forged = svc.store.signature(sid)
    assert forged is not None and forged["sig_version"] == SIG_VERSION  # the column's default is 2 now
    assert not svc.store.intact(forged)
    assert not svc.store.intact({**forged, "sig_version": 1})  # named version 1: not on the frozen list
    for store in (svc.store, EdcStore(sign_key=k.SIGN_KEY)):  # a later start does not list it either
        assert "99" not in [d["final"] for d in store.sendable(k.STUDY)]
        assert "99" not in [d["final"] for d in store.signed(k.STUDY)]
        assert len(store.sendable(k.STUDY)) == 5  # the other values of the visit stay sendable
    assert svc.send_redcap(k.STUDY, "crc")["count"] == 5
    assert [s["intact"] for s in svc.trail(k.STUDY, k.RECORD)["signatures"]] == [True, False]


def test_the_same_forgery_naming_version_1_is_refused(tmp_path: Path) -> None:
    svc = _signed(tmp_path)
    weight = next(d for d in svc.store.drafts(k.STUDY, k.RECORD) if d["item"] == "weight")
    sid = _forge(svc.store, weight, "99")
    with svc.store.db.transaction() as tx:  # the table owner goes around the trigger to set version 1
        tx.execute("ALTER TABLE signature DISABLE TRIGGER signature_append_only")
        tx.execute("UPDATE signature SET sig_version = 1 WHERE id = ?", (sid,))
        tx.execute("ALTER TABLE signature ENABLE TRIGGER signature_append_only")
    row = svc.store.signature(sid)
    assert row is not None and row["sig_version"] == 1 and not svc.store.intact(row)
    assert "99" not in [d["final"] for d in svc.store.sendable(k.STUDY)]


def test_a_new_store_freezes_an_empty_list_once() -> None:
    store = EdcStore(sign_key=k.SIGN_KEY)
    again = EdcStore(sign_key=k.SIGN_KEY)  # a second start writes nothing
    rows = store.db.fetchdicts("SELECT entries, key_id, mac FROM sig_v1_frozen")
    assert len(rows) == 1 and json.loads(rows[0]["entries"]) == [] and rows[0]["key_id"] == store.key_id
    assert rows[0]["mac"] == frozen_mac(k.SIGN_KEY, [])
    assert (
        store.db.fetchval(
            "SELECT column_default FROM information_schema.columns WHERE table_schema = "
            "current_schema() AND table_name = 'signature' AND column_name = 'sig_version'"
        )
        == "2"
    )
    for stmt in ("UPDATE sig_v1_frozen SET entries = '[]'", "DELETE FROM sig_v1_frozen", "TRUNCATE sig_v1_frozen"):
        with pytest.raises(Exception, match="append-only"):
            store.db.execute(stmt)
    again.close()
    store.close()


def test_a_row_from_before_the_migration_is_listed_and_still_checked() -> None:
    store, old = k.store_with_old_signature()
    listed = json.loads(store.db.fetchval("SELECT entries FROM sig_v1_frozen"))
    assert listed == [[old["id"], old["content_sha"]]]
    assert store.intact(old)
    assert not store.intact({**old, "drafts": json.dumps({"1": "c" * 64})})  # changed values: the unkeyed rule
    assert not store.intact({**old, "id": old["id"] + 1})  # another id with the same hash: not listed
    later = EdcStore(sign_key=k.SIGN_KEY)  # a later start reads the same list and adds nothing
    assert later.intact(old) and later.db.fetchval("SELECT count(*) FROM sig_v1_frozen") == 1
    later.close()
    other = EdcStore(sign_key=b"another-box-signature-key-98765")  # the list's MAC does not verify under another key
    assert not other.intact(old)
    other.close()
    store.close()


def test_an_emptied_list_is_not_made_again() -> None:
    store, old = k.store_with_old_signature()
    with store.db.transaction() as tx:  # the table owner drops the trigger and empties the list
        tx.execute("ALTER TABLE sig_v1_frozen DISABLE TRIGGER sig_v1_frozen_no_truncate")
        tx.execute("TRUNCATE sig_v1_frozen")
        tx.execute("ALTER TABLE sig_v1_frozen ENABLE TRIGGER sig_v1_frozen_no_truncate")
    store.close()
    later = EdcStore(sign_key=k.SIGN_KEY)
    assert later.db.fetchval("SELECT count(*) FROM sig_v1_frozen") == 0
    assert not later.intact(old)  # no list: no version-1 row counts
    later.close()


def test_a_list_written_without_the_key_counts_for_nothing() -> None:
    store, old = k.store_with_old_signature()
    with store.db.transaction() as tx:  # the owner swaps the list for one naming another row, with a made-up MAC
        tx.execute("ALTER TABLE sig_v1_frozen DISABLE TRIGGER sig_v1_frozen_append_only")
        tx.execute("UPDATE sig_v1_frozen SET entries = ?, mac = ?",
                   (json.dumps([[old["id"], old["content_sha"]], [99, "d" * 64]]), "0" * 64))  # fmt: skip
        tx.execute("ALTER TABLE sig_v1_frozen ENABLE TRIGGER sig_v1_frozen_append_only")
    store.close()
    later = EdcStore(sign_key=k.SIGN_KEY)
    assert not later.intact(old)
    later.close()
