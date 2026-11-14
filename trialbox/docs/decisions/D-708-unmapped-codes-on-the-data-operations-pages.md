# D-708 The data-operations pages show the rows of a night that hold a value the mapping could not use

- **Task:** NEW-DOPS-1 (the console's half of NEW-DIN-6, D-580 "Not in this card"; the integrator's order of
  2026-11-13)
- **PR:** this branch (`agent/NEW-DOPS-1-unmapped-codes-on-the-night`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-580 (a code the look-up does not know is counted every night), D-587, D-590, D-593 (what else
  that counter holds), D-443 (the data-operations console), D-427 (the night's row keeps tables and counts,
  never a row)

## The problem

Every night the adapter counts the rows that hold a value its mapping could not use, and keeps the count per
source table in the night's row. No page showed it. A lab analyte could be missing for every patient, its
criteria reading "no data", and the only place that said so was a file in the night's folder.

## The decision

- **The night's page** (`/data-ops/batches/{id}`) has a section when the night's row holds any: every source
  table with its count, the largest first (equal counts by name), and the total. No table is cut (OD-10).
- **The words say what the counter is**, as the adapter's own log line does: rows that hold a value the mapping
  could not use (a hospital code that is not in the site's code table, a status or a unit it could not read, a
  code the reference data could not be asked for); such a row is left out or loaded without that value; a row
  with two such values is counted twice; this does not hold a night; the values, with how often each came, are
  in `unmapped_codes.json` in the night's folder (the newest attempt's, and gone when the folder is removed).
- **The source's line** on `/data-ops` (the newest night of each source) carries the total as a link to that
  night.
- **`GET /api/v1/data/batches/{id}`** answers the same list (`unmapped`: table and rows).
- One function reads the row (`console.dataops_page.unmapped_of`): a value that is not a table name with a count
  above zero is not shown, and breaks no page.
- English, Japanese and Traditional Chinese.

## What it does not do

- **No value is shown.** The row keeps none (D-580 writes them only to the file, after its own check that a
  value looks like a code); the page does not read the file.
- **It does not split the count by kind** (a code not known, a unit not read, the reference data not reached).
  The row keeps one number per table; a split needs the adapter to keep it. The owner's to say whether that is
  wanted.
- It does not hold a night and adds no threshold (D-580, point 4).
- It does not show the first-load path's counts (the first load writes no night's row).
- A table's name is the site's own text (its mapping names it) and is written as text. The wording check is of
  the pages' own words; a site that names a table with a word the pages avoid sees its own name.
- The same right as the page (`dataops.view`: the data steward and the administrator); no new route, no new row
  of the matrix.
- Not tested from an adapter night through to the page: the row's shape is pinned by the adapter's own test
  (`tests/unit/test_unmapped_codes.py`) and the page by this card's.

## What the adversarial review changed

One review by a fresh reviewer. Verdict: fix first; the code was sound, the words were not.

- **The first wording said "records not loaded: hospital code not matched".** The counter also holds rows that
  were loaded without a value (a unit not read, D-590), rows with an unknown status (D-587) and rows whose code
  the reference data could not be asked for (D-593), and it counts a row once per such value. A night with 500
  lab rows of a unit not read would have shown "500 records not loaded" and sent the reader to the code table.
  The title, the help, the column head and the mark say what the counter is now, in three languages, by test.
- The help said the file is "in the night's folder" as if it stayed: it is the newest attempt's and goes with
  the folder. Said.
- Japanese and Chinese: polite form throughout, and the catalogue's own words for the box and the night.
- Two tests added: forty-one tables are all listed, and equal counts are in the order of their names.
- Checked and sound: the row's shape is what the adapter writes; no code or identifier can reach the row; a
  table's name is escaped in text and in the attribute; the source's line links the newest attempt of the newest
  night; the routes and their guard are unchanged; the mark-up is valid.

## Reuse check

The night's row and its `detail` (`datacore.dataops`, `DETAIL_KEYS` already keeps `unmapped`), the page's own
templates and catalogue (`console.i18n_dataops`) and the wording check (`tb_common.wording.check`). Nothing is
added to a store and no new reader is built.

## Dropped (D-311)

No sign-off step.
