"""IR v3 (spec v4 §6.2), the v1 -> v3 upgrade, the canonical hash and the criterion library (§6.3): S1-15."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from criteria_compiler.compile_cql.generator import CqlGenerator
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.library import ChiaLicenceUnconfirmed, CriterionLibrary, LibraryError, load_chia_seed
from criteria_compiler.semantics import CompileError
from criteria_compiler.terminology.mapper import Terminology, ValueSets
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from tb_contracts import CriterionIR, validate
from tb_contracts.criterion_ir import (
    SCHEMA_DIR,
    CriterionIRv3,
    CriterionLibraryRecord,
    NotV1Expressible,
    canonical_hash,
    downgrade_to_v1,
    jcs,
    json_schemas,
    render_schema,
    upgrade_v1,
    valueset_content_hash,
)

ROOT = Path(__file__).resolve().parents[2]
RULESET_DIRS = sorted(
    d
    for base in (ROOT / "rulesets", ROOT / "tests" / "fixtures" / "open_data" / "rulesets")
    for d in base.iterdir()
    if (d / "manifest.yaml").exists()
)
IR_FILES = sorted(p for d in RULESET_DIRS for p in (d / "ir").glob("*.json"))
V3_FIX = ROOT / "tests" / "fixtures" / "ir_v3"


def _v3_schema() -> Draft202012Validator:
    return Draft202012Validator(json.loads((SCHEMA_DIR / "criterion_ir.schema.json").read_text("utf-8")))


def _v3_fixture(name: str) -> CriterionIRv3:
    return CriterionIRv3.model_validate_json((V3_FIX / f"{name}.json").read_text("utf-8"))


def test_inventory_is_not_empty() -> None:
    assert len(RULESET_DIRS) >= 7 and len(IR_FILES) >= 90


@pytest.mark.req("DM-01")
def test_committed_v4_schemas_are_generated_from_the_models() -> None:
    for fname, doc in json_schemas().items():
        path = SCHEMA_DIR / fname
        assert path.read_text("utf-8") == render_schema(doc), f"{fname} is stale: python -m tb_contracts.criterion_ir"
        Draft202012Validator.check_schema(doc)
        assert doc["$id"] == f"https://trialbox.local/schemas/v4/{fname}"
    assert SCHEMA_DIR.name == "v4" and SCHEMA_DIR.parent.name == "schemas"


@pytest.mark.req("DM-02")
@pytest.mark.parametrize("path", IR_FILES, ids=lambda p: p.stem)
def test_every_v1_criterion_upgrades_validates_and_round_trips(path: Path) -> None:
    raw = json.loads(path.read_text("utf-8"))
    v3 = upgrade_v1(raw)
    as_json = v3.model_dump(mode="json", by_alias=True, exclude_unset=True)
    assert as_json["ir_version"] == "3.0.0"
    assert not list(_v3_schema().iter_errors(as_json))
    assert CriterionIRv3.model_validate_json(json.dumps(as_json)) == v3
    back = downgrade_to_v1(v3)
    assert json.dumps(back, sort_keys=True, ensure_ascii=False) == json.dumps(raw, sort_keys=True, ensure_ascii=False)
    validate("criterion_ir", back)
    # the generated v1 model upgrades to the same v3 criterion
    assert upgrade_v1(CriterionIR.model_validate(raw)) == v3


def _render(rid: str, version: str, crit: list[CriterionIR], vsi: ValueSets, lookback: int) -> tuple[str, str]:
    try:
        cql = CqlGenerator(rid, version, vsi, lookback).render(crit)
        sql = SqlGenerator(rid, version, vsi).render(crit)
    except CompileError as exc:  # both sides must fail identically
        return f"CompileError: {exc}", ""
    return cql, sql


@pytest.mark.req("DM-02")
@pytest.mark.parametrize("rdir", RULESET_DIRS, ids=lambda d: d.name)
def test_v1_compiler_output_is_byte_identical_after_round_trip(rdir: Path) -> None:
    m = yaml.safe_load((rdir / "manifest.yaml").read_text("utf-8"))
    raws = [json.loads((rdir / "ir" / f"{cid}.json").read_text("utf-8")) for cid in m["criteria"]]
    vs = {p.stem: json.loads(p.read_text("utf-8")) for p in (rdir / "valuesets").glob("*.json")}
    lookback = int(((m.get("scopes") or {}).get("feas") or {}).get("lookback_months") or 36)
    vsi = ValueSets(m["id"], vs, Terminology())
    before = _render(m["id"], m["version"], [CriterionIR.model_validate(r) for r in raws], vsi, lookback)
    after_ir = [CriterionIR.model_validate(downgrade_to_v1(upgrade_v1(r))) for r in raws]
    after = _render(m["id"], m["version"], after_ir, vsi, lookback)
    assert after[0] == before[0] and after[1] == before[1]
    assert "GENERATED" in before[0] and '"C_' in before[1]  # really compiled, not a CompileError


@pytest.mark.req("DM-02")
@pytest.mark.parametrize("name", sorted(p.stem for p in V3_FIX.glob("*.json")))
def test_v3_only_constructs_validate_and_refuse_down_conversion(name: str) -> None:
    ir = _v3_fixture(name)
    assert not list(_v3_schema().iter_errors(json.loads((V3_FIX / f"{name}.json").read_text("utf-8"))))
    with pytest.raises(NotV1Expressible):
        downgrade_to_v1(ir)


@pytest.mark.req("DM-02")
def test_trap5_atoms_are_expressible() -> None:
    aki = _v3_fixture("STARRT-AKI-INC-04")
    rise, _, delta, urine = aki.atoms
    assert rise.change and rise.change.kind == "ratio" and rise.change.num == 2
    assert delta.change and delta.change.kind == "absolute" and delta.change.unit == "umol/L"
    assert urine.aggregate and urine.aggregate.per_weight_kg and urine.aggregate.over_hours == 12
    bnp = _v3_fixture("EMPULSE-INC-07")
    assert bnp.atoms[0].value_if and bnp.atoms[0].value_if[0].value.num == 2400
    diuretic = _v3_fixture("EMPULSE-INC-08").atoms[0].medication
    assert (
        diuretic and diuretic.route == ["47625008"] and diuretic.dose and len(diuretic.dose.per_ingredient or []) == 3
    )
    primary = _v3_fixture("EMPULSE-INC-02")
    assert primary.atoms[1].diagnosis_role == "primary" and primary.atoms[0].window
    assert primary.atoms[0].window.anchor == "randomization"
    lung = _v3_fixture("LUNG7-INC-06")
    assert lung.atoms[0].lot and lung.macros and lung.macros[0].params.renal
    assert lung.atoms[2].window and lung.atoms[2].window.anchor == "screening"


@pytest.mark.req("DM-02")
def test_invalid_v3_shapes_are_rejected() -> None:
    base = json.loads((V3_FIX / "EMPULSE-INC-07.json").read_text("utf-8"))
    bad_ref = copy.deepcopy(base)
    bad_ref["logic"] = {"op": "or", "args": ["a1", "a9"]}
    bad_if = copy.deepcopy(base)
    bad_if["atoms"][0]["value_if"][0]["if_atom"] = "a7"
    dup = copy.deepcopy(base)
    dup["atoms"][1]["id"] = "a1"
    lot_wrong = copy.deepcopy(base)
    lot_wrong["atoms"][2]["domain"] = "line_of_therapy"
    extra = copy.deepcopy(base)
    extra["atoms"][0]["dose"] = 1
    for doc in (bad_ref, bad_if, dup, lot_wrong, extra):
        with pytest.raises(ValidationError):
            CriterionIRv3.model_validate(doc)


@pytest.mark.req("DM-10")
def test_canonical_hash_ignores_ids_text_and_language() -> None:
    a = _v3_fixture("EMPULSE-INC-07")
    d = a.model_dump(mode="json", by_alias=True, exclude_unset=True)
    other = copy.deepcopy(d)
    other.update(id="HFX-INC-03", ruleset="HFX/v2.0.0", label="NP high")
    other["text"] = {"source": "NT-proBNP ≥ 1600 pg/mL（心房顫動者 ≥ 2400）或 BNP ≥ 400 pg/mL", "lang": "zh-TW"}
    renamed = json.loads(json.dumps(other).replace('"a3"', '"af"').replace('"a1"', '"nt"'))
    assert canonical_hash(a) == canonical_hash(CriterionIRv3.model_validate(other))
    assert canonical_hash(a) == canonical_hash(CriterionIRv3.model_validate(renamed))
    changed = copy.deepcopy(d)
    changed["atoms"][0]["value"]["num"] = 1500
    assert canonical_hash(a) != canonical_hash(CriterionIRv3.model_validate(changed))
    assert canonical_hash(a).startswith("sha256:") and len(canonical_hash(a)) == 71


@pytest.mark.req("DM-10")
def test_canonical_hash_uses_valueset_content_not_names() -> None:
    raw = json.loads(next(p for p in IR_FILES if p.stem == "STARRT-AKI-EXC-01").read_text("utf-8"))
    vs = {"compose": {"include": [{"system": "http://loinc.org", "concept": [{"code": "2823-3"}, {"code": "6298-4"}]}]}}
    vs_reordered = {"name": "other", "compose": {"include": [{"system": "http://loinc.org", "concept": [
        {"code": "6298-4", "display": "K"}, {"code": "2823-3"}]}]}}  # fmt: skip
    a = upgrade_v1(raw)
    renamed = copy.deepcopy(raw)
    renamed["logic"]["valueset"] = "VS_POTASSIUM"
    b = upgrade_v1(renamed)
    assert canonical_hash(a) != canonical_hash(b)  # names only: different ids, different hashes
    h1 = canonical_hash(a, {"VS_SERUM_POTASSIUM": valueset_content_hash(vs)})
    h2 = canonical_hash(b, {"VS_POTASSIUM": valueset_content_hash(vs_reordered)})
    assert h1 == h2


def test_jcs_rfc8785_vectors() -> None:
    assert jcs({"b": [1.0, 1e-7, 0.000001, 1e21, 123.456, -0.0], "a": "€", "é": True, "c": None}) == (
        '{"a":"€","b":[1,1e-7,0.000001,1e+21,123.456,0],"c":null,"é":true}'
    )
    # UTF-16 code-unit order (RFC 8785 §3.2.3): U+FB33 sorts after the surrogate pair of U+1F600
    assert jcs({"\ufb33": 0, "€": 1, "\U0001f600": 2, "\r": 3}) == '{"\\r":3,"€":1,"😀":2,"\ufb33":0}'


def _library_with_rulesets() -> tuple[CriterionLibrary, int]:
    lib = CriterionLibrary()
    n = 0
    for rdir in RULESET_DIRS:
        vs = {p.stem: json.loads(p.read_text("utf-8")) for p in (rdir / "valuesets").glob("*.json")}
        for p in sorted((rdir / "ir").glob("*.json")):
            lib.add(upgrade_v1(json.loads(p.read_text("utf-8"))), seed_source="site", valuesets=vs)
            n += 1
    return lib, n


@pytest.mark.req("DM-11")
def test_library_is_keyed_by_canonical_hash(tmp_path: Path) -> None:
    lib = CriterionLibrary(tmp_path / "library.sqlite")
    a = _v3_fixture("EMPULSE-INC-07")
    rec, created = lib.add(a, seed_source="ctgov", text_source="NCT04157751")
    assert created and rec.status == "draft" and rec.data_class == "D1" and rec.used_by == ["EMPULSE/v3-example"]
    assert rec.canonical_hash == canonical_hash(a) and rec.ir.canonical_hash == rec.canonical_hash
    twin = a.model_copy(update={"id": "HFX-INC-03", "ruleset": "HFX/v2.0.0"})
    rec2, created2 = lib.add(twin, seed_source="site", text_source="HFX protocol")
    assert not created2 and rec2.lib_id == rec.lib_id and lib.count() == 1
    assert lib.used_by("HFX/v2.0.0") == [rec.lib_id] and len(lib.get(rec.lib_id).texts) == 2  # type: ignore[union-attr]
    assert lib.match(twin).match == "exact" and lib.match(_v3_fixture("STARRT-AKI-INC-04")).match == "new"
    approved = lib.approve(rec.lib_id, "G1-0412", "ap_01")
    assert approved.status == "approved" and lib.records("approved") == [approved]
    lib.close()
    reopened = CriterionLibrary(tmp_path / "library.sqlite")  # persisted
    assert reopened.by_hash(rec.canonical_hash) == approved
    dep = reopened.deprecate(rec.lib_id)
    assert reopened.match(twin).match == "new" and dep.status == "deprecated"
    with pytest.raises(LibraryError):
        reopened.approve(rec.lib_id, "G1-0413", "ap_02")
    with pytest.raises(LibraryError):
        reopened.put(dep.model_copy(update={"lib_id": "cl_01JB7AAAAAAAAAAAAAAAAAAAAA"}))  # same hash, other id
    validator = Draft202012Validator(json.loads((SCHEMA_DIR / "criterion_library_record.schema.json").read_text()))
    for doc in reopened.export():
        assert not list(validator.iter_errors(doc))
    reopened.close()


@pytest.mark.req("DM-11")
def test_library_records_hold_no_patient_data_and_need_an_approval() -> None:
    rec = json.loads(CriterionLibrary().add(_v3_fixture("EMPULSE-INC-08"), seed_source="site")[0].model_dump_json())
    for bad in ({"data_class": "D3"}, {"status": "approved"}, {"kind": "exclusion"}):
        with pytest.raises(ValidationError):
            CriterionLibraryRecord.model_validate({**rec, **bad})
    lib = CriterionLibrary()
    with pytest.raises(Exception, match="CHECK constraint"):
        lib.db.execute(
            "INSERT INTO criterion_library VALUES ('cl_X', 'sha256:x', '1.0.0', '3.0.0', 'draft', 'inclusion',"
            " 'structured', 'site', NULL, NULL, NULL, 'D3', '{}', 'now', 'now')"
        )


@pytest.mark.req("DM-11")
def test_every_v1_criterion_loads_into_the_library() -> None:
    lib, n = _library_with_rulesets()
    records = lib.records()
    assert n == len(IR_FILES) and n - 10 <= lib.count() < n  # identical criteria across rulesets share one record
    assert sum(len(r.texts) for r in records) == n  # every source text is kept on its record
    adults = next(r for r in records if "STARRT-AKI" in r.used_by and len(r.used_by) > 1)
    assert {"EMPULSE", "STARRT-AKI", "ONC-OSI"} <= set(adults.used_by)  # "age >= 18" is one library criterion
    assert all(r.valuesets for r in records if any(a.valueset not in (None, "NONE") for a in r.ir.atoms))


def test_chia_seed_is_disabled_until_the_licence_is_confirmed() -> None:
    with pytest.raises(ChiaLicenceUnconfirmed, match="licence"):
        load_chia_seed("chia.zip")
