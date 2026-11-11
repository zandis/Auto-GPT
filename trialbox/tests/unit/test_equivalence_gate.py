"""The CQL/SQL equivalence gate cannot pass empty (T-652, ENG-016).

The gate runs on a DuckDB lake (the real ``sql_evaluations`` query path) and a fake ``FhirEvaluator`` that answers
from a table, so every case the finding names runs in the unit job: 0 patients compared, a sample below the
minimum, a patient one engine lacks, a direction-changing disagreement under the threshold, and a tolerated one. The
service tests use the compiler of ``test_compiler_service`` and show that an empty CQL result fails approval.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import duckdb
import pytest
import tb_contracts as c
from criteria_compiler.compile_cql.generator import CqlGenerator
from criteria_compiler.equivalence import gate
from criteria_compiler.service import Compiler
from tb_contracts import CriterionIR, EquivalenceReport, PatientEvaluation

from tests.unit.test_compiler_service import _approve, _compile, _decisions, env  # noqa: F401 (fixture)

INDEX = date(2026, 10, 5)
COND = {"domain": "condition", "quantifier": "any", "valueset": "VS_A"}
Answers = Mapping[str, Mapping[str, bool | None]]


def _ir(cid: str, kind: str, class_: str = "structured") -> CriterionIR:
    extra = {"note_question": "In the notes?"} if class_ in ("mixed", "note") else {}
    return CriterionIR.model_validate(
        {"id": cid, "ruleset": "EQ", "kind": kind, "class": class_, "text": cid, "logic": COND, **extra}
    )


INC = _ir("EQ-INC-01", "inclusion")
EXC = _ir("EQ-EXC-01", "exclusion")
MIX = _ir("EQ-INC-02", "inclusion", "mixed")
NOTE = _ir("EQ-INC-03", "inclusion", "note")
CRITS = [INC, EXC, MIX, NOTE]
IDS = [INC.id, EXC.id, MIX.id]  # the compiled ones


def _ev(pid: str, engine: str, vals: Mapping[str, bool | None], **kw: Any) -> PatientEvaluation:
    return PatientEvaluation(pid=pid, index_date=INDEX, engine=engine, results=dict(vals), **kw)  # type: ignore[arg-type]


def _same(n: int, vals: Mapping[str, bool | None] | None = None) -> dict[str, dict[str, bool | None]]:
    base = vals or {INC.id: True, EXC.id: False, MIX.id: True}
    return {f"P{i:03d}": dict(base) for i in range(n)}


class DuckLake:
    """The lake surface ``sql_evaluations`` reads, on an in-memory DuckDB holding one row per patient with the
    compiled SQL's ``C_<id>`` and ``E_<id>`` columns."""

    def __init__(self, answers: Answers, ids: list[str] = IDS) -> None:
        self.con = duckdb.connect()
        cols = ", ".join(f'"C_{i}" BOOLEAN, "E_{i}" VARCHAR' for i in ids)
        self.con.execute(f"CREATE TABLE s1 (pid VARCHAR, {cols})")
        for pid, vals in answers.items():
            row: list[Any] = [pid]
            for i in ids:
                row += [vals.get(i), f"Condition/{pid}-{i}|2026-01-01" if vals.get(i) is True else None]
            self.con.execute(f"INSERT INTO s1 VALUES ({', '.join('?' * len(row))})", row)
        self.calls: list[list[Any]] = []

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
        self.calls.append(list(params or []))
        return self.con.execute(sql, params or []).to_arrow_table()


SQL = "SELECT * FROM s1 WHERE len($1::VARCHAR[]) > 0 AND ($2::VARCHAR[] IS NULL OR list_contains($2::VARCHAR[], pid))"


@dataclass
class FakeFhir:
    """``FhirEvaluator.evaluate_many`` answered from a table: a pid the table lacks gets no evaluation."""

    answers: Answers
    asked: list[tuple[str, list[str], date, list[str]]] = field(default_factory=list)

    def evaluate_many(self, library: str, pids: list[str], index_date: date, exprs: list[str]) -> list[Any]:
        self.asked.append((library, list(pids), index_date, list(exprs)))
        return [_ev(p, "cql", self.answers[p], evidence={k: ["Condition/x"] for k in self.answers[p]})
                for p in pids if p in self.answers]  # fmt: skip


