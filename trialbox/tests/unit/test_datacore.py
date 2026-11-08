"""TrialBox's own data core (D-123): forms from a REDCap data dictionary, entry with every source off, importers
(spreadsheet, FHIR bundle, REDCap) and the two-way sync with per-field ownership and listed conflicts."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import pytest
from datacore import fhir, forms
from datacore.sources import FhirBundleSource, RedcapSource, SheetSource
from datacore.store import DataCore, DataError
from datacore.sync import attach, enter, resolve, sync
from fastapi.testclient import TestClient
from rc_bridge.client import RedcapClient
from rc_sim.app import create_app, load_projects

from tests.rc_kit import TOKEN_A, sim_edit

AT = "2026-11-08T10:00:00+09:00"


def dictionary_a() -> str:
    """Project A's data dictionary as REDCap's API export columns (plus an identifier field TrialBox must drop)."""
    meta = load_projects()[TOKEN_A]["metadata"]
    buf = io.StringIO()
    cols = list(meta[0])
    w = csv.DictWriter(buf, fieldnames=[*cols, "identifier"])
    w.writeheader()
    for m in meta:
        w.writerow({**m, "identifier": ""})
    w.writerow({"field_name": "pt_name", "form_name": "screening", "field_type": "text", "field_label": "Name",
                "identifier": "y"})  # fmt: skip
    return buf.getvalue()


def core(tmp: Path) -> DataCore:
    dc = DataCore(tmp / "datacore.db")
    for q in forms.questionnaires("GZQO", forms.read_dictionary(dictionary_a()), record_field="record_id"):
        dc.put_form("GZQO", q, "redcap-dictionary", AT)
    return dc


def rc_client(sim: Any) -> Any:
    def make() -> RedcapClient:
        rc = RedcapClient("https://rc.example/", TOKEN_A, http=TestClient(sim, base_url="http://rc"))
        rc.url = "/api/"
        return rc

    return make


def test_dictionary_becomes_questionnaires(tmp_path: Path) -> None:
    fields = forms.read_dictionary(dictionary_a())
    qs = forms.questionnaires("GZQO", fields, record_field="record_id")
    assert [q["name"] for q in qs] == ["screening", "trialbox_screening"]
    items = {i["linkId"]: i for q in qs for i in q["item"]}
    assert "pt_name" not in items and "record_id" not in items  # identifier dropped; the record id is the key
    assert items["enrolled"]["type"] == "choice" and [o["valueCoding"]["code"] for o in
                                                      items["enrolled"]["answerOption"]] == ["1", "0"]  # fmt: skip
    assert items["consent_date"]["type"] == "date"
    back = forms.read_dictionary(forms.dictionary_csv(forms.fields_of(qs[0])))  # round-trips to a REDCap CSV
    assert [f.name for f in back] == [i["linkId"] for i in qs[0]["item"]]
    with pytest.raises(forms.FormError) as e:
        forms.read_dictionary("Variable / Field Name,Form Name,Field Type\nBad Name,f,text\n")
    assert e.value.code == "FORM-NAME"
    with pytest.raises(forms.FormError):
        forms.read_dictionary("a,b\n1,2\n")


def test_standalone_entry_checks_types_and_keeps_history(tmp_path: Path) -> None:
    dc = core(tmp_path)
    assert enter(dc, "GZQO", "GZQO-0001", "", {"consent_date": "2026-11-01", "enrolled": "0"}, "crc", AT) == 2
    with pytest.raises(DataError) as e:
        enter(dc, "GZQO", "GZQO-0001", "", {"enrolled": "7"}, "crc", AT)
    assert e.value.code == "DATA-VALUE"
    with pytest.raises(DataError):
        enter(dc, "GZQO", "GZQO-0001", "", {"consent_date": "1 Nov"}, "crc", AT)
    enter(dc, "GZQO", "GZQO-0001", "", {"enrolled": "1"}, "crc", "2026-11-08T11:00:00+09:00")
    h = dc.history("GZQO", "GZQO-0001")
    assert [(x["field"], x["old"], x["new"]) for x in h][-1] == ("enrolled", "0", "1")
    assert dc.record("GZQO", "GZQO-0001") == {"consent_date": "2026-11-01", "enrolled": "1"}


def test_sheet_import_pseudonymises_and_drops_identifiers(tmp_path: Path) -> None:
    dc = core(tmp_path)
    sheet = tmp_path / "pi.csv"
    sheet.write_text("カルテ番号,氏名,電話,同意日,登録\n00123,山田太郎,03-1234-5678,2026-10-30,1\n00456,佐藤,,,\n",
                     encoding="cp932")  # fmt: skip
    src = SheetSource(sheet, {"同意日": "consent_date", "登録": "enrolled"}, mrn_column="カルテ番号",
                      pseudonymise=lambda m: f"{int(m):032x}", out_path=tmp_path / "pi.trialbox.csv",
                      name="sheet:pi")  # fmt: skip
    attach(dc, "GZQO", src, ["consent_date", "enrolled"])
    res = sync(dc, "GZQO", src, "crc", AT)
    assert res.pulled == 2 and res.taken == 2 and src.dropped == ["氏名", "電話"]
    pid = f"{123:032x}"
    assert dc.record("GZQO", pid) == {"consent_date": "2026-10-30", "enrolled": "1"}
    dump = json.dumps(dc.values("GZQO"), ensure_ascii=False)
    assert "山田" not in dump and "00123" not in dump and "03-1234" not in dump
    with pytest.raises(DataError):
        SheetSource(sheet, {"氏名": "consent_date"}, mrn_column="カルテ番号", pseudonymise=str).pull()
    x = tmp_path / "pi.xlsx"
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["screening no", "consent"])
    ws.append(["gzqo-0009", "2026-11-02"])
    wb.save(x)
    rows = SheetSource(x, {"consent": "consent_date"}, key_column="screening no").pull()
    assert rows[0].record == "GZQO-0009" and rows[0].values == {"consent_date": "2026-11-02"}


def test_fhir_bundle_in_and_out(tmp_path: Path) -> None:
    dc = core(tmp_path)
    b = tmp_path / "in.json"
    b.write_text(json.dumps({"resourceType": "Bundle", "type": "collection", "entry": [{"resource": {
        "resourceType": "QuestionnaireResponse", "id": "qr1", "subject": {"reference": "Patient/ab" + "0" * 30},
        "item": [{"linkId": "consent_date", "answer": [{"valueDate": "2026-11-03"}]},
                 {"linkId": "enrolled", "answer": [{"valueCoding": {"code": "1"}}]}]}}]}), encoding="utf-8")  # fmt: skip
    src = FhirBundleSource(b, ["consent_date", "enrolled"], name="fhir:other")
    sync(dc, "GZQO", src, "crc", AT)
    assert dc.record("GZQO", "ab" + "0" * 30) == {"consent_date": "2026-11-03", "enrolled": "1"}
    res = fhir.resources(dc, "GZQO")
    kinds = [r["resourceType"] for r in res]
    assert kinds.count("Questionnaire") == 2 and kinds.count("QuestionnaireResponse") == 1
    qr = next(r for r in res if r["resourceType"] == "QuestionnaireResponse")
    ans = {i["linkId"]: i["answer"][0] for i in qr["item"]}
    assert ans["consent_date"] == {"valueDate": "2026-11-03"} and ans["enrolled"]["valueCoding"]["code"] == "1"


def test_redcap_off_then_on_two_way_with_conflicts(tmp_path: Path) -> None:
    dc = core(tmp_path)
    sim = create_app()
    # 1 REDCap off: the CRC works in TrialBox alone (record GZQO-0901 exists in REDCap too, unknown to TrialBox)
    enter(dc, "GZQO", "GZQO-0901", "", {"consent_date": "2026-10-19", "tb_status": "3"}, "crc", AT)
    enter(dc, "GZQO", "GZQO-0042", "", {"tb_status": "2", "tb_screen_date": "2026-11-05"}, "crc", AT)
    # 2 REDCap on: consent and enrolment are REDCap's; TrialBox's status fields are TrialBox's
    src = RedcapSource(rc_client(sim), field_map={f: f for f in ("consent_date", "enrolled", "subject_no",
                                                                 "tb_status", "tb_screen_date")}, create=True)  # fmt: skip
    attach(dc, "GZQO", src, ["consent_date", "enrolled", "subject_no"])
    with pytest.raises(DataError) as e:  # a REDCap-owned field is changed in REDCap, not here
        enter(dc, "GZQO", "GZQO-0901", "", {"consent_date": "2026-10-20"}, "crc", AT)
    assert e.value.code == "DATA-OWNED"
    res = sync(dc, "GZQO", src, "sync", AT)
    # REDCap says 2026-10-20, TrialBox had 2026-10-19 before the link: listed, not forced
    c = [x for x in res.conflicts if x["field"] == "consent_date"]
    assert c and c[0]["trialbox"] == "2026-10-19" and c[0]["theirs"] == "2026-10-20"
    assert dc.record("GZQO", "GZQO-0901")["consent_date"] == "2026-10-19"
    assert dc.record("GZQO", "GZQO-0901")["enrolled"] == "1"  # new to TrialBox: taken from REDCap
    rows = {r["record_id"]: r for r in rc_client(sim)().records()}
    assert rows["1"]["tb_status"] == "3" and rows["1"]["consent_date"] == "2026-10-20"  # pushed; REDCap's kept
    new = res.created["GZQO-0042"]
    assert rows[new]["tb_screening_no"] == "GZQO-0042" and rows[new]["tb_status"] == "2"
    # 3 someone edits a TrialBox-owned field in REDCap: a conflict, not taken, not pushed over
    sim_edit(sim, 101, [{"record_id": "1", "tb_status": "5"}])
    r2 = sync(dc, "GZQO", src, "sync", AT)
    assert [(x["field"], x["theirs"]) for x in r2.conflicts] == [("tb_status", "5")]
    assert dc.record("GZQO", "GZQO-0901")["tb_status"] == "3" and r2.pushed == 0
    assert sync(dc, "GZQO", src, "sync", AT).conflicts == []  # listed once
    # 4 resolutions: take REDCap's consent date; keep TrialBox's status (pushed again)
    resolve(dc, c[0]["id"], "theirs", "crc", AT)
    resolve(dc, r2.conflicts[0]["id"], "trialbox", "crc", AT)
    r3 = sync(dc, "GZQO", src, "sync", AT)
    assert r3.conflicts == [] and r3.pushed == 1
    assert dc.record("GZQO", "GZQO-0901")["consent_date"] == "2026-10-20"
    assert rc_client(sim)().records(records=["1"])[0]["tb_status"] == "3"
    assert dc.conflicts("GZQO") == []
    # 5 a later REDCap change of its own field is simply taken
    sim_edit(sim, 101, [{"record_id": "1", "subject_no": "S-0101"}])
    assert sync(dc, "GZQO", src, "sync", AT).taken == 1 and dc.record("GZQO", "GZQO-0901")["subject_no"] == "S-0101"
