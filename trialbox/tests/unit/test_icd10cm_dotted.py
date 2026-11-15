"""F6 (D-808): a site that stores ICD-10-CM codes without their dot has them written dotted.

Value sets and screens hold ICD-10-CM in its dotted form (``M10.9``) and match exactly or by prefix. A source that
stores ``M109`` matched nothing. ``{builder: coding, ..., dotted: icd10cm}`` writes a code of the ICD-10-CM shape with
its dot after the third character; a three-character category has none; a code already dotted is kept. Anything
else is copied as it is and counted (never altered by a guess). Synthetic codes only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from adapter.mapping.engine import Mapper, Mapping

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
I10 = "http://hl7.org/fhir/sid/icd-10-cm"


def _mapper(tmp_path: Path, dotted: bool = True) -> Mapper:
    doc: dict[str, Any] = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    for spec in (doc.get("lookups") or {}).values():
        spec["file"] = str(BASE.parent / spec["file"])
    diag = next(r for r in doc["resources"] if r["type"] == "Condition" and r["table"] == "diagnosis")
    if dotted:
        diag["elements"]["code.coding[0]"]["dotted"] = "icd10cm"
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return Mapper(Mapping.load(path), b"k" * 32, "s")


def _icd10(m: Mapper, code: str) -> str | None:
    row = {"diag_no": "D1", "enc_no": "E1", "mrn": "P1", "icd10": code, "diag_date": "2026-01-13",
           "recorded_date": "2026-01-13", "status": "A", "diag_code_system": "icd10cm"}  # fmt: skip
    (res,) = [r for r in m.map_table("diagnosis", iter([row])) if r["resourceType"] == "Condition"]
    return next((c["code"] for c in res["code"]["coding"] if c["system"] == I10), None)


@pytest.mark.parametrize(("fed", "want"), [
    ("M109", "M10.9"), ("E1165", "E11.65"), ("S72001A", "S72.001A"), ("T8452XA", "T84.52XA"), ("m109", "M10.9"),
    ("M10", "M10"), ("I10", "I10"), ("M10.9", "M10.9"), (" M109 ", "M10.9"), ("U071", "U07.1"),
])  # fmt: skip
def test_an_icd10cm_code_without_its_dot_is_written_dotted(tmp_path: Path, fed: str, want: str) -> None:
    assert _icd10(_mapper(tmp_path), fed) == want


@pytest.mark.parametrize("fed", ["7140", "M1", "M10.9.1", "1M09", "M10-9", "M109XXXXX", "藥"])
def test_a_code_not_of_the_icd10cm_shape_is_copied_and_counted(tmp_path: Path, fed: str) -> None:
    m = _mapper(tmp_path)
    assert _icd10(m, fed) == fed.strip()
    assert sum(n for (t, name, _), n in m.unmapped.items() if t == "diagnosis" and name == "shape:icd10cm") == 1


def test_without_the_declaration_a_code_is_copied_as_before(tmp_path: Path) -> None:
    assert _icd10(_mapper(tmp_path, dotted=False), "M109") == "M109"


# CGRD-A3 (D-815): a site's own codes that look like ICD-10-CM are kept as written, never dotted into a code they are not
def _local(tmp_path: Path, keep: Any) -> Mapper:
    doc: dict[str, Any] = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    for spec in (doc.get("lookups") or {}).values():
        spec["file"] = str(BASE.parent / spec["file"])
    diag = next(r for r in doc["resources"] if r["type"] == "Condition" and r["table"] == "diagnosis")
    diag["elements"]["code.coding[0]"].update({"dotted": "icd10cm", "keep_as_written": keep})
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return Mapper(Mapping.load(path), b"k" * 32, "s")


@pytest.mark.parametrize(("fed", "want"), [("Q990001", "Q990001"), ("q990001", "Q990001"), ("Z000LOC", "Z000LOC"),
                                           ("M109", "M10.9")])  # fmt: skip
def test_a_sites_own_code_is_kept_as_written_and_counted(tmp_path: Path, fed: str, want: str) -> None:
    m = _local(tmp_path, ["Q990001", "Z000LOC"])
    assert _icd10(m, fed) == want
    local = sum(n for (t, name, _), n in m.unmapped.items() if t == "diagnosis" and name == "local:icd10cm")
    assert local == (0 if want == "M10.9" else 1)


@pytest.mark.parametrize("keep", ["Q990001", [""], [1]])
def test_keep_as_written_stated_badly_is_refused_at_load(tmp_path: Path, keep: Any) -> None:
    from adapter.mapping.engine import MappingError

    with pytest.raises(MappingError):
        _local(tmp_path, keep)
