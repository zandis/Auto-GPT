# D-558 The page of a weekly screening run says how far it got with the patients not matched before

- **Task:** NEW-RUN-1 (D-646 left the run page to this lane; the integrator's word of 2026-11-13)
- **PR:** this branch (`agent/NEW-RUN-1-excluded-share-on-the-run-page`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** D-646 (a share of a study's night allowance is kept for the patients whose criteria were not
  matched before), D-99 (the screening card of a job's page), D-273 / D-280 (who sees a run's rows)

## The problem

D-646's weekly run writes four figures into its `microbatch.budget` event: how many of those patients are in
scope, the share of the night kept for them, how many places were kept on this run, and how many weekly runs a
full pass takes at that share. The run's mail says them in English prose, with small counts suppressed because
the mail is an aggregate output. The console's page of the run said none of them: its audit table shows only a
fixed list of an event's keys, and these are not among them.

## The decision

The page of a finished weekly screening run (`/pilot/jobs/{job_id}`) carries a block above the screening card,
in English, Japanese and Traditional Chinese:

- screened again on this run: *n* of *scope* in scope;
- places kept for them: *kept* (*percent* % of the night's allowance);
- at this share, a full pass takes *runs* weekly runs, or, when no place could be kept and some were not reached,
  that no number of runs is sure to reach them all;
- carried over to the next run: *n*, when any were.

**Who sees it:** the accounts that read the study's list, by the same rule as the rows of the screening card
(`Helpers.reads`, or a break-glass grant for the job). An administrator without a grant and a viewer see the
page without the block.

**No small-cell suppression.** The figures are patient counts. The mail suppresses small ones because it is an
aggregate output that leaves the box; this block is shown only to accounts that see the list itself, row by row,
so a count tells them nothing the list does not (the integrator's ruling of 2026-11-13).

**The figures do not join the audit table.** The table's fixed list of keys is what every reader of a job's page
sees; adding patient counts to it would show them to the accounts the block is kept from. The page asks for the
figures through a reader of their own (`console.backend.read_recheck_share`).

**Nothing is shown** for a run after an ingest (it keeps no share), a run that wrote no such event (an older
run), or a run with none of those patients in scope.

**The words** are the page's own ("criteria not matched", 基準に合致しない, 未符合條件): the event's field names
(`excluded_...`) are not shown, and the forbidden-word check holds for the block in each language.

## What it does not do

- It shows the excluded-share figures and "screened again / in scope", not the rest of the night budget
  (re-checks, new patients, versions): those are in the run's mail.
- It does not change the run or its event.

## Reuse check

The job page's own card pattern, `Helpers.reads` and the console's catalogue; the reader is a few lines beside
`read_audit`. Nothing is added.

## Dropped (D-311)

No sign-off step.
