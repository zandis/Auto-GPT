"""NEW-EDC-5 (D-695, deep-review EDC-005): a value TrialBox sent and a person later changed in REDCap is listed.

`sendable` drops a value once it is sent as it is, so it was never read again: the review page, the ODM export, the
SDV and copy-assist sheets went on showing TrialBox's value after a person corrected it in REDCap (case 1a). Now each
send (and a reconcile call) reads REDCap for every value TrialBox wrote and lists each one REDCap holds differently,
with both values, and a `changed_in_redcap` line in the ledger (once per change). Taking REDCap's value is an edit
with a reason, as before; keeping TrialBox's leaves the change listed. Synthetic data only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests import edc_kit as k
from tests.unit.test_edc_attempt_ledger import _correct
from tests.unit.test_edc_t302b import SCREEN1, _edit_in_redcap, _enter, _held, _service


def _changed(svc: Any) -> list[dict[str, Any]]:
    return [dict(s) for s in svc.trail(k.STUDY, "S-001")["sent"] if s["result"] == "changed_in_redcap"]


def test_a_value_a_person_changed_in_redcap_after_the_send_is_listed_with_both_values(tmp_path: Path) -> None:
    svc, sim, _token, pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight", "urate"}))
    assert _held(svc.send_redcap(k.STUDY, "crc"), "sent") == {(SCREEN1, "weight"), (SCREEN1, "urate")}
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "weight": "70.1"})
    got = svc.reconcile(k.STUDY, "monitor")
    assert [(x["record"], x["item"], x["trialbox"], x["redcap"]) for x in got] == [("S-001", "weight", "72.5", "70.1")]
    lines = _changed(svc)
    assert [(s["item"], s["by_user"]) for s in lines] == [("weight", "monitor")] and "70.1" in lines[0]["detail"]


def test_each_send_lists_the_changes_and_writes_one_line_per_change(tmp_path: Path) -> None:
    svc, sim, _token, pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    svc.send_redcap(k.STUDY, "crc")
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "weight": "70.1"})
    out = svc.send_redcap(k.STUDY, "crc")
    assert _held(out, "changed_in_redcap") == {(SCREEN1, "weight")}
    svc.send_redcap(k.STUDY, "crc")
    assert len(_changed(svc)) == 1  # the same change read again: no new line
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "weight": "69.0"})
    svc.reconcile(k.STUDY, "crc")
    assert len(_changed(svc)) == 2


def test_taking_redcaps_value_is_an_edit_with_a_reason_and_then_nothing_is_listed(tmp_path: Path) -> None:
    svc, sim, _token, pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    svc.send_redcap(k.STUDY, "crc")
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "weight": "70.1"})
    assert svc.reconcile(k.STUDY, "crc")
    _correct(svc, "S-001", SCREEN1, "weight", "70.1")
    out = svc.send_redcap(k.STUDY, "crc")
    assert out["changed_in_redcap"] == [] and _held(out, "already_there") == {(SCREEN1, "weight")}
    assert svc.reconcile(k.STUDY, "crc") == []


def test_a_value_never_sent_or_found_already_there_is_not_listed(tmp_path: Path) -> None:
    svc, sim, _token, pid = _service(tmp_path)
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "weight": "72.5"})
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    svc.send_redcap(k.STUDY, "crc")  # already there: the person's value, not TrialBox's write (D-693)
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "weight": "70.1"})
    assert svc.reconcile(k.STUDY, "crc") == []


def test_reconcile_is_audited_and_reads_only_the_record_asked(tmp_path: Path) -> None:
    svc, sim, _token, pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    svc.send_redcap(k.STUDY, "crc")
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "weight": "70.1"})
    assert svc.reconcile(k.STUDY, "crc", record="S-002") == []
    seen: list[tuple[str, dict[str, Any]]] = []
    real = svc._audit

    def spy(ev: str, rs: str, by: str, detail: dict[str, Any]) -> None:
        seen.append((ev, detail))
        real(ev, rs, by, detail)

    svc._audit = spy  # type: ignore[method-assign,assignment]
    svc.reconcile(k.STUDY, "crc", record="S-001")
    assert seen[-1][0] == "edc.reconciled" and seen[-1][1]["changed_in_redcap"] == 1


def test_the_consoles_send_page_counts_changes_in_redcap() -> None:
    from console import edc_pages
    from console.i18n_edc import EN, JA, ZH

    assert "changed_in_redcap" in edc_pages.SEND_RESULTS
    for lang in (EN, JA, ZH):
        assert {"edc.result.changed_in_redcap", "edc.sent_changed_in_redcap"} <= set(lang)


# ------------------------------------------------------------------ the adversarial review
def test_trialboxs_own_erase_is_not_a_change_in_redcap(tmp_path: Path) -> None:
    """Review finding 1: an erase of a hidden value TrialBox wrote is TrialBox's own write."""
    from tests.unit.test_edc_t302b import AE2, WEEK4_1

    svc, sim, _token, pid = _service(tmp_path)
    _enter(svc, "S-001", AE2, {"ae_term": "rash", "ae_serious": "1", "ae_sae_reason": "hospitalised"})
    svc.send_redcap(k.STUDY, "crc")
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": WEEK4_1, "redcap_repeat_instrument": "ae",
                               "redcap_repeat_instance": "2", "ae_serious": "0"})  # fmt: skip
    assert svc.erase_hidden(k.STUDY, "S-001", AE2, "crc")["erased"] == ["ae_sae_reason"]
    assert {x["item"] for x in svc.reconcile(k.STUDY, "crc")} == {"ae_serious"}  # the person's change only


