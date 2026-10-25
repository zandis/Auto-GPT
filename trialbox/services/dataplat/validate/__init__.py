"""L1 validation (§5.3 L1, DP-18, DP-19, DP-22; S1-03).

For one landed batch: object integrity, the data contract of each table (missing contract → blocked), schema drift
by fingerprint, reconciliation of the landed bytes against the source control totals, the expectation suite, and
the split into an ``accepted`` set and a ``quarantine`` set with reason codes. Quarantined rows are never dropped
silently: ``landed = accepted + quarantined`` is an exact equation of the record, and the quarantine set is written
to disk (Z-IDN, D4, kept 30 days).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from tb_contracts.landing import (
    ControlTotals,
    Equation,
    Finding,
    L0BatchManifest,
    ReasonCode,
    Severity,
    TableValidation,
    ValidationReport,
)

from dataplat.common import Clock, stable_id, utc_now, write_atomic, write_json
from dataplat.contracts import DataContract, classify_drift
from dataplat.dq import run_suite, suite_for
from dataplat.landing.shape import iter_rows
from dataplat.landing.zone import LandingZone
from dataplat.reconcile import compute_totals, exact, field_value, record, source_vs_landed

Row = dict[str, Any]
KeyHasher = Callable[[str], str]
MAX_EXAMPLE_KEYS = 20


@dataclass
class L1Result:
    report: ValidationReport
    accepted: dict[str, list[Row]] = field(default_factory=dict)
    quarantine: dict[str, list[tuple[Row, list[str]]]] = field(default_factory=dict)
    landed_totals: dict[str, ControlTotals] = field(default_factory=dict)


def _table_validation(
    table: str,
    contract: DataContract,
    rows: list[Row],
    observed: Any,
    source_totals: ControlTotals | None,
    today: Any,
    key_hasher: KeyHasher,
) -> tuple[TableValidation, list[Row], list[tuple[Row, list[str]]], list[Equation], ControlTotals]:
    findings: list[Finding] = []
    drift, drift_findings = classify_drift(contract, observed)
    for reason, sev, detail in drift_findings:
        findings.append(Finding(table=table, reason=reason, severity=sev, rule_id=f"{table}.schema", detail=detail))
    landed = compute_totals(rows, contract.keys.patient, contract.keys.watermark)
    equations = source_vs_landed(table, source_totals, landed)
    results = run_suite(rows, suite_for(contract), today)
    reasons: dict[int, list[str]] = {}
    for res in results:
        for i in res.failing_rows:
            reasons.setdefault(i, []).append(res.check.reason.value)
        if res.check.result == "fail":
            findings.append(
                Finding(
                    table=table,
                    reason=res.check.reason,
                    severity=res.check.severity,
                    rule_id=res.check.rule_id,
                    detail=f"{res.check.expectation}: {res.check.unexpected} of {res.check.total} unexpected",
                    count=res.check.unexpected,
                )
            )
    accepted = [r for i, r in enumerate(rows) if i not in reasons]
    quarantined = [(rows[i], sorted(set(reasons[i]))) for i in sorted(reasons)]
    n = len(rows)
    share = len(quarantined) / n if n else 0.0
    if share > contract.volume.max_quarantine_share:
        findings.append(
            Finding(
                table=table,
                reason=ReasonCode.QUARANTINE_SHARE,
                severity=Severity.BLOCKING,
                rule_id=f"{table}.quarantine_share",
                detail=f"quarantined {len(quarantined)} of {n} ({share:.2%}) > "
                f"{contract.volume.max_quarantine_share:.2%}",
                count=len(quarantined),
            )
        )
    equations.append(exact("L0→L1", "landed = accepted + quarantined", n, len(accepted) + len(quarantined), table))
    by_reason = Counter(r for _, rs in quarantined for r in rs)
    pk = contract.keys.primary
    examples = sorted(
        {key_hasher("|".join(str(field_value(r, c)) for c in pk)) for r, _ in quarantined} if pk else set()
    )[:MAX_EXAMPLE_KEYS]
    tv = TableValidation(
        table=table,
        contract_id=contract.contract_id,
        contract_version=contract.version,
        landed=n,
        accepted=len(accepted),
        quarantined=len(quarantined),
        quarantine_by_reason=dict(sorted(by_reason.items())),
        drift="breaking" if drift == "breaking" else "additive" if drift == "additive" else "none",
        checks=[r.check for r in results],
        findings=sorted(findings, key=lambda f: (f.severity.value, f.reason.value, f.rule_id)),
        example_keys=examples,
    )
    return tv, accepted, quarantined, equations, landed


def validate_batch(
    zone: LandingZone,
    manifest: L0BatchManifest,
    contracts: Mapping[str, DataContract],
    *,
    key_hasher: KeyHasher,
    clock: Clock = utc_now,
    out_dir: Path | None = None,
) -> L1Result:
    """Validate one L0 batch against its source's contracts. Writes ``report.json`` and the quarantine set to
    ``out_dir`` when given."""
    now = clock()
    tables: list[TableValidation] = []
    equations: list[Equation] = []
    accepted_sets: dict[str, list[Row]] = {}
    quarantine_sets: dict[str, list[tuple[Row, list[str]]]] = {}
    landed_totals: dict[str, ControlTotals] = {}
    bad_objects = set(zone.verify(manifest))
    for obj in manifest.objects:
        table = obj.table
        contract = contracts.get(table)
        if obj.key in bad_objects or contract is None:
            reason = ReasonCode.INTEGRITY if obj.key in bad_objects else ReasonCode.CONTRACT_MISSING
            detail = "object sha256 mismatch" if reason == ReasonCode.INTEGRITY else "no data contract for table"
            tables.append(
                TableValidation(
                    table=table,
                    contract_id=contract.contract_id if contract else None,
                    contract_version=contract.version if contract else None,
                    landed=obj.rows,
                    accepted=0,
                    quarantined=obj.rows,
                    quarantine_by_reason={reason.value: obj.rows},
                    drift="unknown",
                    findings=[
                        Finding(
                            table=table,
                            reason=reason,
                            severity=Severity.BLOCKING,
                            rule_id=f"{table}.{reason.value.lower()}",
                            detail=detail,
                            count=obj.rows,
                        )
                    ],
                )
            )
            continue
        _, data = zone.read_object(manifest, table)
        rows = list(iter_rows(data, obj.key, obj.encoding))
        tv, accepted, quarantined, eqs, landed = _table_validation(
            table, contract, rows, obj.columns, manifest.control_totals.get(table), now.date(), key_hasher
        )
        tables.append(tv)
        equations.extend(eqs)
        accepted_sets[table] = accepted
        quarantine_sets[table] = quarantined
        landed_totals[table] = landed
    landed_tables = {o.table for o in manifest.objects}
    for table, contract in sorted(contracts.items()):
        if contract.required_for_publish and table not in landed_tables:
            tables.append(
                TableValidation(
                    table=table,
                    contract_id=contract.contract_id,
                    contract_version=contract.version,
                    landed=0,
                    accepted=0,
                    quarantined=0,
                    drift="unknown",
                    findings=[
                        Finding(
                            table=table,
                            reason=ReasonCode.TABLE_MISSING,
                            severity=Severity.BLOCKING,
                            rule_id=f"{table}.present",
                            detail="table required for publish is missing from the batch",
                        )
                    ],
                )
            )
    rec = record("batch", manifest.batch_id, equations)
    blocking = {f.reason for t in tables for f in t.findings if f.severity == Severity.BLOCKING}
    blocking |= {e.reason for e in rec.equations if e.verdict == "fail" and e.reason is not None}
    warnings = any(f.severity == Severity.WARNING for t in tables for f in t.findings)
    outcome: Literal["pass", "warn", "block"] = "block" if blocking else "warn" if warnings else "pass"
    tables.sort(key=lambda t: t.table)
    report = ValidationReport(
        report_id=stable_id("val", manifest.batch_id, sorted((c.contract_id, c.version) for c in contracts.values())),
        batch_id=manifest.batch_id,
        source=manifest.source,
        validated_at=now,
        tables=tables,
        reconciliation=rec,
        outcome=outcome,
        blocking_reasons=sorted(blocking, key=lambda r: r.value),
    )
    result = L1Result(report, accepted_sets, quarantine_sets, landed_totals)
    if out_dir is not None:
        write_json(out_dir / "report.json", report.model_dump(mode="json"))
        for table, items in sorted(result.quarantine.items()):
            if items:
                lines = [
                    json.dumps({"reasons": rs, "row": r}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                    for r, rs in items
                ]
                write_atomic(out_dir / "quarantine" / f"{table}.jsonl", ("\n".join(lines) + "\n").encode("utf-8"))
    return result


__all__ = ["L1Result", "validate_batch"]
