"""T-614 (D-314): Japan's ICD-10 is WHO ICD-10, not ICD-10-CM (review STD-010).

* the SS-MIX2 reader keeps the WHO code (a licensed MEDIS target too, even when ICD-10-CM has no such code) and gives
  the ICD-10-CM twin only when ICD-10-CM has the very same code;
* the JP mapping carries the WHO coding under ``http://hl7.org/fhir/sid/icd-10`` on every Condition; JP Core
  ``$validate`` accepts it (0 errors);
* the compiler's groupers stand for the WHO-only categories (E14, I64, F00, ...): a record coded ``E14.9``, ``I64``
  or ``F00.1`` makes the matching criterion unknown, never false, in the SQL and in the CQL the compiler writes.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pytest
from adapter.sources.ssmix2.source import Ssmix2Source, storage_dir, who_icd10
from adapter.validate import jpcore
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.terminology.mapper import (
    ICD10_WHO,
    SYSTEMS,
    WHO_ONLY_CATEGORIES,
    Terminology,
    ValueSets,
    valueset,
    who_only_families,
)
from matching.coverage import Coverage, GapRow, known_systems
from tb_contracts import CriterionIR

ROOT = Path(__file__).resolve().parents[2]
JP_MAPPING = ROOT / "services/adapter/mapping/jp_core/ssmix2_site.yaml"
ICD = SYSTEMS["icd10cm"]
WHO = "http://hl7.org/fhir/sid/icd-10"
BYOMEI = "urn:oid:1.2.392.200119.4.101.6"
EMPTY: dict[str, dict[str, dict[str, str]]] = {"medis": {}, "jlac10": {}, "yj": {}}


def _storage(root: Path, patient: str, order: str, prb: str) -> None:
    d = storage_dir(root, patient, "20260101", "PPR-01")
    d.mkdir(parents=True, exist_ok=True)
    msh = f"MSH|^~\\&|HIS||TB||20261101||PPR^ZD1|{order}|P|2.5"
    text = (
        "\r".join([msh, f"PID|||{patient}^^^^PI", "PV1||O", prb]) + "\r"
    )  # every SS-MIX2 message carries its patient (PR #1095 fourth review b)
    (d / f"{patient}_20260101_PPR-01_{order}_20261101000000000_01_1").write_bytes(text.encode("utf-8"))


def _prb(order: str, alt: str = "", byomei: str = "") -> str:
    cwe = f"{byomei}^病名^99XYZ" + (f"^{alt}^^I10" if alt else "")
    return f"PRB|AD|20260101|{cwe}|{order}||||||||||A||20260101"


# ------------------------------------------------------------------------------------------------- the reader
def test_who_code_is_written_one_way() -> None:
    assert who_icd10("e149") == "E14.9"
    assert who_icd10(" I64 ") == "I64"
    assert who_icd10("G30.0*") == "G30.0" and who_icd10("A17.0†") == "A17.0"
    assert who_icd10("F001") == "F00.1" and who_icd10("M1097") == "M10.97"
    assert who_icd10("M1A.9XX0") == "M1A.9XX0"  # not a WHO shape: kept as written, counted by the reader
    assert who_icd10("") == ""


def test_reader_keeps_who_code_and_gives_icd10cm_only_when_the_same(tmp_path: Path) -> None:
    root = tmp_path / "ss"
    for n, alt in enumerate(("E14.9", "I64", "F00.1", "E11.9", "e119", "M1A.9XX0")):
        _storage(root, "10000001", f"D{n}", _prb(f"D{n}", alt=alt))
    medis = {"ZX01": {"target_code": "E14.9"}, "ZX02": {"target_code": "M10.9"}}
    _storage(root, "10000001", "D8", _prb("D8", byomei="ZX01"))
    _storage(root, "10000001", "D9", _prb("D9", byomei="ZX02"))
    src = Ssmix2Source(root, licensed={**EMPTY, "medis": medis})
    got = {r["diag_no"]: (r["icd10"], r["icd10cm"]) for r in src.rows("diagnosis", "diagnosis", None, None)}
    assert got == {
        "D0": ("E14.9", ""),
        "D1": ("I64", ""),
        "D2": ("F00.1", ""),
        "D3": ("E11.9", "E11.9"),
        "D4": ("E11.9", "E11.9"),
        "D5": ("M1A.9XX0", "M1A.9XX0"),
        "D8": ("E14.9", ""),  # the MEDIS target is kept although ICD-10-CM has no E14
        "D9": ("M10.9", "M10.9"),
    }
    assert src.stats["diagnosis:licensed"] == 2 and src.stats["diagnosis:licensed WHO-only code"] == 1
    assert src.stats["diagnosis:not a WHO ICD-10 shape"] == 1
    assert not src.missed


# -------------------------------------------------------------------------------- the JP mapping and JP Core
def _conditions(tmp_path: Path) -> dict[str, dict[str, Any]]:
    from adapter.mapping.engine import Mapper, Mapping

    root = tmp_path / "ss"
    for n, alt in enumerate(("E14.9", "I64", "F00.1", "E11.9")):
        _storage(root, "10000001", f"D{n}", _prb(f"D{n}", alt=alt, byomei=f"ZB{n:02d}"))
    rows = list(Ssmix2Source(root, licensed=EMPTY).rows("diagnosis", "diagnosis", None, None))
    mapper = Mapper(Mapping.load(JP_MAPPING), b"k" * 32, "JP-A")
    res = [r for r in mapper.map_table("diagnosis", iter(rows)) if r["resourceType"] == "Condition"]
    return {next(c["code"] for c in r["code"]["coding"] if c["system"] == WHO): r for r in res}


def test_jp_condition_carries_the_who_uri(tmp_path: Path) -> None:
    conds = _conditions(tmp_path)
    assert set(conds) == {"E14.9", "I64", "F00.1", "E11.9"}
    systems = {k: [c["system"] for c in v["code"]["coding"]] for k, v in conds.items()}
    assert systems["E14.9"] == [WHO, BYOMEI]  # WHO-only: no ICD-10-CM coding at all
    assert systems["I64"] == [WHO, BYOMEI] and systems["F00.1"] == [WHO, BYOMEI]
    assert systems["E11.9"] == [ICD, WHO, BYOMEI]  # the same code in both: ICD-10-CM first (the one the lake reads)
    from lake.flatten import Flattener

    flat = {k: Flattener("Asia/Tokyo").condition(v) for k, v in conds.items()}
    assert (flat["E14.9"]["system"], flat["E14.9"]["code"]) == (WHO, "E14.9")
    assert (flat["E11.9"]["system"], flat["E11.9"]["code"]) == (ICD, "E11.9")


def test_jp_core_accepts_the_who_uri(tmp_path: Path) -> None:
    rep = jpcore.JpCoreValidator(EMPTY).validate(list(_conditions(tmp_path).values()))
    assert rep.sampled == 4 and rep.errors == 0, rep.messages()
    cond: dict[str, Any] = {
        "resourceType": "Condition",
        "id": "c1",
        "meta": {"profile": [jpcore.JP + "JP_Condition"]},
        "subject": {"reference": "Patient/p1"},
        "code": {"coding": [{"system": WHO, "code": "C50.911"}]},
    }
    out = jpcore.JpCoreValidator(EMPTY).check(cond)  # an ICD-10-CM-only shape under the WHO URI: listed, not failed
    assert out.ok and [i.text for i in out.issues] == ["the code is not written as a WHO ICD-10 code"]


# ----------------------------------------------------------------------------------------- the grouper table
def test_groupers_stand_for_the_who_only_categories() -> None:
    term = Terminology()
    assert (WHO, "E14") in term.map("condition", "type 2 diabetes mellitus").families
    assert (WHO, "E14") in term.map("condition", "type 1 diabetes").families
    assert (WHO, "I64") in term.map("condition", "stroke").families
    assert (WHO, "C97") in term.map("condition", "malignancy").families
    gout = term.map("condition", "gout").families
    assert all(sy == ICD for sy, _ in gout), "no WHO-only category belongs with gout"
    assert who_only_families([(ICD, "G30")]) == {(WHO, "F00")}
    assert who_only_families([(WHO, "G30")]) == set(), "only ICD-10-CM families take WHO-only categories"
    assert ICD10_WHO == WHO and all(len(c) == 3 for c in WHO_ONLY_CATEGORIES)
    full = {c.code[:3] for c in term.expand("icd10cm", "", "prefix")}
    assert not set(WHO_ONLY_CATEGORIES) & full, "a WHO-only category is not an ICD-10-CM category"


def _vs(name: str, concept: str | None = None, prefixes: tuple[str, ...] = ()) -> ValueSets:
    term = Terminology()
    if concept:
        res = term.map("condition", concept)
        concepts, fams = res.concepts, res.families
    else:  # a grouper over prefixes the synonym table does not hold yet (dementia), built the way the mapper does
        concepts = [c for p in prefixes for c in term.expand("icd10cm", p, "prefix")]
        raw = {(ICD, p) for p in prefixes}
        fams = sorted(raw | who_only_families(raw))
    return ValueSets("JP", {name: valueset("JP", name, name, concepts, "1.0.0", families=fams)})


def _crit(vs: str, kind: str) -> CriterionIR:
    return CriterionIR.model_validate(
        {"id": f"JP-{kind[:3].upper()}-01", "ruleset": "JP", "text": vs, "kind": kind, "class": "structured",
         "logic": {"domain": "condition", "valueset": vs}}
    )  # fmt: skip


def _run(sql: str, codes: dict[str, tuple[str, str]]) -> dict[str, bool | None]:
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE patient (pid VARCHAR, birth_date DATE, sex VARCHAR, deceased_date DATE, deceased BOOLEAN)"
    )
    con.execute(
        "CREATE TABLE condition (pid VARCHAR, cid VARCHAR, system VARCHAR, code VARCHAR, onset DATE, recorded DATE)"
    )
    for i, (pid, (sy, c)) in enumerate(codes.items()):
        con.execute("INSERT INTO patient VALUES (?, DATE '1960-01-01', 'female', NULL, NULL)", [pid])
        con.execute("INSERT INTO condition VALUES (?, ?, ?, ?, DATE '2025-01-01', NULL)", [pid, f"c{i}", sy, c])
    rows = con.execute(sql, [[date(2026, 1, 1).isoformat()], list(codes)]).fetchall()
    cols = [d[0] for d in con.description]
    return {
        dict(zip(cols, r, strict=True))["pid"]: next(v for k, v in zip(cols, r, strict=True) if k.startswith("C_"))
        for r in rows
    }


CASES = [
    ("VS_T2DM", "type 2 diabetes mellitus", (), "E14.9", "E11.9"),
    ("VS_STROKE", "stroke", (), "I64", "I63.9"),
    ("VS_DEMENTIA", None, ("F01", "F02", "F03", "G30"), "F00.1", "G30.9"),
]


@pytest.mark.parametrize(("name", "concept", "prefixes", "who", "listed"), CASES)
@pytest.mark.parametrize("kind", ["inclusion", "exclusion"])
def test_who_only_record_makes_the_criterion_unknown_never_false(
    name: str, concept: str | None, prefixes: tuple[str, ...], who: str, listed: str, kind: str
) -> None:
    """Acceptance of T-614: ``E14.9``, ``I64`` and ``F00.1`` make the matching criteria true or unknown, never
    false, whether the criterion includes or excludes."""
    vs = _vs(name, concept, prefixes)
    pts = {"who_only": (WHO, who), "cm_listed": (ICD, listed), "other": (WHO, "J45.9")}
    got = _run(SqlGenerator("JP", "1.0.0", vs).render([_crit(name, kind)]), pts)
    assert got["who_only"] is None
    assert got["cm_listed"] is True
    # outside every family the compiled SQL says false; for an inclusion D-130 holds the WHO row (WHO is a system no
    # ValueSet lists), so the patient is unknown at runtime, not excluded
    assert got["other"] is False
    assert WHO not in known_systems(vs.by_name)
    cov = Coverage({"other": [GapRow("condition", "c2", date(2025, 1, 1), WHO)]})
    refs = cov.refs(_crit(name, "inclusion"), "other", date(2026, 1, 1))
    assert refs == ["c2|2025-01-01"]


def test_who_only_family_reaches_the_cql_too() -> None:
    from criteria_compiler.compile_cql.generator import CqlGenerator

    cql = CqlGenerator("JP", "1.0.0", _vs("VS_T2DM", "type 2 diabetes mellitus")).render(
        [_crit("VS_T2DM", "inclusion")]
    )
    assert f"(Cd.system.value = '{WHO}' and StartsWith(Cd.code.value, 'E14'))" in cql
