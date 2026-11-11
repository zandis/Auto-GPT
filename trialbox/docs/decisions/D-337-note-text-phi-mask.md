# D-337 Note text is masked before chunks, full-text search and embeddings

- **Task:** T-600 (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-600-phi-guard`)
- **Date:** 2026-11-10
- **Status:** accepted
- **Closes:** CR-028 (FR-DEID-01, the D-111 "Not done" item), DATA-020

## Context

Note text in the lake kept patient and staff names, phone numbers and chart numbers. It fed the chunk table, the
BM25 index and the embeddings, and so every retrieval result and every chunk sent on to a model (CR-028, DATA-020:
on the e2e lake 1,223 of 8,889 notes held a patient's phone and 2,480 a chart number).

## Decision

1. **One masker.** `tb_common.phi_guard.mask_note(text, mrn_regex)` masks names, phone numbers (Taiwan and Japan),
   chart numbers and ID or insurance numbers. Chart and ID numbers are found after their label (病歷號, カルテ番号,
   Chart no., 健保卡號, 保険者番号 ...) and, with the site's `settings.mrn_regex`, also without one. Names are found
   after a role or label (記錄者, 家屬, 記載医, 家族の, Dr, Seen by, Daughter ...), before a role (醫師, 護理師) or
   an honorific, and by the v1 rules (patient word, sex and age). Only the identifier is masked, never the title,
   the sex or the age.
2. **Length kept.** Each character of a span other than white space becomes `○`. Chunk boundaries, offsets and line
   breaks stay where they were, so retrieval windows and the clinical words around a span do not move. The
   tokenizer drops `○`: a masked span gives no term to the full-text index and no feature to the hash embedder.
   Masking masked text changes nothing.
3. **Where it runs.** `lake.store.Lake.rebuild` masks each note before chunking; chunk text, BM25 tokens, chunk sha
   and embedding input all come from the masked text. The embed service masks every input to `POST /embed` as
   well, so a caller that sends raw text still embeds none of it. The lake service and the adapter's local rebuild
   pass the site's `mrn_regex`; any other caller gets the labelled patterns.
4. **The original stays under `phi`.** The `document` table and its Parquet file keep the note as written
   (`lake.flatten.PHI_COLUMNS`). The screening engines read coded tables and that original, so screening results
   do not change: the funnels, screen and FEAS goldens are unchanged; `lake/tables@ci.json` moves only in the chunk
   table's `text`, `tok` and `sha`.
5. **Recorded.** `lake_meta.note_mask` carries `phi_guard.NOTE_MASK_VERSION` (now `1`). A snapshot without it was
   built before this decision and still holds unmasked chunks.

## Consequences

- A search for a name, phone or chart number in note text finds nothing. That is the intent.
- The protocol parser (`services/doc_parser`) reads trial protocols, not patient notes, and is left as it is.
- Snapshots built before this change keep unmasked chunks until they are rebuilt or pruned; the embedding cache
  keeps vectors (no text) under the old chunk sha until pruned.
