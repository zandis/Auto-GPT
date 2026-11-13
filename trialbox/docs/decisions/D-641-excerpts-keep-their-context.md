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
2. above each, its nearest heading. A heading is a line in brackets that holds a letter (`【家族歴】`, `〔家族歴〕`,
   `[Family history]`), or a line led by a list symbol that stands alone (`■ 家族歴`; next to another line led the
   same way it is an item, not a heading). A heading may stand across a cut: it governs until the next heading;
3. then each window grows by one sentence above and one below in turn. A direction ends at the first sentence that
   does not fit; nothing is skipped to fit a later, shorter line (that skipping was the stitch).

**A line that ends in a colon is shown only joined to what it governs.** The lead-in of a list (`以下の既往なし：`,
`病人否認下列病史：`, `Denies:`) and a heading written with a colon (`家族歴：`) are reached by the window growing
upwards, so every line between them and the evidence is shown too and the model reads the scope itself. A colon
line is never carried across a cut, and no window ends on one (or on a heading of text that is not shown): it
would read as governing what follows the cut. The first version of this card carried every colon line above the
evidence across cuts; the review showed a SOAP diary reduced to 244 `S：/O：/A：/P：` lines and one sentence, and a
"none of the following:" placed right over a diagnosis it did not govern.

The cost of every `[…]` is inside the cap. With no evidence sentence found in the note (a retrieved chunk that
matches no sentence), the window is the note's start. Two cases keep their old form: a cap too small for an
evidence sentence and its marks gives the first evidence sentence that fits, alone; a first sentence longer than
the cap gives the note's first characters, inside the cap.

**The quote check knows the mark** (`tb_common.quotes`: `CUT`, `runs`, `quote_in`; `verify_span`). A quote must lie
inside one unbroken piece of the excerpt. Before, the check joined the lines on both sides of a cut and folded `…`
to `...`, so `[…]`, `...` and a quote running over a cut verified although none of them is in the note.

No new setting and no new limit: the cap is still half the budget, and the budget is still the models' context
(T-603, `NoteJudge.excerpt_budget`) or `DEFAULT_TOKENS`.

**D-479 stands.** A clipped note still counts as left out, whatever it now shows. This card changes what the
models and the reviewer read, not what an answer on it may do.

## What this does not do

- It does not tell the model what `[…]` means: the judge prompt is pinned by approved rulesets (D-318), and a new
  prompt version is a card of its own. The mark is the common one for omitted text.
- A heading written as a bare word on a line (`家族歴`, `FAMILY HISTORY`, `1. 家族歴`) is not seen as one; it is
  shown only when the window reaches it.
- A list longer than the cap loses its lead-in: the evidence is then shown under its heading with the list's last
  items, and the cut is marked. With the budget taken from the models' context this is a list of hundreds of lines.
- A note line that is itself `[…]` reads as a cut.
- Whether the real pair answers better on these windows is not measured here (test G-03 of the review needs a GPU).
- The line-break join of sentences that stood on one line is as before.

## Test

`tests/unit/test_excerpts.py`: the two expected failures T-710 left are now plain tests (heading kept; lead-in and
its list kept); the two notes of the review; two pieces of evidence far apart are two windows with `[…]` between;
200 seeded random notes fit their cap, are never stitched and leave no colon line hanging over a cut; the checker
itself rejects the old stitched form; in the cascade a clipped note shows its heading and is still left out. From
the review of this card: a lead-in is shown only joined to its evidence and never across a heading; a SOAP diary
is shown as context; a denial far above is not put over a positive finding; the items of a bulleted list are not
headings; a quote is never found across a cut or in the mark; with almost no room the first evidence sentence
that fits is shown.
