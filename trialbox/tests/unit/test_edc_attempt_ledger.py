"""NEW-EDC-8 (D-691, deep-review EDC-008): every write REDCap applied has a line in TrialBox's ledger, under the
person who made it.

The send wrote its ledger lines only after REDCap's answer and the read-back. When REDCap applied the import and the
answer was lost (a timeout, the rate limit hit on the read-back), the ledger was empty and the audit line said
"refused"; the next send found the values there and booked them `already_there` under whoever retried. The trail
could not say who wrote the value into the EDC of record, nor when. Synthetic data only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from edc.store import EdcError
from rc_bridge.client import RcError, RedcapClient

from tests import edc_kit as k
from tests.unit.test_edc_t302b import AE1, SCREEN1, SHEET, WEEK4_1, _drafts, _edit_in_redcap, _enter, _rows, _service


def _lost_after_import(monkeypatch: pytest.MonkeyPatch, code: str = "RC-UPSTREAM") -> None:
    """REDCap applies the import; the answer never reaches TrialBox (once)."""
    real = RedcapClient.import_records
    calls = {"n": 0}

    def flaky(self: RedcapClient, *a: Any, **kw: Any) -> Any:
        got = real(self, *a, **kw)
        calls["n"] += 1
        if calls["n"] == 1:
            raise RcError(code, "the answer was lost (ReadTimeout)")
        return got

    monkeypatch.setattr(RedcapClient, "import_records", flaky)


def _sent(svc: Any, record: str = "S-001") -> list[dict[str, Any]]:
    return [dict(s) for s in svc.trail(k.STUDY, record)["sent"]]


def test_a_write_redcap_applied_but_whose_answer_was_lost_is_in_the_ledger_under_its_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, sim, token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight", "urate"}))
    _lost_after_import(monkeypatch)
    with pytest.raises(EdcError):
        svc.send_redcap(k.STUDY, "crc")
    assert _rows(sim, token)[("1", SCREEN1, "", "")]["weight"] == "72.5"  # REDCap holds it
    first = _sent(svc)
    assert {(s["item"], s["result"], s["by_user"]) for s in first} >= {("weight", "attempt", "crc"),
                                                                         ("urate", "attempt", "crc")}  # fmt: skip
    # someone else sends later: the values are TrialBox's write of the first attempt, under its writer and time
    out = svc.send_redcap(k.STUDY, "monitor")
    assert {x["item"] for x in out["sent"]} == {"weight", "urate"} and out["already_there"] == []
    last = {s["item"]: s for s in _sent(svc) if s["result"] == "sent"}
    assert last["weight"]["by_user"] == "crc" and last["weight"]["at"] == first[0]["at"]
    assert "monitor" in last["weight"]["detail"]  # who read it back, and that it was the earlier attempt
    again = svc.send_redcap(k.STUDY, "crc")
    assert again["count"] == 0


def test_an_attempt_redcap_did_not_apply_is_written_again_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, sim, token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))

    def refused(self: RedcapClient, *a: Any, **kw: Any) -> Any:
        raise RcError("RC-RATE", "too many calls")

    with monkeypatch.context() as m:
        m.setattr(RedcapClient, "import_records", refused)
        with pytest.raises(EdcError):
            svc.send_redcap(k.STUDY, "crc")
    assert "weight" not in _rows(sim, token).get(("1", SCREEN1, "", ""), {}) or not _rows(sim, token)[
        ("1", SCREEN1, "", "")].get("weight")  # fmt: skip
    out = svc.send_redcap(k.STUDY, "monitor")
    assert {x["item"] for x in out["sent"]} == {"weight"}
    sent = [s for s in _sent(svc) if s["result"] == "sent"]
    assert sent[-1]["by_user"] == "monitor"  # this send wrote it


def test_a_person_s_value_equal_to_trialboxs_with_no_attempt_stays_already_there(tmp_path: Path) -> None:
    """Only TrialBox's own attempt becomes `sent`: a value a person entered that happens to equal TrialBox's is
    REDCap's already, as before."""
    svc, sim, _token, pid = _service(tmp_path)
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "weight": "72.5"})
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    out = svc.send_redcap(k.STUDY, "crc")
    assert {x["item"] for x in out["already_there"]} == {"weight"} and out["sent"] == []


def test_a_lost_answer_on_a_repeat_instance_does_not_make_trialboxs_own_instance_anothers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With NEW-EDC-2, an instance holding a value with no `sent` line was "someone else's": TrialBox's own write
    whose answer was lost would have held its instance for good. The attempt counts as TrialBox's write."""
    svc, sim, token, _pid = _service(tmp_path)
    _enter(svc, "S-001", AE1, {"ae_term": "gout flare", "ae_serious": "0"})
    _lost_after_import(monkeypatch)
    with pytest.raises(EdcError):
        svc.send_redcap(k.STUDY, "crc")
    out = svc.send_redcap(k.STUDY, "crc")
    assert out["instance_taken"] == [] and {x["item"] for x in out["sent"]} == {"ae_term", "ae_serious"}
    assert _rows(sim, token)[("1", WEEK4_1, "ae", "1")]["ae_term"] == "gout flare"


