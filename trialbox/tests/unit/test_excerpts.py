"""One excerpt builder (T-710, D-479): ``matching.excerpts.build`` and the three paths that call it.

The paths against each other and the oracle that reads what it is shown are ``tests/property/`` (T-705, T-706).
Here: the builder's rules as cases, the budget from the models' context, and the row's acceptance case (a patient
with five long notes on a 32k build).
"""

from __future__ import annotations

from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from matching import excerpts
from matching.cascade import engine as cascade_engine
from matching.excerpts import DEFAULT_TOKENS, GAP, Note, build, clip, note_tokens, sentences
from orchestrator.scenarios import evaluate
from orchestrator.scenarios.case import ChartJudge
from orchestrator.scenarios.evaluate import NoteJudge, evaluate_patients

from tests.judge_kit import ScriptedModel, ruleset, says
from tests.unit.test_context_budgets import GOOD, INDEX, LINE, PROFILES, _box, _client, _Lake
from tests.unit.test_screen_exclusion_pair import FLARE, IDX, INC, _chunk, _Chunks, _NoStructured

FILLER = "Routine follow-up, vitals stable, no change in plan.\n"  # a note's sentences are its lines


def _n(did: str, day: str, text: str) -> Note:
    return Note(did, date.fromisoformat(day), "progress", text)


# ------------------------------------------------------------------------------------------------ the builder
def test_every_window_note_is_shown_while_it_fits_and_nothing_is_left_out() -> None:
    window = [_n("b", "2026-09-01", "Uric acid 9.1."), _n("a", "2026-10-01", "Gout flare."), _n("c", "2026-08-01", "x")]
    got = build(window, {"a": ["Gout flare."]}, 1000)
    assert [e["did"] for e in got.shown] == ["a", "b", "c"]  # newest first, whatever the ranking
    assert got.left_out == 0 and got.cut == []
    assert got.shown[0] == {"date": "2026-10-01", "note_type": "progress", "text": "Gout flare.", "did": "a"}


def test_the_evidence_notes_are_read_first_and_the_rest_counts_as_left_out() -> None:
    """The ranking decides what is read first, never what counts as read (review H4)."""
    long = FILLER * 40
    window = [_n("new", "2026-10-01", long), _n("mid", "2026-09-01", long), _n("old", "2026-08-01", "Gout flare.")]
    one = note_tokens(long)
    got = build(window, {"old": ["Gout flare."]}, one + note_tokens("Gout flare.") + 5)
    assert [e["did"] for e in got.shown] == ["new", "old"]  # the evidence note, then the newest that fits
    assert got.left_out == 1 and got.cut == ["mid"]
    none = build(window, {}, one + 5)  # no ranking: newest first, and the decisive old note is left out
    assert [e["did"] for e in none.shown] == ["new"] and none.left_out == 2


def test_a_note_that_does_not_fit_is_cut_around_its_evidence_and_counts_as_left_out() -> None:
    key = "右第一MTP関節の急性痛風発作。"
    long = FILLER * 400 + key + "\n" + FILLER * 400
    got = build([_n("n", "2026-10-01", long), _n("o", "2026-09-01", "Colchicine given.")], {"n": [key]}, 600)
    by = {e["did"]: e["text"] for e in got.shown}
    assert key in by["n"] and len(by["n"]) < len(long) and note_tokens(by["n"]) <= 300  # half the budget
    assert by["o"] == "Colchicine given."  # one long note never hides the others (D-142, review A-06)
    assert got.left_out == 1 and got.cut == ["n"]  # cut: not read in full, whatever is shown of it
    # whole sentences of the note (a quote is found in it), and where text was left out the excerpt says so (D-641)
    assert all(s in long for s in by["n"].split("\n") if s != GAP) and by["n"].split("\n")[0] == GAP


def test_a_ranking_orders_the_reading_of_its_notes_best_first() -> None:
    """``ranked``: the note the ranking puts first is read first, even when it is the older one."""
    long = FILLER * 40
    window = [_n("new", "2026-10-01", long), _n("old", "2026-08-01", long)]
    budget = note_tokens(long) + 5  # room for one
    by_rank = build(window, {"old": ["x"], "new": ["y"]}, budget, ranked=True)
    assert [e["did"] for e in by_rank.shown] == ["old"] and by_rank.cut == ["new"]
    by_date = build(window, {"old": ["x"], "new": ["y"]}, budget)
    assert [e["did"] for e in by_date.shown] == ["new"] and by_date.cut == ["old"]


