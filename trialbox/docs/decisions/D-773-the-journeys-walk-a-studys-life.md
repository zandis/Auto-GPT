# D-773 The journeys walk a study's life

- **Task:** NEW-JRN-20 (the deep review of 2026-11-12, JRN-021; plan 33's lane C line)
- **PR:** this branch (`agent/NEW-JRN-20-the-journeys-walk-a-studys-life`), from master after train 15
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** T-315a (D-448: the journeys as the PQ script), NEW-JRN-1 (D-540: a new study's first approval in
  the journeys), D-719 (a protected account is opened by code after a second person confirms)

## The problem

The product's own PQ journeys (`tests/e2e/journeys/journeys.yaml`) passed while a site could not run a study in
them: they did not walk a participant's visits, a serious adverse event and its report clock, a deviation, EDC sign
and send, the monitor's visit record, a study's close, or an account made in the console and its holder's first
sign-in (JRN-021). The walk before the change could not hold them: each new step failed for want of its walk. That
proves the gap in the script, not a defect in the product.

## The decision

Eight steps, each done through the console's pages as the person would and checked against what the screen shows;
none seeds through a store:

| Step | Who | What it walks |
| --- | --- | --- |
| J-ADM-06 | administrator | adds a coordinator account on "Users": it waits for the steward, no code or password is shown |
| J-STW-06 | steward | confirms the request (the code is shown once, to the steward); the new coordinator redeems it at "First sign-in", sets up the authenticator and reaches "My work"; the audit names the confirming person |
| J-CRC-09 | coordinator | adds the built-in forms, sets the visit schedule, records Week 1 done in its window: the participant is on study with Week 4 next |
| J-CRC-10 | coordinator | chooses Taiwan's trial rules and records a serious AE: the SAE banner for the coordinator and the PI, the sponsor report due one day after awareness |
| J-CRC-11 | coordinator | records a deviation on the participant |
| J-CRC-12 | coordinator | confirms GOUT-COH's drafted values, signs (refused without the authenticator code), sends: REDCap holds the confirmed values, no read-back difference |
| J-MON-04 | monitor | records the monitoring visit MV-01 with the participant and a finding |
| J-PI-09 | investigator | closes GZQO with a reason: the screening log says "Closed", its study sheet carries the reason |

- **The re-run list after a long break names steps, not whole journeys,** where a journey holds a step done once
  in a study's life: the eight above, and NEW-JRN-1's new study (J-ADM-05, J-STW-05, J-PI-08, J-CRC-08), which the
  list re-ran before. `test_journeys.py` refuses a re-run of such a step.

Seven new topics name what they prove (`new_account`, `visits`, `sae`, `deviation`, `edc_sign_send`,
`monitor_visit`, `study_close`); the file's own tests require each to be covered. The steps come after the existing
ones in the walk, so each journey keeps its order.

## Adversarial review

NOT SOUND on the first pass:
1. The re-run list would have repeated the irreversible steps (a close, an account, an SAE, a send).
2. Some checks would pass with the feature broken: the SAE rules and the built-in forms were taken as saved on a
   200; "the code is shown once" was checked on a page that never shows it; the monitor visit's participant was
   found in the form below the table.
3. The due time was checked by its date only, with an awareness time two hours after the box's clock.
4. The close's exported sheet was read from the store, not downloaded.
5. The EDC values were confirmed by ids from the backend, not by the page's own Confirm buttons.
6. Some expect texts claimed more than the code checked.

All are fixed: each check reads the screen or the downloaded file, cell by cell where it matters; the record says
what remains.

## Remains

- The PI starting a run from the request page (JRN-003, #620), the privacy office's report by chart number (JRN-006,
  #631) and the monitor's link from the reports page (JRN-008, #634) get their steps when those cards are on master.
- Backup and update are lane D's (their own drills; not a console journey).
- The SAE journey stops at the clock: marking the reports sent and the IRB and TFDA due times are not walked.
- Closing walks a study with nothing open; the refusal to close with participants on study or an open SAE is
  LIFE-006 (#605), whose step follows it onto master (JRN-004).
- A test that no journey writes the database directly is not added: J-STW-03 still writes the nightly load's
  conflict row by SQL, as it did (the journey site serves the legacy lake).
- The new coordinator signs in; giving them a study is J-ADM-05's scope change, not repeated here.

## Held by

`tests/e2e/journeys/test_journeys.py` (the walk, and the file's structure and coverage tests).

## Dropped (D-311)

No sign-off step.
