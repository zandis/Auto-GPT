"""The pair rule on the path SCREEN runs, from the two models' answers to the tier (D-276; safety review S-3).

``tb_common.pair.combine`` is well tested, and so is the engine's ``_map``; nothing tested the two together through
``OrchestratorJudge`` -> ``run_cascade`` -> ``verdicts_of``. Each case here is a pair of scripted models
(``tests/judge_kit.py``) or the stub's test personas over HTTP: only two different models that both say "not met",
both surely enough and both with a quote from the notes, exclude. Also the v1 evaluator's rules the review found
without a test: a structured inclusion with no value keeps the patient a candidate, a scoped patient missing from the
cascade's result is listed for review, and (S-10) an excluding answer read from part of the retrieved notes.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from matching.cascade.engine import CascadeConfig, run_cascade
from matching.decision import Policy
from orchestrator.scenarios import screen_cascade
from orchestrator.scenarios.evaluate import (
    NoteJudge,
    PatientVerdicts,
    effective_note_block,
    evaluate_patients,
    structured_candidate,
)
from orchestrator.scenarios.screen_cascade import OrchestratorJudge, screen_with_cascade, verdicts_of
from tb_contracts import PatientEvaluation

from tests.judge_kit import AGE, ScriptedModel, down, note_criterion, note_lake, ruleset, says, stub_client

IDX = date(2026, 10, 5)
SNAP = "2026-10-05"
FLARE = "Acute gout flare of the right toe"
POOR = "治療反應不佳。"  # the stub's judge reads this sentence as "no" to a question about the response
INC = note_criterion("T-INC-02", "inclusion", "Gout flare in the past year", "Did the patient have a gout flare?")
RESP = note_criterion("T-INC-03", "inclusion", "Good response to treatment", "Is a good treatment response documented?")
LEXICON = {INC.id: ["flare"], RESP.id: ["治療反應"]}
PATIENTS: dict[str, list[tuple[date, str]]] = {
    "P-HIT": [(date(2026, 9, 20), f"{FLARE}\nColchicine started")],
    "P-ZH": [(date(2026, 9, 20), POOR)],
    "P-NONE": [],
}


@pytest.fixture(scope="module")
def lake(tmp_path_factory: pytest.TempPathFactory) -> LakeLocal:
    return note_lake(tmp_path_factory.mktemp("exclusion-pair"), PATIENTS, SNAP)


@pytest.fixture(autouse=True)
def _policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_NOTE_BLOCK", "both_agree")
    monkeypatch.setenv("TB_CANARY_GATE", "off")
    monkeypatch.delenv("TB_MODEL_SWAP", raising=False)
    monkeypatch.delenv("TB_STUB_MODELS", raising=False)


def _screen(lake: LakeLocal, crit: Any, pid: str, llm: Any, verifier: Any) -> tuple[PatientVerdicts, NoteJudge, Any]:
    """One patient through the cascade as SCREEN runs it: the note-block policy of the pair, then the tier."""
    rs = ruleset([crit])
    nj = NoteJudge(lake=None, llm=llm, verifier=verifier)
    may_block = effective_note_block(nj)[0]
    judge = OrchestratorJudge.from_note_judge(nj)
    cfg = CascadeConfig(
        study_id="T", run_date=IDX, lookback_months=36, index_mode="single", purpose="screening", step_id="t",
        snapshot=SNAP, population=[pid], lexicon=LEXICON, language="en", confidence_floor=0.75,
        note_block=may_block, absence_semantics=False,
    )  # fmt: skip
    res = run_cascade(lake, rs, cfg, judge=judge, embedder=HashEmbedder(), reviewer=None)
    # the run's policy, as SCREEN passes it (D-478: a caller that names none gets "notes may not exclude")
    policy = Policy(threshold=0.75, note_block=may_block)
    return verdicts_of(rs, res.traces[pid], policy=policy), judge, res.traces[pid]


def _reason(pv: PatientVerdicts, cid: str) -> str | None:
    v = next(v for v in pv.verdicts if v.id == cid)
    return v.evidence.reason if v.evidence else None


def test_two_different_models_that_agree_exclude(lake: LakeLocal) -> None:
    pv, judge, trace = _screen(
        lake, INC, "P-HIT", ScriptedModel("judge-a", says("fail", FLARE)), ScriptedModel("verifier-b", says("fail", FLARE))
    )  # fmt: skip
    assert pv.tier == "excluded" and trace.exit_stage == "S3" and judge.disagreements == 0 and judge.same_model == 0


@pytest.mark.parametrize(
    ("verifier", "reason"),
    [
        (ScriptedModel("verifier-b", says("pass", FLARE)), "disagree"),
        (ScriptedModel("verifier-b", says("unknown", None, 0.5)), "disagree"),
        (ScriptedModel("verifier-b", down), "model_down"),  # outage or time-out
        (ScriptedModel("verifier-b", says("fail", "A sentence in no note", quote_date="2026-09-20")), "verifier_quote_missing"),
        (ScriptedModel("verifier-b", says("fail", FLARE, 0.6)), "abstained"),  # agreed, the less sure below the floor
        (ScriptedModel("verifier-b", says("fail", FLARE, 0.4)), "low_confidence"),  # below the pair's own minimum
        (None, "note"),  # one model: its "not met" is kept and shown, the patient goes to review
        # S-2: configured under two names, but the answers come back from one model
        (ScriptedModel("verifier-b", says("fail", FLARE), served="judge-a"), "model_down"),
        (ScriptedModel("verifier-b", says("fail", FLARE), served=" Judge-A "), "model_down"),
    ],
)  # fmt: skip
def test_a_contested_not_met_never_excludes(lake: LakeLocal, verifier: Any, reason: str) -> None:
    pv, judge, trace = _screen(lake, INC, "P-HIT", ScriptedModel("judge-a", says("fail", FLARE)), verifier)
    assert pv.tier == "review" and trace.exit_stage is None and trace.tier == "potential:uncertain"
    assert _reason(pv, INC.id) == reason
    if verifier is not None and verifier.served.strip().casefold() == "judge-a":  # one model answered twice
        assert judge.same_model == 1 and judge.failures == 1


def test_one_model_named_twice_never_excludes(lake: LakeLocal) -> None:
    """S-2: the verifier is the judge's model again (same name, another URL). It agrees with itself every time."""
    llm = ScriptedModel("judge-a", says("fail", FLARE), base_url="http://one/v1")
    verifier = ScriptedModel("judge-a", says("fail", FLARE), base_url="http://two/v1")
    nj = NoteJudge(lake=None, llm=llm, verifier=verifier)  # type: ignore[arg-type]
    may, policy, why = effective_note_block(nj)
    assert (may, policy) == (False, "never") and "not a second model" in why and "judge-a" in why
    pv, _, trace = _screen(lake, INC, "P-HIT", llm, verifier)
    assert pv.tier == "review" and trace.exit_stage is None


