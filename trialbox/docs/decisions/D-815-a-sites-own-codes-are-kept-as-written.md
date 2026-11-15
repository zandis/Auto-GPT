# D-815 A site's own diagnosis codes are kept as written, never dotted into a code they are not

- **Task:** CGRD-A3 (from the first look at a real source; facts kept off the repository)
- **PR:** this branch (`agent/CGRD-A3-local-codes-kept-as-written`), cut from CGRD-SQL (#712)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** D-808 (`dotted: icd10cm`)

## Decision

1. A site's own codes that have the ICD-10-CM shape (a local seven-character code) cannot be told from real ones by
   shape. The site lists them in its private mapping: `{builder: coding, dotted: icd10cm, keep_as_written: [...]}`.
2. A listed code is kept as written (upper case, no dot added) and counted (`local:icd10cm`, kind `code_unknown`):
   unmapped with a reason, never dropped, never turned into a code it is not.
3. A code of the right shape that a code table lacks is dotted as before: it matches no value set.
