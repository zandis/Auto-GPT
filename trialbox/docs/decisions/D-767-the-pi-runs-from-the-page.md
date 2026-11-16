# D-767 The PI starts a request from the page

- **Task:** NEW-JRN-3 (the deep review of 2026-11-12, JRN-003, a T-512 follow-up; `37-remaining-work-split.md`, lane
  C2's queue)
- **PR:** this branch (`agent/NEW-JRN-3-the-pi-runs-from-the-page`), from master after train 15
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** T-512 (D-349: the PI may start FEAS, SCREEN and CASE on their own study, the `command.*` rows),
  D-120 (the request page lists this site's studies the account sees)

## The problem

The PI had the right to start FEAS, SCREEN and CASE (T-512) and no working control: "New request" said "You are
signed in as a viewer … a coordinator or administrator starts requests" with no form, and the CASE page showed the
same warning and a disabled button. Only a hand-made POST ran the job. The templates asked `user.can_request` (the
coordinator's row), not the account's run rights. **Confirmed by a test** before the change (kept failing output:
`jrn3-fail.txt`).

## The decision

- **The request page shows a form when the account may start it on a study it sees.** The FEAS form lists the
  trials the account may run FEAS on, the SCREEN form the trials and cohorts it may run SCREEN on
  (`Helpers.may_run`: the `command.*` row with the account's standing in the study); an account that prepares requests
  (`can_request`) sees every study it sees, as before. With nothing to start the page keeps its reading card.
- **The CASE page enables its button by the same rule** and lists only the trials the account may ask a CASE
  question of.
- **The free-text request stays the coordinator's**: it proposes any command, so it shows only with `can_request`.
- The POST routes already checked the right per study (`_need_role` with `may_run`, and the orchestrator checks the
  role again); nothing about who may run changes.

## The review

One adversarial review: SOUND. What the page lists and what the POST accepts are one function (`may_run`), so the
page never offers more than the server allows. One low regression fixed: a coordinator on a box with no approved
trial saw the viewer warning on the CASE page (the button follows `can_request` for them, as before). Found and left
for its own card, not introduced here: a coordinator scoped to studies (SMO) is offered, and may post, FEAS, SCREEN
and CASE for studies outside their scope (`_trial_rulesets` and `may_run` do not ask `sees_study` for that role).

## Reuse check

`Helpers.may_run` (the one rule of T-512), the request and CASE pages, their POST checks. No new route or permission.

## Dropped (D-311)

No sign-off step.
