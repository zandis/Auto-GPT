"""T-302b (D-414): REDCap arms, events and repeating instruments; calculated fields; "erase hidden values".

A synthetic longitudinal project in the REDCap simulator: two arms, a screening and a week-4 event on each, an AE
instrument that repeats on week 4, a calculated BMI and branching logic that hides a field. Synthetic data only
(``tests.edc_kit``)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from datacore.store import DataCore
from edc import logic
from edc.layout import Layout, Slot, split_visit
from edc.prefill import gateway_drafter
from edc.service import EdcService
from edc.store import EdcError, EdcStore
from fastapi.testclient import TestClient
from rc_bridge.client import RedcapClient
from rc_sim.app import create_app
from tb_common.audit import AuditLog

from tests import edc_kit as k
from tests import odm_xsd

SHEET = {"text": "AE log, ward copy", "day": "2026-11-05"}
SCREEN1, WEEK4_1, SCREEN2, WEEK4_2 = "screening_arm_1", "week4_arm_1", "screening_arm_2", "week4_arm_2"
AE1, AE2 = f"{WEEK4_1}__ae__1", f"{WEEK4_1}__ae__2"
BMI = "round([weight]/(([height]/100)^2),1)"

CRF: list[dict[str, str]] = [
    *k.CRF,
    {"field_name": "height", "form_name": "baseline", "field_type": "text", "field_label": "Height (cm)",
     "text_validation_type_or_show_slider_number": "number"},
    {"field_name": "bmi", "form_name": "baseline", "field_type": "calc", "field_label": "BMI",
     "select_choices_or_calculations": BMI},
    {"field_name": "tophus_site", "form_name": "baseline", "field_type": "text", "field_label": "Tophus site",
     "branching_logic": "[tophus] = '1'"},
    {"field_name": "ae_term", "form_name": "ae", "field_type": "text", "field_label": "AE term"},
    {"field_name": "ae_serious", "form_name": "ae", "field_type": "yesno", "field_label": "Serious"},
    {"field_name": "ae_sae_reason", "form_name": "ae", "field_type": "text", "field_label": "Why serious",
     "branching_logic": "[ae_serious] = '1'"},
]  # fmt: skip
MAP: list[dict[str, Any]] = [*k.MAP, {"item": "tophus_site"}, {"item": "ae_term"}, {"item": "ae_serious"},
                             {"item": "ae_sae_reason"}]  # fmt: skip
EVENTS = [{"unique_event_name": SCREEN1, "arm_num": 1}, {"unique_event_name": WEEK4_1, "arm_num": 1},
          {"unique_event_name": SCREEN2, "arm_num": 2}, {"unique_event_name": WEEK4_2, "arm_num": 2}]  # fmt: skip
DESIGNATED = [{"unique_event_name": ev, "form": f} for ev in (SCREEN1, SCREEN2) for f in ("demographics", "baseline")]
DESIGNATED += [{"unique_event_name": ev, "form": "ae"} for ev in (WEEK4_1, WEEK4_2)]
REPEATING = [{"event_name": WEEK4_1, "form_name": "ae"}, {"event_name": WEEK4_2, "form_name": "ae"}]
SEED = [{"record_id": "1", "redcap_event_name": SCREEN1, "tb_screening_no": "S-001", "height": "175"},
        {"record_id": "2", "redcap_event_name": SCREEN2, "tb_screening_no": "S-002", "height": "160"}]  # fmt: skip


def _project(sim: Any, seed: bool = True, crf: list[dict[str, str]] | None = None) -> tuple[str, int]:
    c = TestClient(sim)
    r = c.post("/sim/projects", json={"title": "GZQO longitudinal", "metadata": crf or CRF, "events": EVENTS,
                                      "mapping": DESIGNATED, "repeating": REPEATING})  # fmt: skip
    assert r.status_code == 200, r.text
    token, pid = str(r.json()["token"]), int(r.json()["project_id"])
    if seed:
        assert c.post("/sim/records", json={"project_id": pid, "records": SEED}).status_code == 200
    return token, pid


def _service(tmp_path: Path, crf: list[dict[str, str]] | None = None) -> tuple[EdcService, Any, str, int]:
    sim = create_app()
    token, pid = _project(sim, crf=crf)
    svc = EdcService(EdcStore(sign_key=k.SIGN_KEY), DataCore(), AuditLog(tmp_path / "audit"), lambda: k.STAMP,
                     lambda: k.TODAY, lambda _ref: k.client_for(sim, token), k.FakeFacts,
                     lambda job: gateway_drafter(k.StubLlm(), job))  # fmt: skip
    svc.import_dictionary(k.STUDY, "edc", "crc", "record_id")
    svc.put_map(k.STUDY, MAP, k.TARGET, "crc")
    svc.set_switch(k.STUDY, True, by="pi", role="investigator", **k.ACK)
    return svc, sim, token, pid


def _drafts(svc: EdcService, record: str, visit: str) -> dict[str, dict[str, Any]]:
    return {d["item"]: d for d in svc.store.drafts(k.STUDY, record, visit) if d["fate"] != "superseded"}


def _enter(
    svc: EdcService, record: str, visit: str, values: dict[str, str], confirm: frozenset[str] = frozenset()
) -> None:
    """Draft the visit, type ``values`` (each with a source), confirm the drafted ``confirm`` items, sign."""
    svc.build(k.STUDY, record, k.PID, visit, k.VISIT_DATE, "crc")
    d = _drafts(svc, record, visit)
    for item, value in values.items():
        svc.decide(k.STUDY, d[item]["id"], "edit", value=value, reason="from the source", citation=SHEET, by="crc")
    for item in confirm:
        if d[item]["state"] == "drafted":
            svc.decide(k.STUDY, d[item]["id"], "confirm", by="crc")
    svc.sign(k.STUDY, record, visit, signer="crc", printed_name="Chen Mei", role="coordinator",
             meaning="transcribed", meaning_text="I checked each value.", lang="en",
             seen=k.seen(svc, record, visit))  # fmt: skip


def _rows(sim: Any, token: str) -> dict[tuple[str, str, str, str], dict[str, str]]:
    rows = k.client_for(sim, token).records()
    return {(r["record_id"], r["redcap_event_name"], r["redcap_repeat_instrument"], r["redcap_repeat_instance"]): r
            for r in rows}  # fmt: skip


def _edit_in_redcap(sim: Any, pid: int, row: dict[str, str]) -> None:
    assert TestClient(sim).post("/sim/records", json={"project_id": pid, "records": [row]}).status_code == 200


def _held(out: dict[str, Any], key: str) -> set[tuple[str, str]]:
    return {(x["visit"], x["item"]) for x in out[key]}


# ------------------------------------------------------------------ the acceptance round trip
def test_round_trip_with_arms_events_and_a_repeating_ae_instrument(tmp_path: Path) -> None:
    """Push, read back equal, and a REDCap-side edit listed as a conflict (TB-ASSESS-01 T-302 acceptance)."""
    svc, sim, token, pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight", "urate", "brthdat", "sex"}))
    out = svc.send_redcap(k.STUDY, "crc")
    assert {x["item"] for x in out["sent"]} == {"weight", "urate", "brthdat", "sex"}
    # REDCap computed the BMI from TrialBox's weight and the height it held; TrialBox reads the equation the same
    assert out["calc"] == [{"record": "S-001", "visit": SCREEN1, "item": "bmi", "expected": "23.7", "redcap": "23.7",
                            "equal": True}]  # fmt: skip
    # two AEs on the repeating instrument of week 4, arm 1
    _enter(svc, "S-001", AE1, {"ae_term": "gout flare", "ae_serious": "0"})
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": WEEK4_1, "redcap_repeat_instrument": "ae",
                               "redcap_repeat_instance": "2", "ae_term": "skin rash (typed in REDCap)"})  # fmt: skip
    _enter(svc, "S-001", AE2, {"ae_term": "rash", "ae_serious": "1", "ae_sae_reason": "hospitalised"})
    out = svc.send_redcap(k.STUDY, "crc")
    assert _held(out, "sent") == {(AE1, "ae_term"), (AE1, "ae_serious"), (AE2, "ae_serious"),
                                  (AE2, "ae_sae_reason")}  # fmt: skip
    assert out["conflict"] == [{"id": _drafts(svc, "S-001", AE2)["ae_term"]["id"], "record": "S-001", "visit": AE2,
                                "item": "ae_term", "redcap": "skin rash (typed in REDCap)"}]  # fmt: skip
    rows = _rows(sim, token)
    assert rows[("1", WEEK4_1, "ae", "1")]["ae_term"] == "gout flare"
    assert rows[("1", WEEK4_1, "ae", "2")]["ae_term"] == "skin rash (typed in REDCap)"  # never overwritten
    assert rows[("1", WEEK4_1, "ae", "2")]["ae_sae_reason"] == "hospitalised"
    assert ("1", WEEK4_1, "", "") not in rows  # no base row was written for the AE values (E-05)
    assert rows[("1", SCREEN1, "", "")]["weight"] == "72.5"
    # a second send has only the conflict left: the instance keys hold across sends, nothing is written twice
    again = svc.send_redcap(k.STUDY, "crc")
    assert again["count"] == 0 and _held(again, "conflict") == {(AE2, "ae_term")}
    assert sum(len(v) for key, v in again.items() if isinstance(v, list) and key not in ("conflict", "calc")) == 0


def test_a_value_is_never_written_to_another_arm(tmp_path: Path) -> None:
    svc, sim, token, _ = _service(tmp_path)
    _enter(svc, "S-002", SCREEN1, {}, confirm=frozenset({"weight"}))  # S-002 is on arm 2; screening_arm_1 is arm 1
    out = svc.send_redcap(k.STUDY, "crc")
    assert _held(out, "wrong_arm") == {(SCREEN1, "weight")} and out["count"] == 0
    assert ("2", SCREEN1, "", "") not in _rows(sim, token)
    _enter(svc, "S-002", SCREEN2, {}, confirm=frozenset({"weight"}))
    out = svc.send_redcap(k.STUDY, "crc")
    assert _held(out, "sent") == {(SCREEN2, "weight")}
    assert _rows(sim, token)[("2", SCREEN2, "", "")]["bmi"] == "28.3"  # 72.5 / 1.6^2, computed by REDCap


def test_the_base_row_takes_only_non_repeating_fields_and_each_event_only_its_instruments(tmp_path: Path) -> None:
    """E-05's hazard: an AE value on the base row of week 4, or a baseline value on week 4, is never written."""
    svc, sim, token, _ = _service(tmp_path)
    _enter(svc, "S-001", WEEK4_1, {"ae_term": "gout flare", "tophus_site": "right ear"})
    out = svc.send_redcap(k.STUDY, "crc")
    assert _held(out, "repeating_form") == {(WEEK4_1, "ae_term")}
    assert _held(out, "not_on_event") == {(WEEK4_1, "tophus_site")}
    assert out["count"] == 0 and ("1", WEEK4_1, "", "") not in _rows(sim, token)
    kinds = {r["result"] for r in svc.store.sent_rows(k.STUDY, "S-001")}
    assert kinds == {"repeating_form", "not_on_event"}


