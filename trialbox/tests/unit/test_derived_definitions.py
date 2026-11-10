"""Score definitions from the catalogue and CDAI/SDAI in every engine (WS-04.3, D-189).

* ``libs/tb_common/score_defs.json`` is generated from ``catalogue/scores/*.yaml`` and current; a definition that
  changed under the same version is refused; the same-visit windows and the coefficients the engines use are the
  catalogue's.
* CDAI and SDAI: the published worked examples of ``cdai.yaml`` / ``sdai.yaml`` (and the review's CDAI 14.5) give the
  same value in the Python reference, in the compiled SQL on a small lake, and in the CQL helper functions
  (``TB_Common.CDAI`` / ``SDAI`` and the ``Conv_`` unit functions, evaluated from the rendered CQL text: no CQL engine
  runs on this host). A missing input, a unit that does not fit, or a 0-10 global holding a 0-100 value is no value
  with a reason in every engine, never FALSE.
"""

from __future__ import annotations

import ast
import json
import operator
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.compile_cql.generator import CqlGenerator, render_common
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.terminology.mapper import Concept, Terminology, ValueSets, valueset
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake
from tb_common import derived as d
from tb_common import scores
from tb_contracts import CriterionIR

from tools import gen_score_defs

IDX = date(2026, 11, 9)
LOINC, SCORE = d.LOINC, d.SCORE


# ------------------------------------------------------------------------------------------------ the definitions
def test_generated_definitions_are_current() -> None:
    text = gen_score_defs.render(gen_score_defs.load(), json.loads(gen_score_defs.OUT.read_text("utf-8")))
    assert text == gen_score_defs.OUT.read_text("utf-8"), "run python tools/gen_score_defs.py"
    defs = scores.definitions()
    assert len(defs) == len(list(gen_score_defs.SRC.glob("*.yaml")))
    assert scores.def_version("cdai") == "rheum.cdai@1" and len(scores.definition("cdai")["sha256"]) == 64
    for s in scores.ENGINE:  # every engine score follows a catalogue definition
        assert scores.definition(s)["score_id"] == scores.ENGINE[s]


def test_a_definition_never_changes_under_the_same_version(tmp_path: Path) -> None:
    for f in ("cdai.yaml", "sdai.yaml"):
        (tmp_path / f).write_text((gen_score_defs.SRC / f).read_text("utf-8"), encoding="utf-8")
    before = json.loads(gen_score_defs.render(gen_score_defs.load(tmp_path)))
    edited = (tmp_path / "cdai.yaml").read_text("utf-8").replace("max: 76", "max: 77")
    (tmp_path / "cdai.yaml").write_text(edited, encoding="utf-8")
    with pytest.raises(gen_score_defs.StaleVersion, match="bump its version"):
        gen_score_defs.render(gen_score_defs.load(tmp_path), before)
    (tmp_path / "cdai.yaml").write_text(edited.replace("version: 1", "version: 2"), encoding="utf-8")
    after = json.loads(gen_score_defs.render(gen_score_defs.load(tmp_path), before))
    assert after["definitions"]["rheum.cdai"]["def_version"] == "rheum.cdai@2"


