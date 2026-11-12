"""T-302c (D-434) copy-assist: the ``copy`` switch state, the sheet of signed values in the form's order, the
"copied" ticks bound to the value as signed, the version-1 rule, opt-outs and the audit. Synthetic data only
(``tests.edc_kit``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from edc import copyassist
from edc.store import EdcError

from tests import edc_kit as k

SHEET = {"text": "ward scale sheet", "day": "2026-11-05"}


def _copy_mode(svc: Any) -> None:
    k.ready(svc, on=False)
    if not svc.typed_reentry():
        svc.record_reentry(k.STUDY, pages=30, accuracy=0.985, document="DOC-REENTRY-1", by="admin")
    svc.set_switch(k.STUDY, True, by="pi", role="investigator", copy=True, reentry_pages=30, reentry_accuracy=0.985)


def _drafted(svc: Any) -> dict[str, dict[str, Any]]:
    built = svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc")
    return {d["item"]: d for d in built}


def _sign(svc: Any) -> dict[str, Any]:
    out: dict[str, Any] = svc.sign(k.STUDY, k.RECORD, "", signer="crc", printed_name="Chen Mei", role="coordinator",
                                   meaning="transcribed", meaning_text="I checked each value.", lang="en",
                                   seen=k.seen(svc), method="password")  # fmt: skip
    return out


def _events(svc: Any, name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted(Path(svc.audit.directory).glob("*.jsonl")):
        out += [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [e for e in out if e["event"] == name]


def _values(sheet: dict[str, Any]) -> list[dict[str, Any]]:
    return [v for r in sheet["records"] for vis in r["visits"] for f in vis["forms"] for v in f["values"]]


def test_copy_mode_drafts_and_signs_without_the_acknowledgement_and_never_sends(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc, on=False)
    with pytest.raises(EdcError, match="edc.off"):
        copyassist.sheet(svc, k.STUDY, k.RECORD, "crc")
    _copy_mode(svc)
    sw = svc.store.switch(k.STUDY)
    assert sw.state == "copy" and not sw.on and sw.drafting and sw.kind == ""
    d = _drafted(svc)
    svc.decide(k.STUDY, d["weight"]["id"], "confirm", by="crc")
    _sign(svc)
    for refused in (lambda: svc.send_redcap(k.STUDY, "crc"), lambda: svc.export_odm(k.STUDY, "crc")):
        with pytest.raises(EdcError, match="edc.off"):  # nothing is written to the sponsor's EDC
            refused()
    assert _events(svc, "edc.switch")[-1]["detail"]["state"] == "copy"
    # the re-entry result is still needed
    svc2, _, _ = k.service(tmp_path / "b")
    k.ready(svc2, on=False)
    with pytest.raises(EdcError):
        svc2.set_switch(k.STUDY, True, by="pi", role="investigator", copy=True, reentry_pages=3,
                        reentry_accuracy=0.5)  # fmt: skip


def test_the_sheet_shows_only_signed_values_in_the_form_order(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    _copy_mode(svc)
    d = _drafted(svc)
    for item in ("weight", "sex", "urate"):
        svc.decide(k.STUDY, d[item]["id"], "confirm", by="crc")
    _sign(svc)
    svc.decide(k.STUDY, d["mh_gout"]["id"], "confirm", by="crc")  # decided, not signed: never shown
    sheet = copyassist.sheet(svc, k.STUDY, k.RECORD, "crc")
    vals = _values(sheet)
    assert [v["item"] for v in vals] == ["sex", "weight", "urate"]  # demographics first, then the dictionary order
    assert [f["form"] for f in sheet["records"][0]["visits"][0]["forms"]] == ["demographics", "baseline"]
    assert all(v["signed_by"] == "Chen Mei" and v["citation"] for v in vals)
    assert {v["value"] for v in vals} == {"1", "72.5", "8.4"}
    visit = sheet["records"][0]["visits"][0]
    assert visit["waiting"] >= 1 and "mh_gout" not in {v["item"] for v in vals}
    view = _events(svc, "edc.copy_view")[-1]
    assert view["detail"] == {"record": k.RECORD, "format": "page", "values": 3, "records": 1}
    assert "72.5" not in json.dumps(_events(svc, "edc.copy_view"))  # never a value in the audit


def test_a_version_one_signature_is_never_a_source(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    _copy_mode(svc)
    d = _drafted(svc)
    svc.decide(k.STUDY, d["weight"]["id"], "confirm", by="crc")
    row = svc.store.draft(k.STUDY, d["weight"]["id"])
    assert row is not None
    shas = {int(row["id"]): row["sha"]}
    svc.store.db.execute("ALTER TABLE signature DROP CONSTRAINT signature_v2_only")  # D-461: the owner goes around it
    sid = svc.store.db.fetchval(
        "INSERT INTO signature (study, record, visit, signer, printed_name, role, meaning, meaning_text, lang, method, "
        "at, content_sha, drafts, sig_version, key_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
        (k.STUDY, k.RECORD, row["visit"], "crc", "Chen Mei", "coordinator", "transcribed", "x", "en", "password",
         "2026-11-01T00:00:00+00:00", k.old_unkeyed_sha(shas), json.dumps({str(row["id"]): row["sha"]}), 1, ""))  # fmt: skip
    svc.store.db.execute("UPDATE draft SET signature_id = ?, signed_sha = ? WHERE id = ?", (sid, row["sha"], row["id"]))
    assert svc.store.signed(k.STUDY, k.RECORD) == []  # D-461: the store refuses version 1 as well
    sheet = copyassist.sheet(svc, k.STUDY, k.RECORD, "crc")
    assert _values(sheet) == []
    with pytest.raises(EdcError, match="edc.tick_not_signed"):
        copyassist.tick(svc, k.STUDY, k.RECORD, [int(row["id"])], "copied", "crc")


def test_ticks_hold_for_the_value_as_signed(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    _copy_mode(svc)
    d = _drafted(svc)
    for item in ("weight", "sex"):
        svc.decide(k.STUDY, d[item]["id"], "confirm", by="crc")
    _sign(svc)
    wid = int(d["weight"]["id"])
    # an unsigned value, or one of no sheet, refuses the whole request (audited)
    with pytest.raises(EdcError, match="edc.tick_not_signed"):
        copyassist.tick(svc, k.STUDY, k.RECORD, [wid, int(d["urate"]["id"])], "copied", "crc")
    assert svc.store.ticks(k.STUDY) == []
    assert _events(svc, "edc.copy_tick")[-1]["detail"]["refused"] == "edc.tick_not_signed"
    copyassist.tick(svc, k.STUDY, k.RECORD, [wid], "copied", "crc")
    vals = {v["item"]: v for v in _values(copyassist.sheet(svc, k.STUDY, k.RECORD, "crc"))}
    assert vals["weight"]["copied"] == {"by": "crc", "at": k.STAMP.isoformat(timespec="seconds")}
    assert vals["sex"]["copied"] is None
    with pytest.raises(EdcError, match="edc.reason"):
        copyassist.tick(svc, k.STUDY, k.RECORD, [wid], "undone", "crc")
    copyassist.tick(svc, k.STUDY, k.RECORD, [wid], "undone", "crc", reason="typed in the wrong visit")
    vals = {v["item"]: v for v in _values(copyassist.sheet(svc, k.STUDY, k.RECORD, "crc"))}
    assert vals["weight"]["copied"] is None
    copyassist.tick(svc, k.STUDY, k.RECORD, [wid], "copied", "crc")
    # the value changes after signing and is signed again: the old tick no longer holds, and is listed
    svc.decide(k.STUDY, wid, "edit", value="73", reason="re-read", citation=SHEET, by="crc", unlock=True)
    _sign(svc)
    vals = {v["item"]: v for v in _values(copyassist.sheet(svc, k.STUDY, k.RECORD, "crc"))}
    assert vals["weight"]["value"] == "73" and vals["weight"]["copied"] is None
    assert [e["action"] for e in vals["weight"]["earlier"]] == ["copied", "undone", "copied"]
    for stmt in ("UPDATE copy_tick SET at = 'x'", "DELETE FROM copy_tick", "TRUNCATE copy_tick"):
        with pytest.raises(Exception, match="append-only"):
            svc.store.db.execute(stmt)


def test_an_opted_out_patient_is_never_on_a_sheet(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    _copy_mode(svc)
    d = _drafted(svc)
    svc.decide(k.STUDY, d["weight"]["id"], "confirm", by="crc")
    _sign(svc)
    assert len(_values(copyassist.sheet(svc, k.STUDY, None, "crc"))) == 1
    svc.optouts = lambda: frozenset({k.PID})
    with pytest.raises(EdcError, match="edc.opted_out"):
        copyassist.sheet(svc, k.STUDY, k.RECORD, "crc")
    with pytest.raises(EdcError, match="edc.opted_out"):
        copyassist.tick(svc, k.STUDY, k.RECORD, [int(d["weight"]["id"])], "copied", "crc")
    whole = copyassist.sheet(svc, k.STUDY, None, "crc", "csv")
    assert whole["records"] == [] and whole["values"] == 0