def test_an_instance_takes_only_its_own_instrument(tmp_path: Path) -> None:
    svc, *_ = _service(tmp_path)
    svc.build(k.STUDY, "S-001", k.PID, AE1, k.VISIT_DATE, "crc")
    assert set(_drafts(svc, "S-001", AE1)) == {"ae_term", "ae_serious", "ae_sae_reason"}  # only the AE items


def test_a_repeating_project_whose_export_has_no_instance_column_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, sim, token, _ = _service(tmp_path)
    _enter(svc, "S-001", AE1, {"ae_term": "gout flare"})
    real = RedcapClient.records

    def no_keys(self: RedcapClient, *a: Any, **kw: Any) -> list[dict[str, Any]]:
        return [{c: v for c, v in r.items() if not c.startswith("redcap_repeat")} for r in real(self, *a, **kw)]

    monkeypatch.setattr(RedcapClient, "records", no_keys)
    with pytest.raises(EdcError) as e:
        svc.send_redcap(k.STUDY, "crc")
    assert e.value.code == "edc.repeat_keys" and "redcap_repeat_instance" in e.value.message
    monkeypatch.undo()
    assert ("1", WEEK4_1, "ae", "1") not in _rows(sim, token)
    refusals = [json.loads(line) for f in sorted(Path(svc.audit.directory).glob("*.jsonl"))
                for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]  # fmt: skip
    assert any(a.get("event") == "edc.sent" and a.get("detail", {}).get("refused") == "edc.repeat_keys"
               for a in refusals)  # fmt: skip