# ------------------------------------------------------------------------------------------------ over HTTP (stub)
def test_the_stub_pair_agrees_and_excludes_over_http(lake: LakeLocal) -> None:
    pv, _, trace = _screen(lake, RESP, "P-ZH", stub_client("stub"), stub_client("stub-verifier"))
    assert pv.tier == "excluded" and trace.exit_stage == "S3"


@pytest.mark.parametrize(
    ("llm", "verifier", "reason"),
    [
        ("stub", "stub-dissent", "disagree"),
        ("stub", "stub-lowconf", "low_confidence"),
        ("stub", "stub-badquote", "verifier_quote_missing"),
        ("stub", "stub-down", "model_down"),  # HTTP 503
        ("stub", "timeout", "model_down"),  # the request timed out
        ("stub", "stub-not-served", "model_down"),  # HTTP 404: the stub does not serve this name
        ("stub", "stub", "model_down"),  # S-2 over HTTP: one model answered twice, a failure
        ("stub-olddate", "stub-verifier", "quote_not_found"),  # a real quote under the wrong date (CAS-16)
        ("stub-badquote", "stub-verifier", "quote_not_found"),
    ],
)
def test_a_contested_stub_answer_never_excludes_over_http(lake: LakeLocal, llm: str, verifier: str, reason: str) -> None:  # fmt: skip
    v = stub_client("stub-verifier", timeout=True) if verifier == "timeout" else stub_client(verifier)
    pv, _, trace = _screen(lake, RESP, "P-ZH", stub_client(llm), v)
    assert pv.tier == "review" and trace.exit_stage is None and _reason(pv, RESP.id) == reason


# ------------------------------------------------------------------------------------------------ v1 evaluator
def test_v1_a_structured_inclusion_with_no_value_keeps_the_patient_a_candidate() -> None:
    rs = ruleset([INC])

    def ev(value: bool | None) -> PatientEvaluation:
        return PatientEvaluation(pid="P", index_date=IDX, engine="sql", results={AGE.id: value})

    assert structured_candidate(rs, ev(True)) and structured_candidate(rs, ev(None))  # unknown never excludes
    assert not structured_candidate(rs, ev(False))  # control: a failing value does


class _Chunks:
    """A lake whose search returns the given chunks (newest first after the evaluator's sort)."""

    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self.chunks = chunks

    def chunks_search(self, pid: str, query: str, k: int = 5, **kw: Any) -> list[dict[str, Any]]:
        return list(self.chunks)

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
        rows = [{"did": c["did"], "d": date.fromisoformat(c["date"]), "type": "progress", "text": c["text"]}
                for c in sorted(self.chunks, key=lambda c: c["date"], reverse=True)]  # fmt: skip
        return SimpleNamespace(to_pylist=lambda: rows)