def test_windows_and_coefficients_are_the_catalogues() -> None:
    assert d.SAME_VISIT["cdai"] == ("tjc28", {"sjc28": 0, "ptga10": 0, "evga": 0})
    assert d.SAME_VISIT["sdai"] == ("tjc28", {"sjc28": 0, "ptga10": 0, "evga": 0, "crp": 7})
    # the hand-written DAS28 rule of D-149 says what the catalogue says
    assert d.SAME_VISIT["das28_crp"] == ("tjc28", {"sjc28": 0, "ptga": 0, "crp": 7})
    assert d.SAME_VISIT["das28_esr"] == ("tjc28", {"sjc28": 0, "ptga": 0, "esr": 7})
    assert {**d.SAME_VISIT["das28_crp"][1], **d.SAME_VISIT["das28_esr"][1]} == d.SAME_VISIT["das28"][1]
    ckd = scores.definition("egfr_ckd_epi")["coefficients"]
    assert (ckd["constant"], ckd["kappa_f"], ckd["kappa_m"], ckd["alpha_f"], ckd["alpha_m"]) == (
        d.EGFR["k"], d.EGFR["kappa_f"], d.EGFR["kappa_m"], d.EGFR["alpha_f"], d.EGFR["alpha_m"])  # fmt: skip
    assert (ckd["exp_high"], ckd["age_base"], ckd["female_factor"]) == (
        d.EGFR["exp_hi"], d.EGFR["age_base"], d.EGFR["female"])  # fmt: skip
    jsn = scores.definition("egfr_jsn")["coefficients"]
    assert (jsn["constant"], jsn["scr_exp"], jsn["age_exp"], jsn["female_factor"]) == (
        d.EGFR_JSN["k"], d.EGFR_JSN["scr_exp"], d.EGFR_JSN["age_exp"], d.EGFR_JSN["female"])  # fmt: skip
    esr = scores.definition("das28_esr")["coefficients"]
    crp = scores.definition("das28_crp")["coefficients"]
    assert (esr["tjc"], esr["sjc"], esr["esr"], esr["gh"]) == (d.DAS28["tjc"], d.DAS28["sjc"], d.DAS28["esr_ln"],
                                                                d.DAS28["gh"])  # fmt: skip
    assert (crp["crp"], crp["constant"]) == (d.DAS28["crp_ln"], d.DAS28["crp_const"])


# ------------------------------------------------------------------------------------------------ Python reference
ROLE = {"tjc": ("tjc28", None), "sjc": ("sjc28", None), "ptga": ("ptga10", "{score}"), "evga": ("evga", None),
        "crp_mg_dL": ("crp", "mg/dL")}  # fmt: skip


def _example_obs(inputs: dict[str, Any]) -> dict[str, list[d.Obs]]:
    out: dict[str, list[d.Obs]] = {}
    for role, value in inputs.items():
        comp, unit = ROLE[role]
        out[comp] = [d.Obs(float(value), unit, IDX, f"ex-{comp}")]
    return out


@pytest.mark.parametrize("score", ["cdai", "sdai"])
def test_catalogue_worked_examples_in_python(score: str) -> None:
    examples = scores.worked_examples(score)
    assert len(examples) == 2  # cliot examples, cdai.yaml / sdai.yaml (source_grade calculator)
    for ex in examples:
        res = d.compute(score, _example_obs(ex["inputs"]))
        assert res.reason is None and res.value is not None and round(res.value, 1) == ex["expected"], ex


def test_egfr_catalogue_examples_in_python() -> None:
    for score in ("egfr_ckd_epi", "egfr_jsn"):
        (ex,) = scores.worked_examples(score)
        i = ex["inputs"]
        res = d.compute(score, {"creatinine": [d.Obs(i["scr_mg_dL"], "mg/dL", IDX, "c")]}, age=i["age"],
                        female=i["sex"] == "female")  # fmt: skip
        assert res.value is not None and round(res.value, 1) == ex["expected"]


def test_cdai_sdai_units_scale_and_proposed() -> None:
    def obs(ptga: float, unit: str | None, status: str = "final") -> dict[str, list[d.Obs]]:
        return {"tjc28": [d.Obs(4, None, IDX, "t")], "sjc28": [d.Obs(3, "{count}", IDX, "s")],
                "ptga10": [d.Obs(ptga, unit, IDX, "p", status)], "evga": [d.Obs(3.5, None, IDX, "e")]}  # fmt: skip

    assert d.compute("cdai", obs(4.0, None)).value == 14.5  # the review's example
    assert d.compute("cdai", obs(40, "mm")).value == pytest.approx(14.5)  # a 0-100 mm VAS under the 0-10 item
    assert d.compute("cdai", obs(4, "cm")).value == 14.5  # a 10 cm VAS is 0-10 already
    assert d.compute("cdai", obs(40, None)).reason == "derived_unit:ptga10"  # 40 is not on the 0-10 scale
    assert d.compute("cdai", obs(4, "mg/dL")).reason == "derived_unit:ptga10"
    assert d.compute("cdai", obs(4, None, "proposed")).reason == "derived_missing_input:ptga10"  # never counts
    assert d.compute("cdai", obs(4, None, "confirmed")).value == 14.5
    crp = {"crp": [d.Obs(20, "mg/L", IDX - timedelta(days=3), "c")]}
    assert d.compute("sdai", {**obs(4.0, None), **crp}).value == pytest.approx(16.5)  # 20 mg/L = 2.0 mg/dL
    far = {"crp": [d.Obs(2.0, "mg/dL", IDX - timedelta(days=8), "c")]}
    assert d.compute("sdai", {**obs(4.0, None), **far}).reason == "derived_missing_input:crp"  # not the same visit


