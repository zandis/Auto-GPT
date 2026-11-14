# D-769 A scoped account is shown only its own studies to run

- **Task:** SEC-SCOPE (found by the adversarial review of NEW-JRN-3, D-767; lane C2, a security defect first in the
  queue)
- **PR:** this branch (`agent/SEC-SCOPE-a-scoped-coordinator-runs-only-their-studies`), from master after train 15
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-104 and D-380 (an SMO or CRO account is scoped to the studies on its contract), D-120 (the request
  page lists this site's studies the account sees), D-540 (a scoped account's refusal tells nothing about other
  studies)

## The problem

The CASE page and the registry's home listed every approved trial, also to an account scoped to some studies (an SMO
coordinator): the names of the site's other studies were shown to someone whose refusals are worded to tell nothing
about them. The request page already listed only the studies the account sees. **Checked**: the run itself was
refused all along (`submit` refuses a ruleset outside the account's scope, 403, audited), so nothing could be run
or read; the defect is the names shown. Confirmed by a test before the change (kept failing output:
`scope-fail.txt`).

## The decision

- `_trial_rulesets(sess)` lists only this site's approved trials the account sees (`settings.studies`,
  `User.sees_study`), as the request page does: the CASE page (and its 422 re-render) and the registry's home.
- A test holds that a scoped coordinator is still refused a run on another study (403, nothing created).

## Reuse check

`User.sees_study`, `settings.studies`, the request page's own rule. No new route, store or permission.

## Dropped (D-311)

No sign-off step.
