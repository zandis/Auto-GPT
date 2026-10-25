"""Thin drivers from the bench pages to the pieces already built. Nothing here re-implements a service: each function
calls the real module and shapes its result for a template."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tb_common.policy.classes import Environment, Topology

from tools.testbench.jobs import Log

ROOT = Path(__file__).resolve().parents[2]
SITE_KEY = b"trialbox-testbench-site-key-0123456789ab"
CLASS_TAGS = ("D0", "D1", "D2-L", "D2-K", "D3", "D4")


# ------------------------------------------------------------------------------------------------ data platform
@dataclass
class DataplatRun:
    label: str
    outcome: str
    published: bool
    blocking: list[str]
    counts: dict[str, dict[str, int]]
    conditions: list[dict[str, Any]]
    tables: list[dict[str, Any]]
    quarantine: dict[str, dict[str, int]]
    notice: dict[str, Any] | None
    current_before: str | None
    current_after: str | None
    lineage_complete: bool | None
    lineage_missing: list[str]
    equations: list[dict[str, Any]]


@dataclass
class DataplatResult:
    defect: str
    defect_table: str = ""
    expected_reason: str = ""
    runs: list[DataplatRun] = field(default_factory=list)
    lineage_jobs: list[dict[str, Any]] = field(default_factory=list)


DEFECT_TABLE: dict[str, tuple[str, str | None]] = {
    "row_drop": ("lab", None),
    "type_drift": ("vital", "weight_kg"),
    "duplicate_key": ("encounter", None),
    "null_identifier": ("diagnosis", None),
    "control_total_mismatch": ("medication", None),
}


def _dp_run(label: str, res: Any) -> DataplatRun:
    rep = res.validation
    eqs = []
    for rec in [rep.reconciliation if rep else None, res.reconciliation]:
        if rec is not None:
            eqs += [
                {
                    "level": e.level,
                    "table": e.table or "",
                    "name": e.name,
                    "verdict": e.verdict,
                    "lhs": e.lhs,
                    "rhs": e.rhs,
                }
                for e in rec.equations
            ]
    return DataplatRun(
        label=label,
        outcome=str(res.outcome),
        published=bool(res.published),
        blocking=list(res.blocking_reasons),
        counts=res.counts,
        conditions=[c.model_dump(mode="json") for c in res.gate.conditions],
        tables=[
            {
                "table": t.table,
                "landed": t.landed,
                "accepted": t.accepted,
                "quarantined": t.quarantined,
                "drift": t.drift,
                "findings": [f"{f.reason.value} ({f.severity.value}): {f.detail}" for f in t.findings],
            }
            for t in (rep.tables if rep else [])
        ],
        quarantine=res.quarantine,
        notice={"to": res.notice.to, "cc": res.notice.cc, "subject": res.notice.subject, "body": res.notice.body}
        if res.notice
        else None,
        current_before=res.gate.current_before,
        current_after=res.gate.current_after,
        lineage_complete=res.lineage.complete if res.lineage else None,
        lineage_missing=list(res.lineage.missing) if res.lineage else [],
        equations=eqs,
    )


def run_dataplat(source: Path, defect: str, log: Log, workdir: Path) -> DataplatResult:
    """Baseline publish of the synthetic site, then (optionally) the same drop with one planted defect."""
    from dataplat.common import fixed_clock
    from dataplat.contracts import DEMO_HIS, load_contracts
    from dataplat.pipeline import run_pipeline
    from tb_testkit.defects import Defect, plant, write_source_totals

    if defect and defect not in DEFECT_TABLE:
        raise ValueError(f"unknown defect {defect!r}")
    drop = workdir / "drop"
    shutil.copytree(source, drop)
    contracts = load_contracts(DEMO_HIS)
    write_source_totals(drop, {t: (c.keys.patient, c.keys.watermark) for t, c in contracts.items()})
    work = workdir / "work"
    out = DataplatResult(defect=defect or "none")
    log("cycle 1: clean drop, snapshot 2026-10-04")
    r1 = run_pipeline(
        drop, work, site_key=SITE_KEY, clock=fixed_clock(datetime(2026, 10, 4, 2, 0, tzinfo=UTC)), snapshot="2026-10-04"
    )
    log(f"cycle 1: {r1.outcome}")
    out.runs.append(_dp_run("cycle 1 (clean)", r1))
    if defect:
        table, column = DEFECT_TABLE[defect]
        planted = plant(Defect(defect), drop, table, column)
        out.defect_table, out.expected_reason = table, planted.expected_reason.value
        log(f"planted {defect} in {table}; expected reason {planted.expected_reason.value}")
        r2 = run_pipeline(
            drop,
            work,
            site_key=SITE_KEY,
            clock=fixed_clock(datetime(2026, 10, 5, 2, 0, tzinfo=UTC)),
            snapshot="2026-10-05",
        )
        log(f"cycle 2: {r2.outcome} {r2.blocking_reasons}")
        out.runs.append(_dp_run(f"cycle 2 ({defect})", r2))
    events = work / "lineage" / "events.jsonl"
    if events.exists():
        for line in events.read_text(encoding="utf-8").splitlines():
            ev = json.loads(line)
            out.lineage_jobs.append(
                {
                    "eventType": ev.get("eventType"),
                    "job": ev.get("job", {}).get("name"),
                    "inputs": len(ev.get("inputs") or []),
                    "outputs": len(ev.get("outputs") or []),
                }
            )
    return out


# ------------------------------------------------------------------------------------------------ gateway
def route_table(
    environment: Environment, topology: Topology, *, cloud_opt_in: bool = False, profile: str = "P-GB10"
) -> tuple[list[str], list[tuple[str, list[tuple[bool, str]]]], str]:
    """role × class for one topology: each cell is (allowed, ``route → alias@endpoint`` or the refusal code)."""
    from gateway.policy import Refusal, RoutingPolicy, parse_label

    policy = RoutingPolicy.load()
    rows: list[tuple[str, list[tuple[bool, str]]]] = []
    for role in policy.roles:
        cells: list[tuple[bool, str]] = []
        for tag in CLASS_TAGS:
            try:
                route, cands = policy.candidates(
                    role, parse_label(tag), topology, environment, profile, cloud_opt_in=cloud_opt_in
                )
                cells.append((True, f"{route.id}: " + ", ".join(f"{c.alias}@{c.endpoint.name}" for c in cands)))
            except Refusal as r:
                cells.append((False, r.reason))
        rows.append((role, cells))
    return list(CLASS_TAGS), rows, policy.version


@dataclass
class PromptOutcome:
    status: int
    allowed: bool
    code: str
    body: dict[str, Any]
    audit: list[dict[str, Any]]
    audit_ok: bool
    audit_detail: str


def send_test_prompt(
    note_text: str, data_class: str, environment: Environment, topology: Topology, audit_dir: Path
) -> PromptOutcome:
    """One judge call through tb-gateway with the in-process deterministic stub as the upstream."""
    from fastapi.testclient import TestClient
    from gateway.core import Gateway, GatewayConfig
    from gateway.policy import RoutingPolicy
    from guard.guard import Guard
    from llm_stub.app import app as stub
    from registry.registry import Registry
    from tb_common.audit import AuditLog, verify
    from tb_common.llm import load_prompt, render
    from tb_contracts import inline_schema
    from tb_llm import json_schema_format

    gw = Gateway(
        RoutingPolicy.load(),
        Registry.load(),
        AuditLog(audit_dir),
        GatewayConfig(topology=topology, environment=environment),
        http=TestClient(stub),
        guard=Guard(None),
        env={},
    )
    p = load_prompt("judge")
    variables = {
        "criterion_text": "Current gout flare",
        "note_question": "Is the patient currently (ongoing) having a gout flare?",
        "index_date": "2026-10-05",
        "excerpts": [{"date": "2026-10-01", "note_type": "progress", "text": note_text}],
    }
    body = {
        "messages": render(p, variables),
        "response_format": json_schema_format("judge", inline_schema(p.meta.output_schema)),
        "max_tokens": 512,
    }
    headers = {
        "X-TB-Caller": "testbench",
        "X-TB-Role": "judge",
        "X-TB-Data-Class": data_class,
        "X-TB-Purpose": "development",
        "X-TB-Study": "TESTBENCH",
        "X-TB-Step": "testbench-1",
        "X-TB-Context-Of-Use": "s3_note_judgement",
        "X-TB-Prompt": "judge@3",
    }
    res = gw.chat(headers, body)
    records = [
        json.loads(x) for f in sorted(audit_dir.glob("*.jsonl")) for x in f.read_text(encoding="utf-8").splitlines()
    ]
    v = verify(audit_dir)
    code = (
        str(res.body.get("error", {}).get("code", ""))
        if res.status != 200
        else str(res.body.get("tb", {}).get("route_id", ""))
    )
    return PromptOutcome(res.status, res.status == 200, code, res.body, records[-5:], bool(v.ok), str(v))


def registry_view() -> tuple[str, list[dict[str, Any]], dict[str, str]]:
    from registry.registry import CARDS_DIR, Registry

    reg = Registry.load()
    cards: dict[str, str] = {}
    for p in sorted(CARDS_DIR.glob("*.md")):
        cards[p.stem] = p.read_text(encoding="utf-8")
    return reg.version, reg.table(), cards


# ------------------------------------------------------------------------------------------------ guard
def guard_redact(text: str) -> dict[str, Any]:
    from guard.guard import Guard

    g = Guard(None)
    verdict = g.tripwire(text)
    return {
        "redacted": g.redact(text),
        "hit": verdict.hit,
        "kinds": list(verdict.kinds),
        "count": verdict.count,
        "spans": [
            {"kind": f.kind, "start": f.start, "end": f.end, "text": text[f.start : f.end], "valid": f.valid}
            for f in verdict.findings
        ],
    }


# ------------------------------------------------------------------------------------------------ recall
@dataclass
class RecallResult:
    reps: int
    months: int
    per_month: int
    alpha: float
    rates: list[dict[str, float]]
    trajectory_rate: float
    trajectory_ledger: int
    trajectory: list[dict[str, float]]


def run_recall(reps: int, months: int, per_month: int, rate: float, log: Log, workdir: Path) -> RecallResult:
    """The recall_cert simulation through the ledger, plus one ledger's per-look bounds (CS vs repeated CP)."""
    import functools

    from orchestrator.db_pg import SqliteBackend
    from orchestrator.recall import RecallLedger
    from orchestrator.recall import sim as rsim
    from tb_common.recall import cp_upper
    from tb_contracts.recall import RecallCell, Stratum

    base = rsim.SimConfig()
    rates = tuple(sorted({*base.rates, rate}))
    cfg = rsim.SimConfig(
        rates=rates, reps=reps, months=months, per_month=per_month, seed=base.seed, alpha=base.alpha, workers=1
    )
    log(f"simulating {reps} ledgers × {months} looks × {per_month} draws for p in {list(rates)} (seed {cfg.seed})")
    results = rsim.run(cfg, workdir)
    for r in results:
        log(f"p={r.rate}: repeated CP miss {r.cp_miss:.3f}, CS miss {r.cs_miss:.3f}")
    # one ledger at the chosen rate: the first one repeated CP misses, else ledger 0
    chosen = next(r for r in results if r.rate == rate)
    idx = next((i for i, (cp_ok, _cs) in enumerate(chosen.per_ledger) if not cp_ok), 0)
    batches = rsim.draw_batches(cfg)[rate][idx]
    cell = RecallCell(canonical_hash=f"traj-{rate!r}-{idx:04d}", stratum=Stratum.S1_AFFIRMATIVE)
    traj: list[dict[str, float]] = []
    db = str(workdir / "trajectory.db")
    for m, batch in enumerate(batches):
        backend = SqliteBackend(db)
        try:
            ledger = RecallLedger(backend, clock=functools.partial(rsim._month, m))
            ledger.append(rsim._observations(cell, idx, m, batch))
            counts = ledger.counts(cell)
            traj.append(
                {
                    "look": m + 1,
                    "n": counts.n,
                    "found": counts.found,
                    "cs_upper": ledger.upper(cell, cfg.alpha),
                    "cp_upper": cp_upper(counts.found, counts.n, cfg.alpha),
                }
            )
        finally:
            backend.close()
    return RecallResult(
        reps=reps,
        months=months,
        per_month=per_month,
        alpha=cfg.alpha,
        rates=[{"rate": r.rate, "cp_miss": r.cp_miss, "cs_miss": r.cs_miss} for r in results],
        trajectory_rate=rate,
        trajectory_ledger=idx,
        trajectory=traj,
    )


