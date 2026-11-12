# D-580 A code the look-up does not know is counted every night, and the look-up key is read without its blanks, case and width

- **Task:** NEW-DIN-6 (finding DIN-006 of the deep review of 2026-11-12, `docs/reviews/2026-11-12-deep-review/08-data-input.md`; plan v7.2 section 5, lane E, wave 0)
- **PR:** this branch (`agent/NEW-DIN-6-unmapped-codes-counted`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-130 (no value is unknown, never "not met"), D-275 (a code the map does not know is never the
  default), T-611 (the night's completeness record), T-112a (the night's batch row keeps tables and counts, never a
  row)

## Context

A CSV or SQL feed maps a local code (a lab's own analyte code) to a standard code through a look-up table. A row
whose code the table does not hold is dropped by the resource's `where`. Nothing counted it: the night's report
showed the results that were made, never the ones that were not. The look-up was exact, so `" CRE "` (a fixed-width
column) and `cre` did not match `CRE`: every result of that analyte was gone each night and its criteria read "no
data" for every patient, with nothing to see.

## Decision

1. **The look-up key is read as a person reads it.** A key is looked up as written first. When that finds nothing it
   is looked up again with blanks around it removed, full-width letters and digits made half-width and case lowered.
   Nothing else is folded: not Unicode NFKC (`㎎` is not `MG`, `①` is not `1`), not `ß` to `SS`. That second reading
   counts only when exactly one row of the table has that folded key; two rows that differ only by case, width or
   blanks are two codes of the site and neither is matched by folding.
2. **Every row dropped for an unknown code is counted**, per source table, per look-up and per code, on every night
   of the nightly pipeline (CSV, SQL and SS-MIX2 sources). The counts are in the night's `completeness.json` (per
   table: rows dropped and distinct values), in the file `unmapped_codes.json` beside it (every code with its count,
   the largest first) and in the night's audit event and batch row (per table: rows dropped). The log names the
   table and the two numbers, never a code.
3. **Only a code is written out.** A value is written into `unmapped_codes.json` only when it looks like a code:
   printable ASCII with no blank inside, at most 40 characters (the longest code a look-up is keyed by, JLAC10, has
   17), and not a value that matches the site's chart-number pattern (`mrn_regex`). Anything else (a name, a chart
   number, a sentence that a mis-mapped column put where the code belongs) is counted under `(not a code)`; an
   empty code under `(no code)`. A site whose local lab codes have the same shape as its chart numbers sees them
   under `(not a code)`: the count is kept, the spelling is not.
4. **An unknown code does not hold the night.** A site's lab has codes no study needs. The count is there to be read
   by the person who owns the mapping; `tools/mapping_check.py` reads the look-up the same way.
5. **No list is cut.** Every code is in the file (OD-10: no limit cuts a result silently).

## The risk that stays, said plainly

Lowering case means a look-up that holds only `Na` answers a feed code `NA`. The deep review asked for it
(DIN-006: "strip and case-fold the key"), because the opposite fault is the common one (a HIS that lower-cases or
pads its codes loses the whole analyte). The guard is the look-up itself: a site whose codes differ only by case
has both rows in its look-up, and then neither is matched by folding. `mapping_check` lists what was matched.

## Not in this card

- The data-operations page showing the largest counts (the console is lane C's): sent to the integrator as a finding.
- The first-load path (`services/adapter/backfill.py`, lane B's) maps through the same mapper and does not report
  the counts yet: sent to the integrator as a finding.
- A hold when a mapped code's nightly count falls to zero: it needs a per-code baseline of the last good night and a
  rule for delta nights; it is not built here and has no card yet.

## Consequences

- A site whose HIS pads or lower-cases its codes loads its results without a mapping change: on a full night at
  once, on delta nights only for rows that change (rows dropped before this card come back with the next full load).
- A code written with other blanks or case in the feed than in the look-up now gives a record where it gave none. No
  shipped or synthetic feed has such a code, so no golden moves.