@pytest.mark.parametrize("score", ["egfr_ckd_epi", "egfr_jsn", "egfr"])
def test_egfr_impossible_creatinine_or_age_is_no_value(score: str) -> None:
    def cr(v: float) -> dict[str, list[d.Obs]]:
        return {"creatinine": [d.Obs(v, "mg/dL", IDX, "c")]}

    # before: ZeroDivisionError (0 creatinine or JSN age 0), a complex number or TypeError (negative creatinine)
    assert d.compute(score, cr(0.0), age=50, female=True).reason == "derived_unit:creatinine"
    assert d.compute(score, cr(-1.2), age=50, female=False).reason == "derived_unit:creatinine"
    assert d.compute(score, cr(1.1), age=0, female=True).reason == "derived_missing_input:age"
    assert d.compute(score, cr(1.1), age=-3, female=True).reason == "derived_missing_input:age"
    assert d.compute(score, cr(float("nan")), age=50, female=True).reason == "derived_unit:creatinine"
    assert d.compute(score, cr(1.1), age=50, female=True).value is not None


def test_joint_counts_crp_and_esr_ranges() -> None:
    def ra(tjc: float, sjc: float = 3, crp: float = 5.0, esr: float = 20.0) -> dict[str, list[d.Obs]]:
        return {"tjc28": [d.Obs(tjc, None, IDX, "t")], "sjc28": [d.Obs(sjc, None, IDX, "s")],
                "ptga": [d.Obs(40, "mm", IDX, "g")], "ptga10": [d.Obs(4, None, IDX, "p")],
                "evga": [d.Obs(3.5, None, IDX, "e")], "crp": [d.Obs(crp, "mg/L", IDX, "c")],
                "esr": [d.Obs(esr, "mm/h", IDX, "r")]}  # fmt: skip

    # before: a math domain error (sqrt of a negative count, ln of CRP + 1 <= 0)
    for score in ("das28", "das28_crp", "das28_esr", "cdai", "sdai"):
        assert d.compute(score, ra(-1)).reason == "derived_unit:tjc28", score
        assert d.compute(score, ra(29)).reason == "derived_unit:tjc28", score
        assert d.compute(score, ra(4, sjc=28.5)).reason == "derived_unit:sjc28", score
        assert d.compute(score, ra(28, sjc=0)).value is not None, score  # 0 and 28 are in range
    assert d.compute("das28_crp", ra(4, crp=-1.0)).reason == "derived_unit:crp"
    assert d.compute("das28_crp", ra(4, crp=-5.0)).reason == "derived_unit:crp"
    assert d.compute("sdai", ra(4, crp=-0.1)).reason == "derived_unit:crp"
    assert d.compute("das28_crp", ra(4, crp=0.0)).value is not None  # a CRP of 0 is a value
    assert d.compute("das28_esr", ra(4, esr=-2.0)).reason == "derived_unit:esr"
    assert d.compute("das28_esr", ra(4, esr=0.0)).reason == "derived_missing_input:esr"  # the catalogue's zero rule
    assert d.compute("das28", ra(4, esr=-2.0)).reason == "derived_unit:esr"
    asdas = {"basdai_q2": [d.Obs(5, None, IDX, "q2")], "basdai_q6": [d.Obs(3, None, IDX, "q6")],
             "ptga": [d.Obs(40, "mm", IDX, "g")], "basdai_q3": [d.Obs(2, None, IDX, "q3")],
             "crp": [d.Obs(-1.0, "mg/L", IDX, "c")]}  # fmt: skip
    assert d.compute("asdas", asdas).reason == "derived_unit:crp"


