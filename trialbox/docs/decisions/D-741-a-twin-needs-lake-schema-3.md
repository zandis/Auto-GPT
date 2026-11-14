# D-741 A twin is read only from a snapshot of lake schema 3 or later, and says so

- **Task:** NEW-B-40 (from NEW-B-35's review; placed by the integrator on 2026-11-13)
- **PR:** this branch (`agent/NEW-B-40-twin-needs-schema-3`), on top of NEW-B-35 (#563, which carries #549)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** D-676 (the twin's reader asks the lake for the layout), T-106b (lake schema 3: the encounter's
  status and each row's provenance), D-491 (the night step and the generation ledger)

## Context

The lake still reads snapshots of lake schemas 1 to 4 (`MIN_READABLE_SCHEMA`). The twin's reader asks for the
encounter's `status` and for each row's provenance, both of which came with schema 3. On a snapshot that schema 1
or 2 built, the encounter query failed with the engine's sentence (a 422), so no twin was built. The reader's
"schema 1: rows without provenance" branch therefore answered but never ended in a twin.

**No site is live: no box holds a snapshot of an old layout.** This card makes the rule plain before one could.

## Decision

1. **The reader refuses a snapshot older than lake schema 3** (`TWIN_MIN_SCHEMA`) before any row is asked for:
   `TwinError` "lake snapshot <date> has lake schema <n>; a twin needs schema 3 or later (the encounter's status
   and each row's provenance came with it): rebuild the snapshot from its NDJSON (the lake's rebuild) before twins
   are built from it".
2. **The dead branch goes**: the rows are always asked for with their provenance columns.
3. **The night step says why**: `twin.after_ingest` logs the reader's own sentence whole (a snapshot's name and a
   layout number, never a patient) where it logged only the error's type; it never fails the ingest, keeps no
   twin, and the night's "twin" entry in the generation ledger stays "building".

## What this does not do

- **The generation ledger has no field for a reason**: it shows "building", not why. A column for it is a
  migration of its own; the reason is in the log.
- The lake itself keeps serving schemas 1 and 2 to every other reader.
- The floor is a version check. `observation.value_cmp` came without a schema bump (D-142, B-01, before T-106b's
  schema 3 by the decisions' order, inferred): a file without it passes the floor and fails at the observation query
  with the engine's sentence (the review reproduced it on an altered file).
- A refused night leaves the console's twin page on the last twin built (or "not found"), as any night whose twins
  were not built does.

## Tests

In `tests/unit/test_twin_lake_failure.py` (4 new tests fail on the parent; a fifth, after the review, pins the floor
from above: a schema-3 file is read): a real lake file made to say schema 1
(no version column) and schema 2, through the service and in process: refused with the sentence; the reader asks
only the layout before it refuses; the night step logs the sentence and keeps no twin. **One existing test of
NEW-B-35's changed its expectation**: it read a schema-1 file's rows without provenance; that is the behaviour this
card removes, and the new test above replaces it. No state change.

## Review

One adversarial, read-only review by a fresh agent, by running (altered real lake files of schemas 1 to 4, through
the service and in process; mutants of the floor). It found no defect in the change. It verified: every column the
twin asks for exists from schema 3 on (the compat view gives `patient.deceased` below 4); a schema-4 file is read;
the refusal's text holds a snapshot's name and a number only and goes to the log alone; nothing catches the error
into a wrong answer. Its findings, taken: nothing pinned the floor from above (a reader refusing schema 3 passed: a
test now reads a schema-3 file); `value_cmp` and the console's twin page are said above; D-676 still described the
test this card replaced (corrected).
