"""NEW-STD-5 (D-689): at night a Taiwanese medication with an NHI drug code and no ATC gains the ATC code the NHIA
list gives (the reference data's `nhi_drug_atc` map, D-170), tagged as mapped.

Until this card only the site set-up page read that map. A medication row with no ATC matched no drug value set:
a drug exclusion could never fire on it. The codes below are synthetic NHI-shaped codes; the ATC codes are public
WHO codes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from adapter.mapping.engine import Mapper, Mapping, MappingError
from lake.flatten import Flattener

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
NHI_LIST, ATC = "urn:tw:nhi:drug", "http://www.whocc.no/atc"  # the pack's systems (tb_common.refdata_tw)

MAP = {
    "AC00011100": [("C10AA05", "wider")],  # one product, its ATC class
    "AC00022200": [("L04AX03", "wider")],
    "AC00033300": [("L04AX03", "wider"), ("L01BA01", "wider")],  # two answers: nothing is chosen
    "AC00044400": [("M04AA01", "equivalent")],  # a relation this map never gives: not taken
    "AC00055500": [("C10AA", "wider")],  # a level-4 class: kept, it is what the list says
}


def _map(calls: list[tuple[str, str]] | None = None) -> Any:
    def ask(system: str, code: str) -> list[dict[str, Any]]:
        if calls is not None:
            calls.append((system, code))
        if system != NHI_LIST:
            return []
        return [{"source_system": NHI_LIST, "source_code": code, "target_system": ATC, "target_code": t,
                 "relation": rel, "extra": {}} for t, rel in MAP.get(code, [])]  # fmt: skip

    return ask


def _mapper(tmp_path: Path, concept_map: Any) -> Mapper:
    doc: dict[str, Any] = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    for name, spec in (doc.get("lookups") or {}).items():
        spec["file"] = str(BASE.parent / spec["file"])
        doc["lookups"][name] = spec
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return Mapper(Mapping.load(path), b"k" * 32, "s", concept_map=concept_map)


def _rx(nhi: str, atc: str = "", **more: str) -> dict[str, str]:
    return {"rx_no": "M1", "mrn": "P1", "nhi_drug_code": nhi, "atc": atc, "drug_name": "x", "order_date": "2026-08-01",
            "start_date": "2026-08-01", "end_date": "2026-08-28", "daily_dose": "20", "dose_unit": "mg",
            "status": "active", "dept_code": "RHEU", **more}  # fmt: skip


def _res(mapper: Mapper, row: dict[str, str]) -> dict[str, Any]:
    (res,) = mapper.map_table("medication", iter([row]))
    return dict(res)


def _atc_codings(res: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in res["medicationCodeableConcept"]["coding"] if c["system"] == ATC]


@pytest.mark.parametrize(("nhi", "want"), [("AC00011100", "C10AA05"), ("AC00022200", "L04AX03"),
                                           (" ac00022200 ", "L04AX03"), ("AC00055500", "C10AA")])  # fmt: skip
def test_a_medication_without_atc_gains_the_lists_atc_tagged_as_mapped(tmp_path: Path, nhi: str, want: str) -> None:
    mapper = _mapper(tmp_path, _map())
    res = _res(mapper, _rx(nhi))
    (atc,) = _atc_codings(res)
    assert atc["code"] == want and atc["userSelected"] is False  # not the hospital's own code
    nhi_coding = res["medicationCodeableConcept"]["coding"][0]
    assert nhi_coding["code"] == nhi.strip() and "userSelected" not in nhi_coding  # the hospital's code is kept
    assert Flattener("Asia/Taipei").medication(res)["atc"] == want  # the lake reads it as the drug's ATC
    assert not mapper.unmapped
    assert mapper.mapped_summary() == {"medication": {"map:nhi_drug_list->atc": 1}}


def test_the_hospitals_own_atc_wins_and_the_map_is_not_asked(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    mapper = _mapper(tmp_path, _map(calls))
    res = _res(mapper, _rx("AC00011100", atc="C10AA07"))
    assert [c["code"] for c in _atc_codings(res)] == ["C10AA07"] and "userSelected" not in _atc_codings(res)[0]
    assert calls == [] and mapper.mapped_summary() == {}


@pytest.mark.parametrize("nhi", ["AC00033300", "AC00044400", "AC09999900"])
def test_two_answers_another_relation_or_no_entry_give_no_atc_and_are_counted(tmp_path: Path, nhi: str) -> None:
    mapper = _mapper(tmp_path, _map())
    res = _res(mapper, _rx(nhi))
    assert _atc_codings(res) == [] and Flattener("Asia/Taipei").medication(res)["atc"] is None
    assert mapper.unmapped_summary() == {"medication": {"map:nhi_drug_list->atc": {"rows": 1, "codes": 1}}}


def test_without_the_reference_data_nothing_is_mapped_or_counted(tmp_path: Path) -> None:
    mapper = _mapper(tmp_path, None)
    assert _atc_codings(_res(mapper, _rx("AC00011100"))) == []
    assert not mapper.unmapped and mapper.mapped_summary() == {}


def test_a_map_that_could_not_be_asked_is_counted_apart(tmp_path: Path) -> None:
    mapper = _mapper(tmp_path, lambda system, code: None)
    assert _atc_codings(_res(mapper, _rx("AC00011100"))) == []
    assert mapper.unmapped_summary() == {"medication": {"map:nhi_drug_list->atc:unavailable": {"rows": 1, "codes": 1}}}


def test_the_diagnosis_map_still_takes_only_an_equivalent_entry(tmp_path: Path) -> None:
    """The new relation is accepted only where an element says so: a `wider` ICD-9-CM entry gives no ICD-10-CM code."""

    def ask(system: str, code: str) -> list[dict[str, Any]]:
        return [{"target_system": "http://hl7.org/fhir/sid/icd-10-cm", "target_code": "B20", "relation": "wider"}]

    doc: dict[str, Any] = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    doc["params"] = {"icd9cm_before": "2016-01-01"}
    for name, spec in (doc.get("lookups") or {}).items():
        spec["file"] = str(BASE.parent / spec["file"])
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    mapper = Mapper(Mapping.load(path), b"k" * 32, "s", concept_map=ask)
    (res,) = mapper.map_table("diagnosis", iter([{"diag_no": "D1", "enc_no": "E1", "mrn": "P1", "icd10": "042",
                                                   "diag_date": "2014-03-02", "recorded_date": "2014-03-02",
                                                   "status": "A"}]))  # fmt: skip
    assert [c["code"] for c in res["code"]["coding"]] == ["042"]


@pytest.mark.parametrize("accept", [["inexact"], ["relatedto"], "wider", []])
def test_a_mapping_may_accept_only_relations_that_say_the_code_is_the_class(tmp_path: Path, accept: Any) -> None:
    doc: dict[str, Any] = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    for name, spec in (doc.get("lookups") or {}).items():
        spec["file"] = str(BASE.parent / spec["file"])
    med = next(r for r in doc["resources"] if r["table"] == "medication")
    med["elements"]["medicationCodeableConcept.coding[2]"]["accept"] = accept
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    with pytest.raises(MappingError, match="accept"):
        Mapping.load(path)


def test_the_base_mapping_names_the_nhi_list_map() -> None:
    assert (NHI_LIST, ATC) in Mapping.load(BASE).concept_maps()


# ------------------------------------------------------------------------------------------------ the night
def test_the_night_maps_a_medication_without_atc_and_its_report_counts_by_column_by_map_and_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import csv
    import json

    from adapter.ndjson import read_type, snapshot_dir
    from adapter.pipeline import COMPLETENESS
    from tb_common import refdata

    from tests.unit.test_full_reread_after_refdata_outage import _night, _site

    cfg = _site(tmp_path)
    feed = tmp_path / "feed"
    feed.mkdir()
    rows = [_rx("AC00011100") | {"rx_no": "M1"}, _rx("AC00022200", atc="L04AX03") | {"rx_no": "M2"},
            _rx("AC09999900") | {"rx_no": "M3"}]  # fmt: skip
    with (feed / "medication.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[*rows[0], "updated_at"])
        w.writeheader()
        w.writerows([r | {"updated_at": "2026-09-30"} for r in rows])
    ask = _map()
    monkeypatch.setattr(refdata, "map_targets_or_none", lambda system, code, url=None: ask(system, code))
    monkeypatch.setattr(refdata, "has_map_or_none", lambda src, tgt, url=None: True)  # the pack's map is loaded
    rep = _night(cfg, str(feed), "2026-10-01")
    assert rep.passed
    got = {r["id"]: [(c["code"], c.get("userSelected")) for c in r["medicationCodeableConcept"]["coding"]
                     if c["system"] == ATC] for r in read_type(snapshot_dir(cfg.lake_dir, "2026-10-01"),
                                                                "MedicationRequest")}  # fmt: skip
    assert sorted(got.values()) == [[], [("C10AA05", False)], [("L04AX03", None)]]
    body = json.loads((snapshot_dir(cfg.lake_dir, "2026-10-01") / COMPLETENESS).read_text(encoding="utf-8"))
    med = body["tables"]["medication"]
    assert med["mapped"] == {"map:nhi_drug_list->atc": 1}  # by the map
    assert med["unmapped"] == {"map:nhi_drug_list->atc": {"rows": 1, "codes": 1}}  # unresolved
    # by the hospital's own column: the rest of the rows read (3 read, 1 mapped, 1 unresolved)


def test_a_night_before_the_nhi_list_is_loaded_counts_its_rows_as_not_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-665 for this map: with the pack's NHI list not loaded, a medication without ATC is "not asked" (the next
    night maps it), never "no entry"; a first load would be held (D-660). A site whose every row has an ATC column
    is never asked to load it."""
    import csv
    import json

    from adapter.ndjson import snapshot_dir
    from adapter.pipeline import COMPLETENESS
    from tb_common import refdata

    from tests.unit.test_full_reread_after_refdata_outage import _night, _site

    cfg = _site(tmp_path)
    feed = tmp_path / "feed"
    feed.mkdir()
    with (feed / "medication.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[*_rx("x"), "updated_at"])
        w.writeheader()
        w.writerow(_rx("AC00011100") | {"updated_at": "2026-09-30"})
    monkeypatch.setattr(refdata, "map_targets_or_none", lambda system, code, url=None: [])
    monkeypatch.setattr(refdata, "has_map_or_none", lambda src, tgt, url=None: False)
    assert _night(cfg, str(feed), "2026-10-01").passed  # a night is not held (D-530)
    med = json.loads((snapshot_dir(cfg.lake_dir, "2026-10-01") / COMPLETENESS).read_text(encoding="utf-8"))
    assert med["tables"]["medication"]["unmapped"] == {"map:nhi_drug_list->atc:unavailable": {"rows": 1, "codes": 1}}
    assert "mapped" not in med["tables"]["medication"]
