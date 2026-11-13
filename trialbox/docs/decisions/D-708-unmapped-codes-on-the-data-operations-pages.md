# D-708 The data-operations pages show the records a night did not load for an unmatched hospital code

- **Task:** NEW-DOPS-1 (the console's half of NEW-DIN-6, D-580 "Not in this card"; the integrator's order of
  2026-11-13)
- **PR:** this branch (`agent/NEW-DOPS-1-unmapped-codes-on-the-night`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-580 (a code the look-up does not know is counted every night), D-443 (the data-operations
  console), D-427 (the night's row keeps tables and counts, never a row)

## The problem

D-580 counts, every night, the records dropped because their hospital code is not in the site's code table, and
keeps the count per source table in the night's row. No page showed it. A lab analyte could be missing for every
patient, its criteria reading "no data", and the only place that said so was a file in the night's folder.

## The decision

- **The night's page** (`/data-ops/batches/{id}`) has a section when the night dropped any: every source table
  with its count, the largest first, and the total. No table is cut (OD-10). The help line says that this does
  not hold a night and that the codes, with how often each came, are in `unmapped_codes.json` in the night's
  folder, for the person who keeps the code table.
- **The source's line** on `/data-ops` (the newest night of each source) carries the total as a link to that
  night.
- **`GET /api/v1/data/batches/{id}`** answers the same list (`unmapped`: table and records).
- One function reads the row (`console.dataops_page.unmapped_of`): a value that is not a table name with a count
  above zero is not shown, and breaks no page.
- English, Japanese and Traditional Chinese.

## What it does not do

- **No code is shown.** The row keeps none (D-580 writes codes only to the file, after its own check that a value
  looks like a code); the page does not read the file. Showing the largest codes on the page would need the
  console to read the night's folder or the adapter to serve the file: a later card, if the owner wants it.
- It does not hold a night and adds no threshold (D-580, point 4).
- It does not show the first-load path's counts (the first load does not write a night's row).
- A table's name is the site's own text (its mapping names it) and is written as text. The wording check is the
  pages' own words; a site that names a table with a word the pages avoid sees its own name.
- The same right as the page (`dataops.view`: the data steward and the administrator); no new route, no new row
  of the matrix.

## Review

See "What the adversarial review changed" when the review is in.

## Reuse check

The night's row and its `detail` (`datacore.dataops`, `DETAIL_KEYS` already keeps `unmapped`), the page's own
templates and catalogue (`console.i18n_dataops`) and the wording check (`tb_common.wording.check`). Nothing is
added to a store and no new reader is built.

## Dropped (D-311)

No sign-off step.