def trajectory_svg(traj: list[dict[str, float]], rate: float, width: int = 640, height: int = 260) -> str:
    """Inline SVG: CS upper bound and repeated Clopper–Pearson upper bound per look, with the true p."""
    if not traj:
        return ""
    pad = 40
    ymax = max(0.05, *(t["cs_upper"] for t in traj), *(t["cp_upper"] for t in traj), rate * 1.5)
    n = len(traj)

    def x(i: int) -> float:
        return pad + (width - 2 * pad) * (i / max(1, n - 1))

    def y(v: float) -> float:
        return height - pad - (height - 2 * pad) * (v / ymax)

    def line(key: str) -> str:
        return " ".join(f"{x(i):.1f},{y(t[key]):.1f}" for i, t in enumerate(traj))

    ticks = "".join(
        f'<text x="{pad - 6}" y="{y(v) + 4:.1f}" text-anchor="end" class="tick">{v:.2f}</text>'
        for v in (0.0, ymax / 2, ymax)
    )
    looks = "".join(
        f'<text x="{x(i):.1f}" y="{height - pad + 16}" text-anchor="middle" class="tick">{t["look"]:.0f}</text>'
        for i, t in enumerate(traj)
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="upper bounds per look" class="chart">'
        f'<line x1="{pad}" y1="{y(rate):.1f}" x2="{width - pad}" y2="{y(rate):.1f}" class="truth"/>'
        f'<polyline points="{line("cp_upper")}" class="cp"/>'
        f'<polyline points="{line("cs_upper")}" class="cs"/>'
        f"{ticks}{looks}"
        f'<text x="{width - pad}" y="{y(rate) - 6:.1f}" text-anchor="end" class="tick">true p = {rate}</text>'
        "</svg>"
    )