# ------------------------------------------------------------------------------------------------ SQL on a lake
def _pat(pid: str) -> dict[str, Any]:
    return {"resourceType": "Patient", "id": pid, "birthDate": "1970-01-01", "gender": "female"}


def _obs(pid: str, comp: str, value: float, unit: str | None, days: int = 0) -> dict[str, Any]:
    system, code = d.CODES[comp]
    q: dict[str, Any] = {"value": value}
    if unit is not None:
        q.update({"unit": unit, "code": unit})
    on = (IDX - timedelta(days=10 + days)).isoformat()
    return {"resourceType": "Observation", "id": f"{pid}-{comp}", "subject": {"reference": f"Patient/{pid}"},
            "code": {"coding": [{"system": system, "code": code}]}, "effectiveDateTime": f"{on}T09:00:00+09:00",
            "valueQuantity": q}  # fmt: skip


def _visit(pid: str, tjc: float, sjc: float, ptga: tuple[float, str | None] | None, evga: float | None,
           crp: tuple[float, str, int] | None = None) -> list[dict[str, Any]]:  # fmt: skip
    out = [_obs(pid, "tjc28", tjc, "{count}"), _obs(pid, "sjc28", sjc, None)]
    if ptga is not None:
        out.append(_obs(pid, "ptga10", ptga[0], ptga[1]))
    if evga is not None:
        out.append(_obs(pid, "evga", evga, "{score}"))
    if crp is not None:
        out.append(_obs(pid, "crp", crp[0], crp[1], crp[2]))
    return out


VISITS = {
    "C-REV": _visit("C-REV", 4, 3, (4.0, None), 3.5),  # review: CDAI 14.5
    "C-27": _visit("C-27", 8, 6, (7, "{score}"), 6),  # cdai.yaml: 27
    "C-15": _visit("C-15", 0, 0, (1, None), 0.5),  # cdai.yaml: 1.5
    "C-MM": _visit("C-MM", 4, 3, (40, "mm"), 3.5),  # 14.5 from a mm VAS
    "C-SCALE": _visit("C-SCALE", 4, 3, (40, None), 3.5),  # 40 on a 0-10 item: no value
    "C-NOEV": _visit("C-NOEV", 4, 3, (4.0, None), None),  # no evaluator global
    "S-31": _visit("S-31", 10, 8, (6, None), 5, (2.0, "mg/dL", 0)),  # sdai.yaml: 31
    "S-31L": _visit("S-31L", 10, 8, (6, None), 5, (20, "mg/L", 2)),  # the same CRP in mg/L
    "S-12": _visit("S-12", 0, 0, (0.5, None), 0.5, (0.2, "mg/dL", 0)),  # sdai.yaml: 1.2
    "S-FAR": _visit("S-FAR", 10, 8, (6, None), 5, (2.0, "mg/dL", 30)),  # CRP of another visit
    "S-BADU": _visit("S-BADU", 10, 8, (6, None), 5, (2.0, "mmol/L", 0)),  # CRP unit that does not fit
}


@pytest.fixture(scope="module")
def lake(tmp_path_factory: pytest.TempPathFactory) -> LakeLocal:
    tmp = tmp_path_factory.mktemp("cdai")
    nd = tmp / "nd"
    nd.mkdir()
    (nd / "Patient.ndjson").write_text("\n".join(json.dumps(_pat(p)) for p in VISITS) + "\n")
    obs = [o for os in VISITS.values() for o in os]
    (nd / "Observation.ndjson").write_text("\n".join(json.dumps(o) for o in obs) + "\n")
    Lake(tmp / "lake", "Asia/Tokyo").rebuild("2026-11-09", HashEmbedder(), nd)
    return LakeLocal(tmp / "lake", HashEmbedder(), "Asia/Tokyo")


