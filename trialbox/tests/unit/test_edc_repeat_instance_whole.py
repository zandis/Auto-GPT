"""NEW-EDC-2 (D-690, deep-review EDC-002, Critical): a repeat instance is written whole or not at all.

On a repeating instrument the send judged each field alone: a person's instance 2 holding `ae_term=Rash` gave a
conflict on `ae_term`, and TrialBox still wrote `ae_serious=1` and `ae_sae_reason=hospitalised` into it, with a
"sent, read back equal" line. A human-entered adverse event became a serious one with another event's reason, in
the EDC of record. An instance that holds anything TrialBox did not write is now another person's (or another
event's): nothing of TrialBox's is written into it. Synthetic data only (the kit of ``test_edc_t302b``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests import edc_kit as k
from tests.unit.test_edc_t302b import AE1, AE2, CRF, WEEK4_1, _edit_in_redcap, _enter, _held, _rows, _service

CRF_ONSET: list[dict[str, str]] = [
    *CRF,
    {"field_name": "ae_onset", "form_name": "ae", "field_type": "text", "field_label": "Onset (typed in REDCap)",
     "text_validation_type_or_show_slider_number": "date_ymd"},
]  # fmt: skip


def _instance(sim: Any, token: str, n: str) -> dict[str, str]:
    return _rows(sim, token)[("1", WEEK4_1, "ae", n)]


def test_a_persons_instance_gets_nothing_of_trialboxs_other_event(tmp_path: Path) -> None:
    """The review's case 8a."""
    svc, sim, token, pid = _service(tmp_path)
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": WEEK4_1, "redcap_repeat_instrument": "ae",
                               "redcap_repeat_instance": "2", "ae_term": "Rash"})  # fmt: skip
    _enter(svc, "S-001", AE2, {"ae_term": "Headache", "ae_serious": "1", "ae_sae_reason": "hospitalised"})
    out = svc.send_redcap(k.STUDY, "crc")
    assert _held(out, "conflict") == {(AE2, "ae_term")}
    assert _held(out, "instance_taken") == {(AE2, "ae_serious"), (AE2, "ae_sae_reason")}
    assert out["sent"] == []
    row = _instance(sim, token, "2")
    assert (row["ae_term"], row["ae_serious"], row["ae_sae_reason"]) == ("Rash", "", "")  # untouched
    trail = svc.trail(k.STUDY, "S-001")
    said = [s for s in trail["sent"] if s.get("result") == "instance_taken"]
    assert len(said) == 2 and all("did not write" in str(s.get("detail") or s.get("note") or "") for s in said), said


def test_a_field_trialbox_does_not_send_also_makes_the_instance_anothers(tmp_path: Path) -> None:
    """A person filled only a field TrialBox has no value for: no field-level conflict at all, and before this card
    every TrialBox value went into that person's instance."""
    svc, sim, token, pid = _service(tmp_path, crf=CRF_ONSET)
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": WEEK4_1, "redcap_repeat_instrument": "ae",
                               "redcap_repeat_instance": "2", "ae_onset": "2026-10-30"})  # fmt: skip
    _enter(svc, "S-001", AE2, {"ae_term": "Headache", "ae_serious": "0"})
    out = svc.send_redcap(k.STUDY, "crc")
    assert out["conflict"] == [] and out["sent"] == []
    assert _held(out, "instance_taken") == {(AE2, "ae_term"), (AE2, "ae_serious")}
    row = _instance(sim, token, "2")
    assert (row["ae_onset"], row["ae_term"], row["ae_serious"]) == ("2026-10-30", "", "")


def test_an_empty_instance_and_one_trialbox_wrote_itself_are_written(tmp_path: Path) -> None:
    svc, sim, token, _pid = _service(tmp_path)
    _enter(svc, "S-001", AE1, {"ae_term": "gout flare", "ae_serious": "0"})
    out = svc.send_redcap(k.STUDY, "crc")
    assert _held(out, "sent") == {(AE1, "ae_term"), (AE1, "ae_serious")} and out["instance_taken"] == []
    # the same instance again: everything on it is TrialBox's own, so nothing is held for the instance
    again = svc.send_redcap(k.STUDY, "crc")
    assert again["count"] == 0 and again["instance_taken"] == []
    row = _instance(sim, token, "1")
    assert (row["ae_term"], row["ae_serious"]) == ("gout flare", "0")


def test_a_base_row_is_still_judged_field_by_field(tmp_path: Path) -> None:
    """Only a repeat instance is one unit: on a visit's base row a person's value on one field holds that field."""
    svc, sim, _token, pid = _service(tmp_path)
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": "screening_arm_1", "weight": "80"})
    from tests.unit.test_edc_t302b import SCREEN1

    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight", "urate", "brthdat", "sex"}))
    out = svc.send_redcap(k.STUDY, "crc")
    assert _held(out, "conflict") == {(SCREEN1, "weight")}
    assert {x["item"] for x in out["sent"]} == {"urate", "brthdat", "sex"} and out["instance_taken"] == []
