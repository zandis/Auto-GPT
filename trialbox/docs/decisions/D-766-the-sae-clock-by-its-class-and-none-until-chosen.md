# D-766 The SAE clock by the event's class, and none until the study's set is chosen

- **Task:** NEW-LIFE-8 (plan v7.3, wave 4, lane C: "the SAE clock is off until the study's rule set is confirmed";
  the deep review of 2026-11-12, LIFE-008; `37-remaining-work-split.md`, lane C2's queue)
- **PR:** this branch (`agent/NEW-LIFE-8-the-sae-clock-by-its-class`), from master after train 15
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-277 (named SAE rule sets per study, the regulator from the set's country, CR-009), LIFE-024 (an
  expected AE needs no regulator report), D-415 (a study that reports SAEs opens only with its set chosen)

## The problem

Three rule sets showed a wrong or noisy regulator clock, and an unchosen set ran a clock nobody confirmed:

- (a) In a 医師主導治験 (`jp_gcp_ii`) a known (expected) death or life-threatening reaction still has a 15-day PMDA
  report; the box showed no regulator row.
- (b) In a sponsor's trial at a Taiwan site the TFDA report is the sponsor's; `tw_trial` showed the site a TFDA
  clock that went overdue for ever, which teaches staff to ignore red.
- (c) `ae_related` was never read: an unrelated SAE ran the regulator clock.
- A study with no set chosen ran the country's strictest set with a note (`default_rules`).

**Confirmed by tests** before the change (kept failing output: `life8-fail.txt`).

## The decision

- **The regulator clock is for a suspected reaction.** An SAE answered "not related" (`ae_related` 0) has no
  regulator row; "unknown" (9) or no answer counts as suspected. The sponsor and the IRB are told of every SAE as
  before.
- **An expected reaction follows the set's own row for it** (`EXPECTED_REGULATOR`, not a party): `jp_gcp_ii` gives an
  expected fatal or life-threatening reaction its 15-day PMDA report; an expected non-grave reaction, and every
  expected reaction under the other sets, needs no regulator report (LIFE-024).
- **`tw_trial_sponsor`**: a sponsor's trial at a Taiwan site: sponsor 24 hours, IRB 7/15 days, no site regulator
  clock (the sponsor reports to TFDA). Named in the three languages.
- **No deadline until the study's set is chosen.** With no set named (by the study, or by the box's `TB_SAE_RULES`)
  the clock has no party and the problem is `unconfirmed`, an alert in the three languages ("no deadline is shown
  until it does"); the regulator's name of the country is still shown. A serious AE under it is a no-clock alert
  (S-16) and keeps a study from closing (D-763).

## What the old tests pinned

The SAE tests built their clock from the country's default (`report_rules(tz)`); they now name the set they test
(`tw_trial`, `jp_gcp_ii`), and the page tests choose it on the set-up page, as a coordinator does. The test of the
named sets now holds that nothing chosen gives no clock and the `unconfirmed` alert.

## Reuse check

The rule sets' table and `clock_rules`/`report_clock`; the existing problem and flag paths of the SAE pages; the
set-up page's choice (D-277). No new store, route or permission.

## Dropped (D-311)

No sign-off step. Each trial office confirms its study's set on the set-up page (D-277), as before.
