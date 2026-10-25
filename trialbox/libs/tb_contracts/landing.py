"""Data-platform records (spec v4 §5.3, §5.9, §6.14; S1-02, S1-03, S1-04).

The L0 batch manifest is the S1-02 contract. The other records of §6.14 that the L1–L5 thin path writes
(reconciliation record, validation report, publish-gate record, steward notice, snapshot manifest) live here too, so
that every service reads the same models. Every record carries a :class:`~tb_contracts.dataclass.ClassLabel`.

All times are UTC (§5 conventions). Serialise with :func:`canonical_json` (sorted keys, no spaces, UTF-8): it is the
form that is hashed and signed.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tb_contracts.dataclass import ClassLabel, DataClass

SCHEMA_VERSION = "1.0.0"

D4 = ClassLabel(data_class=DataClass.D4)
D3 = ClassLabel(data_class=DataClass.D3)
D1 = ClassLabel(data_class=DataClass.D1)


class ConnectorKind(StrEnum):
    """Connector kinds of §5.5."""

    DB_VIEW = "db_view"
    CDC = "cdc"
    HL7V2 = "hl7v2"
    FHIR_REST = "fhir_rest"
    FHIR_BULK = "fhir_bulk"
    FILE_DROP = "file_drop"


class ReasonCode(StrEnum):
    """Reason codes for quarantined rows, blocking findings and gate conditions (§5.3 L1, §5.9.3)."""

    CONTRACT_MISSING = "CONTRACT_MISSING"  # a landed table without a data contract (DP-18)
    TABLE_MISSING = "TABLE_MISSING"  # a contract marked required_for_publish without a landed table
    SCHEMA_DRIFT_BREAKING = "SCHEMA_DRIFT_BREAKING"  # dropped column, type change, nulls in a non-null column
    SCHEMA_DRIFT_ADDITIVE = "SCHEMA_DRIFT_ADDITIVE"  # a new column (warning)
    TYPE_MISMATCH = "TYPE_MISMATCH"  # a value that does not parse as the contract type
    REQUIRED_NULL = "REQUIRED_NULL"  # null in a non-nullable column that is not the patient key
    NULL_IDENTIFIER = "NULL_IDENTIFIER"  # null patient key
    DUPLICATE_KEY = "DUPLICATE_KEY"  # primary key seen more than once
    ENUM_VIOLATION = "ENUM_VIOLATION"  # value outside the contract enumeration
    FUTURE_DATE = "FUTURE_DATE"  # plausibility, temporal
    QUARANTINE_SHARE = "QUARANTINE_SHARE"  # quarantined share above the contract maximum
    VOLUME_ZERO = "VOLUME_ZERO"  # zero rows for a table expected to be non-empty
    CONTROL_TOTALS_MISSING = "CONTROL_TOTALS_MISSING"
    RECON_ROW_COUNT = "RECON_ROW_COUNT"  # source count(*) != landed count(*)
    RECON_DISTINCT_PATIENT = "RECON_DISTINCT_PATIENT"  # source count(distinct mrn) != landed
    RECON_MAX_DELTA = "RECON_MAX_DELTA"  # source max(delta) != landed
    RECON_INTERNAL = "RECON_INTERNAL"  # an internal equation (L0 → L4) does not hold exactly
    INTEGRITY = "INTEGRITY"  # a landed object no longer matches its sha256
    VALIDATION_ERROR_RATE = "VALIDATION_ERROR_RATE"  # L2 profile-validation error rate above the ceiling
    IDN_UNRESOLVED = "IDN_UNRESOLVED"  # L3: patient key not resolvable through the MPI
    IDN_QUARANTINE_SHARE = "IDN_QUARANTINE_SHARE"  # L3: identity-quarantine share above the ceiling
    SNAPSHOT_BALANCE = "SNAPSHOT_BALANCE"  # L3 → L4 balance does not hold
    STAGE_FAILED = "STAGE_FAILED"  # a stage raised; nothing is published


class Severity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"


def canonical_json(obj: BaseModel | dict[str, Any] | list[Any]) -> str:
    """Canonical JSON text (sorted keys, no spaces, UTF-8): the form that is hashed, signed and stored."""
    data = obj.model_dump(mode="json") if isinstance(obj, BaseModel) else obj
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(v: datetime | None) -> datetime | None:
    if v is not None and (v.tzinfo is None or v.utcoffset() is None):
        raise ValueError("timestamps must carry a zone (UTC by convention)")
    return v


# ---------------------------------------------------------------------------------------------------- L0 (S1-02)
class ColumnShape(_Record):
    """One column as observed in a landed object: ``[name, physical_type, nullable]`` of §5.8.2."""

    name: str
    type: str
    nullable: bool


class LandedObject(_Record):
    key: str = Field(description="object key relative to the batch directory, e.g. objects/lab.csv")
    table: str
    bytes: int
    sha256: str
    rows: int
    encoding: str
    columns: list[ColumnShape]
    schema_fingerprint: str


class ControlTotals(_Record):
    """Control totals of one table (§5.9.1): ``count(*)``, ``count(distinct patient_key)``, ``max(delta)``."""

    rows: int
    distinct_patients: int | None = None
    max_delta: str | None = None
    patient_column: str | None = None
    delta_column: str | None = None


class L0BatchManifest(_Record):
    """``l0_batch_manifest`` (§6.14). Immutable: written once next to the write-once objects it describes."""

    schema_version: str = SCHEMA_VERSION
    batch_id: str
    source: str
    kind: ConnectorKind
    extract_time: datetime
    extract_start: datetime | None = None
    extract_end: datetime | None = None
    landed_at: datetime
    rows: int
    bytes: int
    sha256: str = Field(description="digest over the sorted (key, sha256) pairs of all objects")
    schema_fingerprint: str = Field(description="sha256(JCS({table: per-object fingerprint}))")
    objects: list[LandedObject]
    watermark_from: str | None = None
    watermark_to: str | None = None
    control_totals: dict[str, ControlTotals] = Field(default_factory=dict)
    control_totals_origin: Literal["source", "extract"] = "source"
    encoding: str = "utf-8"
    data_class: ClassLabel = D4

    @field_validator("extract_time", "extract_start", "extract_end", "landed_at")
    @classmethod
    def _zoned(cls, v: datetime | None) -> datetime | None:
        return _utc(v)

    def object_for(self, table: str) -> LandedObject | None:
        return next((o for o in self.objects if o.table == table), None)


# ---------------------------------------------------------------------------------------------------- L1 (S1-03)
Verdict = Literal["pass", "warn", "fail"]


class Equation(_Record):
    level: str = Field(description="source→L0, L0→L1, L1→L2, L2→L3, L3→L4")
    name: str
    table: str | None = None
    lhs: int | str | None
    rhs: int | str | None
    diff: int | None = None
    tolerance: str = "exact"
    verdict: Verdict
    reason: ReasonCode | None = None


class ReconciliationRecord(_Record):
    """``reconciliation_record`` (§5.9.2, §6.14)."""

    record_id: str
    scope: Literal["batch", "cycle"]
    ref: str
    equations: list[Equation]

    @property
    def passed(self) -> bool:
        return all(e.verdict != "fail" for e in self.equations)


class DqCheck(_Record):
    """One check of the ``dq_report`` (§6.14), Great-Expectations style, Kahn-labelled (§5.10)."""

    rule_id: str
    engine: Literal["gx", "sql", "dqd"] = "gx"
    expectation: str
    kahn_category: Literal["conformance", "completeness", "plausibility"]
    kahn_subtype: str
    context: Literal["verification", "validation"] = "verification"
    table: str
    field: str | None = None
    threshold: float = 0.0
    unexpected: int
    total: int
    result: Literal["pass", "fail"]
    severity: Severity
    reason: ReasonCode


class Finding(_Record):
    table: str
    reason: ReasonCode
    severity: Severity
    rule_id: str
    detail: str
    count: int = 0


class TableValidation(_Record):
    table: str
    contract_id: str | None
    contract_version: str | None
    landed: int
    accepted: int
    quarantined: int
    quarantine_by_reason: dict[str, int] = Field(default_factory=dict)
    drift: Literal["none", "additive", "breaking", "unknown"] = "none"
    checks: list[DqCheck] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    example_keys: list[str] = Field(default_factory=list, description="pseudonymised keys of quarantined rows")


class ValidationReport(_Record):
    """``validation_report`` of L1 (§5.3): pass/warn/block per rule, accepted and quarantine counts."""

    schema_version: str = SCHEMA_VERSION
    report_id: str
    batch_id: str
    source: str
    validated_at: datetime
    tables: list[TableValidation]
    reconciliation: ReconciliationRecord
    outcome: Literal["pass", "warn", "block"]
    blocking_reasons: list[ReasonCode]
    data_class: ClassLabel = D3

    @property
    def blocked(self) -> bool:
        return self.outcome == "block"


# ---------------------------------------------------------------------------------------------------- gate
GateOutcome = Literal["PUBLISH", "PUBLISH_WITH_WARNINGS", "HOLD", "OVERRIDE"]


class GateCondition(_Record):
    number: int
    name: str
    result: Literal["pass", "fail", "not_evaluated"]
    detail: str = ""
    reasons: list[ReasonCode] = Field(default_factory=list)


class PublishGateRecord(_Record):
    """``publish_gate_record`` (§5.9.3, §6.14)."""

    schema_version: str = SCHEMA_VERSION
    gate_id: str
    cycle_id: str
    decided_at: datetime
    conditions: list[GateCondition]
    outcome: GateOutcome
    blocking_reasons: list[ReasonCode]
    warnings: list[str] = Field(default_factory=list)
    current_before: str | None = None
    current_after: str | None = None
    override_gate_id: str | None = None
    data_class: ClassLabel = D1


class StewardNotice(_Record):
    """The rendered steward e-mail of a held cycle (§5.3 L1, §5.9.3 HOLD). Returned to the caller; never sent here."""

    notice_id: str
    cycle_id: str
    to: list[str]
    cc: list[str] = Field(default_factory=list)
    subject: str
    body: str
    failed_rules: list[str]
    example_keys: list[str] = Field(default_factory=list)
    data_class: ClassLabel = D3


# ---------------------------------------------------------------------------------------------------- L4 / L5
class TableSnapshot(_Record):
    rows: int
    sha256: str


class SnapshotManifest(_Record):
    """``snapshot_manifest`` (§6.14): what readers resolve tables through (DP-32). Ed25519-signed."""

    schema_version: str = SCHEMA_VERSION
    snapshot_id: str
    snapshot: str = Field(description="ISO date of the snapshot (the v1 lake name)")
    cycle_id: str
    created_at: datetime
    tables: dict[str, TableSnapshot]
    lake_tables: dict[str, int] = Field(default_factory=dict)
    lake_sha256: str | None = Field(default=None, description="digest over the snapshot's Parquet files")
    contracts: dict[str, str] = Field(default_factory=dict)
    mapping_spec: dict[str, str] = Field(default_factory=dict, description="source → sha256 of its mapping spec")
    terminology: str | None = None
    data_cut_per_source: dict[str, str] = Field(default_factory=dict)
    batches: list[str] = Field(default_factory=list)
    publish_gate: str
    reconciliation: list[str] = Field(default_factory=list)
    previous_snapshot: str | None = None
    warnings: list[str] = Field(default_factory=list)
    lineage_runs: list[str] = Field(default_factory=list)
    data_class: ClassLabel = D3
    signature: str | None = None
    signer_public_key: str | None = None


class ServingPointer(_Record):
    """The L5 ``CURRENT`` pointer (§5.3 L5, §5.9.3): which signed snapshot downstream runs pin."""

    snapshot_id: str
    snapshot: str
    manifest_sha256: str
    pinned_at: datetime
    reason: str


__all__ = [
    "D1",
    "D3",
    "D4",
    "SCHEMA_VERSION",
    "ColumnShape",
    "ConnectorKind",
    "ControlTotals",
    "DqCheck",
    "Equation",
    "Finding",
    "GateCondition",
    "GateOutcome",
    "L0BatchManifest",
    "LandedObject",
    "PublishGateRecord",
    "ReasonCode",
    "ReconciliationRecord",
    "ServingPointer",
    "Severity",
    "SnapshotManifest",
    "StewardNotice",
    "TableSnapshot",
    "TableValidation",
    "ValidationReport",
    "Verdict",
    "canonical_json",
]