def _run(sql_answers: Answers, cql_answers: Answers, **kw: Any) -> EquivalenceReport:
    return gate.run_gate(CRITS, SQL, "EQ", DuckLake(sql_answers), FakeFhir(cql_answers), INDEX, "EQ|1.0.0", **kw)  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------------ run_gate


def test_identical_engines_pass_on_a_full_sample() -> None:
    world = _same(300)
    rep = _run(world, world)
    assert rep.failing == [] and rep.sample_size == 200 and rep.overall_pct == 100.0
    assert rep.per_criterion == dict.fromkeys(IDS, 100.0) and rep.disagreements == []
    assert NOTE.id not in rep.per_criterion  # a note criterion is not compiled, so not compared


def test_the_gate_asks_the_cql_engine_for_the_sampled_patients_and_the_compiled_expressions() -> None:
    world = _same(300)
    fhir = FakeFhir(world)
    lake = DuckLake(world)
    gate.run_gate(CRITS, SQL, "EQ", lake, fhir, INDEX, "EQ|1.0.0")  # type: ignore[arg-type]
    (library, pids, when, exprs) = fhir.asked[0]
    assert library == "EQ" and when == INDEX and len(pids) == 200 == len(set(pids))
    assert exprs == CqlGenerator.expression_names(CRITS)
    assert lake.calls[0] == [[INDEX.isoformat()], None]


def test_an_empty_cql_result_fails_every_compiled_criterion() -> None:
    """ENG-016 acceptance: the CQL engine answers nobody. Before T-652 this gave 100 % and no failing criterion."""
    rep = _run(_same(300), {})
    assert rep.sample_size == 0
    assert rep.failing == sorted(IDS)
    assert rep.overall_pct == 0.0 and set(rep.per_criterion.values()) == {0.0}


def test_an_empty_lake_fails_every_compiled_criterion() -> None:
    rep = _run({}, {})
    assert rep.sample_size == 0 and rep.failing == sorted(IDS)
    assert rep.per_criterion == dict.fromkeys(IDS, 0.0) and rep.disagreements == []


def test_a_small_lake_needs_every_patient_compared() -> None:
    """A lake with 40 patients: the minimum is 40 (min(200, population)); all 40 compared passes."""
    world = _same(40)
    rep = _run(world, world)
    assert rep.sample_size == 40 and rep.failing == []


def test_a_sample_below_the_minimum_fails_every_criterion_even_when_all_agree() -> None:
    """The CQL engine answers 150 of the 200 sampled patients, and agrees on each: the 50 it skipped are not
    silently dropped and the sample is below the minimum, so the gate fails."""
    world = _same(300)
    rep = _run(world, dict(list(world.items())[:150]))
    assert rep.sample_size < 200
    assert rep.failing == sorted(IDS)


def test_compare_minimum_sample_is_its_own_check() -> None:
    world = _same(10)
    sql = [_ev(p, "sql", v) for p, v in world.items()]
    cql = [_ev(p, "cql", v) for p, v in world.items()]
    assert gate.compare(CRITS, cql, sql, 98.0, min_sample=10).failing == []
    assert gate.compare(CRITS, cql, sql, 98.0, min_sample=11).failing == sorted(IDS)
    assert gate.compare(CRITS, cql, sql, 98.0, min_sample=0).failing == []  # 0 reads as 1, never as "none needed"
    assert gate.compare(CRITS, [], [], 98.0, min_sample=0).failing == sorted(IDS)


@pytest.mark.parametrize(
    ("sample", "population", "want"), [(200, 1000, 200), (200, 40, 40), (200, 0, 1), (0, 50, 1), (10, 10, 10)]
)
def test_required_sample(sample: int, population: int, want: int) -> None:
    assert gate.required_sample(sample, population) == want


def test_a_criterion_with_no_patient_compared_fails() -> None:
    """A compiled criterion that neither engine was compared on (no evaluation at all) fails; one compared passes."""
    world = _same(5)
    sql = [_ev(p, "sql", v) for p, v in world.items()]
    cql = [_ev(p, "cql", v) for p, v in world.items()]
    extra = _ir("EQ-EXC-09", "exclusion")
    rep = gate.compare([*CRITS, extra], cql, sql, 98.0, min_sample=5)
    # every patient is compared on every compiled criterion (a missing value is null on both sides): all agree
    assert rep.failing == [] and rep.per_criterion[extra.id] == 100.0
    rep = gate.compare([extra], [], [], 98.0)
    assert rep.failing == [extra.id] and rep.per_criterion == {extra.id: 0.0}


