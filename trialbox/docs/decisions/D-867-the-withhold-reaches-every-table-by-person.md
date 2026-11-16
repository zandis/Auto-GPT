# D-867 The withhold reaches every OMOP table by person, and the clinical conflicts (ERASE-B)

- **Task:** ERASE-B, lane C2's backlog after the PoC freeze: 13 owed OMOP entries that wait for nothing. · **Date:** 2026-11-16
- **Decision:** the opt-out's withhold (`omop.load.withhold_persons`, D-441) now also deletes, by person and in the same transaction:
  - the 12 CDM tables no loader writes today: `condition_era`, `drug_era`, `dose_era`, `device_exposure`, `specimen`, `visit_detail`, `payer_plan_period`, `episode` with its `episode_event`, `cohort` (by `subject_id`), `cost` (through the person's events, by domain), and `location`, an address no other person and no care site uses;
  - `tb_conflict`, every source's value of a disputed item of the person.

  It runs on every tick for everyone opted out, before the early return taken when no live records are left, so a loader that writes one of these tables later is covered from its first row. The worker's read-back counts each of them. The export as of a time (T-728) ends in the same function and drops them too.
- **Why:** each was owed with a plain delete by person and needs nothing from another lane. The owed list goes from 49 to 36 on master (this card alone).
- **Left:** `omop.tb_record` and `omop.tb_record_event` wait for the owner's ruling (the integrator advises a D-441 keep entry: ids only, the trail of what was erased). A `cost` row whose event was already deleted on an earlier tick cannot be attributed; no loader writes `cost` today, so there is none.
- **Held by:** `tests/unit/test_the_withhold_reaches_every_table_by_person.py`, synthetic ids only (failing output on master kept: `eraseb-fail.txt`).
