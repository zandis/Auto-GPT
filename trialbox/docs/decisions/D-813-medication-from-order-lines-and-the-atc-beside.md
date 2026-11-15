# D-813 Medication from order lines; the mapped ATC beside the hospital's; a class-level ATC as a class only

- **Task:** CGRD-A2 (from the first look at a real source; facts kept off the repository). Refines D-689; the owner's
  integrator agreed both refinements.
- **PR:** this branch (`agent/CGRD-A2-medication-from-order-lines`), cut from CGRD-A1 (#707)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)

## Decision

1. **`tables.<t>.rows: {column, in | not_in}`**: one source of order lines feeds two tables (drug lines, procedure
   lines), each keeping its own kind. Rows of the other kind are counted (`rows_of_other_tables`), never lost.
2. **`beside: <hospital ATC column>`** on a mapped ATC: written beside the hospital's own, not only where it is empty.
   Two ATC codes of one drug that disagree (neither begins the other) leave the drug unknown: both move to
   `urn:trialbox:atc-disputed`, which no ATC reader reads, counted (`atc_disputed`). Never the code that happens to match.
3. **`class_target: atc4`**: a map answer that is a level-4 class is written under `urn:trialbox:atc-class`, never
   the ATC system: a level-5 criterion still reads the row as unknown; a level-4 criterion may read the class
   (lane A2 honours the system name in the coverage rule).
4. Without these keys, D-689 is unchanged.
