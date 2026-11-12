# D-467 The trial-opportunity feed: monthly rounded aggregates for approved recruiting trials, signed by the site

- **Task:** T-740 (`docs/plan/32-trial-opportunity-feed.md`)
- **PR:** this branch (`claude/project-thread-dq324y`), with the fixes of the privacy review of draft PR #282
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-74 (trial simulation inside COHORT), D-86 (controlled rounding of FEAS counts), D-140
  (ClinicalTrials.gov live, offline or cassette), D-147 and D-441 (the opt-out register)

## Decision

The owner's rule: only aggregates ever leave a site; no patient-level data, no identifiers, no free text from a record.
The site counts in its own lake (`orchestrator.scenarios.opportunity.build_feed`); the exact counts never leave it.
`tb_common.opportunity.build` reduces them to the feed by these rules, and one schema (`validate`) checks every key,
type, range and multiple-of-10 rule before the site signs and again at the hub before a page shows anything.

1. **Approved studies only.** Only studies on the steward's approved list are counted and published. The list is a
   precondition in the library: an empty list publishes nothing, and a study not on it is refused. The steward page
   that edits it is T-742 (`TB_OPPORTUNITY_APPROVED_FILE` until then).
2. **Under the floor is not published.** A study with fewer than 10 patients who may meet its counted criteria has no
   row (no `<10` rows, no 0). The feed says only how many rows were left out: "none", "some" (1 to 9) or that number
   rounded to 10. A study that could not be counted is a row with `null` counts and a fixed reason code
   (`not_compiled`, `no_countable_criteria`, `count_failed`); no message string reaches the feed.
3. **Rounded counts.** Every published count is a multiple of the threshold (10 by default and at least 10 in code;
   a site may only raise it).
4. **Rate from rounded counts.** New patients per month is the rounded yearly count divided by 12 (the rule of FEAS
   `lam_pub`: an exact mean of small counts reveals their sum). Under 10 new patients a year, no rate is published.
5. **Band from rounded inputs.** The 12-month enrolment band is simulated from the rounded counts only, with a seed
   from the site's secret (`TB_OPPORTUNITY_SECRET_FILE`, never in a feed, so the band cannot be replayed), and is
   published rounded to 10. When it is narrower than the rounding, only the middle value is published. Without a
   secret, no band.
6. **Funnel with complementary suppression.** A criterion's drop is published only when the drop and the patients
   left after it are both at least 10. Otherwise that step is withheld and so is one neighbouring step
   (`smallcell.funnel_drops_publishable`). At most three are listed, as "criteria not matched most often". Their
   labels are the criterion's own words only when they stand in the public registry text, else "criterion n".
7. **Monthly publication.** The feed is published once per period, 30 days by default
   (`TB_OPPORTUNITY_PERIOD_DAYS`). The library refuses to sign a period under 28 days. Counts are taken as of the
   period's first day. Within a period the published values do not change (`publish_once` keeps the first signed
   feed of the period); the site may compute more often for itself.
8. **A cap per condition.** At most `TB_OPPORTUNITY_PER_CONDITION` studies per condition per feed (default 20; it bounds
   how many questions one feed can ask of the lake). The cap is in the feed and checked by the schema.
9. **Opted-out patients are not counted.** `build_feed` reads the opt-out register once (`tb_common.optout.opted_out`,
   as of the job's receipt, the way SCREEN does) and FEAS's lake counts leave those pseudonyms out.
10. **Signature, register, freshness.** The site signs the canonical JSON with Ed25519. The key's fingerprint
    (`key_sha256`) and the period are inside the signed bytes. The hub reads a site key register (site id to key
    fingerprint and registered name). A feed is shown as "signed by site" only when its key is the one registered
    for its `site_id` and its `site_label` is the registered name. A feed past its period is shown as out of date;
    anything else is "not verified". The dashboard refuses an unverified feed unless `--allow-unverified` is given,
    and that flag is refused outside DEV and TEST; the page then says so in a banner. The full hub store and accounts
    are T-743's.
11. **No smart contracts.** Provenance is the signed feed plus the sponsor's own re-run; payment is by contract.

## What a recipient can and cannot infer

A recipient learns, per approved study and per month: whether at least 10 of the site's patients may meet the
counted criteria, and if so that number to the nearest 10; new patients per month to the precision of a yearly count
rounded to 10; an enrolment band that is a function of those rounded numbers alone; and up to three criterion drops
of at least 10, rounded to 10. A study missing from the feed has fewer than 10, or is not on the approved list; the
recipient cannot tell which. The recipient cannot learn an exact count, a count under 10, a drop under 10 (nor its
neighbour, so not by subtraction), the effect of one patient on a given day (values change at most once a month), or
anything about an opted-out patient. Nothing in the feed names, dates or describes a patient. The residual: across
months, a rounded value that changes tells the recipient that the count crossed a rounding boundary in that month;
differencing two overlapping studies gives a difference of rounded values (a multiple of 10), not a small cell.
