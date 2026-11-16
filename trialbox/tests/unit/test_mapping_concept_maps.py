"""`Mapping.concept_maps()`: the reference maps a mapping's `mapped_coding` elements ask for, as (from system, to
system) addresses, so that a load can check they are loaded before it starts (lane B's check; D-593)."""

from __future__ import annotations

from pathlib import Path

from adapter.mapping.engine import Mapping

ROOT = Path(__file__).resolve().parents[2] / "services/adapter/mapping"
BASE = ROOT / "tw_core/demo_his.yaml"
I9, I10CM = "http://hl7.org/fhir/sid/icd-9-cm", "http://hl7.org/fhir/sid/icd-10-cm"


def _site(tmp_path: Path, body: str) -> Mapping:
    p = tmp_path / "site.yaml"
    p.write_text(f"version: 1\nname: site_his\nextends: {BASE}\ntz: Asia/Taipei\n{body}", encoding="utf-8")
    return Mapping.load(p)


def test_the_base_mapping_asks_for_the_icd9_to_icd10cm_map_once() -> None:
    assert Mapping.load(BASE).concept_maps() == [(I9, I10CM), ("urn:tw:nhi:drug", "http://www.whocc.no/atc")]


def test_a_site_that_exports_no_diagnosis_asks_for_none(tmp_path: Path) -> None:
    m = _site(tmp_path, "tables:\n  patient: {source: patient, key: mrn}\n")
    assert m.concept_maps() == []


def test_an_overlay_s_map_is_listed_with_the_base_s_without_duplicates(tmp_path: Path) -> None:
    m = _site(
        tmp_path,
        """tables:
  diagnosis: {source: diagnosis, key: diag_no}
systems:
  house_dx: "http://hospital.example/dx"
overlay:
  - type: Condition
    table: diagnosis
    elements:
      code.coding[5]: {builder: mapped_coding, column: icd10, from: house_dx, to: icd10cm}
      code.coding[6]: {builder: mapped_coding, column: icd10, from: icd9cm, to: icd10cm}
""",
    )
    assert m.concept_maps() == [(I9, I10CM), ("http://hospital.example/dx", I10CM)]


def test_the_japan_mapping_answers_too() -> None:
    assert isinstance(Mapping.load(ROOT / "jp_core/ssmix2_site.yaml").concept_maps(), list)
