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

- **The CASE page listed every approved trial**, also to an account scoped to some studies (an SMO coordinator):
  the names of the site's other studies were shown to someone whose refusals are worded to tell nothing about them.
  The request page and the registry's home already listed only the studies the account sees.
- **A job-id command crossed the scope (found by this card's review).** `submit` checked the scope only when the
  request named a study; STATUS, CANCEL and RELEASE name a job id and no study, so a scoped account could ask
  `STATUS <job of another study>` and be mailed that job's record (type, study, options, file names), and ask CANCEL
  (refused later by the orchestrator unless the account reviews). It needs the job's id.
- A refused request had already stored its uploads; a typed request for a study that is not this site's
  (`TB_CONSOLE_STUDIES`) was accepted though no page offers it.

Confirmed by tests before the change (kept failing output: `scope-fail.txt`; the job-id case by the review's probe).

## The decision

- `_trial_rulesets(sess)` lists only this site's approved trials the account sees (`settings.studies`,
  `User.sees_study`), as the request page does: the CASE page and its 422 re-render. The registry's home keeps its own
  list (scoped already).
- `submit` checks the scope of the job a job-id command names (`target_study`): a job of a study the account does
  not see is refused (403, `request.scope`, audited), and for a scoped account so is a job of no study or one the box
  does not know (the answer is the same whether it exists or not, D-540). A study not in `TB_CONSOLE_STUDIES` is
  refused too.
- The scope is checked before any upload is stored.

## The review

One adversarial review: NOT SOUND on the first pass (the job-id commands; the registry's home was misdescribed and
its list was changed for unscoped accounts with `TB_CONSOLE_STUDIES` set; uploads stored before the refusal; the
site's study list applied on listings only). All fixed as above and held by tests: STATUS and CANCEL of another
study's job refused to a scoped coordinator and allowed to a hospital coordinator; the registry's home unchanged for
an unscoped coordinator.

## Reuse check

`User.sees_study`, `settings.studies`, the request page's own rule. No new route, store or permission.

## Dropped (D-311)

No sign-off step.
