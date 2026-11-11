# D-451 The audit browser: the privacy office and the steward read the chain, by filter, by patient, with its verification

- **Task:** T-211c (`docs/plan/28-master-plan-v6.md` §6.2, wave 3; part c of TB-ASSESS-01 T-211)
- **PR:** this branch (`agent/T-211c-audit-browser`)
- **Date:** 2026-11-11
- **Status:** proposed
- **Closes:** ROLE-013
- **Builds on:** D-133 (the audit trail page by page), D-272 (no chart number in clear; the head anchor), D-355
  (signed heads and off-box anchors), D-380 (the privacy office role; `audit.ids`), D-394 (one audit writer), D-425
  (every call site asks `permit`), D-430 (break-glass uses), D-438 (one reveal path and its record shape, PR #259)

## Context

`/audit` was open to every signed-in role the scope guard did not block: the administrator, a coordinator and an
investigator read the whole site's events (every sign-in, reveal, refusal and export). It showed the newest 1,000
events only, with no filter by patient, person, event or date, no "who saw which chart" report, no chain
verification and no file; the event names were raw codes in every language (ROLE-013).

## Decision

1. **Who.** One matrix row, `audit.browse`: the privacy office and the steward. Everyone else gets 403 and a
   `console.denied` event on every audit route (page, per-patient report, its file, verification). The menu and the
   administrator's links to the audit trail ask the same row. A job page keeps its own job's events (unchanged).
2. **Filters in the reader, never in the page.** The browser reads the chain's day files (the audit volume, read-only
   for the console since D-394) newest first through `console.audit_page.search`: a day file outside the period is not
   opened, a line that cannot match is skipped before it is parsed, and the read stops at one page plus one event.
   The next page is a cursor (day file and line), not a page number, so there is no 1,000-event horizon. Filters:
   kind (reveals, break-glass, exports and downloads, sign-in, refusals, audit reading), event, person, pseudonym,
   job, from and to (dates of the site's zone).
3. **One patient in two steps.** Step one: the pseudonym in the browser's patient box. Step two: the report
   `/audit/patients/{pid}` lists every event of the chain that names it (any field but the hashes), newest first, with
   counts per kind: reveals and their refusals, break-glass uses, exports and downloads. It shows what the events hold
   (study, purpose, reason, basis, cap, via, role) and joins in nothing: no name, no chart number. A chart-number
   lookup is not offered here (it would be a reveal; it would go through `Reveal.identifier`, D-438).
4. **The file.** `/audit/patients/{pid}.csv` is the same report through the same guard, with the same filter, written
   as it is read; a cell that a spreadsheet would run as a formula is quoted.
5. **Reading is audited.** One `console.audit_search` per browser page and one `console.audit_report` per report or
   file (with `format`), each with the filter (pseudonym, kind, event, person, dates), never the result.
6. **Verify.** "Verify the chain" calls the existing verification (`tb_common.audit.verify`, as
   `tools/audit_verify.py --heads` does) with the signed heads of every off-box anchor folder
   (`TB_AUDIT_ANCHOR_TARGETS`) and shows the chain state (PASS or FAIL, events, files, the head hash, the first
   problems), the last signed head (time, event, key) and, per anchor folder, its newest head. The browser does not
   re-implement the check. One `console.audit_verify` event records the result.
7. **Labels.** Every event name the code writes has a label in en, ja and zh-TW (`console.i18n_audit.EVENTS`); a test
   walks the code for event literals and fails on a name without one. The detail keys the browser shows are labelled
   too; values stay as written.

## Not decided here

- An `/api/v1` twin of the browser (T-657 decides which page routes need one).
- Translating the detail values (purpose and reason codes, refusal reasons): they are shown as written.
- The administrator's view of operational events (TB-ASSESS-01 T-211 "admin for the operational classes"): the
  event classes of T-211 are not built; until they are, the administrator reads none.
