# PoC scripts: Japan site (English)

| Field | Value |
| --- | --- |
| Site | `jp`: the Japanese memory-clinic demo site (synthetic, Asia/Tokyo) |
| Studies | AD-MAB (early Alzheimer's disease, anti-amyloid antibody, phase 3 sponsor trial, scenario J1); NEUR-COH (MCI and dementia registry, scenario J2) |
| Accounts | your PI account, your sub-investigator account, your CRC account (one each, never shared) |
| Version | 1.0, 2026-11-10, card T-508 |
| Same tasks in | [jp.ja.md](jp.ja.md) (Japanese). The task ids are the same in both files. |
| Checked by | `tests/integration/test_poc_scripts.py` walks every task below on the current master |

How to use it. Do the tasks in order: session A is the PI part and then the sub-investigator part; session B is the
CRC part, then the questionnaire and the debrief ([../forms.md](../forms.md)). After each task, rate how easy it was
(1 to 7) on the session record. "Expected result" is what the screen must show; anything else is a finding. "Known
gap" marks a result the console does not give yet: tell us how much it matters. "Time" is a budget for a first-time
user, not a target.

All patients, names, doctors and numbers on the site are synthetic. Do not type anything from a real patient.

## Session A, part 1: PI

| # | Task | Expected result | Time |
| --- | --- | --- | --- |
| JP-PI-01 | Open the link you were given and pass the front door. Sign in with your PI account and the password you were given. Set up the second factor: add the key shown to your authenticator app, then type the enrolment code and a code from the app. Choose your own password; you are signed out, so sign in again with it and a new code. Read and accept the acknowledgement. | The console asks for a new password before anything else. After the second sign-in: "Before you start: the acknowledgement", five statements and two optional ones; "I accept" works only with the five ticked. Then "This week's patients · AD-MAB". A banner on every page: synthetic data only, not for clinical use, not a medical device. | 8 min |
| JP-PI-02 | Under "Clinic, next 2 weeks", open the first patient. | The patient sheet: "Why this patient fits", "Still open", "Needs you", "To do", the link "Ask treating doctor" and the mark bar ("Approach", "Need info", "Not suitable now"). | 3 min |
| JP-PI-03 | On the same patient, go to "Every criterion with its evidence". Find the MMSE row, the anticoagulant row, the eGFR row and the amyloid row. | Each row shows type, result, evidence and source. MMSE: "test model", "unknown", "the notes do not say". Anticoagulant: "present" or "not present", from "coded records". eGFR: a result from "coded records", or "unknown" with the reason (for example "the score cannot be computed: an input is missing at that visit"). Amyloid: "unknown". The patient stays on the list and is not on "Criteria not matched". Known gap: a coded row does not yet show its value, unit, date and code (T-514). | 8 min |
| JP-PI-04 | Open the registry NEUR-COH and its "Cohort list". | "NEUR-COH · Cohort list" with the new members. The page says there is no contact step; there is no mark bar. | 3 min |
| JP-PI-05 | Back on AD-MAB, open the second patient of the clinic list. Type a note for the coordinator and press "Need info". | "Sent to the coordinator's task list." with "Undo". The coordinator sees the task with your note (JP-CRC-02). | 2 min |
| JP-PI-06 | Open the third patient. Press "Not suitable now" with no reason. Then choose a reason and press it again. Then press "Undo". | Without a reason: refused ("Choose a reason first."). With a reason: accepted, with "Undo". After "Undo" the patient has no "Not suitable now" mark. | 3 min |
| JP-PI-07 | Open the first patient again and press "Approach". | Before you press: "Check before approaching: marking Approach now is recorded as an override with your name" (no IRB approval date, no consent-form version yet). After: "Approved. The coordinator has a task to contact this patient." The patient has a screening number (AD-MAB-0001 or the next free one); "Screening log" lists it with "Approach despite IRB warning". | 3 min |
| JP-PI-08 | Open the fourth patient. Press "Ask treating doctor" and send the request to the doctor the data suggests. | The "Referrals" page: "Referral requested. It is on the screening log." and "Waiting for the doctor 1". Back on the patient: "Approach waits for the treating doctor"; there is no "Approach" button. | 4 min |
| JP-PI-09 | Open "Criteria not matched". Pick one patient, read why, type what looks wrong and press "This is wrong, send to review". | Each row shows the criterion, where the answer came from and the evidence. After sending: "Sent to review. It is recorded with your name". | 6 min |
| JP-PI-10 | On the approached patient (JP-PI-07), under "Chart number", choose why you need it and press "Show chart number". | The synthetic chart number is shown once; open the page again and it is gone. The view is recorded with your account and the reason. | 2 min |

## Session A, part 2: sub-investigator

| # | Task | Expected result | Time |
| --- | --- | --- | --- |
| JP-SI-01 | Sign out. Sign in with your sub-investigator account for the first time, as in JP-PI-01. | As JP-PI-01: new password, second factor, acknowledgement, then "This week's patients · AD-MAB". | 5 min |
| JP-SI-02 | Open "Delegation log". | You are on it as "Sub-investigator", with no tick under "Approach". The page says "Only the study's PI keeps the delegation log." | 2 min |
| JP-SI-03 | Open the fifth patient of the clinic list. Look for the "Approach" button. | There is no "Approach" button; "Need info" and "Not suitable now" are there. Known gap: the page does not yet say why Approach is missing (T-516). | 3 min |
| JP-SI-04 | On the same patient, type a note and press "Need info". | Accepted. Under "Marks" the mark is listed with your account name. | 2 min |
| JP-SI-05 | Open the sixth patient. Press "Ask treating doctor" and send the request. | The "Referrals" page: the request is waiting for the doctor. | 3 min |
| JP-SI-06 | Open "Criteria not matched". | The list opens, with "This is wrong, send to review" on each patient. | 3 min |
| JP-SI-07 | Type the address of the registry's page yourself: `/studies/NEUR-COH/week`. | "Page not found": the study is not one of yours. A link "My home page" takes you back. | 1 min |
| JP-SI-08 | On the patient of JP-SI-03, choose why you need the chart number and press "Show chart number". | Shown once, recorded with your account. | 2 min |
| JP-SI-09 | Open "IRB and consent form". | You can read it; there is no form to change it (only the PI and the coordinator change it). | 1 min |
| JP-SI-10 | Sign out. | The sign-in page. Opening a page again asks you to sign in. | 1 min |

## Session B: CRC

| # | Task | Expected result | Time |
| --- | --- | --- | --- |
| JP-CRC-01 | Sign in with your CRC account for the first time, as in JP-PI-01. | As JP-PI-01, then "My work" with "My tasks". | 5 min |
| JP-CRC-02 | In "My tasks", find the patient the PI marked "Need info" (JP-PI-05). | The task names the patient's pseudonym and shows the PI's note. | 3 min |
| JP-CRC-03 | Open the patient the PI approached (JP-PI-07). Under "Contact outcome", press "Reached, visit booked". | The screening number is shown; a confirmation with "Undo". "Screening log" shows "Reached, visit booked". | 3 min |
| JP-CRC-04 | Open "Referrals". For the patient of JP-PI-08, choose how you asked the doctor (for example by phone) and press "Agree". | "Recorded: the doctor agrees to introduce the study. The PI may now approach the patient." The count shows "Doctor agreed 1". The PI's patient sheet shows "Approach" again. | 3 min |
| JP-CRC-05 | Open "IRB and consent form". Enter a made-up approval number (for example IRB-DEMO-0001), the approval date, the end of validity, the consent-form version and its date. Press "Save". | Saved and shown. The PI no longer sees the IRB warning before "Approach". | 4 min |
| JP-CRC-06 | Open "Screening log" and download the XLSX file. | One row per screening number with its status; the file holds the same rows. Known gap: the file has no "synthetic data" line yet (DATA-015, card T-682). | 3 min |
| JP-CRC-07 | Open "Participants", then the screening number of JP-CRC-03. Record the step "Consented" with today's date. | "Participants" counts "Consented 1". Known gap: the consent-form version is not asked and an older version is not refused (T-516). | 4 min |
| JP-CRC-08 | Open "Send in a protocol". Type one line of criteria text in the box and send it. | Refused: "Not accepted in the demonstration". Nothing was stored. | 2 min |
| JP-CRC-09 | Leave the console untouched for more than 10 minutes, then open any page. | The sign-in page. After signing in you are on your home page. Known gap: the page you were on and a note you had not saved are not kept. | 12 min |
| JP-CRC-10 | Sign out. | The sign-in page. | 1 min |

After session B: the ten-item usability questionnaire and the five open questions ([../forms.md](../forms.md)), then
the debrief with the facilitator.

Not in this script, and said to the tester: the feedback button on every page (card T-510, not on master yet; use the
session record meanwhile), the phone layout (try it on your own phone if you wish and tell us), the morning notices,
the EDC prefill (on the Taiwan site only), and real model reading (step 2 of the PoC).
