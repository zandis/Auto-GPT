"""F10 + F15 (D-809): a lab look-up keyed by panel and item, and the unit spellings a lab export writes.

Some labs give an item code that means a different test under another panel: the item code alone is not a key. A
mapping now builds one key column from two (``tables.<t>.join: {lab_key: [panel_code, local_code]}``) and a look-up
loads its file keyed by the same two (``lookups.<n>.key: [panel_code, local_code]``). A row that lacks either part
has no key: no look-up row, counted as before, never matched by one part.

Units: ``{cells}/uL`` is ``/uL`` (a UCUM annotation says what is counted, not a unit); ``1000/uL`` is ``10*3/uL``;
``mg/L FEU`` (D-dimer in fibrinogen-equivalent units) is its own unit and never plain ``mg/L``, which may be D-dimer
units, about half; ``倍數`` (a titer's "times") is a titer and agrees only with itself. Synthetic rows only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from adapter.mapping.engine import Mapper, Mapping, MappingError
from tb_common import labvalue

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
PROFILE = "https://twcore.mohw.gov.tw/ig/twcore/StructureDefinition/Observation-laboratoryResult-twcore"
LOOKUP = (
    "panel_code,local_code,system,code,display,ucum,factor,category,value_type,answers,profile,verified,source_unit\n"
    f"CBC,072,loinc,26499-4,Neutrophils [#/volume] in Blood,10*3/uL,1,laboratory,quantity,,{PROFILE},yes,\n"
    f"UR,072,loinc,30405-5,Leukocytes [#/volume] in Urine,/uL,1,laboratory,quantity,,{PROFILE},yes,\n"
    f"COAG,031,loinc,48065-7,Fibrin D-dimer FEU [Mass/volume] in Platelet poor plasma,mg/L{{FEU}},1,laboratory,"
    f"quantity,,{PROFILE},yes,\n"
)


def _mapping(tmp_path: Path, lookup_key: Any = None, join: Any = None) -> Mapping:
    (tmp_path / "lab_pairs.csv").write_text(LOOKUP, encoding="utf-8")
    doc: dict[str, Any] = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    doc["lookups"] = {"lab": {"file": str(tmp_path / "lab_pairs.csv"),
                              "key": lookup_key or ["panel_code", "local_code"]}}  # fmt: skip
    doc["tables"]["lab"]["join"] = join or {"lab_key": ["panel_code", "local_code"]}
    lab = next(r for r in doc["resources"] if r["table"] == "lab")
    text = yaml.safe_dump(lab, allow_unicode=True).replace("key: local_code", "key: lab_key")
    doc["resources"] = [yaml.safe_load(text) if r is lab else r for r in doc["resources"]]
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return Mapping.load(path)


def _lab(panel: str, item: str, value: str, unit: str) -> dict[str, str]:
    return {"lab_no": f"L-{panel}-{item}", "mrn": "P1", "panel_code": panel, "local_code": item, "item_name": "x",
            "result_value": value, "unit": unit, "sample_datetime": "2026-01-13 08:00:00", "result_status": "final"}  # fmt: skip


def _map(m: Mapping, row: dict[str, str]) -> tuple[Mapper, list[dict[str, Any]]]:
    mp = Mapper(m, b"k" * 32, "s")
    return mp, list(mp.map_table("lab", iter([m.normalize("lab", row)])))


def test_one_item_code_under_two_panels_is_two_tests(tmp_path: Path) -> None:
    m = _mapping(tmp_path)
    _, (blood,) = _map(m, _lab("CBC", "072", "4.2", "10^3/ul"))
    _, (urine,) = _map(m, _lab("UR", "072", "12", "cells/ul"))
    assert blood["code"]["coding"][0]["code"] == "26499-4" and blood["valueQuantity"]["value"] == 4.2
    assert urine["code"]["coding"][0]["code"] == "30405-5" and urine["valueQuantity"]["value"] == 12


@pytest.mark.parametrize(("panel", "item"), [("", "072"), ("CBC", ""), ("CHEM", "072")])
def test_a_row_without_both_parts_or_an_unknown_pair_has_no_lookup_row_and_is_counted(
    tmp_path: Path, panel: str, item: str
) -> None:
    mp, got = _map(_mapping(tmp_path), _lab(panel, item, "4.2", "10^3/ul"))
    assert got == [] and sum(n for (t, *_), n in mp.unmapped.items() if t == "lab") == 1


@pytest.mark.parametrize(("lookup_key", "join"), [
    (["panel_code"], None), (["panel_code", ""], None), (None, {"lab_key": ["panel_code"]}),
    (None, {"lab_key": "panel_code"}), (["panel_code", "nope"], None),
])  # fmt: skip
def test_a_pair_key_stated_badly_is_refused_when_the_mapping_loads(tmp_path: Path, lookup_key: Any, join: Any) -> None:
    with pytest.raises(MappingError):
        _mapping(tmp_path, lookup_key, join)


@pytest.mark.parametrize(("written", "code"), [
    ("{cells}/uL", "/uL"), ("{cells}/µL", "/uL"), ("cells/uL", "/uL"), ("cells/ul", "/uL"), ("/uL", "/uL"),
    ("10^3/ul", "10*3/uL"), ("1000/uL", "10*3/uL"), ("1000/µL", "10*3/uL"),
    ("mg/L FEU", "mg/L{FEU}"), ("mg/L(FEU)", "mg/L{FEU}"), ("ug/mL FEU", "mg/L{FEU}"), ("µg/mL FEU", "mg/L{FEU}"),
    ("倍數", "{titer}"), ("倍", "{titer}"),
])  # fmt: skip
def test_the_unit_spellings_a_lab_export_writes_are_read(written: str, code: str) -> None:
    assert labvalue.ucum(written) == code


def test_fibrinogen_equivalent_units_are_never_plain_mg_per_litre() -> None:
    assert labvalue.units_agree("mg/L FEU", "mg/L") is False
    assert labvalue.units_agree("mg/L", "mg/L{FEU}") is False
    assert labvalue.units_agree("mg/L FEU", "mg/L{FEU}") is True
    assert labvalue.units_agree("倍數", "{titer}") is True and labvalue.units_agree("倍數", "1") is False


def test_a_d_dimer_in_feu_is_read_and_one_in_plain_mg_per_litre_has_no_value(tmp_path: Path) -> None:
    m = _mapping(tmp_path)
    _, (feu,) = _map(m, _lab("COAG", "031", "0.8", "mg/L FEU"))
    _, (plain,) = _map(m, _lab("COAG", "031", "0.8", "mg/L"))
    assert feu["valueQuantity"]["value"] == 0.8
    assert "valueQuantity" not in plain


def test_the_mapping_check_asks_the_source_for_the_parts_not_the_joined_column(tmp_path: Path) -> None:
    """The check selects only the columns the mapping names (D-588): the parts, which the source has."""
    from tools.mapping_check import _wanted

    m = _mapping(tmp_path)
    specs = [r for r in m.resources if r.table == "lab"]
    need, optional, local = _wanted(m, "lab", m.tables["lab"], specs)
    assert "lab_key" not in need | optional | set(local)
    assert {"panel_code", "local_code"} <= need and {"panel_code", "local_code"} <= set(local)
