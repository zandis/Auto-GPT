# D-720 The drill's role check runs each service's real write paths

- **Task:** ROLE-PATHS (the nightly of 2026-11-13; lane E's two findings, through the integrator)
- **PR:** this branch (`agent/ROLE-PATHS-the-drill-runs-the-real-write-paths`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-573 (after a restore every service opens its stores as its own role), D-378 (one role per service), D-486 (owned schemas)

## Context

The backup drill's role check (D-573) said "7 service roles, 70 stores opened as their groups" on a box where the
opt-out worker failed at every tick and no role could load the OMOP store. The check opens each store with DDL of
its own; it never ran a line of a service's code under the role script.

## Decision

(written when the card is built)
