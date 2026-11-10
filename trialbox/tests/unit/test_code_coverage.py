"""Review F3 and F-10 (D-113, D-130): codes inside a grouper's family but off its list, and codes in a system no
ValueSet can read.

* The compiled answers (SQL at runtime, CQL in the compile-time gate) fail closed on an off-list family code: unknown,
  never false; the oracle in ``tests/fixtures/equivalence/offlist/expected.json`` is the one both engines are held
  to (``tests/integration/test_compile_compose.py`` replays it on HAPI).
* The runtime (SQL engine of NAV / MICROBATCH / CASE, and the SCREEN cascade) turns a FALSE inclusion into unknown,
  reason ``unknown_code_system``, when the patient has a record in the atom's window coded in a system nobody can
  read (WHO ICD-10, a MEDIS 病名 code, ICD-9-CM, free text, a medicine without ATC). Exclusions are untouched.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pytest
from criteria_compiler.compile_cql.generator import CqlGenerator, render_common
from criteria_compiler.compile_sql.generator import SqlGenerator
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from matching.cascade.engine import CascadeConfig, run_cascade
from matching.coverage import ICD10CM, UNKNOWN_CODE_SYSTEM, Coverage, GapRow, known_systems, positive_atoms
from orchestrator.scenarios.evaluate import SqlEngine, structured_verdict
from tb_common.reasons import LABELS, Reason
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR

from tests.offlist_fixture import build_lake, compiled, index_date, offlist_ruleset

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def fixture(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    crit, vs, vsi, expected = offlist_ruleset()
    sql = SqlGenerator("OFFL", "1.0.0", vsi).render(crit)
    lake = LakeLocal(build_lake(tmp_path_factory.mktemp("offlist-lake")), HashEmbedder())
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest  # any approved manifest: scopes, routing, ...
    manifest = base.model_copy(update={"id": "OFFL", "library": None, "criteria": [c.id for c in crit]})
    rs = Ruleset(manifest=manifest, criteria=crit, valuesets=vs, sql=sql)
    return {"crit": crit, "vsi": vsi, "expected": expected, "sql": sql, "lake": lake, "rs": rs}


def test_sql_matches_the_oracle_and_fails_closed_on_off_list_codes(fixture: dict[str, Any]) -> None:
    exp = fixture["expected"]
    rows = fixture["lake"].query(fixture["sql"], [[index_date(exp).isoformat()], None]).to_pylist()
    got = {r["pid"]: {k[2:]: v for k, v in r.items() if k.startswith("C_")} for r in rows}
    assert got == compiled(exp)
    assert got["OFF-OFFLIST"]["OFFL-INC-01"] is None and got["ULT-OFFLIST"]["OFFL-INC-02"] is None  # D-113


def test_cql_fails_closed_the_same_way(fixture: dict[str, Any]) -> None:
    """The CQL the gate runs on HAPI carries the same family check as the SQL (it read only the list before)."""
    gen = CqlGenerator("OFFL", "1.0.0", fixture["vsi"])
    cql = gen.render(fixture["crit"])
    for cid in ("OFFL-INC-01", "OFFL-INC-02", "OFFL-INC-03", "OFFL-INC-04", "OFFL-EXC-01"):
        assert f'define "O_{cid}_1"' in cql, cid
    assert "StartsWith(Cd.code.value, 'C5')" in cql and "StartsWith(Cd.code.value, 'M04AA')" in cql
    assert 'if exists ("Q_OFFL-INC-03_1") then false else if exists ("O_OFFL-INC-03_1") then null' in cql
    assert gen.render(fixture["crit"]) == cql  # deterministic

    from criteria_compiler.compile_cql.translator import Translator, available, fhirhelpers_source

    if not available():
        pytest.skip("cql-translator jars not available on the host (.cache/jvm)")
    tr = Translator().translate({"FHIRHelpers": fhirhelpers_source(), "TB_Common": render_common(), gen.library: cql})
    assert gen.library in tr.elm


def test_known_systems_and_positive_atoms(fixture: dict[str, Any]) -> None:
    rs = fixture["rs"]
    assert known_systems(rs.valuesets) == ["http://hl7.org/fhir/sid/icd-10-cm", "http://www.whocc.no/atc"]
    by = {c.id: c for c in fixture["crit"]}
    assert positive_atoms(by["OFFL-INC-01"].logic) and positive_atoms(by["OFFL-INC-02"].logic)
    assert positive_atoms(by["OFFL-INC-03"].logic) == []  # "none": a record makes it falser, not truer
    neg = CriterionIR.model_validate(
        {"id": "X-INC-01", "ruleset": "X", "kind": "inclusion", "class": "structured", "text": "not malignant",
         "logic": {"op": "not", "args": [{"domain": "condition", "valueset": "VS_MALIGNANCY"}]}}
    )  # fmt: skip
    assert positive_atoms(neg.logic) == []


def test_sql_engine_keeps_unreadable_codes_unknown(fixture: dict[str, Any]) -> None:
    exp, rs = fixture["expected"], fixture["rs"]
    ids = exp["criteria"]
    evals = SqlEngine(fixture["lake"]).evaluate(rs, list(exp["compiled"]), index_date(exp), ids)
    want = compiled(exp)
    for pid, vals in want.items():
        changed = exp["runtime"].get(pid, {})
        for cid, v in vals.items():
            ev = evals[pid]
            if cid in changed:
                assert v is False and ev.results[cid] is None, (pid, cid)
                assert (ev.reasons or {})[cid] == UNKNOWN_CODE_SYSTEM
                assert any(x.startswith(changed[cid]) for x in (ev.evidence or {})[cid]), ev.evidence
                c = next(c for c in fixture["crit"] if c.id == cid)
                verdict = structured_verdict(c, ev)
                assert verdict.verdict == "unknown" and verdict.evidence is not None
                assert verdict.evidence.reason == Reason.UNKNOWN_CODE_SYSTEM.value
            else:
                assert ev.results[cid] is v, (pid, cid)
    # an exclusion never changes (FALSE keeps the patient anyway), nor a TRUE "none" inclusion
    assert evals["UNK-WHO"].results["OFFL-EXC-01"] is False and evals["UNK-WHO"].results["OFFL-INC-03"] is True


def test_cascade_s1_does_not_exclude_them(fixture: dict[str, Any]) -> None:
    exp, rs = fixture["expected"], fixture["rs"]
    cfg = CascadeConfig(
        study_id="OFFL",
        run_date=index_date(exp),
        index_mode="single",
        population=sorted(exp["compiled"]),
        semantics="v1",
        snapshot=None,
    )
    res = run_cascade(fixture["lake"], rs, cfg)
    for pid, changed in exp["runtime"].items():
        t = res.traces[pid]
        for cid in changed:
            o = t.outcomes[cid]
            assert o.status == "unknown" and not o.hard and o.reason == UNKNOWN_CODE_SYSTEM, (pid, cid, o)
            assert o.evidence and o.evidence[0]["record"] == changed[cid]
    # before D-130 the WHO-coded patient was out at S1 on OFFL-INC-01; now OFFL-INC-01 is not what excludes them
    assert res.traces["UNK-WHO"].exit_criterion != "OFFL-INC-01"
    assert res.traces["OFF-SKIN"].exit_criterion == "OFFL-INC-01"  # a readable code outside the family still fails
    s1 = res.stage("S1").detail
    assert s1["unknown_code_system"] >= 0


def test_coverage_counts_and_windows(fixture: dict[str, Any]) -> None:
    cov = Coverage.load(fixture["lake"], None, None, known_systems(fixture["rs"].valuesets))
    assert cov.patients("condition") == {"UNK-WHO", "UNK-MEDIS", "UNK-TEXT", "UNK-ICD9", "UNK-OLD"}
    assert cov.patients("medication") == {"ULT-YJ"}
    by = {c.id: c for c in fixture["crit"]}
    assert cov.refs(by["OFFL-INC-04"], "UNK-OLD", date(2026, 10, 5)) == []  # 2020: outside the one-year window
    assert cov.refs(by["OFFL-INC-01"], "UNK-OLD", date(2026, 10, 5)) == ["c-old|2020-01-01"]
    assert cov.refs(by["OFFL-EXC-01"], "UNK-WHO", date(2026, 10, 5)) == []  # exclusions are not widened
    assert set(LABELS[UNKNOWN_CODE_SYSTEM]) == {"en", "ja", "zh-TW"}


def test_scoped_coverage_is_empty_without_patients(tmp_path: Path) -> None:
    class NoLake:
        def query(self, *a: Any, **k: Any) -> Any:  # pragma: no cover - must not be called
            raise AssertionError("no query for an empty scope")

    assert Coverage.load(NoLake(), [], None).rows == {}


# ---------------------------------------------------------------------------------------- T-650 (TB-DR-04 §3.3)
def _inclusion(window: dict[str, Any] | None) -> CriterionIR:
    logic: dict[str, Any] = {"domain": "condition", "quantifier": "any", "valueset": "VS_X"}
    if window:
        logic["window"] = window
    return CriterionIR.model_validate({"id": "X-INC-01", "ruleset": "X", "kind": "inclusion", "class": "structured",
                                       "text": "x", "logic": logic})  # fmt: skip


@pytest.mark.parametrize("window", [None, {"anchor": "index", "from_days": -365, "to_days": 0}])
def test_an_undated_unreadable_row_always_counts(window: dict[str, Any] | None) -> None:
    """U09: a row in an unknown system with no date could be in any window: the FALSE becomes unknown."""
    cov = Coverage({"P": [GapRow("condition", "c-undated", None, "urn:who-icd10")]})
    assert cov.refs(_inclusion(window), "P", date(2026, 10, 5)) == ["c-undated"]


def test_a_diagnosis_with_an_empty_code_is_unreadable() -> None:
    """U10: a diagnosis whose code is empty (an SS-MIX2 病名 with no ICD-10 alternate) cannot answer anything, even in
    a known system; it is listed like a row in an unknown system, and a coded row in the same system is not."""
    con = duckdb.connect()
    con.execute("CREATE TABLE condition (pid VARCHAR, cid VARCHAR, code VARCHAR, system VARCHAR, onset DATE, "
                "recorded DATE)")  # fmt: skip
    con.execute("CREATE TABLE medication (pid VARCHAR, mid VARCHAR, atc VARCHAR, authored DATE)")
    con.execute("INSERT INTO condition VALUES ('EMPTY', 'c-empty', '', ?, DATE '2026-03-01', NULL), "
                "('NULL', 'c-null', NULL, ?, DATE '2026-03-01', NULL), "
                "('CODED', 'c-coded', 'M10.9', ?, DATE '2026-03-01', NULL)", [ICD10CM, ICD10CM, ICD10CM])  # fmt: skip

    class Duck:
        def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
            return con.execute(sql, params or []).to_arrow_table()

    cov = Coverage.load(Duck(), None, None, [ICD10CM])
    assert cov.patients("condition") == {"EMPTY", "NULL"}
    assert cov.refs(_inclusion(None), "EMPTY", date(2026, 10, 5)) == ["c-empty|2026-03-01"]
