# D-1003 the nightly public-e2e run opens the studies it creates, and counts missing birth dates as the ingest does

- **Task:** plan 10's 9i-2 (the nightlies green, lane D), the `public-e2e` red of the nightly e2e run of 2026-11-18
- **PR:** this branch (`agent/PUBLIC-E2E-opens-the-new-studies`)
- **Date:** 2026-11-18
- **Status:** accepted
- **Builds on:** D-1153 (WALK-1: a new study starts in start-up), D-386 (lists run only for an open study), D-560
  (ENG-002: the public-data site), lane G's B1 (a stated age gives a birth date)

## Context

Run 44379720072 (job 135068320597) crashed at stage 2, `_done(box, "SCREEN", TRIAL)[0]` raising an IndexError. Both
SCREEN requests answered 303, but each job failed at its `ruleset` step: "Study PUB-ONC is startup: lists run only for
an open study".

WALK-1 (D-1153, train 82, PR #1061) made a new study start in start-up and updated the journeys to open it
(`tests/e2e/journeys/steps.py`, J-CRC-08). It did not update `tools/public_e2e.py`, whose stage 1 creates PUB-ONC and
PUB-CA fresh.

Its stage-0 check, "missing birth dates reported, not invented", had failed since 2026-11-17:

- the site's summary said 120, the ingest's missing `Patient.birthDate` said 117;
- `patient.csv` holds 117 empty birth dates;
- since B1, a note can state an age the record lacks, and that patient is written with a birth date. The summary still
  counted `age is None`.

## Decision

1. **`public_e2e.open_study`** opens each study at the start of stage 2 as the journeys do: the SAE type
   `tw_trial` on the set-up page, then Open on the state page. Each request is a check, so a study that does not open
   says so there, not as a SCREEN that never finished.
2. **`public_site.summarise`** counts as `age_missing` the patients written with no birth date (each patient's record
   now keeps the `birth_date` written for it).

## Test

- `tests/unit/test_public_e2e_opens_its_studies.py` (3 tests, each fails on the code before this change):
  - stage 2 opens both studies before it asks for a list;
  - a study is opened by the journeys' own routes and values, with three checks;
  - the summary counts only patients with no birth date written.
- **The run itself,** locally as the job runs it (TB_ENV=DEV, stub model, the public corpus): **136/136 checks pass**
  in 161 s. Before the change it crashed at stage 2; with only the first fix, 135/136 passed (the birth-date check).
