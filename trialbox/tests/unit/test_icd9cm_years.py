"""NEW-STD-1 (STD-001, D-586): a Taiwanese diagnosis from the ICD-9-CM years says so.

Before: a row ``714.0`` dated 2014-03-02 was emitted as ``icd-10-cm 714.0`` and, with TW Core, also tagged
``icd-10-cm-2014-tw 714.0``; ``250.00`` and ``V58.69`` the same.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from adapter.mapping.engine import Mapper, Mapping

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
ICD9, ICD10 = "http://hl7.org/fhir/sid/icd-9-cm", "http://hl7.org/fhir/sid/icd-10-cm"
TW2014 = "https://twcore.mohw.gov.tw/ig/twcore/CodeSystem/icd-10-cm-2014-tw"
TW2023 = "https://twcore.mohw.gov.tw/ig/twcore/CodeSystem/icd-10-cm-2023-tw"


def _mapper(tmp_path: Path, params: dict[str, str] | None, profiles: str = "tw-core") -> Mapper:
    doc: dict[str, Any] = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    doc["fhir_profiles"] = profiles
    if params is not None:
        doc["params"] = params
    for name, spec in (doc.get("lookups") or {}).items():  # the copy lives elsewhere: point at the shipped files
        spec["file"] = str(BASE.parent / spec["file"])
        doc["lookups"][name] = spec
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return Mapper(Mapping.load(path), b"k" * 32, "s")


def _diag(code: str, day: str, **more: str) -> dict[str, str]:
    return {"diag_no": "D1", "enc_no": "E1", "mrn": "P1", "icd10": code, "diag_date": day, "recorded_date": day,
            "status": "A", **more}  # fmt: skip


def _systems(mapper: Mapper, row: dict[str, str]) -> dict[str, str]:
    (res,) = mapper.map_table("diagnosis", iter([row]))
    return {c["system"]: c["code"] for c in (res.get("code") or {}).get("coding") or []}


@pytest.fixture
def tw(tmp_path: Path) -> Mapper:
    return _mapper(tmp_path, {"icd9cm_before": "2016-01-01"})


@pytest.mark.parametrize(("code", "day"), [("714.0", "2014-03-02"), ("250.00", "2009-11-30"), ("V58.69", "2015-12-31"),
                                           ("E849.0", "2001-01-01"), ("714.0", "20140302")])  # fmt: skip
def test_a_diagnosis_of_the_icd9cm_years_carries_icd9cm_and_nothing_else(tw: Mapper, code: str, day: str) -> None:
    assert _systems(tw, _diag(code, day)) == {ICD9: code}


@pytest.mark.parametrize(("day", "edition"), [("2016-01-01", TW2014), ("2019-06-30", TW2014), ("2024-12-31", TW2014),
                                              ("2025-01-01", TW2023), ("2026-05-12", TW2023)])  # fmt: skip
def test_a_diagnosis_from_2016_on_is_icd10cm_with_its_tw_core_edition(tw: Mapper, day: str, edition: str) -> None:
    assert _systems(tw, _diag("M05.79", day)) == {ICD10: "M05.79", edition: "M05.79"}


def test_the_rows_own_word_wins_over_the_date(tw: Mapper) -> None:
    assert _systems(tw, _diag("714.0", "2017-02-01", diag_code_system="icd9cm")) == {ICD9: "714.0"}  # a late claim
    got = _systems(tw, _diag("M05.79", "2015-06-01", diag_code_system="icd10cm"))  # an early adopter
    assert got == {ICD10: "M05.79", TW2014: "M05.79"}
    assert _systems(tw, _diag("714.0", "", diag_code_system="icd9cm")) == {ICD9: "714.0"}


@pytest.mark.parametrize("row", [_diag("714.0", ""), _diag("714.0", "2014-03-02", diag_code_system="ICD-9"),
                                 _diag("M05.79", "2020-01-01", diag_code_system="snomed")])  # fmt: skip
def test_what_cannot_be_told_has_no_code(tw: Mapper, row: dict[str, str]) -> None:
    """No date and no system, or a system this mapping does not know: no code at all, which the coverage rule reads
    as unknown. Never ICD-10-CM by default."""
    assert _systems(tw, row) == {}


def test_a_mapping_without_the_parameter_is_unchanged(tmp_path: Path) -> None:
    """The shared base and the synthetic sites declare no ICD-9-CM years: every diagnosis is ICD-10-CM whatever its
    date, as before this card (no golden moves)."""
    plain = _mapper(tmp_path, None)
    assert _systems(plain, _diag("M05.79", "2014-03-02")) == {ICD10: "M05.79", TW2014: "M05.79"}
    assert _systems(plain, _diag("M05.79", "")) == {ICD10: "M05.79"}
    assert _systems(plain, _diag("M05.79", "2026-05-12")) == {ICD10: "M05.79", TW2023: "M05.79"}
    assert _systems(Mapper(Mapping.load(BASE), b"k" * 32, "s"), _diag("M05.79", "2014-03-02"))[ICD10] == "M05.79"
    assert Mapping.load(BASE).params == {}


def test_without_tw_core_the_rule_is_the_same(tmp_path: Path) -> None:
    other = _mapper(tmp_path, {"icd9cm_before": "2016-01-01"}, profiles="")
    assert _systems(other, _diag("714.0", "2014-03-02")) == {ICD9: "714.0"}
    assert _systems(other, _diag("M05.79", "2020-01-01")) == {ICD10: "M05.79"}


@pytest.mark.parametrize("name", ["cgrd_sql_site.yaml", "csv_site.yaml"])
def test_the_taiwanese_site_templates_ship_the_parameter(name: str) -> None:
    doc = yaml.safe_load((ROOT / "services/adapter/mapping/templates" / name).read_text(encoding="utf-8"))
    assert doc["params"] == {"icd9cm_before": "2016-01-01"}


def test_the_lake_keeps_the_icd9cm_system_and_never_reads_it_as_icd10cm(tw: Mapper) -> None:
    from lake.flatten import Flattener

    (res,) = tw.map_table("diagnosis", iter([_diag("714.0", "2014-03-02")]))
    code, system = Flattener.coding(res.get("code"))
    assert (code, system) == ("714.0", ICD9)


def test_any_holds_when_one_list_holds_and_an_unset_parameter_has_no_before(tmp_path: Path) -> None:
    plain, site = _mapper(tmp_path, None), _mapper(tmp_path, {"icd9cm_before": "2016-01-01"})
    one = {
        "any": [[{"column": "a", "equals": "1"}], [{"column": "b", "equals": "2"}, {"column": "c", "not_empty": True}]]
    }
    assert plain.cond(one, {"a": "1"}) and plain.cond(one, {"b": "2", "c": "x"})
    assert not plain.cond(one, {"b": "2", "c": ""}) and not plain.cond(one, {})
    before, since = (
        {"column": "d", "date_before": {"param": "icd9cm_before"}},
        {"column": "d", "date_from": {"param": "icd9cm_before"}},
    )
    assert (
        not plain.cond(before, {"d": "2014-01-01"})
        and plain.cond(since, {"d": "2014-01-01"})
        and plain.cond(since, {"d": ""})
    )
    assert site.cond(before, {"d": "2014-01-01"}) and not site.cond(since, {"d": "2014-01-01"})
    assert not site.cond(before, {"d": ""}) and not site.cond(since, {"d": ""})
