# D-641 A clipped note keeps its heading and the lead-in of its list, and says where it was cut

- **Task:** NEW-LLM-1 (TB-PLAN-07 v7.3, wave 1, lane A); deep review 2026-11-12, finding LLM-001 (Blocker), part (b)
- **PR:** this branch (`agent/NEW-LLM-1-excerpts-keep-context`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on a green train and one adversarial review)
- **Builds on:** D-479 (one excerpt builder; a clipped note counts as left out), D-142 (one long note never hides
  the others), D-276 and T-603 (an answer on a cut record that would exclude is not final)

## Context

An evidence note longer than half the excerpt budget is cut to that half. The cut took the evidence sentences and
then sentences from the note's start, and joined them with a line break. Sentences that were pages apart read as
neighbours. A Japanese discharge summary with `肺結核。` only under `【家族歴】` reached both models as
`【既往歴】 … 肺結核。`; a Chinese list under `病人否認下列病史：` reached them without that line. The quote is in the
note, so the quote check passed, and both models read the same text.

D-479 made such an answer not final (a clipped note is left out: an answer that would exclude becomes unknown, one
that keeps the patient is flagged). That is a stop-gap: the person who then opens the case is shown the same
stitched text and the same quote, and the models' answer on it is noise.

## Decision

`matching.excerpts.clip` is rewritten. The one rule: **lines shown next to each other are next to each other in the
note**. Wherever sentences were left out (at the start, between two windows, at the end) the excerpt shows `[…]` on
a line of its own (`excerpts.GAP`). Still only whole sentences of the note, in the note's order.

What is shown, in this order while it fits the cap:

1. each evidence sentence;
2. above each, what governs it: the lines ending in a colon above it (a heading written `家族歴：`, the lead-in of a
   list such as `以下の既往なし：`, `病人否認下列病史：`, `Denies:`), nearest first, up to and with the nearest
   bracketed heading (`【家族歴】`, `[Family history]`, `■ 家族歴`). A bracketed heading ends the scope of every
   lead-in above it: a lead-in is never carried across a heading;
3. the sentences between that and the evidence, from the evidence upwards, so that where there is room the
   lead-in, its list and the evidence are one unbroken run; where there is not, the lead-in, `[…]`, and the lines
   just above the evidence;
4. then each window grows by one sentence below and one above in turn. A direction ends at the first sentence that
   does not fit; nothing is skipped to fit a later, shorter line (that skipping was the stitch).

The cost of every `[…]` is inside the cap. With no evidence sentence found in the note (a retrieved chunk that
matches no sentence), the window is the note's start. Two cases keep their old form: a cap too small for the first
evidence sentence and its markers gives that sentence alone, and a first sentence longer than the cap gives the
note's first characters.

No new setting and no new limit: the cap is still half the budget, and the budget is still the models' context
(T-603, `NoteJudge.excerpt_budget`) or `DEFAULT_TOKENS`.

**D-479 stands.** A clipped note still counts as left out, whatever it now shows. This card changes what the
models and the reviewer read, not what an answer on it may do.

## What this does not do

- It does not tell the model what `[…]` means: the judge prompt is pinned by approved rulesets (D-318), and a new
  prompt version is a card of its own. The mark is the common one for omitted text.
- A heading is told by its brackets or its colon. A heading written as a bare word on a line (`家族歴`) is not
  seen as one; it is shown only when the window reaches it.
- Whether the real pair answers better on these windows is not measured here (test G-03 of the review needs a GPU).
- The line-break join of sentences that stood on one line is as before.

## Test

`tests/unit/test_excerpts.py`: the two expected failures T-710 left are now plain tests (heading kept; lead-in and
its list kept); the two notes of the review; a lead-in far above its evidence is shown with the gap marked, and
not across a heading; two pieces of evidence far apart are two windows with `[…]` between; 200 seeded random notes
fit their cap and are never stitched; the checker itself rejects the old stitched form; in the cascade a clipped
note shows its heading and is still left out.
