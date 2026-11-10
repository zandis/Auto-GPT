"""TB-PLAN-04 step 5b (D-131, D-132, D-135): site set-up and data harmonization, at the service level.

A new site space set up the hard way, on the practice site's synthetic inputs: two pasted charts (the model's facts
proposed beside their quotes), an IT dump in Shift_JIS with the hospital's own codes, a messy Excel list. Charts in
Word, PDF and a scan through a fake OCR; no OCR binary is needed. The one rule is checked on the patient check (the
SQL engine) and the counts; the readiness page goes from red to green.
"""

from __future__ import annotations

import io
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.terminology.mapper import Terminology, ValueSets, valueset
from embed_service.embedder import HashEmbedder
from fastapi.testclient import TestClient
from lake.client import LakeLocal
from llm_stub.app import app as stub
from sitesetup import charts, help, mapping, publish, readiness
from sitesetup.ocr import NoOcr
from sitesetup.service import SiteSetup
from sitesetup.store import SetupError, SetupStore
from tb_common.audit import AuditLog, verify
from tb_common.crypto import pid_for_mrn
from tb_common.llm import LlmClient
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR

ROOT = Path(__file__).resolve().parents[2]
KEY = b"site-setup-test-key-0123456789abcdef"
NOW = datetime(2026, 11, 2, 0, 30, tzinfo=UTC)
TODAY = date(2026, 11, 2)
WS = "newsite"


class FakeOcr:
    name = "fake"

    def __init__(self, text: str) -> None:
        self.text = text

    def available(self) -> bool:
        return True

    def image_text(self, data: bytes) -> str:
        return self.text


def _crit(cid: str, kind: str, text: str, logic: dict[str, Any]) -> CriterionIR:
    return CriterionIR.model_validate(
        {"id": cid, "ruleset": "SITE5B", "kind": kind, "class": "structured", "text": text, "logic": logic}
    )


def site_ruleset() -> Ruleset:
    crit = [
        _crit("SITE5B-INC-01", "inclusion", "18+", {"domain": "demographic", "valueset": "NONE", "age": {"min": 18}}),
        _crit(
            "SITE5B-INC-02", "inclusion", "gout", {"domain": "condition", "quantifier": "any", "valueset": "VS_GOUT"}
        ),
        _crit(
            "SITE5B-INC-03",
            "inclusion",
            "urate >= 7",
            {
                "domain": "observation",
                "quantifier": "latest",
                "valueset": "VS_SERUM_URATE",
                "value": {"op": ">=", "num": 7.0, "unit": "mg/dL"},
                "window": {"anchor": "index", "from_days": -365, "to_days": 0},
            },
        ),
        _crit(
            "SITE5B-EXC-01",
            "exclusion",
            "malignancy",
            {"domain": "condition", "quantifier": "any", "valueset": "VS_MALIGNANCY"},
        ),
    ]
    term = Terminology()
    vs = {}
    for name, domain, concept in (
        ("VS_GOUT", "condition", "gout"),
        ("VS_SERUM_URATE", "observation", "serum urate"),
        ("VS_MALIGNANCY", "condition", "malignancy"),
    ):
        res = term.map(domain, concept)
        vs[name] = valueset("SITE5B", name, concept, res.concepts, "1.0.0", families=res.families)
    sql = SqlGenerator("SITE5B", "1.0.0", ValueSets("SITE5B", vs, term)).render(crit)
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    manifest = base.model_copy(update={"id": "SITE5B", "library": None, "criteria": [c.id for c in crit]})
    return Ruleset(manifest=manifest, criteria=crit, valuesets=vs, sql=sql)


@pytest.fixture
def svc(tmp_path: Path) -> Any:
    llm = LlmClient("http://stub/v1", "stub")
    llm.http = TestClient(stub)
    s = SiteSetup(
        SetupStore(),
        tmp_path / "setup",
        LakeLocal(tmp_path / "main-lake", HashEmbedder()),
        llm,
        AuditLog(tmp_path / "audit"),
        lambda: NOW,
        lambda: TODAY,
        lambda: KEY,
        ocr=NoOcr(),
        mrn_regex=r"^\d{8}$",
    )
    yield s
    s.store.close()


def pid(no: str) -> str:
    return pid_for_mrn(KEY, no)


def _states(svc: SiteSetup, rs: Ruleset) -> dict[str, str]:
    return {p["pid"]: p["state"] for p in readiness.patient_check(svc, WS, rs, TODAY)}


STUDY = {"id": "SITE5B", "exists": True, "approved": "1.0.0", "waiting": 0}


