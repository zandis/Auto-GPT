# D-816 A report's conclusion falls back to its body, and is masked like note text

- **Task:** CGRD-A4 (from the first look at a real source; facts kept off the repository)
- **PR:** this branch (`agent/CGRD-A4-conclusion-from-the-body`), cut from CGRD-A3 (#715)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** T-600 / D-337 (note text masked with `phi_guard.mask_note` and the site's chart pattern)

## Decision

1. **`else: <column>`** on a column element: the next column when the first is empty. The base mapping's
   `conclusion` reads `conclusion`, else `report_text` (a site renames its summary and body columns to these).
2. **`masked: true`**: the text passes through `phi_guard.mask_note` with the site's chart-number pattern (the
   `Mapper` takes it from the night, the back-fill and `mapping_check`). The conclusion reaches the lake's `report`
   table and the screening facts as it is, so it is masked when it is mapped; the length is kept.
3. The goldens move by `mapping_version` and table hashes only: no synthetic data row changes.
