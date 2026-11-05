"""D-103: SCREEN runs the v4 cascade. Pure units: the judge adapter over the orchestrator's LLM client, the trace →
candidate-row mapping, the failure gate, the pipeline switch and the one named funnel."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from matching.cascade.model import Outcome, PatientTrace
from orchestrator.scenarios.screen_cascade import (
    OrchestratorJudge,
    check_failures,
    judged,
    pipeline,
    verdict_of,
    verdicts_of,
)
from tb_common.llm import LlmError, LlmResult
from tb_common.ruleset import Ruleset

ROOT = Path(__file__).resolve().parents[2]
IDX = date(2026, 10, 5)
EXCERPTS = [{"did": "d1", "date": "2026-09-01", "note_type": "progress", "text": "Acute gout flare of the left toe."}]


def _res(verdict: str, quote: str | None = "gout flare", conf: float = 0.9) -> LlmResult:
    data = {"verdict": verdict, "confidence": conf, "quote": quote, "quote_date": "2026-09-01", "reason": "r"}
    return LlmResult(data, "judge", 4, "m", "local", "in", "out" * 8, 10, 2, 1)


@dataclass
class FakeLlm:
    answers: list[Any]
    model: str = "fake"
    seen: list[dict[str, Any]] = field(default_factory=list)

    def chat_json(self, prompt_id: str, variables: dict[str, Any], **kw: Any) -> LlmResult:
        self.seen.append(variables)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        assert isinstance(a, LlmResult)
        return a


def _ask(j: OrchestratorJudge, role: str = "judge") -> Any:
    return j.judge(
        role=role,
        criterion_text="≥ 2 flares",
        note_question="Do the notes document a gout flare?",
        index_date=IDX,
        excerpts=EXCERPTS,
        study_id="GZQO",
        data_class="D3",
        step_id="t",
        purpose="screening",
    )


@pytest.mark.req("CAS-1")
def test_judge_adapter_single_and_agreement() -> None:
    fake = FakeLlm([_res("pass")])
    single = OrchestratorJudge(fake)  # type: ignore[arg-type]
    r = _ask(single)
    assert r.verdict == "pass" and r.confidence == 0.9 and r.quote == "gout flare" and r.prompt == "judge@4"
    assert single.calls == 1 and single.tokens_in == 10 and single.failures == 0
    assert fake.seen[0]["excerpts"] == [{"date": "2026-09-01", "note_type": "progress", "text": EXCERPTS[0]["text"]}]

    agree = OrchestratorJudge(FakeLlm([_res("fail")]), verifier=FakeLlm([_res("fail")]))  # type: ignore[arg-type]
    assert _ask(agree).verdict == "fail" and agree.calls == 2 and agree.disagreements == 0
    disagree = OrchestratorJudge(FakeLlm([_res("fail")]), verifier=FakeLlm([_res("pass")]))  # type: ignore[arg-type]
    r = disagree.judge if False else _ask(disagree)
    assert r.verdict == "unknown" and "disagree" in r.reason and disagree.disagreements == 1 and r.tokens_in == 20
    # an abstaining judge is not put to the verifier
    abstain = OrchestratorJudge(FakeLlm([_res("unknown", None, 0.0)]), verifier=FakeLlm([]))  # type: ignore[arg-type]
    assert _ask(abstain).verdict == "unknown" and abstain.calls == 1
    # the S4 second opinion goes to the verifier when there is one
    second = OrchestratorJudge(FakeLlm([]), verifier=FakeLlm([_res("pass")]))  # type: ignore[arg-type]
    assert _ask(second, role="second_opinion").verdict == "pass" and second.calls == 1


@pytest.mark.req("CAS-1")
def test_judge_adapter_failures_fail_closed_and_gate() -> None:
    down = OrchestratorJudge(FakeLlm([LlmError("boom"), _res("pass")]), verifier=FakeLlm([LlmError("v down")]))  # type: ignore[arg-type]
    r = _ask(down)
    assert r.verdict == "unknown" and r.reason.startswith("judge unavailable") and down.failures == 1
    r = _ask(down)
    assert r.verdict == "unknown" and r.reason.startswith("verifier unavailable") and down.failures == 2
    with pytest.raises(Exception, match="did not answer"):
        check_failures(down)  # 2 failures of 3 > 10 %
    ok = OrchestratorJudge(FakeLlm([]))  # type: ignore[arg-type]
    ok.calls, ok.failures = 100, 5
    check_failures(ok)
    check_failures(None)


def _trace(pid: str, **outcomes: Outcome) -> PatientTrace:
    t = PatientTrace(pid=pid, index_date=IDX, department="RHEU")
    t.outcomes = {o.criterion_id: o for o in outcomes.values()}
    return t


@pytest.mark.req("CAS-1")
def test_trace_to_candidate_rows() -> None:
    rs = Ruleset.load(ROOT / "rulesets" / "GZQO")
    span = {"did": "d9", "start": 0, "end": 10, "date": "2026-09-01", "sentence_hash": "sha256:x", "quote": "flare"}
    meta = {"call_id": "c", "build_sha": "b", "prompt": "judge@4", "confidence": 0.93}
    lake = {
        "source": "lake",
        "record": "Condition/77",
        "date": "2026-01-01",
        "lineage": "snapshot:s",
        "index_date": "x",
    }
    # a note pass with a verified span
    v = verdict_of(Outcome("GZQO-INC-05", "pass", "S3", evidence=[span, meta], reason="two flares"))
    assert v.verdict == "pass" and v.evidence is not None
    assert v.evidence.resource_refs == ["DocumentReference/d9"] and v.evidence.quote == "flare"
    assert v.evidence.quote_date == "2026-09-01" and v.evidence.confidence == 0.93 and v.evidence.reason == "two flares"
    # a coded answer keeps the lake record; a null exclusion value the cascade kept reads "unknown" as in v1
    assert verdict_of(Outcome("GZQO-EXC-01", "pass", "S1", evidence=[lake])).evidence.resource_refs == ["Condition/77"]  # type: ignore[union-attr]
    kept = verdict_of(Outcome("GZQO-EXC-02", "pass", "S1", unknown_kind="data_gap", reason="unknown kept"))
    assert kept.verdict == "unknown"

    strong = _trace("p1", a=Outcome("GZQO-INC-05", "pass", "S3", evidence=[span, meta]))
    strong.tier = "strong"
    pv = verdicts_of(rs, strong)
    assert pv.tier == "high" and pv.n_unknown == 0 and pv.pid == "p1"
    ids = [c.id for c in rs.active() if c.kind in ("inclusion", "exclusion")]
    assert [x.id for x in pv.verdicts] == ids  # protocol order, every criterion present
    assert next(x for x in pv.verdicts if x.id == "GZQO-EXC-01").evidence.reason == "not evaluated"  # type: ignore[union-attr]
    assert judged(strong) and not judged(_trace("p0"))

    # a strong trace with an open coded question is a person's check (review), as v1 tiered it
    open_q = _trace("p2", a=Outcome("GZQO-EXC-02", "pass", "S1", unknown_kind="data_gap", reason="unknown kept"))
    open_q.tier = "strong"
    assert verdicts_of(rs, open_q).tier == "review" and verdicts_of(rs, open_q).n_unknown == 1

    # a soft note fail (single model, D-97) is listed for review with the criterion's action, never excluded
    soft = _trace(
        "p3", a=Outcome("GZQO-EXC-11", "fail", "S3", hard=False, evidence=[span, meta], reason="not_met (single model)")
    )
    soft.tier = "potential:uncertain"
    pv = verdicts_of(rs, soft)
    exc11 = next(x for x in pv.verdicts if x.id == "GZQO-EXC-11")
    assert pv.tier == "review" and exc11.verdict == "fail" and exc11.evidence.quote == "flare"  # type: ignore[union-attr]

    # excluded, watchlist and out-of-scope traces; contact denied is never listed
    gone = _trace("p4", a=Outcome("GZQO-EXC-01", "fail", "S1", hard=True))
    gone.tier, gone.exit_stage = "excluded", "S1"
    assert verdicts_of(rs, gone).tier == "excluded"
    opt = _trace("p5")
    opt.in_scope, opt.scope_reason, opt.tier = False, "research-use opt-out", "out_of_scope"
    pv = verdicts_of(rs, opt)
    assert pv.tier == "excluded" and "opt-out" in " ".join(pv.actions)
    deny = _trace("p6", a=Outcome("GZQO-INC-05", "pass", "S3", evidence=[span, meta]))
    deny.tier, deny.contact_ok = "strong", False
    pv = verdicts_of(rs, deny)
    assert pv.tier == "excluded" and any("contact: deny" in a for a in pv.actions)
    pend = _trace("p7", a=Outcome("GZQO-EXC-13", "pending_human", "S5", reason="human criterion"))
    pend.tier = "strong"
    pv = verdicts_of(rs, pend)
    assert next(x for x in pv.verdicts if x.id == "GZQO-EXC-13").verdict == "pending_human" and pv.tier == "high"


@pytest.mark.req("CAS-1")
def test_pipeline_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_SCREEN_PIPELINE", raising=False)
    assert pipeline() == "cascade"
    monkeypatch.setenv("TB_SCREEN_PIPELINE", "V1")
    assert pipeline() == "v1"
    monkeypatch.setenv("TB_SCREEN_PIPELINE", "v2")
    with pytest.raises(ValueError):
        pipeline()


@pytest.mark.req("CAS-1")
def test_funnel_from_the_cascade_stage_log() -> None:
    from orchestrator.scenarios.screen import ScreenRun, stage_funnel

    rs = Ruleset.load(ROOT / "rulesets" / "GZQO")
    scoped: list[Any] = [object()] * 120
    srun = ScreenRun(
        rs,
        IDX,
        "2026-10-04",
        scoped,
        {},
        [],
        ["P12345"],
        [],
        180,
        None,
        None,
        {"n_after": {"S0": 118, "S1": 40, "S2": 40, "S3": 31, "S4": 31}, "notes_read": 22},
    )
    assert srun.pipeline == "cascade"
    assert stage_funnel(rs, srun, 9, lambda v: v) == [["S0", 118], ["S1", 40], ["S3", 22], ["S4", 9]]
