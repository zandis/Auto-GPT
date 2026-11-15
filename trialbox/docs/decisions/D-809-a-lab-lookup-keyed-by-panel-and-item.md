# D-809 A lab look-up keyed by panel and item; the unit spellings a lab export writes

- **Task:** F10 and F15 (from the first look at a real source; facts kept off the repository). The look-up's
  content comes later, as a code list from the first-look session.
- **PR:** this branch (`agent/F10-lab-lookup-pair-key-and-units`)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** D-580 (counted, never guessed), D-585 (the feed reader's own spellings), D-588

## Decision

1. **A key of several columns.** `tables.<t>.join: {lab_key: [panel_code, local_code]}` makes one key column, and
   `lookups.<n>.key: [panel_code, local_code]` loads the look-up keyed by the same parts, joined with `|`. A row
   without a part has no key: no look-up row, counted as before, never matched on one part. Both are checked when
   the mapping loads; `mapping_check` asks the source for the parts.
2. **Unit spellings, in the feed reader only** (`FEED_SPELLINGS`, never the engines' table):
   - `{cells}/uL` is `/uL` (an annotation says what is counted); `1000/uL` is `10*3/uL`;
   - `mg/L FEU` (and `ug/mL FEU`) is `mg/L{FEU}`, agreeing only with itself: D-dimer in fibrinogen-equivalent units
     is about twice the same result in D-dimer units, so it is never plain `mg/L`;
   - `倍數` / `倍` is `{titer}`, agreeing only with itself.

## Not in this card

- The site's look-up rows (from first-look). A verification mark the source writes on nearly every row says
  nothing on its own; `result_status` is the mapping's `values` map, set when the look-up arrives.