def _python(pid: str, score: str) -> d.Derived:
    rows: dict[str, list[d.Obs]] = {}
    for o in VISITS[pid]:
        comp = next(c for c, sc in d.CODES.items() if sc == (o["code"]["coding"][0]["system"],
                                                         o["code"]["coding"][0]["code"]))  # fmt: skip
        q = o["valueQuantity"]
        rows.setdefault(comp, []).append(
            d.Obs(q["value"], q.get("code"), date.fromisoformat(o["effectiveDateTime"][:10]), o["id"])
        )
    return d.compute(score, rows)


def _crit(cid: str, score: str, op: str, num: float, kind: str = "inclusion") -> CriterionIR:
    logic = {"domain": "observation", "derived": score, "quantifier": "latest",
             "valueset": f"VS_{score.upper()}_COMPONENTS", "value": {"op": op, "num": num}}  # fmt: skip
    return CriterionIR.model_validate({"id": cid, "ruleset": "DER", "kind": kind, "class": "structured",
                                       "text": cid, "logic": logic})  # fmt: skip


def _vsets(*names: str) -> ValueSets:
    vs = {
        f"VS_{s.upper()}_COMPONENTS": valueset(
            "DER", f"VS_{s.upper()}_COMPONENTS", s, [Concept(*d.CODES[c], c) for c in d.COMPONENTS[s]], "1.0.0"
        )
        for s in names
    }
    return ValueSets("DER", vs, Terminology())


def _sql(lake: LakeLocal, crits: list[CriterionIR]) -> dict[str, dict[str, Any]]:
    sql = SqlGenerator("DER", "1.0.0", _vsets("cdai", "sdai")).render(crits)
    return {r["pid"]: r for r in lake.query(sql, [[IDX.isoformat()], list(VISITS)]).to_pylist()}


@pytest.mark.parametrize("score", ["cdai", "sdai"])
def test_sql_agrees_with_python(lake: LakeLocal, score: str) -> None:
    pids = [p for p in VISITS if p.startswith("C-" if score == "cdai" else "S-")]
    for pid in pids:
        py = _python(pid, score)
        if py.value is None:
            rows = _sql(lake, [_crit("DER-INC-01", score, ">", 0), _crit("DER-EXC-01", score, ">", 0, "exclusion")])
            r = rows[pid]
            assert r["C_DER-INC-01"] is None and r["C_DER-EXC-01"] is None, pid  # unknown, never FALSE
            assert r["E_DER-INC-01"] == py.reason, pid
            continue
        rows = _sql(lake, [_crit("DER-INC-01", score, ">=", py.value - 1e-9),
                           _crit("DER-INC-02", score, "<=", py.value + 1e-9)])  # fmt: skip
        assert rows[pid]["C_DER-INC-01"] is True and rows[pid]["C_DER-INC-02"] is True, (pid, py.value)
    expected = {"C-REV": 14.5, "C-27": 27, "C-15": 1.5, "C-MM": 14.5, "S-31": 31, "S-31L": 31, "S-12": 1.2}
    for pid, want in expected.items():
        if pid in pids:
            got = _python(pid, score).value
            assert got is not None and round(got, 1) == want, pid
    reasons = {"C-SCALE": "derived_unit:ptga10", "C-NOEV": "derived_missing_input:evga",
               "S-FAR": "derived_missing_input:crp", "S-BADU": "derived_unit:crp"}  # fmt: skip
    for pid, why in reasons.items():
        if pid in pids:
            assert _python(pid, score).reason == why


# ------------------------------------------------------------------------------------------------ CQL
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def _arith(expr: str, env: dict[str, float]) -> float:
    """Evaluate a CQL arithmetic body (``+ - * /``, names, decimals) with Python numbers; nothing else is allowed."""

    def ev(n: ast.AST) -> float:
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return float(_OPS[type(n.op)](ev(n.left), ev(n.right)))
        if isinstance(n, ast.Name):
            return env[n.id]
        if isinstance(n, ast.Constant) and isinstance(n.value, int | float):
            return float(n.value)
        raise ValueError(f"not plain arithmetic: {ast.dump(n)}")

    return ev(ast.parse(expr, mode="eval").body)


