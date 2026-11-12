# D-488 The audit says who wrote it: the drain checks each event's name against the database role that sent it, and its time against the journal's

- **Card:** T-721 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.2, TB-PLAN-06.1; wave T, safety core)
- **PR:** this branch (`agent/T-721-audit-says-who-wrote-it`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-394 (one writer of the audit chain; the journal records the database role), D-378 (a role per
  service), D-451 (the audit browser)
- **Closes:** finding F10 and proposal TR-10 of `docs/reviews/2026-11-12-architecture/trust.md`, its first half
  (see "Not done")

## The problem

Every service sends its audit events to the append-only `audit.journal`, which records the database role that sent
each row (`session_user`, which the sender cannot choose). The event's name, its `actor` and its time are the
sender's. The mail gateway's role can append `screen.reveal` with `actor=dr_tanaka` and a time of last week; the
chain line carries `journal.role=tb_mail_gateway`, and nothing reads it: not the drain, not `tools/audit_verify.py`,
not the audit browser.

## The decision

(filled in with the build; see the pull request)