def _chunk(n: int, text: str) -> dict[str, Any]:
    return {"date": f"2026-09-{n:02d}", "type": "progress", "text": text, "did": f"D{n}"}


class _NoStructured:
    name = "sql"

    def evaluate(self, rs: Any, pids: list[str], index_date: date, ids: list[str]) -> dict[str, Any]:
        raise AssertionError("no structured criterion was asked for")


def _v1(lake: Any, answer: str) -> tuple[str, str | None]:
    nj = NoteJudge(
        lake=lake,
        llm=ScriptedModel("judge-a", says(answer, FLARE)),  # type: ignore[arg-type]
        verifier=ScriptedModel("verifier-b", says(answer, FLARE)),  # type: ignore[arg-type]
    )
    rs = ruleset([INC])
    out = evaluate_patients(rs, ["P"], IDX, _NoStructured(), nj, 0.75, only={INC.id}, all_candidates=True)
    return out["P"].tier, _reason(out["P"], INC.id)


def test_v1_not_met_is_not_final_when_the_budget_left_retrieved_notes_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """S-10 on the v1 path (NAV, MICROBATCH): five chunks retrieved, the 2,500-token budget shows two, and the
    full record does not fit either. Both models say "not met" on what they saw: unknown, never an exclusion."""
    from orchestrator.scenarios import evaluate

    monkeypatch.setattr(evaluate, "FULL_RECORD_TOKENS", 2500)
    filler = "Routine follow-up, vitals stable, no change in plan. " * 75
    small = _Chunks([_chunk(n, f"{FLARE}. Seen in clinic, visit {n}.") for n in range(1, 6)])
    large = _Chunks([_chunk(n, f"{FLARE}. Visit {n}. {filler}") for n in range(1, 6)])  # distinct notes (D-905)
    assert _v1(small, "fail") == ("excluded", "note")  # control: every retrieved note was read
    assert _v1(large, "fail") == ("review", "notes_over_budget")
    # T-603 (CR-004 flag half): an answer that keeps the patient stands, flagged: review, with the reason
    assert _v1(large, "pass") == ("review", "notes_over_budget")


class _Roomy(ScriptedModel):
    """A scripted model that tells its context: room for 28,000 tokens of notes (a 32k build)."""

    def text_budget(self, prompt: str, fixed: dict[str, Any]) -> int:
        return 28000


def test_v1_an_answer_on_the_whole_window_is_final_when_the_context_holds_it() -> None:
    """T-710 (D-479): one read, sized from the models' context. The same five long notes that a 2,500-token read
    cuts (above) are read whole by models with room for them, and an answer on the whole window is final. Before,
    this was the evaluator's second, "full record" read."""
    filler = "Routine follow-up, vitals stable, no change in plan. " * 75
    large = _Chunks([_chunk(n, f"{FLARE}. Visit {n}. {filler}") for n in range(1, 6)])  # distinct notes (D-905)
    nj = NoteJudge(
        lake=large,  # type: ignore[arg-type]
        llm=_Roomy("judge-a", says("fail", FLARE)),  # type: ignore[arg-type]
        verifier=_Roomy("verifier-b", says("fail", FLARE)),  # type: ignore[arg-type]
    )
    assert nj.window("P", INC, IDX).left_out == 0
    out = evaluate_patients(ruleset([INC]), ["P"], IDX, _NoStructured(), nj, 0.75, only={INC.id}, all_candidates=True)
    assert (out["P"].tier, _reason(out["P"], INC.id)) == ("excluded", "note")
    assert _v1(large, "fail") == ("review", "notes_over_budget")  # the same notes, models that tell no context


# ------------------------------------------------------------------------------------------------ SCREEN
def test_a_scoped_patient_missing_from_the_cascade_result_is_listed_for_review(lake: LakeLocal, monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    """Whatever the cascade returns, every patient SCREEN was asked about comes back: one it lost is ``review``
    (``not_in_snapshot``), never silently dropped from the list (D-118)."""
    real = run_cascade

    def loses_one(*a: Any, **kw: Any) -> Any:
        res = real(*a, **kw)
        del res.traces["P-NONE"]
        return res

    monkeypatch.setattr(screen_cascade, "run_cascade", loses_one)
    ctx: Any = SimpleNamespace(
        job=SimpleNamespace(job_id="J1", metrics=None),
        cfg=SimpleNamespace(settings=SimpleNamespace(site=SimpleNamespace(locale="en"))),
        services=SimpleNamespace(lake=lake),
        metrics=lambda **kw: None,
    )
    rs = ruleset([INC])
    out = screen_with_cascade(ctx, rs, IDX, SNAP, ["P-HIT", "P-NONE"], None, {}, 0.75, 36)
    assert set(out.results) == {"P-HIT", "P-NONE"}
    lost = out.results["P-NONE"]
    assert lost.tier == "review" and {v.verdict for v in lost.verdicts} == {"unknown"}
    assert _reason(lost, INC.id) == "not_in_snapshot"