def test_an_import_redcap_applied_whose_read_back_was_refused_is_in_the_ledger_under_its_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rate limit can land the import and refuse the read-back: the same, the write has its line."""
    svc, sim, token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    real_import, real_records = RedcapClient.import_records, RedcapClient.records
    state = {"imported": False, "refused": False}

    def importing(self: RedcapClient, *a: Any, **kw: Any) -> Any:
        state["imported"] = True
        return real_import(self, *a, **kw)

    def reading(self: RedcapClient, *a: Any, **kw: Any) -> Any:
        if state["imported"] and not state["refused"]:
            state["refused"] = True
            raise RcError("RC-RATE", "too many calls")
        return real_records(self, *a, **kw)

    with monkeypatch.context() as m:
        m.setattr(RedcapClient, "import_records", importing)
        m.setattr(RedcapClient, "records", reading)
        with pytest.raises(EdcError):
            svc.send_redcap(k.STUDY, "crc")
    assert state["refused"] and _rows(sim, token)[("1", SCREEN1, "", "")]["weight"] == "72.5"
    out = svc.send_redcap(k.STUDY, "monitor")
    assert {x["item"] for x in out["sent"]} == {"weight"}
    assert [s["by_user"] for s in _sent(svc) if s["result"] == "sent"] == ["crc"]


def test_a_value_changed_after_a_lost_answer_is_held_as_the_value_redcap_holds_may_be_a_persons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REDCap holds the attempt's value and the value was changed in TrialBox since. TrialBox cannot tell its own
    lost write from a person's equal entry (review finding 1), so it is held as a conflict, never overwritten; the
    field that did not change landed and is booked under its writer."""
    svc, sim, token, _pid = _service(tmp_path)
    _enter(svc, "S-001", AE1, {"ae_term": "gout flare", "ae_serious": "0"})
    _lost_after_import(monkeypatch)
    with pytest.raises(EdcError):
        svc.send_redcap(k.STUDY, "crc")
    _correct(svc, "S-001", AE1, "ae_term", "acute gout flare")
    out = svc.send_redcap(k.STUDY, "monitor")
    assert {x["item"] for x in out["conflict"]} == {"ae_term"}
    assert _rows(sim, token)[("1", WEEK4_1, "ae", "1")]["ae_term"] == "gout flare"
    term = [(s["value"], s["result"], s["by_user"]) for s in _sent(svc) if s["item"] == "ae_term"]
    assert term == [("gout flare", "attempt", "crc"), ("acute gout flare", "conflict", "monitor")]
    assert [(s["result"], s["by_user"]) for s in _sent(svc) if s["item"] == "ae_serious"][-1] == ("sent", "crc")


def _correct(svc: Any, record: str, visit: str, item: str, value: str) -> None:
    """The coordinator re-authenticates, corrects a signed value, signs again."""
    d = _drafts(svc, record, visit)[item]
    svc.decide(k.STUDY, d["id"], "edit", value=value, reason="the source says so", citation=SHEET, by="crc",
               unlock=True)  # fmt: skip
    svc.sign(k.STUDY, record, visit, signer="crc", printed_name="Chen Mei", role="coordinator", meaning="transcribed",
             meaning_text="I checked each value.", lang="en", seen=k.seen(svc, record, visit))  # fmt: skip


def test_a_persons_value_equal_to_a_refused_attempt_is_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding 1: the import was refused (not applied), the coordinator typed the same value into REDCap by
    hand, then corrected it in TrialBox. REDCap's value may be the person's: it is held as a conflict, not
    overwritten, and not booked as TrialBox's write."""
    svc, sim, token, pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))

    def refused(self: RedcapClient, *a: Any, **kw: Any) -> Any:
        raise RcError("RC-RATE", "too many calls")

    with monkeypatch.context() as m:
        m.setattr(RedcapClient, "import_records", refused)
        with pytest.raises(EdcError):
            svc.send_redcap(k.STUDY, "crc")
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "weight": "72.5"})
    _correct(svc, "S-001", SCREEN1, "weight", "73.5")
    out = svc.send_redcap(k.STUDY, "monitor")
    assert {x["item"] for x in out["conflict"]} == {"weight"} and out["sent"] == []
    assert _rows(sim, token)[("1", SCREEN1, "", "")]["weight"] == "72.5"  # the person's value stays
    assert [s for s in _sent(svc) if s["result"] == "sent"] == []


def test_a_landed_attempt_on_an_instance_a_person_changed_since_is_still_booked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding 2: TrialBox's write landed (answer lost), then a person changed another field of the instance.
    The instance is held, and TrialBox's landed write is still in the ledger under its writer."""
    svc, sim, _token, pid = _service(tmp_path)
    _enter(svc, "S-001", AE1, {"ae_term": "gout flare", "ae_serious": "0"})
    _lost_after_import(monkeypatch)
    with pytest.raises(EdcError):
        svc.send_redcap(k.STUDY, "crc")
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": WEEK4_1, "redcap_repeat_instrument": "ae",
                               "redcap_repeat_instance": "1", "ae_serious": "1"})  # fmt: skip
    out = svc.send_redcap(k.STUDY, "monitor")
    assert out["sent"] == [] and {x["item"] for x in out["conflict"] + out["instance_taken"]} == {"ae_term",
                                                                                                  "ae_serious"}  # fmt: skip
    booked = {(s["item"], s["by_user"]) for s in _sent(svc) if s["result"] == "sent"}
    assert booked == {("ae_term", "crc")}  # REDCap holds its value; ae_serious holds the person's, nothing to read back
