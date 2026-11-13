"""A site mapping's `systems.atc` is the ATC system (lane B's NEW-B-16, D-536: the lake reads ATC only under its one
name). A mapping that gives ATC an address of its own is refused when it is loaded, with the reason: its codes would
leave the lake's ATC column and a drug-class exclusion would stop firing for that site, silently."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from adapter.mapping.engine import Mapping, MappingError
from lake.flatten import is_atc_system

BASE = Path(__file__).resolve().parents[2] / "services/adapter/mapping/tw_core/demo_his.yaml"


def _load(tmp_path: Path, systems: str) -> Mapping:
    p = tmp_path / "site.yaml"
    p.write_text(f"version: 1\nname: site_his\nextends: {BASE}\ntz: Asia/Taipei\n{systems}", encoding="utf-8")
    return Mapping.load(p)


@pytest.mark.parametrize("address", [
    "http://hospital.example/fhir/CodeSystem/atc", "https://his.example/atc-codes", "urn:oid:1.2.3.4", "atc",
    "http://www.whocc.no/atc/2024", "",
    # the review: another spelling of the ATC system is read by the lake, not by the readers that compare the
    # address as written (a value set of a ruleset, the JP Core check): one spelling only
    "https://www.whocc.no/atc/", "HTTP://WWW.WHOCC.NO/ATC", "urn:oid:2.16.840.1.113883.6.73", " http://www.whocc.no/atc ",
])  # fmt: skip
def test_an_atc_address_of_the_site_s_own_is_refused_with_the_reason(tmp_path: Path, address: str) -> None:
    with pytest.raises(MappingError) as e:
        _load(tmp_path, f'systems:\n  atc: "{address}"\n')
    said = str(e.value)
    assert "systems.atc" in said and "http://www.whocc.no/atc" in said and "exclusion" in said
    assert "site.yaml" in said


def test_the_atc_system_as_the_box_writes_it_loads(tmp_path: Path) -> None:
    m = _load(tmp_path, 'systems:\n  atc: "http://www.whocc.no/atc"\n')
    assert m.systems["atc"] == "http://www.whocc.no/atc" and is_atc_system(m.systems["atc"])


OVERLAY = """tables:
  medication: {{source: medication, key: rx_no}}
overlay:
  - type: MedicationRequest
    table: medication
    elements:
      medicationCodeableConcept.coding[1]: {{builder: coding, column: atc, system: {key}}}
"""


@pytest.mark.parametrize(("systems", "key"), [
    ('systems:\n  who_atc: "http://hospital.example/atc"\n', "who_atc"),   # a key of the site's own
    ("", "nhi_drug"),                                                       # a key the base has for another code
])  # fmt: skip
def test_the_atc_column_written_under_another_system_is_refused(tmp_path: Path, systems: str, key: str) -> None:
    """The review: the address of one key was checked, not what the ATC column is written under."""
    with pytest.raises(MappingError) as e:
        _load(tmp_path, systems + OVERLAY.format(key=key))
    assert "column atc" in str(e.value) and "exclusion" in str(e.value)


def test_a_site_that_overrides_another_system_keeps_the_base_s_atc(tmp_path: Path) -> None:
    m = _load(tmp_path, 'systems:\n  hosp_drug: "http://hospital.example/drug"\n')
    assert m.systems["atc"] == "http://www.whocc.no/atc" and m.systems["hosp_drug"] == "http://hospital.example/drug"


def test_every_shipped_mapping_loads_and_no_template_gives_atc_an_address() -> None:
    root = BASE.parents[1]
    for p in (BASE, root / "jp_core/ssmix2_site.yaml"):
        assert is_atc_system(Mapping.load(p).systems["atc"]), p
    for p in sorted((root / "templates").glob("*.yaml")):  # a template is copied to a site, then loaded there
        assert "atc" not in (yaml.safe_load(p.read_text(encoding="utf-8")).get("systems") or {}), p
