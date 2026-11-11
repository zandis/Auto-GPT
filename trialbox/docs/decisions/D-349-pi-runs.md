# D-349 The PI starts runs on the PI's own study

- **Task:** T-512 (wave P of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.4)
- **PR:** this branch (`agent/T-512-pi-runs`)
- **Date:** 2026-11-10
- **Status:** accepted (the owner's answer to Q-04, `docs/plan/28-master-plan-v6.md` §10.4)
- **Closes:** FIT-003, FIT-U01 (`docs/reviews/2026-11-10-deep-review/01-fit-to-owner-intent.md`)

## Context

Only coordinators and administrators could start a run. The PI could approve the criteria and nothing else, so a
site where the PI works alone could not screen or refresh feasibility (FIT-003). The owner answered Q-04: the PI may
start feasibility, screening and case runs on the PI's own studies; a separate tick for sub-investigators; daily
limits unchanged. The patient lists did not say how old their data was (FIT-U01).

## Decision

1. **One table.** `tb_common.authz.INVESTIGATOR_RUNS` holds the rule: row `pi` (the study's logged PI, or any
   investigator of the study before its delegation log names a PI) and row `run` (a sub-investigator the PI ticked
   for the new study task `run`). Both rows are FEAS, SCREEN and CASE. A different answer is a change to this table;
   two empty rows give back the old rule.
2. **One function.** `tb_common.authz.can_request(role, command, is_pi=, tasks=)` decides for every role. The
   console asks it through `Helpers.may_run` with the account's standing in the study (the delegation log, D-147);
   the request form, the case form and the feasibility refresh use it.
3. **The orchestrator.** Its job table (`ROLE_COMMANDS`) gives the investigator role the union of both rows: the
   most the role may start anywhere. The delegation log stays in the console.
4. **Limits.** The daily per-sender limits (`daily_limit`) apply to the investigator as to any requester.
5. **Data as of.** The week list, the candidates list, the patient page and the candidate page show the day of the
   data (the run's snapshot). The line turns amber when the data is more than two days old.

## Consequences

- A sub-investigator's ticks now include "Start runs". "See candidates" still only shows candidates.
- The orchestrator does not yet check the signed study scope on `POST /jobs`; the console checks the study. A
  later card (T-102a, or fix group D-280) may add it.
