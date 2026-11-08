"""TB-PLAN-03 step 3 (D-118): one note-judge path, reasons as codes, the minimum confidence, not-in-snapshot is a
review, a model outage is a code, and CONSENT goes through the two-phase swap. No network."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from matching.cascade.judge import AgreementJudge, JudgeReply
from orchestrator.scenarios import consent
from orchestrator.scenarios.evaluate import NoteJudge, evaluate_patients, not_in_snapshot
from orchestrator.scenarios.screen_cascade import OrchestratorJudge
from tb_common.llm import LlmError, LlmResult
from tb_common.pair import Vote, combine
from tb_common.reasons import CODES, LABELS, MIN_CONFIDENCE, code_of, label
from tb_common.ruleset import Ruleset

ROOT = Path(__file__).resolve().parents[2]
GZQO = Ruleset.load(ROOT / "rulesets" / "GZQO")
IDX = date(2026, 2, 1)
EXCERPTS = [
    {"date": "2026-01-10", "note_type": "progress", "text": "Known HIV infection on ART since 2019.", "did": "D1"}
]
QUOTE = "Known HIV infection on ART since 2019."


class Model:
    def __init__(self, verdict: str, conf: float = 0.9, quote: str | None = QUOTE, error: str | None = None) -> None:
        self.model, self.verdict, self.conf, self.quote, self.error = f"m-{verdict}", verdict, conf, quote, error
        self.calls = 0

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> LlmResult:
        self.calls += 1
        if self.error:
            raise LlmError(self.error)
        data = {"verdict": self.verdict, "reason": "The note says HIV.", "confidence": self.conf, "quote": self.quote}
        return LlmResult(data, prompt_id, 4, self.model, "local", "i" * 64, "o" * 64, 10, 2, 1)


# ---------------------------------------------------------------------------------------------- the pair rule
@pytest.mark.parametrize(
    ("first", "second", "verdict", "reason", "flags"),
    [
        (Vote("fail", 0.9, "note"), None, "fail", "note", (False, False)),  # no verifier: the judge stands
        (Vote("fail", 0.9, "note"), Vote("fail", 0.7, "note"), "fail", "note", (False, False)),
        (Vote("fail", 0.9, "note"), Vote("pass", 0.9, "note"), "unknown", "disagree", (True, False)),
        (Vote("fail", 0.9, "note"), Vote("unknown", 0.0, "abstained"), "unknown", "disagree", (True, False)),
        (Vote("fail", 0.9, "note"), Vote("unknown", 0.0, "model_down"), "unknown", "model_down", (False, True)),
        (Vote("pass", 0.9, "note"), Vote("unknown", 0.0, "quote_not_found"), "unknown", "verifier_quote_missing",
         (True, False)),
        (Vote("unknown", 0.0, "abstained"), Vote("fail", 0.9, "note"), "unknown", "abstained", (False, False)),
        (Vote("fail", 0.4, "note"), None, "unknown", "low_confidence", (False, False)),
        (Vote("fail", 0.9, "note"), Vote("fail", 0.3, "note"), "unknown", "low_confidence", (False, False)),
    ],
)  # fmt: skip
def test_combine_table(first: Vote, second: Vote | None, verdict: str, reason: str, flags: tuple[bool, bool]) -> None:
    d = combine(first, second)
    assert (d.verdict, d.reason, (d.disagreement, d.failure)) == (verdict, reason, flags)
    if verdict == "fail" and second is not None:
        assert d.confidence == min(first.confidence, second.confidence)


def test_every_reason_has_three_languages_and_engine_strings_map_to_codes() -> None:
    assert set(LABELS) == set(CODES)
    for code, by in LABELS.items():
        assert set(by) == {"en", "ja", "zh-TW"} and all(by.values()), code
        assert not by["ja"].isascii() and not by["zh-TW"].isascii(), code
    samples = {
        "no value in the window": "data_gap",
        "no record (CAS-11: missing → unknown)": "data_gap",
        "abstained": "abstained",
        "insufficient": "quote_not_found",
        "human criterion": "human",
        "judge/verifier disagree (fail/pass); needs a human look": "disagree",
        "S3/S4 disagree": "disagree",
        "judge unavailable: HTTP 500 upstream said <html>": "model_down",
        "unknown kept": "unknown_kept",
        "unknown_kept": "unknown_kept",
        "zero hits (certified absence)": "not_mentioned",
        "not sampled": "not_evaluated",
        "not in the snapshot": "not_in_snapshot",
    }
    for text, code in samples.items():
        assert code_of(text, "unknown") == code, text
    assert code_of("two documented flares", "pass", quoted=True) == "note"
    assert code_of("matching record", "fail") == "coded"
    assert label("disagree", "ja") == "2回の確認が一致しない：確認してください"
    assert label("free text the engine made up", "ja") == ""  # never an English sentence on a JA page


# ---------------------------------------------------------------------------------------------- one judge path
def test_note_judge_reasons_are_codes_never_model_or_endpoint_text() -> None:
    nj = NoteJudge(lake=None, llm=Model("pass"), verifier=Model("pass", error="HTTP 502 <html>upstream</html>"))  # type: ignore[arg-type]
    r = nj.judge_excerpts("Known HIV", "HIV?", IDX, EXCERPTS)
    assert r.predicate == "unknown" and r.reason == "model_down" and nj.failures == 1 and "html" not in str(r)
    ok = NoteJudge(lake=None, llm=Model("pass"), verifier=Model("pass")).judge_excerpts("x", "x?", IDX, EXCERPTS)  # type: ignore[arg-type]
    assert ok.predicate == "pass" and ok.reason == "note" and ok.model_reason == "The note says HIV."
    low = NoteJudge(lake=None, llm=Model("pass", conf=MIN_CONFIDENCE - 0.1)).judge_excerpts("x", "x?", IDX, EXCERPTS)  # type: ignore[arg-type]
    assert low.predicate == "unknown" and low.reason == "low_confidence" and low.quote is None
    missing = NoteJudge(lake=None, llm=Model("pass", quote="HIV since birth")).judge_excerpts("x", "x?", IDX, EXCERPTS)  # type: ignore[arg-type]
    assert missing.predicate == "unknown" and missing.reason == "quote_not_found"


def _cascade_ask(j: Any) -> JudgeReply:
    kw = dict(criterion_text="Known HIV", note_question="HIV?", index_date=IDX, excerpts=EXCERPTS)
    reply: JudgeReply = j.judge(role="judge", study_id="T", data_class="D0", step_id="s", purpose="p", **kw)
    return reply


def test_cascade_and_v1_give_the_same_answer_through_the_same_judge() -> None:
    cases = [("fail", "fail"), ("fail", "pass"), ("pass", "unknown"), ("pass", "pass")]
    for a, b in cases:
        v1 = NoteJudge(lake=None, llm=Model(a), verifier=Model(b)).judge_excerpts("Known HIV", "HIV?", IDX, EXCERPTS)  # type: ignore[arg-type]
        cas = _cascade_ask(OrchestratorJudge(lake=None, llm=Model(a), verifier=Model(b)))  # type: ignore[arg-type]
        assert (cas.verdict, cas.reason) == (v1.predicate, v1.reason), (a, b)

    class Fixed:
        def __init__(self, verdict: str) -> None:
            self.verdict = verdict

        def judge(self, *, role: str, **_: Any) -> JudgeReply:
            return JudgeReply(self.verdict, 0.9, QUOTE, None, "")

    tool = _cascade_ask(AgreementJudge(Fixed("fail"), Fixed("pass")))
    assert (tool.verdict, tool.reason) == ("unknown", "disagree")  # the offline tools' judge: same rule


# ---------------------------------------------------------------------------------------------- not in snapshot
def test_a_patient_missing_from_the_snapshot_is_a_review_not_an_exclusion() -> None:
    class Engine:
        name = "sql"

        def evaluate(self, rs: Any, pids: list[str], index_date: date, ids: list[str]) -> dict[str, Any]:
            return {}  # the lake holds none of them

    res = evaluate_patients(GZQO, ["ghost"], IDX, Engine(), None, 0.75, workers=1)
    pv = res["ghost"]
    assert pv.tier == "review" and pv.n_unknown == len(pv.verdicts) > 0
    assert {v.evidence.reason for v in pv.verdicts if v.evidence} == {"not_in_snapshot"}
    assert not_in_snapshot(GZQO, "x").tier == "review"


# ---------------------------------------------------------------------------------------------- consent and the swap
def test_consent_draft_runs_in_two_phases_with_a_swap() -> None:
    """With the GPU time-shared, the draft runs with the judge awake and every statement check with the verifier
    awake: the verifier is never called while the judge is the model on the card."""
    from orchestrator.twophase import two_phase

    awake: list[str] = []

    class Phased:
        def __init__(self, name: str, reply: dict[str, Any]) -> None:
            self.name, self.reply, self.model = name, reply, name

        def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> Any:
            want = "serving" if self.name == "judge" else "verifier"
            assert awake and awake[-1] == want, f"{self.name} called while {awake[-1:]} is awake"
            data = self.reply[prompt_id]
            return LlmResult(data, prompt_id, 1, self.name, "local", "i" * 64, "o" * 64, 5, 5, 1)

    para = {"id": "P1", "heading": "Purpose", "text": "You will take one tablet a day for 12 weeks."}
    judge = Phased(
        "judge",
        {
            "consent_explain": {
                "items": [{"section": "purpose", "text": "One tablet a day, 12 weeks.", "quote": para["text"], "para": "P1"}],
                "questions": [],
            }
        },
    )  # fmt: skip
    verifier = Phased("verifier", {"consent_verify": {"checks": [{"id": "I01", "verdict": "supported"}]}})
    m = consent.Models(judge, verifier)  # type: ignore[arg-type]
    out = two_phase(
        m, lambda mm: consent.draft(mm, "T", [para], "en", ["en"], "j"), swap=awake.append, probe=lambda e: None
    )
    assert awake == ["serving", "verifier"]  # draft, then the checks; no direct call to a sleeping model
    assert out["items"][0]["texts"]["en"]["status"] == "ok" and not out["issues"]


# ---------------------------------------------------------------------------------------------- both quotes (D-120)
def test_a_disagreement_keeps_both_answers_and_quotes_on_both_paths() -> None:
    from orchestrator.scenarios.evaluate import note_verdict

    other = "Known HIV infection"  # also in the notes: the second check quotes its own words
    nj = NoteJudge(lake=None, llm=Model("fail"), verifier=Model("pass", quote=other))  # type: ignore[arg-type]
    r = nj.judge_excerpts("Known HIV", "HIV?", IDX, EXCERPTS)
    assert (r.predicate, r.reason) == ("unknown", "disagree")
    assert [(o["role"], o["verdict"], o["quote"]) for o in r.opinions] == [
        ("judge", "fail", QUOTE),
        ("verifier", "pass", other),
    ]
    c = next(c for c in GZQO.active() if c.kind == "exclusion")
    ev = note_verdict(c, r).evidence
    assert ev is not None and ev.opinions and [o.role for o in ev.opinions] == ["judge", "verifier"]
    cas = _cascade_ask(OrchestratorJudge(lake=None, llm=Model("fail"), verifier=Model("pass", quote=other)))  # type: ignore[arg-type]
    assert [o["quote"] for o in cas.opinions] == [QUOTE, other]
    agree = NoteJudge(lake=None, llm=Model("fail"), verifier=Model("fail")).judge_excerpts("x", "x?", IDX, EXCERPTS)  # type: ignore[arg-type]
    assert agree.opinions == []
    from matching.cascade.model import Outcome
    from orchestrator.scenarios.screen_cascade import verdict_of

    o = Outcome(
        "X-EXC-01", "unknown", "S3", unknown_kind="uncertain", evidence=[{"opinions": cas.opinions}], reason="disagree"
    )
    v = verdict_of(o)
    assert v.evidence is not None and v.evidence.reason == "disagree" and len(v.evidence.opinions or []) == 2