# ------------------------------------------------------------------------------------------------ registry match
def run_registry_match(note: str, use_open_data: bool, synthetic: bool, top_k: int) -> dict[str, Any]:
    """TrialGPT-port matching over a local mirror (cached CT.gov records and/or the synthetic test trials) with the
    deterministic mock chat from ``tests/registry_match_mock.py``; lexical retrieval only (no model download)."""
    from matching.registry_match import pipeline
    from matching.registry_match.llm import LLMClient
    from matching.registry_mirror import RegistryMirror
    from matching.registry_mirror.mirror import MirrorRecord

    from tests.registry_match_mock import MockChat, study

    records: list[MirrorRecord] = []
    if use_open_data:
        od = ROOT / "tests" / "fixtures" / "open_data"
        cached = RegistryMirror.from_dir(od, "ctgov_*.json")
        ids = sorted(p.stem.removeprefix("ctgov_") for p in od.glob("ctgov_*.json"))
        records += [r for r in (cached.record(n) for n in ids) if r is not None]
    if synthetic:
        crit = "Inclusion Criteria:\n\n* Gout\n* Serum urate above 6\n\nExclusion Criteria:\n\n* Pregnancy"
        records += [
            MirrorRecord("NCT00000010", study("NCT00000010", "Gout flares", ["Gout"], crit, countries=["France"])),
            MirrorRecord("NCT00000011", study("NCT00000011", "Gout urate", ["Gout"], crit, countries=["Taiwan"])),
            MirrorRecord(
                "NCT00000014", study("NCT00000014", "Women only", ["Lupus"], crit + "\n* NEGATIVE marker", sex="FEMALE")
            ),
        ]
    if not records:
        raise ValueError("choose at least one mirror source")
    mirror = RegistryMirror(records)
    chat = MockChat()
    # LLMClient writes no cache by default (prompts carry the note), so nothing of the run is stored
    run = pipeline.run_patient(
        note, client=LLMClient(chat), mirror=mirror, recruiting_only=False, dense=False, top_k=top_k
    )
    return {
        "manifest": mirror.manifest().__dict__,
        "keywords": run.keywords,
        "candidates": run.candidates,
        "retrieved": run.retrieved,
        "ranked": [
            {
                "nct_id": m.nct_id,
                "title": run.trials.get(m.nct_id, {}).get("brief_title", ""),
                "score": round(m.score, 3),
                "matching": round(m.matching_score, 3),
                "aggregation": round(m.aggregation_score, 3),
                "criteria": [{"kind": c.kind, "text": c.criterion[:140], "label": c.label} for c in m.criteria],
                "errors": m.errors,
            }
            for m in run.ranked
        ],
        "llm_calls": len(chat.calls),
    }


__all__ = [
    "CLASS_TAGS",
    "DEFECT_TABLE",
    "guard_redact",
    "registry_view",
    "route_table",
    "run_dataplat",
    "run_recall",
    "run_registry_match",
    "send_test_prompt",
    "trajectory_svg",
]
