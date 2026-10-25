"""Steward notification of a held cycle (§5.3 L1, §5.9.3 HOLD, DP-20).

Renders the e-mail (recipients, subject, plain-text body with the diff, the failed rules and up to 20 pseudonymised
example keys) as a :class:`~tb_contracts.landing.StewardNotice` and returns it. Nothing is sent here: delivery belongs
to the outbox and channel engine.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from tb_contracts.landing import PublishGateRecord, Severity, StewardNotice, ValidationReport

from dataplat.common import iso_utc, stable_id
from dataplat.contracts import DataContract

MAX_EXAMPLE_KEYS = 20


def render_notice(
    gate: PublishGateRecord,
    reports: Sequence[ValidationReport],
    contracts: Mapping[str, Mapping[str, DataContract]],
    *,
    research_office: Sequence[str] = (),
    extra_reasons: Sequence[str] = (),
) -> StewardNotice:
    """Build the steward notice for a ``HOLD`` gate. ``contracts`` is ``{source: {table: contract}}``."""
    stewards: set[str] = set()
    cc: set[str] = set(research_office)
    failed: list[str] = []
    examples: list[str] = []
    lines = [
        f"The publish gate held cycle {gate.cycle_id} at {iso_utc(gate.decided_at)}.",
        f"Nothing was published. The current snapshot stays {gate.current_after or 'unset (no snapshot yet)'}.",
        "",
        "Blocking reasons: " + ", ".join(r.value for r in gate.blocking_reasons),
        "",
    ]
    for rep in sorted(reports, key=lambda r: (r.source, r.batch_id)):
        src_contracts = contracts.get(rep.source, {})
        lines.append(f"Source {rep.source}, batch {rep.batch_id}: L1 outcome {rep.outcome}")
        for tv in rep.tables:
            blocking = [f for f in tv.findings if f.severity == Severity.BLOCKING]
            if not blocking:
                continue
            c = src_contracts.get(tv.table)
            if c is not None:
                stewards.add(c.steward)
                cc.add(c.change_channel)
            lines.append(
                f"  {tv.table} (contract {tv.contract_id or '-'}@{tv.contract_version or '-'}): landed {tv.landed}, "
                f"accepted {tv.accepted}, quarantined {tv.quarantined}"
            )
            for f in blocking:
                failed.append(f"{f.rule_id}:{f.reason.value}")
                lines.append(f"    - {f.reason.value} [{f.rule_id}] {f.detail}")
            if tv.example_keys:
                lines.append("    example keys (pseudonymised): " + ", ".join(tv.example_keys[:5]))
                examples.extend(tv.example_keys)
        for e in rep.reconciliation.equations:
            if e.verdict == "fail":
                ec = src_contracts.get(e.table or "")
                if ec is not None:
                    stewards.add(ec.steward)
                    cc.add(ec.change_channel)
                failed.append(f"{e.table or '-'}.{e.name}:{e.reason.value if e.reason else 'FAIL'}")
                lines.append(
                    f"  reconciliation {e.level} {e.table or ''} {e.name}: source {e.lhs} vs landed {e.rhs}"
                    + (f" (diff {e.diff})" if e.diff is not None else "")
                )
        lines.append("")
    for reason in extra_reasons:
        failed.append(reason)
        lines.append(f"Other: {reason}")
    for cond in gate.conditions:
        if cond.result == "fail":
            lines.append(f"Gate condition {cond.number} ({cond.name}) failed: {cond.detail}")
    lines += [
        "",
        "Fix the source extract or approve a new contract version at G0, then re-run the cycle.",
        "This message carries no patient identifiers; example keys are keyed hashes.",
    ]
    to = sorted(stewards) or sorted(cc)
    subject = f"[TrialBox] publish HOLD for cycle {gate.cycle_id}: " + ", ".join(
        r.value for r in gate.blocking_reasons[:4]
    )
    return StewardNotice(
        notice_id=stable_id("ntc", gate.gate_id),
        cycle_id=gate.cycle_id,
        to=to,
        cc=sorted(cc - set(to)),
        subject=subject,
        body="\n".join(lines) + "\n",
        failed_rules=sorted(set(failed)),
        example_keys=sorted(set(examples))[:MAX_EXAMPLE_KEYS],
    )


__all__ = ["render_notice"]
