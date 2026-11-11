# D-390 Operations documents: support, recovery, keys, patches, leavers, and the team's own document

- **Task:** T-635, operations documents (`docs/plan/28-master-plan-v6.md` §6.2, row T-635)
- **PR:** this branch (`agent/T-635-operations-docs`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** OPS-038, OPS-039, OPS-044, OPS-074, OPS-073 (by an index, see 4); the support part of CR-096
- **Not here:** the incident plan (severity scale, roles, notification clocks, the six cases) is T-318;
  decommissioning is T-628 (RUNBOOK §20); the measured RPO and RTO are T-213b

## Context

The operations review (TB-DR-09) found no support model, no written fallback for remote help, no list of what to
revoke outside a lost box, no patch split in the RUNBOOK, no leaver steps, and no page for eight common events
(OPS-074). RPO 24 hours and RTO 4 hours were written as "measured in the restore drill"; no such measurement exists.
The RUNBOOK mixed the site's procedures with the team's (OPS-073). Four owner questions decide parts of this
(TB-DR-09 §6, Q1 host system, Q2 remote support, Q5 spare hardware, Q6 first-line names); none is answered on master.

## Decision

1. **Five sections on their reserved numbers.** §21 support model and the supervised remote session, §22 disaster
   recovery, §23 key inventory and the lost-box list, §24 patch policy, §25 leavers.
2. **The missing pages are parts, not new numbers.** The morning mail did not arrive, disk full and GPU fault are
   parts of §4; certificate renewal of §12; a planned power cut, moving the box and replacing hardware of §22. A
   leaver is §25. No new section number was needed.
3. **Every page names its drill** in one line that starts `**Drill (T-213b):**` and names `test_runbook_<n>_<what>`,
   the test T-213b writes. `tests/unit/test_operations_docs.py` checks each T-635 page has exactly one, that the names are unique,
   and that both tabletop records list every one.
4. **The team's document.** `docs/DEVELOPING.md` is the ninth document (`tools/doclint.py` set). It indexes the
   RUNBOOK sections whose audience is `team` and holds the checks before a push. The team sections keep their
   numbers and files, because other documents and the plan link them by number; moving them would break those links
   for no gain to a site.
5. **No measured number is claimed.** §22 states targets (RPO 24 hours, 5 minutes with WAL archiving; RTO 4 hours
   on the same hardware, 5 working days with a loaner) and a "measured" column that says "not measured yet" until
   T-213b fills it.
6. **Defaults until the owner answers**, each marked in the text with its question:
   Q1: bare Ubuntu LTS on the Japan box, Windows with WSL2 only on the hospital's written request.
   Q2: no standing remote access; a hospital-started, hospital-driven screen share for one ticket, no patient page on
   screen, recorded in the ticket.
   Q5: one Aimedics loaner box, hardware RTO 5 working days.
   Q6: tier 2 in both countries is the Aimedics owner of record, no backup named; names never in the repository.
7. **Site documents.** `docs/plan/sites/support-sheet.md` (TB-SITE-08, en, ja, zh-TW) and one tabletop record
   template per site (`tabletop-record-japan.md` TB-SITE-09, `tabletop-record-cgmh.md` TB-SITE-10). A filled record
   names people and stays with the hospital.

## Consequences

- When the owner answers Q1, Q2, Q5 or Q6, the marked lines change; nothing else waits on them.
- A `support.session` audit event, the offline OS patch bundle (T-408) and the unused-account report (T-209) are
  named as not built; the pages say what to do until then.
- T-213b turns each named drill into a test and writes the measured RPO and RTO into §22 and the IT pack.
