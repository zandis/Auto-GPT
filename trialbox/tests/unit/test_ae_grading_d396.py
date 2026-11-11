"""D-396 (T-619b, STD-050, STD-051, STD-063): CTCAE grade and version on the built-in AE form of an oncology study,
and the CDISC export with CDASH IE rows for a screen failure and DS rows per CDASH, fed from the screening log."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from xml.etree import ElementTree as ET

import pytest
from datacore import builtin, export, forms
from datacore.lifecycle import Lifecycle
from datacore.store import DataCore, DataError
from datacore.sync import save_form
from edc import cdash, mapping
from edc.mapping import ItemMap

AT = "2026-11-08T10:00:00+09:00"
ODM = "{http://www.cdisc.org/ns/odm/v1.3}"
ONC = "ONCO"
FAILED = "ONCO-EXC-06"


def _items(qs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {i["linkId"]: i for q in qs for i in q["item"]}


@pytest.fixture
def dc() -> Iterator[DataCore]:
    core = DataCore()  # TB_DB_URL: the test's own schemas (tests/conftest.py)
    for q in builtin.builtin_questionnaires(ONC, "5.0"):
        core.put_form(ONC, q, builtin.ORIGIN, AT)
    yield core
    core.close()


# ---------------------------------------------------------------------------------------------- CTCAE (STD-051)
def test_an_oncology_study_grades_each_ae_1_to_5_with_the_ctcae_version() -> None:
    items = _items(builtin.builtin_questionnaires(ONC, "5.0"))
    grade, version = items["ae_ctcae_grade"], items["ae_ctcae_version"]
    assert [o["valueCoding"]["code"] for o in grade["answerOption"]] == ["1", "2", "3", "4", "5"]
    assert grade["required"] is True and version["required"] is True
    assert [o["valueCoding"]["display"] for o in version["answerOption"]] == ["CTCAE v5.0"]  # the study's one
    assert "required" not in items["ae_severity"]  # AETOXGR or AESEV: the grade carries it here
    back = {f.name: f for q in builtin.builtin_questionnaires(ONC, "6") for f in forms.fields_of(q)}
    assert back["ae_ctcae_version"].options == {"6": "CTCAE v6.0"}
    assert set(back["ae_ctcae_grade"].option_labels) == {"ja", "zh-TW"}
    assert back["ae_ctcae_grade"].option_labels["ja"]["3"].startswith("グレード3")
    assert builtin.ctcae_of(builtin.builtin_questionnaires(ONC, "v6.0")) == "CTCAE v6.0"


def test_a_study_without_a_ctcae_version_keeps_mild_moderate_severe() -> None:
    items = _items(builtin.builtin_questionnaires("GZQO"))
    assert "ae_ctcae_grade" not in items and "ae_ctcae_version" not in items
    assert items["ae_severity"]["required"] is True
    assert builtin.ctcae_of(builtin.builtin_questionnaires("GZQO")) == ""
    for bad in ("4.03", "7", "CTCAE"):
        with pytest.raises(ValueError):
            builtin.ctcae_code(bad)
    assert [builtin.ctcae_code(v) for v in ("", "5", "5.0", "v5.0", "CTCAE v6.0")] == ["", "5", "5", "5", "6"]


def test_a_graded_ae_is_saved_and_exported_with_its_version(dc: DataCore) -> None:
    out = save_form(dc, ONC, "ONCO-0001", "ae1", "tb_adverse_event", {
        "ae_term": "末梢神経障害", "ae_onset": "2026-11-03", "ae_serious": "0", "ae_related": "1",
        "ae_ctcae_grade": "3", "ae_ctcae_version": "5"}, "crc", AT)  # fmt: skip
    assert out["changed"] >= 6
    with pytest.raises(DataError):  # the grade is a choice of 1 to 5 only
        save_form(dc, ONC, "ONCO-0001", "ae2", "tb_adverse_event", {
            "ae_term": "x", "ae_onset": "2026-11-03", "ae_serious": "0", "ae_related": "1",
            "ae_ctcae_grade": "6", "ae_ctcae_version": "5"}, "crc", AT)  # fmt: skip
    root = ET.fromstring(export.odm(dc, ONC, AT, cdisc=True))
    grade = root.find(f".//{ODM}ItemDef[@OID='ae_ctcae_grade']/{ODM}Alias")
    assert grade is not None and (grade.get("Context"), grade.get("Name")) == ("CDASH", "AE.AETOXGR")
    ver = root.find(f".//{ODM}ItemDef[@OID='ae_ctcae_version']/{ODM}Alias")
    assert ver is not None and ver.get("Name") == "TS.TOXGRV"
    vals = {e.get("ItemOID"): e.get("Value") for e in root.iter(f"{ODM}ItemData")}
    assert vals["ae_ctcae_grade"] == "3" and vals["ae_ctcae_version"] == "5"


# ---------------------------------------------------------------------------------------------- IE and DS (STD-063)
def test_the_cdisc_odm_carries_ie_rows_for_a_screen_failure(dc: DataCore, tmp_path: Any) -> None:
    from tests import odm_xsd

    life = Lifecycle(dc)
    life.ensure(ONC, "ONCO-0001", "1" * 32, "crc", AT)
    life.step(ONC, "ONCO-0001", "screen_fail", by="crc", at=AT, on_day="2026-11-02", reason="not_eligible",
              criterion=FAILED, criteria_version="3.0.0")  # fmt: skip
    life.ensure(ONC, "ONCO-0002", "2" * 32, "crc", AT)  # still a candidate: no IE, no DS
    text = export.odm(dc, ONC, AT, cdisc=True)
    assert odm_xsd.problems(text) == []
    lint = odm_xsd.xmllint(text, tmp_path)
    assert lint is None or lint[0] == 0, lint
    root = ET.fromstring(text)
    mdv = root.find(f".//{ODM}MetaDataVersion")
    assert mdv is not None
    ie_def = mdv.find(f"{ODM}ItemGroupDef[@OID='IG.IE']")
    assert ie_def is not None and ie_def.get("Domain") == "IE" and ie_def.get("Repeating") == "Yes"
    oids = {e.get("OID") for e in mdv}
    refs = {e.get(a) for e in mdv.iter() for a in ("FormOID", "ItemGroupOID", "ItemOID", "CodeListOID")
            if e.get(a)}  # fmt: skip
    assert refs <= oids
    subjects = {s.get("SubjectKey"): s for s in root.iter(f"{ODM}SubjectData")}
    assert set(subjects) == {"ONCO-0001"}

    def rows(dom: str) -> list[dict[str, str]]:
        return [{str(i.get("ItemOID")).split(".")[1]: str(i.get("Value")) for i in g}
                for g in subjects["ONCO-0001"].iter(f"{ODM}ItemGroupData") if g.get("ItemGroupOID") == f"IG.{dom}"]  # fmt: skip

    assert rows("IE") == [{"IECAT": "EXCLUSION", "IETESTCD": "EXCL06", "IETEST": f"{FAILED} (v3.0.0)",
                           "IEORRES": "Y", "IEDAT": "2026-11-02"}]  # fmt: skip
    assert rows("DS") == [{"DSCAT": "DISPOSITION EVENT", "DSDECOD": "SCREEN FAILURE",
                           "DSTERM": "SCREEN FAILURE: NOT ELIGIBLE", "DSSTDAT": "2026-11-02"}]  # fmt: skip
    plain = export.odm(dc, ONC, AT)  # the REDCap round trip: no CDASH items in the plain ODM
    assert "IG.IE" not in plain and "Alias" not in plain


def test_ds_rows_follow_cdash_for_consent_completion_and_withdrawal(dc: DataCore) -> None:
    life = Lifecycle(dc)
    life.ensure(ONC, "ONCO-0003", "3" * 32, "crc", AT)
    for to, day in (("approached", "2026-10-01"), ("consented", "2026-10-02"), ("enrolled", "2026-10-03"),
                    ("on_study", "2026-10-04")):  # fmt: skip
        life.step(ONC, "ONCO-0003", to, by="crc", at=AT, on_day=day)
    life.step(ONC, "ONCO-0003", "withdrawn", by="crc", at=AT, on_day="2026-10-20", reason="3")
    got = export.cdash_rows(dc, ONC)["ONCO-0003"]
    assert [(d, r["DSDECOD"], r["DSSTDAT"]) for d, r in got] == [
        ("DS", "INFORMED CONSENT OBTAINED", "2026-10-02"),
        ("DS", "ADVERSE EVENT", "2026-10-20"),
    ]
    assert [r["DSCAT"] for _, r in got] == ["PROTOCOL MILESTONE", "DISPOSITION EVENT"]
    steps = [{"new": "consented", "on_day": "2026-01-02"}, {"new": "completed", "on_day": "2026-06-01"}]
    assert [r["DSDECOD"] for r in cdash.ds_rows(steps)] == ["INFORMED CONSENT OBTAINED", "COMPLETED"]
    for code, decod in cdash.WITHDRAWAL_DECOD.items():
        assert cdash.ds_rows([{"new": "withdrawn", "on_day": "2026-01-02", "reason": code}])[0]["DSDECOD"] == decod
    # a screen failure without a criterion: its DS row stands, no IE row
    assert cdash.ie_rows([{"new": "screen_fail", "on_day": "2026-01-02", "reason": "declined"}]) == []
    assert cdash.ie_rows([{"new": "screen_fail", "criterion": "I3", "on_day": "2026-01-02"}])[0]["IEORRES"] == "N"


def test_criterion_ids_become_cdash_short_names() -> None:
    assert [cdash.ie_category(c) for c in ("GZQO-INC-02", "GZQO-EXC-06", "I3", "E1", "AGE-MIN")] == [
        "INCLUSION", "EXCLUSION", "INCLUSION", "EXCLUSION", ""]  # fmt: skip
    assert [cdash.ie_testcd(c) for c in ("GZQO-INC-02", "GZQO-EXC-6", "I3", "age_min:v2.long")] == [
        "INCL02", "EXCL06", "INCL03", "AGEMINV2"]  # fmt: skip
    assert all(len(cdash.ie_testcd(c)) <= 8 for c in ("A" * 48, "X-EXC-123456789"))


def test_the_cdash_tags_cover_ae_ie_and_ds() -> None:
    for tag in ("AE.AETOXGR", "AE.AETERM", "IE.IETESTCD", "IE.IEORRES", "IE.IECAT", "DS.DSDECOD", "DS.DSSTDAT"):
        assert tag in cdash.VARIABLES and cdash.valid_tag(tag)
    assert set(cdash.BUILTIN.values()) <= set(cdash.VARIABLES)
    names = {f.name for f in builtin.fields()}
    assert set(cdash.BUILTIN) <= names
    assert cdash.sds_name("IEDAT") == "" and cdash.sds_name("AETOXGR") == "AETOXGR"


def test_the_item_map_tags_a_grade_only_on_a_choice_of_grades() -> None:
    fields = {f.name: f for f in builtin.study_fields("5")}
    sug = {m.item: m for m in mapping.suggest(list(fields.values()), set())}
    assert sug["ae_ctcae_grade"].cdash == "AE.AETOXGR" and sug["ae_ctcae_grade"].source == "none"
    assert sug["ae_term"].cdash == "AE.AETERM"
    assert mapping.check([ItemMap("ae_ctcae_grade", "AE.AETOXGR")], fields, set()) == []
    bad = mapping.check([ItemMap("ae_outcome", "AE.AETOXGR"), ItemMap("ae_term", "AE.AETOXGR")], fields, set())
    assert [b["code"] for b in bad] == ["cdash_grade", "cdash_grade"]
    text = forms.Field("ae_grade", "f", "text", "AE grade")
    assert mapping.suggest([text], set())[0].cdash == ""  # a free-text grade gets no tag rather than a refused one