def test_a_long_value_changed_in_redcap_gets_one_line(tmp_path: Path) -> None:
    """Review finding 2: the ledger's detail is cut at 300 characters; the same change is still told apart."""
    svc, sim, _token, pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {"tophus": "1", "tophus_site": "right ear"})
    svc.send_redcap(k.STUDY, "crc")
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "tophus_site": "x" * 280})
    for _ in range(3):
        svc.reconcile(k.STUDY, "crc")
    assert len(_changed(svc)) == 1


def test_a_value_changed_back_and_away_again_has_its_lines(tmp_path: Path) -> None:
    """Review finding 3: REDCap equal again closes the change with a line; changed again opens a new one."""
    svc, sim, _token, pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    svc.send_redcap(k.STUDY, "crc")
    for v in ("70.1", "72.5", "70.1"):
        _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "weight": v})
        svc.reconcile(k.STUDY, "crc")
    lines = [s["result"] for s in svc.trail(k.STUDY, "S-001")["sent"] if s["result"] in ("changed_in_redcap",
                                                                                             "equal_again")]  # fmt: skip
    assert lines == ["changed_in_redcap", "equal_again", "changed_in_redcap"]


def test_a_value_whose_redcap_dictionary_entry_changed_is_not_compared(tmp_path: Path) -> None:
    """Review finding 4: a value is formatted under the dictionary entry it was sent under, or not compared."""
    svc, sim, _token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    svc.send_redcap(k.STUDY, "crc")
    proj = next(iter(sim.state.sim.projects.values()))
    for m in proj["metadata"]:
        if m["field_name"] == "weight":
            m["text_validation_type_or_show_slider_number"] = "number_2dp"
    assert svc.reconcile(k.STUDY, "crc") == []


def test_a_send_says_when_redcap_could_not_be_read_again(tmp_path: Path, monkeypatch: Any) -> None:
    """Review finding 7: "could not read" is not "nothing changed"; the send's own audit line is written first."""
    from edc.store import EdcError

    svc, _sim, _token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))

    def down(*_a: Any, **_k: Any) -> Any:
        raise EdcError("RC-UPSTREAM", "REDCap did not answer", 502)

    monkeypatch.setattr(svc, "reconcile", down)
    out = svc.send_redcap(k.STUDY, "crc")
    assert _held(out, "sent") == {(SCREEN1, "weight")} and out["reread"] == "RC-UPSTREAM"
