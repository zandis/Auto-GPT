# D-1480 The EDC stops for a withdrawal without data use, a PRODUCTION box sends only for an open study, and the delegation log decides the PI's EDC rights (M7)

- **Task:** module M7 (EDC door), wave 2; findings V15-06 and V2-05; R1-E5 and R1-E6
  · **Date:** 2026-11-26
- **Status:** reserved for M7 (the integrator flips the row when merged)
- **Builds on:** D-162 (the EDC gates and the opt-out register), D-281 (signed values only), D-380 (no PI until the
  log names one), D-484 (the orchestrator reads the delegation log itself), D-1072 (rc1 refusals on a PRODUCTION box)

## Context

Three rules were missing from the EDC service. A withdrawal form whose "data collected so far may be used" was No
did not stop any EDC step: only the opt-out register was read (V15-06). The orchestrator's EDC router asked a role
check that reads an investigator as on no delegation log, so the study's PI was refused the copy sheet, the ODM
export and the send, which the matrix gives them (V2-05). And a PRODUCTION box sent signed values to REDCap for any
study, open or not: rc1's RC-RC1 covered only the data core's push of screening values.

## Decision

1. **Withdrawal.** A subject whose withdrawal form says the data may not be used (`wd_data_use` "0", on any event,
   read from the data core at every call) is refused at every EDC step: draft, decide, sign, preview, erase, ODM
   import, the copy-assist sheet and its ticks (`edc.withdrawn`, audited). A send or export for the study leaves
   their values out and records each as `withdrawn`; one that would carry only their values is refused.
2. **PRODUCTION send.** A box in any environment but DEV, TEST and VALIDATION (unset is PRODUCTION) sends to the EDC
   only for a study the console recorded `open`. A study not recorded open, or whose state cannot be read, is
   refused with RC-RC1, `missing: study_open`, audited. Only values a named person confirmed and signed are ever
   sendable (unchanged).
3. **The PI's EDC rights.** Where the matrix leaves a role's `edc.*` row to the delegation log (the investigator),
   the EDC router reads the log and asks the matrix with the tasks the log gives; the PI the log names holds every
   task. A log that cannot be read refuses.
4. Each value sent and read back keeps REDCap's own log line of the write (time, user, action), shown on the trail.

## Consequences

- A participant's withdrawal of data use is honoured by the EDC service without a person remembering to stop it.
- A PRODUCTION study must be opened on its state page before anything is sent to its EDC.
- Tests: `tests/unit/test_v15_withdrawal_data_use.py`, `tests/unit/test_m7_edc_door.py`,
  `tests/unit/test_matrix_role_walk_orchestrator.py` (V2-05), `tests/console/test_matrix_role_walk.py`, and
  `tests/e2e/test_edc_real_doors.py` against a REDCap test instance.
