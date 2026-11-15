# D-765 Retention holds a running study's files

- **Task:** NEW-LIFE-9 (plan v7.3, wave 4, lane C: "retention hold by study state", LIFE-009 and T-305c re-ordered:
  before go-live, without waiting for T-305b; the deep review of 2026-11-12, LIFE-009, old LIFE-027;
  `37-remaining-work-split.md`, lane C2's queue)
- **PR:** this branch (`agent/NEW-LIFE-9-retention-holds-a-running-study`), from master after train 15
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-78 and D-492 (RETENTION, the last step of the night), D-458 (an open study's micro-batch inputs
  are kept), D-386 (the study's state)

## The problem

RETENTION deleted attachments after 90 days and outputs after 365 by object age only, whatever the study's state.
The candidate list a mark was made on, the evidence shown, the review workbook and the protocol file the criteria
were compiled from were gone three to twelve months later while the study still ran; only their hashes stayed. GCP
keeps the study file for the study's life and its retention period after. **Confirmed by a test** before the change
(kept failing output: `life9-fail.txt`).

## The decision

- **A study's files are held while the study is not `closed`.** An expired object under `attachments/<job>/` or
  `outputs/<job>/` whose job's ruleset is a study the console has a recorded state for (`site.study_state`, read by
  `scheduler.recorded_study_state`) is kept while that state is anything but `closed`.
- **"No recorded state" is not a running study.** A ruleset the console never set up as a study (a feasibility of a
  trial the site declined, a cohort, a case, the cohort merge) keeps the configured ages: the hold does not switch
  retention off for every job with a ruleset.
- **A study whose state cannot be read is held**: keep rather than delete, as D-458 does.
- **After the close, the configured ages apply** (`retention.attachments_days`, `retention.outputs_days`), counted from
  the object's own age. A per-study retention period after the close (a setting the trial office gives) is the rest of
  T-305c and stays open.
- **What has no study keeps its ages:** a job with no ruleset (a pilot request), a job this box no longer knows, and
  the public ClinicalTrials.gov cache (`ctgov/`).
- **A running study's pool and marks are kept** by the inactive-pool pruning too (`prune_inactive`), also while its
  ruleset's approval has lapsed.
- The night's retention report counts what was held (`held_for_running_studies`), beside D-458's
  `kept_for_open_studies`.

## The review

One adversarial review: NOT SOUND on the first pass. "No state row" read as open, so every job with a ruleset that
was never a study (patient-level feasibility outputs included) was held for ever; the tests stood in for the state
read and missed it; a paused study's pool could be pruned by its lapsed approval. Fixed as above and held by tests on
the test's own trial database (the console's real state table). Left as it is: a held object is looked at again each
night (one job read per held job, one state read per ruleset): linear, tolerable at one site. Lake snapshots go by
their own rule (36 month-ends, the lake's holds API); that is not this card.

## Reuse check

`scheduler.recorded_study_state` (the read under `scheduler.study_state`, which the timer and D-458 use and which
reads "nothing recorded" as open), the job record's `ruleset`, the existing report. One filter in `retention.run`, one read per job and study.

## Remains

The per-study retention period after the close (T-305c's second half).

## Dropped (D-311)

No sign-off step.
