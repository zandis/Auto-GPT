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
3. **The weekly re-check keeps it.** The re-check of the pool's booked patients writes their coded answers
   anew and reads no values (it never did). An answer whose values the last read could not get still has none:
   the new answer keeps the mark, until a run reads the values.
4. **The row says it.** A row of the candidate list has `coded_values: "not read"` while any of its answers
   carries the mark. The summary has `coded_values_not_read`: how many rows **of that list** say so, so the
   figure can be checked against the list (a screening run's excluded patients are not on the list and not in
   the figure; their own list has D-652's `coded_values`).
5. **Nothing is written when everything was read.** No field on the answer, the row or the summary: a run that
   read everything writes the same bytes as before this card, so a re-run of an older job still compares equal.

Three optional fields in `schemas/candidate_list.schema.json` (`evidence.coded_read`, `candidate_row.coded_values`,
`tier_summary.coded_values_not_read`); the contract models are generated from it.

**For the console (lane C2):** per row `coded_values == "not read"`; per answer `evidence.coded_read is false`;
per run `summary.coded_values_not_read` (absent: none).

## What it does not do

- The weekly re-check still reads no coded values (item 3 keeps the mark through it; it does not fetch them).
  Whether it should is a separate question; the integrator's word: no card now.
- A weekly run whose own read failed only for patients who did not come onto the list (excluded patients looked
  at again and still excluded) changes no row of the list and says it only in the log.
- A row stored in the pool before this card after a failed read has no mark; nothing can tell it now.
- D-652's `coded_values` in the stored list of excluded patients stays as it is. That list's answers now carry
  `coded_read: false` too; the console reads its keys by name and shows nothing new for it.
- **A box rolled back to the code before this card** after a failed read cannot read the marked pool rows (the
  older models refuse a field they do not know): every weekly run of that study fails until a screening run
  writes the pool again. The same has held for every field added to an answer (`coded`, D-362). Update forwards.
- A re-run of a job whose first run had a failed read differs from it on a healthy lake, as in D-652.

## Test

`tests/unit/test_coded_values_read_per_row.py`: a failed read marks the coded answers and the age and sex answers,
not a note's; a read that is made takes the mark away; the row and the screening run's list; a screening run with
a failed read followed by a weekly run (the carried row still says not read, the rows the weekly run read do not);
a weekly run whose own read failed; a weekly run with nothing unread writes the list as before.

The weekly re-check: its stand-in returns a new coded answer for a booked patient, and the row still says not read.

## Review

One adversarial review by running (on `db6ca269`), on the in-process box with the real pool: a clean screening
run, one with the values' reads failing, a weekly run, a weekly run with the reads failing, a good screening run.
Verdict: fix first.

| Finding | Confirmed | What was done |
|---|---|---|
| HIGH: the weekly re-check took "not read" away from the rows it re-checked (4 of 11), for good, though they still had no values; the unit test passed only because its stand-in re-check returned no answer | by running | item 3; a test whose stand-in returns the answer |
| MED: a pool row written by this card cannot be read by the code before it | by running the older models | stated above |
| MED: the summary's figure meant different things in the two runs (the screening run counted its 354 excluded patients; the weekly run could not) | by running | the figure counts the list's own rows in both |
| LOW: the branch that clears a mark is not reached in production (answers are written anew); a re-run differs after a failed read; the excluded list now carries the per-answer mark; no mailed workbook says it | by running, by reading | stated |

Held (the reviewer's runs): rows not re-checked keep the mark out of the real pool; the pool stores no null
field; old rows validate; a re-run of the weekly run is byte-identical; a clean screening run has none of the new
keys anywhere and its re-run is identical; the list validates against its schema; eight mutations each fail a
test. The fixes after the review were not reviewed again.