def test_a_short_note_that_no_longer_fits_is_skipped_never_shredded() -> None:
    """Only an evidence note longer than half the budget is cut, to that half; the others are whole or absent."""
    note = FILLER * 20
    one = note_tokens(note)
    window = [_n(f"n{i}", f"2026-09-{i:02d}", note) for i in range(1, 7)]
    got = build(window, {n.did: [FILLER.strip()] for n in window}, 2 * one + one // 2)
    assert [e["text"] == note for e in got.shown] == [True, True] and got.left_out == 4


def test_an_empty_note_is_not_shown_and_is_left_out() -> None:
    """Review of T-710 (MED 1): a window note with no text (a scanned note, an unreadable one) is something in the
    window the models did not see. It is not shown and it counts as left out, so a "not met" beside it is not
    final. (The first version skipped it without counting.)"""
    got = build([_n("e", "2026-10-01", "  \n"), _n("a", "2026-09-01", "Gout flare.")], {}, 1000)
    assert [e["did"] for e in got.shown] == ["a"] and got.left_out == 1 and got.cut == ["e"]


def test_notes_of_one_day_are_shown_in_their_own_order_whatever_the_input_order() -> None:
    """Review of T-710 (LOW 4, 5): an uploaded chart's paragraphs of one day (#1 .. #11) reach the models in
    order (a lead-in before its list), not as strings sort (#10 before #9); two notes of one id and day come out
    in one order whatever order they were given in."""
    paras = [_n(f"chart#{i}", "2026-10-01", f"Paragraph {i}.") for i in range(1, 12)]
    older = _n("old#1", "2026-09-01", "Older.")
    want = [f"chart#{i}" for i in range(1, 12)] + ["old#1"]
    assert [e["did"] for e in build([older, *paras], {}, 5000).shown] == want
    assert [e["did"] for e in build([*reversed(paras), older], {}, 5000).shown] == want
    twins = [_n("d", "2026-10-01", "Beta."), _n("d", "2026-10-01", "Alpha.")]
    one = [e["text"] for e in build(twins, {}, 5000).shown]
    assert one == [e["text"] for e in build(twins[::-1], {}, 5000).shown] == ["Alpha.", "Beta."]


# ------------------------------------------------------------------------------------------------ NEW-LLM-1 (D-641)
# LLM-001: the clip joined sentences that were not next to each other and dropped the heading or the lead-in that
# governs them, so a family-history list or a denied list read as the patient's own history.
def _adjacent_or_marked(part: str, text: str) -> bool:
    """Every run of lines between two ``[…]`` is a run of the note's sentences next to each other, the runs in the
    note's order; the excerpt starts (ends) with ``[…]`` exactly when it does not start (end) where the note does."""
    whole = "\n" + "\n".join(sentences(text)) + "\n"
    blocks = ["\n" + "\n".join(b) + "\n" for b in _split(part.split("\n"))]
    at = 0
    for b in blocks:
        at = whole.find(b, at)
        if at < 0:
            return False
        at += len(b) - 1
    lines = part.split("\n")
    starts = (lines[0] == GAP) != whole.startswith(blocks[0])
    ends = (lines[-1] == GAP) != whole.endswith(blocks[-1])
    return starts and ends and GAP + "\n" + GAP not in part


def _split(lines: list[str]) -> list[list[str]]:
    out: list[list[str]] = [[]]
    for line in lines:
        if line == GAP:
            out.append([])
        else:
            out[-1].append(line)
    return [b for b in out if b]


def test_a_clipped_note_keeps_the_heading_of_its_evidence() -> None:
    text = "【既往歴】\n高血圧。\n" + "経過良好。\n" * 400 + "【家族歴】\n肺結核。"
    got = clip(_n("n", "2026-10-01", text), ["肺結核。"], 300)
    assert "【家族歴】\n肺結核。" in got and note_tokens(got) <= 300
    assert "【既往歴】\n肺結核。" not in got and _adjacent_or_marked(got, text)


def test_a_clipped_note_keeps_the_negation_scope_of_its_evidence() -> None:
    text = "経過良好。\n" * 400 + "以下の既往なし：\n糖尿病\n肺結核"
    got = clip(_n("n", "2026-10-01", text), ["肺結核"], 300)
    assert "以下の既往なし：\n糖尿病\n肺結核" in got and _adjacent_or_marked(got, text)


def test_the_two_notes_of_the_review_are_not_stitched() -> None:
    """The run of LLM-001: tuberculosis only under the family history (ja); a denied list (zh-TW)."""
    ja = (
        "【現病歴】\n" + "".join(f"第{i}病日、経過良好、バイタル安定。\n" for i in range(1, 160))
        + "【既往歴】\n高血圧。\n" + "経過観察を継続する。\n" * 40 + "【家族歴】\n肺結核。\n"
    )  # fmt: skip
    got = clip(_n("n", "2026-10-01", ja), ["肺結核。"], 1250)
    assert "【家族歴】\n肺結核。" in got and "高血圧。\n肺結核。" not in got and _adjacent_or_marked(got, ja)
    zh = (
        "【現病史】\n" + "".join(f"第{i}日，病況穩定，生命徵象平穩。\n" for i in range(1, 180))
        + "【過去病史】\n病人否認下列病史：\n糖尿病。\n高血壓。\n肺結核。\nB型肝炎。\n" + "持續追蹤觀察。\n" * 60
    )  # fmt: skip
    got = clip(_n("n", "2026-10-01", zh), ["肺結核。", "B型肝炎。"], 1250)
    assert "【過去病史】\n病人否認下列病史：\n糖尿病。\n高血壓。\n肺結核。\nB型肝炎。" in got
    assert _adjacent_or_marked(got, zh) and note_tokens(got) <= 1250


def test_a_lead_in_is_shown_only_joined_to_its_evidence_and_never_across_a_heading() -> None:
    """Review of #419 (H1, M2): the first version showed a colon line above the evidence across a gap. A "none of
    the following:" far above then sat right over a positive finding it does not govern. A colon line is shown
    only when every line between it and the evidence is shown; a bracketed heading may stand across a gap."""
    items = [f"項目{i}の既往。" for i in range(300)]
    text = "【既往歴】\n以下の既往なし：\n" + "\n".join(items) + "\n肺結核"
    got = clip(_n("n", "2026-10-01", text), ["肺結核"], 120)
    lines = got.split("\n")
    assert lines[:2] == ["【既往歴】", GAP] and lines[-1] == "肺結核"  # the heading; the cut said; the list's end
    assert "以下の既往なし：" not in got and _adjacent_or_marked(got, text) and note_tokens(got) <= 120
    # a heading between the lead-in and the evidence ends the lead-in's scope: it is not carried over
    text = "以下の既往なし：\n糖尿病\n" + "経過良好。\n" * 400 + "【家族歴】\n肺結核"
    got = clip(_n("n", "2026-10-01", text), ["肺結核"], 120)
    assert "【家族歴】\n肺結核" in got and "以下の既往なし：" not in got


def _colon_before_gap(part: str, evidence: list[str]) -> list[str]:
    lines = part.split("\n")
    return [
        a for a, b in pairwise(lines)
        if b == GAP and a.endswith(("：", ":")) and a not in evidence
    ]  # fmt: skip


def test_a_soap_diary_is_shown_as_context_not_as_a_column_of_colon_lines() -> None:
    """Review of #419 (H1), by running: 150 days of S：/O：/A：/P： gave 244 colon lines, 245 marks and one line."""
    days = "".join(
        f"S：\n{d}日目、咳あり。\nO：\n体温37.{d % 10}度。\nA：\n経過観察{d}。\nP：\n継続{d}。\n" for d in range(150)
    )
    text = days + "A：\n肺結核の疑い。\nP：\n喀痰検査。"
    got = clip(_n("n", "2026-10-01", text), ["肺結核の疑い。"], 300)
    assert "A：\n肺結核の疑い。" in got and got.count(GAP) == 1 and _adjacent_or_marked(got, text)
    assert _colon_before_gap(got, ["肺結核の疑い。"]) == [] and note_tokens(got) <= 300
    assert len([x for x in got.split("\n") if not x.endswith("：") and x != GAP]) > 20  # context, not an outline


def test_a_denial_far_above_is_not_put_over_a_positive_finding() -> None:
    """Review of #419 (H1): vitals lines, a denied list, a bare heading, prose, then a diagnosis."""
    text = (
        "バイタル：\n" * 260 + "以下の既往なし：\n糖尿病\n喘息\n現病歴\n"
        + "".join(f"第{i}病日、咳が続く。\n" for i in range(40)) + "喀痰培養で肺結核と診断した。"
    )  # fmt: skip
    for cap in (60, 120, 300):
        got = clip(_n("n", "2026-10-01", text), ["喀痰培養で肺結核と診断した。"], cap)
        assert "以下の既往なし：" not in got or "以下の既往なし：\n糖尿病\n喘息\n現病歴\n第0病日" in got, cap
        assert _colon_before_gap(got, []) == [] and _adjacent_or_marked(got, text)


@pytest.mark.parametrize("bullet", ["● ", "■ ", "#", "・", "- ", "□ "])
def test_the_items_of_a_bulleted_list_are_not_headings(bullet: str) -> None:
    """Review of #419 (M1): "● 糖尿病" was read as a heading, so the lead-in of a ● list was cut off from it."""
    text = "経過良好。\n" * 400 + "【既往歴】\n病人否認下列病史：\n" + "".join(f"{bullet}項目{i}\n" for i in range(200))
    text += f"{bullet}肺結核\n" + "経過良好。\n" * 400
    got = clip(_n("n", "2026-10-01", text), [f"{bullet}肺結核"], 120)
    # the list is longer than the cap: its section's heading still stands above it (the item before is no heading)
    assert "【既往歴】" in got and f"{bullet}項目199\n{bullet}肺結核" in got and _adjacent_or_marked(got, text)
    # and a symbol-led line that stands alone is still a heading
    text = "経過良好。\n" * 400 + "■ 家族歴\n" + "".join(f"所見{i}。\n" for i in range(200)) + "肺結核。"
    got = clip(_n("n", "2026-10-01", text), ["肺結核。"], 120)
    assert "■ 家族歴" in got and _adjacent_or_marked(got, text)


def test_a_quote_is_never_found_across_a_cut_or_in_the_mark_itself() -> None:
    """Review of #419 (M3): the quote check folds "…" to "..." and joined the lines on both sides of a mark, so
    "[…]", "..." and a quote running over a cut verified although none is in the note."""
    from matching.cascade.judge import JudgeReply, verify_span
    from tb_common.quotes import quote_in

    part = f"【既往歴】\n高血圧。\n{GAP}\n【家族歴】\n肺結核。"
    for bad in (
        GAP,
        "...",
        "…",
        "[...]",
        f"{GAP}【家族歴】",
        "高血圧。【家族歴】",
        f"高血圧。{GAP}【家族歴】",
        "高血圧。...【家族歴】",
    ):
        assert not quote_in(bad, part), bad
    for good in ("肺結核。", "【家族歴】 肺結核。", "【既往歴】高血圧。"):  # inside one run, over its line break
        assert quote_in(good, part), good
    assert quote_in("経過観察...", "所見。\n経過観察...\n以上。")  # dots the note itself holds are still a quote
    ex = [{"did": "d", "date": "2026-10-01", "text": part}]
    lo, hi = date(2026, 1, 1), date(2026, 12, 31)

    def span(quote: str) -> Any:
        reply = JudgeReply(verdict="fail", confidence=0.9, quote=quote, quote_date=None, reason="")
        return verify_span(reply, ex, lo, hi)

    assert span(GAP) is None and span("高血圧。【家族歴】") is None and span("...") is None
    got = span("【家族歴】肺結核。")
    assert got is not None and got["did"] == "d"


def test_with_almost_no_room_the_first_evidence_sentence_that_fits_is_shown() -> None:
    """Review of #419 (L1): only the first evidence sentence was tried; then the note's first characters."""
    text = (
        "経過良好。\n" * 50
        + "長い長い長い長い長い長い長い長い長い長い長い長い所見の肺結核。\n"
        + "経過良好。\n" * 50
        + "肺結核。"
    )
    cap = note_tokens("肺結核。") + 2
    got = clip(
        _n("n", "2026-10-01", text), ["長い長い長い長い長い長い長い長い長い長い長い長い所見の肺結核。", "肺結核。"], cap
    )
    assert got == "肺結核。"


def test_two_pieces_of_evidence_far_apart_are_two_windows_with_the_gap_between() -> None:
    text = (
        "【主訴】\n発熱。\n"
        + "経過良好。\n" * 300
        + "【既往歴】\n痛風発作あり。\n"
        + "経過良好。\n" * 300
        + "【家族歴】\n肺結核。"
    )
    got = clip(_n("n", "2026-10-01", text), ["肺結核。", "痛風発作あり。"], 200)
    assert "【既往歴】\n痛風発作あり。" in got and "【家族歴】\n肺結核。" in got
    assert got.index("痛風発作あり。") < got.index(GAP, got.index("痛風発作あり。")) < got.index("【家族歴】")
    assert _adjacent_or_marked(got, text) and note_tokens(got) <= 200


def test_the_check_of_these_cases_sees_a_stitched_excerpt() -> None:
    text = "【既往歴】\n高血圧。\n経過良好。\n【家族歴】\n肺結核。"
    assert not _adjacent_or_marked("【既往歴】\n肺結核。", text)  # what the clip gave before: stitched
    assert not _adjacent_or_marked("【既往歴】\n[…]\n【家族歴】", text)  # the end is cut and not said
    assert _adjacent_or_marked("【既往歴】\n[…]\n【家族歴】\n肺結核。", text)


def test_any_clip_fits_its_cap_and_is_never_stitched() -> None:
    import random

    rng = random.Random(641)
    for case in range(200):
        n = rng.randint(3, 120)
        sents = []
        for i in range(n):
            kind = rng.random()
            body = f"所見{case}-{i}" + "あ" * rng.randint(0, 30)
            sents.append(f"【節{i}】" if kind < 0.08 else body + "：" if kind < 0.18 else body + "。")
        text = "\n".join(sents)
        note = _n("n", "2026-10-01", text)
        ev = rng.sample([x for x in sents if x.endswith("。")] or sents, k=min(rng.randint(0, 3), 1 + n // 10))
        cap = note_tokens("") + rng.randint(40, 400)
        got = clip(note, ev, cap)
        assert note_tokens(got) <= cap, (case, cap, got)
        assert _adjacent_or_marked(got, text), (case, got)
        assert _colon_before_gap(got, ev) == [], (case, got)  # no lead-in left hanging over a cut
        if ev and cap - note_tokens("") > 80:
            assert any(x in got.split("\n") for x in ev), (case, got)  # room for a sentence: evidence is shown


def test_a_cut_note_in_the_cascade_shows_its_heading_and_is_still_left_out() -> None:
    """The stop-gap stays (D-479): a clipped note is left out, whatever it now shows."""
    text = "【既往歴】\n高血圧。\n" + "経過良好。\n" * 3000 + "【家族歴】\n肺結核。"
    note = cascade_engine._Note("d", date(2026, 10, 1), "discharge", text, sentences(text))
    shown, left = cascade_engine._Run.excerpt_set([note], {"d": {"肺結核。"}})
    assert left == 1 and "【家族歴】\n肺結核。" in shown[0]["text"] and GAP in shown[0]["text"]


def test_a_note_without_evidence_that_does_not_fit_is_skipped_not_cut() -> None:
    got = build([_n("n", "2026-10-01", FILLER * 400)], {}, 300)
    assert got.shown == [] and got.left_out == 1


def test_a_retrieved_chunk_is_evidence_for_the_sentences_it_holds() -> None:
    """The v1 ranking gives chunks, not sentences: the note is cut around the chunk's sentences."""
    key = "Tophus on the left ear."
    long = FILLER * 300 + key + "\n" + FILLER * 300
    chunk = FILLER + key + "\n" + FILLER
    got = build([_n("n", "2026-10-01", long)], {"n": [chunk]}, 400)
    assert key in got.shown[0]["text"] and got.left_out == 1


def test_a_line_the_chunk_shares_with_the_whole_note_does_not_crowd_out_its_own_sentence() -> None:
    """D-645: a chunk holds a line the note repeats (a daily "no change"): every copy counted as evidence and was
    taken first, in the note's order, so whether the chunk's own sentence was shown hung on the tokens left over
    (the test above passed at 400 and would not have at 410, 420, 440 or 800). The sentence the note says once
    goes first, at every budget that forces a cut."""
    key = "Tophus on the left ear."
    long = FILLER * 300 + key + "\n" + FILLER * 300
    chunk = FILLER + key + "\n" + FILLER
    missing = [b for b in range(120, 3000, 10)
               if key not in build([_n("n", "2026-10-01", long)], {"n": [chunk]}, b).shown[0]["text"]]  # fmt: skip
    assert missing == []


def test_a_repeated_evidence_sentence_is_still_shown_once_before_any_second_copy() -> None:
    """Review of D-645: "once before repeated" by the total count dropped a decisive line the note says twice
    (a chunk's line also written elsewhere), and a lexicon hit a daily note repeats. One copy of every distinct
    evidence sentence goes first; second copies after."""
    lines = [f"Line {i} of the stay, nothing new." for i in range(400)]
    lines[5] = lines[200] = "Tophus on the left ear."
    note = _n("n", "2026-10-01", "\n".join(lines))
    chunk = "\n".join(lines[190:230])
    missing = [b for b in range(120, 1800, 10)
               if "Tophus on the left ear." not in build([note], {"n": [chunk]}, b).shown[0]["text"]]  # fmt: skip
    assert missing == []
    # the cascade's shape: exact sentences; one hit repeated daily beside sixty hits said once
    daily = "痛風発作あり。"
    once = [f"痛風発作の既往{i}回目を確認した。" for i in range(60)]
    text = "\n".join(x for i in range(60) for x in (daily, once[i], "経過良好。"))
    for cap in (100, 200, 400, 800, 1250):
        assert daily in clip(_n("n", "2026-10-01", text), [daily, *once], cap).split("\n"), cap


def test_with_room_for_one_line_more_the_lead_in_goes_before_the_heading() -> None:
    """D-645: the heading was taken first; with room for one of the two the excerpt read "[...] 【過去病史】 [...]
    肺結核。": the denied list under the title of the patient's own history. From the first budget that holds the
    lead-in with its evidence, the lead-in is shown; below it the heading may still stand (second review: under
    "family history" it is the context, and hiding it gains nothing)."""
    text = "【過去病史】\n" + "高血壓。\n" * 40 + "病人否認下列病史：\n肺結核。\nB型肝炎。"
    note = _n("n", "2026-10-01", text)
    shown = {cap: clip(note, ["肺結核。"], cap).split("\n") for cap in range(note_tokens("肺結核。"), 200)}
    with_lead_in = [cap for cap, lines in shown.items() if "病人否認下列病史：" in lines]
    assert with_lead_in == list(range(with_lead_in[0], 200))  # once it fits, always
    assert all(shown[c][shown[c].index("病人否認下列病史：") + 1] == "肺結核。" for c in with_lead_in)
    assert "【過去病史】" not in shown[with_lead_in[0]]  # room for one of the two: the lead-in is the one
    family = "【既往歴】\n" + "高血圧症。\n" * 20 + "【家族歴】\n" + "父：" + "あ" * 40 + "：\n肺結核。\n糖尿病。"
    cut = clip(_n("n", "2026-10-01", family), ["肺結核。"], 60).split("\n")
    assert "【家族歴】" in cut and "肺結核。" in cut  # a lead-in too long to fit does not hide the heading


def test_one_line_longer_than_the_cap_is_cut_in_a_few_steps_whatever_it_holds() -> None:
    """Review of D-645: the cut of an over-long line walked at character costs of its own (a digit a quarter) and
    then dropped one character at a time, each with a count of the whole text: minutes for a long run of digits."""
    calls = 0

    def counted(text: str) -> int:
        nonlocal calls
        calls += 1
        return note_tokens(text)

    for line in ("7" * 200_000, "あ" * 200_000, "x" * 200_000, "7あx " * 50_000):
        calls = 0
        got = clip(_n("n", "2026-10-01", line), [], 1250, counted)
        assert got and line.startswith(got) and note_tokens(got) <= 1250 < note_tokens(line[: len(got) + 8])
        assert calls <= 60, calls


def test_clip_and_sentences_are_the_cascades_own() -> None:
    assert sentences("痛風発作。再診予定！\nUric acid 9.1? ok") == ["痛風発作。", "再診予定！", "Uric acid 9.1?", "ok"]
    assert cascade_engine.sentences is sentences  # type: ignore[attr-defined]  # one splitter
    note = _n("n", "2026-10-01", "First.\nSecond.\nThird.")
    assert clip(note, ["Third."], 10_000) == "First.\nSecond.\nThird."
    # the evidence sentence first, and the cut before it is said (D-641: "[…]" where text was left out)
    assert clip(note, ["Third."], note_tokens(GAP + "\nThird.") + 2) == GAP + "\nThird."
    assert clip(note, ["Third."], note_tokens("Third.") + 2) == "Third."  # no room to say it: the sentence alone
    start = clip(_n("n", "2026-10-01", "x" * 4000), [], note_tokens("") + 10)
    assert start == "x" * 40  # one sentence over the cap: the note's start


def test_the_cascade_counts_a_window_note_without_a_hit_as_left_out() -> None:
    """Review H4, the S2 half: a window note with no lexicon hit was neither shown nor counted."""
    hit = cascade_engine._Note("h", date(2026, 10, 1), "progress", "Gout clinic follow-up booked.",
                               ["Gout clinic follow-up booked."])  # fmt: skip
    text = (FILLER * 60) + "Painful swollen red first toe since Monday."
    other = cascade_engine._Note("o", date(2026, 9, 1), "progress", text, sentences(text))
    keep = {"h": {"Gout clinic follow-up booked."}}
    shown, left = cascade_engine._Run.excerpt_set([hit, other], keep, budget=200)
    assert [e["did"] for e in shown] == ["h"] and left == 1  # the other note did not fit: a "not met" is not final
    shown, left = cascade_engine._Run.excerpt_set([hit, other], keep, budget=20_000)
    assert [e["did"] for e in shown] == ["h", "o"] and left == 0  # room for the window: both are read


# ------------------------------------------------------------------------------------------------ the budget
class _Tells(ScriptedModel):
    """A scripted model that tells its context: ``room`` tokens for notes."""

    def __init__(self, model: str, answer: Any, room: int) -> None:
        super().__init__(model, answer)
        self.room = room

    def text_budget(self, prompt: str, fixed: dict[str, Any]) -> int:
        return self.room


def _judge(lake: Any, answer: str, judge_room: int | None, verifier_room: int | None,
           quote: str = FLARE) -> NoteJudge:  # fmt: skip
    def model(name: str, room: int | None) -> Any:
        return _Tells(name, says(answer, quote), room) if room is not None else ScriptedModel(name, says(answer, quote))

    return NoteJudge(lake=lake, llm=model("judge-a", judge_room), verifier=model("verifier-b", verifier_room))


def test_the_budget_is_the_smaller_context_of_the_pair_and_the_default_when_neither_tells() -> None:
    lake = _Chunks([_chunk(1, FLARE)])
    assert _judge(lake, "pass", 20_000, 9_000).excerpt_budget(INC, IDX) == 9_000
    assert _judge(lake, "pass", 20_000, None).excerpt_budget(INC, IDX) == 20_000
    assert _judge(lake, "pass", None, None).excerpt_budget(INC, IDX) is None
    assert DEFAULT_TOKENS == 2500 == cascade_engine.EXCERPT_TOKENS  # the one declared default of both pipelines
    assert not hasattr(evaluate, "CHUNK_TOKENS") and not hasattr(evaluate, "FULL_RECORD_MAX_CANDIDATES")


def test_the_v1_read_counts_a_window_note_the_retrieval_did_not_return() -> None:
    """Review H4, the v1 half: the retrieval returns two notes that say nothing; the third note of the window does
    not fit. Before, nothing was "left out" and both models' "not met" excluded the patient."""

    class Lake(_Chunks):
        def chunks_search(self, pid: str, query: str, k: int = 5, **kw: Any) -> list[dict[str, Any]]:
            return [c for c in self.chunks if c["did"] != "D3"]

    lake = Lake([_chunk(1, "Seen in clinic."), _chunk(2, "Seen in clinic."), _chunk(3, f"{FLARE}.\n" + FILLER * 300)])
    nj = _judge(lake, "fail", 1500, 1500, quote="Seen in clinic")
    got = nj.window("P", INC, IDX)
    assert {e["did"] for e in got.shown} == {"D1", "D2"} and got.cut == ["D3"]
    out = evaluate_patients(ruleset([INC]), ["P"], IDX, _NoStructured(), nj, 0.75, only={INC.id}, all_candidates=True)
    v = out["P"].verdicts[0]
    assert out["P"].tier == "review" and v.verdict == "unknown"
    assert v.evidence is not None and v.evidence.reason == "notes_over_budget"
    roomy = _judge(
        lake, "fail", 20_000, 20_000, quote="Seen in clinic"
    )  # control: with room for the window the pair's answer is final
    assert roomy.window("P", INC, IDX).left_out == 0
    out = evaluate_patients(ruleset([INC]), ["P"], IDX, _NoStructured(), roomy, 0.75, only={INC.id},
                            all_candidates=True)  # fmt: skip
    assert out["P"].tier == "excluded"


def test_a_window_with_notes_none_of_which_fits_is_unknown_not_no_notes() -> None:
    class Unranked(_Chunks):  # the retrieval returns nothing: the note is not evidence, so it is skipped, not cut
        def chunks_search(self, pid: str, query: str, k: int = 5, **kw: Any) -> list[dict[str, Any]]:
            return []

    nj = _judge(Unranked([_chunk(1, FILLER * 400)]), "fail", 100, 100)
    r = nj.judge_patient("P", INC, IDX)
    assert (r.predicate, r.reason, r.left_out) == ("unknown", "notes_over_budget", 1)
    empty = _judge(_Chunks([]), "fail", 100, 100).judge_patient("P", INC, IDX)
    assert (empty.predicate, empty.reason) == ("unknown", "no_notes")


def test_case_reads_the_chart_through_the_builder_and_the_judges_budget() -> None:
    """CASE showed the whole upload with no budget, and a "not met" on it was final whatever was read."""
    chart = [{"did": f"C{i}", "date": f"2026-09-{i:02d}", "note_type": "progress",
              "text": f"{FLARE}.\nVisit {i}.\n" + FILLER * 60} for i in range(1, 6)]  # fmt: skip
    small = ChartJudge(_judge(None, "fail", 1500, 1500), chart).decide(INC, IDX)
    assert (small.predicate, small.reason) == ("unknown", "notes_over_budget") and small.left_out > 0
    whole = ChartJudge(_judge(None, "fail", 20_000, 20_000), chart).decide(INC, IDX)
    assert whole.predicate == "fail" and whole.left_out == 0


# ------------------------------------------------------------------------------------------------ the acceptance case
@pytest.mark.parametrize(("gpu", "decided"), [("rtxpro6000", True), ("rtx5090", False)])
def test_five_long_notes_get_a_decided_verdict_on_a_32k_build(
    tmp_path: Path, gpu: str, decided: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row's acceptance: a patient with five long notes. On the 32k build the pair reads all five (through the
    real gateway and its context) and the answer is decided: ``high``. On the 8k build the same five do not fit:
    the answer is flagged and the patient goes to review, never out."""
    _, rec, app = _box(tmp_path, gpu, monkeypatch)
    lake = _Lake(n=5, lines=100)
    assert all(note_tokens(r["text"]) > 2000 for r in lake.rows)  # long: over 2,000 tokens each
    nj = NoteJudge(
        lake=lake,  # type: ignore[arg-type]
        llm=_client(app, "orchestrator", "j-workhorse"),
        verifier=_client(app, "orchestrator", "v-verifier"),
        job_id="STUDY-1",
    )
    room = nj.excerpt_budget(GOOD, INDEX)
    assert room is not None and 0 < room < PROFILES[gpu]  # from the context, not a fixed number
    got = nj.window("P", GOOD, INDEX)
    assert sum(note_tokens(e["text"]) for e in got.shown) <= room
    assert (got.left_out == 0) == decided and (len(got.shown) == 5) == decided
    out = evaluate_patients(ruleset([GOOD]), ["P"], INDEX, _NoStructured(), nj, 0.0, only={GOOD.id},
                            all_candidates=True)  # fmt: skip
    v = out["P"].verdicts[0]
    assert v.verdict == "pass" and nj.failures == 0, (v, nj.failures, rec.log)
    assert all(status == 200 for _, status in rec.log), rec.log
    assert out["P"].tier == ("high" if decided else "review")
    assert (v.evidence is not None and v.evidence.reason == "notes_over_budget") == (not decided)
    assert LINE in lake.rows[0]["text"] and room > excerpts.DEFAULT_TOKENS
