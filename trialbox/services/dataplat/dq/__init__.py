"""Data-quality expectations in code, Great-Expectations style, Kahn-labelled (§5.10, DP-22, DP-23; S1-03).

Each contract yields one expectation suite (:func:`suite_for`). An expectation names a GX expectation type
(``expect_column_values_to_not_be_null`` …), a Kahn category and subtype, a context, a severity, a reason code and a
``mostly``-style threshold (the largest tolerated share of unexpected rows; ``0`` tolerates none). Row-level
expectations also return the failing row indices, which L1 quarantines with the expectation's reason code.

Not Soda Core (ELv2, DP-23). The Great Expectations package itself is not a dependency yet; the expectation names
and the result shape follow it, so a later swap to real GX suites keeps the reports comparable.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from tb_contracts.landing import DqCheck, ReasonCode, Severity

from dataplat.contracts import ColumnSpec, DataContract
from dataplat.reconcile import field_value, is_null

Row = dict[str, Any]
KahnCategory = Literal["conformance", "completeness", "plausibility"]

_INT = re.compile(r"^-?\d+$")
_DEC = re.compile(r"^-?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$")
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$")


def _is_date(v: str) -> bool:
    try:
        date.fromisoformat(v[:10])
    except ValueError:
        return False
    return len(v) == 10


def value_conforms(value: Any, typ: str) -> bool:
    """Does one non-null value conform to the contract type? CSV cells are strings; NDJSON values are JSON."""
    if isinstance(value, str) and typ in ("string", "integer", "decimal", "date", "timestamp"):
        v = value.strip()
        if typ == "string":
            return True
        if typ == "integer":
            return bool(_INT.match(v))
        if typ == "decimal":
            return bool(_DEC.match(v))
        if typ == "date":
            return _is_date(v)
        return bool(_TS.match(v)) and _is_date(v[:10])
    checks: dict[str, Callable[[Any], bool]] = {
        "string": lambda x: isinstance(x, str),
        "object": lambda x: isinstance(x, dict),
        "array": lambda x: isinstance(x, list),
        "number": lambda x: isinstance(x, int | float) and not isinstance(x, bool),
        "boolean": lambda x: isinstance(x, bool),
        "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
        "decimal": lambda x: isinstance(x, int | float) and not isinstance(x, bool),
    }
    fn = checks.get(typ)
    return fn(value) if fn else False


@dataclass(frozen=True)
class Expectation:
    rule_id: str
    expectation: str
    table: str
    column: str | None
    kahn_category: KahnCategory
    kahn_subtype: str
    severity: Severity
    reason: ReasonCode
    threshold: float = 0.0
    quarantine: bool = True  # failing rows go to the quarantine set
    columns: tuple[str, ...] = ()
    allowed: tuple[str, ...] = ()
    type: str = ""
    min_rows: int = 0


@dataclass(frozen=True)
class CheckResult:
    check: DqCheck
    failing_rows: tuple[int, ...]


def suite_for(contract: DataContract) -> list[Expectation]:
    """The expectation suite of one contract, versioned with it (``<contract_id>@<version>``)."""
    t = contract.table
    out: list[Expectation] = [
        Expectation(
            rule_id=f"{t}.row_count",
            expectation="expect_table_row_count_to_be_between",
            table=t,
            column=None,
            kahn_category="completeness",
            kahn_subtype="atemporal",
            severity=Severity.BLOCKING,
            reason=ReasonCode.VOLUME_ZERO,
            quarantine=False,
            min_rows=contract.volume.min_rows,
        )
    ]
    share = contract.volume.max_quarantine_share
    patient = contract.keys.patient
    if patient:
        out.append(
            Expectation(
                rule_id=f"{t}.{patient}.not_null",
                expectation="expect_column_values_to_not_be_null",
                table=t,
                column=patient,
                kahn_category="completeness",
                kahn_subtype="atemporal",
                severity=Severity.BLOCKING,
                reason=ReasonCode.NULL_IDENTIFIER,
            )
        )
    if contract.keys.primary:
        out.append(
            Expectation(
                rule_id=f"{t}.{'+'.join(contract.keys.primary)}.unique",
                expectation="expect_compound_columns_to_be_unique",
                table=t,
                column="+".join(contract.keys.primary),
                kahn_category="plausibility",
                kahn_subtype="uniqueness",
                severity=Severity.BLOCKING,
                reason=ReasonCode.DUPLICATE_KEY,
                columns=tuple(contract.keys.primary),
            )
        )
    for col in contract.columns:
        out.extend(_column_expectations(t, col, patient, share))
    return out


def _column_expectations(t: str, col: ColumnSpec, patient: str | None, share: float) -> list[Expectation]:
    out: list[Expectation] = []
    if not col.nullable and col.name != patient:
        out.append(
            Expectation(
                rule_id=f"{t}.{col.name}.not_null",
                expectation="expect_column_values_to_not_be_null",
                table=t,
                column=col.name,
                kahn_category="completeness",
                kahn_subtype="atemporal",
                severity=Severity.BLOCKING,
                reason=ReasonCode.REQUIRED_NULL,
                threshold=share,
            )
        )
    if col.type not in ("string", "null"):
        out.append(
            Expectation(
                rule_id=f"{t}.{col.name}.type",
                expectation="expect_column_values_to_be_of_type",
                table=t,
                column=col.name,
                kahn_category="conformance",
                kahn_subtype="value",
                severity=Severity.BLOCKING,
                reason=ReasonCode.TYPE_MISMATCH,
                threshold=share,
                type=col.type,
            )
        )
    if col.enum:
        out.append(
            Expectation(
                rule_id=f"{t}.{col.name}.in_set",
                expectation="expect_column_values_to_be_in_set",
                table=t,
                column=col.name,
                kahn_category="conformance",
                kahn_subtype="value",
                severity=Severity.BLOCKING,
                reason=ReasonCode.ENUM_VIOLATION,
                threshold=share,
                allowed=tuple(col.enum),
            )
        )
    if col.not_future:
        out.append(
            Expectation(
                rule_id=f"{t}.{col.name}.not_future",
                expectation="expect_column_values_to_not_be_in_future",
                table=t,
                column=col.name,
                kahn_category="plausibility",
                kahn_subtype="temporal",
                severity=Severity.WARNING,
                reason=ReasonCode.FUTURE_DATE,
                quarantine=False,
            )
        )
    return out


def _failing(exp: Expectation, rows: Sequence[Row], today: date) -> list[int]:
    col = exp.column
    if exp.expectation == "expect_compound_columns_to_be_unique":
        seen: set[tuple[str, ...]] = set()
        dup: list[int] = []
        for i, r in enumerate(rows):
            key = tuple(str(field_value(r, c)) for c in exp.columns)
            if any(is_null(field_value(r, c)) for c in exp.columns):
                continue  # null keys are the not_null rule's business
            if key in seen:
                dup.append(i)
            seen.add(key)
        return dup
    assert col is not None
    if exp.expectation == "expect_column_values_to_not_be_null":
        return [i for i, r in enumerate(rows) if is_null(field_value(r, col))]
    if exp.expectation == "expect_column_values_to_be_of_type":
        return [
            i for i, r in enumerate(rows) if not is_null(v := field_value(r, col)) and not value_conforms(v, exp.type)
        ]
    if exp.expectation == "expect_column_values_to_be_in_set":
        allowed = set(exp.allowed)
        return [i for i, r in enumerate(rows) if not is_null(v := field_value(r, col)) and str(v) not in allowed]
    if exp.expectation == "expect_column_values_to_not_be_in_future":
        cut = today.isoformat()
        return [i for i, r in enumerate(rows) if not is_null(v := field_value(r, col)) and str(v)[:10] > cut]
    raise ValueError(f"unknown expectation {exp.expectation}")


def run_suite(rows: Sequence[Row], suite: list[Expectation], today: date) -> list[CheckResult]:
    """Run every expectation over the landed rows; results are in suite order."""
    out: list[CheckResult] = []
    n = len(rows)
    for exp in suite:
        if exp.expectation == "expect_table_row_count_to_be_between":
            bad = n < exp.min_rows
            check = DqCheck(
                rule_id=exp.rule_id,
                expectation=exp.expectation,
                kahn_category="completeness",
                kahn_subtype=exp.kahn_subtype,
                table=exp.table,
                field=None,
                threshold=float(exp.min_rows),
                unexpected=int(bad),
                total=n,
                result="fail" if bad else "pass",
                severity=exp.severity,
                reason=exp.reason,
            )
            out.append(CheckResult(check, ()))
            continue
        failing = _failing(exp, rows, today)
        share = len(failing) / n if n else 0.0
        failed = share > exp.threshold if exp.threshold > 0 else bool(failing)
        check = DqCheck(
            rule_id=exp.rule_id,
            expectation=exp.expectation,
            kahn_category=exp.kahn_category,
            kahn_subtype=exp.kahn_subtype,
            table=exp.table,
            field=exp.column,
            threshold=exp.threshold,
            unexpected=len(failing),
            total=n,
            result="fail" if failed else "pass",
            severity=exp.severity,
            reason=exp.reason,
        )
        out.append(CheckResult(check, tuple(failing) if exp.quarantine else ()))
    return out


__all__ = ["CheckResult", "Expectation", "run_suite", "suite_for", "value_conforms"]
