# HPOC1: the proof-of-concept workbook door

**Reader:** the people who build TrialBox: the lane H lead and the integrator. One language.

- **Card:** HPOC1, item 1 (lane H)
- **Date:** 2026-11-28
- **Findings:** [`poc-workbook-door-hpoc1-2026-11-28/findings.json`](poc-workbook-door-hpoc1-2026-11-28/findings.json)
  (HPOC1-01 to HPOC1-04)
- **Tests:** `tests/unit/test_poc_workbook_door.py`, `tests/unit/test_poc_workbook_lake_omop.py`

## What was found first

No spreadsheet door existed (the readers were `csv`, `cgrd_sql`, `ssmix2`, `fhir_bulk`). The lab lookup already
accepted a `score` code system, and a numeric Observation already became an OMOP measurement. A free-text Observation
did not become an OMOP observation, and no year-month birth was handled anywhere.

## What it does

- `--source xlsx --path <file>`: one workbook, each sheet a table. Values only: a formula cell leaves its row out
  (counted with the reason in the night's completeness file), a sheet over 100,000 rows or a workbook over 25 MB is
  refused whole with a reason, a missing sheet is reported as missing. None of these stops the night.
- `mapping/poc/poc_workbook.yaml`: the nine Japanese-headed sheets onto the canonical tables. `score` and
  `finding` are new canonical tables. A site mapping may now carry resources of its own.
- Birth: `1948-05` stays year and month in FHIR, in the lake (`patient.birth_ym`, `birth_date` NULL) and in OMOP
  `person` (year and month, day and birth datetime NULL).
- Scores are OMOP measurements (the instrument is the source code, the number is `value_as_number`). Findings are
  OMOP observations (`value_as_string`, the text as `value_source_value`, the finding code as the source value).
- The template is written by `python -m tools.poc_workbook`; a test holds the committed file equal to its output.
  Every example row is synthetic (case number `SYN-0001`).

## Lake layout

Schema version 5 adds `patient.birth_ym` and `observation.value_text`. A snapshot of an older layout reads both as
unknown through the compatibility view (tested). The finding text is patient text: a test holds it out of the log and
of every night report file.

## A year-month birth and the age criteria

`tests/unit/test_poc_workbook_age_unknown.py` screens a patient born `1958-11` (lake `birth_date` NULL) through the
real compiled SQL and the cascade, with an age inclusion (>= 65) and an age exclusion (>= 86), beside a patient with a
whole birth date and one aged 96. The year-month patient stays on the list (tier review), both criteria are unknown,
and the funnel keeps them through every stage (3 in, 2 after the exclusion: only the 96-year-old leaves). The compiled
base keeps a NULL-birth patient (`p.birth_date IS NULL OR ...`) and the age expression is NULL for them, which the
cascade reads as unknown. The test passed on the existing compiler: nothing in the compiler changed.

## Not done

See the findings: no code-level test-data stop, the finer age rule, `settings.yaml` naming `xlsx`, and the
birth conflict across sources.
