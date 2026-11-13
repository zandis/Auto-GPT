# D-652 A lake read that failed is said in the output, not shown as "none"

- **Task:** LAKE-read-failed-is-said (four places found by the review of D-650; placed by the integrator)
- **PR:** this branch (`agent/LAKE-read-failed-is-said`), cut from #535 (`74ba273c`, D-651)
- **Date:** 2026-11-13
- **Status:** proposed (merges on a green train)
- **Builds on:** D-649 to D-651 (a missing table is asked of the lake), D-143 (the page "Criteria not matched"),
  D-135 (confirmed facts), D-120 (a doctor's name comes from the records), D-362 (the values behind a coded answer)
- **Outside lane A2's folders, placed by the integrator (lane C2's files):** `services/console/home.py`,
  `studies.py`, `i18n_review.py`, `i18n_home.py`, `templates/excluded.html`, and their tests.

## Context

Four places caught **any** failure of a lake read and went on with an empty value. None of them read an error's
text; each was written for one harmless case (an older snapshot without a table or a column) and swallowed every
other failure with it. The empty value then read as a fact:

| Place | What a failed read showed |
|---|---|
| `screen.confirmed_facts` | on the page "Criteria not matched", shown to the person who decides: every answer from the records "came from the coded records", also one a person had confirmed from a chart |
| `screen.practitioner_names` | on the lists: the settings' placeholder name as the doctor's name (D-120 took those off the lists for this reason) |
| `coded_values.attach` | nothing: the answers stood without their values and nobody was told why |
| `feas_profile` | on the feasibility page: "No doctor's notes are in the box" |

## Decision

A read that failed is said where its result is shown. The job is not failed for it: each of these is shown beside
answers that were decided without it.

1. **Where an exclusion's answer came from.** A snapshot from before the site facts has no confirmed fact; that is
   asked of the lake (`tb_common.lakeprobe`). Any other failure: the stored document says
   `confirmed_facts: not read`, and an answer from the records has the source `records`, not `coded`. The page
   says "the records (whether a person confirmed them could not be read)", the filter can select it, and a
   sentence above the list says what could not be read.
2. **A doctor's name.** On a failed read every label is `<id> (name not read)`. The settings name still fills a
   name the records do not hold when the records were read (D-120); it does not stand in for records that were
   not read.
3. **The values behind a coded answer.** `attach` returns None, not 0. The answers keep no `coded` (which claims
   nothing; an empty list would say "the run looked and found no record"). The run carries
   `coded_values_read`, the stored document `coded_values: not read`, and the page says so in one sentence.
4. **What the feasibility counts stand on.** Both counts are None and `read` is false. The page says "Note data
   could not be read for this report" (it already said so for the appointments).

A document or a report written before this card has none of the new fields; the pages show it as before.

## What is not changed

- The answers themselves, the lists, the counts. Nothing here decides who is listed or excluded.
- `KeyboardInterrupt` and `SystemExit` pass through all four.
- The candidate page and the lists do not yet say when the coded values were not read; only the page "Criteria
  not matched" does. The run carries the flag for them.

## Test

`tests/unit/test_lake_read_failed_is_said.py`: each place with the lake raising, with the lake answering, and
with the table absent where that is asked; a failure whose text holds the words of a missing table is "not read".
`tests/console/test_lake_unread_pages.py`: the page in three languages, the filter, a run that read everything, a
document from before; the feasibility facts for not read, none and some.

Existing tests changed, each for the changed behaviour: `test_coded_values.py` (a failed read gave 0, now None);
`tests/console/test_excluded_page.py` (its lake stand-in took one argument; the read now uses the lake's own call
shape; two assertions added).
