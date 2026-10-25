"""Recall certificate for a cascade run (spec v4 §10.14 SAFE-10 … SAFE-14, §6.7 DM-16; CAS-10).

:func:`certify` wires a :class:`~matching.cascade.engine.CascadeResult` to the recall ledger
(``orchestrator.recall.ledger``):

1. the run's exclusions become cells (canonical criterion hash × stratum of the excluding stage). SAFE-13: patients
   unprocessed for budget, patients whose only open items are abstentions or data gaps, and S0 opt-outs are never in
   a cell; they are reported separately;
2. the excluded counts E_c are recorded for the run (they fix the pre-registered α_c = α · E_c/ΣE at the study's
   first certificate);
3. audit samples are drawn per cell with a stored seed, uniformly with replacement (the only weighting implemented,
   §6.7), and labelled by the adjudicator: a truth oracle for synthetic data (the ``human_blinded`` route) or the S4
   re-evaluation (``s4`` route). ``AuditPlan`` simulates the monthly looks of the ledger on the synthetic population;
4. known positives feed line H (historical enrollees, biased) and line B (blinded chart review);
5. :func:`orchestrator.recall.ledger.render_certificate` renders the certificate.

The certificate is **refused** (and the feasibility pack prints the refusal instead, RPT-32) when no bound can be
stated honestly: no exclusions to certify, a cell with exclusions but no audit observation, or no known positive on
either line (AI-13: a recall claim must quote a line's lower bound and name its population).
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from tb_contracts.recall import KnownPositiveLineKind, RecallCell, RecallObservation, Stratum

from matching.cascade.engine import CascadeResult

#: (pid, criterion id) → 1 wrongly excluded, 0 correctly excluded, None: no human label (the S4 label is used)
PairOracle = Callable[[str, str], int | None]
#: pid → True eligible in truth, False not eligible, None unknown
PatientOracle = Callable[[str], bool | None]


@dataclass(frozen=True)
class AuditPlan:
    """Simulated audit draws (SAFE-10: monthly per cell, stored seed). Synthetic data only."""

    looks: int = 12
    per_cell_per_look: int = 25
    blinded_per_look: int = 30
    seed: int = 912733
    planted_miss_rate: float = 0.0  # simulation: chance an S4-route label is a planted miss
    start: datetime = datetime(2025, 10, 31, 12, 0, tzinfo=ZoneInfo("Asia/Taipei"))


@dataclass
class CertificateOutcome:
    status: str  # "issued" | "refused"
    certificate: dict[str, Any] | None
    reasons: list[str]
    cells: dict[str, int]
    never_excluded: dict[str, int]
    ledger_path: Path
    observations: int = 0
    known_positive: dict[str, int] = field(default_factory=dict)

    def as_pack_input(self) -> dict[str, Any]:
        if self.certificate is not None and self.status == "issued":
            return self.certificate
        return {"refused": True, "reasons": self.reasons, "cells": self.cells, "never_excluded": self.never_excluded}


def pid_hash(pid: str) -> str:
    return "sha256:" + hashlib.sha256(f"recall|{pid}".encode()).hexdigest()


def exclusion_cells(res: CascadeResult) -> tuple[dict[RecallCell, list[str]], dict[str, int]]:
    """Cells with their excluded patients, and the SAFE-13 counts that are never exclusions."""
    cells: dict[RecallCell, list[str]] = {}
    never = {"unprocessed": 0, "abstained_only": 0, "data_gap_only": 0, "opted_out": 0}
    for t in res.traces.values():
        if not t.in_scope:
            never["opted_out"] += "opt-out" in t.scope_reason
            continue
        if t.exit_stage is None:
            if t.unprocessed:
                never["unprocessed"] += 1
            elif t.tier == "potential:uncertain":
                never["abstained_only"] += 1
            elif t.tier == "potential:data_gap":
                never["data_gap_only"] += 1
            continue
        cid = t.exit_criterion or ""
        o = t.outcomes.get(cid)
        if o is None or not o.hard or o.stratum is None:
            continue
        cell = RecallCell(canonical_hash=res.criterion_hashes[cid], stratum=Stratum(o.stratum), criterion_type=cid)
        cells.setdefault(cell, []).append(t.pid)
    return cells, never


def certify(
    res: CascadeResult,
    ledger_path: Path,
    *,
    run_id: str,
    period: str,
    plan: AuditPlan,
    pair_oracle: PairOracle | None = None,
    patient_oracle: PatientOracle | None = None,
    historical_enrollees: Sequence[str] = (),
    alpha: float = 0.05,
) -> CertificateOutcome:
    from orchestrator.db_pg import SqliteBackend
    from orchestrator.recall.ledger import RecallLedger, render_certificate

    cells, never = exclusion_cells(res)
    summary = {
        f"{c.stratum.value}|{c.criterion_type}": len(p) for c, p in sorted(cells.items(), key=lambda kv: kv[0].key)
    }
    if not cells:
        return CertificateOutcome("refused", None, ["no exclusions to certify"], summary, never, ledger_path)
    ledger = RecallLedger(SqliteBackend(ledger_path), clock=lambda: plan.start)
    ledger.record_run(
        run_id, res.study_id, f"{res.ruleset}/v{res.ruleset_version}", period, {c: len(p) for c, p in cells.items()}
    )
    rng = random.Random(plan.seed)
    n_obs = 0
    excluded = {t.pid for t in res.in_scope() if t.exit_stage is not None}
    passed = sorted(t.pid for t in res.in_scope() if t.exit_stage is None)
    pop_h = f"historical enrollees of {res.study_id} (synthetic)"
    pop_b = f"blinded chart review of {res.study_id}, cumulative"
    for look in range(plan.looks):
        at = plan.start + timedelta(days=30 * look)
        obs: list[RecallObservation] = []
        for cell in sorted(cells, key=lambda c: c.key):
            pids = sorted(cells[cell])
            for i in range(plan.per_cell_per_look):
                pid = pids[rng.randrange(len(pids))]
                truth = pair_oracle(pid, cell.criterion_type or "") if pair_oracle else None
                route: Literal["human_blinded", "s4"] = "human_blinded" if truth is not None else "s4"
                label = truth if truth is not None else int(rng.random() < plan.planted_miss_rate)
                obs.append(
                    RecallObservation(
                        canonical_hash=cell.canonical_hash,
                        stratum=cell.stratum,
                        draw_id=f"{run_id}:{look:02d}:{cell.stratum.value}:{cell.criterion_type}:{i:03d}",
                        pid_hash=pid_hash(pid),
                        study_id=res.study_id,
                        run_id=f"{run_id}:look{look:02d}",
                        draw_prob=1.0 / len(pids),
                        weight=1.0,
                        label=1 if label else 0,
                        route=route,
                        observed_at=at,
                    )
                )
        n_obs += ledger.append(obs)
        # line B: passed and excluded patients mixed in one blinded queue
        if patient_oracle is not None:
            pool = sorted(excluded) + passed
            for _ in range(min(plan.blinded_per_look, len(pool))):
                pid = pool[rng.randrange(len(pool))]
                if patient_oracle(pid) is True:
                    ledger.add_known_positive(
                        KnownPositiveLineKind.BLINDED_CHART_REVIEW,
                        pop_b,
                        f"b:{pid_hash(pid)}",
                        pid_hash(pid),
                        pid in excluded,
                    )
    for pid in historical_enrollees:
        if pid in res.traces:
            ledger.add_known_positive(
                KnownPositiveLineKind.HISTORICAL_ENROLLEES, pop_h, f"h:{pid_hash(pid)}", pid_hash(pid), pid in excluded
            )
    cert = render_certificate(
        ledger,
        run_id,
        rc_id=f"rc_{hashlib.sha256(run_id.encode()).hexdigest()[:20]}",
        populations={
            KnownPositiveLineKind.HISTORICAL_ENROLLEES: (pop_h, pop_h),
            KnownPositiveLineKind.BLINDED_CHART_REVIEW: (pop_b, pop_b),
        },
        alpha=alpha,
        seed=plan.seed,
        lineage_id=res.ir_hash,
    )
    body = cert.model_dump(mode="json")
    body["never_excluded"] = never  # SAFE-13: reported separately on the certificate
    reasons = [
        f"cell {c.stage.value} {c.canonical_hash[:19]} has exclusions but no audit sample"
        for c in cert.cells
        if c.excluded and c.ledger_sampled == 0
    ]
    kp = {kp.line.value: kp.r for kp in cert.known_positive}
    if all(r == 0 for r in kp.values()):
        reasons.append("no known positive on line H or line B: no recall bound can be quoted (AI-13)")
    return CertificateOutcome("refused" if reasons else "issued", body, reasons, summary, never, ledger_path, n_obs, kp)


__all__ = ["AuditPlan", "CertificateOutcome", "PairOracle", "PatientOracle", "certify", "exclusion_cells", "pid_hash"]