# ------------------------------------------------------------------ branching logic and erase hidden values
def test_a_value_redcap_would_hide_is_not_sent(tmp_path: Path) -> None:
    svc, sim, token, _ = _service(tmp_path)
    _enter(svc, "S-001", AE1, {"ae_term": "gout flare", "ae_serious": "0", "ae_sae_reason": "none"})
    out = svc.send_redcap(k.STUDY, "crc")
    assert _held(out, "hidden") == {(AE1, "ae_sae_reason")}
    assert _held(out, "sent") == {(AE1, "ae_term"), (AE1, "ae_serious")}
    assert _rows(sim, token)[("1", WEEK4_1, "ae", "1")]["ae_sae_reason"] == ""


def test_holding_one_value_back_hides_the_one_that_depends_on_it(tmp_path: Path) -> None:
    """``ae_serious`` is held back (REDCap holds another value); ``ae_sae_reason`` then shows only by REDCap's 0."""
    svc, sim, _token, pid = _service(tmp_path)
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": WEEK4_1, "redcap_repeat_instrument": "ae",
                               "redcap_repeat_instance": "1", "ae_serious": "0"})  # fmt: skip
    _enter(svc, "S-001", AE1, {"ae_serious": "1", "ae_sae_reason": "hospitalised"})
    out = svc.send_redcap(k.STUDY, "crc")
    assert _held(out, "conflict") == {(AE1, "ae_serious")} and _held(out, "hidden") == {(AE1, "ae_sae_reason")}


