"""Compact metadata lookups for the Taiwan SQL-view door; synthetic rows only."""

from datetime import date
from pathlib import Path
from typing import Self

import pytest
import yaml
from adapter.mapping.engine import Mapper, Mapping

pytestmark = pytest.mark.nodb

TEMPLATE = Path(__file__).resolve().parents[2] / "services/adapter/mapping/templates/cgrd_sql_site.yaml"


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    class FixedDate(date):
        @classmethod
        def today(cls) -> Self:
            return cls(2026, 10, 5)

    monkeypatch.setattr("adapter.mapping.engine.date", FixedDate)


def mapper(tmp_path: Path) -> Mapper:
    return Mapper(Mapping.load(TEMPLATE), bytes(range(32)), "T", ingest_time="2026-10-05T00:00:00Z")


def test_diagnosis_standard_lookup(tmp_path: Path) -> None:
    m = mapper(tmp_path)
    row = {
        "diag_no": "D1",
        "mrn": "P1",
        "icd10": "I10",
        "diag_code_system": "icd10cm",
        "diag_date": "2026-10-04",
        "recorded_date": "2026-10-04",
    }
    (res,) = m.map_table("diagnosis", iter([row]))
    assert any(c["code"] == "59621000" for c in res["code"]["coding"])


@pytest.mark.parametrize(
    "code,edition,day",
    [
        ("9991", "ICD9CM", "2014-10-04"),
        ("999.1", "ICD9CM", "2014-10-04"),
        ("Z991", "ICD10CM", "2026-10-04"),
        ("Z99.1", "ICD10CM", "2026-10-04"),
    ],
)
def test_dotless_edition_lookup(tmp_path: Path, code: str, edition: str, day: str) -> None:
    m = mapper(tmp_path)
    m.m.lookups["diagnosis_standard"].rows = {
        "synthetic": {
            "source_vocabulary": edition,
            "source_code": code.replace(".", ""),
            "target_vocabulary": "SNOMED",
            "target_code": "SYNTHETIC-CONDITION",
        }
    }
    row = {
        "diag_no": "D1",
        "mrn": "P1",
        "icd10": code,
        "diag_code_system": edition.lower(),
        "diag_date": day,
        "recorded_date": day,
    }
    (res,) = m.map_table("diagnosis", iter([row]))
    assert any(c["code"] == "SYNTHETIC-CONDITION" for c in res["code"]["coding"])


def test_unmapped_diagnosis_is_kept(tmp_path: Path) -> None:
    m = mapper(tmp_path)
    (res,) = m.map_table(
        "diagnosis",
        iter(
            [
                {
                    "diag_no": "D1",
                    "mrn": "P1",
                    "icd10": "ZZ-NOT-MAPPED",
                    "diag_date": "2026-10-04",
                    "recorded_date": "2026-10-04",
                }
            ]
        ),
    )
    assert any(c["code"] == "ZZ-NOT-MAPPED" for c in res["code"]["coding"])
    assert not any(c["system"] == m.m.systems["snomed"] for c in res["code"]["coding"])
    assert "crosswalk:diagnosis_standard" in m.unmapped_summary()["diagnosis"]


@pytest.mark.parametrize("unit,want", [("MG/DL", 1.2), ("unconvertible", None)])
def test_lab_lookup_and_unknown_unit(tmp_path: Path, unit: str, want: float | None) -> None:
    m = mapper(tmp_path)
    (res,) = m.map_table(
        "lab",
        iter(
            [
                {
                    "lab_no": "L1",
                    "mrn": "P1",
                    "local_code": "CREATININE",
                    "unit": unit,
                    "result_value": "1.2",
                    "sample_datetime": "2026-10-04 00:00:00",
                }
            ]
        ),
    )
    assert res["code"]["coding"][0]["code"] == "2160-0"
    if want is None:
        assert "valueQuantity" not in res
        assert res["dataAbsentReason"]["text"] == "unit_mismatch"
    else:
        assert res["valueQuantity"]["value"] == want
        assert res["valueQuantity"]["code"] == "mg/dL"


