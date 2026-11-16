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

- **The regulator clock is for a suspected reaction.** An SAE the investigator answers "not related" (`ae_related`
  0) has no regulator row, unless the sponsor answers related (`ae_sponsor_related` 1: ICH E2A, either one's
  judgment); "unknown" (9) or no answer counts as suspected. The sponsor and the IRB are told of every SAE as
  before.
- **An expected reaction follows the set's own row for it** (`EXPECTED_REGULATOR`, not a party): `jp_gcp_ii` gives an
  expected fatal or life-threatening reaction its 15-day PMDA report; an expected non-grave reaction, and every
  expected reaction under the other sets, needs no regulator report (LIFE-024).
- **`tw_trial_sponsor`**: a sponsor's trial at a Taiwan site: sponsor 24 hours, IRB 7/15 days, no site regulator
  clock (the sponsor reports to TFDA). Named in the three languages.
- **No deadline until the study's set is chosen.** With no set named by the study, the clock has no party and the
  problem is `unconfirmed`, an alert in the three languages; the regulator's name (from the box's `TB_SAE_RULES`, else
  the site's country) is still shown. A box-wide `TB_SAE_RULES` runs no clock of its own: only each study's choice,
  made on its set-up page by its trial office, does (it put a TFDA clock on every sponsor trial). A serious AE with no
  clock is listed with the overdue reports on the home page, the week page and the coordinator's mail as "no deadline
  yet: choose the study's SAE rule set", never left out; it is a no-clock alert (S-16) on the SAE pages. An existing
  case's register trail records its deadlines going to none, as it records every change.
- **The expected row is not a party.** `EXPECTED_REGULATOR` does not show in the rules line; an override that turns
  the regulator off (`TB_SAE_REPORT_DAYS=regulator=0`) turns it off too; the 7 + 8 regulator follow-up is for an
  unexpected reaction, not the expected row; `expected_noreg` is not said when the set keeps a regulator row. A bad
  override is said whether or not a set is chosen.

## The review

One adversarial review: NOT SOUND on the first pass. The sponsor's causality was ignored; studies with no set
chosen lost their overdue reports from the home page and mail with nothing in their place; a box-wide set counted as
chosen (and brought back the sponsor-trial TFDA clock); `expected_noreg` contradicted the expected PMDA row; the
expected row leaked into the rules line and past an override; the regulator follow-up made a "day 23" for an
expected reaction; a bad override was hidden before a set was chosen. All fixed as above and held by tests.

## What the old tests pinned

The SAE tests built their clock from the country's default (`report_rules(tz)`); they now name the set they test
(`tw_trial`, `jp_gcp_ii`), and the page tests choose it on the set-up page, as a coordinator does. The test of the
named sets now holds that nothing chosen gives no clock and the `unconfirmed` alert.

## Reuse check

The rule sets' table and `clock_rules`/`report_clock`; the existing problem and flag paths of the SAE pages; the
set-up page's choice (D-277). No new store, route or permission.

## Dropped (D-311)

No sign-off step. Each trial office confirms its study's set on the set-up page (D-277), as before.
