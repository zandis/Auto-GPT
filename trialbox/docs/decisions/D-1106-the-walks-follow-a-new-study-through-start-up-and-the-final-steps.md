# D-1106 The walks follow a new study through start-up and confirm its final steps (H-30)

- **Task:** lane H, card H-30 (the integrator, 2026-11-17 13:44 and 13:52 UTC): H-10's and H-20's walks follow
  WALK-1 (D-1153)
- **PR:** this branch (`claude/lane-h-30-walks-follow-walk-1`), stacked on lane C2's `agent/WALK-1-final-steps`
- **Date:** 2026-11-17
- **Status:** reserved
- **Builds on:** D-1121 (H-10's walk of a new study), D-1135 (H-20's walk of a study's life and its findings page),
  D-1153 (a new study starts in start-up; a final step is named before it is made), D-386, D-415, D-178, D-763, D-779

## Context

WALK-1 (D-1153) records a new study in start-up when its protocol is sent through the console. It opens only through
the move to open, which runs D-415's check of the type for SAE reporting, and a list job of a study that is not open
fails at its first check (D-386). Withdraw and Screen fail with a reason, and a close, now ask once on a confirmation
sheet. Both walks ran SCREEN on a new study, and withdrew and closed in one click, so on WALK-1's branch both stop.

## Decision

1. **The two steps before SCREEN are folded into steps 9 and 10, by the role that owns them.** Step 9 (the
   coordinator, matrix rows `study.setup` and `study.state`): after who to screen, the study's state page shows it in
   start-up, Open is refused with `sstate.sae_type`, and set-up's SAE reporting rules take the type (the steps-mode
   box's site is in Taiwan: `tw_trial`). Step 10 (the coordinator, `study.state`): SCREEN fails with the job page's
   words (the catalogue's `job.error`, then the orchestrator's message, read from `require_open`, never typed), the
   coordinator opens the study on its state page, and SCREEN runs. The refusals are real requests with the page's
   form token, answered 403: the investigator and the steward may not save the SAE type, the steward and the
   administrator may not open the study. The steps keep their numbers: the life-cycle walk's steps continue H-10's
   (D-1135, a test holds it), and renumbering them would move every life-cycle step and finding.
2. **Steps 16 and 17 confirm on the sheet.** Without a reason, Withdraw and Change state to Closed are refused before
   any sheet; the Reason labels say they are required. With one, the walk asserts the sheet's words (the step, the
   participant and the reason, and that it is final; for the close, that it is final and the day the files are kept
   until), clicks Yes (`confirm-yes`), and checks that the day kept until is the close's own site day plus the period.
3. **A finding the walk no longer sees leaves the table and keeps its id.** It moves to `FIXED` in
   `tests/e2e/life_cycle_walk_plan.py` with the decision that changed the product and what the walk now asserts; the
   findings page lists it under "The findings the walk no longer sees". Ids are not used again: the findings and the
   fixed ones together still run F-01 to F-nn with no gap (the fast test that held the ids consecutive now holds both
   lists). A test holds each fixed finding to the acts that assert it. F-11, F-14, F-15 and F-16 leave so (D-1153);
   F-20, which H-25 settled (D-1124), is listed with them.
   What the walk saw on the new steps is new (F-22 is H-25's): F-23 (the reason SCREEN fails is the orchestrator's
   English on every page, the state by its code), F-24 (no link from the failed job to the page that opens the
   study), F-25 (the refusal's "type for serious adverse event reporting" has no field of that name on set-up).
4. **The testers' pages** `docs/handover/new-study-walk.{en,zh-TW,ja}.md` carry the new acts in their step tables
   (written by the plan) and a line in each language on start-up before the steps.

## Consequences

- Both walks pass only on a product with D-1153. They are stacked on its branch and go to master with it or after it.
- The SCREEN refusal's own words are not in the console's catalogue: the walk asserts them as the product shows them
  and reports them (F-23), it does not assert them as correct.
- Lane H's H-25 (D-1124) changed steps 21 and 22, F-20, F-21 and F-22 on master; this card takes them as they are.

## Held by

`tests/e2e/test_new_study_walk.py` (the owner rows of steps 9 and 10, the SAE type the box offers, SCREEN's words) and
`tests/e2e/test_life_cycle_walk.py` (ids with the fixed findings, each fixed finding asserted by its step, the page
equal to the plan); the walks themselves, `make walk-new-study` and `make walk-life-cycle`.
