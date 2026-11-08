"""D-113: a code-prefix grouper fails closed. A record coded inside the grouper's family but outside its listed codes
makes the criterion unknown (kept for review), never a silent "not present" (Fable review 2026-11-08, finding 2)."""

from __future__ import annotations

from datetime import date
from typing import Any

import duckdb
import pytest
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.terminology.mapper import FAMILY_EXT, SYSTEMS, Terminology, ValueSets, valueset
from matching.cascade.engine import CODE_OUTSIDE_LIST
from orchestrator.scenarios.evaluate import structured_verdict
from tb_contracts import CriterionIR, PatientEvaluation

ICD = SYSTEMS["icd10cm"]


def _vs(term: Terminology) -> dict[str, dict[str, Any]]:
    res = term.map("condition", "malignancy")
    return {
        "VS_MALIGNANCY": valueset("FAM", "VS_MALIGNANCY", "malignancy", res.concepts, "1.0.0", families=res.families)
    }


def _crit(kind: str, quantifier: str | None = None) -> CriterionIR:
    logic: dict[str, Any] = {"domain": "condition", "valueset": "VS_MALIGNANCY"}
    if quantifier:
        logic["quantifier"] = quantifier
    return CriterionIR.model_validate(
        {"id": f"FAM-{kind[:3].upper()}-01", "ruleset": "FAM", "text": "malignancy", "kind": kind,
         "class": "structured", "logic": logic}
    )  # fmt: skip


def _run(sql: str, codes: dict[str, list[str]]) -> dict[str, bool | None]:
    con = duckdb.connect()
    con.execute("CREATE TABLE patient (pid VARCHAR, birth_date DATE, sex VARCHAR, deceased_date DATE)")
    con.execute(
        "CREATE TABLE condition (pid VARCHAR, cid VARCHAR, system VARCHAR, code VARCHAR, onset DATE, recorded DATE)"
    )
    for i, (pid, cs) in enumerate(codes.items()):
        con.execute("INSERT INTO patient VALUES (?, DATE '1960-01-01', 'female', NULL)", [pid])
        for j, c in enumerate(cs):
            con.execute("INSERT INTO condition VALUES (?, ?, ?, ?, DATE '2025-01-01', NULL)", [pid, f"c{i}{j}", ICD, c])
    rows = con.execute(sql, [[date(2026, 1, 1).isoformat()], list(codes)]).fetchall()
    cols = [d[0] for d in con.description]
    out = {}
    for r in rows:
        rec = dict(zip(cols, r, strict=True))
        out[rec["pid"]] = next(v for k, v in rec.items() if k.startswith("C_"))
    return out


PATIENTS = {
    "listed": ["C50.911"],  # in the list
    "offlist": ["C50.912"],  # inside the C5 family, not in the demo list
    "skin": ["C44.91"],  # basal cell skin cancer: outside every malignancy family (C44 is not listed)
    "none": ["M10.00"],
    "both": ["C50.912", "C61"],
}


def test_grouper_keeps_its_families_on_the_valueset() -> None:
    term = Terminology()
    res = term.map("condition", "malignancy")
    assert (ICD, "C5") in res.families and (ICD, "C8") in res.families
    codes = {c.code for c in res.concepts}
    assert {"C80.1", "C50.9", "C25.9"} <= codes, "the public-data cancer codes are in the demo terminology"
    vs = _vs(term)
    assert any(e["url"] == FAMILY_EXT and e["valueString"] == f"{ICD}|C5" for e in vs["VS_MALIGNANCY"]["extension"])
    assert ValueSets("FAM", vs).families("VS_MALIGNANCY") == res.families
    # a plain list (exact synonyms, no prefix) carries no family and renders the same SQL as before
    plain = term.map("condition", "medullary thyroid carcinoma")
    assert plain.families == [] and "extension" not in valueset("FAM", "VS_MTC", "mtc", plain.concepts, "1.0.0")


@pytest.mark.parametrize("kind", ["inclusion", "exclusion"])
def test_offlist_family_code_is_unknown_not_false(kind: str) -> None:
    vs = ValueSets("FAM", _vs(Terminology()))
    got = _run(SqlGenerator("FAM", "1.0.0", vs).render([_crit(kind)]), PATIENTS)
    assert got == {"listed": True, "offlist": None, "skin": False, "none": False, "both": True}


def test_none_quantifier_fails_closed_too() -> None:
    vs = ValueSets("FAM", _vs(Terminology()))
    got = _run(SqlGenerator("FAM", "1.0.0", vs).render([_crit("inclusion", "none")]), PATIENTS)
    assert got == {"listed": False, "offlist": None, "skin": True, "none": True, "both": False}


def test_valueset_without_families_renders_no_family_table() -> None:
    term = Terminology()
    res = term.map("condition", "malignancy")
    vs = ValueSets("FAM", {"VS_MALIGNANCY": valueset("FAM", "VS_MALIGNANCY", "m", res.concepts, "1.0.0")})
    sql = SqlGenerator("FAM", "1.0.0", vs).render([_crit("inclusion")])
    assert "vsf(" not in sql and "_off" not in sql
    assert _run(sql, PATIENTS)["offlist"] is False  # the old behaviour, kept for lists that are not groupers


def test_offlist_unknown_names_its_reason_in_both_paths() -> None:
    c = _crit("inclusion")
    ev = PatientEvaluation(
        pid="p", index_date=date(2026, 1, 1), engine="sql", results={c.id: None}, evidence={c.id: ["c00|2025-01-01"]}
    )
    v = structured_verdict(c, ev)
    assert v.verdict == "unknown" and v.evidence is not None and v.evidence.reason == CODE_OUTSIDE_LIST
    gap = PatientEvaluation(pid="p", index_date=date(2026, 1, 1), engine="sql", results={c.id: None}, evidence={})
    assert structured_verdict(c, gap).evidence.reason == "data_gap"  # type: ignore[union-attr]
