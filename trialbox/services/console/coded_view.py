"""The coded records behind an answer, on the patient page and the not-matched list (card T-514, D-362, UX-008).

``matching.coded_values`` puts on a coded answer the records a person checks it against: the record's own value
and unit, its date and its code (``evidence.coded``). This module turns them into the lines the two pages show
("29.4 kg/m² · 2026-09-12 · LOINC 39156-5", "ICD-10-CM M10.9 · 2025-10-08") and holds their words in the three page
languages. A coded answer the run found no record behind says so in words, so no met or not met row is left without
a value or a quote.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from criteria_compiler.terminology.mapper import SYSTEMS

from console.i18n import CATALOGUES

# the short name of a code system beside the code; a system not listed shows the code alone (its URI on hover)
SYSTEM_NAMES: dict[str, str] = {
    SYSTEMS["icd10cm"]: "ICD-10-CM",
    "http://hl7.org/fhir/sid/icd-10": "ICD-10",
    SYSTEMS["atc"]: "ATC",
    SYSTEMS["loinc"]: "LOINC",
    SYSTEMS["nhi_drug"]: "NHI",
    SYSTEMS["nhi_order"]: "NHI",
    "http://snomed.info/sct": "SNOMED CT",
}

EN: dict[str, str] = {
    "coded.none": "No coded record matches the codes and limits of this criterion",
    "coded.more": "and {n} more records",
    "coded.age": "age {n}",
    "coded.sex.male": "male",
    "coded.sex.female": "female",
    "coded.dept": "department",
}
JA: dict[str, str] = {
    "coded.none": "基準のコードと条件に当てはまるコード化された記録はありません",
    "coded.more": "ほか記録 {n} 件",
    "coded.age": "{n} 歳",
    "coded.sex.male": "男性",
    "coded.sex.female": "女性",
    "coded.dept": "診療科",
}
ZH: dict[str, str] = {
    "coded.none": "沒有符合此條件之代碼與數值範圍的編碼紀錄",
    "coded.more": "另有 {n} 筆紀錄",
    "coded.age": "{n} 歲",
    "coded.sex.male": "男性",
    "coded.sex.female": "女性",
    "coded.dept": "科別",
}

for _lang, _cat in (("en", EN), ("ja", JA), ("zh-TW", ZH)):
    CATALOGUES[_lang].update(_cat)


def number(v: float) -> str:
    """A stored number as the record shows it: ``29.4``, ``88``, ``0.25`` (no trailing zeros, no exponent)."""
    text = f"{v:.6f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


# review 2026-11-13 (CON-UX-3): the printed form of the UCUM codes a page shows most; the stored unit is unchanged
SHOWN_UNIT = {"mm[Hg]": "mmHg", "[iU]/L": "IU/L", "[IU]/L": "IU/L", "10*9/L": "10^9/L", "10*12/L": "10^12/L",
              "10*3/uL": "10^3/uL", "10*6/uL": "10^6/uL"}  # fmt: skip


def shown_unit(unit: str) -> str:
    return SHOWN_UNIT.get(unit, unit)


def line(cv: Mapping[str, Any]) -> dict[str, Any]:
    """One coded record as the page shows it: the value (number, comparator and unit, or a coded answer), the age or
    the sex of a demographic answer, the date, and the code with its system's short name."""
    system = str(cv.get("system") or "")
    out: dict[str, Any] = {"date": cv.get("date") or "", "code": cv.get("code") or "", "system_uri": system,
                           "system": SYSTEM_NAMES.get(system, ""), "value": "", "age": None, "sex": "",
                           "dept": system == SYSTEMS["department"]}  # fmt: skip
    if cv.get("domain") == "demographic":
        if cv.get("code") == "age" and cv.get("value") is not None:
            out["age"] = int(cv["value"])
        elif cv.get("code") == "sex":
            out["sex"] = str(cv.get("value_code") or "")
        out["code"] = ""
        return out
    if cv.get("value") is not None:
        out["value"] = " ".join(
            x for x in (f"{cv.get('comparator') or ''}{number(float(cv['value']))}", shown_unit(str(cv.get("unit") or ""))) if x
        )
    elif cv.get("value_code"):
        out["value"] = str(cv["value_code"])
    return out


def view(ev: Mapping[str, Any], verdict: Any) -> dict[str, Any]:
    """What the evidence cell shows of the coded records: ``lines`` (latest first), ``more`` (records not shown) and
    ``none`` (the run looked and found no record behind a met or not met coded answer: an empty ``coded``). A list
    from before T-514 has no ``coded``: its cell is as it was."""
    raw = ev.get("coded")
    coded = [line(x) for x in raw or [] if isinstance(x, Mapping)]
    refs = [r for r in ev.get("resource_refs") or [] if not str(r).startswith("DocumentReference/")]
    shown_refs = sum(1 for x in raw or [] if isinstance(x, Mapping) and x.get("domain") != "demographic")
    return {
        "lines": coded,
        "more": max(0, len(refs) - shown_refs) if coded else 0,
        "none": raw == [] and not ev.get("quote") and verdict in ("pass", "fail"),
    }
