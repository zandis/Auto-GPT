# D-653 Whether the values behind a row's coded answers were read is kept per row

- **Task:** CODED-values-read-per-row (a finding of the review of lane C2's follow-up to D-652; placed by the
  integrator)
- **PR:** this branch (`agent/CODED-values-read-per-row`), cut from `origin/train/14` (`45416a9b`), which holds
  D-652 (#540)
- **Date:** 2026-11-13
- **Status:** proposed (merges on a green train)
- **Builds on:** D-652 (a lake read that failed is said), D-362 (the values behind a coded answer)

## Context

D-652 recorded a failed read of the coded values per run: `ScreenRun.coded_values_read`, written into the
screening run's stored list of excluded patients. Two things were wrong with "per run":

- A weekly or after-ingest run (MICROBATCH) publishes the candidate list and never that list, and records the
  flag nowhere. The console's patient page reads the study's **latest** screening job. As soon as a weekly run
  was the latest, the sentence "the values could not be read" was gone, though the rows the weekly run carried
  from the screening run still had no values.
- A weekly run whose own read failed never said so at all.

The console cannot mend this: the fact is not in what it reads.

## Decision

1. **The answer carries it.** When the read of the values fails, every answer whose values would have been read
   (a coded answer with records, an age or sex answer) gets `evidence.coded_read: false`. The answer's verdict
   and its other evidence are untouched. A read that is made writes the answer without the mark.
2. **So it travels with the row.** The pool stores a row's answers as they are; a later run that carries the row
   carries the mark. A run that reads the row again (the screen of a new patient, of another criteria version, of
   an excluded patient looked at again) writes its answers anew: the mark goes if that read was made, and is set
   if it failed.
3. **The row says it.** A row of the candidate list has `coded_values: "not read"` while any of its answers
   carries the mark. The summary has `coded_values_not_read`: how many rows of the run say so (listed or not).
4. **Nothing is written when everything was read.** No field on the answer, the row or the summary: a run that
   read everything writes the same bytes as before this card, so a re-run of an older job still compares equal.

Three optional fields in `schemas/candidate_list.schema.json` (`evidence.coded_read`, `candidate_row.coded_values`,
`tier_summary.coded_values_not_read`); the contract models are generated from it.

**For the console (lane C2):** per row `coded_values == "not read"`; per answer `evidence.coded_read is false`;
per run `summary.coded_values_not_read` (absent: none).

## What it does not do

- The weekly **re-check** of pool rows (`evaluate_scope`) never read coded values, before or after this card: an
  answer it writes anew has no values and no mark, like a list from before D-362. It makes no claim. Whether
  the re-check should read the values is a separate question (reported to the integrator).
- A row stored in the pool before this card after a failed read has no mark; nothing can tell it now.
- D-652's `coded_values` in the stored list of excluded patients stays as it is.

## Test

`tests/unit/test_coded_values_read_per_row.py`: a failed read marks the coded answers and the age and sex answers,
not a note's; a read that is made takes the mark away; the row and the screening run's list; a screening run with
a failed read followed by a weekly run (the carried row still says not read, the rows the weekly run read do not);
a weekly run whose own read failed; a weekly run with nothing unread writes the list as before.
