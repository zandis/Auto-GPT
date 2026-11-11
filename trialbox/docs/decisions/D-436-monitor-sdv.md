# D-436 The monitor's source-data verification page: enrolled subjects only, the cited record items only

- **Task:** T-303 (`docs/plan/28-master-plan-v6.md` §6.2; TB-ASSESS-01 T-303, WS-07.6)
- **PR:** this branch (`agent/T-303-monitor-sdv`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-147 (the delegation log is the one permission function), D-160 (EDC drafts: every value cites
  its source), D-273 (an opted-out patient is on no page), D-280 (the administrator reads no patient), D-302 and
  D-425 (the permission matrix, `permit`), D-380 (T-102b: the monitor grant, `monitor.grant` and `monitor.read`)
- **Closes:** FIT-002 (page half; the grant half is D-380), ROLE-012, LIFE-026

## Context

D-380 gave a CRO account a monitor grant per study for the visit dates, and one route,
`/studies/{rs}/monitor/{record}`, that opened an enrolled subject read-only. A journey test (T-315a, J-MON-03)
found that the route refused every enrolled subject: the data core answers `GET /studies/{rs}/subjects/{record}`
with `{"study", "today", "subject": {...}, "steps", "visits", ...}`, and the console handed the whole reply to
`monitor_may_see`, which looks for `state` at the top. The unit test passed only because its fake core answered a
flat subject. Beyond the bug, the page showed every scalar of the reply and nothing a monitor verifies: which source
item each CRF value came from.

The owner's rule (2026-11-10): "SDV access to enrolled subjects only, limited to the cited record items".

## Decision

1. **The console reads the data core's real reply.** The monitor's subject is `reply["subject"]`; the check
   (`monitor_may_see`) and the page read that dict. The tests' fake core answers in the real shape, and one test
   runs the page on the real orchestrator routers (data core, lifecycle, EDC) on the test's own database.
2. **The monitor's pages live in `console/sdv_page.py`** (moved from `team.py`, which keeps the grant itself):
   - `/studies/{rs}/monitor` (and `GET /api/v1/studies/{rs}/monitor`): the study's enrolled subjects (the states of
     `MONITOR_STATES`, or withdrawn after an enrolment), by screening number, state and enrolment date; and the
     study's monitoring-visit records. A monitor under a grant sees both; the PI the log names and the steward (who
     may give a grant, `monitor.grant`) see the visit records only.
   - `/studies/{rs}/monitor/{record}` (and its `/api/v1` twin): the source-reference sheet of one enrolled subject.
     Its subject facts (state, dates, consent; never the pseudonym), then **per CRF value a person decided**
     (confirmed or edited, not superseded): the item, visit, value, whether it is signed, and the **citation the EDC
     draft holds** (kind, table, row, snapshot, day, text and, for a note, the verbatim quote). Then the value's
     trail: each decision (old, new, reason, who, when) and each signature (printed name, role, meaning, when,
     intact). Nothing else of the patient's record: no open draft, no draft's pseudonym, no twin
     (`patient_profile`), no narrative, no neighbours, no lake row beyond the cited one. The page prints as the
     per-subject "source references" sheet (navigation and forms do not print).
   - `POST /studies/{rs}/monitor/visits` (and `POST /api/v1/studies/{rs}/monitor/visits`, session and right
     checked before the body is read): the monitoring-visit record: the visit date, the CRA (the signed-in account,
     never typed), the monitoring-visit id the grant names, the subjects verified (each must be an enrolled subject of
     this study the monitor may open) and the findings (free text, at most 2,000 characters). Kept in
     `team.monitor_visits` (team version 3), append-only by code; record inventory R-04 beside the delegation log.
3. **Rights are matrix rows.** `monitor.read` (existing: a CRO account under a grant) for every read; new
   `monitor.visit` (a CRO account under a grant) for the visit record; `monitor.grant` (existing) also reads the
   visit records. No inline role check.
4. **Every read is audited with the visit.** `console.monitor_view` per subject sheet (record, visit, state, the
   number of cited items shown), per list read (`record` `*`); `console.monitor_visit` per visit record;
   `console.denied` with `why` `not_enrolled` or `opted_out` for a refusal. An opted-out patient is never listed and
   their sheet is 404 (who opted out is private, D-273).
5. **No chart number for the monitor.** The pages show screening numbers and cited items. A monitor's request for
   a chart number (the candidate reveal, the referral print reveal) is refused (403) and audited by the CRO scope
   check; there is no site SDV rule that opens one in this decision. Any later chart-number need calls the one reveal
   function (`Reveal.identifier`, T-103), never a second path.

## Not in this decision

- A site rule that lets the monitor see a chart number with step-up (TB-ASSESS-01 "unless the site's SDV rule says
  so"): no site has asked; it would go through `Reveal.identifier` (T-103) once that is on master.
- A PDF of the sheet: the browser prints the page.
- Editing or withdrawing a visit record: a correction is a new record.
