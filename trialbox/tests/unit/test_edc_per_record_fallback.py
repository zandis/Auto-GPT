"""NEW-EDC-7 (D-692, deep-review EDC-007): one refused record does not stop the study's send.

One import call carried every record. REDCap refuses an import whole: one locked form (or one value REDCap's rules
refuse) and no subject of the study was written; the send said only "refused". Now a refused import of several
records is sent again one record at a time; each record REDCap refuses is ledgered `refused` with the kind of
error (never REDCap's text, D-555), the others are written. Case 2b of the review. Synthetic data only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import rc_sim.app as sim_app
from edc.store import EdcError
from rc_bridge.client import RcError, RedcapClient, error_kind

from tests import edc_kit as k
from tests.unit.test_edc_t302b import AE1, SCREEN1, SCREEN2, WEEK4_1, _edit_in_redcap, _enter, _rows, _service

LOCKED = "This record ('1') cannot be imported: the instrument baseline is locked for record '1'"


def _lock_record_1(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """REDCap refuses any import that holds a row of record 1 (its form is locked); the calls are kept."""
    real = sim_app._import_records
    calls: list[list[str]] = []

    def locked(proj: dict[str, Any], form: Any) -> Any:
        rows = json.loads(str(form.get("data")))
        calls.append(sorted({str(r.get("record_id")) for r in rows}))
        if any(str(r.get("record_id")) == "1" for r in rows):
            return sim_app._err(400, LOCKED)
        return real(proj, form)

    monkeypatch.setattr(sim_app, "_import_records", locked)
    return calls


def _two_subjects(tmp_path: Path) -> tuple[Any, Any, str, int]:
    svc, sim, token, pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight", "urate"}))
    _enter(svc, "S-002", SCREEN2, {}, confirm=frozenset({"weight"}))
    return svc, sim, token, pid


def test_one_locked_record_does_not_stop_the_other_subjects_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, sim, token, _pid = _two_subjects(tmp_path)
    calls = _lock_record_1(monkeypatch)
    out = svc.send_redcap(k.STUDY, "crc")
    assert {(x["record"], x["item"]) for x in out["sent"]} == {("S-002", "weight")}
    assert {(x["record"], x["item"]) for x in out["refused"]} == {("S-001", "weight"), ("S-001", "urate")}
    assert calls[0] == ["1", "2"] and sorted(calls[1:]) == [["1"], ["2"]]  # the batch, then one record at a time
    assert _rows(sim, token)[("2", SCREEN2, "", "")]["weight"] == "72.5"
    assert not _rows(sim, token)[("1", SCREEN1, "", "")].get("weight")
    lines = [dict(s) for s in svc.trail(k.STUDY, "S-001")["sent"] if s["result"] == "refused"]
    assert {s["item"] for s in lines} == {"weight", "urate"}
    assert all("locked" in s["detail"] and "'1'" not in s["detail"] for s in lines)  # the kind, not REDCap's text


def test_when_every_record_is_refused_the_send_is_refused_loudly_and_each_is_ledgered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, _sim, _token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    _lock_record_1(monkeypatch)
    with pytest.raises(EdcError) as e:
        svc.send_redcap(k.STUDY, "crc")
    assert e.value.code == "RC-UPSTREAM" and "locked" in str(e.value)
    assert [s["result"] for s in svc.trail(k.STUDY, "S-001")["sent"]][-1] == "refused"


def test_a_refused_record_is_written_on_a_later_send_once_redcap_takes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, sim, token, _pid = _two_subjects(tmp_path)
    with monkeypatch.context() as m:
        _lock_record_1(m)
        svc.send_redcap(k.STUDY, "crc")
    out = svc.send_redcap(k.STUDY, "monitor")  # the form was unlocked
    assert {(x["record"], x["item"]) for x in out["sent"]} == {("S-001", "weight"), ("S-001", "urate")}
    assert _rows(sim, token)[("1", SCREEN1, "", "")]["weight"] == "72.5"


def test_a_refusal_closes_the_attempt_a_persons_equal_value_is_theirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REDCap said no: nothing of the import applied. A value a person then types into REDCap is theirs, never booked
    as TrialBox's write of the refused attempt (D-691)."""
    svc, sim, _token, pid = _two_subjects(tmp_path)
    with monkeypatch.context() as m:
        _lock_record_1(m)
        svc.send_redcap(k.STUDY, "crc")
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "weight": "72.5"})
    out = svc.send_redcap(k.STUDY, "monitor")
    assert {(x["record"], x["item"]) for x in out["already_there"]} == {("S-001", "weight")}


