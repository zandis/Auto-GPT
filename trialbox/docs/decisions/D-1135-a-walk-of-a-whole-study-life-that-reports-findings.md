# D-1135 A walk of a study's whole life, by the role that owns each step, that reports findings and fixes nothing

- **Task:** lane H, card H-20 (the integrator, PR #639, 2026-11-17 08:12 UTC): the whole-life-cycle walk, four
  roles
- **PR:** this branch (`claude/lane-h-20-life-cycle-walk`), from H-10's branch (PR #964)
- **Date:** 2026-11-17
- **Status:** reserved
- **Builds on:** D-1121 (H-10's walk of a new study), D-1062 (steps mode), D-1063 (one sign-in with an acting role),
  D-134 (the lifecycle), D-386 and D-763 (the study's state and its close), D-380, D-441 and D-465 (the opt-out
  register, its worker and the erasure registry)

## Context

H-10's walk ends at the candidate list. Testers on the preview box go further: the weekly page, a patient taken
forward, a withdrawal, the close and an opt-out. Nobody had walked those steps in order on a steps-mode box, by the
roles that own them, in three languages. So nobody knew where a tester would be stopped or have to guess.

## Decision

1. **What the walk covers.** `tests/e2e/test_life_cycle_walk.py` (marked e2e) starts the steps-mode box as H-10's
   walk does (its own `box` fixture). It walks one study per page language (en, zh-TW, ja), each under its own new
   ruleset id (`LIFEWALK`, `LIFEWALKZH`, `LIFEWALKJA`):
   - steps 1 to 11 are H-10's, unchanged (a test holds them equal to H-10's plan);
   - step 12: the coordinator opens the weekly page;
   - step 13: the PI marks Approach;
   - step 14: the coordinator records "reached, visit booked" (the screening number);
   - steps 15 and 16: consent given, enrolled, then a withdrawal (first without a reason, refused, then with one);
   - step 17: the coordinator closes the study;
   - steps 18 and 19: the chart number shown on the patient sheet, then the data steward's opt-out by it;
   - step 20: the patient is gone from the weekly and candidate lists;
   - step 21: the administrator reads the opt-out worker's health check (the erase).

   Each step is done by the role whose matrix row permits it (`OWNER_ROW`, held against
   `libs/tb_common/authz_matrix.yaml` by a fast test). Every new role boundary has at least one refusal: a real
   request with the page's own form token, answered 403 with the refusal page. There are ten refusals, and a test
   holds that each refused role lacks the row.
2. **It reports and does not fix.** The walk changes no product file. Where it must find a thing another way than by
   a documented label (an address typed in, a link found by the start of its name, a value carried over from
   another role's page), the act names a finding and the walk logs it as a guess. Where the product does not do what
   its documents say and the step cannot go on, the walk stops that step with the product's own words (`Stop`, a
   finding that blocks the step). It records the steps that stand on it as not walked, and it never asserts the
   fault as correct. The findings by step (`FINDINGS` in `tests/e2e/life_cycle_walk_plan.py`) and the steps a
   steps-mode box cannot complete are on `docs/handover/life-cycle-walk-findings-2026-11-17.md`, in English only:
   findings for builders, not a testers' page. A fast test keeps its tables equal to the plan.
3. **What it records.** Per step, in a JSON log outside the repository (`TB_WALK_LOG_DIR`, else the box's scratch
   folder):
   - the page reached (path and heading);
   - the clicks from the previous step's page (count and texts);
   - the time, the inputs and the texts a finding quotes;
   - the guesses, the refusals and any stop.

   Chart numbers and whole pseudonyms are written as `{chart}` and `{pid}`. A small summary of the three runs is
   committed in the plan (`SUMMARY`) and shown on the findings page.
4. **The testers' pages are left as they are.** `new-study-walk.{en,zh-TW,ja}.md` stay H-10's. The life-cycle steps
   join them once the findings that slow a tester are settled; until then such a page would send a tester to typed
   addresses.
5. **How it runs.** `make walk-life-cycle`: one Makefile target, on CI's full-tier list, which the card allows. The
   run is the box's seed (about 7 minutes), then about 2 minutes per language on a 4-core container. Its waits are
   page states, never time, and its test ids are the three language codes. CI is not changed here. Like H-10's walk,
   the nightly compose job (`make test-compose`) selects every e2e test in `tests/e2e/` and would collect it once
   merged. The integrator decides whether the nightly's budget takes about 14 more minutes. The fast tests run in
   the unit tier as they are.

## Test

`tests/e2e/test_life_cycle_walk.py` holds:

- the walk in three languages (e2e; every refusal answered 403, every stop a blocking finding of the plan with the
  page's words);
- H-10's steps unchanged;
- each step done by its owner and refused to the others;
- every text the console's own, in zh-TW and ja too;
- the findings well formed and the page equal to them;
- the new ids new to the stub and the box, and never H-10's;
- the logs outside the repository;
- every act the plan sends known to the driver.