def test_erase_hidden_values_erases_only_what_trialbox_wrote(tmp_path: Path) -> None:
    svc, sim, token, pid = _service(tmp_path)
    _enter(svc, "S-001", AE2, {"ae_term": "rash", "ae_serious": "1", "ae_sae_reason": "hospitalised"})
    assert svc.send_redcap(k.STUDY, "crc")["count"] == 3
    # in REDCap the AE is made non-serious: the reason TrialBox wrote is now hidden; REDCap's import keeps it
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": WEEK4_1, "redcap_repeat_instrument": "ae",
                               "redcap_repeat_instance": "2", "ae_serious": "0"})  # fmt: skip
    # and on the screening row someone typed a tophus site while tophus is not ticked
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "tophus": "0",
                               "tophus_site": "left toe"})  # fmt: skip
    res = svc.erase_hidden(k.STUDY, "S-001", AE2, "crc")
    assert res == {"erased": ["ae_sae_reason"], "kept": []}
    row = _rows(sim, token)[("1", WEEK4_1, "ae", "2")]
    assert (row["ae_sae_reason"], row["ae_term"], row["ae_serious"]) == ("", "rash", "0")
    assert [r["result"] for r in svc.store.sent_rows(k.STUDY, "S-001")][-1] == "erased"
    res = svc.erase_hidden(k.STUDY, "S-001", SCREEN1, "crc")
    assert res == {"erased": [], "kept": [{"item": "tophus_site", "why": "not_written_by_trialbox"}]}
    assert _rows(sim, token)[("1", SCREEN1, "", "")]["tophus_site"] == "left toe"  # someone else's: never erased


def test_after_a_send_redcap_hidden_values_are_listed(tmp_path: Path) -> None:
    svc, sim, _token, pid = _service(tmp_path)
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "tophus": "0",
                               "tophus_site": "left toe"})  # fmt: skip
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    out = svc.send_redcap(k.STUDY, "crc")
    assert out["hidden_in_redcap"] == [{"record": "S-001", "visit": SCREEN1, "item": "tophus_site",
                                        "trialbox": False}]  # fmt: skip


def test_logic_trialbox_cannot_read_holds_the_value_back(tmp_path: Path) -> None:
    crf = [dict(r, branching_logic="[ae_serious] = '1' and [event-name] = 'week4_arm_1'")
           if r["field_name"] == "ae_sae_reason" else r for r in CRF]  # fmt: skip
    svc, *_ = _service(tmp_path, crf)
    _enter(svc, "S-001", AE1, {"ae_serious": "1", "ae_sae_reason": "hospitalised"})
    out = svc.send_redcap(k.STUDY, "crc")
    assert _held(out, "logic") == {(AE1, "ae_sae_reason")} and _held(out, "sent") == {(AE1, "ae_serious")}


