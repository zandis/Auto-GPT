"""Equivalence gate (SPEC §6.4): CQL (fhir-store) vs SQL (lake) on a stratified 200-patient sample.

Sample = 100 random patients + 100 patients with any criterion true (by SQL), deterministic per ruleset/version;
too few such patients and the rest of the 200 are drawn from the others.
Per-criterion agreement counts ``null`` as a distinct value; criteria below the threshold are flagged and block
approval. T-652 (ENG-016): the gate cannot pass empty. A criterion with 0 patients compared fails, a sample below
the minimum fails every criterion, and a disagreement that changes the eligibility direction fails its criterion at
any rate.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date
from typing import Any

from lake.client import LakeAPI
from matching.verdict import direction_changes
from tb_common.fhir import FhirEvaluator
from tb_contracts import CriterionIR, Disagreement, EquivalenceReport, PatientEvaluation

from criteria_compiler.compile_cql.generator import CqlGenerator
from criteria_compiler.semantics import compiled


def sql_evaluations(
    lake: LakeAPI, sql: str, index_date: date, pids: list[str] | None = None
) -> list[PatientEvaluation]:
    table = lake.query(sql, [[index_date.isoformat()], pids])
    out = []
    for row in table.to_pylist():
        results = {k[2:]: v for k, v in row.items() if k.startswith("C_")}
        evidence = {k[2:]: [v] for k, v in row.items() if k.startswith("E_") and v}
        out.append(
            PatientEvaluation(pid=row["pid"], index_date=index_date, engine="sql", results=results, evidence=evidence)
        )
    return out


def stratified_sample(evals: list[PatientEvaluation], seed: str, n_random: int = 100, n_hit: int = 100) -> list[str]:
    rng = random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16))
    pids = sorted(e.pid for e in evals)
    chosen = rng.sample(pids, min(n_random, len(pids)))
    taken = set(chosen)
    hits = sorted(e.pid for e in evals if any(v is True for v in e.results.values()) and e.pid not in taken)
    chosen += rng.sample(hits, min(n_hit, len(hits)))
    # T-652: too few hits leave room; it is filled from the other patients, so the sample is min(planned, population)
    # and the minimum-sample check never fails a lake only for having few hits
    rest = sorted(set(pids) - set(chosen))
    chosen += rng.sample(rest, min(n_random + n_hit - len(chosen), len(rest)))
    return sorted(chosen)


def required_sample(sample: int, population: int) -> int:
    """The minimum number of patients both engines must answer for: the planned sample, or everyone when the lake
    holds fewer, and never 0 (ENG-016: a gate that compared nobody has shown nothing)."""
    return max(1, min(sample, population))


def compare(
    criteria: list[CriterionIR],
    cql: list[PatientEvaluation],
    sql: list[PatientEvaluation],
    threshold_pct: float,
    engine: str = "hapi-cr $evaluate vs duckdb",
    min_sample: int = 1,
) -> EquivalenceReport:
    """Per-criterion agreement of the two engines, ``null`` counting as its own value. A criterion fails when:
    no patient was compared for it, its agreement is below ``threshold_pct``, or one disagreement changes the
    eligibility direction (``matching.verdict.direction_changes``), at any rate. Every criterion fails when fewer than
    ``min_sample`` patients were answered by both engines. A patient one engine answered and the other did not counts
    as a disagreement against ``null`` (never silently skipped) but not in ``sample_size``."""
    by_sql = {e.pid: e for e in sql}
    by_cql = {e.pid: e for e in cql}
    crits = compiled(criteria)
    ids = [c.id for c in crits]
    agree = dict.fromkeys(ids, 0)
    total = dict.fromkeys(ids, 0)
    flipped: set[str] = set()
    found: list[tuple[bool, Disagreement]] = []
    for pid in sorted(set(by_sql) | set(by_cql)):
        ce, se = by_cql.get(pid), by_sql.get(pid)
        when = next(e for e in (ce, se) if e is not None).index_date.isoformat()
        for c in crits:
            total[c.id] += 1
            a = ce.results.get(c.id) if ce else None
            b = se.results.get(c.id) if se else None
            if a == b and ce is not None and se is not None:
                agree[c.id] += 1
                continue
            flip = direction_changes(c.kind, a, b) or (ce is None or se is None)
            if flip:
                flipped.add(c.id)
            found.append(
                (
                    flip,
                    Disagreement(
                        criterion_id=c.id,
                        pid=pid,
                        index_date=when,
                        cql=a,
                        sql=b,
                        evidence_cql=((ce.evidence or {}).get(c.id, []) if ce else [])[:5],
                        evidence_sql=";".join((se.evidence or {}).get(c.id, []) if se else [])[:500],
                    ),
                )
            )
    per = {cid: round(100.0 * agree[cid] / total[cid], 2) if total[cid] else 0.0 for cid in ids}
    overall = round(100.0 * sum(agree.values()) / max(1, sum(total.values())), 2)
    sample_size = len(set(by_cql) & set(by_sql))
    if sample_size < max(1, min_sample):
        failing = sorted(ids)
    else:
        failing = sorted(cid for cid in ids if total[cid] == 0 or per[cid] < threshold_pct or cid in flipped)
    # the direction-changing disagreements first, so the 100 kept always show the ones that block
    disagreements = [d for _, d in sorted(found, key=lambda x: not x[0])][:100]
    return EquivalenceReport(
        overall_pct=overall,
        per_criterion=per,
        failing=failing,
        sample_size=sample_size,
        disagreements=disagreements,
        engine=engine,
    )


def unproven(report: EquivalenceReport, criteria: list[CriterionIR]) -> list[str]:
    """Compiled criteria a stored or injected report does not prove equivalent, whatever its ``failing`` says:
    every one when the report compared no patient, else each one the report has no agreement figure for. The
    approval blocks on these as on ``failing`` (ENG-016: an empty result never passes)."""
    ids = [c.id for c in compiled(criteria)]
    if report.sample_size <= 0:
        return sorted(ids)
    return sorted(cid for cid in ids if cid not in report.per_criterion)


def run_gate(
    criteria: list[CriterionIR],
    sql: str,
    library: str,
    lake: LakeAPI,
    fhir: FhirEvaluator,
    index_date: date,
    seed: str,
    threshold_pct: float = 98.0,
    sample: int = 200,
) -> EquivalenceReport:
    all_sql = sql_evaluations(lake, sql, index_date)
    pids = stratified_sample(all_sql, seed, sample // 2, sample - sample // 2)
    exprs = CqlGenerator.expression_names(criteria)
    cql = fhir.evaluate_many(library, pids, index_date, exprs)
    chosen = set(pids)
    return compare(
        criteria,
        cql,
        [e for e in all_sql if e.pid in chosen],
        threshold_pct,
        min_sample=required_sample(sample, len(all_sql)),
    )


def summary(report: EquivalenceReport) -> dict[str, Any]:
    return {"overall_pct": report.overall_pct, "failing": report.failing, "sample_size": report.sample_size}


def without_pseudonyms(report: EquivalenceReport) -> EquivalenceReport:
    """T-206b part 2b (D-862): the report as it is stored (the draft's ``tests/equivalence.json``, kept in the
    criteria library's history): each disagreeing patient is a case label (``case-001``, in the order first named),
    never the pseudonym, also where an evidence string names it. The run itself keeps the pseudonyms (it compares and
    flags in memory); nothing reads a stored disagreement's patient back, so an opt-out has nothing to erase there."""
    labels: dict[str, str] = {}
    out: list[Disagreement] = []
    for d in report.disagreements or []:
        lab = labels.setdefault(d.pid, f"case-{len(labels) + 1:03d}")

        def scrub(text: str) -> str:
            return text.replace(d.pid, lab)  # noqa: B023 - each disagreement scrubs its own patient

        out.append(d.model_copy(update={"pid": lab, "evidence_cql": [scrub(x) for x in d.evidence_cql or []],
                                        "evidence_sql": scrub(d.evidence_sql or "")}))  # fmt: skip
    return report.model_copy(update={"disagreements": out})
