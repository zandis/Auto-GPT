"""Reconciliation against control totals and the internal stage equations (§5.9.1, §5.9.2, DP-19; S1-03).

Source → L0 compares the totals the source took with the extract (``count(*)``, ``count(distinct patient_key)``,
``max(delta)``) with the same totals computed from the landed bytes; it is exact. The internal equations
(L0 → L1 … L3 → L4) are exact too. Every equation is kept in a ``reconciliation_record``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from tb_contracts.landing import ControlTotals, Equation, ReasonCode, ReconciliationRecord

from dataplat.common import stable_id

Row = dict[str, Any]


def field_value(row: Row, name: str) -> Any:
    """A column value; dotted names walk nested objects (NDJSON rows, e.g. ``subject.reference``)."""
    if name in row:
        return row[name]
    node: Any = row
    for part in name.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def is_null(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def compute_totals(rows: Iterable[Row], patient_column: str | None, delta_column: str | None) -> ControlTotals:
    n = 0
    patients: set[str] = set()
    max_delta: str | None = None
    for row in rows:
        n += 1
        if patient_column:
            p = field_value(row, patient_column)
            if not is_null(p):
                patients.add(str(p).strip())
        if delta_column:
            d = field_value(row, delta_column)
            if not is_null(d) and (max_delta is None or str(d) > max_delta):
                max_delta = str(d)
    return ControlTotals(
        rows=n,
        distinct_patients=len(patients) if patient_column else None,
        max_delta=max_delta,
        patient_column=patient_column,
        delta_column=delta_column,
    )


def source_vs_landed(table: str, source: ControlTotals | None, landed: ControlTotals) -> list[Equation]:
    """Source → L0 equations for one table. Missing source totals are themselves a failed equation."""
    if source is None:
        return [
            Equation(
                level="source→L0",
                name="control_totals_present",
                table=table,
                lhs=None,
                rhs=landed.rows,
                verdict="fail",
                reason=ReasonCode.CONTROL_TOTALS_MISSING,
            )
        ]
    eqs = [
        Equation(
            level="source→L0",
            name="count(*)",
            table=table,
            lhs=source.rows,
            rhs=landed.rows,
            diff=landed.rows - source.rows,
            verdict="pass" if source.rows == landed.rows else "fail",
            reason=None if source.rows == landed.rows else ReasonCode.RECON_ROW_COUNT,
        )
    ]
    if source.distinct_patients is not None:
        ok = source.distinct_patients == landed.distinct_patients
        eqs.append(
            Equation(
                level="source→L0",
                name=f"count(distinct {source.patient_column or 'patient'})",
                table=table,
                lhs=source.distinct_patients,
                rhs=landed.distinct_patients,
                diff=(landed.distinct_patients or 0) - source.distinct_patients,
                verdict="pass" if ok else "fail",
                reason=None if ok else ReasonCode.RECON_DISTINCT_PATIENT,
            )
        )
    if source.max_delta is not None or source.delta_column:
        ok = source.max_delta == landed.max_delta
        eqs.append(
            Equation(
                level="source→L0",
                name=f"max({source.delta_column or 'delta'})",
                table=table,
                lhs=source.max_delta,
                rhs=landed.max_delta,
                verdict="pass" if ok else "fail",
                reason=None if ok else ReasonCode.RECON_MAX_DELTA,
            )
        )
    return eqs


def exact(level: str, name: str, lhs: int, rhs: int, table: str | None = None) -> Equation:
    """An internal equation (``lhs == rhs`` exactly); a difference is ``RECON_INTERNAL`` (DP-19)."""
    ok = lhs == rhs
    return Equation(
        level=level,
        name=name,
        table=table,
        lhs=lhs,
        rhs=rhs,
        diff=rhs - lhs,
        verdict="pass" if ok else "fail",
        reason=None if ok else ReasonCode.RECON_INTERNAL,
    )


def record(scope: str, ref: str, equations: list[Equation]) -> ReconciliationRecord:
    eqs = sorted(equations, key=lambda e: (e.level, e.table or "", e.name))
    rid = stable_id("rec", scope, ref, [e.model_dump_json() for e in eqs])
    return ReconciliationRecord(record_id=rid, scope="cycle" if scope == "cycle" else "batch", ref=ref, equations=eqs)


__all__ = ["compute_totals", "exact", "field_value", "is_null", "record", "source_vs_landed"]