# --------------------------------------------------------------------------------- direction-changing disagreements


def _one_diff(cid: str, cql_value: bool | None, sql_value: bool | None) -> EquivalenceReport:
    """300 identical patients except one, where the two engines differ on ``cid``: 99.5 % agreement, above 98 %."""
    world = _same(300, {INC.id: True, EXC.id: False, MIX.id: True})
    sql = {p: dict(v) for p, v in world.items()}
    cql = {p: dict(v) for p, v in world.items()}
    pid = gate.stratified_sample(gate.sql_evaluations(DuckLake(world), SQL, INDEX), "EQ|1.0.0")[0]  # type: ignore[arg-type]
    sql[pid][cid] = sql_value
    cql[pid][cid] = cql_value
    rep = _run(sql, cql)
    assert rep.sample_size == 200 and rep.per_criterion[cid] == 99.5
    assert rep.disagreements and rep.disagreements[0].pid == pid
    return rep


@pytest.mark.parametrize(
    ("cid", "cql_value", "sql_value"),
    [
        (INC.id, True, False),  # inclusion met vs not met
        (INC.id, False, True),
        (EXC.id, True, False),  # exclusion present vs absent
        (EXC.id, False, True),
        (INC.id, False, None),  # one engine excludes, the other keeps for review
        (INC.id, None, False),
        (EXC.id, True, None),
        (EXC.id, None, True),
        (EXC.id, False, None),  # decided vs null on an exclusion
        (EXC.id, None, False),
        (MIX.id, True, False),
    ],
)
def test_a_direction_changing_disagreement_blocks_at_any_rate(
    cid: str, cql_value: bool | None, sql_value: bool | None
) -> None:
    rep = _one_diff(cid, cql_value, sql_value)
    assert rep.failing == [cid]


@pytest.mark.parametrize(("cql_value", "sql_value"), [(True, None), (None, True)])
def test_a_met_inclusion_against_an_undecided_one_is_under_the_threshold(
    cql_value: bool | None, sql_value: bool | None
) -> None:
    """Both answers keep the patient: one disagreement in 200 is within 98 %."""
    rep = _one_diff(INC.id, cql_value, sql_value)
    assert rep.failing == []
    d = rep.disagreements[0]  # type: ignore[index]
    assert (d.cql, d.sql) == (cql_value, sql_value) and d.criterion_id == INC.id
    assert d.index_date == INDEX.isoformat()


def test_tolerated_disagreements_still_fail_below_the_threshold() -> None:
    """Five undecided-vs-met inclusions in 200 patients: 97.5 % < 98 %."""
    world = _same(300)
    sampled = gate.stratified_sample(gate.sql_evaluations(DuckLake(world), SQL, INDEX), "EQ|1.0.0")  # type: ignore[arg-type]
    cql = {p: dict(v) for p, v in world.items()}
    for pid in sampled[:5]:
        cql[pid][INC.id] = None
    rep = _run(world, cql)
    assert rep.per_criterion[INC.id] == 97.5 and rep.failing == [INC.id]


def test_a_patient_only_one_engine_answered_counts_against_null_and_blocks() -> None:
    """The SQL side lacks a patient the CQL side answered (or the reverse): a disagreement against null, never a
    silent skip. On an exclusion that is direction-changing, so it blocks."""
    world = _same(5)
    sql = [_ev(p, "sql", v) for p, v in world.items()]
    cql = [_ev(p, "cql", v) for p, v in world.items()] + [_ev("ONLY-CQL", "cql", world["P000"])]
    rep = gate.compare(CRITS, cql, sql, 50.0, min_sample=5)
    assert rep.sample_size == 5
    assert rep.failing == sorted(IDS)
    only = [d for d in rep.disagreements or [] if d.pid == "ONLY-CQL"]
    assert {d.criterion_id for d in only} == set(IDS) and all(d.sql is None for d in only)
    rep = gate.compare(CRITS, cql[:5], [*sql, _ev("ONLY-SQL", "sql", world["P000"])], 50.0, min_sample=5)
    assert rep.failing == sorted(IDS)
    assert all(d.cql is None and d.evidence_cql == [] for d in rep.disagreements or [] if d.pid == "ONLY-SQL")


