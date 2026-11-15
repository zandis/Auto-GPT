"""NEW-EDC-8b (D-693, deep-review EDC-012, assigned to the NEW-EDC-8 change): an `already_there` line does not make
TrialBox the owner of a person's value.

`last_sent` counted `already_there` as TrialBox's write. A value a person typed in REDCap, equal to TrialBox's, was
then TrialBox's: a later correction in TrialBox overwrote it with no conflict line (case 1c), and "erase hidden
values" erased it. Ownership is now from TrialBox's own writes only (`sent`, `erased`; D-690's `last_written`).
Synthetic data only."""

from __future__ import annotations

from pathlib import Path

from tests import edc_kit as k
from tests.unit.test_edc_attempt_ledger import _correct
from tests.unit.test_edc_t302b import SCREEN1, _edit_in_redcap, _enter, _held, _rows, _service


def test_a_persons_value_trialbox_found_already_there_is_not_overwritten_by_a_later_correction(
    tmp_path: Path,
) -> None:
    svc, sim, token, pid = _service(tmp_path)
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "weight": "72.5"})
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    assert _held(svc.send_redcap(k.STUDY, "crc"), "already_there") == {(SCREEN1, "weight")}
    _correct(svc, "S-001", SCREEN1, "weight", "73.5")
    out = svc.send_redcap(k.STUDY, "crc")
    assert _held(out, "conflict") == {(SCREEN1, "weight")} and out["sent"] == []
    assert _rows(sim, token)[("1", SCREEN1, "", "")]["weight"] == "72.5"  # the person's value stays


def test_erase_hidden_values_never_erases_a_persons_value_trialbox_found_already_there(tmp_path: Path) -> None:
    svc, sim, token, pid = _service(tmp_path)
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "tophus": "1",
                               "tophus_site": "right ear"})  # fmt: skip
    _enter(svc, "S-001", SCREEN1, {"tophus": "1", "tophus_site": "right ear"})
    assert _held(svc.send_redcap(k.STUDY, "crc"), "already_there") == {(SCREEN1, "tophus"), (SCREEN1, "tophus_site")}
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "tophus": "0"})
    res = svc.erase_hidden(k.STUDY, "S-001", SCREEN1, "crc")
    assert res == {"erased": [], "kept": [{"item": "tophus_site", "why": "not_written_by_trialbox"}]}
    assert _rows(sim, token)[("1", SCREEN1, "", "")]["tophus_site"] == "right ear"


def test_after_a_send_a_hidden_value_trialbox_found_already_there_is_not_listed_as_trialboxs(tmp_path: Path) -> None:
    svc, sim, _token, pid = _service(tmp_path)
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "tophus": "0",
                               "tophus_site": "right ear"})  # fmt: skip
    _enter(svc, "S-001", SCREEN1, {"tophus_site": "right ear"}, confirm=frozenset({"weight"}))
    out = svc.send_redcap(k.STUDY, "crc")
    assert next(h for h in out["hidden_in_redcap"] if h["item"] == "tophus_site")["trialbox"] is False
