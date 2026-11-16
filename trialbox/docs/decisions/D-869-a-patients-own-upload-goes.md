# D-869 A patient's own upload to the site set-up is deleted at an opt-out (ERASE-A4)

- **Task:** ERASE-A4, lane C2's backlog after the PoC freeze. · **Date:** 2026-11-16
- **Decision:** a new clear of the opt-out worker, `setup_uploads`, deletes a per-patient upload of the site set-up: a chart, which is a `sitesetup.input` row carrying the patient's pseudonym (only a chart carries one). What goes:
  - its files on disk under the set-up's folder: the upload, its text and its lake text, `<ws>/inputs/<id>.*`;
  - its check items, its column fixes and its facts;
  - the row itself.

  The files go first, so a crash leaves the rows and the next tick finishes. An upload that raced the clear is swept on a later tick: facts of no upload, and files no row names that are older than the moment the ids were read. A file written after that may be an upload whose row came later, so it is left. The tick passes the orchestrator's set-up folder; a worker that cannot reach it never calls the uploads cleared. A publish that meets a just-deleted file skips it.

  A consented subject's chart goes too: the set-up's chart is the site's own input, not the trial's record (REDCap and the EDC keep that, OD-8).
- **The lake's copies:**
  - the hospital lake's `lake:site` loses the chart at its next publish, within about a minute;
  - its snapshots and the backups keep it, and stay owed (`lake:db`, `lake:parquet`, `lake:embed_cache.duckdb`, `outside:backups`);
  - a practice space's own lake keeps the chart's text until that space is published again, named under `outside:sitesetup_space_omop`.
- **Left:**
  - A sheet of many patients that names the patient stays owed: its file and its rows (`check_item`, `fix`) are not keyed by patient.
  - A chart uploaded under a merged-away chart number of a patient who opted out under the surviving number is not found: `with_survivors` follows merges one way, a gap of the whole system.
  - ERASE-A1 (D-866, #830) refuses a new chart of an opted-out patient; until it lands, such a chart is kept until the next tick.
- **The adversarial review (NOT SOUND as first worded):** "goes whole" over-claimed (the lake copies), an upload racing the clear could leave orphans, and a racing publish could fail once. All three are fixed or named above.
- **Held by:** `tests/unit/test_a_patients_own_upload_goes.py`, synthetic data only (failing output on master kept: `erasea4-fail.txt`). The pinned clear-name list of `test_erasure_registry` moves.
