# D-713 The patient's page and the weekly sample say when the run could not read the values behind its coded answers

- **Task:** NEW-CAND-1 (the handover of lane A2's D-652, placed by the integrator on 2026-11-13)
- **PR:** this branch (`agent/NEW-CAND-1-coded-values-not-read-is-said`), cut from train 14 (it needs #540)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-652 (a failed read of the lake is said: the run records `coded_values: not read`), T-514 /
  D-362 (the coded records' value, unit, date and code beside a coded answer), D-446 (the weekly sample)

## The problem

When a screening run cannot read the values behind its coded answers, the answers stand and are shown without
their values. D-652 made the run record that and the page "Criteria not matched" say it. Two other places show a
run's coded answers one by one and did not: the criteria table of a patient (the PI's patient page and the team's
candidate page share it) and the PI's weekly sample. A reader there saw a coded answer with no value and nothing
to say why: a run that could not read looked like a record with nothing in it.

## The decision

- **The criteria table of a patient** has the sentence above it when that run said so: "For this run the values
  behind the coded answers could not be read. The answers stand." (the words D-652 wrote, `ex.unread.values`, in
  three languages). The page reads the flag where the run keeps it: the run's stored "not matched" list.
- **The weekly sample** has the same sentence when a run its patients were drawn from said so.
- A run that read the values, a list written before the field existed, and a run with no stored list show
  nothing, as before.

## What it does not do

- **While an after-ingest or weekly run (`MICROBATCH`) is the study's latest run, nothing is said.** Such a run
  writes a candidate list and no "not matched" list and records no flag; its list mixes rows carried from the
  earlier screening with rows it read again. The patient's page reads the latest run, so the sentence lasts
  until the next such run, though carried rows still have no values; and a run of that kind whose own read
  failed is not said at all. Saying the earlier run's flag instead would be wrong for the rows read again with
  their values. The remedy is in the orchestrator (that run records the flag, per run or per row): not this
  lane's file, sent to the integrator. The page "Criteria not matched" and the weekly sample read the screening
  run's own list and still say it. Pinned by test.
- **The weekly list's side panel** shows no coded value (only the verdict and its source), so it has no
  sentence.
- The flag is the run's, not one answer's: the sentence stands above the table and is not repeated per row.
- A list from before D-652 cannot say whether its values were read; nothing is said for it (by test). That is
  "not known", shown as silence: the run did not record it, and no page can tell.
- The team's candidate page gets the sentence through the shared table and context; it has no test of its own
  here (the reviewer ran it).
- No new words: the sentence is D-652's.

## What the adversarial review changed

One review by a fresh reviewer, with variant tests in a detached copy. Verdict: fix first, one finding.

- **The limit above was not named**: with a `MICROBATCH` as the latest run the sentence is missing. It is named
  and pinned by a test now, and the remedy is sent on; it is not closed here.
- **Every view of the weekly list's side panel read and parsed the run's whole stored list** for a flag that
  panel does not use (it shares the patient's context). The answer of the last run asked is kept; a finished
  run's list does not change. By test (three views, one read).
- The sentence had a class with no style of its own; it uses the pages' warning style.
- Ran and sound: the team's candidate page shows it (with a purpose given) and nothing for a run that read;
  every render of the table goes through the same context; it is never shown wrongly, because a screening run's
  listed and excluded rows share the one flag; held, empty and a gone run on the sample show nothing.
- Said, not changed: the `/api/v1` twins of the two pages do not carry the flag; a store that raises an
  unexpected error fails the page, as the candidate list's own read does.

## Reuse check

`ex.unread.values` (D-652), the console's own loader of a run's stored document (`home.load`), the sample's
`run_doc`. One small function is added (`values_unread`), with the last run's answer kept.

## Dropped (D-311)

No sign-off step.
