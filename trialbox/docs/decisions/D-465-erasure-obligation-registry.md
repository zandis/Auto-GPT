# D-465 Erasure as an obligation of every store: one registry, a test that enumerates the stores, the worker runs it

- **Task:** T-727 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.3, wave G; privacy)
- **PR:** this branch (`agent/T-727-erasure-obligation-registry`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Closes:** root cause S4 / R4 of the lifecycle review of 2026-11-12 ("erasure is a list a store opts into; a new
  store is exempt by default"); F-7 (the structural half: the stores are enumerated, the two erase functions that
  existed are called); frames F-14 and F-9 (their clears stay T-206b's and T-728's, listed as owed)
- **Builds on:** D-441 (T-206a, the opt-out worker), D-147 (the register), D-439 (T-203a, the vector store), D-440
  (T-204, the patient twin), D-378 (T-212c, one database role per service), OD-8 (an enrolled participant's trial
  record stays), D-204 (migrations), D-363 (the record inventory)

## Context

The opt-out worker of D-441 cleared the stores of a private list (`STORES` in `services/datacore/optout_worker.py`:
the candidate pool, the candidate registry and OMOP). A store joined the list only if its card called
`register_store`, and no card did: `VecStore.delete_patient` (D-439) and `ProfileStore.erase` (D-440) existed and were
never called by the worker. After an opt-out and a tick the patient stayed in at least ten stores (review
`2026-11-12-architecture/lifecycle.md` F-7), and nothing made an eleventh store impossible to add without a clear.

## Decision

1. **One registry, `libs/tb_common/erasure.py`.** Every table created by every store's migrations (the stores of
   `tests/unit/test_migrations.py::store_migrations`, keyed `schema.table`), every top-level entry the lake and the
   adapter write under the lake directory (keyed `lake:<name>`), every object-store prefix (`objects:<prefix>`) and the
   stores outside both (the FHIR store, the backups, the audit day files and journal) has exactly one obligation:
   - `erase`: the opt-out takes the patient out. The entry names its **clear** (a named function of the worker that
     takes the opted-out pids and returns counts) and the clear names its **verify** (reads the store back and returns
     the rows still there, per table). Where no clear exists yet the entry is `erase` with no clear and an
     `owed_by` card (T-206b), and it is on the generated **erasure owed** list. An entry whose clear does only part of
     the job (OMOP's `tb_record`: tombstoned, the row stays; the candidate registry: withdrawn, the row stays) has
     both a clear and an `owed_by` naming what is left.
   - `keep`: kept on purpose, with the decision that says why: the opt-out register itself (D-441, D-147); OMOP's
     `tb_withheld` and `tb_consent` and `tb_id_map` (D-441 §4: the refusal must reach the lake, and the worker must
     still find the person); the pid map and its aliases (D-441 §2: the chart number must still be recognised at the
     door, and a merged chart's opt-out hides the surviving pid); the trial record of a consented or enrolled subject
     (OD-8: the data core, signed EDC rows, the SAE register); the break-glass grants and uses (D-430: the steward's
     review of an access); the audit chain (D-394, D-147: append-only, and the opt-out's own events carry counts only,
     never who).
   - `no_patient_data`: nothing about a patient (reference data, settings, staff, counts).
   Each table was classified from its columns: a table with a pseudonym, a person id, a hash of a pseudonym or free
   text taken from a record is not `no_patient_data`.
2. **The enumerating test** (`tests/unit/test_erasure_registry.py`) extracts every `CREATE TABLE` (and the renames and
   drops) from every store's migrations, the lake's top-level entries from the lake's and the adapter's own code (the
   paths written under the lake directory and `RERUN_DIR`), and the object-store key prefixes from the code that
   builds the keys; it fails on any with no entry, and on an entry naming one that no longer exists. A new table, lake
   folder or object prefix in any card fails it until the card adds its line.
3. **The worker runs the registry.** `optout_worker.STORES`, `BUILTIN` and `register_store` are gone. One tick runs
   every clear the registry names (`erasure.clears()`), then that clear's verify; a clear that raises, or a verify that
   finds a row of an opted-out patient, is listed in `failed`, audited (`optout.worker_failed`, names of clears only)
   and turns the health line red (`metrics.check_optout`). The tick's `optout.worker` event carries the counts and
   the verify's remaining counts, never a pseudonym. Clears today: `candidate_pool`, `candidate_registry`, `omop`
   (D-441) and, new, `vec` (`VecStore.delete_patient`: the chunks and every vector no other chunk uses) and `profile`
   (`ProfileStore.erase`: every version of the twin).
4. **The database roles.** The worker runs in the orchestrator. The smallest correct wiring: **`profile` and `vec` are
   added to `tb_orchestrator`'s list** in both copies of `30-service-roles.sh` (kept byte-identical). The orchestrator
   already builds the twins (`twins_after_ingest`), so on a box with the D-378 roles it was the schema's creator and
   owner by accident; the list now says so. `vec` stays the lake's; the orchestrator joins its group so the clear can
   delete. The alternative, a lake endpoint the orchestrator calls, would add a route, a token check and an HTTP
   failure mode to a tick that must not depend on the lake service being up; the orchestrator already holds OMOP's
   notes, so `vec`'s masked chunks are no new class of data for it. A store that does not exist on a box (no pgvector,
   no twin yet) is not created by the worker: its clear reports `skipped` and its verify finds nothing. The lake's
   nightly indexer (T-203b) still cannot read `optout`; it may index an opted-out patient's notes again, and the next
   tick deletes them (within `TB_OPTOUT_WORKER_MINUTES`). Skipping at index time is T-203b's.
5. **The owed list can only shrink.** `erasure.owed()` is the list of `erase` entries not fully met; the seed test
   asserts it equals a known set, so a card that adds a clear must remove its line, and a card that adds a store with
   patient data and no clear must add one. The list is rendered in `docs/validation/erasure-registry.md`
   (`python -m tb_common.erasure --write`; a test fails when the file and the registry differ).
6. **What an opt-out removes today** is written once, in `docs/security/05-data-protection.md`, from the registry: the
   candidate pool, open candidates (withdrawn), OMOP's live rows, the vector store and the patient twin. Everything
   else on the owed list stays until T-206b builds its clear: the lake's snapshots, NDJSON nights and Parquet,
   `embed_cache.duckdb`, OMOP's before-images, the FHIR store, derived rows, job outputs, EDC drafts of a patient who
   never enrolled, the backups and the rest of the list.

## Not done here

- The remaining clears (T-206b, PR #278, on this registry); restore and as-of export (T-728).
- The console reads twins (`services/console/twin_api.py`) but `tb_console` has no `profile` in its list: on a box
  with the D-378 roles that read is refused. Not an erasure question; reported for T-204's follow-up.

## Tests

`tests/unit/test_erasure_registry.py`: every table, lake entry and object prefix has an entry and every entry names
one that exists (and a planted new table, lake folder and object prefix are each found); every `keep` names a decision,
every `erase` a clear or an owed card, every clear resolves to a function and a verify; the generated file is current.
`tests/unit/test_erasure_seed.py`: one synthetic patient in every store that has a clear today (the pool, an open
candidate, OMOP, the twin, the vector store where pgvector exists), an opt-out, one tick: every verify finds nothing,
an independent scan of every table of the test database and every file of the lake folder finds the pseudonym only in
stores whose entry is `keep` or owed, and the owed list is exactly the known set. `tests/unit/test_optout_worker.py`
moves from `register_store` to the registry: a failing clear and a verify that finds a row are both reported, audited
and turn the health line red.