def test_the_kept_disagreements_show_the_blocking_ones_first() -> None:
    """More than 100 disagreements: the list is cut at 100 and the direction-changing one is in it."""
    world = _same(300)
    sampled = gate.stratified_sample(gate.sql_evaluations(DuckLake(world), SQL, INDEX), "EQ|1.0.0")  # type: ignore[arg-type]
    cql = {p: dict(v) for p, v in world.items()}
    for pid in sampled[:-1]:
        cql[pid][INC.id] = None  # tolerated kind, 199 of them
    cql[sampled[-1]][EXC.id] = True  # one that flips the answer, on the last sampled patient
    rep = _run(world, cql)
    assert rep.disagreements is not None and len(rep.disagreements) == 100
    assert rep.disagreements[0].criterion_id == EXC.id and rep.disagreements[0].pid == sampled[-1]
    assert rep.failing == sorted([INC.id, EXC.id])


def test_evidence_travels_into_the_disagreement() -> None:
    sql = [_ev("A", "sql", {INC.id: True}, evidence={INC.id: ["Condition/1|2026-01-01", "Condition/2|2026-02-01"]})]
    cql = [_ev("A", "cql", {INC.id: False}, evidence={INC.id: [f"Condition/{i}" for i in range(9)]})]
    rep = gate.compare([INC], cql, sql, 98.0)
    d = rep.disagreements[0]  # type: ignore[index]
    assert d.evidence_cql == [f"Condition/{i}" for i in range(5)]
    assert d.evidence_sql == "Condition/1|2026-01-01;Condition/2|2026-02-01"
    assert rep.failing == [INC.id] and rep.engine == "hapi-cr $evaluate vs duckdb"


def test_sql_evaluations_reads_results_and_evidence_columns() -> None:
    lake = DuckLake({"A": {INC.id: True, EXC.id: None, MIX.id: False}, "B": {INC.id: False}})
    out = {e.pid: e for e in gate.sql_evaluations(lake, SQL, INDEX, ["A"])}  # type: ignore[arg-type]
    assert set(out) == {"A"} and out["A"].engine == "sql" and out["A"].index_date == INDEX
    assert out["A"].results == {INC.id: True, EXC.id: None, MIX.id: False}
    assert out["A"].evidence == {INC.id: [f"Condition/A-{INC.id}|2026-01-01"]}


def test_stratified_sample_is_deterministic_and_takes_hits() -> None:
    world = {f"P{i:03d}": {INC.id: i % 10 == 0} for i in range(500)}
    evals = [_ev(p, "sql", v) for p, v in world.items()]
    a = gate.stratified_sample(evals, "seed", 20, 20)
    assert a == gate.stratified_sample(list(reversed(evals)), "seed", 20, 20) and len(a) == 40 == len(set(a))
    assert sum(1 for p in a if world[p][INC.id]) >= 20
    assert a != gate.stratified_sample(evals, "other seed", 20, 20)


@pytest.mark.parametrize("n", [0, 1, 99, 100, 150, 199, 200, 201, 260])
def test_the_sample_is_the_planned_size_or_everyone(n: int) -> None:
    """Few hits (here 1 in 50) never leave the sample short of min(200, population), so a lake of 150 patients is
    compared in full and passes the minimum-sample check."""
    evals = [_ev(f"P{i:03d}", "sql", {INC.id: i % 50 == 0}) for i in range(n)]
    got = gate.stratified_sample(evals, "seed")
    assert len(got) == len(set(got)) == min(200, n)
    world = {e.pid: dict(e.results) for e in evals}
    if n:
        rep = gate.run_gate([INC], SQL, "EQ", DuckLake(world, [INC.id]), FakeFhir(world), INDEX, "s")  # type: ignore[arg-type]
        assert rep.sample_size == min(200, n) and rep.failing == []


def test_summary() -> None:
    rep = EquivalenceReport(overall_pct=99.0, per_criterion={"X": 99.0}, failing=["X"], sample_size=200)
    assert gate.summary(rep) == {"overall_pct": 99.0, "failing": ["X"], "sample_size": 200}


def test_unproven() -> None:
    empty = EquivalenceReport(overall_pct=100.0, per_criterion={}, failing=[], sample_size=0)
    assert gate.unproven(empty, CRITS) == sorted(IDS)
    partial = EquivalenceReport(overall_pct=100.0, per_criterion={INC.id: 100.0}, failing=[], sample_size=200)
    assert gate.unproven(partial, CRITS) == sorted([EXC.id, MIX.id])
    assert gate.unproven(partial, [NOTE]) == []


