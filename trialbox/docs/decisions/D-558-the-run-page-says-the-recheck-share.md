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
in English, Japanese and Traditional Chinese. It follows the run's own cases:

- **Screened again on this run: *n* of *scope*.** When nobody was carried over: all of them were.
- **The share**, when the box has a night budget: the places kept on this run, and that up to *percent* % of the
  study's night budget is kept for them. The places are the smaller of that share of what was left and the
  patients waiting, so the share is said as a limit, never as what the places amount to (8 places kept of a
  budget of 2000 is not 25 % of anything). When the share is set to 0: no share is kept by setting, and they are
  screened again only when the other patients leave room. With no night budget, nothing is said of a share.
- **Carried over to the next run: *n***, when any were, and then either how many weekly runs it takes at this
  share to screen them all again (when the run gave a number above 1), or that the budget left for this run was
  too small to keep a place (when the run could give none). The run writes "1 run" whenever nobody was carried,
  whatever the share, so that figure is not said as a property of the share; and it can write "1 run" beside
  patients carried over (it counts those waiting before the re-checks): the page then says no number.

**Who sees it:** the accounts that read the study's list, by the same rule as the rows of the screening card
(`Helpers.reads`, or a break-glass grant for the job). An administrator without a grant and a viewer see the
page without the block.

**No small-cell suppression.** The figures are patient counts. The mail suppresses small ones because it is an
aggregate output that leaves the box; this block is shown only to accounts that read the study's list row by
row (the integrator's ruling of 2026-11-13). The list holds the patients to approach, not the ones not matched,
so these counts are more than the list says; they are of the same study, to the same accounts.

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

## What the adversarial review changed

One review by a fresh reviewer, who rendered each case of the run through the real page. Verdict: fix first.

- **The first sentences were untrue of what the run computes** in its commonest case and three others: the share
  read as what the places amount to; "a full pass takes 1 run at this share" appeared whenever everybody was
  reached, even at a share of 0; a share of 0 was said as "no place could be kept"; and "1 run" could stand
  beside patients carried over. The block is as above now, one test per case, each with figures the run can
  write.
- The block waits for the run to end (the event is written before the reporting step).
- The tests now hold the carried line, an investigator who is not ticked for screening, and a running job; a
  viewer was a vacuous case (a viewer cannot open the page) and is gone.
- Wording: the Japanese line uses the page's own words (対象, この実行); the Traditional Chinese counts places
  with 個.
- **Checked and sound:** the gate is the rows' own; no API route returns the figures; every stand-in of the
  console's backend has the reader; the reader's first filter holds for how the audit is written.
- **Follow-up against D-646, sent to the integrator:** the run's number of runs uses the nominal share and a
  count taken before the re-checks, so it can say 1 with patients carried over.
- Left: the reader makes a second pass over the audit files on a view of such a page (after the gate; it skips
  every line that is not the event without parsing it).

## Reuse check

The job page's own card pattern, `Helpers.reads` and the console's catalogue; the reader is a few lines beside
`read_audit`. Nothing is added.

## Dropped (D-311)

No sign-off step.
