"""D-461 (T-720, trust review F4 / TR-9): an EDC signature counts only in version 2 (the keyed hash); a version-1
row, which anyone can re-make without the key, covers nothing. ``sig_version`` defaults to 2 and a new row must say
2. The review route marks a value "covered" only while an intact signature covers it. Synthetic data only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from edc import copyassist
from edc.store import MIGRATIONS, SIG_VERSION, EdcStore, draft_sha
from fastapi import FastAPI
from fastapi.testclient import TestClient
from orchestrator.edc_api import router as edc_router

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


def _weight(store: EdcStore) -> dict[str, Any]:
    return next(d for d in store.drafts(k.STUDY, k.RECORD) if d["item"] == "weight")


def _forge(store: EdcStore, value: str, version: int | None = None) -> int:
    """The forgery of the trust review (F4), as the schema's owner without the key: change a signed value, re-make
    its hash (no key needed), insert a signature row with the unkeyed hash and point the draft at it."""
    d = _weight(store)
    sha = draft_sha({**d, "final": value})
    cols = ""
    args: tuple[int, ...] = ()
    with store.db.transaction() as tx:
        if version is not None:  # the owner drops the version check first
            tx.execute("ALTER TABLE signature DROP CONSTRAINT IF EXISTS signature_v2_only")
            cols, args = ", sig_version", (version,)
        sid = int(tx.fetchval(
            "INSERT INTO signature (study, record, visit, signer, printed_name, role, meaning, meaning_text, lang, "
            f"method, at, content_sha, drafts{cols}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?{',?' * len(args)}) RETURNING id",
            (d["study"], d["record"], d["visit"], "crc", "Chen Mei", "coordinator", "transcribed", "x", "en",
             "password", "2026-11-09T10:00:00+00:00", k.old_unkeyed_sha({int(d["id"]): sha}),
             json.dumps({str(d["id"]): sha}), *args)))  # fmt: skip
        tx.execute("UPDATE draft SET final = ?, signed_sha = ?, signature_id = ? WHERE id = ?",
                   (value, sha, sid, int(d["id"])))  # fmt: skip
    return sid


def _never_sent(store: EdcStore, value: str) -> None:
    assert value not in [d["final"] for d in store.sendable(k.STUDY)]
    assert value not in [d["final"] for d in store.signed(k.STUDY)]
    assert len(store.sendable(k.STUDY)) == 5  # the other values of the visit stay sendable


def test_a_signature_row_inserted_without_a_version_is_never_sent(tmp_path: Path) -> None:
    svc = _signed(tmp_path)
    forged = svc.store.signature(_forge(svc.store, "99"))
    assert forged is not None and forged["sig_version"] == SIG_VERSION  # the column's default is 2 now
    assert not svc.store.intact(forged) and not svc.store.intact({**forged, "sig_version": 1})
    _never_sent(svc.store, "99")
    assert svc.send_redcap(k.STUDY, "crc")["count"] == 5
    assert [s["intact"] for s in svc.trail(k.STUDY, k.RECORD)["signatures"]] == [True, False]


def test_a_version_1_row_is_refused(tmp_path: Path) -> None:
    svc = _signed(tmp_path)
    row = svc.store.signature(_forge(svc.store, "99", version=1))
    assert row is not None and row["sig_version"] == 1 and not svc.store.intact(row)
    _never_sent(svc.store, "99")


@pytest.mark.parametrize("keep", [0, 1, 2, 3, 4])
def test_resetting_the_schema_record_does_not_bring_a_version_1_row_back(tmp_path: Path, keep: int) -> None:
    """The review's reset: the owner forges a version-1 row, forgets the schema versions after ``keep`` (D-461's is 5) and waits
    for a restart, which re-runs them. Nothing a migration does makes a version-1 row count."""
    svc = _signed(tmp_path)
    _forge(svc.store, "99", version=1)
    svc.store.db.execute("DELETE FROM _schema_version WHERE version > ?", (keep,))
    svc.store.close()
    again = EdcStore(sign_key=k.SIGN_KEY)
    assert len(again.db.applied()) == len(MIGRATIONS)
    _never_sent(again, "99")
    again.close()


def test_new_rows_default_to_and_must_say_version_2(tmp_path: Path) -> None:
    svc = _signed(tmp_path)
    db = svc.store.db
    assert db.fetchval("SELECT column_default FROM information_schema.columns WHERE table_schema = current_schema() "
                       "AND table_name = 'signature' AND column_name = 'sig_version'") == "2"  # fmt: skip
    with pytest.raises(Exception, match="signature_v2_only"):
        db.execute("INSERT INTO signature (study, record, visit, signer, printed_name, role, meaning, meaning_text, "
                   "lang, method, at, content_sha, drafts, sig_version) VALUES ('S','R','','u','n','r','m','t','en',"
                   "'password','2026-11-09','x','{}',1)")  # fmt: skip


def test_an_old_signature_from_before_the_migration_covers_nothing() -> None:
    store, old = k.store_with_old_signature()  # the migration accepts the existing row (NOT VALID) and ignores it
    assert old["sig_version"] == 1 and not store.intact(old)
    store.close()


def test_the_review_list_says_signed_only_while_the_signature_covers_the_value(tmp_path: Path) -> None:
    svc = _signed(tmp_path)
    api = FastAPI()
    api.include_router(edc_router(lambda: svc))
    oc = TestClient(api)

    def listed() -> dict[str, dict[str, Any]]:
        r = oc.get(f"/studies/{k.STUDY}/edc/drafts", params={"record": k.RECORD})
        assert r.status_code == 200, r.text
        return {d["item"]: d for d in r.json()}

    before = listed()
    assert before["weight"]["covered"] and before["weight"]["signature"]["printed_name"] == "Chen Mei"
    svc.store.db.execute("UPDATE draft SET final = '99' WHERE id = ?", (before["weight"]["id"],))  # a plain update
    after = listed()
    assert after["weight"]["signature_id"] is not None and not after["weight"]["covered"]
    assert "signature" not in after["weight"]
    assert after["urate"]["covered"] and "signature" in after["urate"]
    sheet = copyassist.sheet(svc, k.STUDY, k.RECORD, "crc")  # T-302c's copy-assist sheet tells the same story
    on_sheet = {v["item"] for r in sheet["records"] for vis in r["visits"] for f in vis["forms"] for v in f["values"]}
    assert "weight" not in on_sheet and "urate" in on_sheet
    whole = oc.get(f"/studies/{k.STUDY}/edc/drafts").json()  # without a record: the flag is there too
    assert {d["item"]: d["covered"] for d in whole}["weight"] is False
