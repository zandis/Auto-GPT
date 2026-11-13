# D-645 A digit counts as a token; the cascade uses the one estimate; a clip takes the rare sentence first

- **Task:** review test G-5 of lane G's run C (2026-11-13): the worst real / estimated token ratio was 1.2121
  (zh-TW, the judge), over the share the budget keeps free (1 / `SAFETY` = 1.176)
- **PR:** this branch (`agent/LLM-token-estimate`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on a green train)

## What was measured first

Lane G's set (200 ja and 200 zh-TW synthetic excerpts, `tools.synth` sentences, its seed) counted here with the
tokenizer files of the registry's judge and verifier builds (text only, no special tokens). The largest ratio
real / estimate per estimate of the product:

| Estimate | ja, judge | ja, verifier | zh-TW, judge | zh-TW, verifier |
| --- | --- | --- | --- | --- |
| `tb_llm.budget.estimate_tokens` (sizes every prompt) | 0.941 | 0.909 | 1.111 | 0.972 |
| the cascade's `expected_tokens` (counts a call against the night's token budget) | 0.970 | 0.915 | **1.2121** | 1.061 |

So lane G's 1.2121 is reproduced exactly, and it is the cascade's count, which sizes no prompt. The estimate that
does size prompts was at 1.111: inside the share with G-5's 5 % (1.167 against 1.176), by less than one percent.

## Cause

Both tokenizers give every digit a token of its own ("民國115年3月14日" is 10 tokens on both); both estimates counted
digits as other text, four characters per token. A clinical note is full of numbers. The cascade's count also took
full-width punctuation (，：（）) as a quarter token: its range of "CJK" ended before the full-width forms.

## Decision

1. `estimate_tokens`: a digit is one token, like a CJK character. Other text stays at four characters per token.
   On the measured set no text has more tokens than the estimate (largest ratio 0.936 zh-TW, 0.914 ja), so
   `SAFETY` (0.85, unchanged) is all margin.
2. The cascade's `expected_tokens` is 300 plus `estimate_tokens` of each excerpt's text: one estimate (D-357).
3. Found on the way, in `matching.excerpts.clip`: evidence sentences were taken in the note's order. A retrieved
   chunk that holds a line the note repeats (a daily "no change") made every copy evidence, and the copies took
   the room of the chunk's own sentence; whether that sentence was shown hung on the tokens left over (the
   existing test passed at a budget of 400 and would not have at 410, 420, 440 or 800). Now a sentence the note
   says once is taken before one it repeats.

4. From the review of this card:
   - the first form of item 3 ordered by how often the note says a sentence, and so dropped a decisive line the
     note says twice (a chunk's line also written elsewhere; a lexicon hit a daily note repeats). The order is:
     one copy of every distinct evidence sentence, then second copies;
   - the cascade sized its excerpt set on the notes' text alone, while the prompt shows each note with its date
     and type as JSON: a window of some hundreds of short notes passed as "all shown, none left out" and the
     gateway then refused the whole call as too long (the pair's answer was unknown: it went to review; before
     this card from about 280 notes, with item 1 from about 225). The cascade's set is now sized with the count
     the prompt is sized with (`excerpts.note_tokens`), as the other two paths are;
   - one line longer than the cap was cut by a walk with character costs of its own, then one character at a
     time: minutes for a long run of digits. It is cut by halving.

5. Found by the whole unit suite on this card (the clipped-note cases of lane G's run, #439): with the larger
   count, at a budget of 90 the zh-TW denied list was shown as "[…] 【過去病史】 […] 肺結核。": the heading was
   taken before the line right above the evidence, and there was room for one of the two. `clip` now takes the
   evidence's lead-in (the line right above it when it ends in a colon) before the heading. (NEW-LLM-1, D-641,
   took the heading first.)
6. From the second review (of item 5 alone, by running, 29,647 clips of random notes against the parent: no
   property of D-641 lost):
   - a first form also hid the heading when the lead-in did not fit. Under 【家族歴】 that removed true context
     (the excerpt read as the patient's own history), and in the denial case bare evidence says no more of the
     denial than the heading did. Removed: the heading is shown as before when the lead-in does not fit;
   - **limits, as before this card:** the lead-in is taken only when it is the line right above the evidence. For
     the second and later items of a denied list, at caps of about 40 to 105 tokens, the heading can still stand
     across a cut without the denial line (a colon line further up is not carried across a cut: D-641's review).
     A colon written as U+FE30 or U+FE55, or a lead-in without a colon, is not seen as a lead-in. A label line
     ("処方：") right above the evidence is taken as its lead-in. The cap is half the budget and the smallest real
     budget is 2,500 tokens; a clipped note is left out and its answer never final, whatever the clip shows.

## What this changes for a site

Prompts with numbers are estimated larger, and the cascade counts each note's date and type, so slightly fewer
notes fit one judge prompt, and a night's token budget (when one is set) counts about 4 % (ja) to 9 % (zh-TW)
more per call. A note that no longer fits is left out and counted so (D-479): the answer goes to review,
never to a silent exclusion.

## What this does not do

- It does not measure the rendered prompt with the models' chat templates: G-5 does that on the model server.
  Without the template (role markers taken as 6 tokens a message) the prompt ratio here was at most 1.02 before
  this change.
- English text is not measured here; four characters per token stays as it was.
- `SAFETY` is not changed.

## Test

`tests/unit/test_token_estimate_measured.py` with `tests/fixtures/llm/token_counts_cjk.json` (the 400 excerpts and
their counts; the tokenizer files' sha256 are in it); `tests/unit/test_excerpts.py`
(`test_a_line_the_chunk_shares_with_the_whole_note_does_not_crowd_out_its_own_sentence`).
