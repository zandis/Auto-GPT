# Gate GP PoC sessions

| Field | Value |
| --- | --- |
| Gate | GP PoC sessions |
| Source | TB-PLAN-06 §2.1; TB-POC-01 §5, §8.2, §8.3 |
| Planned | Tue 2026-12-08 to Fri 12-11; exit review Mon 12-14 |
| Decided by | the owner, the two tester clinicians |
| Result | open |
| Signer | the owner |
| Date signed | to fill on the day |

## Register condition

Counted on the day of the decision. Code rows and owner or site rows are counted apart (PLAN-040).

| Source | Rows | Open Blocker | Open Critical | Open High | Counted on |
| --- | --- | --- | --- | --- | --- |
| TB-REG-01 | code | to fill on the day | to fill on the day | to fill on the day | to fill on the day |
| TB-REG-01 | owner or site | to fill on the day | to fill on the day | to fill on the day | to fill on the day |
| Deep review 2026-11-10 | code | to fill on the day | to fill on the day | to fill on the day | to fill on the day |
| Deep review 2026-11-10 | owner or site | to fill on the day | to fill on the day | to fill on the day | to fill on the day |

## Criteria

Result is open until the day of the decision. Evidence names where the proof is or will be.

| # | Criterion | Measure | Evidence | Result | Signer | Date |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Both clinicians complete their scripts | sessions A and B held per tester | the session checklists in `docs/poc/` | open | the owner | |
| 2 | Every task is attempted by both testers | tasks attempted / tasks, per tester = 100 % | the session checklists in `docs/poc/` | open | the owner | |
| 3 | At least 80 % of tasks are completed without help | tasks done without help / tasks ≥ 0.80 | the session checklists in `docs/poc/` | open | the owner | |
| 4 | No finding rated "would cause a wrong patient decision" is left without a fix card | count = 0 | `docs/poc/gp-findings.md` | open | the integrator | |
| 5 | Every finding is triaged | untriaged = 0 | `docs/poc/gp-findings.md` | open | the integrator | |
| 6 | No real patient information was entered, or each event was handled under TB-POC-01 §8.2 | the identifier scan of stored input after each session | the scan logs per session | open | the owner | |

## Notes

If the criteria are not met, a second round runs on tag `poc-2` in the week of 2027-01-12 with GP-2. The platform still freezes on 01-08. The go-live dates do not move because of the PoC.