def test_a_site_set_up_the_hard_way(svc: SiteSetup, tmp_path: Path) -> None:
    rs = site_ruleset()
    inp = help.practice_inputs()
    r0 = readiness.readiness(svc, WS, {"id": "SITE5B", "exists": False}, {})
    assert r0["overall"] == "red" and r0["questions"]["patients"]["state"] == "red"
    # --- start with the least: two pasted charts. Facts are proposed, beside their quotes
    out = [svc.add_chart(WS, no, "pasted.txt", text.encode(), "crc", "ja", pasted=True) for no, text in inp["charts"]]
    assert out[0]["facts"] >= 5 and out[1]["facts"] >= 2
    facts = svc.store.facts(WS, "proposed")
    assert all(f["quote"] for f in facts) and {f["pid"] for f in facts} == {pid("10000004"), pid("10000005")}
    dx = {(f["pid"], f["code"]) for f in facts if f["domain"] == "condition"}
    assert (pid("10000005"), "C50.919") in dx and (pid("10000004"), "M10.9") in dx
    assert not any(f["code"].startswith("C") for f in facts if f["pid"] == pid("10000004"))  # "悪性腫瘍なし": negated
    assert all("10000004" not in f["quote"] and "青木" not in f["quote"] for f in facts)  # identifiers redacted
    lake = svc.lake(WS)
    docs = lake.query("SELECT text FROM document").to_pylist()
    assert docs and not any("10000004" in d["text"] or "青木" in d["text"] for d in docs)  # notes stay notes, redacted
    r1 = readiness.readiness(svc, WS, STUDY, {"forms": 7})
    miss = {m["key"] for m in r1["questions"]["patients"]["missing"]}
    assert {"patients.proposed", "patients.bulk"} <= miss and r1["questions"]["patients"]["state"] == "amber"
    # the one rule: chart-only facts never count and never exclude
    assert _states(svc, rs) == {pid("10000004"): "needs", pid("10000005"): "needs"}
    # --- the IT dump with the hospital's own codes
    d = svc.add_sheet(WS, "dump", inp["dump"][0], inp["dump"][1], {}, "crc")
    assert d["patients"] == 4 and d["dropped"] == []
    codes = {(c["system"].rsplit(":", 1)[-1], c["code"]): c for c in svc.store.locals(WS)}
    assert codes[("lab-code", "3C020000002327101")]["suggested_code"] == "3084-1"
    assert codes[("drug-code", "3943001F1020")]["suggested_code"] == "M04AA01"
    assert codes[("dx-code", "ZG01")]["suggested_code"] == "M10.9"
    r2 = readiness.readiness(svc, WS, STUDY, {"forms": 7})
    miss2 = {m["key"]: m for m in r2["questions"]["patients"]["missing"]}
    assert "patients.unmapped" in miss2 and "patients.bulk" not in miss2
    assert miss2["patients.unknown_share"]["pct"] > 0  # diagnoses in the hospital's own codes: not readable yet
    st = _states(svc, rs)
    assert st[pid("10000003")] == "needs"  # unmapped: an unknown code system is unknown, never a silent "no" (D-130)
    for c in svc.store.locals(WS):
        target = {"system": c["suggested_system"], "code": c["suggested_code"]}
        if c["code"] == "ZI10":
            target = {"system": mapping.ICD10CM, "code": "I10"}
        svc.map_code(WS, c["domain"], c["system"], c["code"], target, "crc")
    st = _states(svc, rs)
    assert st[pid("10000001")] == "ready" and st[pid("10000003")] == "not_eligible"
    assert st[pid("10000005")] == "needs"  # coded-eligible, with a proposed malignancy: needs information, not out
    # --- the PI's messy sheet: safe fixes made and listed, the rest asked
    sh = svc.add_sheet(WS, "sheet", inp["sheet"][0], inp["sheet"][1], {}, "crc")
    assert sh["dropped"] == ["氏名"] and sh["held"] == ["ID"] and sh["header_row"] == 2
    kinds = {f["kind"] for f in svc.store.fixes(WS)}
    assert {"header_row", "merged", "era", "minguo", "width", "unit", "dmy"} <= kinds
    checks = {c["key"]: c for c in svc.store.checks(WS, open_only=True)}
    assert {"chart_column:ID", "date_order:受診日", "no_key:カルテ番号:5", "unit:尿酸値|g/L"} <= set(checks)
    assert checks["date_order:受診日"]["suggestion"] == "dmy" and checks["chart_column:ID"]["raw"] == "…"
    people = publish.disagreements(svc.store.facts(WS))
    assert [(x["pid"], x["what"]) for x in people] == [(pid("10000002"), "birth_date")]
    with pytest.raises(SetupError):
        svc.answer(int(checks["date_order:受診日"]["id"]), "ymd", "crc")
    # the scripted coordinator works through the list: the suggestions, except the ID column, which is left out
    for key, c in checks.items():
        svc.answer(int(c["id"]), "drop" if key == "chart_column:ID" else c["suggestion"], "crc")
    assert not svc.store.checks(WS, open_only=True)
    for c in svc.store.locals(WS):
        if c["mapped_code"] is None:
            target = (
                {"system": c["suggested_system"], "code": c["suggested_code"]}
                if c["suggested_code"]
                else {"system": mapping.ICD10CM, "code": "I10"}
            )
            svc.map_code(WS, c["domain"], c["system"], c["code"], target, "crc")
    svc.resolve(WS, pid("10000002"), "birth_date", "1971-06-05", "crc")
    assert not publish.disagreements(svc.store.facts(WS))
    assert _states(svc, rs)[pid("10000005")] == "needs"
    fz = readiness.feasibility(svc, WS, rs, TODAY)
    assert fz is not None and fz["steps"][-1]["proposed"] >= 1 and fz["steps"][-1]["confirmed"] == 0
    # --- the coordinator confirms the proposed facts: now they count, and the malignancy excludes
    for f in svc.store.facts(WS, "proposed"):
        svc.decide(int(f["id"]), "confirm", "crc")
    st = _states(svc, rs)
    assert st[pid("10000005")] == "not_eligible" and st[pid("10000004")] == "ready"
    fz = readiness.feasibility(svc, WS, rs, TODAY)
    assert fz is not None and fz["steps"][-1]["confirmed"] >= 1 and fz["steps"][-1]["proposed"] == 0
    r3 = readiness.readiness(svc, WS, STUDY, {"forms": 7})
    assert r3["overall"] == "green", r3
    events = {e["event"] for e in _audit(tmp_path)}
    assert {
        "setup.chart",
        "setup.input",
        "setup.map",
        "setup.check",
        "setup.resolve",
        "setup.fact",
        "setup.publish",
    } <= events
    assert verify(tmp_path / "audit").ok
    trail = (
        (tmp_path / "audit").read_bytes()
        if (tmp_path / "audit").is_file()
        else b"".join(p.read_bytes() for p in (tmp_path / "audit").glob("*.jsonl"))
    )
    assert b"10000004" not in trail and "青木".encode() not in trail


