# The PoC pack

Everything needed to run step 1 of the clinician proof of concept (`docs/plan/27-poc-plan.md`, gate GP of
`docs/plan/28-master-plan-v6.md`). Card T-508, version 1.0, 2026-11-10. Synthetic data only.

## Contents

| Part | File | For |
| --- | --- | --- |
| Protocol | [protocol.md](protocol.md) | the owner, the facilitator, the operator |
| Scripts, Japan site (ten tasks per role: PI, sub-investigator, CRC) | [scripts/jp.en.md](scripts/jp.en.md), [scripts/jp.ja.md](scripts/jp.ja.md) | tester T1, the facilitator |
| Scripts, Taiwan site (ten tasks per role) | [scripts/tw.en.md](scripts/tw.en.md), [scripts/tw.zh-TW.md](scripts/tw.zh-TW.md) | tester T2, the facilitator |
| Forms: session record, finding form, questionnaire, debrief | [forms.md](forms.md) | the facilitator, the testers |
| Severity scale | [severity.md](severity.md) | the facilitator, the exit review |
| Data-handling statement and acknowledgement | [data-handling.en.md](data-handling.en.md), [data-handling.ja.md](data-handling.ja.md), [data-handling.zh-TW.md](data-handling.zh-TW.md) | the testers, before the first sign-in |
| The "not research" decision | [D-332](../decisions/D-332-poc-not-research.md) | everyone |
| Notice on the testers' own data | [testers-data.md](testers-data.md) (en, ja, zh-TW) | the testers |
| Session checklist | [session-checklist.md](session-checklist.md) | the facilitator, the operator |
| Two-page tester guide | [guide.en.md](guide.en.md), [guide.ja.md](guide.ja.md), [guide.zh-TW.md](guide.zh-TW.md) | the testers |
| The dry run, as a test | `tests/integration/test_poc_scripts.py` | the integrator, CI |

The scripts in Japanese and Traditional Chinese have the same task ids as the English ones; a test checks that each
script has ten tasks per role in both languages. The triaged findings will be gp-findings.md in this folder, written at
the exit review.

## How the scripts are kept true

`tests/integration/test_poc_scripts.py` builds both demo sites in process from the synthetic hospitals of T-503 and
T-504, seeds them as the operator does, switches demo mode on (D-328), issues each tester's accounts as the PoC host
does (T-505b), and walks every task of the English scripts in order with those accounts: first sign-in with the
second factor, the forced password change, the acknowledgement, then each task and its expected result. A task in a
script without a step in the test, a step without a task, or a different result on the console fails it. The
acceptance "an internal dry run completes every task on tag `poc-1`" waits for the tag; until then this test is the
dry run on master.

## Contact

The project owner, by the mail address given with the testers' accounts. This is the one contact line of the pack:
for testers, for an incident and for a request about a tester's own data. No person's name or address is written in
the repository.

## Dropped (D-311)

These items of the original design are struck by the owner's rule of 2026-11-10 (`docs/decisions/D-311-no-development-gates.md`)
and are not in this pack:

| Item | Was | Now |
| --- | --- | --- |
| Native-reader sign-off (D-311 B12) | the Japanese and Traditional Chinese scripts, wording and statement signed by a native clinician before use (TB-POC-01 §5.3, §8 step 5, §8.1 item 10; card T-508 acceptance) | no signature; a wording fault is a PoC finding ([severity.md](severity.md) rule 3) |
| Counsel reads the statement (D-311 B13) | counsel reads the data-handling statement once | the statement is a draft by the plan's authors, not legal advice |
| Committee or ethics step | ask the ethics committee whether review is needed before publishing (statement point 9, TB-POC-01 §11 item 6) | no committee or ethics step; the testers are asked first (D-332) |
| Conflict-of-interest file (D-311 B8) | a pilot-site investigator's part recorded in the study's conflict-of-interest file (statement point 10) | struck from the statement |
| Signed paper acknowledgement (D-311 S3) | a signed page kept beside the on-screen acknowledgement | the on-screen acknowledgement only (`demo.ack`, D-328) |
| GP gate record and 80 % rule (D-311 S1, S2, S4) | a GP record with a signer; at least 80 % of tasks completed without help | one triaged findings list; the dry run is the automated walk plus the owner's 30 minutes |
