"""Data contracts per (source, table) and schema-drift classification (§5.8, DP-18; S1-03).

A contract is a YAML file ``<contracts_dir>/<table>.yaml`` following the structure of §6.14 (identity, schema, keys,
volume, control totals, quality, change policy). Built-in contracts for the synthetic demo HIS export and for the
MIMIC-IV FHIR demo ship next to this module (``demo_his/``, ``mimic_fhir/``); a site keeps its own under
``site/contracts/<source>/``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field
from tb_contracts.dataclass import DataClass
from tb_contracts.landing import ColumnShape, ConnectorKind, ReasonCode, Severity

from dataplat.landing.shape import fingerprint

CONTRACTS_ROOT = Path(__file__).resolve().parent
DEMO_HIS = CONTRACTS_ROOT / "demo_his"
MIMIC_FHIR = CONTRACTS_ROOT / "mimic_fhir"

ColumnType = Literal[
    "string", "integer", "decimal", "date", "timestamp", "object", "array", "number", "boolean", "null"
]
Privacy = Literal["direct_identifier", "quasi_identifier", "sensitive", "free_text", "none"]

# contract type -> observed physical types it accepts (``null`` = an all-empty column is always accepted)
_ACCEPTS: dict[str, frozenset[str]] = {
    "string": frozenset({"string", "integer", "decimal", "date", "timestamp", "null"}),
    "decimal": frozenset({"decimal", "integer", "null"}),
    "integer": frozenset({"integer", "null"}),
    "date": frozenset({"date", "null"}),
    "timestamp": frozenset({"timestamp", "date", "null"}),
    "object": frozenset({"object", "null"}),
    "array": frozenset({"array", "null"}),
    "number": frozenset({"number", "null"}),
    "boolean": frozenset({"boolean", "null"}),
    "null": frozenset({"null"}),
}


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
    validation_max_pct: float = Field(default=0.5, description="L2 profile-validation error ceiling, percent")
    change_policy: dict[str, str] = Field(default_factory=lambda: {"additive": "auto", "breaking": "g0_major"})

    def column(self, name: str) -> ColumnSpec | None:
        return next((c for c in self.columns if c.name == name), None)

    @property
    def expected_fingerprint(self) -> str:
        return fingerprint(ColumnShape(name=c.name, type=c.type, nullable=c.nullable) for c in self.columns)


def load_contract(path: Path) -> DataContract:
    doc: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: not a contract document")
    return DataContract.model_validate(doc)


def load_contracts(directory: Path) -> dict[str, DataContract]:
    """All contracts of one source directory, keyed by table."""
    out: dict[str, DataContract] = {}
    for p in sorted(directory.glob("*.yaml")):
        c = load_contract(p)
        if c.table in out:
            raise ValueError(f"{directory}: two contracts for table {c.table!r}")
        out[c.table] = c
    return out


def classify_drift(
    contract: DataContract, observed: list[ColumnShape]
) -> tuple[str, list[tuple[ReasonCode, Severity, str]]]:
    """Classify the observed schema against the contract (§5.8.3): ``none``, ``additive`` or ``breaking``.

    Breaking: a contract column missing from the batch, or an observed type the contract type does not accept.
    Additive: a column the contract does not know. Nulls are row-level findings, not drift.
    """
    seen = {c.name: c for c in observed}
    findings: list[tuple[ReasonCode, Severity, str]] = []
    for spec in contract.columns:
        obs = seen.get(spec.name)
        if obs is None:
            if contract.format == "csv" or not spec.nullable:
                findings.append((ReasonCode.SCHEMA_DRIFT_BREAKING, Severity.BLOCKING, f"column {spec.name} missing"))
            continue
        if obs.type not in _ACCEPTS[spec.type]:
            findings.append(
                (
                    ReasonCode.SCHEMA_DRIFT_BREAKING,
                    Severity.BLOCKING,
                    f"column {spec.name}: contract type {spec.type}, batch type {obs.type}",
                )
            )
    known = {c.name for c in contract.columns}
    for name in sorted(set(seen) - known):
        findings.append((ReasonCode.SCHEMA_DRIFT_ADDITIVE, Severity.WARNING, f"new column {name}"))
    if any(r == ReasonCode.SCHEMA_DRIFT_BREAKING for r, _, _ in findings):
        return "breaking", findings
    return ("additive" if findings else "none"), findings


__all__ = [
    "CONTRACTS_ROOT",
    "DEMO_HIS",
    "MIMIC_FHIR",
    "ColumnSpec",
    "DataContract",
    "Keys",
    "Volume",
    "classify_drift",
    "load_contract",
    "load_contracts",
]
