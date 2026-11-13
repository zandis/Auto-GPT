# D-535 The first load says what a night says about its tables and its codes

- **Task:** NEW-B-13 (the night and capacity lane's queue: "back-fill: the unmapped summary and completeness",
  after NEW-DIN-6 and NEW-DIN-8)
- **PR:** this branch (`agent/NEW-B-13-first-load-completeness-and-unmapped`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** T-611 (the completeness gate per source table), D-583 (NEW-DIN-8: on the first night every table
  of the mapping must be there with rows), D-580 (NEW-DIN-6: the codes no look-up knows are counted every night),
  D-403 (the back-fill: a hospital's first load, by year)

## Context

The back-fill is how a hospital's history first enters the box. It mapped the same tables with the same mapper as
a night, and wrote neither of the two records a night writes about them:

- **No completeness record.** The night after a first load had no baseline. D-583 closed half of that (a table
  missing or empty on that night is held); a table that lost half its rows still passed, because there was no
  count to compare with. And the first-night rule itself was never asked of the load that is the first night: a
  first load without its lab table published.
- **No count of unknown codes.** The mapper counted them during the load and the count was dropped: the site saw
  its unmapped codes only from the first night on, and on delta nights only for rows that changed.

## Decision

1. **The first load asks the night's completeness gate** (`pipeline.completeness_check`, a full night with no
   night before it) of its tables **after the source is read and before a year is published**: a required table
   missing or empty, and with `first_night_all_tables` (the product's entry sets it) any table of the mapping that
   the site did not list as optional. A problem holds the load (`state: held`, `incomplete` in its report);
   nothing is published.
2. **The published snapshot has a completeness record** (`completeness.json`): per table whether it was there,
   its rows, its live rows, its rejects and its unknown codes, and the reference counts the next night is held
   to. Its `first_load` entry says which years the publish held.
3. **The unknown codes are counted as a night counts them**: `unmapped_codes.json` in the snapshot (codes and
   counts only, by the mapper's own rule for what looks like a code), the rows per table in the load's report
   (`unmapped`) and a line in the log.
4. **The facts are kept with the spool** (`spool/done.json`), so a load started again says the same without
   reading the source again. A spool written before this card has none: nothing is asked of it and no record is
   written (the load goes on as before).

## Consequences

- A first load of a feed that lacks a table of the mapping is held where it published before. The site lists the
  table under `feed_completeness.optional_tables`, or supplies it.
- The night after a first load is held to the load's row counts (the drop limit), not only to "there and not
  empty".
- **Duplicate source keys are not counted by the first load** (the night counts them in a pass of its own over
  the keys): the record says `duplicates_counted: false`, and its `duplicate_keys` of 0 means "not counted".

## Not decided here

- The other checks the back-fill leaves to the nights: the data contracts' row checks, the JP Core profile
  sample, the FHIR store load (its module text lists them).
- Deleted rows: the first load leaves them out and counts them only as the difference of `rows` and `rows_live`.
