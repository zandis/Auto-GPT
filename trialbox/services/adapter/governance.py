"""The ingest controls moved from the retired data platform into the adapter (D-370, D-381; T-659b, DATA-002).

* **Contracts.** A YAML contract per source table (``contracts/<source>/<table>.yaml``): columns, types, non-null
  keys, enumerations, the patient key, the primary key, the largest quarantined share. A mapped table without a
  contract holds the night (``CONTRACT_MISSING``); a contract column missing from the file holds it
  (``SCHEMA_DRIFT_BREAKING``); a column the contract does not know is a warning (``SCHEMA_DRIFT_ADDITIVE``).
* **Row quarantine.** Each row is checked against its contract (null patient key, duplicate key, null required
  column, type, enumeration). A failing row is set aside with its reason codes, counted, and never mapped. Its values
  are not copied anywhere: the report keeps only counts by reason and keyed hashes of the primary keys. A blocking
  check that fails, or a quarantined share over the contract's maximum, holds the night.
* **Reconciliation.** When the export ships ``control_totals.json`` (``tb_testkit.defects`` writes the format), each
  table's ``count(*)`` and ``count(distinct patient)`` must equal what was read (``RECON_ROW_COUNT``,
  ``RECON_DISTINCT_PATIENT``). Without the file the condition is ``not_evaluated``.
* **One gate record per night.** :func:`gate_record` folds every reason the adapter can hold a night for (the
  contracts, the reconciliation, the file quarantine of T-615b, the completeness gate of T-611, validation, the
  lake's refusal) into one :class:`~tb_contracts.landing.PublishGateRecord`, written as ``gate.json`` beside the
  night's report and as ``<lake>/gates/<night>.json``.
* **Lineage.** :func:`lineage` is the night's ``lineage.json``: the input files and their sha256, the mapping file
  and its sha256, the snapshot written, the gate's outcome. No row and no chart number.

The pseudonym rule does not change: ``pid = HMAC-SHA-256(site key, chart number)`` (D-370 §2).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field
from tb_contracts.dataclass import DataClass
from tb_contracts.landing import (
    ConnectorKind,
    ControlTotals,
    DqCheck,
    Equation,
    Finding,
    GateCondition,
    GateOutcome,
    PublishGateRecord,
    ReasonCode,
    ReconciliationRecord,
    Severity,
    TableValidation,
    ValidationReport,
)

CONTRACTS_ROOT = Path(__file__).resolve().parent / "contracts"
DEMO_HIS = CONTRACTS_ROOT / "demo_his"
MIMIC_FHIR = CONTRACTS_ROOT / "mimic_fhir"
CONTROL_TOTALS_FILE = "control_totals.json"  # the export's own totals (as tb_testkit.defects writes them)
GATE = "gate.json"  # beside the night's ingest_report.json
LINEAGE = "lineage.json"  # beside the night's completeness.json
CONTRACT_REPORT = "contract_report.json"  # the night's per-table contract checks (counts only)
GATES_DIR = "gates"  # <lake>/gates/<night>.json: one gate record per night

Row = dict[str, Any]
ColumnType = Literal[
    "string", "integer", "decimal", "date", "timestamp", "object", "array", "number", "boolean", "null"
]
Privacy = Literal["direct_identifier", "quasi_identifier", "sensitive", "free_text", "none"]


# ------------------------------------------------------------------------------------------------ contracts
class ColumnSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    type: ColumnType
    nullable: bool = True
    unique: bool = False
    privacy: Privacy = "none"
    enum: list[str] | None = None
    not_future: bool = False


class Keys(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    primary: list[str] = Field(default_factory=list)
    patient: str | None = Field(default=None, description="patient key column (dotted path for NDJSON)")
    watermark: str | None = Field(default=None, description="delta column for max(delta) control totals")


class Volume(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    min_rows: int = 1
    max_quarantine_share: float = 0.005


class DataContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_id: str
    version: str
    source: str
    table: str
    kind: ConnectorKind = ConnectorKind.FILE_DROP
    format: Literal["csv", "ndjson"] = "csv"
    owner: str = "Hospital (controller)"
    steward: str
    change_channel: str
    latency_class: Literal["real_time", "intraday", "daily", "periodic", "static"] = "daily"
    data_class: DataClass = DataClass.D4
    keys: Keys = Field(default_factory=Keys)
    columns: list[ColumnSpec]
    volume: Volume = Field(default_factory=Volume)
    control_totals: list[str] = Field(default_factory=lambda: ["count", "count_distinct_patient", "max_watermark"])
    required_for_publish: bool = True
    validation_max_pct: float = Field(default=0.5, description="profile-validation error ceiling, percent")
    change_policy: dict[str, str] = Field(default_factory=lambda: {"additive": "auto", "breaking": "g0_major"})

    def column(self, name: str) -> ColumnSpec | None:
        return next((c for c in self.columns if c.name == name), None)


def load_contract(path: Path) -> DataContract:
    doc: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: not a contract document")
    return DataContract.model_validate(doc)


def load_contracts(directory: Path) -> dict[str, DataContract]:
    """All contracts of one source directory, keyed by table (the source file's name)."""
    out: dict[str, DataContract] = {}
    for p in sorted(directory.glob("*.yaml")):
        c = load_contract(p)
        if c.table in out:
            raise ValueError(f"{directory}: two contracts for table {c.table!r}")
        out[c.table] = c
    return out


def contracts_dir(value: str | None) -> Path | None:
    """``TB_DATA_CONTRACTS``: a built-in set's name (``demo_his``) or a folder of contracts; empty is None."""
    raw = (value or "").strip()
    if not raw:
        return None
    builtin = CONTRACTS_ROOT / raw
    return builtin if "/" not in raw and builtin.is_dir() else Path(raw)


def classify_drift(contract: DataContract, columns: Iterable[str]) -> tuple[str, list[Finding]]:
    """The file's header against the contract: ``none``, ``additive`` (a new column: a warning) or ``breaking`` (a
    contract column missing: holds). A changed type shows in the row checks (``TYPE_MISMATCH``)."""
    seen = set(columns)
    t = contract.table
    out: list[Finding] = []
    for spec in contract.columns:
        if spec.name not in seen and (contract.format == "csv" or not spec.nullable):
            out.append(
                Finding(
                    table=t,
                    reason=ReasonCode.SCHEMA_DRIFT_BREAKING,
                    severity=Severity.BLOCKING,
                    rule_id=f"{t}.schema",
                    detail=f"column {spec.name} missing",
                )
            )
    for name in sorted(seen - {c.name for c in contract.columns}):
        out.append(
            Finding(
                table=t,
                reason=ReasonCode.SCHEMA_DRIFT_ADDITIVE,
                severity=Severity.WARNING,
                rule_id=f"{t}.schema",
                detail=f"new column {name}",
            )
        )
    if any(f.reason == ReasonCode.SCHEMA_DRIFT_BREAKING for f in out):
        return "breaking", out
    return ("additive" if out else "none"), out


# ------------------------------------------------------------------------------------------------ row checks
_INT = re.compile(r"^-?\d+$")
_DEC = re.compile(r"^-?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$")
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$")


def _is_date(v: str) -> bool:
    try:
        date.fromisoformat(v[:10])
    except ValueError:
        return False
    return len(v) == 10


def is_null(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def field_value(row: Row, name: str) -> Any:
    """A column value; dotted names walk nested objects."""
    if name in row:
        return row[name]
    node: Any = row
    for part in name.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def value_conforms(value: Any, typ: str) -> bool:
    """Does one non-null value conform to the contract type? CSV cells are strings; JSON values are JSON."""
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
class _Rule:
    rule_id: str
    expectation: str
    column: str | None
    kahn: Literal["conformance", "completeness", "plausibility"]
    subtype: str
    severity: Severity
    reason: ReasonCode
    threshold: float = 0.0  # the largest tolerated share of failing rows (0: none)
    quarantine: bool = True
    columns: tuple[str, ...] = ()
    allowed: tuple[str, ...] = ()
    type: str = ""


def rules_for(contract: DataContract) -> list[_Rule]:
    """The contract's row checks, Kahn-labelled, in the order they run."""
    t, share, patient = contract.table, contract.volume.max_quarantine_share, contract.keys.patient
    out: list[_Rule] = []
    if patient:
        out.append(
            _Rule(
                f"{t}.{patient}.not_null",
                "expect_column_values_to_not_be_null",
                patient,
                "completeness",
                "atemporal",
                Severity.BLOCKING,
                ReasonCode.NULL_IDENTIFIER,
            )
        )
    if contract.keys.primary:
        pk = tuple(contract.keys.primary)
        out.append(
            _Rule(
                f"{t}.{'+'.join(pk)}.unique",
                "expect_compound_columns_to_be_unique",
                "+".join(pk),
                "plausibility",
                "uniqueness",
                Severity.BLOCKING,
                ReasonCode.DUPLICATE_KEY,
                columns=pk,
            )
        )
    for col in contract.columns:
        if not col.nullable and col.name != patient:
            out.append(
                _Rule(
                    f"{t}.{col.name}.not_null",
                    "expect_column_values_to_not_be_null",
                    col.name,
                    "completeness",
                    "atemporal",
                    Severity.BLOCKING,
                    ReasonCode.REQUIRED_NULL,
                    share,
                )
            )
        if col.type not in ("string", "null"):
            out.append(
                _Rule(
                    f"{t}.{col.name}.type",
                    "expect_column_values_to_be_of_type",
                    col.name,
                    "conformance",
                    "value",
                    Severity.BLOCKING,
                    ReasonCode.TYPE_MISMATCH,
                    share,
                    type=col.type,
                )
            )
        if col.enum:
            out.append(
                _Rule(
                    f"{t}.{col.name}.in_set",
                    "expect_column_values_to_be_in_set",
                    col.name,
                    "conformance",
                    "value",
                    Severity.BLOCKING,
                    ReasonCode.ENUM_VIOLATION,
                    share,
                    allowed=tuple(col.enum),
                )
            )
        if col.not_future:
            out.append(
                _Rule(
                    f"{t}.{col.name}.not_future",
                    "expect_column_values_to_not_be_in_future",
                    col.name,
                    "plausibility",
                    "temporal",
                    Severity.WARNING,
                    ReasonCode.FUTURE_DATE,
                    quarantine=False,
                )
            )
    return out


def _failing(rule: _Rule, rows: Sequence[Row], today: date) -> list[int]:
    col = rule.column or ""
    if rule.columns:
        seen: set[tuple[str, ...]] = set()
        dup: list[int] = []
        for i, r in enumerate(rows):
            if any(is_null(field_value(r, c)) for c in rule.columns):
                continue  # a null key is the not-null rule's business
            key = tuple(str(field_value(r, c)) for c in rule.columns)
            if key in seen:
                dup.append(i)
            seen.add(key)
        return dup
    if rule.expectation == "expect_column_values_to_not_be_null":
        return [i for i, r in enumerate(rows) if is_null(field_value(r, col))]
    if rule.expectation == "expect_column_values_to_be_of_type":
        return [
            i for i, r in enumerate(rows) if not is_null(v := field_value(r, col)) and not value_conforms(v, rule.type)
        ]
    if rule.expectation == "expect_column_values_to_be_in_set":
        return [i for i, r in enumerate(rows) if not is_null(v := field_value(r, col)) and str(v) not in rule.allowed]
    cut = today.isoformat()
    return [i for i, r in enumerate(rows) if not is_null(v := field_value(r, col)) and str(v)[:10] > cut]


def totals(rows: Iterable[Row], patient: str | None, delta: str | None) -> ControlTotals:
    """``count(*)``, ``count(distinct patient)`` (non-empty) and ``max(delta)`` of the rows as read."""
    n, patients, top = 0, set(), None
    for r in rows:
        n += 1
        if patient and not is_null(p := field_value(r, patient)):
            patients.add(str(p).strip())
        if delta and not is_null(d := field_value(r, delta)) and (top is None or str(d) > top):
            top = str(d)
    return ControlTotals(
        rows=n,
        distinct_patients=len(patients) if patient else None,
        max_delta=top,
        patient_column=patient,
        delta_column=delta,
    )


def counted(rows: Iterable[Row], patient: str | None, delta: str | None, out: list[ControlTotals]) -> Iterator[Row]:
    """E2E P-25: ``rows`` as they pass, and :func:`totals` of them appended to ``out`` once they have all passed. No
    row is kept: a night without data contracts reconciles the export's control totals at the streamed read's cost."""
    n, patients, top = 0, set(), None
    for r in rows:
        n += 1
        if patient and not is_null(p := field_value(r, patient)):
            patients.add(str(p).strip())
        if delta and not is_null(d := field_value(r, delta)) and (top is None or str(d) > top):
            top = str(d)
        yield r
    out.append(ControlTotals(rows=n, distinct_patients=len(patients) if patient else None, max_delta=top,
                             patient_column=patient, delta_column=delta))  # fmt: skip


def reconcile(table: str, source: ControlTotals, read: ControlTotals) -> list[Equation]:
    """The export's own totals against the rows read (exact). ``max(delta)`` is compared only when both carry one."""
    eqs = [
        Equation(
            level="source→adapter",
            name="count(*)",
            table=table,
            lhs=source.rows,
            rhs=read.rows,
            diff=read.rows - source.rows,
            verdict="pass" if source.rows == read.rows else "fail",
            reason=None if source.rows == read.rows else ReasonCode.RECON_ROW_COUNT,
        )
    ]
    if source.distinct_patients is not None:
        ok = source.distinct_patients == read.distinct_patients
        eqs.append(
            Equation(
                level="source→adapter",
                name=f"count(distinct {source.patient_column or 'patient'})",
                table=table,
                lhs=source.distinct_patients,
                rhs=read.distinct_patients,
                diff=(read.distinct_patients or 0) - source.distinct_patients,
                verdict="pass" if ok else "fail",
                reason=None if ok else ReasonCode.RECON_DISTINCT_PATIENT,
            )
        )
    if source.max_delta is not None and read.max_delta is not None:
        ok = source.max_delta == read.max_delta
        eqs.append(
            Equation(
                level="source→adapter",
                name=f"max({source.delta_column or 'delta'})",
                table=table,
                lhs=source.max_delta,
                rhs=read.max_delta,
                verdict="pass" if ok else "fail",
                reason=None if ok else ReasonCode.RECON_MAX_DELTA,
            )
        )
    return eqs


def read_control_totals(directory: Path) -> dict[str, ControlTotals] | None:
    """The export's ``control_totals.json``, or None when it ships none."""
    path = directory / CONTROL_TOTALS_FILE
    if not path.is_file():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {str(t): ControlTotals.model_validate(v) for t, v in (doc.get("tables") or {}).items()}


@dataclass
class TableCheck:
    """One table's contract check: the rows to map (``accepted``) and the record of the rest."""

    validation: TableValidation
    accepted: list[Row]
    equations: list[Equation] = field(default_factory=list)


def key_hasher(site_key: bytes) -> Callable[[str], str]:
    """A keyed hash for the example keys of a report (never the key itself; not a pid)."""
    return lambda v: "k_" + hmac.new(site_key, f"example|{v}".encode(), hashlib.sha256).hexdigest()[:16]


def check_table(
    contract: DataContract | None,
    table: str,
    rows: list[Row],
    *,
    today: date,
    source_totals: ControlTotals | None = None,
    hasher: Callable[[str], str] = lambda v: "k_" + hashlib.sha256(v.encode()).hexdigest()[:16],
    present: bool = True,
) -> TableCheck:
    """Check one table's rows (as read, before the mapping) against its contract."""
    n = len(rows)
    if contract is None:
        tv = TableValidation(
            table=table,
            contract_id=None,
            contract_version=None,
            landed=n,
            accepted=0,
            quarantined=n,
            quarantine_by_reason={ReasonCode.CONTRACT_MISSING.value: n} if n else {},
            drift="unknown",
            findings=[
                Finding(
                    table=table,
                    reason=ReasonCode.CONTRACT_MISSING,
                    severity=Severity.BLOCKING,
                    rule_id=f"{table}.contract_missing",
                    detail="no data contract for table",
                    count=n,
                )
            ],
        )
        return TableCheck(tv, [])
    findings: list[Finding] = []
    drift = "none"
    if not present and contract.required_for_publish:
        findings.append(
            Finding(
                table=table,
                reason=ReasonCode.TABLE_MISSING,
                severity=Severity.BLOCKING,
                rule_id=f"{table}.present",
                detail="table required for publish is missing",
            )
        )
    elif rows:
        drift, drifted = classify_drift(contract, rows[0].keys())
        findings += drifted
    checks: list[DqCheck] = []
    reasons: dict[int, list[str]] = {}
    if n < contract.volume.min_rows and present:
        findings.append(
            Finding(
                table=table,
                reason=ReasonCode.VOLUME_ZERO,
                severity=Severity.BLOCKING,
                rule_id=f"{table}.row_count",
                detail=f"{n} rows, at least {contract.volume.min_rows}",
            )
        )
    for rule in rules_for(contract):
        bad = _failing(rule, rows, today)
        share = len(bad) / n if n else 0.0
        failed = share > rule.threshold if rule.threshold > 0 else bool(bad)
        checks.append(
            DqCheck(
                rule_id=rule.rule_id,
                expectation=rule.expectation,
                kahn_category=rule.kahn,
                kahn_subtype=rule.subtype,
                table=table,
                field=rule.column,
                threshold=rule.threshold,
                unexpected=len(bad),
                total=n,
                result="fail" if failed else "pass",
                severity=rule.severity,
                reason=rule.reason,
            )
        )
        if rule.quarantine:
            for i in bad:
                reasons.setdefault(i, []).append(rule.reason.value)
        if failed:
            findings.append(
                Finding(
                    table=table,
                    reason=rule.reason,
                    severity=rule.severity,
                    rule_id=rule.rule_id,
                    detail=f"{rule.expectation}: {len(bad)} of {n} unexpected",
                    count=len(bad),
                )
            )
    accepted = [r for i, r in enumerate(rows) if i not in reasons]
    quarantined = len(rows) - len(accepted)
    if n and quarantined / n > contract.volume.max_quarantine_share:
        findings.append(
            Finding(
                table=table,
                reason=ReasonCode.QUARANTINE_SHARE,
                severity=Severity.BLOCKING,
                rule_id=f"{table}.quarantine_share",
                detail=f"quarantined {quarantined} of {n} ({quarantined / n:.2%}) > "
                f"{contract.volume.max_quarantine_share:.2%}",
                count=quarantined,
            )
        )
    equations: list[Equation] = []
    if source_totals is not None:
        equations = reconcile(table, source_totals, totals(rows, contract.keys.patient, contract.keys.watermark))
    pk = contract.keys.primary
    examples = sorted({hasher("|".join(str(field_value(rows[i], c)) for c in pk)) for i in reasons} if pk else set())
    by_reason = Counter(x for rs in reasons.values() for x in sorted(set(rs)))
    tv = TableValidation(
        table=table,
        contract_id=contract.contract_id,
        contract_version=contract.version,
        landed=n,
        accepted=len(accepted),
        quarantined=quarantined,
        quarantine_by_reason=dict(sorted(by_reason.items())),
        drift="breaking" if drift == "breaking" else "additive" if drift == "additive" else "none",
        checks=checks,
        findings=sorted(findings, key=lambda f: (f.severity.value, f.reason.value, f.rule_id)),
        example_keys=examples[:20],
    )
    return TableCheck(tv, accepted, equations)


def _sid(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:24]


def contract_report(source: str, night: str, checks: Sequence[TableCheck], at: datetime) -> ValidationReport:
    """The night's contract checks as one report (counts and reason codes only)."""
    tables = sorted((c.validation for c in checks), key=lambda t: t.table)
    eqs = sorted((e for c in checks for e in c.equations), key=lambda e: (e.table or "", e.name))
    rec = ReconciliationRecord(
        record_id=_sid("rec", source, night, [e.model_dump_json() for e in eqs]),
        scope="batch",
        ref=night,
        equations=eqs,
    )
    blocking = {f.reason for t in tables for f in t.findings if f.severity == Severity.BLOCKING}
    blocking |= {e.reason for e in eqs if e.verdict == "fail" and e.reason is not None}
    warn = any(f.severity == Severity.WARNING for t in tables for f in t.findings)
    return ValidationReport(
        report_id=_sid("val", source, night),
        batch_id=night,
        source=source,
        validated_at=at.astimezone(UTC),
        tables=tables,
        reconciliation=rec,
        outcome="block" if blocking else "warn" if warn else "pass",
        blocking_reasons=sorted(blocking, key=lambda r: r.value),
    )


# ------------------------------------------------------------------------------------------------ the gate
@dataclass
class NightFacts:
    """What one night measured, for :func:`gate_record`. ``None``: the step did not run."""

    night: str
    contracts: ValidationReport | None = None
    file_quarantine: Mapping[str, str] = field(default_factory=dict)  # T-615b: table -> why
    completeness: Sequence[str] = ()  # T-611 problems (and the resource-type drop guard)
    overrides: Sequence[str] = ()  # D-271 overrides that let a gap through
    validation: Sequence[str] = ()  # validation error-rate or JP Core findings over the ceiling
    other: Sequence[str] = ()  # every other error that held the night (rejects, a failed load, a refusal)
    current_before: str | None = None
    current_after: str | None = None
    # E2E P-25: the export's control totals reconciled on a night without data contracts (with them, ``contracts``)
    reconciliation: Sequence[Equation] = ()


def _cond(number: int, name: str, ok: bool | None, detail: str, reasons: Sequence[ReasonCode]) -> GateCondition:
    result: Literal["pass", "fail", "not_evaluated"] = "not_evaluated" if ok is None else "pass" if ok else "fail"
    return GateCondition(number=number, name=name, result=result, detail=detail, reasons=[] if ok else list(reasons))


def gate_record(f: NightFacts, decided_at: datetime) -> PublishGateRecord:
    """One record per night: the conditions, the outcome, the reasons (D-370 §3, publish gate)."""
    rep = f.contracts
    blocking = sorted(
        {x.reason for t in (rep.tables if rep else []) for x in t.findings if x.severity == Severity.BLOCKING},
        key=lambda r: r.value,
    )
    eqs = rep.reconciliation.equations if rep else list(f.reconciliation)
    failed = [e for e in eqs if e.verdict == "fail"]
    conds = [
        _cond(
            1,
            "every mapped table meets its contract",
            None if rep is None else not blocking,
            "no contracts configured" if rep is None else ", ".join(r.value for r in blocking),
            blocking,
        ),
        _cond(
            2,
            "the export's control totals hold",
            None if not eqs else not failed,
            "no control totals shipped"
            if not eqs
            else "; ".join(f"{e.table} {e.name}: {e.lhs} vs {e.rhs}" for e in failed[:10]),
            sorted({e.reason for e in failed if e.reason}, key=lambda r: r.value),
        ),
        _cond(
            3,
            "no source file quarantined",
            not f.file_quarantine,
            "; ".join(f.file_quarantine.values()),
            [ReasonCode.INTEGRITY],
        ),
        _cond(
            4,
            "the feed is complete against the last good night",
            not f.completeness,
            "; ".join(f.completeness),
            [ReasonCode.FEED_INCOMPLETE],
        ),
        _cond(
            5,
            "validation error rate within the ceiling",
            not f.validation,
            "; ".join(f.validation),
            [ReasonCode.VALIDATION_ERROR_RATE],
        ),
        _cond(6, "no other step failed", not f.other, "; ".join(f.other)[:2000], [ReasonCode.STAGE_FAILED]),
    ]
    reasons = sorted({r for c in conds if c.result == "fail" for r in c.reasons}, key=lambda r: r.value)
    warnings = [*f.overrides]
    if rep is not None:
        warnings += [
            f"{x.table}: {x.reason.value} ({x.detail})"
            for t in rep.tables
            for x in t.findings
            if x.severity == Severity.WARNING
        ]
    outcome: GateOutcome = "HOLD" if reasons else "PUBLISH_WITH_WARNINGS" if warnings else "PUBLISH"
    return PublishGateRecord(
        gate_id=_sid("gate", f.night, [c.model_dump_json() for c in conds]),
        cycle_id=f.night,
        decided_at=decided_at.astimezone(UTC),
        conditions=conds,
        outcome=outcome,
        blocking_reasons=reasons,
        warnings=warnings,
        current_before=f.current_before,
        current_after=f.current_after,
    )


def write_gate(record: PublishGateRecord, night_dir: Path, lake_dir: Path) -> None:
    """``gate.json`` beside the night's report, and ``<lake>/gates/<night>.json`` (a re-run replaces its night's)."""
    body = json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    (night_dir / GATE).write_text(body, encoding="utf-8")
    gates = lake_dir / GATES_DIR
    gates.mkdir(parents=True, exist_ok=True)
    (gates / f"{record.cycle_id}.json").write_text(body, encoding="utf-8")


# ------------------------------------------------------------------------------------------------ lineage
def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def lineage(
    night: str, source: str, inputs: Iterable[Path], mapping: Path | None, snapshot_dir: Path, gate: PublishGateRecord
) -> dict[str, Any]:
    """The night's ``lineage.json``: what went in (names and hashes), the mapping, what was written, the outcome."""
    files = sorted({p for p in inputs if p.is_file()})
    return {
        "night": night,
        "source": source,
        "inputs": [{"name": p.name, "sha256": file_sha256(p), "bytes": p.stat().st_size} for p in files],
        "mapping": {"name": mapping.name, "sha256": file_sha256(mapping)} if mapping and mapping.is_file() else None,
        "snapshot": {
            "night": night,
            "folder": snapshot_dir.name,
            "files": sorted(p.name for p in snapshot_dir.glob("*.ndjson")),
        },
        "gate": {"gate_id": gate.gate_id, "outcome": gate.outcome},
    }


def lineage_complete(doc: Mapping[str, Any]) -> bool:
    """Every input hashed, the snapshot named, the gate's outcome recorded."""
    ins = doc.get("inputs") or []
    return bool(ins) and all(i.get("sha256") for i in ins) and bool(doc.get("snapshot")) and bool(doc.get("gate"))


__all__ = [
    "CONTRACTS_ROOT",
    "DEMO_HIS",
    "MIMIC_FHIR",
    "ColumnSpec",
    "DataContract",
    "NightFacts",
    "TableCheck",
    "check_table",
    "classify_drift",
    "contract_report",
    "contracts_dir",
    "gate_record",
    "key_hasher",
    "lineage",
    "lineage_complete",
    "load_contracts",
    "read_control_totals",
    "value_conforms",
    "write_gate",
]