def _cql_function(common: str, name: str) -> tuple[list[str], str]:
    m = re.search(rf'define function "{name}"\((.*?)\):\n(.*?)(?:\n\n|\n/\*|\ndefine |\Z)', common, re.S)
    assert m is not None, name
    params = [p.strip().split(" ")[0] for p in m.group(1).split(",")]
    return params, " ".join(m.group(2).split())


def _cql_conv(common: str, comp: str, value: float, unit: str | None) -> float | None:
    """``TB_Common.Conv_<comp>`` read from the rendered CQL: its unit arms and its scale."""
    _, body = _cql_function(common, f"Conv_{comp}")
    u = d.norm_unit(unit)
    unitless = re.search(r'"UnitOf"\(O\) in \{ (.*?) \} then "ObsValue"\(O\) else null$', body)
    if unitless is not None:  # counts and scores: the value as it is when the unit is one of the allowed
        return value if u in re.findall(r"'([^']*)'", unitless.group(1)) else None
    arms = dict(re.findall(r"when '([^']*)' then \"ObsValue\"\(O\) \* ([0-9.]+)", body))
    if u not in arms:
        return None
    v = value * float(arms[u])
    scale = (
        re.search(r", ([0-9.]+), ([0-9.]+)\)$", body)
        if body.startswith('if O is null then null else "InScale"')
        else None
    )
    if scale is not None and not float(scale.group(1)) <= v <= float(scale.group(2)):
        return None
    return v


@pytest.mark.parametrize("score", ["cdai", "sdai"])
def test_cql_helpers_agree_with_python(score: str) -> None:
    common = render_common()
    params, body = _cql_function(common, score.upper())
    pids = [p for p in VISITS if p.startswith("C-" if score == "cdai" else "S-")]
    for pid in pids:
        py = _python(pid, score)
        picked = py.inputs
        conv = {c: (_cql_conv(common, c, picked[c].value or 0, picked[c].unit) if c in picked else None)
                for c in d.COMPONENTS[score]}  # fmt: skip
        if py.value is None:  # CQL null arithmetic: any null input is a null score
            assert any(v is None for v in conv.values()), pid
            continue
        env = dict(zip(params, [conv[c] for c in d.COMPONENTS[score]], strict=True))
        assert _arith(body, env) == pytest.approx(py.value), pid  # type: ignore[arg-type]


def test_cql_names_cdai_sdai_and_translates() -> None:
    crits = [_crit("DER-INC-01", "cdai", ">", 10), _crit("DER-INC-02", "sdai", "<=", 3.3)]
    gen = CqlGenerator("DER", "1.0.0", _vsets("cdai", "sdai"))
    cql = gen.render(crits)
    assert "TB.CDAI(" in cql and "TB.SDAI(" in cql and 'TB."Conv_ptga10"' in cql and 'TB."Conv_evga"' in cql
    assert 'TB.SameVisit(X, "L_DER-INC-02_1_tjc28", 7)' in cql  # the CRP within 7 days of the joint count
    common = render_common()
    assert '"InScale"(case "UnitOf"(O)' in common
    from criteria_compiler.compile_cql.translator import Translator, available, fhirhelpers_source

    if not available():
        pytest.skip("cql-translator jars not available on the host (.cache/jvm)")
    tr = Translator().translate({"FHIRHelpers": fhirhelpers_source(), "TB_Common": common, gen.library: cql})
    assert gen.library in tr.elm and "TB_Common" in tr.elm


def test_cdai_sdai_criteria_round_trip_to_pinned_calculators() -> None:
    from tb_contracts.criterion_ir import downgrade_to_v1, upgrade_v1

    for score in ("cdai", "sdai"):
        v3 = upgrade_v1(_crit("DER-INC-01", score, ">", 10))
        assert f'"{score}@1.0.0"' in v3.model_dump_json()
        assert downgrade_to_v1(v3)["logic"]["derived"] == score
