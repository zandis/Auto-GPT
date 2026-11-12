"""NEW-STD-1, second half, part 2 (D-593): at night an ICD-9-CM diagnosis gains its ICD-10-CM code only where the
reference-data map says the two are the same. The map rows here are the shapes of the CMS file (D-592)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from adapter.mapping.engine import Mapper, Mapping
from lake.flatten import Flattener

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
I9, I10 = "http://hl7.org/fhir/sid/icd-9-cm", "http://hl7.org/fhir/sid/icd-10-cm"

GEM = {
    "042": [("B20", "equivalent")],
    "585.3": [("N18.3", "equivalent")],
    "714.0": [("M06.9", "inexact")],
    "V58.69": [("Z79.84", "relatedto"), ("Z79.891", "relatedto"), ("Z79.899", "relatedto")],
    "305.93": [("F18.11", "relatedto"), ("F19.11", "relatedto")],
    "001.0": [("A00.0", "equal")],
    # entries that exist in the real file and must never be reached by a value that is not a numeric ICD-9-CM code
    "E030": [("Y93.9", "equivalent")],
    "E03.0": [("Y93.9", "equivalent")],
    "V12.5": [("Z86.7", "equivalent")],
    "123.45": [("X00", "equivalent")],
}


def _map(calls: list[tuple[str, str]] | None = None) -> Any:
    def ask(system: str, code: str) -> list[dict[str, Any]]:
        if calls is not None:
            calls.append((system, code))
        if system != I9:
            return []
        return [{"source_system": I9, "source_code": code, "target_system": I10, "target_code": t, "relation": rel,
                 "extra": {}} for t, rel in GEM.get(code, [])]  # fmt: skip

    return ask


def _mapper(tmp_path: Path, concept_map: Any, params: dict[str, str] | None = None) -> Mapper:
    doc: dict[str, Any] = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    doc["params"] = {"icd9cm_before": "2016-01-01"} if params is None else params
    for name, spec in (doc.get("lookups") or {}).items():
        spec["file"] = str(BASE.parent / spec["file"])
        doc["lookups"][name] = spec
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return Mapper(Mapping.load(path), b"k" * 32, "s", concept_map=concept_map)


def _diag(code: str, day: str = "2014-03-02", **more: str) -> dict[str, str]:
    return {"diag_no": "D1", "enc_no": "E1", "mrn": "P1", "icd10": code, "diag_date": day, "recorded_date": day,
            "status": "A", **more}  # fmt: skip


def _res(mapper: Mapper, row: dict[str, str]) -> dict[str, Any]:
    (res,) = mapper.map_table("diagnosis", iter([row]))
    return dict(res)


def _codings(mapper: Mapper, row: dict[str, str]) -> list[tuple[str, str]]:
    return [(c["system"], c["code"]) for c in (_res(mapper, row).get("code") or {}).get("coding") or []]


@pytest.mark.parametrize(("code", "want"), [("042", "B20"), ("585.3", "N18.3"), ("5853", "N18.3"), (" 585.3 ", "N18.3"),
                                            ("001.0", "A00.0")])  # fmt: skip
def test_an_exact_entry_gives_the_icd10cm_code_first_and_keeps_the_icd9cm_one(
    tmp_path: Path, code: str, want: str
) -> None:
    mapper = _mapper(tmp_path, _map())
    res = _res(mapper, _diag(code))
    codings = res["code"]["coding"]
    assert [(c["system"], c["code"]) for c in codings] == [(I10, want), (I9, code.strip())]
    assert codings[0]["userSelected"] is False and "userSelected" not in codings[1]  # not the hospital's own code
    assert not mapper.unmapped
    row = Flattener().condition(res)
    assert (row["code"], row["system"]) == (want, I10)  # the lake reads the diagnosis as the ICD-10-CM code


@pytest.mark.parametrize("code", ["714.0", "V58.69", "305.93", "999.99", "7140"])
def test_everything_else_stays_icd9cm_and_is_counted(tmp_path: Path, code: str) -> None:
    """An approximate entry, alternatives, a combination, no entry: never "the" code (D-592)."""
    mapper = _mapper(tmp_path, _map())
    assert _codings(mapper, _diag(code)) == [(I9, code)]
    assert dict(mapper.unmapped) == {("diagnosis", "map:icd9cm->icd10cm", code): 1}  # counted as fed


def test_a_mapper_without_the_reference_data_maps_nothing_and_counts_nothing(tmp_path: Path) -> None:
    mapper = _mapper(tmp_path, None)
    assert _codings(mapper, _diag("042")) == [(I9, "042")] and not mapper.unmapped


def test_an_icd10cm_diagnosis_is_never_looked_up(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    mapper = _mapper(tmp_path, _map(calls))
    got = _codings(mapper, _diag("M05.79", "2019-03-02"))
    assert (I10, "M05.79") in got and (I9, "M05.79") not in got and calls == []
    plain = _mapper(tmp_path, _map(calls), params={})  # a mapping with no ICD-9-CM years
    assert (I10, "042") in _codings(plain, _diag("042")) and calls == []


def test_a_code_is_asked_once_however_many_rows_have_it(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    mapper = _mapper(tmp_path, _map(calls))
    rows = [_diag("585.3", diag_no=f"D{i}") for i in range(5)] + [_diag("714.0", diag_no="D9")]
    assert len(list(mapper.map_table("diagnosis", iter(rows)))) == 6
    assert calls == [(I9, "585.3"), (I9, "714.0")]


def test_a_map_that_fails_or_answers_oddly_never_gives_a_code(tmp_path: Path) -> None:
    def other_system(system: str, code: str) -> list[dict[str, Any]]:
        return [{"target_system": "http://snomed.info/sct", "target_code": "1", "relation": "equivalent"}]

    def two_exact(system: str, code: str) -> list[dict[str, Any]]:
        return [{"target_system": I10, "target_code": t, "relation": "equivalent"} for t in ("B20", "B21")]

    def exact_and_another(system: str, code: str) -> list[dict[str, Any]]:
        return [{"target_system": I10, "target_code": "B20", "relation": "equivalent"},
                {"target_system": I10, "target_code": "B21", "relation": "relatedto"}]  # fmt: skip

    def no_code(system: str, code: str) -> list[dict[str, Any]]:
        return [{"target_system": I10, "target_code": "", "relation": "equivalent"}]

    for ask in (other_system, two_exact, exact_and_another, no_code):
        assert _codings(_mapper(tmp_path, ask), _diag("042")) == [(I9, "042")], ask.__name__


def test_the_night_and_the_backfill_give_the_mapper_the_boxes_reference_data() -> None:
    for name in ("pipeline.py", "backfill.py"):
        text = (ROOT / "services/adapter" / name).read_text(encoding="utf-8")
        assert "concept_map=" in text and "map_targets_or_none" in text, name


@pytest.mark.parametrize("code", [
    "E03.0", "E030", "e03.0",          # an ICD-10-CM code written in the ICD-9-CM years (a site that back-coded)
    "V12.5", "V125", "E800.0",         # the letter chapters share their shapes with ICD-10: never looked up
    "0.42", "71.40", "5853.", "585.300", "58", "123456", "585,3", "7140;4010",  # not the shape of a numeric code
])  # fmt: skip
def test_only_a_numeric_icd9cm_code_is_ever_looked_up(tmp_path: Path, code: str) -> None:
    """The review's finding: ``E03.0`` (ICD-10-CM, hypothyroidism) was re-dotted into the ICD-9-CM E-code ``E030``,
    which the real file maps exactly to ``Y93.9``. A code that starts with a letter can be either edition."""
    calls: list[tuple[str, str]] = []
    mapper = _mapper(tmp_path, _map(calls))
    assert _codings(mapper, _diag(code)) == [(I9, code)] and calls == []
    assert dict(mapper.unmapped) == {("diagnosis", "map:icd9cm->icd10cm", code.upper()): 1}


def test_a_value_shaped_like_a_chart_number_reaches_the_count_as_fed_so_the_filter_sees_it(tmp_path: Path) -> None:
    mapper = _mapper(tmp_path, _map())
    list(mapper.map_table("diagnosis", iter([_diag("12345678"), _diag("54321", diag_no="D2")])))
    by_code = mapper.unmapped_by_code(r"\d{8}|\d{5}")["diagnosis"]["map:icd9cm->icd10cm"]
    assert by_code == {"(not a code)": 2}


def test_a_map_that_could_not_be_asked_is_not_no_entry(tmp_path: Path) -> None:
    """The reference data down for one question: nothing is mapped for that row, it is counted apart, and the
    next row of the same code asks again."""
    state = {"down": True}
    calls: list[str] = []

    def ask(system: str, code: str) -> list[dict[str, Any]] | None:
        calls.append(code)
        if state["down"]:
            return None
        return [{"target_system": I10, "target_code": "B20", "relation": "equivalent"}]

    mapper = _mapper(tmp_path, ask)
    assert _codings(mapper, _diag("042")) == [(I9, "042")]
    assert dict(mapper.unmapped) == {("diagnosis", "map:icd9cm->icd10cm:unavailable", "042"): 1}
    state["down"] = False
    assert _codings(mapper, _diag("042", diag_no="D2")) == [(I10, "B20"), (I9, "042")]
    assert calls == ["042", "042"]


def test_the_boxes_reference_data_says_when_it_could_not_be_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    from tb_common import refdata

    monkeypatch.delenv("TB_DB_URL", raising=False)
    assert refdata.map_targets_or_none(I9, "042") == []  # no database configured: there is nothing to ask
    assert refdata.map_targets_or_none(I9, "042", "postgresql://nobody@127.0.0.1:1/none") is None  # configured, down
