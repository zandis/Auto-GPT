# PoC protocol: the clinician proof of concept, step 1

| Field | Value |
| --- | --- |
| Version | 1.0, 2026-11-10, card T-508 |
| Design | `docs/plan/27-poc-plan.md` (TB-POC-01); gate GP of `docs/plan/28-master-plan-v6.md`, as changed by D-311 |
| Status of the PoC | product evaluation, not research (D-332) |
| Contact | the project owner |

This is the procedure for step 1 of the PoC: the hands-on sessions on the hosted demo. It turns the design of
TB-POC-01 into what is done, by whom, in what order. Where this file and the design differ, the design as changed by
D-311 wins, and this file is corrected.

## 1. Purpose

Two site clinicians, one per site, work the screening flow of their own kind of trial in their own language, on
synthetic patients, and say what is wrong, confusing or missing. The findings reach the design freeze (G2).

The PoC shows: whether a PI, a sub-investigator and a CRC can do a clinic day's screening work in the console;
whether the Japanese and Traditional Chinese wording reads as a clinician expects; whether the screens show what is
needed to trust or reject a criterion result; which steps are missing for each site's trial type.

It does not show how well real models read real notes. Step 1 uses a test model with fixed answers, and every page
says so where a result comes from it. Real note reading is step 2 (GP-2).

## 2. People

| Role | Who | Does |
| --- | --- | --- |
| Tester T1 | the Japan site clinician | the Japan scripts in Japanese |
| Tester T2 | the Taiwan site clinician | the Taiwan scripts in Traditional Chinese |
| Facilitator | the project owner, or a person he names | runs the sessions, watches, does not help unless asked, fills the session record |
| Operator | the project owner, or a person he names | hosts the demo, issues accounts, runs the scan after each session, destroys the host at the end |
| Integrator | the integrator session | turns findings into cards on the owner's word |

Testers are named only outside the repository. In the repository they are T1 and T2.

## 3. Environment

The `demo/` image built from tag `poc-1`, run by digest on one cloud VM behind HTTPS and an identity front door (card
T-509). Two demo sites: `jp` (Asia/Tokyo, Japanese notes, scenarios J1 and J2) and `tw` (Asia/Taipei, Traditional
Chinese and English notes, scenarios T1, T2 and T3). Demo mode on (D-328): uploads and pasted chart text refused,
the banner on every page, the acknowledgement at the first sign-in. Per-tester accounts with the second factor
(T-505a, T-505b). Kept data (`TB_DEMO_KEEP=1`). Test model only.

| Site | Studies | What each shows |
| --- | --- | --- |
| `jp` | AD-MAB (J1) | an early Alzheimer's disease sponsor trial: note-based criteria in Japanese, many honest "unknown" answers (amyloid status) |
| `jp` | NEUR-COH (J2) | a registry: a cohort list with no contact step |
| `tw` | RA-JAK (T2) | a rheumatoid arthritis JAK inhibitor sponsor trial: a derived score, infection screening |
| `tw` | GZQO (T1) | a sponsor trial amendment: what the PI sees and approves |
| `tw` | GOUT-COH (T3) | an investigator-initiated registry: EDC prefill to REDCap with a signature |

## 4. Procedure

| Step | When | Who | What | Done when |
| --- | --- | --- | --- | --- |
| 1 | before the freeze | operator | seed both sites; write the scan baseline; issue accounts out of band; send the statement, the notice and the guide ([session-checklist.md](session-checklist.md)) | the checklist's first part is ticked |
| 2 | before the sessions | owner | the dry run: walk both scripts (GP-1, D-311 S2). Until the tag exists, `tests/integration/test_poc_scripts.py` walks every English task on master | every task completes, or is struck from the script with a note |
| 3 | optional, the week before | owner, each tester | a guided first look, 30 minutes, the owner drives | notes |
| 4 | session A, about 80 minutes | tester, facilitator | the PI tasks, then the sub-investigator tasks of the tester's script | the session record |
| 5 | session B, about 80 minutes | tester, facilitator | the CRC tasks, the questionnaire, the debrief ([forms.md](forms.md)) | the session record, the questionnaire, the debrief notes |
| 6 | after each session | operator, facilitator | the stored-input scan against the baseline; the finding forms | the checklist's after-session part is ticked |
| 7 | exit review | owner, integrator | triage every finding ([severity.md](severity.md)); write gp-findings.md (this folder) | one triaged findings list (D-311 S4) |
| 8 | within a week | owner | reply to the testers | sent |
| 9 | after the reply | operator | destroy the host, delete snapshots and recordings; delete accounts and logs within 90 days | a record of the deletion |

Each tester has the two sessions on a video call. The tester may also use the demo alone between sessions; findings
from free use go on a finding form with the task "free use".

## 5. The scripts

One script per site, in English and in the site's language, with ten tasks for each role:

| Site | English | Site language |
| --- | --- | --- |
| Japan | [scripts/jp.en.md](scripts/jp.en.md) | [scripts/jp.ja.md](scripts/jp.ja.md) |
| Taiwan | [scripts/tw.en.md](scripts/tw.en.md) | [scripts/tw.zh-TW.md](scripts/tw.zh-TW.md) |

The tasks and the expected results were written from the console on master and are checked by
`tests/integration/test_poc_scripts.py`, which walks every English task in process with the tester's own accounts
(second factor, forced password change, acknowledgement, delegation log) and fails if a task in a script has no step
or the console gives another result. A task marked "known gap" names what the console does not do yet and the card
that adds it. The scripts differ from the draft tasks of TB-POC-01 §5 where the console differs; the test is the
authority.

## 6. Rules during the sessions

1. Synthetic data only. If a tester enters or describes real patient information: stop the session, purge, record
   the event without the content, tell the tester what was done; the tester follows the hospital's own rule.
2. Nothing is fixed live. A defect is logged and the session goes on with the next task.
3. The facilitator does not explain a screen unless asked; each request for help is a finding.
4. If the demo is down for more than 15 minutes, the session is rebooked.
5. Recording only if the tester agreed in the acknowledgement and agrees again that day.

## 7. Feedback and findings

In the session: the session record and the finding forms ([forms.md](forms.md)). In the product: "Feedback on this page"
on every page (T-510, D-331): a flag, a rating and a comment, stored with the page, language, role and time; the
owner exports them as CSV (`/feedback/export.csv`) for the exit review. After session B: the ten-item
usability questionnaire and five open questions. Each finding carries the tester's rating and, at the exit review,
the triage severity and outcome ([severity.md](severity.md)). Findings carry tester codes, never names.

## 8. Exit

GP exits with one triaged findings list (D-311 S4): every task attempted, every finding triaged, and every finding a
tester rated "would cause a wrong patient decision" turned into a card. There is no completion-rate threshold. If the
owner wants a second round, it runs on a new tag with step 2.

## 9. What the testers sign

Only the acknowledgement on screen, once per account (D-328, D-332). The statement and the notice are given, not
signed: [data-handling.en.md](data-handling.en.md) ([ja](data-handling.ja.md), [zh-TW](data-handling.zh-TW.md)),
[testers-data.md](testers-data.md).

## 10. Contact

The project owner, by the mail address given with the accounts. It is the one contact for testers, for an incident
and for a request about a tester's own data.
