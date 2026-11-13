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

- **The weekly list's side panel** shows no coded value (only the verdict and its source), so it has no
  sentence.
- The flag is the run's, not one answer's: the sentence stands above the table and is not repeated per row.
- A list from before D-652 cannot say whether its values were read; nothing is said for it (by test). That is
  "not known", shown as silence: the run did not record it, and no page can tell.
- The team's candidate page gets the sentence through the shared table and context; it has no test of its own
  here (the patient page's test covers the shared part).
- No new words: the sentence is D-652's.

## Review

See "What the adversarial review changed" when the review is in.

## Reuse check

`ex.unread.values` (D-652), the console's own loader of a run's stored document (`home.load`), the sample's
`run_doc`. One small function is added (`values_unread`).

## Dropped (D-311)

No sign-off step.