def _audit(tmp: Path) -> list[dict[str, Any]]:
    import json

    return [json.loads(x) for p in sorted((tmp / "audit").glob("*.jsonl")) for x in p.read_text().splitlines() if x]


def test_confirm_correct_reject(svc: SiteSetup) -> None:
    no, text = help.PRACTICE_CHARTS[0]
    svc.add_chart(WS, no, "pasted.txt", text.encode(), "crc", "ja", pasted=True)
    facts = {(f["domain"], f["code"]): f for f in svc.store.facts(WS, "proposed")}
    urate = facts[("observation", "3084-1")]
    assert urate["value"] == "8.8" and urate["unit"] == "mg/dL" and urate["day"] == "2026-09-18"
    out = svc.decide(int(urate["id"]), "correct", "crc", {"value": "８．６"})
    assert out["status"] == "confirmed" and out["value"] == "8.6" and '"8.8"' in (out["before"] or "")
    cr = facts[("observation", "2160-0")]
    assert svc.decide(int(cr["id"]), "reject", "crc")["status"] == "rejected"
    with pytest.raises(SetupError):
        svc.decide(int(cr["id"]), "maybe", "crc")
    obs = {r["oid"] for r in svc.lake(WS).query("SELECT oid FROM observation").to_pylist()}
    assert f"tbcf-{urate['id']}" in obs and f"tbpf-{cr['id']}" not in obs and f"tbcf-{cr['id']}" not in obs


