# D-486 Owner, writer and reader roles per schema, the EDC schema first: no service role owns a trail table, and migrations of such a schema run as an install step

- **Card:** T-718 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.2, TB-PLAN-06.1; wave T, safety core)
- **PR:** this branch (`agent/T-718-schema-owner-writer-reader`); built on T-712's branch (PR #308): it shows its
  commits until it merges
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-378 (one database role per service), D-461 (the EDC schema is the orchestrator's alone), D-481
  (a service holds its own role's password only)
- **Closes:** finding F4 of `docs/reviews/2026-11-12-architecture/trust.md` for the schema `edc`, and proposal TR-6
  for that schema (see "Not done" for the others)

## The problem

Every service role that reads or writes a schema is a member of the group that owns it (`tbs_<schema>`, D-378), and
`tb_common.db` sets the role to that group on connect. So every writer is an owner: the triggers that make the EDC
trail tables append-only are made at service start by the orchestrator's own role, and the same role can drop
them, disable them, alter the table or truncate it. The stores are append-only against their own code, not
against their writers.

## The decision

(filled in with the build; see the pull request)
