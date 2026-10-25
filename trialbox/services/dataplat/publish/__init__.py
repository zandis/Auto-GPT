"""The publish gate (§5.9.3, DP-20; S1-03).

One decision per publish cycle, the conjunction of the seven conditions of §5.9.3. Conditions that need components
not built yet (3: terminology coverage via ``tb-terminology``; 6: OHDSI DQD via ``tb-omop``) are recorded as
``not_evaluated`` and do not block; every other failed condition holds the cycle. A held cycle publishes nothing,
in any source (no partial publish), and the previous snapshot stays current.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from tb_contracts.landing import (
    GateCondition,
    GateOutcome,
    PublishGateRecord,
    ReasonCode,
    ReconciliationRecord,
    Severity,
    ValidationReport,
)

from dataplat.common import stable_id

IDENTITY_QUARANTINE_MAX = 0.001  # condition 5 (est. default of §5.9.3)


@dataclass
class GateInputs:
    """What the cycle measured. Stages that did not run (because L1 already blocked) leave their field ``None``."""

    cycle_id: str
    reports: Sequence[ValidationReport]
    required_sources: Sequence[str] = ()
    reconciliations: Sequence[ReconciliationRecord] = ()
    validation_error_pct: dict[str, tuple[float, float]] | None = None  # source -> (error_pct, ceiling)
    identity_quarantine: tuple[int, int] | None = None  # (quarantined, total)
    snapshot_balanced: bool | None = None
    stage_errors: list[str] = field(default_factory=list)


def _cond(number: int, name: str, ok: bool | None, detail: str, reasons: list[ReasonCode]) -> GateCondition:
    result: Literal["pass", "fail", "not_evaluated"] = "not_evaluated" if ok is None else "pass" if ok else "fail"
    return GateCondition(number=number, name=name, result=result, detail=detail, reasons=[] if ok else reasons)


def evaluate(inputs: GateInputs, *, decided_at: datetime, current_before: str | None) -> PublishGateRecord:
    reports = list(inputs.reports)
    by_source = {r.source: r for r in reports}
    l1_reasons: list[ReasonCode] = []
    missing = [s for s in inputs.required_sources if s not in by_source]
    for r in reports:
        for t in r.tables:
            l1_reasons += [f.reason for f in t.findings if f.severity == Severity.BLOCKING]
    c1_ok = not l1_reasons and not missing
    c1 = _cond(
        1,
        "no blocking L1 finding for a required source",
        c1_ok,
        "" if c1_ok else f"blocking findings: {sorted({x.value for x in l1_reasons})}; missing sources: {missing}",
        sorted(set(l1_reasons), key=lambda x: x.value) + ([ReasonCode.TABLE_MISSING] if missing else []),
    )
    recs = [r.reconciliation for r in reports] + list(inputs.reconciliations)
    failed_eq = [e for rec in recs for e in rec.equations if e.verdict == "fail"]
    c2 = _cond(
        2,
        "all reconciliation equations hold",
        not failed_eq,
        "; ".join(f"{e.level} {e.table or ''} {e.name}: {e.lhs} vs {e.rhs}" for e in failed_eq[:10]),
        sorted({e.reason for e in failed_eq if e.reason is not None}, key=lambda x: x.value),
    )
    c3 = _cond(3, "terminology coverage ≥ contract floor", None, "tb-terminology not built yet", [])
    if inputs.validation_error_pct is None:
        c4 = _cond(4, "profile-validation error rate ≤ ceiling", None, "L2 did not run", [])
    else:
        over = {s: v for s, v in inputs.validation_error_pct.items() if v[0] > v[1]}
        c4 = _cond(
            4,
            "profile-validation error rate ≤ ceiling",
            not over,
            "; ".join(f"{s}: {v[0]:.2f}% (ceiling {v[1]}%)" for s, v in sorted(inputs.validation_error_pct.items())),
            [ReasonCode.VALIDATION_ERROR_RATE],
        )
    if inputs.identity_quarantine is None:
        c5 = _cond(5, "identity-quarantine share ≤ 0.1 %", None, "L3 did not run", [])
    else:
        q, n = inputs.identity_quarantine
        share = q / n if n else 0.0
        c5 = _cond(
            5,
            "identity-quarantine share ≤ 0.1 %",
            share <= IDENTITY_QUARANTINE_MAX,
            f"{q} of {n} ({share:.3%})",
            [ReasonCode.IDN_QUARANTINE_SHARE],
        )
    c6 = _cond(6, "no blocking DQD check on OMOP staging", None, "tb-omop (DQD) not built yet", [])
    c7 = _cond(
        7,
        "snapshot balance L3 → L4 exact",
        inputs.snapshot_balanced,
        "" if inputs.snapshot_balanced is None else "balanced" if inputs.snapshot_balanced else "unbalanced",
        [ReasonCode.SNAPSHOT_BALANCE],
    )
    conditions = [c1, c2, c3, c4, c5, c6, c7]
    if inputs.stage_errors:
        conditions.append(
            GateCondition(
                number=8,
                name="every stage completed",
                result="fail",
                detail="; ".join(inputs.stage_errors)[:2000],
                reasons=[ReasonCode.STAGE_FAILED],
            )
        )
    blocking = sorted({r for c in conditions if c.result == "fail" for r in c.reasons}, key=lambda x: x.value)
    held = any(c.result == "fail" for c in conditions)
    warnings = sorted(
        {f"{r.source}/{t.table}: {f.reason.value}" for r in reports for t in r.tables for f in t.findings}
        - {
            f"{r.source}/{t.table}: {f.reason.value}"
            for r in reports
            for t in r.tables
            for f in t.findings
            if f.severity == Severity.BLOCKING
        }
    )
    outcome: GateOutcome = "HOLD" if held else "PUBLISH_WITH_WARNINGS" if warnings else "PUBLISH"
    return PublishGateRecord(
        gate_id=stable_id("pg", inputs.cycle_id, [c.model_dump_json() for c in conditions]),
        cycle_id=inputs.cycle_id,
        decided_at=decided_at,
        conditions=conditions,
        outcome=outcome,
        blocking_reasons=blocking,
        warnings=warnings,
        current_before=current_before,
        current_after=current_before,  # the caller sets the new pointer after a publish
    )


__all__ = ["IDENTITY_QUARANTINE_MAX", "GateInputs", "evaluate"]
