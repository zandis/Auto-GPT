# 5. Data protection

- **Pseudonyms at the door.** The adapter turns each chart number into `HMAC(site key, chart number)`; names and IDs
  live only in the AES-GCM pid map. The lake has no chart number, ID or phone column (`e2e_simple` stage 0).
- **Log scrubbing.** Logs carry pseudonyms only; the scrubber removes Japanese and Taiwanese IDs, phone numbers and
  postcodes (`tb_common/logging.py`, D-121).
- **Small cells.** Counts under 5 are shown as `<5` in anything that leaves the study team (`tb_common/smallcell.py`).
- **Routing.** Patient-level files go only to the study's internal list, as 7z AES-256 with the password in a second
  mail; aggregate files may go to `aggregate_to`. Checked before every send (`tb_common/routing.py`).
- **Models.** Every call goes through the gateway, which routes by data class; local models only for patient data.
  A note excludes a patient only when two different models agree on a verified quote, and every note holding the
  evidence was shown to them (D-115, D-117, D-276).
- **Planted instructions.** A fence in a note, chart, consent form or protocol cannot close a prompt's data block;
  text nobody can see on the page is flagged; the injection suite (56 attacks, 14 controls, en / ja / zh-TW) gates
  CI against the stub and `qualify` against a pair; model traces live 7 days in PRODUCTION (D-346).
- **One-way hospital systems.** TrialBox never writes to an EMR, SS-MIX2 or CGRD (owner decision 2).
- **What an opt-out removes today** (D-441, D-465). Within one tick of the opt-out worker (`TB_OPTOUT_WORKER_MINUTES`)
  the patient leaves the candidate pool, every open candidate becomes withdrawn (a consented or enrolled subject's
  trial record stays, OD-8), OMOP's live rows are deleted and tombstoned and later loads keep them out, and the vector
  store's chunks and the patient twin are deleted; each store is read back and a row left turns the health line red.
  Kept on purpose: the register itself, the pid map (the chart number must still be recognised), OMOP's consent rows
  and person map, the break-glass record, the audit chain (counts only). **Still owed** (T-206b): the lake's kept
  snapshots, NDJSON nights and Parquet, `embed_cache.duckdb`, OMOP's before-images, the FHIR store, derived rows, job
  outputs and attachments, EDC drafts of a patient who never enrolled, the backups and the other lines of the
  generated list `docs/validation/erasure-registry.md`. Every screening path already reads the register, so no list
  shows the patient meanwhile.
