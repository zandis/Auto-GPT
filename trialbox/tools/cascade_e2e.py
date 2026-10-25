"""End-to-end run of the MS1 slice: dataplat L0–L5 → cascade S0–S5 → DL-1 feasibility pack + recall certificate.

    from tools.cascade_e2e import run_end_to_end
    result = run_end_to_end(Path("tests/fixtures/.../site-a"), "GZQO", Path("out"))
    result.passed, result.stage_counts, result.artefacts, result.certificate_status

    python -m tools.cascade_e2e --source <dir> --trial GZQO --out <dir>
    python -m tools.cascade_e2e --source .cache/open_data/mimic-iv-fhir-demo --trial EMPULSE --out <dir>

``source_dir`` is a synthetic site drop (CSV, ``tools/make_fixtures.py``) or the MIMIC-IV FHIR demo (detected by its
``fhir/`` folder). ``trial_id`` names a ruleset in ``rulesets/`` or ``tests/fixtures/open_data/rulesets/``. Only D0
datasets of ``eval/DATASETS.yaml`` are accepted, and the tool refuses to run unless ``TB_ENV`` is unset, ``DEV`` or
``TEST``. The model path is the in-process ``tb-gateway`` in front of the deterministic ``llm_stub`` (no network) by
default. With ``TB_GATEWAY_URL`` set (e.g. ``http://127.0.0.1:8020/v1``, the compose ``gateway`` service), every judge
call goes to that gateway instead, as caller ``orchestrator``; with ``TB_GATEWAY_VERIFIER_URL`` also set (and optionally
``TB_GATEWAY_VERIFIER_MODEL`` / ``TB_GATEWAY_VERIFIER_EXPECT_SHA``) the judge is the two-model
:class:`matching.cascade.judge.AgreementJudge`: a criterion blocks only when the verifier build agrees;
``TB_GATEWAY_MODEL`` names the alias to ask for (``j-workhorse`` for the on-box build once pinned, unset for the stub)
and ``TB_GATEWAY_EXPECT_SHA`` makes the run fail unless every answer came from the build with that sha256 (the
``gateway_build_pinned`` check).

Outputs in ``out_dir``: ``dataplat/`` (the publish cycle), ``cascade/`` (D3: traces, review queue, final list,
stage log, manifest block), ``dl1/`` (D1: PDF, XLSX, JSON, figures; plus the INTERNAL exact comparison for these
open/synthetic data), ``recall/`` (ledger and certificate or refusal), ``audit/`` (gateway audit chain),
``e2e_summary.json`` and ``e2e_summary.md``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, cast

ROOT = Path(__file__).resolve().parents[1]
RULESET_DIRS = (ROOT / "rulesets", ROOT / "tests" / "fixtures" / "open_data" / "rulesets")
SITE_KEY = b"trialbox-open-data-demo-key-0123456789abcdef"  # fixed: reproducible pseudonyms (D0 data only)
DATASETS = ROOT / "eval" / "DATASETS.yaml"


class E2EError(RuntimeError):
    pass


@dataclass
class E2EResult:
    """What :func:`run_end_to_end` returns (and writes to ``e2e_summary.json``)."""

    passed: bool
    trial_id: str
    source_kind: str  # "csv" (synthetic site) | "mimic_fhir"
    dataset: str  # eval/DATASETS.yaml key
    out_dir: str
    pipeline: dict[str, Any]  # outcome, snapshot, counts, blocking reasons, lineage
    stage_counts: dict[str, dict[str, Any]]  # S0..S5: patients/pairs in and out, class label, IR hash
    tiers: dict[str, int]
    final_list_size: int
    certificate_status: str  # "issued" | "refused"
    certificate_reasons: list[str]
    certificate_statement: str
    headline: dict[str, Any]  # DL-1 executive-summary numbers (released)
    artefacts: dict[str, str]  # name -> absolute path
    checks: dict[str, bool]  # invariant -> holds
    problems: list[str] = field(default_factory=list)
    seconds: float = 0.0
    gateway: dict[str, Any] = field(default_factory=dict)  # mode, url, model, builds answering, refusals

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ------------------------------------------------------------------------------------------------ helpers
def _check_env() -> None:
    env = os.environ.get("TB_ENV", "TEST")
    if env not in ("DEV", "TEST"):
        raise E2EError(f"cascade_e2e runs only with TB_ENV DEV or TEST (got {env!r}): open and synthetic data only")


def detect_kind(source_dir: Path) -> str:
    if (source_dir / "fhir").is_dir() or any(source_dir.glob("Mimic*.ndjson*")):
        return "mimic_fhir"
    if (source_dir / "patient.csv").exists():
        return "csv"
    raise E2EError(f"{source_dir}: neither a synthetic site drop (patient.csv) nor the MIMIC-IV FHIR demo (fhir/)")


def dataset_for(kind: str) -> tuple[str, str]:
    """(dataset key, data class) from eval/DATASETS.yaml; anything above D0 is refused."""
    import yaml

    key = "mimic_iv_fhir_demo" if kind == "mimic_fhir" else "synthetic_hospitals"
    doc = yaml.safe_load(DATASETS.read_text(encoding="utf-8")) or {}
    cls = str((doc.get("datasets") or {}).get(key, {}).get("data_class", ""))
    if cls != "D0":
        raise E2EError(f"dataset {key} is {cls or 'unregistered'}, the test path accepts D0 only")
    return key, cls


def load_trial(trial_id: str) -> Any:
    from tb_common.ruleset import Ruleset

    for d in RULESET_DIRS:
        if (d / trial_id / "manifest.yaml").exists():
            rs = Ruleset.load(d / trial_id)
            if not rs.sql:
                from criteria_compiler.compile_sql.generator import SqlGenerator
                from criteria_compiler.terminology.mapper import Terminology, ValueSets

                rs.sql = SqlGenerator(rs.id, rs.version, ValueSets(rs.id, rs.valuesets, Terminology())).render(
                    rs.active()
                )
            return rs
    raise E2EError(f"no ruleset {trial_id!r} in {', '.join(str(d) for d in RULESET_DIRS)}")


def local_gateway(audit_dir: Path) -> Any:
    """``tb_llm.GatewayClient`` → in-process ``tb-gateway`` (TEST, topology A) → ``llm_stub``. No network."""
    from fastapi.testclient import TestClient
    from gateway.app import create_app
    from gateway.core import Gateway, GatewayConfig
    from gateway.policy import RoutingPolicy
    from guard.guard import Guard
    from llm_stub.app import app as stub
    from registry.registry import Registry
    from tb_common.audit import AuditLog
    from tb_common.policy.classes import Environment, Topology
    from tb_llm import GatewayClient

    for name in ("gateway", "llm-stub"):  # request logs of the in-process apps
        logging.getLogger(name).setLevel(logging.WARNING)
    gw = Gateway(
        RoutingPolicy.load(),
        Registry.load(),
        AuditLog(audit_dir),
        GatewayConfig(topology=Topology.A, environment=Environment.TEST),
        http=TestClient(stub),
        guard=Guard.from_settings(),
        env={},
    )
    return GatewayClient("http://tb-gateway/v1", "orchestrator", http=TestClient(create_app(gw)))


class RecordingClient:
    """Wraps a ``tb_llm.GatewayClient``: counts calls and records which ``alias:build_sha`` answered each one."""

    def __init__(self, client: Any, mode: str, url: str) -> None:
        self.client = client
        self.mode = mode
        self.url = url
        self.calls = 0
        self.builds: dict[str, int] = {}

    def chat(self, *args: Any, **kwargs: Any) -> Any:
        res = self.client.chat(*args, **kwargs)
        self.calls += 1
        key = f"{res.alias}:{res.build_sha}"
        self.builds[key] = self.builds.get(key, 0) + 1
        return res

    def summary(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "url": self.url,
            "model": getattr(self.client, "model", None),
            "calls": self.calls,
            "builds": dict(sorted(self.builds.items())),
        }


def verifier_client() -> RecordingClient | None:
    """The verifier gateway for the two-model judge (``TB_GATEWAY_VERIFIER_URL``), or None for a single model."""
    url = os.environ.get("TB_GATEWAY_VERIFIER_URL", "").strip()
    if not url:
        return None
    from tb_llm import GatewayClient

    model = os.environ.get("TB_GATEWAY_VERIFIER_MODEL") or os.environ.get("TB_GATEWAY_MODEL") or None
    return RecordingClient(GatewayClient(url, "orchestrator", model=model), "remote-verifier", url)


def gateway_client(audit_dir: Path) -> RecordingClient:
    """The remote gateway at ``TB_GATEWAY_URL`` when set, else :func:`local_gateway` (in process, stub upstream)."""
    url = os.environ.get("TB_GATEWAY_URL", "").strip()
    if url:
        from tb_llm import GatewayClient

        return RecordingClient(
            GatewayClient(url, "orchestrator", model=os.environ.get("TB_GATEWAY_MODEL") or None), "remote", url
        )
    return RecordingClient(local_gateway(audit_dir), "in-process", "")


@dataclass
class _Truth:
    """Synthetic ground truth (``note_truth.json``, ``human_truth.json``) keyed by pid through the MPI stand-in.
    Used only as the simulated adjudicator of the recall audit and as the S5 reviewer. Never on real data."""

    notes: dict[str, dict[str, str]]
    human: dict[str, dict[str, str]]

    @classmethod
    def load(cls, source_dir: Path, workdir: Path, site_id: str) -> _Truth | None:
        nt, ht = source_dir / "note_truth.json", source_dir / "human_truth.json"
        if not nt.exists():
            return None
        from dataplat.mpi import Mpi, SiteKeys

        keys = SiteKeys.derive(SITE_KEY, site_id)
        notes_by_mrn: dict[str, dict[str, str]] = json.loads(nt.read_text("utf-8"))
        human_by_mrn: dict[str, dict[str, str]] = json.loads(ht.read_text("utf-8")) if ht.exists() else {}
        notes: dict[str, dict[str, str]] = {}
        human: dict[str, dict[str, str]] = {}
        with Mpi(workdir / "vault" / "mpi.sqlite", keys) as mpi:
            for mrn in sorted(set(notes_by_mrn) | set(human_by_mrn)):
                mid = mpi.lookup(mrn)
                if mid is None:
                    continue
                pid = mpi.pid(mid)
                notes[pid] = notes_by_mrn.get(mrn, {})
                human[pid] = human_by_mrn.get(mrn, {})
        return cls(notes, human)


def _oracles(truth: _Truth | None, rs: Any, res: Any) -> tuple[Any, Any, list[str]]:
    """Simulated adjudicators for the synthetic site: a pair oracle (was an excluded pair wrongly excluded?) and a
    patient oracle (does the patient meet every automated criterion in truth?). Human criteria are S5's business and
    are not part of the cascade's recall."""
    if truth is None:
        return None, None, []
    kind = {c.id: c.kind for c in rs.active()}

    def eligible_on(pid: str, cid: str) -> bool | None:
        v = truth.notes.get(pid, {}).get(cid)
        if v not in ("yes", "no"):
            return None
        return (v == "yes") if kind.get(cid) == "inclusion" else (v == "no")

    def pair(pid: str, cid: str) -> int | None:
        if cid not in res.note_criteria:
            return 0  # structured: the full-pipeline re-evaluation reads the same records and agrees
        e = eligible_on(pid, cid)
        return None if e is None else int(e)

    def patient(pid: str) -> bool | None:
        t = res.traces.get(pid)
        if t is None or not t.in_scope:
            return None
        if any(o.status == "fail" and o.stage == "S1" for o in t.outcomes.values()):
            return False
        verdicts = [eligible_on(pid, cid) for cid in res.note_criteria]
        if any(v is False for v in verdicts):
            return False
        return None if any(v is None for v in verdicts) else True

    historical = sorted(p for p in truth.notes if patient(p) is True)
    return pair, patient, historical


