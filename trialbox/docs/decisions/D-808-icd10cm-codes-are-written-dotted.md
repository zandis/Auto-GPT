# D-808 ICD-10-CM codes stored without their dot are written dotted, at ingest

- **Task:** F6 (from the first look at a real source; facts kept off the repository)
- **PR:** this branch (`agent/F6-icd10cm-dotted`)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** D-580 (counted, never guessed), D-593 (`dotted: icd9` for a mapped lookup)

## Context

Value sets and screens hold ICD-10-CM dotted (`M10.9`) and match exactly or by prefix. A source that stores `M109`
matched nothing. Only the MIMIC normaliser added the dot.

## Decision

1. **The mapping side writes the dot**, once, so every screen, value set and export reads one form (proposed on
   #639; lane A2 changes nothing). A site declares it per element: `{builder: coding, ..., dotted: icd10cm}`.
2. A code of the ICD-10-CM shape gets its dot after the third character; a three-character category has none; a
   dotted code is kept (upper case). Any other code is copied as fed and counted (`shape:icd10cm`, kind
   `code_unknown`).
3. Without the declaration nothing changes.