# ------------------------------------------------------------------ calculated fields
def test_preview_shows_the_row_the_calculation_and_what_would_not_be_written(tmp_path: Path) -> None:
    svc, _sim, _token, _pid = _service(tmp_path)
    svc.build(k.STUDY, "S-001", k.PID, SCREEN1, k.VISIT_DATE, "crc")
    d = _drafts(svc, "S-001", SCREEN1)
    svc.decide(k.STUDY, d["weight"]["id"], "confirm", by="crc")
    svc.decide(k.STUDY, d["ae_term"]["id"], "edit", value="flare", reason="from the source", citation=SHEET, by="crc")
    svc.decide(k.STUDY, d["tophus_site"]["id"], "edit", value="ear", reason="from the source", citation=SHEET,
               by="crc")  # fmt: skip
    p = svc.preview(k.STUDY, "S-001", SCREEN1, "crc")
    assert (p["event"], p["instrument"], p["instance"]) == (SCREEN1, "", 0)
    assert p["misplaced"] == [{"item": "ae_term", "why": "not_on_event"}]
    assert p["hidden"] == [{"item": "tophus_site", "why": "hidden"}]  # tophus is not ticked (its draft is open)
    # REDCap holds no BMI yet (no weight); TrialBox computes it from the confirmed weight and REDCap's height
    assert p["calc"] == [{"item": "bmi", "expected": "23.7", "redcap": "", "equal": False}]
    with pytest.raises(EdcError) as e:
        svc.preview(k.STUDY, "S-001", "week9_arm_1", "crc")
    assert e.value.code == "edc.no_slot"


def test_a_calculation_redcap_holds_differently_is_listed(tmp_path: Path) -> None:
    svc, sim, _token, pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    svc.send_redcap(k.STUDY, "crc")
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "bmi": "24"})
    p = svc.preview(k.STUDY, "S-001", SCREEN1, "crc")
    assert p["calc"] == [{"item": "bmi", "expected": "23.7", "redcap": "24", "equal": False}]


# ------------------------------------------------------------------ ODM with repeat keys
def test_an_ae_on_a_repeating_instrument_exports_and_reimports_equal(tmp_path: Path) -> None:
    from xml.etree import ElementTree as ET

    svc, *_ = _service(tmp_path)
    _enter(svc, "S-001", AE1, {"ae_term": "gout flare", "ae_serious": "0"})
    _enter(svc, "S-001", AE2, {"ae_term": "rash", "ae_serious": "1", "ae_sae_reason": "hospitalised"})
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    text = svc.export_odm(k.STUDY, "crc")
    assert odm_xsd.problems(text) == []
    ns = {"o": "http://www.cdisc.org/ns/odm/v1.3"}
    root = ET.fromstring(text)
    assert root.find(".//o:FormDef[@OID='Form.ae']", ns).get("Repeating") == "Yes"  # type: ignore[union-attr]
    assert root.find(".//o:FormDef[@OID='Form.baseline']", ns).get("Repeating") == "No"  # type: ignore[union-attr]
    keys = sorted(f.get("FormRepeatKey") or "" for f in root.iterfind(".//o:FormData[@FormOID='Form.ae']", ns))
    assert keys == ["1", "2"]
    # a fresh project with the same dictionary takes the file back: each instance on its own row, values equal
    sim = create_app()
    token, _ = _project(sim, seed=False)
    r = TestClient(sim).post("/api/", data={"token": token, "content": "record", "format": "odm", "type": "flat",
                                            "data": text, "returnContent": "ids"})  # fmt: skip
    assert r.status_code == 200, r.text
    rows = _rows(sim, token)
    assert rows[("S-001", WEEK4_1, "ae", "1")]["ae_term"] == "gout flare"
    assert rows[("S-001", WEEK4_1, "ae", "2")]["ae_sae_reason"] == "hospitalised"
    assert rows[("S-001", SCREEN1, "", "")]["weight"] == "72.5"
    assert rows[("S-001", SCREEN1, "", "")]["bmi"] == ""  # no height in the file: REDCap leaves the BMI blank
    signed = {(d["visit"], d["item"]): d["final"] for d in svc.store.signed(k.STUDY)}
    back = {}
    for (_rec, ev, form, inst), row in rows.items():
        visit = f"{ev}__{form}__{inst}" if inst else ev
        back.update(
            {(visit, f): val for f, val in row.items() if val and f != "record_id" and not f.startswith("redcap_")}
        )
    assert back == signed