# ------------------------------------------------------------------------------------------------ approval


def _gate_with(report: Callable[[list[CriterionIR]], EquivalenceReport]) -> Any:
    def fn(criteria: list[CriterionIR], sql: str, library: str, index_date: date, seed: str) -> EquivalenceReport:
        return report(criteria)

    return fn


def _empty_cql_gate(criteria: list[CriterionIR]) -> EquivalenceReport:
    """The real gate on a 300-patient DuckDB lake whose CQL engine answers nobody."""
    from criteria_compiler.semantics import compiled

    ids = [x.id for x in compiled(criteria)]
    world = {f"P{i:03d}": dict.fromkeys(ids, True) for i in range(300)}
    return gate.run_gate(criteria, SQL, "GZQO", DuckLake(world, ids), FakeFhir({}), INDEX, "GZQO|1.0.0")  # type: ignore[arg-type]


def test_an_empty_cql_result_fails_approval(env: dict[str, Any]) -> None:  # noqa: F811
    """ENG-016 acceptance: the compiler's approval runs the real gate with a CQL engine that answers nobody; every
    compiled criterion blocks and nothing is tagged."""
    env["deps"].equivalence = _gate_with(_empty_cql_gate)
    res = _compile(env)
    compiled_ids = {x.id for x in res.criteria if x.class_ in ("structured", "mixed")}
    assert compiled_ids and compiled_ids <= set(res.needs_review or [])
    out = _approve(env, _decisions(env["store"], res.review_xlsx_key))
    assert out.status == "needs_review" and out.tag is None
    assert compiled_ids <= set(out.blocking or [])
    assert out.tests is not None and out.tests.sample_size == 0


def test_a_vacuous_report_from_any_source_fails_approval(env: dict[str, Any]) -> None:  # noqa: F811
    """A report that compared no patient and lists nothing as failing (what the gate gave before T-652, and what an
    injected or stored report can still say) blocks every compiled criterion."""
    vacuous = EquivalenceReport(overall_pct=100.0, per_criterion={}, failing=[], sample_size=0, engine="old")
    env["deps"].equivalence = _gate_with(lambda _: vacuous)
    res = _compile(env)
    out = _approve(env, _decisions(env["store"], res.review_xlsx_key))
    compiled_ids = {x.id for x in out.criteria or [] if x.class_ in ("structured", "mixed")}
    assert out.status == "needs_review" and compiled_ids <= set(out.blocking or [])
    assert out.tests is not None and set(out.tests.failing) == compiled_ids
    assert all(out.tests.per_criterion[i] == 0.0 for i in compiled_ids)


def test_a_report_missing_a_criterion_blocks_only_that_criterion(env: dict[str, Any]) -> None:  # noqa: F811
    def partial(criteria: list[CriterionIR]) -> EquivalenceReport:
        ids = [x.id for x in criteria if x.class_ in ("structured", "mixed")]
        return EquivalenceReport(
            overall_pct=100.0, per_criterion=dict.fromkeys(ids[1:], 100.0), failing=[], sample_size=200
        )

    env["deps"].equivalence = _gate_with(partial)
    res = _compile(env)
    first = next(x.id for x in res.criteria if x.class_ in ("structured", "mixed"))
    out = _approve(env, _decisions(env["store"], res.review_xlsx_key))
    assert out.status == "needs_review" and out.blocking == [first]


def test_enforce_leaves_a_sound_report_alone() -> None:
    rep = EquivalenceReport(overall_pct=100.0, per_criterion=dict.fromkeys(IDS, 100.0), failing=[], sample_size=200)
    assert Compiler.enforce(rep, CRITS) is rep
    already = EquivalenceReport(overall_pct=0.0, per_criterion={}, failing=sorted(IDS), sample_size=0)
    assert Compiler.enforce(already, CRITS) is already
    rejected = INC.model_copy(update={"review": c.CriterionReview(status="rejected")})
    partial = EquivalenceReport(overall_pct=100.0, per_criterion={EXC.id: 100.0, MIX.id: 100.0}, failing=[],
                                sample_size=200)  # fmt: skip
    assert Compiler.enforce(partial, [rejected, EXC, MIX]) is partial
