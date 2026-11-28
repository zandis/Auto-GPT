# FU-DQD-NAMES: the data quality rows are scrubbed and typed

**Reader:** the people who build TrialBox: the lane H lead and lane N (its files are touched). One language.

- **Card:** FU-DQD-NAMES (lane H, follow-up to the data quality rows of H3-NLP §3.1)
- **Date:** 2026-11-28
- **Findings:** [`dqd-name-scrub-2026-11-28/findings.json`](dqd-name-scrub-2026-11-28/findings.json)
  (FUDQDNAMES-01 to FUDQDNAMES-02)
- **Tests:** `tests/unit/test_dqd_scrub.py`, `tests/console/test_dataops_dqd_scrub.py`; the existing
  `tests/console/test_dataops_dqd.py` and `tests/unit/test_dqd_in_the_night.py` are unchanged and pass

## What was found

A data quality row (`checkName`, `cdmTableName`, `cdmFieldName`, `status`, `notes`) went from `omop.dqd.run` through
`adapter.dual_write._dqd` into the night report and the audit event, through `datacore.dataops.omop_kept` into the
batch row, and out through the batch page and `/api/v1/data/batches/{id}`, with no scrub. `omop_kept` also copied a
`failed` that was not a list, and any field value of any type.

The study export (`datacore/export.py`) and the support bundle carry no data quality rows. The orchestrator's batch
answers read the batch row, which now holds the scrubbed record.

## What changed

- `omop_kept` is the one projection. A text field goes through `tb_common.logging.redact` (the scrub the logs use); a
  count must be an int; `cdmFieldName` may be empty; anything else is dropped, and one warning gives how many values
  were dropped (a count, never a value). A `failed` that is not a list is dropped.
- `adapter.dual_write._dqd` projects through `omop_kept`, so the night report and the audit event are scrubbed where
  they are made. `DataOps.record_night` puts the scrubbed record in the audit event too.
- `console.dataops_page.dqd_of` projects through `omop_kept`, so a row stored before this card is scrubbed when shown.

## Not covered

The scrub finds labelled forms (a labelled name, a chart number, an id); a person's name standing bare in a note is
not found. That is the scrubber's stated limit.
