# D-869 A patient's own upload to the site set-up goes whole at an opt-out (ERASE-A4)

- **Task:** ERASE-A4, lane C2's backlog after the PoC freeze. · **Date:** 2026-11-16
- **Decision:** a new clear of the opt-out worker, `setup_uploads`, deletes a per-patient upload of the site set-up whole: a chart, which is a `sitesetup.input` row carrying the patient's pseudonym. What goes:
  - its files on disk under the set-up's folder: the upload, its text and its lake text, `<ws>/inputs/<id>.*`;
  - its check items, its column fixes and its facts;
  - the row itself.

  The files go first, so a crash leaves the rows and the next tick finishes. The tick passes the orchestrator's set-up folder. A worker that cannot reach it never calls the uploads cleared. Since ERASE-A1 (D-866), no new chart of an opted-out patient is kept.
- **Left:** a sheet of many patients that names the patient stays owed. Its file and its rows (`check_item`, `fix`) are not keyed by patient, and taking the patient's rows out means rewriting the sheet. `sitesetup.input`, `check_item` and `fix` say so; the owed list keeps the three entries for that rest.
- **Held by:** `tests/unit/test_a_patients_own_upload_goes.py`, synthetic data only (failing output on master kept: `erasea4-fail.txt`). The pinned clear-name list of `test_erasure_registry` moves.
