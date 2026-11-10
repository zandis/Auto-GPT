# Gate GP-0 PoC build freeze

| Field | Value |
| --- | --- |
| Gate | GP-0 PoC build freeze |
| Source | TB-PLAN-06 §2.1; TB-POC-01 §8.1 |
| Planned | Fri 2026-11-27 |
| Decided by | the owner, the integrator |
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
| 1 | Tag `poc-1` is on master with CI green | the tag exists; the TrialBox CI run on it is green | the tag and its CI run link | open | the integrator | |
| 2 | No open Blocker or Critical finding on the PoC path | count = 0 (the deep review's PoC-path rows and TB-REG-01) | the register condition above, plus the PoC-path filter | open | the integrator | |
| 3 | The image from the tag starts on a clean host with no manual step; both sites answer over HTTPS behind the front door | a clean boot by digest | the deploy log of the tag | open | the integrator | |
| 4 | A sign-in needs the second factor on every route, console and API | a test with TOTP on passes | the test id and CI run (T-505) | open | the integrator | |
| 5 | An upload and a pasted chart are refused in three languages; a planted identifier in feedback is found by the scan | refusal tests pass; the scan reports the plant | the test ids and CI run (T-502) | open | the integrator | |
| 6 | The acknowledgement is shown once per account and stored | a test passes | the test id and CI run (T-506) | open | the integrator | |
| 7 | The feedback control stores an item from every script page; the export uses a tester code and no name | a test passes | the test id and CI run (T-510) | open | the integrator | |
| 8 | Each tester's three accounts exist; the sub-investigator sees only the delegated study | an account check | the account list by role, no names | open | the owner | |
| 9 | At least two scenarios per site are loaded; each script task has its expected result | the dry-run sheet | `docs/poc/` script sheets (T-503, T-504, T-508) | open | the integrator | |
| 10 | The statement and acknowledgement are final in ja and zh-TW after a native read | a signed note per language | `docs/poc/` native-read notes | open | the owner | |
| 11 | The purge script ran once on a planted record; the incident note names the role who is called | a run record | the purge run log and the incident note | open | the owner | |
| 12 | The decision "the PoC is product evaluation, not research" is recorded (Q-07) | a decision file | the decision file under `docs/decisions/` | open | the owner | |

## Notes

No-go on any miss of rows 2 to 6 or 11 (TB-POC-01 §8.1). A miss of row 9 for J1 alone is a go with J3 and J2. Any other miss: the owner decides, and this record says why.
