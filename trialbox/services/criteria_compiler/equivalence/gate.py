"""Equivalence gate (SPEC §6.4): CQL (fhir-store) vs SQL (lake) on a stratified 200-patient sample.

Sample = 100 random patients + 100 patients with any criterion true (by SQL), deterministic per ruleset/version.
Per-criterion agreement counts ``null`` as a distinct value; criteria below the threshold are flagged and block
approval.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date
from typing import Any

from lake.client import LakeAPI
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
    return sorted(chosen)


def compare(
    criteria: list[CriterionIR],
    cql: list[PatientEvaluation],
    sql: list[PatientEvaluation],
    threshold_pct: float,
    engine: str = "hapi-cr $evaluate vs duckdb",
) -> EquivalenceReport:
    by_pid = {e.pid: e for e in sql}
    ids = [c.id for c in compiled(criteria)]
    agree = dict.fromkeys(ids, 0)
    total = dict.fromkeys(ids, 0)
    disagreements: list[Disagreement] = []
    for ce in cql:
        se = by_pid.get(ce.pid)
        if se is None:
            continue
        for cid in ids:
            total[cid] += 1
            a, b = ce.results.get(cid), se.results.get(cid)
            if a == b:
                agree[cid] += 1
            elif len(disagreements) < 100:
                disagreements.append(
                    Disagreement(
                        criterion_id=cid,
                        pid=ce.pid,
                        index_date=ce.index_date.isoformat(),
                        cql=a,
                        sql=b,
                        evidence_cql=(ce.evidence or {}).get(cid, [])[:5],
                        evidence_sql=";".join((se.evidence or {}).get(cid, []))[:500],
                    )
                )
    per = {cid: round(100.0 * agree[cid] / total[cid], 2) if total[cid] else 100.0 for cid in ids}
    overall = round(100.0 * sum(agree.values()) / max(1, sum(total.values())), 2)
    failing = sorted(cid for cid, pct in per.items() if pct < threshold_pct)
    sample_size = len({e.pid for e in cql} & set(by_pid))
    return EquivalenceReport(
        overall_pct=overall,
        per_criterion=per,
        failing=failing,
        sample_size=sample_size,
        disagreements=disagreements,
        engine=engine,
    )


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
    return compare(criteria, cql, [e for e in all_sql if e.pid in set(pids)], threshold_pct)


def summary(report: EquivalenceReport) -> dict[str, Any]:
    return {"overall_pct": report.overall_pct, "failing": report.failing, "sample_size": report.sample_size}
