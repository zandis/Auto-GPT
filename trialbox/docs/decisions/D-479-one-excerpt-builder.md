# D-479 One excerpt builder: what the models read is chosen in one place, and every window note not shown counts as left out

- **Task:** T-710 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.1, wave D; TB-PLAN-06.1; absorbs T-696)
- **PR:** this branch (`agent/T-710-one-excerpt-builder`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Measures:** H4 and M5 of `docs/reviews/2026-11-12-architecture/decision.md` (card AD-4; root cause R3: the text
  a model reads is chosen by the caller, not by the judge); F-13 of the scale review (a 2,500-token excerpt budget
  whatever the model's context)
- **Builds on:** D-276 (both models read the same excerpts: with a note left out, "not met" is not final), T-603
  (the budget from the model's context; a record that did not fit is flagged), D-449 / PR #275 (the left-out fix
  on the cascade's S2b), D-478 (the one status function reads the flag), OD-10 (no fixed limit that is not
  derived from the hardware or the model)

## Context

The same note question was answered from different text on each path. The cascade showed the notes with a lexicon
hit, else the notes holding the top five sentences, inside a fixed 2,500 tokens. The v1 path (NAV, the MICROBATCH
re-check, SCREEN v1) showed the five chunks a retrieval returned and counted as "left out" only those of the five
that did not fit: every other note of the window was "not left out", so two models agreeing "not met" on five
chunks excluded the patient. CASE showed the whole upload with no budget. The v1 path read the full record a second
time only when its first answer was unknown and the run held at most 100 candidates, so a patient's status
depended on how many others were in the run.

## Decision

1. **One builder**, `services/matching/excerpts.py: build(window, evidence, budget)`. `window`: every note of the
   patient inside the criterion's window. `evidence`: what the path's ranking points at (the cascade's lexicon
   hits or top sentences, the v1 retrieval's chunks, nothing for CASE). It shows whole notes, the evidence notes
   first (in the ranking's own order where the path has one: S2b's top sentences, the v1 retrieval) and then the
   rest, newest first, until the budget is spent. An evidence note longer than half the budget is cut to that
   half, whole sentences around its evidence (as the cascade did); any other note that does not fit is skipped,
   never cut into the last few tokens. A window note with no text (a scan, an
   unreadable note) is not shown and **counts as left out**: it is in the window and the models did not see it
   (review of this card; the first version skipped it without counting, and a pair's "not met" beside it
   excluded). The shown notes are newest first, within a day in the notes' own order (`#9` before `#10`).
2. **"Left out" counts every window note not shown in full**: skipped, or clipped. With a note left out, a "not
   met" is not final (unknown, a person looks) and a "met" is flagged (review), on every path. The ranking decides
   what is read first, never what counts as read.
3. **The budget is the models' context** (T-603's `NoteJudge.budget`): what the judge's and the verifier's context
   leave beside the prompt and the answer. A client that cannot tell its context gets the declared default
   (`EXCERPT_TOKENS`, the size that fits the smallest registered build). No path has a fixed budget of its own.
4. **One read.** The v1 path's second "full record" read and its 100-candidate limit go: the first read already
   shows as much of the window as the models can hold.

5. **Not built here: NEW-LLM-1 (LLM-001).** A note cut by the builder keeps whole sentences around its evidence,
   but not the heading above them nor the negation they sit under: clipped, a Japanese family-history list
   loses `【家族歴】` and a "none of the following" list loses its lead-in (English and Traditional Chinese kept
   theirs in the review's cases only by the accident of sentence length). The stop-gap holds: every cut note is
   counted as left out before it is cut, so an answer that would exclude is not final on any path. Keeping the
   heading and the negation scope in a cut, in en, ja and zh-TW, is **the next card of this lane**; its two
   failing tests are in `tests/unit/test_excerpts.py` as strict expected failures.
6. **Not built here: the v1 path stays.** Plan v7.2 removes the v1 path at the end of T-709/T-710. NAV and the
   MICROBATCH re-check still judge through it (`NoteJudge`), now with the one builder. Removing it is its own
   card.

## Consequences

- **More review on a small context, by design.** Before, a patient whose evidence notes fitted was decided even
  when other notes of the window were never read. Now any window note not read in full makes a "not met" unknown
  and flags a "met". On a build with a large context the whole window is usually read and nothing changes; on an
  8k build, or with models that cannot tell their context (2,500 tokens), a patient with a long window goes to
  review. This is the excerpts invariant of TB-PLAN-06 §7.4 applied to every path; the review load it costs is
  what T-734's capacity statement has to show.

- On a 32k build a patient with five long notes is read whole and gets a decided verdict; on an 8k build the same
  patient is read in part and goes to review with the reason, never out.
- The last lines of the expected-failure tables of T-705 and T-706 (H4, M5) are removed.
- The pair is measured again on this code (TB-PLAN-06.1 §7: G1's first numbers were measured before it).
