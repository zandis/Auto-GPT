# D-472 Lake rebuild and nightly ingest as polled jobs; the site publish records a publish in progress

- **Task:** T-690 (`docs/plan/28-master-plan-v6.md` §6.2.10; `docs/plan/31-master-plan-v6.1-addendum.md` §3.4)
- **PR:** this branch (`agent/T-690-rebuild-ingest-polled-jobs`)
- **Date:** 2026-11-12
- **Status:** proposed
- **Closes:** scale review 2026-11-11 F-01 (the rest D-462 left open) and F-08
- **Builds on:** D-462 (T-722: one lake lock, one rebuild per snapshot, `LakeBusy`), D-403 (T-305b: holds, the
  batched publish), D-271 (refused rebuilds leave `CURRENT` alone), OD-10 (no fixed limit on work that grows with
  the hospital)

## Decision

Work in progress (the draft pull request is the claim). The full text lands with the code.