# ------------------------------------------------------------------ the layout, read without and with the project
def test_visits_name_rows() -> None:
    forms = {"ae", "baseline"}
    assert split_visit(AE2, forms) == Slot(WEEK4_1, "ae", 2) and Slot(WEEK4_1, "ae", 2).visit == AE2
    assert split_visit("visit_2_arm_1__3", forms) == Slot("visit_2_arm_1", "", 3)
    assert split_visit("", forms) == Slot("event_1_arm_1") and split_visit("v1", forms) == Slot("v1")
    lay = Layout.read({"is_longitudinal": 1}, EVENTS, DESIGNATED, REPEATING)
    assert lay.slot(AE2) == Slot(WEEK4_1, "ae", 2) and lay.slot(SCREEN1) == Slot(SCREEN1)
    assert lay.slot(f"{SCREEN1}__ae__1") is None and lay.slot("week9_arm_1") is None
    assert lay.slot(f"{WEEK4_1}__ae__0") is None
    assert lay.misplaced(Slot(SCREEN2), "baseline", {1}) == "wrong_arm"
    classic = Layout.read({"is_longitudinal": 0}, [], [], [{"event_name": "", "form_name": "ae"}])
    assert classic.slot("event_1_arm_1__ae__4") == Slot("event_1_arm_1", "ae", 4)
    assert classic.misplaced(Slot("event_1_arm_1"), "ae", set()) == "repeating_form"


# ------------------------------------------------------------------ the evaluator
def _look(row: dict[str, str]) -> logic.Lookup:
    def lookup(event: str | None, field: str, code: str | None, instance: int | None) -> str:
        key = f"{event}:{field}" if event else field
        if key not in row:
            raise logic.LogicError(f"no {key}")
        return ("1" if code in row[key].split(",") else "0") if code else row[key]

    return lookup


TODAY = date(2026, 11, 9)


@pytest.mark.parametrize(
    ("text", "row", "want"),
    [
        (BMI, {"weight": "72.5", "height": "175"}, "23.7"),
        (BMI, {"weight": "72.5", "height": ""}, ""),  # a blank makes the calculation blank
        ("sum([a],[b],[c])", {"a": "1", "b": "", "c": "2.5"}, "3.5"),  # sum skips blanks
        ("mean([a],[b])", {"a": "1", "b": "2"}, "1.5"),
        ("[a]/[b]", {"a": "1", "b": "0"}, ""),  # division by zero is blank
        ("round(2.5) + rounddown(1.99,1) + roundup(1.01,1)", {}, "6"),  # 3 + 1.9 + 1.1
        ("if([a] > 70, 1, 0)", {"a": "72"}, "1"),
        ("datediff([d1],[d2],'d')", {"d1": "2026-01-01", "d2": "2026-03-01"}, "59"),
        ("datediff([d2],[d1],'d',true)", {"d1": "2026-01-01", "d2": "2026-03-01"}, "-59"),
        ("rounddown(datediff([dob],'today','y'))", {"dob": "1960-05-01"}, "66"),
        ("[baseline_arm_1][w] - [w]", {"baseline_arm_1:w": "80", "w": "72.5"}, "7.5"),
        ("[cb(2)] + [cb(3)]", {"cb": "1,3"}, "1"),
        ("2^10 - -1", {}, "1025"),
        ("sqrt(-1)", {}, ""),
    ],
)
def test_the_evaluator_computes_as_redcap(text: str, row: dict[str, str], want: str) -> None:
    assert logic.calculate(text, _look(row), TODAY) == want


@pytest.mark.parametrize(
    ("text", "row", "want"),
    [
        ("[s] = '1'", {"s": "1"}, True),
        ("[s] = '1'", {"s": ""}, False),
        ("[s] = ''", {"s": ""}, True),
        ("[s] = 0", {"s": ""}, False),  # a blank is not zero
        ("[a] > 5", {"a": ""}, False),  # an order comparison with a blank is false
        ("[a] <> '2' and ([b] = 'x' or [c] >= 3)", {"a": "1", "b": "y", "c": "3"}, True),
        ("[a] != 1 || [b] = 1", {"a": "1", "b": "1"}, True),
        ("[d] > '2026-01-01'", {"d": "2026-02-01"}, True),
        ("contains([t], 'gout') and not_contain([t], 'rash')", {"t": "Gout flare"}, True),
        ("isnumber([a]) and isinteger([b])", {"a": "1.5", "b": "2.0"}, False),
    ],
)
def test_branching_logic_shows_as_redcap(text: str, row: dict[str, str], want: bool) -> None:
    assert logic.shown(text, _look(row), TODAY) is want


