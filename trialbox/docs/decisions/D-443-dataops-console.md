# D-443 Data operations, second half: the steward's `/data-ops` page, `/api/v1/data/*`, and the feed on the readiness page

- **Task:** T-112b (`docs/plan/28-master-plan-v6.md` §6.2.5, wave 2; as TB-ASSESS-01 T-112, second half)
- **PR:** this branch (`agent/T-112b-dataops-console`)
- **Date:** 2026-11-11
- **Status:** proposed (in review)
- **Closes:** CR-067 (console half), FIT-017 (console half: "no data-operations console, no held-batch accept/reject"),
  ROLE-022 (ingest history: the steward's list of every night)
- **Builds on:** D-427 (the `dataops` schema and batch states), D-149 (a held night keeps `CURRENT`), T-611 / D-312
  (the held marker on the readiness page), D-380 (the steward role), D-425 (every call site asks `permit`), D-426
  (the steward's conflicts page, the pattern this page follows)

## Context

T-112a (D-427) gave every ingest night a `dataops.batch` row and a state, and a `decide` that alone leaves `HELD`.
Nobody could see the rows or decide a night: the readiness page read the held night from the audit chain's day
files, and the steward had no list of nights (ROLE-022: "Ingest synthetic site A" is a button with no history).

## Decision

To be completed in this pull request.
