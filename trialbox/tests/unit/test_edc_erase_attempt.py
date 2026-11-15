"""NEW-EDC-8c (D-614, D-691's known limit): an erase REDCap applied but whose answer was lost is TrialBox's.

"Erase hidden values" wrote its ledger line only after REDCap's answer. An erase that applied with its answer lost
left the item as TrialBox last wrote it in the ledger, while REDCap held blank: on a repeat instance that made the
instance "someone else's" (D-690) for good. The erase now writes an attempt line first, as the send does (D-691), and
the next send books the erase under its writer. Synthetic data only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from edc.store import EdcError
from rc_bridge.client import RcError, RedcapClient

from tests import edc_kit as k
from tests.unit.test_edc_attempt_ledger import _correct
from tests.unit.test_edc_t302b import AE2, WEEK4_1, _edit_in_redcap, _enter, _rows, _service


def _sent(svc: Any) -> list[dict[str, Any]]:
    return [dict(s) for s in svc.trail(k.STUDY, "S-001")["sent"]]


def _lost_erase(svc: Any, sim: Any, token: str, pid: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """AE2 sent; REDCap made non-serious by a person; the erase of the hidden reason applies, its answer is lost."""
    _enter(svc, "S-001", AE2, {"ae_term": "rash", "ae_serious": "1", "ae_sae_reason": "hospitalised"})
    svc.send_redcap(k.STUDY, "crc")
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": WEEK4_1, "redcap_repeat_instrument": "ae",
                               "redcap_repeat_instance": "2", "ae_serious": "0"})  # fmt: skip
    real = RedcapClient.import_records

    def lost(self: RedcapClient, *a: Any, **kw: Any) -> Any:
        real(self, *a, **kw)
        raise RcError("RC-UPSTREAM", "REDCap did not answer (ReadTimeout)")

    with monkeypatch.context() as m:
        m.setattr(RedcapClient, "import_records", lost)
        with pytest.raises(EdcError):
            svc.erase_hidden(k.STUDY, "S-001", AE2, "crc")
    assert _rows(sim, token)[("1", WEEK4_1, "ae", "2")]["ae_sae_reason"] == ""  # REDCap took the erase


def test_an_erase_is_in_the_ledger_before_redcap_answers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    svc, sim, token, pid = _service(tmp_path)
    _lost_erase(svc, sim, token, pid, monkeypatch)
    reason = [(s["result"], s["by_user"], s["value"]) for s in _sent(svc) if s["item"] == "ae_sae_reason"]
    assert reason[-1] == ("attempt", "crc", "")


def test_a_lost_erase_is_never_booked_as_trialboxs_a_blank_may_be_a_persons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review: TrialBox cannot tell its lost erase from a person clearing the field; booking it would let a later
    send write into a person's instance. Nothing is booked: the next send and a reconcile write no `erased` line,
    and the change stays listed for a person."""
    svc, _sim, _token, _pid = _lost_erase_and(tmp_path, monkeypatch)
    svc.send_redcap(k.STUDY, "monitor")
    got = svc.reconcile(k.STUDY, "monitor")
    after = [s["result"] for s in _sent(svc) if s["item"] == "ae_sae_reason"]
    assert "erased" not in after and ("S-001", "ae_sae_reason") in {(x["record"], x["item"]) for x in got}


def test_an_erase_attempt_is_never_taken_for_a_landed_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The review: a blank attempt read back blank made the send book a `sent` line with a blank value and set the
    draft's sent value to blank. An erase attempt is not a write of TrialBox's value."""
    svc, sim, token, _pid = _lost_erase_and(tmp_path, monkeypatch)
    _correct(svc, "S-001", AE2, "ae_sae_reason", "admitted overnight")
    svc.send_redcap(k.STUDY, "crc")
    lines = [(s["result"], s["value"]) for s in _sent(svc) if s["item"] == "ae_sae_reason"]
    assert ("sent", "") not in lines
    d = next(x for x in svc.store.drafts(k.STUDY, "S-001", AE2) if x["item"] == "ae_sae_reason")
    assert d["sent_value"] != ""
    assert _rows(sim, token)[("1", WEEK4_1, "ae", "2")]["ae_sae_reason"] == ""  # the instance is held, not written


def _lost_erase_and(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, str, int]:
    svc, sim, token, pid = _service(tmp_path)
    _lost_erase(svc, sim, token, pid, monkeypatch)
    return svc, sim, token, pid


def test_an_erase_redcap_refused_is_ledgered_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    svc, sim, _token, pid = _service(tmp_path)
    _enter(svc, "S-001", AE2, {"ae_term": "rash", "ae_serious": "1", "ae_sae_reason": "hospitalised"})
    svc.send_redcap(k.STUDY, "crc")
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": WEEK4_1, "redcap_repeat_instrument": "ae",
                               "redcap_repeat_instance": "2", "ae_serious": "0"})  # fmt: skip

    def refused(self: RedcapClient, *a: Any, **kw: Any) -> Any:
        raise RcError("RC-UPSTREAM", "REDCap returned 400: a form of the record is locked", refused=True)

    with monkeypatch.context() as m:
        m.setattr(RedcapClient, "import_records", refused)
        with pytest.raises(EdcError):
            svc.erase_hidden(k.STUDY, "S-001", AE2, "crc")
    assert [s["result"] for s in _sent(svc) if s["item"] == "ae_sae_reason"][-2:] == ["attempt", "refused"]