def _reviewer(truth: _Truth | None, rs: Any) -> Callable[[Any, Any], dict[str, Any]]:
    """Simulated S5 reviewer: resolves open items from the synthetic truth (CRC chart review, patient contact);
    confirms only when every open item resolves to pass. On open data it confirms ``strong`` candidates only."""
    kind = {c.id: c.kind for c in rs.active()}
    truth_human_ids = {cid for h in (truth.human.values() if truth else []) for cid in h}

    def review(item: Any, _trace: Any) -> dict[str, Any]:
        if truth is None:
            return {"decision": "confirm" if item.tier == "strong" else "defer", "by": "simulated CRC (open data)"}
        crit: dict[str, str] = {}
        for cid in [*item.pending_human, *item.uncertain, *item.data_gap]:
            h = truth.human.get(item.pid, {}).get(cid)
            n = truth.notes.get(item.pid, {}).get(cid)
            if h in ("willing", "unwilling"):
                crit[cid] = "pass" if h == "willing" else "fail"
            elif n in ("yes", "no"):
                ok = (n == "yes") if kind.get(cid) == "inclusion" else (n == "no")
                crit[cid] = "pass" if ok else "fail"
            elif cid in item.pending_human and cid not in truth_human_ids:
                crit[cid] = "pass"  # the generator models no truth for this human criterion: assumed met
        open_items = {*item.pending_human, *item.uncertain, *item.data_gap}
        if any(v == "fail" for v in crit.values()):
            decision = "reject"
        elif open_items <= set(crit):
            decision = "confirm"
        else:
            decision = "defer"
        return {"decision": decision, "criteria": crit, "by": "simulated CRC (synthetic truth)"}

    return review


