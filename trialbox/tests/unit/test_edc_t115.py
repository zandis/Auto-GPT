"""T-115 (D-368), the merged EDC prefill card: the signature beside each value (E-12), the stored blind re-entry
result (E-14), what a draft was built under and the checks at confirm and send (E-15, E-16), ODM 1.3.2 by the CDISC
schema (E-23, E-25, STD-062), REDCap validation types and formats (STD-061), ``https`` only (SEC-14) and the REDCap
cassettes (STD-060, CR-062). Synthetic data only (``tests.edc_kit``)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import httpx
import pytest
from datacore import forms
from edc.store import EdcError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rc_bridge.cassette import CassetteMiss, Recording, icd04_run, replay, replay_client, save
from rc_bridge.client import RcError, RedcapClient
from tb_common.service_auth import actor_header

from tests import edc_kit as k
from tests import odm_xsd

NS = {"o": "http://www.cdisc.org/ns/odm/v1.3"}
SHEET = {"text": "ward scale sheet", "day": "2026-11-05"}
CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "redcap_cassettes"


def _d(svc: Any) -> dict[str, dict[str, Any]]:
    return {d["item"]: d for d in svc.store.drafts(k.STUDY, k.RECORD)}


def _built(svc: Any) -> dict[str, dict[str, Any]]:
    return {d["item"]: d for d in svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc")}


def _confirm(svc: Any, items: set[str] | None = None) -> None:
    for d in _d(svc).values():
        if d["state"] == "drafted" and d["fate"] == "open" and (items is None or d["item"] in items):
            svc.decide(k.STUDY, d["id"], "confirm", by="crc")


def _sign(svc: Any, lang: str = "en", text: str = "I checked each value.") -> dict[str, Any]:
    out: dict[str, Any] = svc.sign(k.STUDY, k.RECORD, "", signer="crc", printed_name="Chen Mei", role="coordinator",
                                   meaning="transcribed", meaning_text=text, lang=lang, seen=k.seen(svc))  # fmt: skip
    return out


def _signed(tmp_path: Path) -> tuple[Any, Any, str]:
    svc, sim, token = k.service(tmp_path)
    k.ready(svc)
    _built(svc)
    _confirm(svc)
    _sign(svc)
    return svc, sim, token


def _audit(svc: Any) -> list[dict[str, Any]]:
    out = []
    for f in sorted(Path(svc.audit.directory).glob("*.jsonl")):
        out += [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    return out


def _held(out: dict[str, Any], key: str) -> set[str]:
    return {x["item"] for x in out[key]}


# ------------------------------------------------------------------ SEC-14: https only
@pytest.mark.parametrize("url", ["http://redcap.example/", "http://redcap.example/api/", "ftp://redcap.example/"])
def test_sec14_a_plain_http_redcap_url_is_refused(url: str) -> None:
    with pytest.raises(RcError) as e:
        RedcapClient(url, "0123456789ABCDEF0123456789ABCDEF")
    assert e.value.code == "RC-UPSTREAM" and "https://" in e.value.message
    assert RedcapClient("HTTPS://redcap.example/", "0123456789ABCDEF0123456789ABCDEF").url.endswith("/api")


# ------------------------------------------------------------------ STD-061: validation types and formats
def _f(**row: str) -> forms.Field:
    return forms.field_of({"field_name": "x", "form_name": "f", "field_label": "X", **row})


def test_std061_validation_types_are_read_checked_and_formatted() -> None:
    one = _f(field_type="text", text_validation_type_or_show_slider_number="number_1dp")
    assert (one.kind, one.validation) == ("decimal", "number_1dp")
    assert forms.problem(one, "72.55") == {"field": "x", "code": "decimals", "places": "1"}
    assert forms.reason(forms.problem(one, "72.55") or {}) == "x has at most 1 decimal places"
    assert forms.problem(one, "72") is None and forms.redcap_value(one, "72") == "72.0"  # padded, never rounded
    comma = _f(field_type="text", text_validation_type_or_show_slider_number="number_2dp_comma_decimal")
    assert forms.problem(comma, "72,5") is None and forms.redcap_value(comma, "72.5") == "72,50"
    assert forms.problem(_f(text_validation_type_or_show_slider_number="time"), "25:00") == {"field": "x",
                                                                                              "code": "time"}  # fmt: skip
    assert forms.problem(_f(text_validation_type_or_show_slider_number="time"), "08:30") is None
    assert forms.problem(_f(text_validation_type_or_show_slider_number="email"), "no-at-sign") is not None
    assert forms.problem(_f(text_validation_type_or_show_slider_number="phone"), "call me") is not None
    dmy = _f(text_validation_type_or_show_slider_number="datetime_dmy")
    assert (dmy.kind, dmy.validation) == ("dateTime", "datetime_dmy")
    plain = _f(text_validation_type_or_show_slider_number="date_dmy")  # the API sends YYYY-MM-DD whatever the order
    assert (plain.kind, plain.validation) == ("date", "")
    assert forms.problem(_f(field_type="file"), "a.pdf") == {"field": "x", "code": "not_entered"}
    assert _f(field_type="sql").kind == "calc" and _f(field_type="slider").kind == "integer"


def test_std061_validation_survives_the_questionnaire_and_goes_back_to_redcap() -> None:
    fields = [_f(field_type="text", text_validation_type_or_show_slider_number="number_1dp"),
              forms.field_of({"field_name": "scan", "form_name": "f", "field_type": "file", "field_label": "Scan"})]  # fmt: skip
    back = forms.fields_of(forms.questionnaires("GZQO", fields)[0])
    assert [(f.name, f.kind, f.validation) for f in back] == [("x", "decimal", "number_1dp"), ("scan", "file", "")]
    meta = forms.metadata(back)
    assert (meta[0]["text_validation_type_or_show_slider_number"], meta[1]["field_type"]) == ("number_1dp", "file")
    # what the meaning rests on: choices and type count, a translation does not
    a = forms.field_of({"field_name": "s", "form_name": "f", "field_type": "radio",
                        "select_choices_or_calculations": "1, Male | 2, Female"})  # fmt: skip
    b = forms.field_of({"field_name": "s", "form_name": "f", "field_type": "radio", "field_label:ja": "性別",
                        "select_choices_or_calculations": "1, Male | 2, Female"})  # fmt: skip
    c = forms.field_of({"field_name": "s", "form_name": "f", "field_type": "radio",
                        "select_choices_or_calculations": "1, Female | 2, Male"})  # fmt: skip
    assert forms.field_sha(a) == forms.field_sha(b) != forms.field_sha(c)


def test_std061_a_number_1dp_item_is_formatted_on_send_and_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    crf = [dict(r, text_validation_type_or_show_slider_number="number_1dp") if r["field_name"] == "weight" else r
           for r in k.CRF]  # fmt: skip
    monkeypatch.setattr(k, "CRF", crf)
    svc, sim, token = k.service(tmp_path)
    k.ready(svc)
    d = _built(svc)
    with pytest.raises(EdcError) as e:  # refused locally, by the item's name, before anything reaches REDCap
        svc.decide(k.STUDY, d["weight"]["id"], "edit", value="72.55", reason="re-read", citation=SHEET, by="crc")
    assert e.value.code == "edc.invalid" and e.value.problems == [  # type: ignore[attr-defined]
        {"field": "weight", "code": "decimals", "places": "1"}
    ]
    svc.decide(k.STUDY, d["weight"]["id"], "edit", value="73", reason="scale re-read", citation=SHEET, by="crc")
    _confirm(svc)
    _sign(svc)
    rc = k.client_for(sim, token)
    with pytest.raises(RcError):  # REDCap (the simulator) refuses "73" for a one-decimal field, the whole batch
        rc.import_records([{"record_id": "1", "weight": "73"}])
    out = svc.send_redcap(k.STUDY, "crc")
    assert "weight" in _held(out, "sent") and not out["format"]
    assert rc.records()[0]["weight"] == "73.0"
    assert svc.send_redcap(k.STUDY, "crc")["count"] == 0  # sent once; the formatted value reads back as the same


# ------------------------------------------------------------------ E-15: the map row and the target
def test_e15_a_map_change_supersedes_unsigned_drafts_of_that_item(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    first = _built(svc)
    assert all(first[i]["map_sha"] and first[i]["dict_sha"] and first[i]["target"] == "edc" for i in first)
    svc.decide(k.STUDY, first["weight"]["id"], "confirm", by="crc")
    changed = [dict(m, window_days=60) if m["item"] in ("weight", "sex") else m for m in k.MAP]
    assert svc.put_map(k.STUDY, changed, k.TARGET, "crc")["superseded"] == 2
    now = {d["item"]: d for d in svc.store.drafts(k.STUDY, k.RECORD, current=False)}
    assert now["weight"]["fate"] == now["sex"]["fate"] == "superseded"  # decided but not signed, and open
    assert now["urate"]["fate"] == "open"  # its row did not change
    dec = [x for x in svc.trail(k.STUDY, k.RECORD)["decisions"] if x["action"] == "superseded"]
    assert [(x["item"], x["old"], x["new"]) for x in dec] == [("weight", "72.5", None)]
    again = _built(svc)
    assert again["weight"]["fate"] == "open" and again["weight"]["map_sha"] != first["weight"]["map_sha"]


def test_e15_a_signed_value_whose_map_row_changed_is_not_sent_until_decided_again(tmp_path: Path) -> None:
    svc, _, _ = _signed(tmp_path)
    changed = [dict(m, window_days=120) if m["item"] == "urate" else m for m in k.MAP]
    assert svc.put_map(k.STUDY, changed, k.TARGET, "crc")["superseded"] == 0  # signed values stay as signed
    out = svc.send_redcap(k.STUDY, "crc")
    assert _held(out, "stale_map") == {"urate"} and out["count"] == 5
    assert [r["result"] for r in svc.store.sent_rows(k.STUDY) if r["item"] == "urate"] == ["stale_map"]
    with pytest.raises(EdcError) as e:  # the record lock still holds
        svc.decide(k.STUDY, _d(svc)["urate"]["id"], "edit", value="8.4", reason="map re-checked", by="crc")
    assert e.value.code == "edc.locked"
    urate = _d(svc)["urate"]
    out1 = svc.decide(k.STUDY, urate["id"], "edit", value=urate["final"], reason="map re-checked", by="crc",
                      unlock=True)  # fmt: skip
    assert out1["final"] == "8.4" and out1["map_sha"] != urate["map_sha"]  # decided again under the map of now
    _sign(svc)
    assert _held(svc.send_redcap(k.STUDY, "crc"), "sent") == {"urate"}


def test_e15_a_redcap_connection_is_one_studys_target(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    calls: list[Callable[[], Any]] = [
        lambda: svc.put_map("OTHR", k.MAP, k.TARGET, "crc2"),
        lambda: svc.import_dictionary("OTHR", "edc", "crc2", "record_id"),
    ]
    for call in calls:
        with pytest.raises(EdcError) as e:
            call()
        assert e.value.code == "edc.token_bound"
    assert {(x["event"], x["detail"].get("refused")) for x in _audit(svc) if x["detail"].get("refused")} == {
        ("edc.map", "edc.token_bound"),
        ("edc.dictionary", "edc.token_bound"),
    }


def test_e15_values_signed_for_one_target_are_not_sent_to_another(tmp_path: Path) -> None:
    svc, _, _ = _signed(tmp_path)
    svc.put_map(k.STUDY, k.MAP, {**k.TARGET, "token_ref": "edc2"}, "crc")
    out = svc.send_redcap(k.STUDY, "crc")
    assert out["count"] == 0 and _held(out, "target_changed") == {"brthdat", "sex", "weight", "urate", "mh_gout",
                                                                   "tophus"}  # fmt: skip


def test_e15_the_signed_hash_covers_what_the_draft_was_built_under(tmp_path: Path) -> None:
    svc, _, _ = _signed(tmp_path)
    w = _d(svc)["weight"]
    svc.store.db.execute("UPDATE draft SET map_sha = ? WHERE id = ?", ("0" * 16, w["id"]))
    assert "weight" not in {x["item"] for x in svc.store.sendable(k.STUDY)}  # its hash no longer matches
    assert "weight" not in {x["item"] for x in svc.store.signed(k.STUDY)}  # and it is left out of the ODM file


# ------------------------------------------------------------------ E-16: the dictionary at confirm and at send
def test_e16_a_dictionary_changed_in_redcap_after_signing_holds_the_value(tmp_path: Path) -> None:
    svc, sim, token = _signed(tmp_path)
    meta = sim.state.sim.projects[token]["metadata"]
    for m in meta:
        if m["field_name"] == "sex":  # the codes now mean the other sex in REDCap
            m["select_choices_or_calculations"] = "1, Female | 2, Male"
    out = svc.send_redcap(k.STUDY, "crc")
    assert _held(out, "dictionary_changed") == {"sex"} and out["count"] == 5
    assert k.client_for(sim, token).records()[0]["sex"] == ""


def test_e16_confirm_reads_the_dictionary_of_now(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    svc, sim, token = k.service(tmp_path)
    k.ready(svc)
    d = _built(svc)
    for m in sim.state.sim.projects[token]["metadata"]:
        if m["field_name"] == "sex":
            m["select_choices_or_calculations"] = "1, Female | 2, Male"
    svc.import_dictionary(k.STUDY, "edc", "crc", "record_id")
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, d["sex"]["id"], "confirm", by="crc")
    assert e.value.code == "edc.stale_dictionary"
    assert svc.decide(k.STUDY, d["weight"]["id"], "confirm", by="crc")["fate"] == "confirmed"  # weight unchanged
    assert ("edc.decide", "edc.stale_dictionary") in {(x["event"], x["detail"].get("refused")) for x in _audit(svc)}


# ------------------------------------------------------------------ E-14: the stored re-entry result
def test_e14_the_switch_goes_on_with_the_stored_reentry_result_of_another_person(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    svc.typed_reentry = lambda: False  # a PRODUCTION box: typed numbers never count
    k.ready(svc, on=False)
    with pytest.raises(EdcError) as e:
        svc.set_switch(k.STUDY, True, by="pi", role="investigator", **k.ACK)
    assert e.value.code == "edc.reentry_record"
    with pytest.raises(EdcError) as e:
        svc.record_reentry(k.STUDY, pages=30, accuracy=0.99, document=" ", by="admin1")
    assert e.value.code == "edc.reentry_document"
    svc.record_reentry(k.STUDY, pages=29, accuracy=0.99, document="QA-RE-0007", by="admin1")
    with pytest.raises(EdcError) as e:  # the stored result is below the bar, whatever is typed
        svc.set_switch(k.STUDY, True, by="pi", role="investigator", **k.ACK)
    assert e.value.code == "edc.reentry"
    rec = svc.record_reentry(k.STUDY, pages=30, accuracy=0.991, document="QA-RE-0008", by="admin1")
    sw = svc.set_switch(k.STUDY, True, by="pi", role="investigator", **{**k.ACK, "reentry_pages": 0})
    assert (sw["state"], sw["reentry_pages"], sw["reentry_accuracy"], sw["reentry_id"]) == ("on", 30, 0.991,
                                                                                            rec["id"])  # fmt: skip
    svc.set_switch(k.STUDY, False, by="pi", role="investigator")
    svc.record_reentry(k.STUDY, pages=30, accuracy=0.99, document="QA-RE-0009", by="pi")
    with pytest.raises(EdcError) as e:  # a second person records it
        svc.set_switch(k.STUDY, True, by="pi", role="investigator", **k.ACK)
    assert e.value.code == "edc.reentry_same_person"
    with pytest.raises(Exception, match="append-only"):
        svc.store.db.execute("UPDATE reentry_record SET accuracy = 1")
    assert {x["detail"].get("document") for x in _audit(svc) if x["event"] == "edc.reentry"} >= {"QA-RE-0008"}


def test_e14_only_an_administrator_records_the_reentry_result(tmp_path: Path) -> None:
    from orchestrator.edc_api import router

    svc, _, _ = k.service(tmp_path)
    app = FastAPI()
    app.include_router(router(lambda: svc))
    c = TestClient(app)
    body = {"pages": 30, "accuracy": 0.99, "document": "QA-RE-0010"}
    for role in ("investigator", "coordinator"):
        r = c.post(f"/studies/{k.STUDY}/edc/reentry", json=body, headers=actor_header("pi", role=role))
        assert r.status_code == 403 and r.json()["detail"]["code"] == "edc.role"
    r = c.post(f"/studies/{k.STUDY}/edc/reentry", json=body, headers=actor_header("admin1", role="admin"))
    assert r.status_code == 200 and r.json()["document"] == "QA-RE-0010" and r.json()["by_user"] == "admin1"


# ------------------------------------------------------------------ E-12: the signature beside each value
def test_e12_each_signed_value_shows_who_signed_when_and_the_meaning(tmp_path: Path) -> None:
    from orchestrator.edc_api import router

    svc, _, _ = _signed(tmp_path)
    app = FastAPI()
    app.include_router(router(lambda: svc))
    rows = TestClient(app).get(f"/studies/{k.STUDY}/edc/drafts", params={"record": k.RECORD}).json()
    signed = {d["item"]: d["signature"] for d in rows if d.get("signature_id")}
    assert set(signed) == {"brthdat", "sex", "weight", "urate", "mh_gout", "tophus"}
    assert (
        signed["weight"]["printed_name"] == "Chen Mei" and signed["weight"]["meaning_text"] == "I checked each value."
    )
    assert signed["weight"]["at"] and signed["weight"]["role"] == "coordinator"
    assert "signature" not in {k2 for d in rows if not d.get("signature_id") for k2 in d}
    sigs = svc.trail(k.STUDY, k.RECORD)["signatures"]
    assert sigs[0]["items"] == ["brthdat", "sex", "weight", "urate", "mh_gout", "tophus"]


# ------------------------------------------------------------------ E-23, E-25, STD-062: ODM 1.3.2 by the schema
def test_e23_the_edc_odm_file_validates_against_the_odm_1_3_2_schema(tmp_path: Path) -> None:
    svc, _, _ = _signed(tmp_path)
    w = _d(svc)["weight"]
    svc.decide(k.STUDY, w["id"], "edit", value="73", reason="scale re-read", citation=SHEET, by="crc", unlock=True)
    _sign(svc, "ja", "各値を出典と照合しました。")  # a second meaning text, in another language
    text = svc.export_odm(k.STUDY, "crc")
    assert odm_xsd.problems(text) == []
    lint = odm_xsd.xmllint(text, tmp_path)
    assert lint is None or lint[0] == 0, lint
    root = ET.fromstring(text)
    defs = {d.get("OID"): d for d in root.iterfind(".//o:SignatureDef", NS)}
    assert len(defs) == 2 and {str(o).split(".")[2] for o in defs} == {"en", "ja"}
    refs = {s.get("SignatureOID") for s in root.iterfind(".//o:Signature/o:SignatureRef", NS)}
    assert refs == set(defs)  # each signature points at the words its signer saw
    units = {u.get("Name"): u.get("OID") for u in root.iterfind(".//o:BasicDefinitions/o:MeasurementUnit", NS)}
    assert set(units) == {"kg", "mg/dL"}
    weight = root.find(".//o:ItemDef[@OID='weight']", NS)
    assert weight is not None and weight.find("o:MeasurementUnitRef", NS) is not None
    assert weight.find("o:MeasurementUnitRef", NS).get("MeasurementUnitOID") == units["kg"]  # type: ignore[union-attr]
    brth = root.find(".//o:ItemDef[@OID='brthdat']", NS)
    assert brth is not None and brth.get("SDSVarName") is None  # BRTHDAT is CDASH, not SDTM (STD-062)
    assert "RepeatKey" not in text  # nothing here repeats (E-23 b)
    broken = text.replace('DataType="float"', 'DataType="real"')
    assert odm_xsd.problems(broken)  # the check would see a broken file


# ------------------------------------------------------------------ STD-060, CR-062: cassettes
def test_every_committed_cassette_replays_equal() -> None:
    files = sorted(CASSETTES.glob("*.json"))
    assert files, "no cassette committed"
    for f in files:
        assert '"token"' not in f.read_text(encoding="utf-8")
        now, then = replay(f)
        assert now == then, f.name


def test_a_cassette_records_and_replays_and_misses_loudly(tmp_path: Path) -> None:
    from rc_sim.app import create_app

    sim = create_app()
    token = k.sim_project(sim, [{"record_id": "1", "tb_screening_no": k.RECORD}])
    tc = TestClient(sim, base_url="https://rc")

    def forward(request: httpx.Request) -> httpx.Response:
        r = tc.post("/api/", content=request.content, headers={"content-type": request.headers["content-type"]})
        return httpx.Response(r.status_code, headers={"content-type": r.headers.get("content-type", "")},
                              content=r.content)  # fmt: skip

    rec = Recording(httpx.MockTransport(forward))
    got = icd04_run(RedcapClient("https://rc.example/", token, http=httpx.Client(transport=rec)))
    assert got["version"] == "16.0.10" and got["record"][0]["tb_screening_no"] == k.RECORD
    out = tmp_path / "c.json"
    save(out, version=str(got["version"]), source="test", results=got, exchanges=rec.exchanges)
    assert token not in out.read_text(encoding="utf-8")
    now, then = replay(out)
    assert now == then
    body = json.loads(out.read_text(encoding="utf-8"))
    body["exchanges"][0]["body"] = "17.0.1"  # a REDCap version the client does not support
    out.write_text(json.dumps(body), encoding="utf-8")
    now, then = replay(out)
    assert now["version"] == {"error": "RC-VERSION"} != then["version"]
    c = RedcapClient("https://rc.example/", token, http=replay_client(body["exchanges"]))
    with pytest.raises(CassetteMiss):
        c.records(fields=["sex"])  # never asked of the recorded REDCap
