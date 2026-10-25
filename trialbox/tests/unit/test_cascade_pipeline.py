"""Cascade S0–S5 + DL-1 feasibility pack + recall certificate on the synthetic fixture (site-a, trial GZQO).

One end-to-end run (``tools.cascade_e2e.run_end_to_end``, in-process gateway with the stub upstream, no network) is
shared by the module; engine variants re-run the cascade on the same published snapshot with injected judges."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest

TRIAL = "GZQO"


@pytest.fixture(scope="module")
def e2e(synth_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Any:
    from tools.cascade_e2e import run_end_to_end

    out = tmp_path_factory.mktemp("cascade_e2e")
    return run_end_to_end(synth_dir / "site-a", TRIAL, out, repro=True)


@pytest.fixture(scope="module")
def env(e2e: Any) -> dict[str, Any]:
    from dataplat.serving import Serving
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from matching.cascade import CascadeConfig

    from tools.cascade_e2e import load_trial

    wd = Path(e2e.out_dir) / "dataplat"
    manifest = Serving(wd / "l5", wd / "l4", wd / "l4" / "lake", tz="Asia/Taipei").manifest()
    lake = LakeLocal(wd / "l4" / "lake", HashEmbedder(), "Asia/Taipei")
    rs = load_trial(TRIAL)
    cfg = CascadeConfig(
        study_id=TRIAL,
        run_date=date(2026, 10, 5),
        lookback_months=int(rs.manifest.scopes.feas.lookback_months or 36),
        notes_class="D0",
        purpose="feasibility",
        step_id="test",
        sample_per_stratum=200,
        snapshot=manifest.snapshot,
    )
    return {"lake": lake, "rs": rs, "cfg": cfg}


class RecordingJudge:
    def __init__(self, refuse: bool = False) -> None:
        self.refuse = refuse
        self.calls: list[dict[str, Any]] = []

    def judge(self, **kw: Any) -> Any:
        from matching.cascade.judge import JudgeReply

        self.calls.append(kw)
        if self.refuse:
            return JudgeReply("unknown", 0.0, None, None, "gateway refused: test", refused="phi_tripwire")
        return JudgeReply("unknown", 0.2, None, None, "not stated")


def _run(env: dict[str, Any], judge: Any, **cfg: Any) -> Any:
    from embed_service.embedder import HashEmbedder
    from matching.cascade import run_cascade

    from tools.cascade_e2e import _reviewer

    return run_cascade(
        env["lake"],
        env["rs"],
        replace(env["cfg"], **cfg),
        judge=judge,
        embedder=HashEmbedder(),
        reviewer=_reviewer(None, env["rs"]),
    )


# --------------------------------------------------------------------------------------------- end to end
@pytest.mark.req("FR-M3-2", "CAS-1")
def test_end_to_end_passes(e2e: Any) -> None:
    assert e2e.passed, (e2e.problems, {k: v for k, v in e2e.checks.items() if not v})
    assert all(e2e.checks.values())
    for key in ("dl1_pdf", "dl1_xlsx", "dl1_json", "cascade_traces", "cascade_manifest", "recall_certificate"):
        assert Path(e2e.artefacts[key]).is_file(), key
    summary = json.loads((Path(e2e.out_dir) / "e2e_summary.json").read_text("utf-8"))
    assert summary["passed"] is True


@pytest.mark.req("CAS-1", "CAS-7")
def test_stage_logs_and_metrics(e2e: Any) -> None:
    from matching.cascade.model import STAGES

    log = [json.loads(x) for x in Path(e2e.artefacts["cascade_stage_log"]).read_text("utf-8").splitlines() if x]
    assert [r["stage"] for r in log] == list(STAGES)
    assert len({r["ir_hash"] for r in log}) == 1 and all(r["data_class"] == "D3" for r in log)
    m = json.loads(Path(e2e.artefacts["cascade_manifest"]).read_text("utf-8"))
    blob = json.dumps(m)
    for key in ("n_scope", "n_after", "unprocessed", "llm_share"):
        assert key in blob, key
    outs = [m["n_after"][s] for s in ("S0", "S1", "S2", "S2b", "S3", "S4")]
    assert outs == sorted(outs, reverse=True)


@pytest.mark.req("RPT-32", "RPT-33", "RPT-35", "RPT-22")
def test_feasibility_pack_contents(e2e: Any) -> None:
    obj = json.loads(Path(e2e.artefacts["dl1_json"]).read_text("utf-8"))["object"]
    assert [s["id"] for s in obj["sections"]] == [str(i) for i in range(1, 16)]
    assert obj["data_class"] == "D1"
    h = obj["headline"]
    assert set(h) == {
        "computable_count",
        "adjusted_estimate",
        "monthly_new_meeting_criteria",
        "projection_12m",
        "top_limiting_criteria",
        "recall_sentence",
    }
    text = json.dumps(obj)
    assert "SELECT " not in text and "define " not in text
    assert obj["logic_text_released"] is False and obj["annex_b_logic_hashes"]


@pytest.mark.req("RPT-05", "RPT-06")
def test_released_counts_follow_sponsor_profile(e2e: Any) -> None:
    from deliverables.disclosure import SPONSOR, released_ok, require_complete
    from deliverables.pack import all_released_counts

    obj = json.loads(Path(e2e.artefacts["dl1_json"]).read_text("utf-8"))["object"]
    require_complete(obj["disclosure_trace"])
    assert obj["disclosure_trace"]["profile"] == SPONSOR.name
    vals = list(all_released_counts(obj))
    assert vals and all(released_ok(v, SPONSOR) for v in vals)
    exact = json.loads(Path(e2e.artefacts["dl1_internal_exact"]).read_text("utf-8"))
    assert exact  # released vs exact columns kept apart: exact values only in the INTERNAL file


@pytest.mark.req("RPT-06")
def test_render_deterministic_and_refuses_incomplete_trace(e2e: Any) -> None:
    from deliverables.disclosure import DisclosureError, sha256
    from deliverables.render import render_pdf, render_xlsx

    doc = json.loads(Path(e2e.artefacts["dl1_json"]).read_text("utf-8"))
    obj = doc["object"]
    pngs = {k[4:]: Path(v).read_bytes() for k, v in e2e.artefacts.items() if k.startswith("dl1_F-")}
    frozen = {"object": obj, "sha256": doc["sha256"], "pngs": pngs}
    assert render_xlsx(frozen) == render_xlsx(frozen)
    assert render_pdf(frozen) == render_pdf(frozen)
    bad = {**obj, "disclosure_trace": {**obj["disclosure_trace"], "steps": obj["disclosure_trace"]["steps"][:-1]}}
    broken = {"object": bad, "sha256": sha256(bad), "pngs": pngs}  # hash matches, trace incomplete
    with pytest.raises(DisclosureError):
        render_pdf({**frozen, "sha256": "sha256:0"})
    with pytest.raises(DisclosureError):
        render_pdf(broken)
    with pytest.raises(DisclosureError):
        render_xlsx(broken)


@pytest.mark.req("CAS-10", "SAFE-14", "DM-16", "SAFE-10")
def test_certificate_issued_on_synthetic(e2e: Any) -> None:
    assert e2e.certificate_status == "issued", e2e.certificate_reasons
    cert = json.loads(Path(e2e.artefacts["recall_certificate"]).read_text("utf-8"))
    assert cert["cells"] and all(c["ledger_sampled"] > 0 for c in cert["cells"] if c["excluded"])
    assert {kp["line"] for kp in cert["known_positive"]}
    assert "never_excluded" in cert
    obj = json.loads(Path(e2e.artefacts["dl1_json"]).read_text("utf-8"))["object"]
    assert obj["headline"]["recall_sentence"] and obj["recall_certificate"]["rc_id"] == cert["rc_id"]


# --------------------------------------------------------------------------------------------- engine variants
@pytest.mark.req("CAS-2", "CAS-8")
def test_only_note_criteria_reach_the_judge(env: dict[str, Any]) -> None:
    judge = RecordingJudge()
    res = _run(env, judge)
    structured = set(res.applied)
    for t in res.in_scope():
        for o in t.outcomes.values():
            if o.stage in ("S3", "S4"):
                assert o.criterion_id in res.note_criteria and o.criterion_id not in structured
                assert t.exit_stage in (None, "S3", "S4") and (t.exit_stage is None or t.exit_stage >= "S3")
    assert judge.calls, "the fixture should produce S3 work"
    assert all(c["data_class"] == "D0" for c in judge.calls)


@pytest.mark.req("CAS-4", "SAFE-13")
def test_budget_exhaustion_never_excludes(env: dict[str, Any]) -> None:
    from matching.cascade.certificate import exclusion_cells

    judge = RecordingJudge()
    res = _run(env, judge, max_llm_items=0)
    assert judge.calls == []
    assert res.metrics.unprocessed > 0
    assert not any(t.exit_stage in ("S3", "S4") for t in res.in_scope())
    cells, never = exclusion_cells(res)
    assert never["unprocessed"] == res.metrics.unprocessed
    excluded = {p for pids in cells.values() for p in pids}
    assert not excluded & {t.pid for t in res.in_scope() if t.unprocessed}


@pytest.mark.req("CAS-16", "NFR-B12")
def test_gateway_refusal_fails_closed(env: dict[str, Any]) -> None:
    res = _run(env, RecordingJudge(refuse=True))
    assert not any(t.exit_stage in ("S3", "S4") for t in res.in_scope())
    judged = [o for t in res.in_scope() for o in t.outcomes.values() if o.stage == "S3"]
    assert judged and all(o.status in ("unknown", "pending_human", "pass") for o in judged)
    assert res.metrics.gateway_refusals > 0


@pytest.mark.req("CAS-1")
def test_cascade_is_deterministic(env: dict[str, Any]) -> None:
    a, b = _run(env, RecordingJudge()), _run(env, RecordingJudge())
    assert [s.patients_out for s in a.stages] == [s.patients_out for s in b.stages]
    assert a.tier_counts() == b.tier_counts() and a.final_list == b.final_list