def _data_fitness(pres: Any) -> list[dict[str, Any]]:
    rep = pres.validation
    rows: list[dict[str, Any]] = []
    if rep is None:
        return rows
    for tv in rep.tables:
        failed = [c for c in tv.checks if c.result not in ("pass",)]
        rows.append(
            {
                "domain": tv.table,
                "source": rep.source,
                "coverage_pct": round(100.0 * tv.accepted / tv.landed, 1) if tv.landed else None,
                "completeness_pct_key_vars": None,
                "freshness_days": 0,
                "dq_grade": "A" if not failed else ("B" if tv.quarantined == 0 else "C"),
                "reconciliation_status": rep.reconciliation.status if hasattr(rep.reconciliation, "status") else "ok",
            }
        )
    return rows


# ------------------------------------------------------------------------------------------------ the run
def run_end_to_end(
    source_dir: Path,
    trial_id: str,
    out_dir: Path,
    *,
    recipient_class: str = "external_sponsor",
    kind: str | None = None,
    repro: bool = True,
) -> E2EResult:
    """Run dataplat → cascade → DL-1 pack + recall certificate for one trial; return a PASS/FAIL summary.

    ``recipient_class`` selects the disclosure profile (``external_sponsor`` → ``dc.sponsor``, k = 11;
    ``internal`` → ``dc.internal``, k = 5). ``repro`` re-runs the cascade and the pack and requires an identical
    object hash."""
    from dataplat.common import fixed_clock
    from dataplat.pipeline import mimic_default_window, run_pipeline
    from dataplat.serving import Serving
    from deliverables.disclosure import profile_for, released_ok
    from deliverables.pack import PackInputs, all_released_counts, build_pack
    from deliverables.render import render_all
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from matching.cascade import CascadeConfig, run_cascade, write_outputs
    from matching.cascade.certificate import AuditPlan, certify
    from matching.cascade.judge import AgreementJudge, GatewayJudge
    from matching.cascade.model import STAGES
    from orchestrator.scenarios.feas_compute import FeasParams, compute
    from tb_common.policy.classes import Destination, PolicyError, Topology, lower, may_reach
    from tb_contracts.dataclass import ClassLabel, DataClass

    t0 = time.monotonic()
    _check_env()
    source_dir, out_dir = Path(source_dir).resolve(), Path(out_dir).resolve()
    kind = kind or detect_kind(source_dir)
    if kind not in ("csv", "mimic_fhir"):
        raise E2EError(f"unknown source kind {kind!r}")
    dataset, notes_class = dataset_for(kind)
    out_dir.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    checks: dict[str, bool] = {}
    artefacts: dict[str, str] = {}

    # -------------------------------------------------------------------------------------- dataplat L0–L5
    if kind == "csv":
        meta = json.loads((source_dir / "meta.json").read_text("utf-8")) if (source_dir / "meta.json").exists() else {}
        run_date = date.fromisoformat(str(meta.get("ref_date", "2026-10-05")))
        site_id, tz = str(meta.get("site_id", "DEMO-A")), "Asia/Taipei"
        snapshot = (run_date.fromordinal(run_date.toordinal() - 1)).isoformat()
        window = None
    else:
        run_date, site_id, tz, snapshot = date(2026, 10, 1), "MIMIC-DEMO", "America/New_York", "2026-09-30"
        window = mimic_default_window(run_date)
    workdir = out_dir / "dataplat"
    clock = fixed_clock(datetime(run_date.year, run_date.month, run_date.day, 2, 0, tzinfo=UTC))
    pres = run_pipeline(
        source_dir,
        workdir,
        kind=cast(Literal["csv", "mimic_fhir"], kind),
        site_id=site_id,
        site_key=SITE_KEY,
        snapshot=snapshot,
        clock=clock,
        tz=tz,
        mimic_window=window,
    )
    pipeline = {
        "outcome": pres.outcome,
        "published": pres.published,
        "blocking_reasons": pres.blocking_reasons,
        "snapshot_id": pres.manifest.snapshot_id if pres.manifest else None,
        "lake_tables": pres.manifest.lake_tables if pres.manifest else {},
        "lineage_complete": bool(pres.lineage and pres.lineage.complete),
        "quarantine": pres.quarantine,
    }
    checks["pipeline_published"] = pres.published
    checks["zero_blocking_dq"] = not pres.blocking_reasons
    checks["lineage_complete"] = bool(pres.lineage and pres.lineage.complete)
    if not pres.published or pres.manifest is None:
        problems.append(f"publish gate held the cycle: {pres.blocking_reasons}")
        return _finish(
            out_dir,
            trial_id,
            kind,
            dataset,
            pipeline,
            None,
            {},
            "refused",
            ["no snapshot"],
            "",
            {},
            artefacts,
            checks,
            problems,
            t0,
        )
    serving = Serving(workdir / "l5", workdir / "l4", workdir / "l4" / "lake", tz=tz)
    manifest = serving.manifest()  # DP-32: signature and pin verified before any read
    lake = LakeLocal(workdir / "l4" / "lake", HashEmbedder(), tz)

    # -------------------------------------------------------------------------------------- cascade
    rs = load_trial(trial_id)
    lookback = 36
    if rs.manifest.scopes and rs.manifest.scopes.feas and rs.manifest.scopes.feas.lookback_months:
        lookback = int(rs.manifest.scopes.feas.lookback_months)
    truth = _Truth.load(source_dir, workdir, site_id) if kind == "csv" else None
    client = gateway_client(out_dir / "audit")
    verifier = verifier_client()
    agreement: list[AgreementJudge] = []

    def make_judge() -> Any:
        if verifier is None:
            return GatewayJudge(client)
        j = AgreementJudge(GatewayJudge(client), GatewayJudge(verifier))
        agreement.append(j)
        return j

    def cascade() -> Any:
        cfg = CascadeConfig(
            study_id=trial_id,
            run_date=run_date,
            lookback_months=lookback,
            notes_class=notes_class,
            purpose="feasibility",
            step_id=f"e2e:{trial_id}",
            sample_per_stratum=200,
            snapshot=manifest.snapshot,
        )
        return run_cascade(lake, rs, cfg, judge=make_judge(), embedder=HashEmbedder(), reviewer=_reviewer(truth, rs))

    res = cascade()
    expect_sha = os.environ.get("TB_GATEWAY_EXPECT_SHA", "").strip()
    if expect_sha:
        shas = {k.rsplit(":", 1)[-1] for k in client.builds}
        checks["gateway_build_pinned"] = client.calls > 0 and shas == {expect_sha}
        if not checks["gateway_build_pinned"]:
            problems.append(f"gateway answered with builds {sorted(client.builds)}, expected sha256 {expect_sha}")
    expect_v = os.environ.get("TB_GATEWAY_VERIFIER_EXPECT_SHA", "").strip()
    if verifier is not None and expect_v:
        vshas = {k.rsplit(":", 1)[-1] for k in verifier.builds}
        checks["verifier_build_pinned"] = verifier.calls > 0 and vshas == {expect_v}
        if not checks["verifier_build_pinned"]:
            problems.append(f"verifier answered with builds {sorted(verifier.builds)}, expected sha256 {expect_v}")
    d3 = ClassLabel(data_class=DataClass.D3)
    if not may_reach(d3, Destination.PERIMETER, Topology.A):  # patient-level files stay in the perimeter
        raise PolicyError("D3 patient list may not be written here")
    checks["patient_list_blocked_externally"] = not may_reach(d3, Destination.EXTERNAL_MODEL, Topology.C) and not (
        may_reach(d3, Destination.DEV_PUBLIC, Topology.A)
    )
    for name, path in write_outputs(res, out_dir / "cascade").items():
        artefacts[f"cascade_{name}"] = str(path)
    checks["cas1_stage_order"] = [s.stage for s in res.stages] == list(STAGES)
    after = [res.metrics.n_after[s] for s in ("S0", "S1", "S2", "S2b", "S3", "S4")]
    checks["monotone_funnel"] = after == sorted(after, reverse=True)
    checks["stage_pairs_consistent"] = all(s.pairs_out <= s.pairs_in or s.stage == "S0" for s in res.stages)
    checks["stage_logs_labelled"] = all(s.data_class == "D3" and s.ir_hash == res.ir_hash for s in res.stages)

    # -------------------------------------------------------------------------------------- v1 FEAS cross-check
    raw = None
    try:
        _, raw = compute(lake, rs, FeasParams(run_date=run_date, snapshot=manifest.snapshot, lookback_months=lookback))
        from deliverables import analytics as an

        seq = an.sequential(an.state_matrix(res), res, {})
        cas = {r.criterion_id: r.n_remaining for r in seq if r.stage == "S1"}
        checks["cascade_matches_v1_funnel"] = all(cas.get(k) == v for k, v in raw.remaining.items())
        if not checks["cascade_matches_v1_funnel"]:
            problems.append(f"cascade S1 funnel {cas} differs from v1 FEAS {raw.remaining}")
    except Exception as exc:  # the cross-check is reported, the pack still renders without incidence
        checks["cascade_matches_v1_funnel"] = False
        problems.append(f"v1 FEAS cross-check failed: {type(exc).__name__}: {exc}")

    # -------------------------------------------------------------------------------------- recall certificate
    pair, patient, historical = _oracles(truth, rs, res)
    rdir = out_dir / "recall"
    rdir.mkdir(parents=True, exist_ok=True)
    ledger = rdir / "recall_ledger.sqlite"
    for f in rdir.glob("recall_ledger.sqlite*"):
        f.unlink()
    cert = certify(
        res,
        ledger,
        run_id=f"run:{trial_id}:{manifest.snapshot_id}",
        period=run_date.isoformat()[:7],
        plan=AuditPlan(),
        pair_oracle=pair,
        patient_oracle=patient,
        historical_enrollees=historical,
    )
    cert_path = rdir / ("recall_certificate.json" if cert.status == "issued" else "recall_refusal.json")
    cert_path.write_text(json.dumps(cert.as_pack_input(), indent=1, sort_keys=True, default=str) + "\n", "utf-8")
    artefacts["recall_certificate" if cert.status == "issued" else "recall_refusal"] = str(cert_path)
    artefacts["recall_ledger"] = str(ledger)
    checks["certificate_or_refusal"] = cert.status == "issued" or bool(cert.reasons)

    # -------------------------------------------------------------------------------------- DL-1
    profile = profile_for(recipient_class)

    def pack(result: Any) -> dict[str, Any]:
        return build_pack(
            PackInputs(
                cascade=result,
                ruleset=rs,
                profile=profile,
                site_id=site_id,
                site_name="MIMIC-IV demo (open data)" if kind == "mimic_fhir" else f"Synthetic site {site_id}",
                snapshot_id=manifest.snapshot_id,
                snapshot=manifest.snapshot,
                data_cut=next(iter(manifest.data_cut_per_source.values()), manifest.snapshot),
                run_date=run_date,
                recipient_class=recipient_class,
                feas_raw=raw,
                data_fitness=_data_fitness(pres),
                certificate=cert.as_pack_input(),
                include_exact=True,
            )
        )

    frozen = pack(res)
    obj = frozen["object"]
    lowered = lower(d3, "privacy_accountant", certificate=frozen["sha256"])  # the only way an aggregate leaves D3
    checks["pack_lowered_to_d1"] = lowered.data_class is DataClass.D1 and obj["data_class"] == "D1"
    for name, path in render_all(frozen, out_dir / "dl1", f"DL1_{trial_id}").items():
        artefacts[f"dl1_{name}"] = str(path)
    released = all_released_counts(obj)
    checks["small_cells_released"] = all(released_ok(v, profile) for v in released)
    if not checks["small_cells_released"]:
        problems.append(
            f"released counts violate {profile.name}: {[v for v in released if not released_ok(v, profile)][:10]}"
        )
    checks["disclosure_trace_complete"] = [s["step"] for s in obj["disclosure_trace"]["steps"]].__len__() == 8
    text = Path(artefacts["dl1_json"]).read_text("utf-8")
    checks["no_logic_text_released"] = "SELECT " not in text and "define " not in text
    checks["sections_in_order"] = [s["id"] for s in obj["sections"]] == [str(i) for i in range(1, 16)]
    if repro:
        frozen2 = pack(cascade())
        checks["reproducible"] = frozen2["sha256"] == frozen["sha256"]
        if not checks["reproducible"]:
            problems.append("a second cascade + pack run produced a different object hash")
    return _finish(
        out_dir,
        trial_id,
        kind,
        dataset,
        pipeline,
        res,
        obj["headline"],
        cert.status,
        cert.reasons,
        obj["headline"]["recall_sentence"],
        obj,
        artefacts,
        checks,
        problems,
        t0,
        gateway={
            **client.summary(),
            **(
                {"verifier": verifier.summary(), "disagreements": sum(j.disagreements for j in agreement)}
                if verifier is not None
                else {}
            ),
        },
    )


