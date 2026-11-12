# 11. The vector store

Note text is chunked and embedded on the box, into the box's own PostgreSQL (schema `vec`, pgvector; T-203a,
D-439). The vectors never leave the box and are never written into a lake snapshot file.

**What is stored.** `vec.note_chunk` holds each chunk of a note: the pseudonymous patient id, the note id, its date
and type, the chunk's start and end offsets in the note, the chunk text and its sha256. `vec.embedding` holds one
vector per chunk text and embedding model (a `halfvec` of the embedder's dimension); a text met again on a later
night, or in another note, is not embedded again.

**Names and numbers never reach it.** Every note goes through the PHI pass of T-600 (`mask_note`: names, phone
numbers, chart numbers and ID numbers, with the site's chart-number pattern) before it is chunked. The stored chunk
text and everything the embedder reads are the masked text. Masking keeps the length, so the offsets also point
into the original note, which stays only in the lake's `document` table under the `phi` label.

**Chunks.** A chunk ends at a sentence end (`。！？；`, `.`, `!`, `?` before a space, a line break) and holds at most
500 characters; the next chunk repeats the last whole sentences of the one before, up to 100 characters. A
sentence longer than 500 characters is cut into windows of 500 with the same overlap.

**The embedder decides the dimension.** The embedder is chosen in G1 (D-429). The store takes the dimension from the
embedder and makes one HNSW index per embedding model, so the switch from the CI stub to the chosen embedder
needs no schema change. Vectors of the stub (DEV and TEST only) and of the embedder never mix.

**Backup, retention and erasure.** The schema is in the nightly backup with the rest of the trial database; the
backup drill (`tools/backup_drill.py`) checks it reads back the same after a restore. Its rows are derived data
(record inventory O-13): kept while the note is in the lake. Erasing a patient (T-206b) calls
`VecStore.delete_patient`, which removes the patient's chunks and every vector no other chunk uses, in one
transaction.

**Screening reads it behind a flag (T-203b, D-449).** The flag `vec.s2b` (off; switched on `/ops/flags` with a
reason, never by an environment file) makes S2b of the screening cascade rank a patient's window sentences from the
stored vectors instead of embedding them during the run. The orchestrator asks the lake service (`POST /vec/s2b`):
only the lake's role reads `vec`. The lake reads the window notes from the snapshot the job pinned and chunks them
again exactly as the indexer does; when every note's chunks and their vectors of the lake's embedder model are in the
store, it ranks them, and the cascade gives each sentence the score of the best chunk over it. Anything else (no
store, a note not indexed, a note whose text changed since a later night indexed it, a missing vector, an error)
sends that pair to the old on-the-fly path. Each patient's run records how many pairs came from the store, how many
fell back and why, and the embedder model of each, in the job's file `s2b_source_<study>_v<version>.json` (SCREEN and
MICROBATCH; console only, never mailed); the stage log counts them. A second model inside one patient's run is refused. With absence
semantics on (feasibility) the store is not asked, because the S2b threshold is fitted to on-the-fly vectors and is
refitted only after the embedder is chosen (D-429). In screening S2b only picks the excerpts and the index rescue: it
never excludes, with the flag on or off.

**Indexing a snapshot.** `vec.index.index_snapshot(store, lake, snapshot, embedder, exclude=opted_out)` indexes every
note of a snapshot, leaving out the patients of the opt-out register; text already embedded costs nothing. Its
nightly run after the lake rebuild is not wired yet (see D-449 "Open").

**Parity.** `python -m tools.vec_parity --db-url <a database with pgvector>` builds a synthetic site,
indexes it, runs the screening cascade of every ruleset with note criteria with the flag off and on, and writes
`eval/vec_parity/report.json`: the S2b pairs, how many were ranked from the store, how many excerpt sets and final
results differ. The committed record is the hash stub's; it is repeated with the chosen embedder before the flag is
switched on at a site.

**Not yet.** The lake's older vector file `embed_cache.duckdb` (D-149) stays until the parity with the chosen
embedder is recorded (D-449 "Open").