def test_no_answer_from_redcap_is_not_a_refusal_and_is_not_sent_again_record_by_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lost answer may have applied: sending again would hide that. The send fails as before (D-691 reads it back
    next time)."""
    svc, _sim, _token, _pid = _two_subjects(tmp_path)
    n = {"calls": 0}

    def lost(self: RedcapClient, *a: Any, **kw: Any) -> Any:
        n["calls"] += 1
        raise RcError("RC-UPSTREAM", "REDCap did not answer (ReadTimeout)")

    monkeypatch.setattr(RedcapClient, "import_records", lost)
    with pytest.raises(EdcError):
        svc.send_redcap(k.STUDY, "crc")
    assert n["calls"] == 1


def test_the_client_says_when_redcap_refused_and_when_it_did_not_answer() -> None:
    def answer(status: int, body: dict[str, Any]) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(status, json=body)))

    token = "0" * 32
    with pytest.raises(RcError) as e:
        RedcapClient("https://redcap.example", token, http=answer(400, {"error": LOCKED})).import_records([{"a": "1"}])
    assert e.value.refused and "locked" in e.value.message and "'1'" not in e.value.message

    def boom(_r: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    c = RedcapClient("https://redcap.example", token, http=httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(RcError) as e:
        c.import_records([{"a": "1"}])
    assert not e.value.refused
    for status in (403, 429, 500, 503):
        with pytest.raises(RcError) as e:
            RedcapClient("https://redcap.example", token, http=answer(status, {"error": "x"})).import_records(
                [{"a": "1"}])  # fmt: skip
        assert not e.value.refused, status
    assert error_kind(LOCKED) == "a form of the record is locked"


def test_the_consoles_send_page_counts_refused_values() -> None:
    from console import edc_pages
    from console.i18n_edc import EN, JA, ZH

    assert "refused" in edc_pages.SEND_RESULTS
    for lang in (EN, JA, ZH):
        assert "edc.result.refused" in lang and "edc.sent_refused" in lang


def test_a_refusal_is_ledgered_even_when_a_later_record_gets_no_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding: record 1 refused, then record 2's call failed (a server error). The refusal is still in the
    ledger, so a value a person types afterwards is theirs, not TrialBox's "lost" write (D-691)."""
    svc, sim, _token, pid = _two_subjects(tmp_path)
    real = sim_app._import_records

    def locked_then_down(proj: dict[str, Any], form: Any) -> Any:
        recs = {str(r.get("record_id")) for r in json.loads(str(form.get("data")))}
        if "1" in recs:
            return sim_app._err(400, LOCKED)
        return sim_app._err(500, "server error")

    with monkeypatch.context() as m:
        m.setattr(sim_app, "_import_records", locked_then_down)
        with pytest.raises(EdcError):
            svc.send_redcap(k.STUDY, "crc")
    assert [s["result"] for s in svc.trail(k.STUDY, "S-001")["sent"]][-1] == "refused"
    assert real is sim_app._import_records
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "weight": "72.5"})
    out = svc.send_redcap(k.STUDY, "monitor")
    assert ("S-001", "weight") in {(x["record"], x["item"]) for x in out["already_there"]}


def test_a_refused_row_does_not_hold_the_same_subjects_other_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding: the retry is by row (record, event, instrument, instance), so a locked screening form does not
    hold the subject's adverse event."""
    svc, sim, token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    _enter(svc, "S-001", AE1, {"ae_term": "gout flare", "ae_serious": "0"})
    real = sim_app._import_records

    def screening_locked(proj: dict[str, Any], form: Any) -> Any:
        rows = json.loads(str(form.get("data")))
        if any(r.get("redcap_event_name") == SCREEN1 for r in rows):
            return sim_app._err(400, LOCKED)
        return real(proj, form)

    monkeypatch.setattr(sim_app, "_import_records", screening_locked)
    out = svc.send_redcap(k.STUDY, "crc")
    assert {x["item"] for x in out["refused"]} == {"weight"}
    assert {x["item"] for x in out["sent"]} == {"ae_term", "ae_serious"}
    assert _rows(sim, token)[("1", WEEK4_1, "ae", "1")]["ae_term"] == "gout flare"


def test_a_partly_refused_send_is_not_audited_as_a_refused_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding: an audit line's `refused` is the code of a send REDCap refused; a send that wrote some records
    counts its refused values under another name."""
    svc, _sim, _token, _pid = _two_subjects(tmp_path)
    _lock_record_1(monkeypatch)
    seen: list[dict[str, Any]] = []
    real = svc._audit
    monkeypatch.setattr(svc, "_audit", lambda ev, rs, by, detail: (seen.append(detail), real(ev, rs, by, detail)))
    svc.send_redcap(k.STUDY, "crc")
    line = [d for d in seen if "target" in d][-1]
    assert "refused" not in line and line["records_refused"] == 2 and line["sent"] == 1


def test_a_lock_sentence_naming_a_repeating_instrument_is_still_a_lock() -> None:
    assert error_kind("the repeating instrument ae is locked for record '1'") == "a form of the record is locked"