@pytest.mark.parametrize(
    "text",
    [
        "__import__('os').system('id')",
        "eval('1')",
        "[a].__class__",
        "[event-name] = 'x'",  # smart variables are not read
        "[a] = 1 ; [b]",
        "now",
        "(" * 60 + "1" + ")" * 60,  # too deep
        "1+" * 1200 + "1",  # too long
        "datediff([a],[b],'w')",
        "[a](1)",
        "",
    ],
)
def test_the_evaluator_refuses_what_it_does_not_read(text: str) -> None:
    with pytest.raises(logic.LogicError):
        logic.calculate(text, _look({"a": "1", "b": "2026-01-01"}), TODAY)


def test_the_evaluator_never_calls_eval_or_exec() -> None:
    src = Path(logic.__file__).read_text(encoding="utf-8")
    assert "eval(" not in src.replace("_Eval(", "").replace("evaluate(", "") and "exec(" not in src
    assert "compile(" not in src.replace("re.compile(", "")


# ------------------------------------------------------------------ the simulator's repeating instruments
def _api(sim: Any, token: str, **form: str) -> Any:
    return TestClient(sim).post("/api/", data={"token": token, "format": "json", **form})


def test_the_simulator_answers_repeating_forms_and_refuses_a_value_on_the_wrong_row() -> None:
    sim = create_app()
    token, _ = _project(sim)
    r = _api(sim, token, content="repeatingFormsEvents")
    assert r.status_code == 200 and {(x["event_name"], x["form_name"]) for x in r.json()} == {(WEEK4_1, "ae"),
                                                                                             (WEEK4_2, "ae")}  # fmt: skip
    assert _api(sim, token, content="project").json()["has_repeating_instruments_or_events"] == 1
    base = {"record_id": "1", "redcap_event_name": WEEK4_1}

    def imp(row: dict[str, str]) -> Any:
        return _api(sim, token, content="record", type="flat", data=json.dumps([row]))

    assert "repeat" in imp({**base, "ae_term": "x"}).json()["error"]  # an AE field on the base row
    r = imp({**base, "redcap_repeat_instrument": "ae", "redcap_repeat_instance": "", "ae_term": "x"})
    assert "instance" in r.json()["error"]
    r = imp({**base, "redcap_repeat_instrument": "ae", "redcap_repeat_instance": "1", "weight": "70"})
    assert r.status_code == 400  # a baseline field on an AE instance (and baseline is not on week 4)
    r = imp({"record_id": "1", "redcap_event_name": SCREEN1, "redcap_repeat_instrument": "baseline",
             "redcap_repeat_instance": "1", "weight": "70"})  # fmt: skip
    assert "not set to repeat" in r.json()["error"]
    assert (
        imp({**base, "redcap_repeat_instrument": "ae", "redcap_repeat_instance": "3", "ae_term": "x"}).status_code
        == 200
    )
    rows = _rows(sim, token)
    assert rows[("1", WEEK4_1, "ae", "3")]["ae_term"] == "x"
    assert all("redcap_repeat_instance" in r for r in k.client_for(sim, token).records())
    # overwriteBehavior=overwrite: a blank erases; normal: a blank never erases
    _api(sim, token, content="record", type="flat", overwriteBehavior="normal",
         data=json.dumps([{**base, "redcap_repeat_instrument": "ae", "redcap_repeat_instance": "3", "ae_term": ""}]))  # fmt: skip
    assert _rows(sim, token)[("1", WEEK4_1, "ae", "3")]["ae_term"] == "x"
    k.client_for(sim, token).import_records(
        [{**base, "redcap_repeat_instrument": "ae", "redcap_repeat_instance": "3", "ae_term": ""}], erase=True
    )
    assert _rows(sim, token)[("1", WEEK4_1, "ae", "3")]["ae_term"] == ""


def test_a_classic_project_without_repeats_answers_no_repeating_forms() -> None:
    sim = create_app()
    token = k.sim_project(sim, [{"record_id": "1", "tb_screening_no": k.RECORD}])
    assert _api(sim, token, content="repeatingFormsEvents").status_code == 400
    assert "redcap_repeat_instance" not in k.client_for(sim, token).records()[0]
