# D-794 The note stage runs in batches of patients

- **Task:** T-694 part 3 (plan 28; placed with lane A2 on #593, 2026-11-15)
- **PR:** see the REGISTRY row
- **Date:** 2026-11-15
- **Status:** reserved
- **Builds on:** D-103 (the SCREEN cascade), D-456 (the pair budget), D-788 (notes-only rulesets)

## Decision

The cascade's S2 (the lexicon over the notes) and S2b (the embedder's ranking of the zero-hit pairs) read every
alive patient's notes at once: at 50,000 patients with 20 notes each, a million notes sat in memory before the first
judge call. `CascadeConfig.note_batch` now runs both stages on that many alive patients at a time, in the order of
the patients' traces. Each batch reads only its patients' notes, and lets them go after S2b; the routes keep only
their excerpts. A size below 1 is refused.

The answers are the same for any size, because each patient's S2 and S2b outcome depends on its own notes alone:

- the S2 and S2b stage logs are written once, from the totals, with the counts an unbatched run writes (S2's
  patients out are counted before any S2b exclusion);
- the routes go on to sampling and S3 in the order of an unbatched run: S2's routes, then S2b's, each by patient
  and criterion. A pair budget (`max_llm_items`) therefore stops at the same pair.

The test compares traces, stage logs and metrics for no batches and for 1, 7 and 1,000 patients a batch, with one
index date and with month-ends, and with a pair budget of 5.

SCREEN sets the size from `TB_SCREEN_NOTE_BATCH`, 1,000 patients when unset. Other callers (FEAS, the end-to-end
tool, the scale gate) keep `None`, one batch.

## Not changed

S3 and S4 (the judge and the verifier) are not batched: they already go pair by pair under the pair budget, and hold
excerpts only. S2b still asks the embedder once per pair, as before, so the number of embedder calls does not depend
on the batch size.

## Test

`tests/unit/test_note_stage_batches.py`.
