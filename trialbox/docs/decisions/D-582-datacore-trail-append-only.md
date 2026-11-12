# D-582 The data core's trail is append-only: `history` and `subject_step` take inserts only, a `conflict` row is never deleted

- **Task:** EDC-009 (finding EDC-009 of the deep review of 2026-11-12, `docs/reviews/2026-11-12-deep-review/10-redcap-edc.md`, case 10c; plan v7.2 section 5, lane E, wave 0, and section 3.2: "its trail is made append-only")
- **PR:** this branch (`agent/EDC-009-datacore-trail-append-only`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-281 (the pre-fill's trail tables refuse UPDATE and DELETE by trigger), D-427 (the data-operations
  steps, the same), OD-8 (an enrolled subject's record is kept)

## Context

The data core keeps every change of a value in `history` (old, new, who, when, source), every step of a subject in
`subject_step` and every difference with a source in `conflict`. Any connection of the service could UPDATE or DELETE
those rows (review case 10c: both accepted). The screening log, the lifecycle and the REDCap link all read them.

## Decision

1. `datacore.history` and `datacore.subject_step` refuse UPDATE, DELETE and TRUNCATE by trigger. The code only ever
   inserted into them.
2. `datacore.conflict` refuses DELETE and TRUNCATE. An UPDATE may only close an open conflict: it sets `resolved`,
   `resolved_by` and `resolved_at` on a row whose `resolved` is empty and changes no other column. A closed conflict
   is never changed again.
3. The triggers are made when the store opens, as the pre-fill's are (a plpgsql body cannot go through the migration
   splitter), idempotent and under an advisory lock. They are not a migration, so no stored schema version moves.
4. As in D-281, this holds against every role but a table owner who drops the trigger; the database roles are T-718's.

## Not in this card

- A reason for change on an edit of an existing value in the entry page (the other half of the finding's fix): the
  page is the console's (lane C); sent to the integrator as a finding.
- The data core's standing (a working aid, not an EDC of record) is plan v7.2 section 3.2; wave 8 decides it.

## Consequences

- Nothing in the product deleted or updated these rows, so no path changes. An opt-out keeps them (OD-8, the
  erasure registry's rows for `datacore.history`, `subject_step` and `conflict` are unchanged).
- A restore loads rows by COPY (an insert); the triggers do not fire.
