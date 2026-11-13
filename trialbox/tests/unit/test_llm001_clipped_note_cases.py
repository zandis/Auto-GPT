"""The two clipped-note cases of the GPU run, as CI tests (the twin of lane G's G-7, ``tools/g_probes.py``).

Run C of 2026-11-13 (5,000 synthetic patients, the real pair, a commit from before T-710 and NEW-LLM-1) made a wrong
exclusion: a zh-TW note says "病人否認下列病史：… 肺結核" (the patient denies tuberculosis); the clip of that day kept
"肺結核。" and dropped the denial line; both models answered "has it"; the pair agreed; the answer was final. On the
whole note both answered correctly. The Japanese case (肺結核 only under 【家族歴】) lost its heading the same way.

What holds since, and is held here on these two notes exactly as the run builds them:

* **the notes are no longer clipped at the default budget** (T-710, D-479: a note that fits the budget is shown
  whole; the run's clip was at half the budget);
* **when a budget does force a cut, the heading and the denial line stay directly above the evidence** and the cut
  is marked (NEW-LLM-1, D-641);
* **an answer on a clipped note that would exclude is never final** (D-479 with D-276: a clipped note counts as
  left out; the cascade's ``_map``, ``NoteJudge.judge_window`` and CASE make such an answer unknown).
"""

from __future__ import annotations

import random
from datetime import date
from typing import Any

import pytest
from matching.cascade import engine as cascade_engine
from matching.cascade.judge import norm
from matching.excerpts import GAP, Note, build, sentences
from orchestrator.scenarios.evaluate import NoteJudge

from tests.judge_kit import ScriptedModel, note_criterion, says
from tools.synth import notes as zh
from tools.synth import notes_ja as ja

TB_LEXICON = ("tuberculosis", "結核", "肺結核", "tb")  # the run's lexicon for a tuberculosis exclusion
TB = note_criterion(
    "T-EXC-01", "exclusion", "Active or past tuberculosis",
    "Does the patient have active tuberculosis or a history of tuberculosis?",
)  # fmt: skip
IDX = date(2026, 6, 30)

_daily_ja = [f"入院{i}日目、{ja.FILLER[i % len(ja.FILLER)]}" for i in range(1, 60)]
NOTE_JA = "\n".join(["【現病歴】", *_daily_ja, "【既往歴】", "高血圧症。", "脂質異常症。", "【家族歴】", "肺結核。",
                     "糖尿病。", "【アレルギー】", "なし。"])  # fmt: skip
_daily_zh = [f"住院第{i}天，{zh.FILLER[i % len(zh.FILLER)]}" for i in range(1, 60)]
NOTE_ZH = "\n".join(["【現病史】", *_daily_zh, "【過去病史】", "高血壓。", "病人否認下列病史：", "肺結核。",
                     "B型肝炎。", "【過敏史】", "無。"])  # fmt: skip
CASES = [
    ("LLM-001-ja-family-history", NOTE_JA, "【家族歴】\n肺結核。"),
    ("LLM-001-zh-TW-denied-list", NOTE_ZH, "病人否認下列病史：\n肺結核。"),
]


def _view(case: str, text: str, budget: int | None = None) -> tuple[list[dict[str, Any]], int]:
    """The cascade's excerpt of one note, as the run's ``clipped_view`` asks for it."""
    note = cascade_engine._Note(case, date(2026, 6, 1), "discharge", text, sentences(text))
    ev = [s for s in note.sents if any(t in norm(s).lower() for t in TB_LEXICON)]
    assert ev == ["肺結核。"]
    return cascade_engine._Run.excerpt_set([note], {note.did: ev}, budget=budget)


@pytest.mark.parametrize(("case", "text", "governed"), CASES)
def test_at_the_default_budget_the_runs_notes_are_read_whole(case: str, text: str, governed: str) -> None:
    shown, left_out = _view(case, text)
    assert left_out == 0 and [e["text"] for e in shown] == [text] and governed in text


@pytest.mark.parametrize("budget", [1000, 400, 150, 90])
@pytest.mark.parametrize(("case", "text", "governed"), CASES)
def test_a_forced_cut_keeps_what_governs_the_evidence_and_counts_as_left_out(
    case: str, text: str, governed: str, budget: int
) -> None:
    shown, left_out = _view(case, text, budget)
    assert left_out == 1 and len(shown) == 1
    part = str(shown[0]["text"])
    assert part != text and governed in part and part.startswith(GAP)
    assert "【既往歴】\n肺結核。" not in part and "高血壓。\n肺結核。" not in part  # what the run's clip showed


def _pair(answer: str) -> NoteJudge:
    def model(name: str) -> Any:
        return ScriptedModel(name, says(answer, "肺結核。"))

    return NoteJudge(lake=None, llm=model("judge-a"), verifier=model("verifier-b"))


@pytest.mark.parametrize(("case", "text", "governed"), CASES)
def test_a_pair_that_says_has_it_on_the_clipped_note_never_excludes(case: str, text: str, governed: str) -> None:
    """The run's wrong exclusion, replayed with a scripted pair: both models answer "has it" with the quote."""
    shown, left_out = _view(case, text, 400)
    r = _pair("pass").judge_window(TB, IDX, shown, left_out, "chunks")
    assert (r.predicate, r.reason, r.left_out) == ("unknown", "notes_over_budget", 1)
    # on the whole note the pair's answer is the answer: nothing was left out (the run's pair got it right there)
    whole, none_left = _view(case, text)
    assert _pair("pass").judge_window(TB, IDX, whole, none_left, "full_record").predicate == "pass"
    assert _pair("fail").judge_window(TB, IDX, whole, none_left, "full_record").predicate == "fail"


def test_no_note_is_shown_cut_without_being_counted_as_left_out() -> None:
    """The rule behind "a clipped note never gives a final not met": whatever the window, the evidence and the
    budget, every note the builder shows in part is in its ``cut`` list, so ``left_out`` is never 0 for it."""
    rng = random.Random(479)
    for _ in range(300):
        notes = []
        for k in range(rng.randint(1, 6)):
            lines = [f"所見{k}-{i}" + "あ" * rng.randint(0, 40) + "。" for i in range(rng.randint(1, 80))]
            notes.append(Note(f"d{k}", date(2026, 5, 1 + k), "progress", "\n".join(lines)))
        evidence = {n.did: [rng.choice(sentences(n.text))] for n in notes if rng.random() < 0.7}
        got = build(notes, evidence, rng.randint(60, 3000))
        whole = {n.did: n.text for n in notes}
        for e in got.shown:
            assert e["text"] == whole[e["did"]] or e["did"] in got.cut
        assert got.left_out == len(got.cut) >= sum(1 for e in got.shown if e["text"] != whole[e["did"]])
        assert got.left_out + sum(1 for e in got.shown if e["text"] == whole[e["did"]]) == len(notes)
