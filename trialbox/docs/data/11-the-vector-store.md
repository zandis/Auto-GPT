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

**Not yet.** Screening does not read this store yet: S2b reads it behind a flag after a parity test (T-203b), and
the lake's older vector file `embed_cache.duckdb` (D-149) is removed only after that.
