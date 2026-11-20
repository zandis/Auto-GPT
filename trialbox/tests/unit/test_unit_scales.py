"""D-418 (T-619c, DATA-016): the engines convert units of one kind by definition, whatever the analyte.

Before, the SQL and CQL engines converted only the five analytes of ``tb_common.derived.UNITS``: a haemoglobin of
120 g/L against "Hb >= 9 g/dL", or a white count of 0.45 10*4/uL against "WBC >= 3.0 10*9/L", was unknown
(``unit_mismatch``). The scale table of D-334 (``SCALES``) now feeds the Python rule, its SQL twin and its CQL twin.
Mass to substance (mg/dL to mmol/L) still needs a molar mass and stays unknown in the engines.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pytest
from criteria_compiler.compile_cql.generator import _cql_dec, unit_function
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.terminology.mapper import Concept, Terminology, ValueSets, valueset
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake
from tb_common import id_rule, labunit, labvalue
from tb_contracts import CriterionIR

LOINC = "http://loinc.org"
HB, WBC, GLUCOSE, CREAT = "718-7", "6690-2", "2345-7", "2160-0"
IDX = date(2026, 10, 5)


def test_units_of_one_kind_convert_whatever_the_analyte() -> None:
    assert labunit.convert(120, "g/L", "g/dL", LOINC, HB) == pytest.approx(12.0)
    assert labunit.convert(12, "g/dL", "g/L", LOINC, HB) == pytest.approx(120.0)
    assert labunit.convert(0.45, "10*4/uL", "10*9/L", LOINC, WBC) == pytest.approx(4.5)
    assert labunit.convert(4500, "/uL", "10^9/L", LOINC, WBC) == pytest.approx(4.5)
    assert labunit.convert(3.2, "ng/mL", "ug/L") == pytest.approx(3.2)  # one unit, two spellings
    assert labunit.convert(7.0, "ug/mL", "mg/L") == pytest.approx(7.0)
    assert labunit.convert(250, "pg/mL", "ng/mL") == pytest.approx(0.25)
    assert labunit.convert(40, "U/L", "mU/mL") == pytest.approx(40.0)
    # never across kinds, never enzyme units for international units, never % for mmol/mol
    assert labunit.convert(100, "mg/dL", "mmol/L", LOINC, GLUCOSE) is None
    assert labunit.convert(40, "U/L", "IU/L") is None
    assert labunit.convert(53, "mmol/mol", "%") is None
    assert labunit.convert(1.0, None, "g/dL") is None
    assert labunit.convert(5.0, "ug/L", "g/dL") is None  # 5e-7 g/dL would round to 0 at 6 decimals
    # the analytes' own tables are read first and agree with the families
    assert labunit.convert(88.4, "umol/L", "mg/dL", LOINC, CREAT) == pytest.approx(1.0)
    assert labunit.convert(0.01, "g/L", "mg/dL", LOINC, CREAT) == pytest.approx(1.0)


def test_the_families_are_the_adapters_table() -> None:
    """One table: what the adapter's check (labvalue.conversion) says, the engines say (labunit.convert)."""
    assert labvalue.SCALES is labunit.SCALES and labvalue.UCUM is labunit.UCUM
    for table in labunit.SCALES.values():
        for have in table:
            for want in table:
                k = labvalue.conversion(have, want)
                assert k is not None
                got = labunit.convert(1.0, have, want)
                if 1 / labunit.MAX_SCALE <= k <= labunit.MAX_SCALE:
                    assert got == pytest.approx(k), (have, want)
                else:  # a factor that could round a real value to 0 at 6 decimals: unknown in the engines
                    assert got is None, (have, want)


def _all_keys() -> list[str]:
    return sorted(labunit.FAMILIES)


def test_the_sql_twin_gives_the_python_number_for_every_unit_of_every_family() -> None:
    con = duckdb.connect()
    keys = _all_keys()
    for want in keys:
        expr = labunit.value_sql("v", "u", "s", "c", want)
        for have in [*keys, "mmol/mol", "", "%"]:
            got = con.execute(
                f"SELECT {expr} FROM (SELECT CAST(2.5 AS DOUBLE) AS v, CAST(? AS VARCHAR) AS u, ? AS s, ? AS c)",
                [have or None, LOINC, HB],
            ).fetchone()
            assert got is not None
            ref = labunit.convert(2.5, have, want, LOINC, HB)
            assert (got[0] is None) == (ref is None), (want, have, got, ref)
            if ref is not None:
                assert got[0] == pytest.approx(ref, rel=1e-9), (want, have)


