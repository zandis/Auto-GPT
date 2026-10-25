"""One publish cycle L0 → L5 for one source (§5.3, §5.7.1; S1-02 … S1-04).

:func:`run_pipeline` lands the source drop (L0), validates and reconciles it (L1), and only if L1 holds nothing
back, standardises (L2), pseudonymises (L3) and stages the curated snapshot (L4). The publish gate then decides: on
``PUBLISH`` the snapshot is committed, signed and pinned (L5); on ``HOLD`` nothing is published, the serving pointer
stays on the previous snapshot and a steward notice is rendered and returned. Every stage emits OpenLineage events.

Workdir layout::

    l0/                      landing zone (Z-IDN, D4, write-once)
    l1/<source>/<batch>/     validation report, quarantine sets (D4)
    l2/<source>/<cycle>/     L2 working set (D4: working tokens, not pids)
    vault/mpi.sqlite         MPI stand-in for tb-vault (Z-IDN)
    l4/                      curated snapshots (Z-PSN, D3), l4/lake = the v1 lake
    l5/                      serving pointer and pin history
    gates/, notices/         publish-gate records and rendered steward notices
    lineage/events.jsonl     OpenLineage run events (append-only, no PHI)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from tb_common.crypto import ed25519_generate
from tb_contracts.landing import (
    D3,
    D4,
    ConnectorKind,
    ControlTotals,
    Equation,
    GateOutcome,
    L0BatchManifest,
    PublishGateRecord,
    ReconciliationRecord,
    ServingPointer,
    SnapshotManifest,
    StewardNotice,
    ValidationReport,
)

from dataplat import curated
from dataplat.common import Clock, iso_utc, run_uuid, stable_id, utc_now, write_json
from dataplat.contracts import DEMO_HIS, MIMIC_FHIR, DataContract, load_contracts
from dataplat.landing import LandingZone, iter_rows, read_drop
from dataplat.lineage import LineageCheck, LineageLog, check_complete, dataset, facet
from dataplat.mpi import MergeEvent, Mpi, SiteKeys
from dataplat.pseudonymise import L3Output, pseudonymise
from dataplat.publish import GateInputs, evaluate
from dataplat.reconcile import compute_totals, record
from dataplat.serving import Serving
from dataplat.standardise import (
    V1_DEMO_MAPPING,
    L2Output,
    profile_check,
    standardise_mimic,
    standardise_tabular,
    write_working_set,
)
from dataplat.validate import L1Result, validate_batch
from dataplat.validate.notify import render_notice

log = logging.getLogger("dataplat")
SourceKind = Literal["csv", "mimic_fhir"]
DEFAULT_RESEARCH_OFFICE = ("research-office@site-a.example",)

# MIMIC demo defaults, as in tools/open_data_e2e.py (run date 2026-10-01, 36-month FEAS lookback)
MIMIC_RUN_DATE = date(2026, 10, 1)
MIMIC_LOOKBACK_MONTHS = 36
MIMIC_TZ = "America/New_York"


def mimic_default_window(
    run_date: date = MIMIC_RUN_DATE, lookback_months: int = MIMIC_LOOKBACK_MONTHS
) -> tuple[date, date]:
    """The normaliser window of the open-data end-to-end run: last encounters land inside the FEAS lookback."""
    from tb_common.timeutil import add_months, month_ends

    idx = month_ends(run_date, lookback_months)
    return add_months(idx[0], -1) + timedelta(days=45), idx[-1] - timedelta(days=20)


@dataclass
class PipelineResult:
    cycle_id: str
    source: str
    outcome: GateOutcome
    gate: PublishGateRecord
    batch: L0BatchManifest | None
    landing_created: bool
    validation: ValidationReport | None
    reconciliation: ReconciliationRecord | None  # cycle-level equations L1 → L4
    notice: StewardNotice | None
    manifest: SnapshotManifest | None
    current: ServingPointer | None
    lineage: LineageCheck | None
    workdir: Path
    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    drops: dict[str, int] = field(default_factory=dict)
    quarantine: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def published(self) -> bool:
        return self.outcome in ("PUBLISH", "PUBLISH_WITH_WARNINGS", "OVERRIDE")

    @property
    def blocking_reasons(self) -> list[str]:
        return [r.value for r in self.gate.blocking_reasons]


def _signing_key(workdir: Path) -> tuple[bytes, bytes]:
    d = workdir / "keys"
    priv, pub = d / "snapshot_ed25519.pem", d / "snapshot_ed25519.pub"
    if not priv.exists():
        d.mkdir(parents=True, exist_ok=True)
        p, q = ed25519_generate()
        priv.write_bytes(p)
        priv.chmod(0o600)
        pub.write_bytes(q)
    return priv.read_bytes(), pub.read_bytes()


def _extract_totals(drop_files: dict[str, Path], contracts: dict[str, DataContract]) -> dict[str, ControlTotals]:
    """Totals taken by the connector from the same bytes it lands (origin ``extract``)."""
    out: dict[str, ControlTotals] = {}
    for table, path in sorted(drop_files.items()):
        c = contracts.get(table)
        if c is None:
            continue
        out[table] = compute_totals(iter_rows(path.read_bytes(), path.name), c.keys.patient, c.keys.watermark)
    return out


class _Cycle:
    """State of one run; keeps :func:`run_pipeline` readable."""

    def __init__(self, workdir: Path, source: str, site_id: str, clock: Clock, tz: str) -> None:
        self.workdir = workdir
        self.source = source
        self.clock = clock
        self.lineage = LineageLog(workdir / "lineage" / "events.jsonl", site_id, clock)
        self.serving = Serving(workdir / "l5", workdir / "l4", workdir / "l4" / "lake", tz=tz, clock=clock)
        self.run_ids: list[str] = []
        self.cycle_id = ""

    def run(self, job: str, key: str, **kw: Any) -> str:
        rid = self.lineage.run(job, cycle_id=self.cycle_id, key=key, **kw)
        self.run_ids.append(rid)
        return rid


def run_pipeline(
    source_dir: Path,
    workdir: Path,
    *,
    source: str | None = None,
    kind: SourceKind = "csv",
    site_id: str | None = None,
    site_key: bytes,
    snapshot: str | None = None,
    clock: Clock = utc_now,
    tz: str | None = None,
    contracts_dir: Path | None = None,
    mapping_path: Path = V1_DEMO_MAPPING,
    merges: Sequence[MergeEvent] = (),
    id_factory: Callable[[], str] | None = None,
    signing_key: tuple[bytes, bytes] | None = None,
    research_office: Sequence[str] = DEFAULT_RESEARCH_OFFICE,
    mimic_window: tuple[date, date] | None = None,
) -> PipelineResult:
    """Drive one publish cycle L0 → L5 for ``source_dir`` (synthetic CSV site or MIMIC-IV FHIR demo)."""
    source = source or ("demo_his" if kind == "csv" else "mimic_fhir")
    site_id = site_id or ("DEMO-A" if kind == "csv" else "MIMIC-DEMO")
    tz = tz or ("Asia/Taipei" if kind == "csv" else MIMIC_TZ)
    contracts = load_contracts(contracts_dir or (DEMO_HIS if kind == "csv" else MIMIC_FHIR))
    keys = SiteKeys.derive(site_key, site_id)
    signing = signing_key or _signing_key(workdir)
    started = clock()
    snap = snapshot or started.astimezone(ZoneInfo(tz)).date().isoformat()
    cyc = _Cycle(workdir, source, site_id, clock, tz)

    def key_hasher(value: str) -> str:
        return "k_" + hmac.new(keys.k_lookup, f"example|{value}".encode(), hashlib.sha256).hexdigest()[:16]

    # ------------------------------------------------------------------------------------------------ L0
    if kind == "mimic_fhir" and (source_dir / "fhir").is_dir():
        source_dir = source_dir / "fhir"
    drop = read_drop(source_dir)
    totals, origin = (drop.control_totals, "source") if drop.control_totals is not None else (None, "extract")
    if totals is None:
        totals = _extract_totals(drop.files, contracts)
    zone = LandingZone(workdir / "l0", clock)
    landed = zone.land(
        source,
        drop.files,
        kind=ConnectorKind.FILE_DROP if kind == "csv" else ConnectorKind.FHIR_BULK,
        extract_time=started,
        control_totals=totals,
        control_totals_origin=origin,
    )
    m0 = landed.manifest
    gates_dir = workdir / "gates"
    seq = len(list(gates_dir.glob("*.json"))) if gates_dir.exists() else 0
    cyc.cycle_id = stable_id("cyc", source, m0.batch_id, snap, seq)
    current_before = cyc.serving.current()
    l0_out = {
        o.table: dataset(
            "file://tb/l0-idn",
            f"{source}/{m0.batch_id}/{o.table}",
            {
                "schema": facet("schema", fields=[{"name": c.name, "type": c.type} for c in o.columns]),
                "tb_controlTotals": facet(
                    "tb_controlTotals",
                    origin=m0.control_totals_origin,
                    **(totals.get(o.table, ControlTotals(rows=0)).model_dump(mode="json")),
                ),
                "tb_dataClass": facet("tb_dataClass", data_class=D4.tag),
            },
        )
        for o in m0.objects
    }
    cyc.run(
        f"tb.l0.land.{source}",
        m0.batch_id,
        inputs=[dataset(f"file://{source}", p.name) for p in drop.files.values()],
        outputs=list(l0_out.values()),
        run_facets={"tb_batch": facet("tb_batch", batch_id=m0.batch_id, sha256=m0.sha256, created=landed.created)},
    )

    # ------------------------------------------------------------------------------------------------ L1
    l1: L1Result = validate_batch(
        zone, m0, contracts, key_hasher=key_hasher, clock=clock, out_dir=workdir / "l1" / source / m0.batch_id
    )
    rep = l1.report
    l1_out: dict[str, dict[str, Any]] = {}
    for tv in rep.tables:
        out = dataset(
            "file://tb/l1-idn",
            f"{source}/{m0.batch_id}/{tv.table}/accepted",
            {
                "dataQualityAssertions": facet(
                    "dataQualityAssertions",
                    assertions=[
                        {
                            "assertion": c.rule_id,
                            "success": c.result == "pass",
                            **({"column": c.field} if c.field else {}),
                        }
                        for c in tv.checks
                    ],
                ),
                "tb_contract": facet("tb_contract", contract_id=tv.contract_id, version=tv.contract_version),
                "tb_quarantine": facet(
                    "tb_quarantine", landed=tv.landed, accepted=tv.accepted, quarantined=tv.quarantined
                ),
            },
        )
        l1_out[tv.table] = out
        cyc.run(
            f"tb.l1.validate.{source}.{tv.table}",
            f"{m0.batch_id}/{tv.table}",
            inputs=[l0_out[tv.table]] if tv.table in l0_out else [],
            outputs=[out],
        )
    quarantine = {tv.table: dict(tv.quarantine_by_reason) for tv in rep.tables if tv.quarantined}

    def hold(gate: PublishGateRecord, extra: Sequence[str] = ()) -> PipelineResult:
        cyc.serving.hold(f"hold:{gate.gate_id}")
        notice = render_notice(gate, [rep], {source: contracts}, research_office=research_office, extra_reasons=extra)
        write_json(workdir / "notices" / f"{notice.notice_id}.json", notice.model_dump(mode="json"))
        write_json(gates_dir / f"{seq:06d}_{gate.gate_id}.json", gate.model_dump(mode="json"))
        cyc.run(
            "tb.l4.publish",
            cyc.cycle_id,
            inputs=list(l1_out.values()),
            failed=f"HOLD: {', '.join(r.value for r in gate.blocking_reasons)}",
            run_facets={"tb_gate": facet("tb_gate", gate_id=gate.gate_id, outcome=gate.outcome)},
        )
        return PipelineResult(
            cycle_id=cyc.cycle_id,
            source=source,
            outcome=gate.outcome,
            gate=gate,
            batch=m0,
            landing_created=landed.created,
            validation=rep,
            reconciliation=cycle_rec,
            notice=notice,
            manifest=None,
            current=cyc.serving.current(),
            lineage=None,
            workdir=workdir,
            counts=counts,
            drops=drops,
            quarantine=quarantine,
        )

    counts: dict[str, dict[str, int]] = {"L0": {o.table: o.rows for o in m0.objects}}
    drops: dict[str, int] = {}
    cycle_rec: ReconciliationRecord | None = None
    cur_label = current_before.snapshot_id if current_before else None
    if rep.blocked:
        gate = evaluate(
            GateInputs(cycle_id=cyc.cycle_id, reports=[rep], required_sources=[source]),
            decided_at=clock(),
            current_before=cur_label,
        )
        return hold(gate)

    # ------------------------------------------------------------------------------------------------ L2–L4
    stage_errors: list[str] = []
    l2: L2Output | None = None
    l3: L3Output | None = None
    staged: curated.Staged | None = None
    equations: list[Equation] = []
    try:
        if kind == "csv":
            l2 = standardise_tabular(source, l1.accepted, k_l2=keys.k_l2, site_id=site_id, mapping_path=mapping_path)
        else:
            ws, we = mimic_window or mimic_default_window()
            l2 = standardise_mimic(source, l1.accepted, k_l2=keys.k_l2, window_start=ws, window_end=we)
        profile_check(l2)
        write_working_set(l2, workdir / "l2" / source / cyc.cycle_id)
        equations += l2.equations
        drops = dict(l2.drops)
        counts["L2"] = l2.counts
        l2_out = dataset(
            "file://tb/l2-idn",
            f"{source}/{cyc.cycle_id}",
            {
                "tb_mappingSpec": facet("tb_mappingSpec", sha256=l2.mapping_spec),
                "tb_dataClass": facet("tb_dataClass", data_class=D4.tag),
            },
        )
        cyc.run(
            f"tb.l2.standardise.{source}",
            cyc.cycle_id,
            inputs=[d for t, d in sorted(l1_out.items()) if t in l1.accepted],
            outputs=[l2_out],
            run_facets={
                "tb_validation": facet(
                    "tb_validation", error_pct=l2.validation_error_pct, sampled=l2.validation_sampled
                )
            },
        )
        with Mpi(workdir / "vault" / "mpi.sqlite", keys, clock=clock, id_factory=id_factory) as mpi:
            l3 = pseudonymise(l2, mpi, merges=merges)
        equations += l3.equations
        counts["L3"] = l3.counts
        write_json(
            workdir / "l3" / cyc.cycle_id / "identity_quarantine.json",
            [{"resourceType": t, "id": i, "reason": r} for t, i, r in l3.quarantined],
        )
        l3_out = dataset("file://tb/l3-psn", cyc.cycle_id, {"tb_dataClass": facet("tb_dataClass", data_class=D3.tag)})
        cyc.run(
            "tb.l3.pseudonymise",
            cyc.cycle_id,
            inputs=[l2_out],
            outputs=[l3_out],
            run_facets={
                "tb_identity": facet(
                    "tb_identity", persons=l3.persons, merged=l3.merged, quarantined=len(l3.quarantined)
                )
            },
        )
        previous = cyc.serving.manifest() if current_before else None
        staged = curated.stage(l3, workdir / "l4", snap, previous)
        equations += staged.equations
    except Exception as exc:
        stage_errors.append(f"{type(exc).__name__}: {exc}")
        log.exception("dataplat cycle %s: stage failed", cyc.cycle_id)
    cycle_rec = record("cycle", cyc.cycle_id, equations)
    ceiling = max((c.validation_max_pct for c in contracts.values()), default=0.5)
    gate = evaluate(
        GateInputs(
            cycle_id=cyc.cycle_id,
            reports=[rep],
            required_sources=[source],
            reconciliations=[cycle_rec],
            validation_error_pct={source: (l2.validation_error_pct, ceiling)} if l2 else None,
            identity_quarantine=(len(l3.quarantined), l3.total_in) if l3 else None,
            snapshot_balanced=staged.balanced if staged else None,
            stage_errors=stage_errors,
        ),
        decided_at=clock(),
        current_before=cur_label,
    )
    if gate.outcome == "HOLD" or staged is None or l3 is None:
        if staged is not None:
            curated.discard(staged)
        return hold(gate, stage_errors)

    # ------------------------------------------------------------------------------------------------ commit + L5
    publish_rid = cyc.cycle_id
    later_runs = [
        run_uuid("tb.l4.publish", cyc.cycle_id, publish_rid),
        run_uuid("tb.l5.serve.duckdb", cyc.cycle_id, staged.snapshot_id),
    ]
    try:
        manifest = curated.commit(
            staged,
            workdir / "l4",
            workdir / "l4" / "lake",
            tz=tz,
            created_at=clock(),
            signing_key=signing,
            fields={
                "cycle_id": cyc.cycle_id,
                "contracts": {
                    c.contract_id: c.version for c in sorted(contracts.values(), key=lambda c: c.contract_id)
                },
                "mapping_spec": {source: l2.mapping_spec} if l2 else {},
                "data_cut_per_source": {source: iso_utc(m0.extract_time)},
                "batches": [m0.batch_id],
                "publish_gate": gate.gate_id,
                "reconciliation": sorted([rep.reconciliation.record_id, cycle_rec.record_id]),
                "previous_snapshot": cur_label,
                "warnings": gate.warnings,
                "lineage_runs": sorted(cyc.run_ids + later_runs),
                "data_class": D3,
            },
        )
    except Exception as exc:
        curated.discard(staged)
        gate = evaluate(
            GateInputs(
                cycle_id=cyc.cycle_id,
                reports=[rep],
                required_sources=[source],
                reconciliations=[cycle_rec],
                stage_errors=[f"commit: {type(exc).__name__}: {exc}"],
            ),
            decided_at=clock(),
            current_before=cur_label,
        )
        return hold(gate, [f"commit failed: {exc}"])
    l4_out = dataset(
        "lake://tb/psn",
        manifest.snapshot_id,
        {
            "tb_snapshot": facet(
                "tb_snapshot", snapshot_id=manifest.snapshot_id, manifest_sha=curated.manifest_sha(manifest)
            ),
            "tb_dataClass": facet("tb_dataClass", data_class=D3.tag),
        },
    )
    cyc.run(
        "tb.l4.publish",
        publish_rid,
        inputs=[l3_out],
        outputs=[l4_out],
        run_facets={"tb_gate": facet("tb_gate", gate_id=gate.gate_id, outcome=gate.outcome)},
    )
    ptr = cyc.serving.pin(manifest, f"publish:{gate.gate_id}")
    cyc.run(
        "tb.l5.serve.duckdb",
        manifest.snapshot_id,
        inputs=[l4_out],
        outputs=[dataset("duckdb://tb/psn", manifest.snapshot_id)],
    )
    gate = gate.model_copy(update={"current_after": manifest.snapshot_id})
    write_json(gates_dir / f"{seq:06d}_{gate.gate_id}.json", gate.model_dump(mode="json"))
    counts["L4"] = {t: s.rows for t, s in manifest.tables.items()}
    return PipelineResult(
        cycle_id=cyc.cycle_id,
        source=source,
        outcome=gate.outcome,
        gate=gate,
        batch=m0,
        landing_created=landed.created,
        validation=rep,
        reconciliation=cycle_rec,
        notice=None,
        manifest=manifest,
        current=ptr,
        lineage=check_complete(cyc.lineage.events(), manifest),
        workdir=workdir,
        counts=counts,
        drops=drops,
        quarantine=quarantine,
    )


__all__ = ["MIMIC_TZ", "PipelineResult", "mimic_default_window", "run_pipeline"]
