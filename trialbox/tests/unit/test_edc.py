"""EDC prefill (D-160): the map, the drafts, the review rules, the signature, the REDCap send and the ODM export.
One test per rule; synthetic data only (``tests.edc_kit``)."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from xml.etree import ElementTree as ET

import pytest
from datacore import forms
from edc import cdash, mapping
from edc.store import EdcError
from fastapi.testclient import TestClient
from tb_common.audit import verify

from tests import edc_kit as k

NS = {"o": "http://www.cdisc.org/ns/odm/v1.3"}


def _by_item(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["item"]: r for r in rows}


def _draft(svc: Any, **kw: Any) -> dict[str, dict[str, Any]]:
    return _by_item(svc.build(k.STUDY, k.RECORD, kw.get("pid", k.PID), kw.get("visit", ""),
                              kw.get("visit_date", k.VISIT_DATE), "crc"))  # fmt: skip


def _el(parent: ET.Element, path: str) -> ET.Element:
    found = parent.find(path, NS)
    assert found is not None, path
    return found


def _fields() -> dict[str, forms.Field]:
    return {f.name: f for f in (forms.field_of(r) for r in k.CRF)}


# ------------------------------------------------------------------ the map
def test_map_check_refuses_what_could_draft_a_wrong_value() -> None:
    f = _fields()
    protected = {"record_id", "tb_screening_no"}
    rows: list[dict[str, Any]] = [
        {"item": "tb_screening_no", "source": "patient", "what": "birth_date"},  # the link field
        {"item": "nope", "source": "patient", "what": "sex"},  # not in the dictionary
        {"item": "weight", "source": "observation", "what": "value", "codes": ["29463-7"]},  # no unit
        {"item": "urate", "source": "observation", "what": "value", "unit": "mg/dL"},  # no codes
        {"item": "mh_gout", "source": "condition", "what": "presence", "codes": ["M10"], "yes_code": "9"},
        {"item": "sex", "source": "patient", "what": "sex", "sex_codes": {"male": "1"}},
        {"item": "brthdat", "cdash": "dm.brthdat", "source": "patient", "what": "birth_date"},
        {"item": "tophus", "source": "note", "what": "value"},  # no question
        {"item": "comments", "source": "condition", "what": "date", "codes": ["M10"]},  # notes field, not a date
        {"item": "weight", "source": "magic", "what": "value"},
    ]
    bad = mapping.check([mapping.ItemMap.from_dict(x) for x in rows], f, protected)
    codes = {(b["item"], b["code"]) for b in bad}
    for want in [("tb_screening_no", "protected"), ("nope", "not_in_dictionary"), ("weight", "unit"),
                 ("urate", "codes"), ("mh_gout", "yes_code"), ("sex", "sex_codes"), ("brthdat", "cdash"),
                 ("tophus", "question"), ("comments", "kind"), ("weight", "twice"), ("weight", "source")]:  # fmt: skip
        assert want in codes, want
    assert mapping.check([mapping.ItemMap.from_dict(x) for x in k.MAP], f, protected) == []


def test_suggestion_never_guesses_diagnosis_or_medicine_codes() -> None:
    sug = {m.item: m for m in mapping.suggest(list(_fields().values()), {"record_id", "tb_screening_no"})}
    assert "record_id" not in sug and "tb_screening_no" not in sug and "pt_initials" not in sug
    assert sug["weight"].source == "observation" and sug["weight"].codes == ("29463-7",) and sug["weight"].unit == "kg"
    assert sug["brthdat"].cdash == "DM.BRTHDAT" and sug["sex"].sex_codes == {"male": "1", "female": "2"}
    assert sug["mh_gout"].source == "none" and sug["mh_gout"].cdash == "MH.MHOCCUR"  # tagged, never drafted
    assert sug["cm_allo"].source == "none" and not sug["cm_allo"].codes
    hint = cdash.suggest("x", "體重")
    assert cdash.suggest("taijuu", "体重 (kg)") is not None and hint is not None and hint.test == "WEIGHT"


def test_map_with_problems_is_refused_and_nothing_saved(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    svc.import_dictionary(k.STUDY, "edc", "crc", "record_id")
    with pytest.raises(EdcError) as e:
        svc.put_map(k.STUDY, [{"item": "record_id", "source": "patient", "what": "sex"}], k.TARGET, "crc")
    assert e.value.code == "edc.map" and svc.store.map(k.STUDY) == []


def test_dictionary_from_redcap_drops_identifier_fields(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    out = svc.import_dictionary(k.STUDY, "edc", "crc", "record_id")
    assert out["dropped"] == ["pt_initials"] and "pt_initials" not in svc.dc.fields(k.STUDY)
    assert set(out["forms"]) == {"demographics", "baseline"}


# ------------------------------------------------------------------ the switch
def test_switch_is_off_by_default_and_nothing_is_drafted(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc, on=False)
    assert svc.store.switch(k.STUDY).state == "off"
    with pytest.raises(EdcError) as e:
        _draft(svc)
    assert e.value.code == "edc.off"


@pytest.mark.parametrize("change,code", [
    ({"kind": ""}, "edc.ack_kind"),
    ({"reference": " "}, "edc.ack_reference"),
    ({"ack_date": "soon"}, "edc.ack_date"),
    ({"ack_date": "2026-12-01"}, "edc.ack_date"),  # in the future
    ({"reentry_pages": 29}, "edc.reentry"),
    ({"reentry_accuracy": 0.97}, "edc.reentry"),
])  # fmt: skip
def test_switch_needs_the_acknowledgement_and_the_reentry_result(tmp_path: Path, change: dict[str, Any],
                                                                  code: str) -> None:  # fmt: skip
    svc, _, _ = k.service(tmp_path)
    with pytest.raises(EdcError) as e:
        svc.set_switch(k.STUDY, True, by="pi", role="investigator", **{**k.ACK, **change})
    assert e.value.code == code and not svc.store.switch(k.STUDY).on
    assert svc.store.switch_events(k.STUDY) == []  # a refused change is audited, not recorded as a change


def test_switch_off_keeps_the_acknowledgement_and_every_change(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    svc.set_switch(k.STUDY, True, by="pi", role="investigator", **k.ACK)
    svc.set_switch(k.STUDY, False, by="admin", role="admin", reason="sponsor withdrew")
    sw = svc.store.switch(k.STUDY)
    assert sw.state == "off" and sw.reference == "SPN-2026-041"
    assert [e["state"] for e in svc.store.switch_events(k.STUDY)] == ["on", "off"]


# ------------------------------------------------------------------ the drafts
def test_drafts_carry_a_citation_for_every_value(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    d = _draft(svc)
    assert d["brthdat"]["value"] == "1960-05-01" and d["sex"]["value"] == "1"
    assert d["weight"]["value"] == "72.5" and d["weight"]["citation"]["row"] == "o1"
    assert d["urate"]["value"] == "8.4" and d["urate"]["citation"]["day"] == "2026-10-20"  # latest before the visit
    assert d["mh_gout"]["value"] == "1" and d["mh_gout"]["citation"]["table"] == "condition"
    assert d["tophus"]["value"] == "1" and d["tophus"]["citation"]["kind"] == "note"
    assert d["tophus"]["citation"]["quote"] == "Tophus on the right ear."
    for r in d.values():
        assert (r["state"] == "drafted") == bool(r["citation"]) == bool(r["value"])
        assert r["citation"] is None or r["citation"]["snapshot"] == "snap-1"


def test_unknown_never_becomes_no_and_proposed_facts_never_count(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    d = _draft(svc)
    # no allopurinol in the hospital record; a chart fact nobody confirmed names it: still unknown, never "0"
    assert d["cm_allo"]["state"] == "unknown" and d["cm_allo"]["value"] == ""
    assert d["cm_allo"]["why"] == "only_proposed"
    assert d["comments"]["why"] == "not_mapped"
    facts = k.FakeFacts()
    facts.facts = []
    facts.data["condition"] = []
    svc2, _, _ = k.service(tmp_path / "b", facts)
    k.ready(svc2)
    d2 = _draft(svc2)
    assert d2["cm_allo"]["why"] == "no_record" and d2["mh_gout"]["value"] == "" and d2["mh_gout"]["why"] == "no_record"


@pytest.mark.parametrize("rows,why", [
    ([{"row": "a", "code": "29463-7", "d": date(2026, 11, 1), "value_num": 72.5, "unit": "kg", "cmp": ""},
      {"row": "b", "code": "29463-7", "d": date(2026, 11, 1), "value_num": 75.0, "unit": "kg", "cmp": ""}], "conflict"),
    ([{"row": "a", "code": "29463-7", "d": date(2026, 11, 1), "value_num": 160.0, "unit": "lb", "cmp": ""}], "unit"),
    ([{"row": "a", "code": "29463-7", "d": date(2026, 11, 1), "value_num": 20.0, "unit": "kg", "cmp": "<"}], "censored"),
    ([{"row": "a", "code": "29463-7", "d": date(2026, 1, 1), "value_num": 72.0, "unit": "kg", "cmp": ""}],
     "out_of_window"),
    ([{"row": "a", "code": "29463-7", "d": date(2026, 11, 1), "value_num": 900.0, "unit": "kg", "cmp": ""}], "invalid"),
    ([{"row": "a", "code": "29463-7", "d": date(2026, 11, 7), "value_num": 72.0, "unit": "kg", "cmp": ""}],
     "out_of_window"),  # after the visit: never used by latest_before
])  # fmt: skip
def test_an_unclear_value_stays_unknown_with_its_reason(tmp_path: Path, rows: list[dict[str, Any]], why: str) -> None:
    facts = k.FakeFacts()
    facts.data["observation"] = rows
    svc, _, _ = k.service(tmp_path, facts)
    k.ready(svc)
    w = _draft(svc)["weight"]
    assert (w["state"], w["value"], w["why"], w["citation"]) == ("unknown", "", why, None)


def test_a_note_value_needs_its_quote_in_the_note(tmp_path: Path) -> None:
    class Liar:
        def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: Any = None, **_: Any) -> Any:
            return SimpleNamespace(
                data={"found": True, "value": "1", "note": "n1", "date": "2026-10-20", "quote": "Large tophus seen"},
                prompt_version="1",
            )

    svc, _, _ = k.service(tmp_path, llm=Liar())
    k.ready(svc)
    t = _draft(svc)["tophus"]
    assert (t["state"], t["why"]) == ("unknown", "quote_not_found")
    assert "crf_prefill_v1" in t["version"]


def test_a_negated_note_mention_is_not_a_value(tmp_path: Path) -> None:
    facts = k.FakeFacts()
    facts.note_rows = [{"row": "n1", "d": date(2026, 10, 20), "type": "progress", "text": "No tophus: なし"}]
    svc, _, _ = k.service(tmp_path, facts)
    k.ready(svc)
    assert _draft(svc)["tophus"]["why"] == "no_record"


def test_no_visit_date_in_the_future_and_no_draft_for_a_stale_map(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    with pytest.raises(EdcError) as e:
        _draft(svc, visit_date="2026-12-01")
    assert e.value.code == "edc.visit_date"
    svc.dc.put_form(k.STUDY, forms.questionnaires(k.STUDY, [forms.field_of(r) for r in k.CRF[:4]],
                                                  record_field="record_id")[0], "test", "now")  # fmt: skip
    for q in svc.dc.forms(k.STUDY):  # the baseline form disappears from the dictionary
        if q["name"] == "baseline":
            svc.dc.db.execute("DELETE FROM form WHERE study = ? AND name = ?", (k.STUDY, "baseline"))
    with pytest.raises(EdcError) as e2:
        _draft(svc)
    assert e2.value.code == "edc.map"


def test_a_new_run_supersedes_open_drafts_and_keeps_decisions(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    d = _draft(svc)
    svc.decide(k.STUDY, d["weight"]["id"], "confirm", by="crc")
    d2 = _draft(svc)
    assert "weight" in d2 and d2["weight"]["id"] == d["weight"]["id"]  # the decided one stays
    assert d2["urate"]["id"] != d["urate"]["id"]
    old = svc.store.draft(k.STUDY, d["urate"]["id"])
    assert old is not None and old["fate"] == "superseded"
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, d["urate"]["id"], "confirm", by="crc")
    assert e.value.code == "edc.superseded"


# ------------------------------------------------------------------ review rules
def test_a_value_without_a_citation_cannot_be_confirmed(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    d = _draft(svc)
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, d["cm_allo"]["id"], "confirm", by="crc")
    assert e.value.code == "edc.no_citation"
    with pytest.raises(EdcError) as e2:  # typing a value without naming its source is refused too
        svc.decide(k.STUDY, d["cm_allo"]["id"], "edit", value="1", reason="seen in clinic", by="crc")
    assert e2.value.code == "edc.edit_source"
    out = svc.decide(k.STUDY, d["cm_allo"]["id"], "edit", value="1", reason="seen in clinic", by="crc",
                     citation={"text": "Prescription list, outpatient 2026-10-01", "day": "2026-10-01"})  # fmt: skip
    assert out["fate"] == "edited" and out["final_citation"]["kind"] == "manual"


def test_an_edit_needs_a_reason_and_a_valid_value(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    d = _draft(svc)
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, d["weight"]["id"], "edit", value="73", reason=" ", by="crc")
    assert e.value.code == "edc.reason"
    with pytest.raises(EdcError) as e2:
        svc.decide(k.STUDY, d["weight"]["id"], "edit", value="9000", reason="typo", by="crc")
    assert e2.value.code == "edc.invalid"
    with pytest.raises(EdcError) as e3:
        svc.decide(k.STUDY, d["sex"]["id"], "edit", value="3", reason="typo", by="crc")
    assert e3.value.code == "edc.invalid"
    out = svc.decide(
        k.STUDY,
        d["weight"]["id"],
        "edit",
        value="73",
        reason="scale re-read",
        by="crc",
        citation={"text": "ward scale sheet", "day": "2026-11-05"},
    )
    assert (out["fate"], out["final"], out["reason"]) == ("edited", "73", "scale re-read")
    hist = svc.trail(k.STUDY, k.RECORD)["decisions"]
    assert [(h["action"], h["old"], h["new"]) for h in hist] == [("edit", None, "73")]


def test_confirm_twice_is_refused_and_a_change_keeps_the_old_value(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    d = _draft(svc)
    svc.decide(k.STUDY, d["weight"]["id"], "confirm", by="crc")
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, d["weight"]["id"], "confirm", by="crc")
    assert e.value.code == "edc.decided"
    svc.decide(
        k.STUDY,
        d["weight"]["id"],
        "edit",
        value="72",
        reason="rounded per protocol",
        by="crc",
        citation={"text": "ward scale sheet", "day": "2026-11-05"},
    )
    hist = svc.trail(k.STUDY, k.RECORD)["decisions"]
    assert [(h["action"], h["old"], h["new"]) for h in hist] == [("confirm", None, "72.5"), ("edit", "72.5", "72")]


# ------------------------------------------------------------------ signature, send, export
def _confirm_all(svc: Any) -> dict[str, dict[str, Any]]:
    d = _draft(svc)
    for r in d.values():
        if r["state"] == "drafted":
            svc.decide(k.STUDY, r["id"], "confirm", by="crc")
    return d


def _sign(svc: Any) -> dict[str, Any]:
    out: dict[str, Any] = svc.sign(k.STUDY, k.RECORD, "", signer="crc", printed_name="Chen Mei", role="coordinator",
                    meaning="transcribed", meaning_text="I checked each value.", lang="en",
                    seen=k.seen(svc))  # fmt: skip
    return out


def test_nothing_is_sent_before_it_is_confirmed_and_signed(tmp_path: Path) -> None:
    svc, sim, token = k.service(tmp_path)
    k.ready(svc)
    d = _draft(svc)
    assert svc.send_redcap(k.STUDY, "crc")["count"] == 0  # drafts only
    svc.decide(k.STUDY, d["weight"]["id"], "confirm", by="crc")
    assert svc.send_redcap(k.STUDY, "crc")["count"] == 0  # confirmed, not signed
    rows = k.client_for(sim, token).records()
    assert rows[0]["weight"] == ""
    with pytest.raises(EdcError) as e:
        svc.sign(k.STUDY, "S-404", "", signer="crc", printed_name="x", role="coordinator", meaning="transcribed",
                 meaning_text="x", lang="en", seen={})  # fmt: skip
    assert e.value.code == "edc.nothing_to_sign"


def test_signed_values_are_sent_and_read_back(tmp_path: Path) -> None:
    svc, sim, token = k.service(tmp_path)
    k.ready(svc)
    _confirm_all(svc)
    sig = _sign(svc)
    assert sig["printed_name"] == "Chen Mei" and sig["meaning"] == "transcribed" and len(json.loads(sig["drafts"])) == 6
    out = svc.send_redcap(k.STUDY, "crc")
    assert out["count"] == 6 and not out["conflict"] and not out["readback"]
    row = k.client_for(sim, token).records()[0]
    assert (row["weight"], row["urate"], row["sex"], row["mh_gout"], row["tophus"]) == ("72.5", "8.4", "1", "1", "1")
    assert row["cm_allo"] == ""  # unknown: never sent as "0"
    assert svc.send_redcap(k.STUDY, "crc")["count"] == 0  # sent once


def test_a_value_changed_after_signing_is_not_sent_until_signed_again(tmp_path: Path) -> None:
    svc, sim, token = k.service(tmp_path)
    k.ready(svc)
    d = _confirm_all(svc)
    _sign(svc)
    svc.decide(
        k.STUDY,
        d["weight"]["id"],
        "edit",
        value="73",
        reason="scale re-read",
        by="crc",
        citation={"text": "ward scale sheet", "day": "2026-11-05"},
    )
    out = svc.send_redcap(k.STUDY, "crc")
    assert "weight" not in {x["item"] for x in out["sent"]}
    # a change straight in the database (not through the service) breaks the signature's hash: never sent
    svc.store.db.execute("UPDATE draft SET final = '80' WHERE id = ?", (d["urate"]["id"],))
    assert d["urate"]["id"] not in {x["id"] for x in svc.store.sendable(k.STUDY)}
    _sign(svc)
    out2 = svc.send_redcap(k.STUDY, "crc")
    assert {x["item"] for x in out2["sent"]} == {"weight"}
    assert k.client_for(sim, token).records()[0]["weight"] == "73"


def test_a_value_someone_wrote_in_redcap_is_never_overwritten(tmp_path: Path) -> None:
    svc, sim, token = k.service(tmp_path, records=[{"record_id": "1", "tb_screening_no": k.RECORD, "urate": "7.7"}])
    k.ready(svc)
    _confirm_all(svc)
    _sign(svc)
    out = svc.send_redcap(k.STUDY, "crc")
    assert [(c["item"], c["redcap"]) for c in out["conflict"]] == [("urate", "7.7")]
    assert k.client_for(sim, token).records()[0]["urate"] == "7.7"
    assert any(s["result"] == "conflict" for s in svc.store.sent_rows(k.STUDY))


def test_a_subject_without_a_redcap_record_is_listed_not_created(tmp_path: Path) -> None:
    svc, sim, token = k.service(tmp_path, records=[{"record_id": "1", "tb_screening_no": "S-999"}])
    k.ready(svc)
    _confirm_all(svc)
    _sign(svc)
    out = svc.send_redcap(k.STUDY, "crc")
    assert out["count"] == 0 and len(out["no_record"]) == 6
    assert len(k.client_for(sim, token).records()) == 1


def test_switch_off_stops_review_signing_sending_and_export(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    d = _confirm_all(svc)
    _sign(svc)
    svc.set_switch(k.STUDY, False, by="pi", role="investigator")
    for call in (lambda: svc.send_redcap(k.STUDY, "crc"), lambda: svc.export_odm(k.STUDY, "crc"),
                 lambda: _sign(svc), lambda: svc.decide(k.STUDY, d["cm_allo"]["id"], "reject", by="crc")):  # fmt: skip
        with pytest.raises(EdcError) as e:
            call()
        assert e.value.code == "edc.off"


def test_odm_holds_signed_values_with_audit_signature_and_cdash(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    d = _confirm_all(svc)
    svc.decide(
        k.STUDY,
        d["weight"]["id"],
        "edit",
        value="73",
        reason="scale re-read",
        by="crc",
        citation={"text": "ward scale sheet", "day": "2026-11-05"},
    )
    _sign(svc)
    _ = _draft(svc)  # a new run: its open drafts are never exported
    text = svc.export_odm(k.STUDY, "crc")
    root = ET.fromstring(text)
    assert root.get("ODMVersion") == "1.3.2" and root.get("FileType") == "Transactional"
    assert [c.tag.split("}")[1] for c in root] == ["Study", "AdminData", "ClinicalData"]
    items = {i.get("ItemOID"): i for i in root.iterfind(".//o:ItemData", NS)}
    assert set(items) == {"brthdat", "sex", "weight", "urate", "mh_gout", "tophus"}
    w = items["weight"]
    assert w.get("Value") == "73" and w.get("TransactionType") == "Upsert"
    assert [c.tag.split("}")[1] for c in w] == ["AuditRecord", "Signature"]
    assert _el(w, "o:AuditRecord/o:ReasonForChange").text == "scale re-read"
    # the changed value names the person's own source, not the machine's citation of the old value (E-08)
    assert _el(w, "o:AuditRecord/o:SourceID").text == "manual:2026-11-05"
    assert str(_el(items["urate"], "o:AuditRecord/o:SourceID").text).startswith("record:observation:o2@")
    assert _el(w, "o:Signature/o:SignatureRef").get("SignatureOID") == "SD.transcribed"
    idef = _el(root, ".//o:ItemDef[@OID='weight']")
    assert idef.get("SDSVarName") == "VSORRES"
    assert {(a.get("Context"), a.get("Name")) for a in idef.iterfind("o:Alias", NS)} == {
        ("CDASH", "VS.VSORRES"),
        ("CDASH-TESTCD", "WEIGHT"),
    }
    assert [c.tag.split("}")[1] for c in idef] == ["Description", "Question", "Alias", "Alias"]
    assert root.find(".//o:SignatureDef/o:Meaning", NS) is not None
    assert _el(root, ".//o:User/o:FullName").text == "Chen Mei"
    assert "Tophus on the right ear" not in text  # the citation is a reference, never note text


def test_odm_round_trips_into_redcap(tmp_path: Path) -> None:
    svc, sim, _ = k.service(tmp_path)
    k.ready(svc)
    _confirm_all(svc)
    _sign(svc)
    text = svc.export_odm(k.STUDY, "crc")
    fresh = k.sim_project(sim)
    r = TestClient(sim).post("/api/", data={"token": fresh, "content": "record", "format": "odm", "type": "flat",
                                            "data": text, "returnContent": "ids"})  # fmt: skip
    assert r.status_code == 200, r.text
    row = k.client_for(sim, fresh).records()[0]
    assert (row["record_id"], row["weight"], row["brthdat"]) == (k.RECORD, "72.5", "1960-05-01")


def test_every_step_is_audited_without_clinical_values(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    d = _confirm_all(svc)
    with pytest.raises(EdcError):
        svc.decide(k.STUDY, d["cm_allo"]["id"], "confirm", by="crc")
    _sign(svc)
    svc.send_redcap(k.STUDY, "crc")
    svc.export_odm(k.STUDY, "crc")
    lines = [json.loads(x) for p in sorted((tmp_path / "audit").glob("*.jsonl")) for x in p.read_text().splitlines()]
    events = [x["event"] for x in lines]
    for e in ("edc.dictionary", "edc.map", "edc.switch", "edc.drafts", "edc.decide", "edc.sign", "edc.sent",
              "edc.export"):  # fmt: skip
        assert e in events, e
    assert any(x["event"] == "edc.decide" and x["detail"].get("refused") == "edc.no_citation" for x in lines)
    blob = json.dumps(lines)
    assert "72.5" not in blob and "1960-05-01" not in blob and "Tophus" not in blob
    assert verify(tmp_path / "audit").ok


# ------------------------------------------------------------------ the role table
def test_role_table_for_prefill() -> None:
    from tb_common.authz import EDC_ACTIONS, edc_allowed

    data = frozenset({"screen", "enter_data"})
    for a in EDC_ACTIONS:
        assert not edc_allowed("viewer", a, tasks=data, is_pi=True)
        assert not edc_allowed("cro", a, tasks=data, is_pi=True)
    assert edc_allowed("coordinator", "sign", tasks=data, is_pi=False)
    assert not edc_allowed("coordinator", "switch_on", tasks=data, is_pi=False)
    assert not edc_allowed("coordinator", "switch_off", tasks=data, is_pi=False)
    assert edc_allowed("investigator", "switch_on", tasks=frozenset(), is_pi=True)
    assert not edc_allowed("investigator", "switch_on", tasks=data, is_pi=False)  # a sub-investigator
    assert not edc_allowed("investigator", "review", tasks=frozenset({"screen"}), is_pi=False)  # not ticked
    assert edc_allowed("investigator", "review", tasks=data, is_pi=False)  # ticked for data entry
    assert edc_allowed("admin", "switch_off", tasks=frozenset({"screen"}), is_pi=False)
    assert not edc_allowed("admin", "switch_on", tasks=frozenset({"screen"}), is_pi=False)
    assert not edc_allowed("admin", "review", tasks=frozenset({"screen"}), is_pi=False)
    assert not edc_allowed("coordinator", "bogus", tasks=data, is_pi=False)


# ------------------------------------------------------------------ review TB-REV-EDC-01 (D-162)
def _signed(svc: Any, visit: str = "") -> None:
    for r in _by_item(svc.build(k.STUDY, k.RECORD, k.PID, visit, k.VISIT_DATE, "crc")).values():
        if r["state"] == "drafted":
            svc.decide(k.STUDY, r["id"], "confirm", by="crc")
    svc.sign(
        k.STUDY,
        k.RECORD,
        visit,
        signer="crc",
        printed_name="Chen Mei",
        role="coordinator",
        meaning="transcribed",
        meaning_text="I checked each value.",
        lang="en",
        seen=k.seen(svc, visit=visit),
    )


def test_e02_a_record_key_stays_bound_to_its_subject(tmp_path: Path) -> None:
    facts = k.FakeFacts()
    facts.patients["p-0002"] = {"pid": "p-0002", "birth_date": date(1970, 1, 1), "sex": "F"}
    svc, _, _ = k.service(tmp_path, facts=facts)
    k.ready(svc)
    _draft(svc)
    with pytest.raises(EdcError) as e:
        _draft(svc, pid="p-0002")
    assert e.value.code == "edc.pid_mismatch"
    d = svc.store.drafts(k.STUDY, k.RECORD)
    assert {x["pid"] for x in d} == {k.PID}


def test_e03_a_new_run_leaves_one_current_draft_per_item(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    d = _draft(svc)
    svc.decide(k.STUDY, d["weight"]["id"], "reject", by="crc")
    again = svc.store.drafts(k.STUDY, k.RECORD)
    items = [x["item"] for x in again]
    assert len(items) == len(set(items))  # the rejected draft is superseded by the new run, not kept beside it
    _draft(svc)
    items = [x["item"] for x in svc.store.drafts(k.STUDY, k.RECORD)]
    assert len(items) == len(set(items))
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, d["weight"]["id"], "confirm", by="crc")
    assert e.value.code == "edc.superseded"


def test_e04_a_visit_that_is_not_an_event_of_the_project_is_not_sent(tmp_path: Path) -> None:
    from rc_sim.app import create_app

    svc, _, _ = k.service(tmp_path)
    sim = create_app()
    token = k.sim_project(sim, [{"record_id": "1", "redcap_event_name": "baseline_arm_1", "tb_screening_no": k.RECORD}],
                          events=["baseline_arm_1", "week4_arm_1"])  # fmt: skip
    svc.client = lambda _ref: k.client_for(sim, token)
    k.ready(svc)
    _signed(svc, "week9_arm_1")
    out = svc.send_redcap(k.STUDY, "crc")
    assert out["count"] == 0 and len(out["no_event"]) == 6
    _signed(svc, "baseline_arm_1")
    out = svc.send_redcap(k.STUDY, "crc")
    assert out["count"] == 6 and len(out["no_event"]) == 6
    row = next(r for r in k.client_for(sim, token).records() if r["redcap_event_name"] == "baseline_arm_1")
    assert row["weight"] == "72.5"


def test_e05_a_project_with_repeating_forms_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from rc_bridge.client import RedcapClient

    svc, sim, token = k.service(tmp_path)
    k.ready(svc)
    _signed(svc)
    real = RedcapClient.project
    monkeypatch.setattr(RedcapClient, "project",
                        lambda self: {**real(self), "has_repeating_instruments_or_events": 1})  # fmt: skip
    with pytest.raises(EdcError) as e:
        svc.send_redcap(k.STUDY, "crc")
    assert e.value.code == "edc.repeating"
    assert k.client_for(sim, token).records()[0]["weight"] == ""


def test_e06_a_screening_number_on_two_records_is_never_written(tmp_path: Path) -> None:
    svc, sim, token = k.service(tmp_path, records=[{"record_id": "1", "tb_screening_no": k.RECORD},
                                                   {"record_id": "2", "tb_screening_no": k.RECORD.lower()}])  # fmt: skip
    k.ready(svc)
    _signed(svc)
    out = svc.send_redcap(k.STUDY, "crc")
    assert out["count"] == 0 and len(out["duplicate"]) == 6
    assert all(r["weight"] == "" for r in k.client_for(sim, token).records())
    assert {r["result"] for r in svc.store.sent_rows(k.STUDY)} == {"duplicate"}


def test_e07_an_opted_out_patient_is_not_decided_signed_sent_or_exported(tmp_path: Path) -> None:
    svc, sim, token = k.service(tmp_path)
    k.ready(svc)
    d = _confirm_all(svc)
    gone: set[str] = set()
    svc.optouts = lambda: frozenset(gone)
    gone.add(k.PID)
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, d["weight"]["id"], "edit", value="73", reason="x", by="crc",
                   citation={"text": "sheet", "day": "2026-11-05"})  # fmt: skip
    assert e.value.code == "edc.opted_out"
    with pytest.raises(EdcError) as e:
        _sign(svc)
    assert e.value.code == "edc.opted_out"
    with pytest.raises(EdcError) as e:
        _draft(svc)
    assert e.value.code == "edc.opted_out"
    gone.clear()
    _sign(svc)
    gone.add(k.PID)  # opted out after signing
    out = svc.send_redcap(k.STUDY, "crc")
    assert out["count"] == 0 and len(out["opted_out"]) == 6
    assert k.client_for(sim, token).records()[0]["weight"] == ""
    assert "<ItemData " not in svc.export_odm(k.STUDY, "crc")


def test_e08_a_changed_value_carries_its_own_source(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    d = _draft(svc)
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, d["weight"]["id"], "edit", value="99", reason="re-weighed", by="crc")
    assert e.value.code == "edc.edit_source"
    out = svc.decide(k.STUDY, d["weight"]["id"], "edit", value="99", reason="re-weighed", by="crc",
                     citation={"text": "ward scale sheet", "day": "2026-11-05"})  # fmt: skip
    cite = out["final_citation"]
    assert cite["kind"] == "manual" and cite["text"] == "ward scale sheet" and cite["replaces"]["kind"] == "record"
    # the same value with a corrected reason keeps the machine's citation
    out = svc.decide(k.STUDY, d["urate"]["id"], "edit", value="8.4", reason="checked the lab sheet", by="crc")
    assert out["final_citation"]["kind"] == "record"


@pytest.mark.parametrize("status,drafted", [("active", True), ("completed", True), ("stopped", True),
                                            ("entered-in-error", False), ("cancelled", False), ("draft", False)])  # fmt: skip
def test_e09_a_void_medicine_order_never_drafts_yes(tmp_path: Path, status: str, drafted: bool) -> None:
    facts = k.FakeFacts()
    facts.facts = []
    facts.data["medication"] = [{"row": "m1", "code": "M04AA01", "code2": "", "d": date(2026, 9, 1), "name": "allo",
                                 "status": status}]  # fmt: skip
    svc, _, _ = k.service(tmp_path, facts=facts)
    k.ready(svc)
    d = _draft(svc)["cm_allo"]
    assert (d["state"] == "drafted") is drafted
    if drafted:
        assert f"({status})" in d["citation"]["text"]


def test_e19_short_prefixes_and_hospital_codes_match_whole() -> None:
    from edc.prefill import _matches

    m = mapping.ItemMap.from_dict({"item": "cm", "source": "medication", "what": "presence", "codes": ["62", "M04A"]})
    assert not _matches(m, {"code": "", "code2": "620001234"})
    assert not _matches(m, {"code": "6201", "code2": ""})
    assert _matches(m, {"code": "M04AA01", "code2": ""})
    m2 = mapping.ItemMap.from_dict({"item": "cm", "source": "medication", "what": "presence", "codes": ["620001234"]})
    assert _matches(m2, {"code": "", "code2": "620001234"})


def test_e01_the_orchestrator_takes_the_person_from_the_signed_assertion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import FastAPI
    from orchestrator.edc_api import router
    from tb_common.service_auth import actor_header

    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    app = FastAPI()
    app.include_router(router(lambda: svc))
    c = TestClient(app)
    body = {"record": k.RECORD, "pid": k.PID, "visit_date": k.VISIT_DATE}
    # DEV/TEST without a token: the header names the person, and the role must allow the action
    assert c.post(f"/studies/{k.STUDY}/edc/drafts", json=body, headers=actor_header("v1", role="viewer")
                  ).status_code == 403  # fmt: skip
    assert c.post(f"/studies/{k.STUDY}/edc/drafts", json={**body, "by": "crc"}).status_code == 403  # no role
    r = c.post(f"/studies/{k.STUDY}/edc/drafts", json=body, headers=actor_header("crc", role="coordinator"))
    assert r.status_code == 200 and {d["built_by"] for d in r.json()} == {"crc"}
    assert c.post(f"/studies/{k.STUDY}/edc/switch", json={"on": False},
                  headers=actor_header("crc", role="coordinator")).status_code == 403  # fmt: skip
    # with a token: a body or a bare header names nobody; only a signed assertion does
    monkeypatch.setenv("TB_SERVICE_TOKEN", "edc-test-token-0123456789abcdef")
    assert c.post(f"/studies/{k.STUDY}/edc/drafts", json={**body, "by": "crc"}).status_code == 403
    forged = {**actor_header("crc", role="coordinator"), "X-TB-Actor": "drsato"}
    assert c.post(f"/studies/{k.STUDY}/edc/drafts", json=body, headers=forged).status_code == 403
    assert c.post(f"/studies/{k.STUDY}/edc/drafts", json=body,
                  headers=actor_header("crc", "s1", role="coordinator")).status_code == 200  # fmt: skip
    d = {x["item"]: x for x in svc.store.drafts(k.STUDY, k.RECORD)}
    r = c.post(f"/studies/{k.STUDY}/edc/drafts/{d['weight']['id']}/decide", json={"action": "confirm", "by": "eve"},
               headers=actor_header("crc", "s1", role="coordinator"))  # fmt: skip
    assert r.status_code == 200 and r.json()["decided_by"] == "crc"
    sign = {"record": k.RECORD, "printed_name": "Chen Mei", "meaning_text": "I checked each value.",
            "seen": {str(i): s for i, s in k.seen(svc).items()}}  # fmt: skip
    r = c.post(f"/studies/{k.STUDY}/edc/sign", json=sign, headers=actor_header("crc", "s1", role="coordinator"))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "edc.reauth_needed"
    r = c.post(f"/studies/{k.STUDY}/edc/sign", json=sign,
               headers=actor_header("crc", "reauth-0123abcd", role="coordinator"))  # fmt: skip
    assert r.status_code == 200 and r.json()["signer"] == "crc"


class _Says:
    """A note drafter stand-in that gives one fixed answer."""

    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **_: Any) -> Any:
        return SimpleNamespace(data=dict(self.answer), prompt_version="1")


@pytest.mark.parametrize("answer,why", [
    ({"found": True, "value": "0", "quote": "Tophus on the right ear.", "note": "n1"}, "only_yes_from_notes"),
    ({"found": True, "value": "1", "quote": "ear", "note": "n1"}, "quote_not_found"),
])  # fmt: skip
def test_e18_a_note_drafts_only_yes_and_only_with_a_real_quote(tmp_path: Path, answer: dict[str, Any],
                                                                why: str) -> None:  # fmt: skip
    svc, _, _ = k.service(tmp_path, llm=_Says(answer))
    k.ready(svc)
    d = _draft(svc)["tophus"]
    assert d["state"] == "unknown" and d["why"] == why


def test_e26_a_long_note_is_skipped_not_every_note(tmp_path: Path) -> None:
    from edc.prefill import NOTE_CHARS

    facts = k.FakeFacts()
    facts.note_rows.insert(0, {"row": "n0", "d": date(2026, 11, 4), "type": "progress", "text": "x" * (NOTE_CHARS + 1)})
    svc, _, _ = k.service(tmp_path, facts=facts)
    k.ready(svc)
    assert _draft(svc)["tophus"]["state"] == "drafted"  # the older, shorter note is still read
    facts.note_rows = facts.note_rows[:1]
    svc2, _, _ = k.service(tmp_path / "b", facts=facts)
    k.ready(svc2)
    d = _draft(svc2)["tophus"]
    assert d["state"] == "unknown" and d["why"] == "too_long"


def test_e22_a_signed_value_whose_item_left_the_map_stops_the_export(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    _confirm_all(svc)
    _sign(svc)
    svc.put_map(k.STUDY, [m for m in k.MAP if m["item"] != "urate"], k.TARGET, "crc")
    with pytest.raises(EdcError) as e:
        svc.export_odm(k.STUDY, "crc")
    assert e.value.code == "edc.odm_gap" and "urate" in e.value.message


def test_e23_user_ids_do_not_collide(tmp_path: Path) -> None:
    from edc import odm

    assert odm.user_oid("a@b") != odm.user_oid("a_b")
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    _confirm_all(svc)
    _sign(svc)
    one = svc.export_odm(k.STUDY, "crc")
    d = _by_item(svc.store.drafts(k.STUDY, k.RECORD))
    svc.decide(k.STUDY, d["weight"]["id"], "edit", value="73", reason="re-read", by="crc",
               citation={"text": "sheet", "day": "2026-11-05"})  # fmt: skip
    _sign(svc)
    two = svc.export_odm(k.STUDY, "crc")  # the same second, other values: another file id (E-28)
    oid = re.compile(r'FileOID="([^"]+)"')
    m1, m2 = oid.search(one), oid.search(two)
    assert m1 and m2 and m1.group(1) != m2.group(1)
