"""SCR-01 (deep review 2026-11-13, Critical): the malignancy value set missed C44 and C4A.

"Malignancy within the past 5 years" (RA-JAK-EXC-08, RA-BIO-EXC-04) did not exclude a patient with a squamous or
basal cell carcinoma of the skin (C44) or a Merkel cell carcinoma (C4A): the grouper listed the families around
them (C43, C45 ...), a code outside list and families is a plain non-match, and the compiled SQL said FALSE: a
silent wrong inclusion. One shared grouper had dropped C44 for GZQO's "except non-melanoma skin cancer"; the
exception belongs to that one criterion. A personal history code (Z85) or a neoplasm malignant by behaviour (D45 to
D47) was a silent FALSE too; it is now a member of the family without being a listed code: the answer is unknown,
and a person looks."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pytest
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.terminology.mapper import FAMILY_EXT, SYSTEMS, Terminology, ValueSets, valueset
from tb_contracts import CriterionIR

ROOT = Path(__file__).resolve().parents[2]
ICD = SYSTEMS["icd10cm"]
ALL = "malignancy"
EXCEPT_NMSC = "malignancy except non-melanoma skin cancer"
#: the shipped criteria that say "malignancy", and what each says of non-melanoma skin cancer
SHIPPED = {"RA-JAK": ("RA-JAK-EXC-08", True), "RA-BIO": ("RA-BIO-EXC-04", True), "GZQO": ("GZQO-EXC-07", False)}


def _valueset_of(rid: str, cid: str) -> dict[str, Any]:
    ir = json.loads((ROOT / "rulesets" / rid / "ir" / f"{cid}.json").read_text(encoding="utf-8"))
    names = {m.group(0) for m in __import__("re").finditer(r"VS_[A-Z0-9_]+", json.dumps(ir["logic"]))}
    assert len(names) == 1, names
    doc: dict[str, Any] = json.loads(
        (ROOT / "rulesets" / rid / "valuesets" / f"{names.pop()}.json").read_text(encoding="utf-8")
    )
    return doc


def _codes(vs: dict[str, Any]) -> set[str]:
    return {x["code"] for inc in vs["compose"]["include"] if inc["system"] == ICD for x in inc.get("concept", [])}


def _families(vs: dict[str, Any]) -> set[str]:
    return {
        e["valueString"].rsplit("|", 1)[1]
        for e in vs.get("extension", [])
        if e["url"] == FAMILY_EXT and e["valueString"].startswith(ICD + "|")
    }


@pytest.mark.parametrize("rid", sorted(SHIPPED))
def test_the_shipped_criterion_lists_merkel_cell_carcinoma_and_knows_the_history_codes(rid: str) -> None:
    cid, _ = SHIPPED[rid]
    vs = _valueset_of(rid, cid)
    codes, fams = _codes(vs), _families(vs)
    assert {"C4A.0", "C4A.9", "C43.9", "C50.911"} <= codes and "C4A" in fams
    # personal history of a malignancy, and neoplasms malignant by behaviour: in the family, not listed
    assert {"Z85", "D45", "D46", "D47"} <= fams and not {c for c in codes if c.startswith(("Z85", "D45", "D46", "D47"))}


@pytest.mark.parametrize("rid", sorted(SHIPPED))
def test_non_melanoma_skin_cancer_is_a_malignancy_except_where_the_criterion_says_otherwise(rid: str) -> None:
    cid, counts = SHIPPED[rid]
    vs = _valueset_of(rid, cid)
    codes, fams = _codes(vs), _families(vs)
    skin = {c for c in codes if c.startswith("C44")}
    if counts:
        assert {"C44.01", "C44.92"} <= skin and "C44" in fams
    else:  # GZQO: "except non-melanoma skin cancer": such a patient stays eligible, by this criterion's own list
        assert not skin and "C44" not in fams


# ----------------------------------------------------------------------------------- what the compiled SQL answers
def _answers(concept: str, kind: str = "exclusion") -> dict[str, bool | None]:
    term = Terminology()
    res = term.map("condition", concept)
    vs = {"VS_M": valueset("M", "VS_M", concept, res.concepts, "1.0.0", families=res.families)}
    crit = CriterionIR.model_validate(
        {"id": "M-EXC-01", "ruleset": "M", "text": concept, "kind": kind, "class": "structured",
         "logic": {"domain": "condition", "quantifier": "any", "valueset": "VS_M"}}
    )  # fmt: skip
    sql = SqlGenerator("M", "1.0.0", ValueSets("M", vs, term)).render([crit])
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE patient (pid VARCHAR, birth_date DATE, sex VARCHAR, deceased_date DATE, deceased BOOLEAN)"
    )
    con.execute(
        "CREATE TABLE condition (pid VARCHAR, cid VARCHAR, system VARCHAR, code VARCHAR, onset DATE, recorded DATE)"
    )
    patients = {"basal": "C44.91", "merkel": "C4A.0", "melanoma": "C43.9", "history": "Z85.3", "mds": "D46.9",
                "pv": "D45", "gout": "M10.9"}  # fmt: skip
    for i, (pid, code) in enumerate(patients.items()):
        con.execute("INSERT INTO patient VALUES (?, DATE '1960-01-01', 'female', NULL, NULL)", [pid])
        con.execute("INSERT INTO condition VALUES (?, ?, ?, ?, DATE '2025-06-01', NULL)", [pid, f"c{i}", ICD, code])
    rows = con.execute(sql, [[date(2026, 11, 9).isoformat()], list(patients)]).fetchall()
    cols = [d[0] for d in con.description]
    return {
        str(dict(zip(cols, r, strict=True))["pid"]): next(
            v for k, v in dict(zip(cols, r, strict=True)).items() if k.startswith("C_")
        )
        for r in rows
    }


def test_malignancy_is_true_for_skin_and_merkel_cell_carcinoma_and_unknown_for_a_history_code() -> None:
    got = _answers(ALL)
    assert got == {"basal": True, "merkel": True, "melanoma": True, "history": None, "mds": None, "pv": None,
                   "gout": False}  # fmt: skip


def test_the_exception_is_a_concept_of_its_own_and_only_drops_non_melanoma_skin_cancer() -> None:
    got = _answers(EXCEPT_NMSC)
    assert got == {"basal": False, "merkel": True, "melanoma": True, "history": None, "mds": None, "pv": None,
                   "gout": False}  # fmt: skip


def test_every_shipped_ruleset_that_says_malignancy_has_the_same_list_as_the_grouper_gives_today() -> None:
    """Whatever ruleset names the concept gets C44 and C4A with it (the build's drift check holds the files)."""
    want = {c.code for c in Terminology().map("condition", ALL).concepts if c.system == ICD}
    assert {"C44.01", "C4A.0"} <= want
    for rid in ("RA-JAK", "RA-BIO"):
        assert _codes(_valueset_of(rid, SHIPPED[rid][0])) == want, rid