def test_every_cql_factor_is_an_exact_decimal() -> None:
    """CQL decimals stop at 8 places: a factor such as 1e-9 would read as 0. Each arm's factor is written exactly."""
    for need in _all_keys():
        for _u, _op, k in labunit.scale_arms(need):
            assert Decimal(_cql_dec(k)) == Decimal(repr(k)), (need, k)
    fn = unit_function("N_x", "g/dL")
    assert "when TB.UnitKey(Q) = 'g/l' then Round(Q.value.value / 10.0, 6)" in fn
    assert "when TB.UnitKey(Q) = 'mg/dl' then Round(Q.value.value / 1000.0, 6)" in fn
    assert "'mmol/l'" not in fn and "'ug/l'" not in fn  # mass to substance; a factor of 1e-7


def _crit(cid: str, code_vs: str, op: str, num: float, unit: str) -> CriterionIR:
    return CriterionIR.model_validate(
        {
            "id": cid,
            "ruleset": "SCALE",
            "kind": "inclusion",
            "class": "structured",
            "text": cid,
            "logic": {
                "domain": "observation",
                "quantifier": "latest",
                "valueset": code_vs,
                "value": {"op": op, "num": num, "unit": unit},
                "window": {"anchor": "index", "from_days": -365, "to_days": 0},
            },
        }
    )


def _obs(pid: str, code: str, value: float, unit: str) -> dict[str, Any]:
    return {
        "resourceType": "Observation",
        "id": f"o-{pid}",
        "status": "final",
        "subject": {"reference": f"Patient/{pid}"},
        "code": {"coding": [{"system": LOINC, "code": code}]},
        "effectiveDateTime": "2026-09-20T09:00:00+08:00",
        "valueQuantity": {"value": value, "unit": unit},
    }


CASES = {
    "HB-GL-OK": (HB, 120.0, "g/L", True),  # 12 g/dL >= 9
    "HB-GL-LOW": (HB, 85.0, "g/L", False),  # 8.5 g/dL
    "HB-GDL": (HB, 9.0, "g/dL", True),
    "HB-MMOL": (HB, 7.5, "mmol/L", None),  # needs a molar mass: unknown
    "WBC-10E4": (WBC, 0.45, "10*4/uL", True),  # 4.5 10*9/L >= 3.0
    "WBC-PERUL": (WBC, 2500.0, "/uL", False),  # 2.5 10*9/L
}


def test_a_lab_in_another_unit_of_the_same_kind_is_decided_by_the_sql(tmp_path: Path) -> None:
    vs = {
        "VS_HB": valueset("SCALE", "VS_HB", "haemoglobin", [Concept(LOINC, HB, "Hb")], "1.0.0"),
        "VS_WBC": valueset("SCALE", "VS_WBC", "white cells", [Concept(LOINC, WBC, "WBC")], "1.0.0"),
    }
    crits = [_crit("SCALE-INC-01", "VS_HB", ">=", 9, "g/dL"), _crit("SCALE-INC-02", "VS_WBC", ">=", 3.0, "10*9/L")]
    sql = SqlGenerator("SCALE", "1.0.0", ValueSets("SCALE", vs, Terminology())).render(crits)
    nd = tmp_path / "ndjson"
    nd.mkdir()
    rows = {
        "Patient": [{"resourceType": "Patient", "id": p, "gender": "female", "birthDate": "1971-03-01"} for p in CASES],
        "Observation": [_obs(p, *c[:3]) for p, c in CASES.items()],
        "MedicationRequest": [],
        "Condition": [],
    }
    for name, rs in rows.items():
        (nd / f"{name}.ndjson").write_text("".join(json.dumps(r) + "\n" for r in rs), encoding="utf-8")
    id_rule.write_snapshot_record(nd)  # D-1253: a snapshot of this release
    Lake(tmp_path / "lake").rebuild("2026-10-05", HashEmbedder(), nd)
    lake = LakeLocal(tmp_path / "lake", HashEmbedder())
    got = {r["pid"]: r for r in lake.query(sql, [[IDX.isoformat()], list(CASES)]).to_pylist()}
    for pid, (code, _v, _u, want) in CASES.items():
        col = "C_SCALE-INC-01" if code == HB else "C_SCALE-INC-02"
        assert got[pid][col] is want, (pid, got[pid][col])
    assert got["HB-MMOL"]["E_SCALE-INC-01"].split(";")[0] == "unit_mismatch"
