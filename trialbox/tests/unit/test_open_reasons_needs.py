"""H-7 (REAL2): every open answer names what the site must supply: the view and the field of the site mapping template
and the concept the criterion reads, in en, ja and zh-TW. Shipped criteria; synthetic outcomes only."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml
from matching.cascade.model import Outcome, PatientTrace
from orchestrator.scenarios.screen_cascade import verdict_of, verdicts_of
from tb_common import open_reasons
from tb_common.reasons import Reason
from tb_common.ruleset import Ruleset

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "services" / "adapter" / "mapping" / "tw_core" / "demo_his.yaml"


def _crit(rs: str, cid: str):  # type: ignore[no-untyped-def]
    return Ruleset.load(ROOT / "rulesets" / rs).by_id()[cid]


def _template_columns() -> dict[str, set[str]]:
    """Every column the template reads, per logical table (``column``, ``start``/``end``, ``base64``, lookups' keys)."""
    doc = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    cols: dict[str, set[str]] = {t: set() for t in doc["tables"]}
    for r in doc["resources"]:
        for spec in (r.get("elements") or {}).values():
            if isinstance(spec, dict):
                for k in ("column", "start", "end", "base64", "unit_column", "key", "display_column"):
                    if isinstance(spec.get(k), str):
                        cols[r["table"]].add(spec[k])
    return cols


def test_every_named_view_and_field_is_one_the_template_reads() -> None:
    cols = _template_columns()
    for view, field in open_reasons.named_sources():
        assert field in cols.get(view, set()), f"{view}.{field} is not read by {TEMPLATE.name}"


@pytest.mark.parametrize(
    ("rs", "cid", "raw", "view", "field", "concept"),
    [
        # the twin's encounters carry no department: the clinic visit list cannot be read
        ("NEUR-COH", "NEUR-COH-INC-02", "code_system_not_carried", "encounter", "dept_code", "VS_MEMORY_CLINIC_VISIT"),
        # a duration needs each order's end
        ("RA-BIO", "RA-BIO-INC-03", "order_dates_missing", "medication", "end_date", "VS_METHOTREXATE"),
        # a coded answer value of a lab test
        ("RA-JAK", "RA-JAK-EXC-02", "unknown kept", "lab", "result_value", "VS_HBSAG"),
        # the first atom of an and/not: the lab test, not the medicine
        ("RA-BIO", "RA-BIO-EXC-03", "unknown kept", "lab", "result_value", "VS_HBSAG"),
        # a score's missing input: its own view and field
        ("GOUT-COH", "GOUT-COH-INC-06", "derived_missing_input:height", "vital", "height_cm", "bmi: height"),
        ("RA-COH", "RA-COH-INC-03", "derived_missing_input:tjc28", "lab", "result_value", "das28: tjc28"),
        # a vital sign value
        ("GZQO", "GZQO-EXC-09", "unknown kept", "vital", "sbp", "VS_SYSTOLIC_BLOOD_PRESSURE"),
        # no procedure record of the list's system
        ("GZQO", "GZQO-EXC-05", "code_system_not_carried", "procedure", "order_code", "VS_BARIATRIC_SURGERY"),
        # a note criterion: the note feed
        ("GZQO", "GZQO-INC-05", "no notes in window", "note", "text", "GZQO-INC-05"),
        # a mixed criterion the notes would settle
        ("RA-JAK", "RA-JAK-EXC-06", "no notes in window", "note", "text", "RA-JAK-EXC-06"),
    ],
)
def test_needs_names_view_field_and_concept(rs: str, cid: str, raw: str, view: str, field: str, concept: str) -> None:
    r = Ruleset.load(ROOT / "rulesets" / rs)
    n = open_reasons.needs(raw, r.by_id()[cid], r.valuesets)
    assert n == {"view": view, "field": field, "concept": concept}


def test_a_decided_answer_or_one_a_person_decides_needs_nothing() -> None:
    c = _crit("GZQO", "GZQO-EXC-06")
    assert open_reasons.needs(Reason.CODED.value, c) is None
    assert open_reasons.needs(Reason.HUMAN.value, c) is None


def test_every_site_gap_and_product_reason_names_a_source() -> None:
    """Whatever the reason of an open coded answer (except a person's), the site is told a view and a field."""
    c = _crit("GZQO", "GZQO-EXC-06")
    for r in sorted(open_reasons.SITE_GAP | open_reasons.PRODUCT):
        n = open_reasons.needs(r.value, c)
        assert n is not None and n["view"] and n["field"] and n["concept"], r


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_the_text_names_the_view_field_and_concept_in_each_language(lang: str) -> None:
    n = {"view": "encounter", "field": "dept_code", "concept": "VS_MEMORY_CLINIC_VISIT"}
    s = open_reasons.needs_text(n, lang)
    assert "encounter.dept_code" in s and "VS_MEMORY_CLINIC_VISIT" in s
    assert s != open_reasons.needs_text(n, "en") or lang == "en"  # each language its own sentence


def test_an_open_screening_answer_carries_its_need_and_a_decided_one_none() -> None:
    rs = Ruleset.load(ROOT / "rulesets" / "NEUR-COH")
    c = rs.by_id()["NEUR-COH-INC-02"]
    gap = verdict_of(Outcome(c.id, "unknown", "S1", unknown_kind="data_gap", reason="code_system_not_carried"), rs=rs)
    assert gap.evidence is not None and gap.evidence.reason == "code_system_not_carried"
    assert gap.evidence.needs is not None and gap.evidence.needs.model_dump() == {
        "view": "encounter", "field": "dept_code", "concept": "VS_MEMORY_CLINIC_VISIT"}  # fmt: skip
    met = verdict_of(Outcome(c.id, "pass", "S1", reason="matching record"), rs=rs)
    assert met.evidence is not None and met.evidence.needs is None
    # the patient's rows, as the candidate list stores them, carry the same
    t = PatientTrace(pid="p1", index_date=date(2026, 10, 5), department="NEUR")
    t.outcomes = {c.id: Outcome(c.id, "unknown", "S1", unknown_kind="data_gap", reason="code_system_not_carried")}
    row = next(v for v in verdicts_of(rs, t).verdicts if v.id == c.id)
    assert row.evidence is not None and row.evidence.needs is not None and row.evidence.needs.field == "dept_code"


def test_the_patient_page_row_carries_the_need() -> None:
    from console import studies

    need = {"view": "medication", "field": "end_date", "concept": "VS_METHOTREXATE"}
    ev = {"reason": "order_dates_missing", "needs": need}
    rows = studies.patient_rows([{"id": "X", "verdict": "unknown", "evidence": ev}], {})
    assert rows[0]["needs"] == need
    assert studies.patient_rows([{"id": "X", "verdict": "pass", "evidence": {}}], {})[0]["needs"] is None


def test_a_score_input_with_a_wrong_unit_names_the_unit_and_an_adult_score_the_birth_date() -> None:
    r = Ruleset.load(ROOT / "rulesets" / "AD-MAB")
    c = r.by_id()["AD-MAB-EXC-04"]  # eGFR (JSN) below 30
    unit = open_reasons.needs("derived_unit:creatinine", c, r.valuesets)
    assert unit == {"view": "lab", "field": "unit", "concept": "egfr_jsn: creatinine"}
    adult = open_reasons.needs("derived_adult_only", c, r.valuesets)
    assert adult == {"view": "patient", "field": "birth_date", "concept": "egfr_jsn"}


def test_a_vital_sign_is_told_by_its_loinc_code_and_system_together() -> None:
    r = Ruleset.load(ROOT / "rulesets" / "GZQO")
    c = r.by_id()["GZQO-EXC-09"]
    local = {"VS_SYSTOLIC_BLOOD_PRESSURE": {"compose": {"include": [{"system": "https://hospa.test/lab-local",
                                                                      "concept": [{"code": "8480-6"}]}]}}}  # fmt: skip
    assert open_reasons.needs("unknown kept", c, local) == {
        "view": "lab", "field": "result_value", "concept": "VS_SYSTOLIC_BLOOD_PRESSURE"}  # fmt: skip
