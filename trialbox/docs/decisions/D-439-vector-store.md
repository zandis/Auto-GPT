# D-439 The vector store in pgvector: schema `vec`, a sentence-aware chunker with offsets on masked note text, one embedding per text and model, the dimension from the embedder, one read and one per-patient delete

- **Task:** T-203a (`docs/plan/28-master-plan-v6.md` §6.2.6, wave 3; part a of T-203, TB-ASSESS-01)
- **PR:** this branch (`agent/T-203a-vector-store`)
- **Date:** 2026-11-11
- **Status:** proposed (in review)
- **Closes:** CR-068 (the vector half), FIT-004 (part: "no pgvector store")
- **Builds on:** D-204 (the db image with pgvector, checksummed migrations), D-378 (one role per service),
  D-337 / T-600 (note text masked before chunks and embeddings), D-429 / T-607 (the embedder under control; its
  dimension is not known before G1), D-149 (the lake's DuckDB vector store, interim: review P-36)

## Context

The lake keeps its vectors in `embed_cache.duckdb` (D-149), a DuckDB file with its own lock protocol, declared
interim by the review (P-36). The plan wants the vectors in the box's PostgreSQL with pgvector (`halfvec`, HNSW),
so that S2b retrieval (T-203b), "patients like this one" (T-203c) and erasure (T-206b) all reach one store that the
nightly backup already covers. The embedder is not chosen yet (D-429 "Open"): its dimension comes after the G1 run,
so the schema cannot fix `halfvec(1024)`.

## Decision

1. **Schema `vec`, two tables** (`services/vec/store.py`, version 1, pinned in `tests/unit/test_migrations.py`):
   - `embedding (sha, model, dim, emb public.halfvec, made_at)`, key `(sha, model)`: one vector per masked chunk
     text (its sha256) and embedding model. A text met again (the same note on two nights, the same sentence in two
     notes) is never embedded twice. A check holds `public.vector_dims(emb) = dim`.
   - `note_chunk (pid, did, chunk_no, note_date, note_type, start_char, end_char, text, sha, mask_version, made_at)`,
     key `(did, chunk_no)`, btree indexes on `(pid, note_date)` and on `sha`. `text` is the masked chunk text.
2. **The dimension comes from the embedder, not from the schema.** The column is `halfvec` without a size; each row
   records `dim`. The HNSW index is an expression index made for each embedding model when the store is opened for
   it (`VecStore(url, model=, dim=)` or `ensure_index`): `USING hnsw ((emb::public.halfvec(<dim>))
   public.halfvec_cosine_ops) WHERE model = '<model>'`, named `embedding_hnsw_<sha of the model name>`. A vector
   whose length differs from the embedder's `dim` is refused before anything is written. When G1 names the
   embedder, nothing in the schema changes: its vectors get their own index, and the hash-stub rows (DEV and TEST
   only, D-429) are a different model and never mix with them.
3. **Chunks are made after the PHI pass.** `services/vec/index.py` masks each note with
   `tb_common.phi_guard.mask_note` (the site's chart-number pattern), then chunks the masked text. Masking keeps the
   length, so a chunk's `start_char` and `end_char` index the original note text too: the chunk text is exactly
   `masked[start:end]`, and the note's own bytes are `note.encode()[len(note[:start].encode()):...]`. No unmasked
   text reaches a chunk, the `note_chunk` table or the embedder's input. The chunker
   (`services/vec/chunker.py`) cuts at sentence ends (`。！？；`, `.!?` before white space, line breaks), packs
   sentences up to 500 characters, carries whole trailing sentences up to 100 characters into the next chunk, and
   cuts a sentence longer than 500 characters into windows with the same overlap.
4. **One read and one delete for the next cards.** `VecStore.search(vector, model, k, pids=None)` is the read T-203b
   puts behind its flag: with `pids` it ranks those patients' chunks exactly (btree on `pid`, no index needed);
   without, it ranks through the model's HNSW index (for "patients like this one", T-203c, which filters by
   `permit` before ranking). `VecStore.delete_patient(pid)` is the erasure T-206b calls: in one transaction it
   deletes the patient's chunks and every embedding no other chunk still uses, and returns both counts.
5. **Roles and backup.** `vec` is on the list of `tb_lake` (D-378): the lake service writes the store and reads it
   for S2b. Its tables are in the nightly backup with every other schema of the trial database; the backup drill
   (`tools/backup_drill.py`) fills the store before the backup and checks after the restore that the rows, the
   vectors, the HNSW index and a search read back the same.
6. **Not wired.** Screening does not read this store yet: that is T-203b, behind a flag, with the parity test. The
   lake keeps writing `embed_cache.duckdb` until then.

## Consequences

- The stock PostgreSQL of the unit job and of the local test cluster has no pgvector, so the store's SQL is tested
  in `tests/integration/test_vec_store.py`, against the box's db image (the nightly or dispatched workflow
  `trialbox-e2e.yml`, `make test-compose`, which allows no skip; it does not run on a pull request) or any server in `TB_TEST_DB_URL` that has the extension. Locally those tests skip with the
  reason. The chunker, the PHI pass, "embed once per sha" and the dimension rule are unit tests that need no
  database.
- `tests/unit/test_migrations.py` migrates every store on the local cluster; it now skips the stores that need an
  extension the cluster lacks (only `vec`), and the integration test migrates `vec` twice instead.
- Erasure (T-206b) has one call to make, and it leaves no orphan vector.

## Open

- The nightly job that indexes the lake's notes into `vec` and the switch of S2b (T-203b), the parity report
  (`eval/vec_parity/report.json`) and the removal of `embed_cache.duckdb` after parity (T-203b, then D-227's line).
- `person_vector` and the structured feature block per specialty (T-203c).
- The HNSW build parameters (`m`, `ef_construction`) stay pgvector's defaults until a 50k-patient measurement.