def _finish(
    out_dir: Path,
    trial_id: str,
    kind: str,
    dataset: str,
    pipeline: dict[str, Any],
    res: Any,
    headline: dict[str, Any],
    cert_status: str,
    cert_reasons: list[str],
    statement: str,
    obj: dict[str, Any],
    artefacts: dict[str, str],
    checks: dict[str, bool],
    problems: list[str],
    t0: float,
    *,
    gateway: dict[str, Any] | None = None,
) -> E2EResult:
    stages = (
        {
            s.stage: {
                "patients_in": s.patients_in,
                "patients_out": s.patients_out,
                "pairs_in": s.pairs_in,
                "pairs_out": s.pairs_out,
                "data_class": s.data_class,
                "ir_hash": s.ir_hash,
                "detail": s.detail,
            }
            for s in res.stages
        }
        if res is not None
        else {}
    )
    for name, ok in checks.items():
        if not ok and not any(name in p for p in problems):
            problems.append(f"check failed: {name}")
    result = E2EResult(
        passed=bool(checks) and all(checks.values()),
        trial_id=trial_id,
        source_kind=kind,
        dataset=dataset,
        out_dir=str(out_dir),
        pipeline=pipeline,
        stage_counts=stages,
        tiers=res.tier_counts() if res is not None else {},
        final_list_size=len(res.final_list) if res is not None else 0,
        certificate_status=cert_status,
        certificate_reasons=cert_reasons,
        certificate_statement=statement,
        headline=headline,
        artefacts=artefacts,
        checks=checks,
        problems=problems,
        seconds=round(time.monotonic() - t0, 1),
        gateway=gateway or {},
    )
    (out_dir / "e2e_summary.json").write_text(
        json.dumps(result.to_dict(), indent=1, sort_keys=True, default=str) + "\n", "utf-8"
    )
    (out_dir / "e2e_summary.md").write_text(markdown(result), "utf-8")
    return result


