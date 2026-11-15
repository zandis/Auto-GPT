# D-812 A row without its key is refused, never merged into another

- **Task:** CGRD-A1 (from the first look at a real source; facts kept off the repository)
- **PR:** this branch (`agent/CGRD-A1-a-row-without-its-key-is-refused`)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** D-809 (`join`: a key column made of several), DATA-017

## Decision

1. A table whose key column repeats (a diagnosis row carrying its visit's number) is keyed by the columns unique
   together: the site's `join` written over the key column the base mapping's id reads
   (`join: {diag_no: [enc_no, diag_seq]}`). No engine change was needed for that.
2. **A record id from an empty key is refused**: the row is rejected and counted where rejected rows are. Before,
   every row with an empty key (or a joined key missing a part) had one id, and all but one were lost.
