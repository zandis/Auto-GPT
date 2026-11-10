# Gate record template

Copy this file to `<gate>.md` (for example `G2a.md`). One file per gate. A gate without its record is not passed
(TB-PLAN-06 §2.1). `tools/doclint.py` fails when a gate on its list has no record, or when a criterion row has an
empty evidence cell. Write roles, never personal names or contact details. No patient data.

| Field | Value |
| --- | --- |
| Gate | `<id>` `<name>` |
| Source | TB-PLAN-06 §2.1 (and any other source) |
| Planned | `<date>` |
| Decided by | `<roles>` |
| Result | open / passed / passed with a waiver / failed |
| Signer | `<role>` |
| Date signed | `<date>` |

## Register condition

Counted on the day of the decision. Code rows and owner or site rows are counted apart (PLAN-040).

| Source | Rows | Open Blocker | Open Critical | Open High | Counted on |
| --- | --- | --- | --- | --- | --- |
| TB-REG-01 | code | to fill on the day | to fill on the day | to fill on the day | to fill on the day |
| TB-REG-01 | owner or site | to fill on the day | to fill on the day | to fill on the day | to fill on the day |
| Deep review 2026-11-10 | code | to fill on the day | to fill on the day | to fill on the day | to fill on the day |
| Deep review 2026-11-10 | owner or site | to fill on the day | to fill on the day | to fill on the day | to fill on the day |

## Criteria

Every row needs an evidence cell: a path, a commit, a PR, a tag or a dated reference. "Result" is one of open, met,
missed, waived (with the reason in "Notes").

| # | Criterion | Measure | Evidence | Result | Signer | Date |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `<what must be true>` | `<how it is measured>` | `<where the proof is>` | open | `<role>` | |

## Notes

Waivers, misses and their reasons.

## Gates still to get a record

Each later gate gets its record from this template when its card is opened, and joins the list in
`tools/doclint.py`. What each must add to TB-PLAN-05:

| Gate | Planned | Criteria the record must carry | Finding |
| --- | --- | --- | --- |
| G1b B200 qualified | Fri 2026-12-11 | the `shared-quota` record from the owner's B200 on two MIG layouts, with the host fingerprint; the match with the CGMH layout is checked at G2a | PLAN-026 |
| G2a Platform freeze | Fri 2027-01-08 | every Blocker and Critical code row closed; the commitments register has no red row; PoC findings rated "before G2" closed; the traceability matrix shows status from evidence | PLAN-027, PLAN-040 |
| G2b Site and people freeze | Fri 2027-01-08 | both surveys signed; feed tiers dated with a named hospital owner role; contracts with hospital legal at both sites; the safety-core engineer, the CGMH second reviewer and the deputies named; the conflict-of-interest ruling on file | PLAN-027 |
| GP-2 PoC with real models | Tue 2027-01-12 to Fri 01-22 | only after G1 and G1b; synthetic data; the same front door | |
| G3 Feature complete | Fri 2027-02-26 | 0 open Blocker, Critical or High rows; the backlog prints 0 open cards for G3 | PLAN-040 |
| G4 IQ/OQ per site | CGMH 03-15 to 03-26; Japan 03-22 to 04-09 | as TB-PLAN-05 | |
| G5 PQ / UAT | CGMH 03-29 to 04-23; Japan 04-12 to 05-12 | as TB-PLAN-05 | |
| G6 Readiness review | CGMH 2027-04-23; Japan 2027-05-12 | non-waivable, added: the commitments register green; a named deputy for the steward; the conflict-of-interest ruling; no signer counted twice for two roles | PLAN-029 |
