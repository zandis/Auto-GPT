# D-848 The data dictionary TrialBox hands out has REDCap's 18 columns, in REDCap's order

- **Task:** RC13-B (D-521: the owner's REDCap 13.7.23 run privately and offline in lane E's container; synthetic
  projects only)
- **PR:** this branch (`agent/RC13-B-dictionary-all-columns`)
- **Date:** 2026-11-16
- **Status:** proposed (merges on green CI)
- **Builds on:** D-840 (`@TB-DECIMALS`), STD-061

## Decision

1. REDCap's dictionary import reads its columns by position: a row with fewer columns, or the columns in another
   order, is refused or misread. `datacore.forms.metadata` now gives every row all 18 columns in REDCap's order, and
   `dictionary_csv` writes REDCap's 18 headers in that order (the reader still maps any of them by name).
2. What TrialBox knows is no longer dropped on the way out: the identifier flag (`identifier: y`) and a decimal
   field's places, as `@TB-DECIMALS=n` in the field annotation (read back by D-840).
3. Columns TrialBox does not keep (section header, note, alignment, question number, matrix group and ranking) are
   written empty. A calculated field's expression is not kept by `Field` and stays empty, as before: a separate card
   if sites are to build calculated fields from TrialBox's dictionary.
