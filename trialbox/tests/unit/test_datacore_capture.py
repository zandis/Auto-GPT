"""TB-PLAN-04 step 4 (D-129): TrialBox's built-in forms, the checks at entry (branching, required, type, range,
ownership), the change history, and the exports (ODM 1.3.2, REDCap CSV, XLSX), with ODM re-imported into a fresh
REDCap simulator project that has the same dictionary, every value equal."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from typing import Any
from xml.etree import ElementTree as ET

import pytest
from datacore import branching, builtin, export, forms
from datacore.store import DataCore, DataError
from datacore.sync import enter, save_form
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from rc_sim.app import create_app

AT = "2026-11-08T10:00:00+09:00"
ODM = "{http://www.cdisc.org/ns/odm/v1.3}"


@pytest.fixture
def dc() -> Iterator[DataCore]:
    core = DataCore()  # TB_DB_URL: the test's own schemas (tests/conftest.py)
    for q in builtin.builtin_questionnaires("GZQO"):
        core.put_form("GZQO", q, builtin.ORIGIN, AT)
    yield core
    core.close()


# ---------------------------------------------------------------------------------------------- the forms
def test_seven_builtin_forms_in_three_languages() -> None:
    fields = builtin.fields()
    assert list(dict.fromkeys(f.form for f in fields)) == list(builtin.TITLES)
    assert len(builtin.TITLES) == 7 and all(set(t) == {"en", "ja", "zh-TW"} for t in builtin.TITLES.values())
    for f in fields:
        assert f.label and set(f.labels) == {"ja", "zh-TW"}, f.name
        assert len({f.label, f.labels["ja"], f.labels["zh-TW"]}) == 3 or f.label.endswith("(kg)"), f.name
        for g in ("ja", "zh-TW"):
            assert set(f.option_labels.get(g, {})) == set(f.options), (f.name, g)
        assert branching.supported(f.branching), f.branching
        assert not f.identifier
    ae = {f.name: f for f in fields if f.form == "tb_adverse_event"}
    assert {"ae_term", "ae_onset", "ae_serious", "ae_severity", "ae_outcome", "ae_related"} <= set(ae)
    assert ae["ae_term"].kind == "text" and set(ae["ae_related"].options) == {"1", "0", "9"}
    visit = {f.name: f for f in fields if f.form == "tb_visit"}
    assert visit["vs_status"].options == {"1": "Done", "2": "Missed"} and visit["vs_window_note"].kind == "notes"
    wd = {f.name for f in fields if f.form == "tb_withdrawal"}
    assert {"wd_date", "wd_reason"} <= wd


def test_questionnaire_carries_languages_required_range_and_branching() -> None:
    qs = builtin.builtin_questionnaires("GZQO")
    assert forms.titles_of(qs[1]) == {"en": "Consent", "ja": "同意", "zh-TW": "知情同意"}
    items = {i["linkId"]: i for q in qs for i in q["item"]}
    assert "record_id" not in items  # the record key, not an item
    date = items["vs_date"]
    assert date["required"] is True and date["enableWhen"] == [{"question": "vs_status", "operator": "=",
                                                                "answerCoding": {"code": "1"}}]  # fmt: skip
    assert {"url": forms.MIN_VALUE, "valueDate": "2000-01-01"} in date["extension"]
    assert items["en_age"]["extension"][:2] == [{"url": forms.MIN_VALUE, "valueInteger": 0},
                                                {"url": forms.MAX_VALUE, "valueInteger": 120}]  # fmt: skip
    assert items["ae_end"]["enableBehavior"] == "any"
    back = {f.name: f for q in qs for f in forms.fields_of(q)}
    src = {f.name: f for f in builtin.fields()}
    for name, f in back.items():
        s = src[name]
        assert (f.kind, f.label, f.labels, f.options, f.option_labels, f.required, f.vmin, f.vmax, f.branching) == (
            s.kind,
            s.label,
            s.labels,
            s.options,
            s.option_labels,
            s.required,
            s.vmin,
            s.vmax,
            s.branching,
        ), name
    assert back["vs_weight"].label_in("ja") == "体重(kg)" and back["ae_severity"].options_in("zh-TW")["3"] == "重度"
    # the dictionary round-trips with its languages (the XLSX's dictionary sheet), and without them for REDCap
    rows = forms.metadata(list(back.values()), translations=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    again = {f.name: f for f in forms.read_dictionary(buf.getvalue())}
    assert again["ic_copy"].option_labels == back["ic_copy"].option_labels
    plain = forms.read_dictionary(forms.dictionary_csv(list(back.values())))
    assert [(f.name, f.branching, f.vmin) for f in plain] == [(f.name, f.branching, f.vmin) for f in back.values()]


def test_branching_subset() -> None:
    p = branching.parse("[a] = '1' and ([b] <> 2 or [c]=\"x\")")
    assert p == ["and", ["=", "a", "1"], ["or", ["<>", "b", "2"], ["=", "c", "x"]]]
    assert branching.evaluate(p, {"a": "1", "b": "3"}) and branching.evaluate(p, {"a": "1", "b": "2", "c": "x"})
    assert not branching.evaluate(p, {"a": "1", "b": "2"}) and not branching.evaluate(p, {"a": "0"})
    assert branching.evaluate(branching.parse("[n] = 2") or [], {"n": "2.0"})  # numbers compare as numbers
    assert branching.evaluate(branching.parse("[x] = ''") or [], {}) and branching.shown("", {})
    for rule in ("[a(1)] = '1'", "datediff([a], 'today') > 1", "[a] > 1", "[a] = '1' and", "[e][a] = '1'"):
        assert branching.parse(rule) is None and branching.shown(rule, {}), rule  # outside the subset: shown
    sel = branching.css_show(p, {"a", "b", "c"})
    assert sel == [
        ':has(input[name="f_a"][value="1"]:checked):not(:has(input[name="f_b"][value="2"]:checked))',
        ':has(input[name="f_a"][value="1"]:checked):has(input[name="f_c"][value="x"]:checked)',
    ]
    assert branching.css_show(p, {"a", "b"}) is None  # c is free text: the server decides
    css = branching.css_rules({"x": "[a] = '1'", "y": "[t] = 'z'", "z": "[a(1)] = '1'"}, {"a"})
    assert css == '#entry:not(:has(input[name="f_a"][value="1"]:checked)) .q-x { display: none; }\n'


# ---------------------------------------------------------------------------------------------- entry
def test_whole_form_save_checks_and_history(dc: DataCore) -> None:
    with pytest.raises(DataError) as e:
        save_form(dc, "GZQO", "GZQO-0001", "", "tb_consent", {"ic_date": "2026-13-01", "ic_copy": "7"}, "crc", AT)
    got = {(p["field"], p["code"]) for p in e.value.problems}
    assert got == {("ic_date", "date"), ("ic_copy", "choice"), ("ic_version", "required")}
    assert e.value.code == "DATA-FORM" and dc.history("GZQO") == []  # refused whole: nothing written
    # a hidden field is never required: ic_reconsent_date only shows when ic_reconsent = 1
    out = save_form(dc, "GZQO", "GZQO-0001", "", "tb_consent",
                    {"ic_date": "2026-11-02", "ic_version": "v2.1", "ic_copy": "1", "ic_reconsent": "0",
                     "ic_reconsent_date": "2026-11-03"}, "crc", AT)  # fmt: skip
    assert out["changed"] == 4 and out["hidden"] == ["ic_reconsent_date"]
    assert "ic_reconsent_date" not in dc.record("GZQO", "GZQO-0001")
    with pytest.raises(DataError) as e:
        save_form(dc, "GZQO", "GZQO-0001", "", "tb_consent", {"ic_reconsent": "1"}, "crc", AT,
                  reason_text="re-consented")  # D-778: a saved value changes with a reason  # fmt: skip
    assert [(p["field"], p["code"]) for p in e.value.problems] == [("ic_reconsent_date", "required")]
    # range: weight 1..400, age 0..120; a missed visit needs its reason, not a date
    with pytest.raises(DataError) as e:
        save_form(dc, "GZQO", "GZQO-0001", "v1", "tb_visit", {"vs_status": "1", "vs_date": "2026-11-05",
                                                              "vs_weight": "999"}, "crc", AT)  # fmt: skip
    assert e.value.problems == [{"field": "vs_weight", "code": "max", "max": "400"}]
    with pytest.raises(DataError) as e:
        save_form(dc, "GZQO", "GZQO-0001", "v1", "tb_visit", {"vs_status": "2"}, "crc", AT)
    assert [(p["field"], p["code"]) for p in e.value.problems] == [("vs_missed_reason", "required")]
    save_form(dc, "GZQO", "GZQO-0001", "v1", "tb_visit", {"vs_status": "1", "vs_date": "2026-11-05",
                                                          "vs_weight": "61.5"}, "crc", AT)  # fmt: skip
    with pytest.raises(DataError) as e:
        save_form(dc, "GZQO", "GZQO-0001", "", "tb_enrolment", {"en_date": "2026-11-06", "en_eligible": "1",
                                                                "en_age": "-1", "nope": "x"}, "crc", AT)  # fmt: skip
    assert {(p["field"], p["code"]) for p in e.value.problems} == {("en_age", "min"), ("nope", "unknown")}
    # an edit shows in the history: who, when, old, new, source (D-778: with its reason)
    save_form(dc, "GZQO", "GZQO-0001", "", "tb_consent", {"ic_version": "v2.2"}, "pi-desk", "2026-11-09T09:00:00",
              reason_text="version misread")  # fmt: skip
    hist = [(h["field"], h["old"], h["new"], h["by"], h["source"]) for h in dc.history("GZQO", "GZQO-0001")]
    assert ("ic_version", "v2.1", "v2.2", "pi-desk", "trialbox") in hist and ("ic_version", None, "v2.1", "crc",
                                                                              "trialbox") in hist  # fmt: skip
    # ownership as before: a source's field is changed in that source
    dc.set_owner("GZQO", "ic_by", "redcap")
    with pytest.raises(DataError) as e:
        save_form(dc, "GZQO", "GZQO-0001", "", "tb_consent", {"ic_by": "AB"}, "crc", AT)
    assert e.value.problems == [{"field": "ic_by", "code": "owned", "owner": "redcap"}]
    with pytest.raises(DataError) as e:
        save_form(dc, "GZQO", "GZQO-0001", "", "tb_nope", {}, "crc", AT)
    assert e.value.problems[0]["code"] == "form"


def test_a_redcap_dictionary_with_rules_outside_the_subset_still_imports_and_saves(dc: DataCore) -> None:
    text = ("field_name,form_name,field_type,field_label,branching_logic,required_field,"
            "select_choices_or_calculations\n"
            "record_id,f,text,ID,,,\nsx,f,checkbox,Symptoms,,,\"1, Fever | 2, Cough\"\n"
            "temp,f,text,Temperature,[sx(1)] = '1',y,\n")  # fmt: skip
    fs = forms.read_dictionary(text)
    for q in forms.questionnaires("OTHR", fs, record_field="record_id"):
        dc.put_form("OTHR", q, "redcap-dictionary", AT)
    out = save_form(dc, "OTHR", "OTHR-1", "", "f", {"sx": "1,2"}, "crc", AT)  # temp: rule unknown, so not required
    assert out["changed"] == 1
    assert enter(dc, "OTHR", "OTHR-1", "", {"temp": "38"}, "crc", AT) == 1  # the step-3 path is unchanged


# ---------------------------------------------------------------------------------------------- exports
def _filled(dc: DataCore) -> None:
    save_form(dc, "GZQO", "GZQO-0001", "", "tb_consent", {"ic_date": "2026-11-02", "ic_version": "v2.1",
                                                          "ic_copy": "1"}, "crc", AT)  # fmt: skip
    save_form(dc, "GZQO", "GZQO-0001", "v1", "tb_visit", {"vs_status": "1", "vs_date": "2026-11-05",
                                                          "vs_weight": "61.5", "vs_window": "0",
                                                          "vs_window_note": "二日遅れ, 患者都合"}, "crc", AT)  # fmt: skip
    save_form(dc, "GZQO", "GZQO-0002", "", "tb_adverse_event", {"ae_term": "頭痛 & <めまい>", "ae_onset": "2026-11-03",
              "ae_serious": "0", "ae_severity": "1", "ae_related": "9"}, "crc", AT)  # fmt: skip


def _fresh(sim: Any, dc: DataCore, events: list[str]) -> str:
    meta = forms.metadata(export.export_fields(dc, "GZQO"))
    r = TestClient(sim).post("/sim/projects", json={"title": "GZQO re-import", "metadata": meta, "events": events})
    assert r.status_code == 200, r.text
    return str(r.json()["token"])


def _sim_values(sim: Any, token: str) -> dict[tuple[str, str, str], str]:
    rows = TestClient(sim).post("/api/", data={"token": token, "content": "record", "format": "json"}).json()
    out = {}
    for r in rows:
        ev = r.pop("redcap_event_name", "")
        rid = r.pop("record_id")
        for k, v in r.items():
            if v != "":
                out[(rid, "" if ev == export.BASE_EVENT else ev, k)] = v
    return out


def test_odm_is_well_formed_with_standard_oids_and_reimports_equal(dc: DataCore) -> None:
    _filled(dc)
    text = export.odm(dc, "GZQO", AT)
    root = ET.fromstring(text)
    assert root.tag == f"{ODM}ODM" and root.get("ODMVersion") == "1.3.2" and root.get("FileType") == "Snapshot"
    study = root.find(f"{ODM}Study")
    assert study is not None and study.get("OID") == "Project.GZQO"
    mdv = study.find(f"{ODM}MetaDataVersion")
    assert mdv is not None
    oids = {e.get("OID") for e in mdv}
    assert {"Event.event_1_arm_1", "Event.v1", "Form.tb_consent", "Form.tb_visit", "ic_date", "vs_weight",
            "ic_copy.choices"} <= oids  # fmt: skip
    refs = {e.get(a) for e in mdv.iter() for a in ("FormOID", "ItemGroupOID", "ItemOID", "CodeListOID",
                                                   "StudyEventOID") if e.get(a)}  # fmt: skip
    assert refs <= oids  # every reference has its definition
    q = mdv.find(f"{ODM}ItemDef[@OID='ic_date']/{ODM}Question")
    assert q is not None and [(t.get("{http://www.w3.org/XML/1998/namespace}lang"), t.text) for t in q] == [
        ("en", "Date of consent"),
        ("ja", "同意取得日"),
        ("zh-TW", "簽署同意日期"),
    ]
    rc = mdv.find(f"{ODM}ItemDef[@OID='vs_weight']/{ODM}RangeCheck")
    assert rc is not None and rc.get("Comparator") == "GE"
    cd = root.find(f"{ODM}ClinicalData")
    assert cd is not None and cd.get("MetaDataVersionOID") == mdv.get("OID")
    assert [s.get("SubjectKey") for s in cd] == ["GZQO-0001", "GZQO-0002"]
    # a fresh REDCap project with the same dictionary takes the ODM back, every value equal
    sim = create_app()
    token = _fresh(sim, dc, [export.BASE_EVENT, "v1"])
    r = TestClient(sim).post("/api/", data={"token": token, "content": "record", "format": "odm", "type": "flat",
                                            "data": text, "returnContent": "ids"})  # fmt: skip
    assert r.status_code == 200 and r.json() == ["GZQO-0001", "GZQO-0002"], r.text
    assert _sim_values(sim, token) == export.values_of(dc, "GZQO")


def test_odm_validates_against_the_odm_1_3_2_schema(dc: DataCore, tmp_path: Any) -> None:
    """T-115 (STD-062, E-25): the data-core export is valid ODM 1.3.2 by the CDISC schema, as lxml and xmllint read
    it; a float carries Length and SignificantDigits."""
    from tests import odm_xsd

    _filled(dc)
    text = export.odm(dc, "GZQO", AT)
    assert odm_xsd.problems(text) == []
    lint = odm_xsd.xmllint(text, tmp_path)
    assert lint is None or lint[0] == 0, lint
    assert odm_xsd.problems(text.replace("<StudyName>", "<StudyNam>").replace("</StudyName>", "</StudyNam>"))
    weight = ET.fromstring(text).find(f".//{ODM}ItemDef[@OID='vs_weight']")
    assert weight is not None and weight.get("Length") and weight.get("SignificantDigits")


def test_classic_study_and_checkboxes_round_trip(dc: DataCore) -> None:
    text = (
        "field_name,form_name,field_type,field_label,select_choices_or_calculations\n"
        'record_id,f,text,ID,\nsx,f,checkbox,Symptoms,"1, Fever | 2, Cough | 3, Rash"\nnote,f,notes,Note,\n'
    )
    for q in forms.questionnaires("OTHR", forms.read_dictionary(text), record_field="record_id"):
        dc.put_form("OTHR", q, "redcap-dictionary", AT)
    save_form(dc, "OTHR", "OTHR-1", "", "f", {"sx": "1,3", "note": "a\nb"}, "crc", AT)
    cols, rows = export.flat(dc, "OTHR")
    assert cols == ["record_id", "sx___1", "sx___2", "sx___3", "note"]  # classic: no event column
    assert rows == [{"record_id": "OTHR-1", "sx___1": "1", "sx___2": "0", "sx___3": "1", "note": "a\nb"}]
    meta = forms.metadata(export.export_fields(dc, "OTHR"))
    sim = create_app()
    token = TestClient(sim).post("/sim/projects", json={"metadata": meta}).json()["token"]
    r = TestClient(sim).post("/api/", data={"token": token, "content": "record", "format": "odm", "type": "flat",
                                            "data": export.odm(dc, "OTHR", AT)})  # fmt: skip
    assert r.json() == {"count": 1}
    assert _sim_values(sim, token) == export.values_of(dc, "OTHR")


def test_redcap_csv_columns_match_the_dictionary_and_xlsx(dc: DataCore) -> None:
    _filled(dc)
    text = export.redcap_csv(dc, "GZQO")
    rows = list(csv.DictReader(io.StringIO(text)))
    names = [f.name for f in export.export_fields(dc, "GZQO")]
    assert list(rows[0]) == ["record_id", "redcap_event_name", *names[1:]]
    assert [(r["record_id"], r["redcap_event_name"]) for r in rows] == [
        ("GZQO-0001", "event_1_arm_1"),
        ("GZQO-0001", "v1"),
        ("GZQO-0002", "event_1_arm_1"),
    ]
    assert rows[1]["vs_window_note"] == "二日遅れ, 患者都合" and rows[2]["ae_term"] == "頭痛 & <めまい>"
    wb = load_workbook(io.BytesIO(export.xlsx(dc, "GZQO")))
    assert wb.sheetnames == ["data", "dictionary"]
    data = list(wb["data"].iter_rows(values_only=True))
    assert list(data[0]) == list(rows[0]) and len(data) == 4
    dic = list(wb["dictionary"].iter_rows(values_only=True))
    assert "field_label:ja" in dic[0] and any("同意取得日" in [str(x) for x in r] for r in dic)


def test_sim_refuses_odm_with_a_dtd_and_unknown_fields(dc: DataCore) -> None:
    _filled(dc)
    sim = create_app()
    token = _fresh(sim, dc, [export.BASE_EVENT, "v1"])
    bad = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><ODM/>'
    r = TestClient(sim).post("/api/", data={"token": token, "content": "record", "format": "odm", "data": bad})
    assert r.status_code == 400
    text = export.odm(dc, "GZQO", AT).replace('ItemOID="ae_term"', 'ItemOID="not_a_field"')
    r = TestClient(sim).post("/api/", data={"token": token, "content": "record", "format": "odm", "data": text})
    assert r.status_code == 400 and "not_a_field" in r.text
    r = TestClient(sim).post("/api/", data={"token": token, "content": "metadata", "format": "odm"})
    assert r.status_code == 400
