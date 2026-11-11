"""T-302d (D-435): ODM import as proposals a person confirms; refused whole with a named reason.

The fixtures are TrialBox's own ODM export of the synthetic longitudinal study of ``test_edc_t302b`` (two arms, a
repeating AE instrument on week 4) and small hand-made files. Synthetic data only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from datacore.forms import Field
from datacore.lifecycle import Lifecycle
from edc import odm_import as oi
from edc.service import EdcService
from edc.store import EdcError

from tests import edc_kit as k
from tests.unit.test_edc_t302b import AE1, AE2, SCREEN1, _drafts, _enter, _service

OID = f"Project.{k.STUDY}"
NEW = "S-003"


def _subject(svc: EdcService, record: str = NEW, pid: str = "p-0003") -> None:
    Lifecycle(svc.dc).ensure(k.STUDY, record, pid, "crc", k.STAMP.isoformat())


def _signed_study(tmp_path: Path) -> tuple[EdcService, str]:
    svc, *_ = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight", "urate", "brthdat", "sex"}))
    _enter(svc, "S-001", AE1, {"ae_term": "gout flare", "ae_serious": "0"})
    _enter(svc, "S-001", AE2, {"ae_term": "rash", "ae_serious": "1", "ae_sae_reason": "hospitalised"})
    return svc, svc.export_odm(k.STUDY, "crc")


def _open(svc: EdcService, record: str) -> dict[tuple[str, str], dict[str, Any]]:
    return {(d["visit"], d["item"]): d for d in svc.store.drafts(k.STUDY, record) if d["fate"] == "open"}


def _odm(body: str, head: str = "", mdv: str = "") -> bytes:
    return (f'<?xml version="1.0" encoding="UTF-8"?>{head}<ODM xmlns="http://www.cdisc.org/ns/odm/v1.3" '
            f'FileType="Snapshot" FileOID="F.1" ODMVersion="1.3.2" CreationDateTime="2026-11-09T10:00:00+00:00">'
            f'<Study OID="{OID}"><MetaDataVersion OID="M.1" Name="m">{mdv}</MetaDataVersion></Study>'
            f'<ClinicalData StudyOID="{OID}" MetaDataVersionOID="M.1">{body}</ClinicalData></ODM>').encode()  # fmt: skip


def _row(items: str, form: str = "baseline", event: str = SCREEN1, rec: str = NEW, fkey: str = "") -> str:
    fk = f' FormRepeatKey="{fkey}"' if fkey else ""
    return (f'<SubjectData SubjectKey="{rec}"><StudyEventData StudyEventOID="Event.{event}">'
            f'<FormData FormOID="Form.{form}"{fk}><ItemGroupData ItemGroupOID="{form}.x">{items}</ItemGroupData>'
            f"</FormData></StudyEventData></SubjectData>")  # fmt: skip


# ------------------------------------------------------------------ the acceptance round trip
def test_own_export_with_a_repeating_ae_reimports_equal_as_open_drafts(tmp_path: Path) -> None:
    """An AE on a repeating instrument exports and re-imports equal (TB-ASSESS-01 T-302 contract), as proposals."""
    svc, text = _signed_study(tmp_path)
    signed = {(d["visit"], d["item"]): d["final"] for d in svc.store.signed(k.STUDY, "S-001")}
    assert (AE2, "ae_sae_reason") in signed
    _subject(svc)
    out = svc.import_odm(k.STUDY, text.replace('SubjectKey="S-001"', f'SubjectKey="{NEW}"').encode(), "crc",
                         "back.odm.xml")  # fmt: skip
    got = _open(svc, NEW)
    assert {key: d["value"] for key, d in got.items()} == signed
    assert len(out["drafted"]) == len(signed) and not out["decided"]
    d = got[(AE2, "ae_term")]
    assert d["state"] == "drafted" and d["pid"] == "p-0003" and d["signature_id"] is None
    assert d["citation"]["kind"] == "odm" and d["citation"]["file"] == out["file"]
    assert d["citation"]["path"] == f"{NEW}/Event.week4_arm_1/Form.ae[2]/ae_term"
    # nothing signed, nothing decided: the import is a proposal (the product never writes a regulated record)
    assert svc.store.signatures(k.STUDY, NEW) == []
    assert svc.store.signed(k.STUDY, NEW) == []
    assert svc.store.trail(k.STUDY, NEW)["decisions"] == []
    # a person confirms and signs; the next export cites the file
    svc.decide(k.STUDY, d["id"], "confirm", by="crc")
    assert (svc.store.draft(k.STUDY, d["id"]) or {})["fate"] == "confirmed"
    svc.sign(k.STUDY, NEW, AE2, signer="crc", printed_name="Chen Mei", role="coordinator", meaning="transcribed",
             meaning_text="I checked each value.", lang="en", seen=k.seen(svc, NEW, AE2))  # fmt: skip
    assert f"odm:{out['file'][:16]}:{NEW}/Event.week4_arm_1/Form.ae[2]/ae_term" in svc.export_odm(k.STUDY, "crc")


def test_reimport_keeps_decisions_and_lists_the_same_file(tmp_path: Path) -> None:
    svc, text = _signed_study(tmp_path)
    out = svc.import_odm(k.STUDY, text.encode(), "crc")  # S-001's own values: all signed already
    assert out["drafted"] == [] and len(out["decided"]) == len(svc.store.signed(k.STUDY, "S-001"))
    _subject(svc)
    data = text.replace('SubjectKey="S-001"', f'SubjectKey="{NEW}"').encode()
    first = svc.import_odm(k.STUDY, data, "crc")
    again = svc.import_odm(k.STUDY, data, "crc")
    assert again["drafted"] == [] and len(again["same"]) == len(first["drafted"])


def test_an_import_replaces_only_the_same_items_open_draft(tmp_path: Path) -> None:
    svc, *_ = _service(tmp_path)
    svc.build(k.STUDY, "S-001", k.PID, SCREEN1, k.VISIT_DATE, "crc")
    before = _drafts(svc, "S-001", SCREEN1)
    out = svc.import_odm(k.STUDY, _odm(_row('<ItemData ItemOID="weight" Value="80"/>', rec="S-001")), "crc")
    after = _drafts(svc, "S-001", SCREEN1)
    assert [x["item"] for x in out["drafted"]] == ["weight"]
    assert after["weight"]["value"] == "80" and after["weight"]["citation"]["kind"] == "odm"
    assert after["weight"]["visit_date"] == k.VISIT_DATE  # the visit's own date, from its drafts
    assert {i: d["id"] for i, d in after.items() if i != "weight"} == {
        i: d["id"] for i, d in before.items() if i != "weight"}  # fmt: skip
    assert (svc.store.draft(k.STUDY, before["weight"]["id"]) or {})["fate"] == "superseded"


def test_a_file_in_shift_jis_is_read_through_the_one_decoder(tmp_path: Path) -> None:
    svc, *_ = _service(tmp_path)
    _subject(svc)
    term = "痛風発作、右足の親指が腫れて痛む"
    data = _odm(_row(f'<ItemData ItemOID="ae_term" Value="{term}"/>', form="ae", event="week4_arm_1", fkey="1"),
                mdv='<FormDef OID="Form.ae" Name="ae" Repeating="Yes"/>').decode()  # fmt: skip
    raw = data.replace('encoding="UTF-8"', 'encoding="Shift_JIS"').encode("cp932")
    svc.import_odm(k.STUDY, raw, "crc")
    assert _open(svc, NEW)[("week4_arm_1__ae__1", "ae_term")]["value"] == term


# ------------------------------------------------------------------ refusals: named, audited, all or nothing
REFUSALS = {
    "odm.dtd": _odm(_row('<ItemData ItemOID="weight" Value="&x;"/>'), head='<!DOCTYPE ODM [<!ENTITY x "80">]>'),
    "odm.dtd_external": _odm(_row('<ItemData ItemOID="weight" Value="80"/>'),
                             head='<!DOCTYPE ODM SYSTEM "http://example.invalid/odm.dtd">'),
    "odm.xml": b'<ODM xmlns="http://www.cdisc.org/ns/odm/v1.3"><Study',
    "odm.not_odm": b"<html/>",
    "odm.study": _odm(_row('<ItemData ItemOID="weight" Value="80"/>')).replace(
        f'ClinicalData StudyOID="{OID}"'.encode(), b'ClinicalData StudyOID="Project.OTHER"'),
    "odm.duplicate_value": _odm(_row('<ItemData ItemOID="weight" Value="80"/><ItemData ItemOID="weight" Value="81"/>')),
    "odm.duplicate_oid": _odm(_row('<ItemData ItemOID="weight" Value="80"/>'),
                              mdv='<FormDef OID="Form.ae" Name="a"/><FormDef OID="Form.ae" Name="b"/>'),
    "odm.unknown_item": _odm(_row('<ItemData ItemOID="weight" Value="80"/><ItemData ItemOID="bmi" Value="23"/>')),
    "odm.wrong_form": _odm(_row('<ItemData ItemOID="weight" Value="80"/>', form="ae")),
    "odm.invalid": _odm(_row('<ItemData ItemOID="urate" Value="7.0"/><ItemData ItemOID="weight" Value="heavy"/>')),
    "odm.repeat_key": _odm(_row('<ItemData ItemOID="weight" Value="80"/>', fkey="2")),
    "odm.transaction": _odm(_row('<ItemData ItemOID="weight" Value="80" TransactionType="Remove"/>')),
    "odm.version": _odm(_row("")).replace(b'ODMVersion="1.3.2"', b'ODMVersion="2.0"'),
    "odm.unknown_subject": _odm(_row('<ItemData ItemOID="weight" Value="80"/>', rec="S-404")),
}  # fmt: skip


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_a_file_that_does_not_validate_is_refused_whole_with_its_reason(tmp_path: Path, case: str) -> None:
    svc, *_ = _service(tmp_path)
    _subject(svc)
    with pytest.raises(EdcError) as e:
        svc.import_odm(k.STUDY, REFUSALS[case], "crc")
    assert e.value.code == case.removesuffix("_external")
    assert svc.store.drafts(k.STUDY, NEW) == []  # never half-imported: the good value beside it is not kept
    events = [json.loads(line) for f in sorted(Path(svc.audit.directory).glob("*.jsonl"))
              for line in f.read_text(encoding="utf-8").splitlines() if '"edc.odm_import"' in line]  # fmt: skip
    assert events[-1]["detail"]["refused"] == e.value.code and "file" in events[-1]["detail"]


def test_entity_expansion_is_refused_before_anything_expands() -> None:
    lol = '<!ENTITY l0 "lol">' + "".join(f'<!ENTITY l{i} "&l{i - 1};&l{i - 1};&l{i - 1};">' for i in range(1, 10))
    with pytest.raises(oi.OdmRefused) as e:
        oi.read(_odm("", head=f"<!DOCTYPE ODM [{lol}]>"), OID)
    assert e.value.code == "odm.dtd"


def test_size_and_depth_are_bounded() -> None:
    data = _odm(_row('<ItemData ItemOID="weight" Value="80"/>'))
    with pytest.raises(oi.OdmRefused) as e:
        oi.read(data, OID, env={oi.MAX_BYTES_ENV: str(len(data) - 1)})
    assert e.value.code == "odm.size"
    deep = b'<ODM xmlns="http://www.cdisc.org/ns/odm/v1.3">' + b"<a>" * 40 + b"</a>" * 40 + b"</ODM>"
    with pytest.raises(oi.OdmRefused) as e:
        oi.read(deep, OID)
    assert e.value.code == "odm.depth"


def test_a_switch_that_is_off_refuses_the_import(tmp_path: Path) -> None:
    svc, *_ = _service(tmp_path)
    svc.set_switch(k.STUDY, False, by="pi", role="investigator")
    with pytest.raises(EdcError) as e:
        svc.import_odm(k.STUDY, _odm(_row('<ItemData ItemOID="weight" Value="80"/>', rec="S-001")), "crc")
    assert e.value.code == "edc.off"


def test_an_opted_out_patient_is_refused(tmp_path: Path) -> None:
    svc, *_ = _service(tmp_path)
    _subject(svc)
    svc.optouts = lambda: frozenset({"p-0003"})
    with pytest.raises(EdcError) as e:
        svc.import_odm(k.STUDY, _odm(_row('<ItemData ItemOID="weight" Value="80"/>')), "crc")
    assert e.value.code == "edc.opted_out" and svc.store.drafts(k.STUDY, NEW) == []


# ------------------------------------------------------------------ the reader alone
def test_checkbox_choices_fold_back_and_vendor_elements_are_left_out() -> None:
    fields = {"sym": Field("sym", "baseline", "multi", "Symptoms", options={"1": "Pain", "2": "Swelling", "3": "Red"})}
    body = ('<SubjectData SubjectKey="S-9"><StudyEventData StudyEventOID="Event.event_1_arm_1" '
            'StudyEventRepeatKey="1"><FormData FormOID="Form.baseline" FormRepeatKey="1" xmlns:r="urn:x">'
            '<r:note>vendor text</r:note><ItemGroupData ItemGroupOID="baseline.sym" ItemGroupRepeatKey="1">'
            '<ItemData ItemOID="sym___1" Value="1" r:flag="x"/><ItemData ItemOID="sym___2" Value="0"/>'
            '<ItemData ItemOID="sym___3" Value="1"/></ItemGroupData></FormData></StudyEventData></SubjectData>')  # fmt: skip
    got = oi.proposals(oi.read(_odm(body), OID), fields, ["sym"])
    assert [(p.record, p.visit, p.item, p.value) for p in got] == [("S-9", "event_1_arm_1", "sym", "1,3")]


def test_a_repeating_event_instance_takes_d414s_name() -> None:
    fields = {"vs_status": Field("vs_status", "visit", "text", "Status")}
    body = (
        '<SubjectData SubjectKey="S-9"><StudyEventData StudyEventOID="Event.ae" StudyEventRepeatKey="3">'
        '<FormData FormOID="Form.visit"><ItemGroupData ItemGroupOID="visit.vs_status">'
        '<ItemData ItemOID="vs_status" Value="done"/></ItemGroupData></FormData></StudyEventData></SubjectData>'
    )
    f = oi.read(_odm(body, mdv='<StudyEventDef OID="Event.ae" Name="ae" Repeating="Yes" Type="Common"/>'), OID)
    assert [p.visit for p in oi.proposals(f, fields, ["vs_status"])] == ["ae__3"]


def test_the_orchestrator_route_takes_the_file_and_the_role_of_a_draft(tmp_path: Path) -> None:
    import base64

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from orchestrator.edc_api import router
    from tb_common.service_auth import actor_header

    svc, *_ = _service(tmp_path)
    _subject(svc)
    app = FastAPI()
    app.include_router(router(lambda: svc))
    c = TestClient(app)
    url = f"/studies/{k.STUDY}/edc/import/odm"
    good = {
        "name": "x.odm.xml",
        "data": base64.b64encode(_odm(_row('<ItemData ItemOID="weight" Value="80"/>'))).decode(),
    }
    assert c.post(url, json=good, headers=actor_header("v1", role="viewer")).status_code == 403
    r = c.post(url, json=good, headers=actor_header("crc", role="coordinator"))
    assert r.status_code == 200 and [x["item"] for x in r.json()["drafted"]] == ["weight"]
    bad = {"data": base64.b64encode(REFUSALS["odm.dtd"]).decode()}
    r = c.post(url, json=bad, headers=actor_header("crc", role="coordinator"))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "odm.dtd"
    r = c.post(url, json={"data": "not base64!"}, headers=actor_header("crc", role="coordinator"))
    assert r.status_code == 400