def test_unmapped_lab_is_reported(tmp_path: Path) -> None:
    m = mapper(tmp_path)
    assert list(m.map_table("lab", iter([{"local_code": "ZZ-NOT-MAPPED"}]))) == []
    assert m.unmapped_summary()["lab"]


def test_drug_reference_columns_and_ambiguity() -> None:
    from adapter.mapping.tw_reference import drug_pairs

    def row(code: str, atc: str) -> list[str]:
        return ["", code, "discarded", *([""] * 13), atc]

    assert drug_pairs([row("ZZ00000001", "l04ax03")]) == {"ZZ00000001": "L04AX03"}
    assert drug_pairs([row("ZZ00000001", "L04AX03"), row("ZZ00000001", "L01BA01")]) == {}
    assert drug_pairs([row("ZZ00000001", "L04"), row("ZZ00000002", "")]) == {}


@pytest.mark.parametrize(
    "code,targets,want",
    [
        ("ZZ00000001", ["L04AX03"], "L04AX03"),
        ("ZZ00000001", ["L04AX03", "L01BA01"], None),
        ("ZZ-UNKNOWN", ["L04AX03"], None),
    ],
)
def test_drug_lookup_never_guesses(tmp_path: Path, code: str, targets: list[str], want: str | None) -> None:
    m = mapper(tmp_path)
    lk = m.m.lookups["drug_standard"]
    lk.rows = {
        str(i): {"source_code": "ZZ00000001", "target_code": target, "target_vocabulary": "ATC"}
        for i, target in enumerate(targets)
    }
    (res,) = m.map_table(
        "medication",
        iter(
            [
                {
                    "rx_no": "R1",
                    "mrn": "P1",
                    "nhi_drug_code": code,
                    "atc": "",
                    "daily_dose": "1",
                    "dose_unit": "mg",
                    "order_date": "2026-10-04",
                    "start_date": "2026-10-04",
                    "end_date": "2026-11-04",
                }
            ]
        ),
    )
    got = [c["code"] for c in res["medicationCodeableConcept"]["coding"] if c["system"] == m.m.systems["atc"]]
    assert got == ([] if want is None else [want])


def test_lab_without_evidenced_unit_stays_unknown(tmp_path: Path) -> None:
    m = mapper(tmp_path)
    (res,) = m.map_table(
        "lab",
        iter(
            [
                {
                    "lab_no": "L1",
                    "mrn": "P1",
                    "local_code": "PDW",
                    "unit": "",
                    "result_value": "12",
                    "sample_datetime": "2026-10-04 00:00:00",
                }
            ]
        ),
    )
    assert "valueQuantity" not in res
    assert res["dataAbsentReason"]["text"] == "unit_mismatch"


def test_standard_drug_lookup(tmp_path: Path) -> None:
    m = mapper(tmp_path)
    m.m.lookups["drug_standard"].rows = {
        "synthetic": {
            "source_code": "ZZ00000001",
            "target_vocabulary": "RxNorm",
            "target_code": "SYNTHETIC-INGREDIENT",
        }
    }
    (res,) = m.map_table(
        "medication",
        iter(
            [
                {
                    "rx_no": "R1",
                    "mrn": "P1",
                    "nhi_drug_code": "ZZ00000001",
                    "atc": "",
                    "daily_dose": "1",
                    "dose_unit": "mg",
                    "order_date": "2026-10-04",
                }
            ]
        ),
    )
    assert any(c["code"] == "SYNTHETIC-INGREDIENT" for c in res["medicationCodeableConcept"]["coding"])


def test_table_metadata_preserves_identifier_guards() -> None:
    doc = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    meta = doc["source_metadata"]
    assert "CHTNO" in meta["guarded_columns"]
    assert meta["tables"]["RCGRDOPDAF"]["domain"] == "condition"
    assert meta["tables"]["RCGRDLABRSLT"]["priority"] == "P0"
    assert "OPDNO" in meta["tables"]["RCGRDOPDAF"]["guarded_columns"]
