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
2. **A doctor's name.** On a failed read the settings name is all there is: the label says so,
   `<name> (<id>; name from settings)`, and a doctor with no settings name is `<id> (name not read)`. When the
   records were read, the settings name still fills a name the records do not hold (D-120), unmarked as before.
   A doctor who is not in the settings has no label; the lists show the bare id, as for any doctor without a name.
   The two phrases are English in every language's workbook: the label is built where no language is known.
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

## What follows from it, for an update and a re-run

- **Update the console before or with the orchestrator.** A console from before this card shows the source
  `records` as the raw key `ex.src.records`, with no sentence above the list. Not a false fact, but a raw key on
  a page a person decides on.
- **A re-run of a job whose first run had a failed read** differs from it on a healthy lake (the stored list
  says "not read" in one and not in the other). Expected: the first run's output says what it could not read.
- An older snapshot without the name column: every doctor's label says "name from settings" or "name not read".

## Review

One adversarial review by running (on `db45f309`). Verdict: fix first, for one finding.

| Finding | Confirmed | What was done |
|---|---|---|
| HIGH: the Japanese sentence held a variant the wording rule bans (人の確認); `tests/unit/test_wording.py` was red | by running | reworded (人が確認した) |
| MED: the "list from before" half of a page test never showed that list (two lists stored at one time; the page kept the first) | by running | a box of its own |
| MED: nothing tested that a failed read of the values reaches the run's flag | by a mutation | the step is a function of its own, tested |
| MED: an answer with no source, in a list that says the facts were not read, showed "the coded records" (not reachable from the producer) | by running | it shows "the records"; test |
| MED: a console older than the orchestrator shows the raw key | by running | stated above |
| MED: "name not read" was only for doctors in the settings; the NAV draft's doctor field got the phrase where it had the settings name | by running, by reading | the settings name is kept and marked; the record says who has no label |
| LOW: the PI's weekly sample page has no sentence (its pill does say "the records …"); a re-run differs; three log lines a run | by running | stated; not changed |

Held (the reviewer's runs): the page for lists with one, both or neither flag, the filter and its counts; no
other reader of the stored list reads the source (no export, gate, audit or quality figure); every real lake's
`query` takes the three arguments, and a real in-process screening run reads the facts and names with no error
swallowed; no consumer parses a doctor's label, routing is by id; an answer without `coded` never shows "no coded
record"; only the console reads the feasibility counts; seven mutations each fail a test; the log lines print the
error's type only. The fixes after the review were not reviewed again.