def test_chart_inputs_word_pdf_and_scans(svc: SiteSetup, tmp_path: Path) -> None:
    import docx
    from reportlab.pdfgen import canvas

    d = docx.Document()
    d.add_paragraph("Clinic note 2026-09-20")
    d.add_paragraph("Diagnosis: gout. Serum uric acid 9.1 mg/dL")
    buf = io.BytesIO()
    d.save(buf)
    out = svc.add_chart(WS, "10000010", "note.docx", buf.getvalue(), "crc", "en")
    assert out["method"] == "docx" and out["facts"] >= 2
    pbuf = io.BytesIO()
    c = canvas.Canvas(pbuf)
    c.drawString(72, 720, "Clinic note 2026-09-21")
    c.drawString(72, 700, "Diagnosis: gout. Serum uric acid 8.2 mg/dL")
    c.save()
    out = svc.add_chart(WS, "10000011", "note.pdf", pbuf.getvalue(), "crc", "en")
    assert out["method"] == "pdf" and out["facts"] >= 2
    # a scan: refused plainly without OCR; read with OCR on the box (a fake here)
    with pytest.raises(SetupError) as e:
        svc.add_chart(WS, "10000012", "scan.png", b"\x89PNG fake", "crc", "ja")
    assert e.value.code == "CHART-OCR"
    svc.ocr = FakeOcr("2026年9月22日 診断：痛風 尿酸 9.4 mg/dL")
    out = svc.add_chart(WS, "10000012", "scan.png", b"\x89PNG fake", "crc", "ja")
    assert out["method"] == "ocr" and out["facts"] >= 2 and out["notes"]
    with pytest.raises(SetupError):
        svc.add_chart(WS, "", "pasted.txt", b"text", "crc", pasted=True)  # no chart number: cannot be joined
    with pytest.raises(SetupError):
        svc.add_chart(WS, "ABC", "pasted.txt", b"text", "crc", pasted=True)  # not this hospital's chart number


def test_a_quote_not_in_the_chart_is_dropped() -> None:
    class Liar:
        def chat_json(self, *_a: Any, **_k: Any) -> dict[str, Any]:
            return {
                "facts": [
                    {
                        "domain": "condition",
                        "term": "gout",
                        "code": "M10.9",
                        "system": "icd10cm",
                        "value": "",
                        "unit": "",
                        "date": "",
                        "quote": "gout since 2010",
                    },
                    {
                        "domain": "condition",
                        "term": "cancer",
                        "code": "C50.9",
                        "system": "icd10cm",
                        "value": "",
                        "unit": "",
                        "date": "",
                        "quote": "breast cancer",
                    },
                    {
                        "domain": "observation",
                        "term": "urate",
                        "code": "3084-1",
                        "system": "loinc",
                        "value": "8",
                        "unit": "furlongs",
                        "date": "",
                        "quote": "urate 8",
                    },
                ]
            }

    kept, dropped = charts.extract(Liar(), "Patient has gout since 2010. urate 8 furlongs", "en")
    assert [f["code"] for f in kept] == ["M10.9"] and dropped == 2


def test_join_by_pseudonym_never_by_name(svc: SiteSetup) -> None:
    import csv

    rows = [["患者番号", "氏名", "生年月日"], ["10000001", "青山 太郎", "1961/04/03"]]
    b = io.StringIO()
    csv.writer(b).writerows(rows)
    svc.add_sheet(WS, "dump", "a.csv", b.getvalue().encode("cp932"), {}, "crc")
    rows2 = [["カルテ番号", "名前", "生年月日"], ["１００００００１", "別人 花子", "S36.4.3"]]
    b2 = io.StringIO()
    csv.writer(b2).writerows(rows2)
    svc.add_sheet(WS, "sheet", "b.csv", b2.getvalue().encode("utf-8"), {}, "crc")
    people = {f["pid"] for f in svc.store.facts(WS)}
    assert people == {pid("10000001")}  # one patient: same chart number, different names; names never stored
    dump = str(svc.store.facts(WS)) + str(svc.store.inputs(WS))
    assert "青山" not in dump and "別人" not in dump and "10000001" not in dump
    assert not publish.disagreements(svc.store.facts(WS))  # 1961/04/03 and S36.4.3 are the same day


def test_templates_and_practice_site(svc: SiteSetup) -> None:
    from openpyxl import load_workbook

    for lang, word in (("ja", "カルテ番号"), ("zh-TW", "病歷號"), ("en", "Chart number")):
        wb = load_workbook(io.BytesIO(help.candidate_template(lang)))
        assert wb.worksheets[0]["A1"].value == word and len(wb.worksheets) == 2
    inp = help.practice_inputs()
    svc.add_sheet("practice", "dump", inp["dump"][0], inp["dump"][1], {}, "crc")
    sheet = help.mapping_sheet(svc.store.locals("practice"), "ja")
    wb = load_workbook(io.BytesIO(sheet))
    ws = wb.worksheets[0]
    ws["H2"] = ws["F2"].value
    buf = io.BytesIO()
    wb.save(buf)
    rows = help.read_mapping_sheet(buf.getvalue())
    assert len(rows) == 1 and rows[0]["use"]
    svc.reset("practice", "admin")
    assert not svc.store.inputs("practice")
    with pytest.raises(SetupError):
        svc.reset("main", "admin")  # the hospital's own data is never reset from here