def markdown(r: E2EResult) -> str:
    lines = [
        f"# TrialBox MS1 slice end to end: {r.trial_id} on {r.dataset}",
        "",
        f"Result: **{'PASS' if r.passed else 'FAIL'}** in {r.seconds} s. Snapshot {r.pipeline.get('snapshot_id')}.",
        "",
        "| stage | patients in | patients out | pairs in | pairs out | class |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for st, s in r.stage_counts.items():
        lines.append(
            f"| {st} | {s['patients_in']} | {s['patients_out']} | {s['pairs_in']} | {s['pairs_out']} | "
            f"{s['data_class']} |"
        )
    lines += [
        "",
        f"Tiers (exact, internal): {r.tiers}. Final list (S5 confirmed): {r.final_list_size}.",
        "",
        f"Recall certificate: {r.certificate_status}. {r.certificate_statement}",
        "",
        "Checks: " + ", ".join(f"{k} {'ok' if v else 'FAIL'}" for k, v in r.checks.items()),
        "",
    ]
    if r.gateway:
        g = r.gateway
        where = f" at {g['url']}" if g.get("url") else ""
        lines += [
            f"Gateway: {g.get('mode')}{where}, model {g.get('model') or 'route default'}, {g.get('calls')} calls; "
            f"answered by {g.get('builds')}.",
            "",
        ]
    if r.problems:
        lines += ["Problems:", *(f"- {p}" for p in r.problems), ""]
    lines += ["Artefacts:", *(f"- {k}: {v}" for k, v in sorted(r.artefacts.items())), ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--trial", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--recipient", default="external_sponsor", choices=["external_sponsor", "internal"])
    ap.add_argument("--no-repro", action="store_true")
    args = ap.parse_args(argv)
    try:
        r = run_end_to_end(args.source, args.trial, args.out, recipient_class=args.recipient, repro=not args.no_repro)
    except E2EError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(markdown(r))
    return 0 if r.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
