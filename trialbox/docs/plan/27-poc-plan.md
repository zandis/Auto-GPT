# TB-POC-01 The clinician PoC: design, procedures, scripts and feedback loop

| Field | Value |
| --- | --- |
| Document ID | TB-POC-01 |
| Version | 1.0 (draft for the owner's approval at G0, Fri 2026-11-13) |
| Date | 2026-11-10 |
| Owner | Changfu Kuo (Aimedics) |
| Testers | Dr Makoto (Japan site, Japanese) and Dr Wenn (CGMH, Traditional Chinese) |
| Basis | The deep review of 2026-11-10 (`docs/reviews/2026-11-10-deep-review/`), above all TB-DR-02a (clinical journeys, run on the demo), TB-DR-02b (roles and the demo as a host), TB-DR-05b §6 (statement and acknowledgement), TB-DR-07 §3 (site trial types), TB-DR-09 §4 (hosting) and TB-DR-10 §3.1 (the gate). |
| Plan | Gate GP of `28-master-plan-v6.md` (TB-PLAN-06). The cards named here (T-501 to T-516) are defined in TB-PLAN-06 §6.2, wave P. |
| Rule | Synthetic and public data only. No real patient data, ever, in the PoC, its feedback, its logs or its screenshots. |

## 1. What the PoC is, and what it is not

**Purpose.** Two site clinicians work the screening flow of their own kind of trial, in their own language, on synthetic patients, and tell us what is wrong, confusing or missing. Their feedback reaches the design freeze (G2, Fri 2027-01-08).

**It is** formative product evaluation: design input.

**It is not** research on the testers, not validation (no IQ, OQ or PQ evidence comes from it), not a test of model accuracy, and not a use of the product for any patient or trial.

**What it can show:** whether a PI, a sub-investigator and a CRC can do a clinic day's screening work in the console; whether the Japanese and Traditional Chinese wording reads as a clinician expects; whether the screens show what is needed to trust or reject a criterion result; which steps are missing for each site's real trial type.

**What it cannot show, and the testers are told so:** how well the real models read real notes. Step 1 uses a test model with fixed answers (and recorded real-model answers where the G1 short run has them, labelled). Real note reading is judged in step 2 (GP-2), after G1 and G1b.

## 2. The fastest safe design: two steps

| | Step 1: GP (hands-on, hosted demo) | Step 2: GP-2 (real models; optional, recommended) |
| --- | --- | --- |
| When | sessions Tue 2026-12-08 to Fri 12-11; exit review Mon 12-14 | Tue 2027-01-12 to Fri 01-22 |
| Environment | the `demo/` image on one small cloud VM, two demo sites on it (a Japan-style site and a Taiwan-style site), HTTPS, an identity front door, per-tester accounts with a second factor | the installed stack on the owner's own B200 with the real pair, behind the same front door |
| Data | synthetic hospital; three scenarios per site (§4) | the same scenarios, the same synthetic patients |
| Models | test model; recorded real-pair answers from the G1 short run where they exist, each labelled | judge and verifier, live |
| Proves | flows, wording, roles, missing steps | note reading, speed, the two-model signal, the install path |
| Needs first | wave P of TB-PLAN-06 (§7 below) | G1, G1b, PR #68, GP exit |
| Cost | about US$110 a month for the VM, two months; a domain name about US$10 (prices from memory: check at order). The owner approves (Q-03) | none in cloud |

Why this and not something else (TB-DR-09 §4): the free hosting plan cannot run the demo (it needs about 1.9 GB at start and loses all work at each restart). The owner's own machine behind a tunnel works within hours but stops when the machine sleeps; it is the same-day fallback. A real box on the B200 takes two to four weeks, competes with G1b for the one card, and would be a first install in front of users.

A **guided first look** (30 minutes per clinician, on a call, the owner drives the demo) is offered on Wed 12-02 or Thu 12-03. It settles language and scope before the hands-on week and costs no build work.

## 3. Environment

| Item | Design | Card |
| --- | --- | --- |
| Host | one GCP VM (`e2-standard-4`, 16 GB) in `asia-east1`; either country is a few tens of milliseconds away. The image is built once from tag `poc-1` and run by digest. | T-509 |
| Two sites | two demo instances on the VM: `jp` (Asia/Tokyo, Japanese notes, the Japan scenarios) and `tw` (Asia/Taipei, Traditional Chinese and English notes, the CGMH scenarios). Each tester sees their own language end to end. | T-503, T-504 |
| HTTPS | Caddy on the VM with a real host name and a public certificate. Secure cookies on. | T-501, T-509 |
| Front door | an identity proxy (Cloudflare Access or Google IAP) that lets in only the testers' and the owner's mail addresses. The console is never open to the internet. | T-509 |
| Accounts | one account per tester per role, never shared: for each clinician a PI, a sub-investigator (with a seeded delegation log) and a CRC account; the owner holds the only admin account. Passwords are issued once out of band; the first sign-in forces a change; TOTP is on; the API session route enforces the second factor; sign-in is throttled per address. | T-505 |
| Language | the account's default language is stored on the account (ja for Dr Makoto, zh-TW for Dr Wenn); en is one click away. | T-505 |
| PoC mode | uploads and pasted chart text are refused with a page in the user's language; a banner on every page says "synthetic data, not for clinical use, not a medical device"; the acknowledgement is shown at first sign-in and stored as an audit event. | T-502 |
| Persistence | the testers' work survives a restart; the owner resets a site with one command; a daily snapshot of the data folder is kept for the PoC's life. | T-501, T-505, T-509 |
| One clock | the demo day is the real day in the site's time zone; no page shows a date after today. | T-513, PR #86 |
| Feedback | a control on every page (§6). | T-510 |
| Models | the test model answers Japanese, Traditional Chinese and English notes; pages say "test model" where a result comes from it; recorded real-pair opinions are labelled with the run they come from. | T-507, T-515 |
| Logs | no patient data exists to log; the testers' own account data and actions are logged as the statement says (§9). | |
| End of life | after the GP exit review the VM is destroyed and its snapshots deleted (a script, with a record); the feedback is kept without names. | T-509 |

Secrets (passwords, the front door's settings, the host name) never enter the repository, an issue or this document.

## 4. Content: the screening flows of the two sites' real trial types

The repository states one first study type per site (TB-DR-07 §3.1): early Alzheimer's disease in Japan and rheumatology (a rheumatoid arthritis biologic study, with an optional gout cohort) at CGMH. Neither PI's actual study list is written anywhere. **The owner confirms both lists at G0 (Q-02); if Dr Wenn's field is not rheumatology, scenario T2 changes and T1 is the stand-in.**

| # | Site | Scenario (synthetic study) | Shows | State today | Card |
| --- | --- | --- | --- | --- | --- |
| J1 | Japan | **Early Alzheimer's disease, anti-amyloid antibody, phase 3 sponsor 治験** ("AD-MAB"). Protocol in Japanese. Criteria on age, coded MCI or mild AD dementia, MMSE and CDR from notes, amyloid status from a report, anticoagulants, MRI microbleeds from a radiology report, recent stroke, eGFR, a study partner (a person-only criterion). | the site's real trial type; note-based criteria in Japanese; many honest "unknown" answers (amyloid status) | **missing**: no ruleset, no synthetic archetype, no Japanese protocol | T-503 (L) |
| J2 | Japan | **MCI and dementia registry, observational, opt-out** ("NEUR-COH"), on REDCap | a cohort list with no contact step; the opt-out register | small once J1's patients exist | T-503 |
| J3 | Japan | **Gout phase 3 sponsor trial run with an SMO CRC** (GZQO) on the Japan-style site | a sponsor trial end to end today; the fallback if J1 is late | exists; needs Japanese criterion labels | T-507 |
| T1 | CGMH | **Gout phase 3 sponsor trial** (GZQO), console in Traditional Chinese, the protocol in English as sponsors send it; one protocol amendment (one criterion relaxed, one added) | the sponsor trial flow; what happens to marked patients after an amendment | exists; the amendment step and labels to add | T-504, T-507 |
| T2 | CGMH | **Rheumatoid arthritis, JAK inhibitor or biologic, phase 3 sponsor trial** ("RA-JAK"). Criteria on RA duration, methotrexate, DAS28-CRP (a derived score), prior biologics, HBsAg, anti-HBc, IGRA, zoster and thrombosis from notes, eGFR. | the site's real trial type; a derived score; infection screening | value sets and patients exist; the trial ruleset and protocol are missing | T-504 (M) |
| T3 | CGMH | **Investigator-initiated registry with REDCap** (RA-COH or GOUT-COH) | the cohort list and EDC prefill with a sign-off | exists | T-504 |

Rule for names: no real sponsor's study name without its consent; the scenarios use synthetic sponsors and public registry text.

If J1 is not ready at the freeze, the Japan session runs J3 and J2 on the gout and general patients, J1 moves to a second session in the week of 12-14, and the GP record says so. LIFE-001 stays open until J1 is shown.

## 5. The test scripts

Each clinician has two sessions of about 60 minutes on a video call with a facilitator (the owner or a person he names) who watches, does not help unless asked, and notes where the tester stops. Session A is PI and sub-investigator. Session B is CRC, phone and the debrief. The tester may also use the demo alone between sessions.

After each task the tester answers one question in the product: "How easy was this?" (1 to 7). "Expected result" is what the screen must show; anything else is a finding. "Time" is the budget for a first-time user; the product records the real time. Machine times for the existing steps were measured on 2026-11-10 (TB-DR-02a §6) and are all under 3 seconds.

### 5.1 Dr Makoto (Japanese, the `jp` site)

**Session A: PI and sub-investigator (about 60 minutes)**

| # | Role | Task | Expected result | Time |
| --- | --- | --- | --- | --- |
| A0 | — | Open the link; pass the front door; sign in as PI; change the password; set up the second factor; read and accept the acknowledgement | The acknowledgement in Japanese; then 今週の患者 for AD-MAB; the banner on every page | 5 min |
| A1 | PI | Open 受信した通知 and the morning digest | One digest for today's clinic with the candidate count; opening it shows today's list; no patient name in the digest | 2 min |
| A2 | PI | Open the first candidate under 判断できる | The reason this patient may fit; the unknown items; the to-dos; the mark bar | 3 min |
| A3 | PI | Open the full criteria table. Find one criterion answered from a note (MMSE or CDR) and one answered from coded data (anticoagulant or eGFR) | Each row: met, not met, unknown or "a person must check". The note row shows the Japanese sentence it rests on. The coded row shows the value, unit, date and code. Unknown is amber and says it does not exclude. A row from the test model says so | 8 min |
| A4 | PI | Find the amyloid criterion on a patient with no PET or CSF report | "Unknown": the patient stays on the list with a to-do, never "not matched" | 3 min |
| A5 | PI | Mark one patient 情報が必要 with a note for the CRC | A confirmation with Undo; the CRC has a task | 2 min |
| A6 | PI | Mark one patient 今回は見合わせる: first with no reason, then with a reason; then Undo | Refused without a reason; accepted with one; Undo restores the patient | 3 min |
| A7 | PI | For a patient of another department, ask the treating physician first (主治医に確認), then approve the approach | The referral request is recorded and appears in the screening log; the approach waits for the treating physician's answer | 4 min |
| A8 | PI | Open 基準に合致しない患者. Pick one patient, read why, and flag it as wrong with a note | The criterion, the source (coded, note, rule) and the record passage; the flag is recorded with the tester's account and returns to the PI's list | 6 min |
| A9 | PI | Reveal one chart number with a reason | The (synthetic) number is shown once; the reveal is recorded with account and purpose | 2 min |
| A10 | PI | Acknowledge the SAE on the banner; open the SAE register | Acknowledged with account and time; the deadlines per party; the regulator named for Japan | 4 min |
| A11 | PI | Switch to NEUR-COH (J2). Open the cohort list | A list with no contact step; an opted-out patient is absent | 3 min |
| A12 | Sub-I | Sign out; sign in as sub-investigator. Open a candidate. Try to approve an approach | The sub-investigator sees the candidates of the delegated study only. If approach is not delegated, the page says why. Marks are recorded under this account | 5 min |
| A13 | Sub-I | Open a study that is not delegated (type its address) | A clear refusal page in Japanese with a way back | 1 min |
| A14 | — | Sign out | The sign-in page | 1 min |

**Session B: CRC, phone, debrief (about 60 minutes)**

| # | Role | Task | Expected result | Time |
| --- | --- | --- | --- | --- |
| B1 | CRC | Sign in as CRC. Open the home tasks | The task from A5 with the PI's note; due dates on or after today | 3 min |
| B2 | CRC | Record a call outcome "reached, visit booked" for the approved patient | A screening number; the screening log row changes state | 3 min |
| B3 | CRC | Record the treating physician's answer to the referral of A7 | "The PI may now approach"; the PI's list shows it | 2 min |
| B4 | CRC | Record consent on paper: version, date, who explained | Saved; the screening log and the participant page both say "consented"; an older ICF version is refused with a reason | 5 min |
| B5 | CRC | On GZQO (J3): open the EDC draft for the screening visit, check three values against their sources, change one with a reason, sign, send | Every value shows its source; unknown is never drafted as "no"; a change needs a reason; the signature needs the password; the read-back after sending matches | 10 min |
| B6 | CRC | Download the screening log | A file with one row per patient seen, with the reason for non-enrolment; the "synthetic data" line in the file | 2 min |
| B7 | PI | On a phone: sign in as PI; open a candidate; mark "need information"; ask the treating physician | The patient sheet fills the screen; the mark bar stays in reach; no sideways scroll | 6 min |
| B8 | any | Leave the console idle past the limit, then try to save a mark | Back to sign-in; after sign-in, the same patient, with the note kept | 3 min |
| B9 | any | Use the feedback control on two pages of your choice | Stored; a thank-you; nothing else changes | 2 min |
| B10 | — | The ten-item usability questionnaire in Japanese and five open questions (§6.3) | | 10 min |
| B11 | — | Debrief with the facilitator: the three worst things, the three best, what is missing for your trials | Notes by the facilitator, read back to the tester | 12 min |

### 5.2 Dr Wenn (Traditional Chinese, the `tw` site)

**Session A: PI and sub-investigator (about 60 minutes)**

| # | Role | Task | Expected result | Time |
| --- | --- | --- | --- | --- |
| A0 | — | Open the link; pass the front door; sign in as PI; change the password; set up the second factor; read and accept the acknowledgement | The acknowledgement in Traditional Chinese; then 本週病人 for RA-JAK; the banner on every page | 5 min |
| A1 | PI | Open 收到的通知 and the morning digest | One digest for today's clinic with the candidate count; no patient name in it | 2 min |
| A2 | PI | Open the first candidate under 可決定 | The reason this patient may fit; the unknown items; the to-dos; the mark bar | 3 min |
| A3 | PI | Open the full criteria table. Find DAS28-CRP, HBsAg and one note-based criterion (zoster or thrombosis) | DAS28-CRP shows the score, its components and their dates, and says which component is missing if it cannot be computed. HBsAg shows the result, date and code. The note row shows the sentence. Dates in the site's format | 8 min |
| A4 | PI | Find a patient with anti-HBc positive and no HBV DNA result | "Unknown" or "a person must check" with a to-do; never "not matched" on missing data | 3 min |
| A5 | PI | Mark one patient 需要更多資訊 with a note | A confirmation with Undo; the CRC has a task | 2 min |
| A6 | PI | Mark one patient 暫不邀請 with no reason, then with one; then Undo | Refused; accepted; restored | 3 min |
| A7 | PI | Ask the treating physician first (詢問主治醫師), then approve the approach | The referral is recorded and in the screening log; the approach waits for the answer | 4 min |
| A8 | PI | Open 未符合條件之病人. Pick one, read why, flag it as wrong | The criterion, the source and the passage; the flag recorded and returned to the PI's list | 6 min |
| A9 | PI | Switch to GZQO (T1). The protocol was amended (version 3 to 4). Open the list | Patients marked "not suitable" under version 3 on the relaxed criterion are listed for a second look, with the version of each earlier mark | 5 min |
| A10 | PI | Reveal one chart number with a reason | Shown once; recorded | 2 min |
| A11 | PI | Acknowledge the SAE; open the register | Acknowledged; the deadlines per party; the regulator named for Taiwan | 4 min |
| A12 | Sub-I | Sign in as sub-investigator. Open a candidate. Try to approve an approach. Open a study that is not delegated | Delegated studies only; a reason where an action is absent; a clear refusal page in Traditional Chinese | 6 min |
| A13 | — | Sign out | The sign-in page | 1 min |

**Session B: CRC, phone, debrief (about 60 minutes)**

| # | Role | Task | Expected result | Time |
| --- | --- | --- | --- | --- |
| B1 | CRC | Sign in as CRC. Open the home tasks | The task from A5 with the PI's note | 3 min |
| B2 | CRC | Record a call outcome "reached, visit booked" | A screening number; the log row changes | 3 min |
| B3 | CRC | Record the treating physician's answer | "The PI may now approach" | 2 min |
| B4 | CRC | Record consent: version, date, who explained | Saved; the log and the participant page agree; an older ICF version is refused | 5 min |
| B5 | CRC | On the registry (T3): open the REDCap draft for the baseline form, check three values against their sources, change one with a reason, sign, send | Every value with its source; a reason for a change; the password for the signature; the read-back matches | 10 min |
| B6 | CRC | Download the screening log | One row per patient seen with the reason for non-enrolment; the "synthetic data" line | 2 min |
| B7 | PI | On a phone: open a candidate; mark; ask the treating physician | The sheet fills the screen; the mark bar in reach; no sideways scroll | 6 min |
| B8 | any | Idle past the limit, then save a mark | Sign-in, then the same patient with the note kept | 3 min |
| B9 | any | Use the feedback control on two pages | Stored | 2 min |
| B10 | — | The usability questionnaire in Traditional Chinese and five open questions | | 10 min |
| B11 | — | Debrief | Notes read back | 12 min |

### 5.3 Notes on the scripts

- Several expected results are **not true today**. They are the PoC prerequisites of §7 (coded values on a criterion row, the note kept after sign-in, the screening log agreeing with the participant page, the second look after an amendment, the reason shown to a sub-investigator). A task whose prerequisite is not met at the freeze is either removed from the script with a note in the GP record, or kept and marked "known gap: tell us how much it matters".
- The two-page tester guide per language (part of T-508) holds: the link, how to sign in, the rule on real data in one bold sentence, the task list above, how to give feedback, and whom to call.
- The scripts in Japanese and Traditional Chinese are read by a native clinician before use.

## 6. Feedback: how it is captured and how it flows back

### 6.1 In the product (card T-510)

| Control | Where | What it stores |
| --- | --- | --- |
| **Feedback button** | every page, fixed position, in the page's language | a rating (1 to 5); a kind (wrong result / confusing / wording / missing / slow / other); how much it matters, in the tester's own judgement (**would cause a wrong patient decision** / blocks my task / slows me down / cosmetic); a comment; and, set by the product, the page, the study, the role, the language, the screen size, the release, the time and the tester's code |
| **"This answer is wrong" flag** | each criterion row and each row of the "criteria not matched" list | the criterion, the synthetic patient's pseudonym, the answer shown, the tester's correct answer, a comment |
| **Ease question** | after each scripted task (a small prompt the tester can dismiss) | 1 to 7, the task id, the time taken |
| **End questionnaire** | a page linked from the guide | the ten-item System Usability Scale in a published Japanese and Traditional Chinese translation, and five open questions (§6.3) |

Rules. The comment box repeats "do not describe a real patient" beside it. There is no field that asks for a patient example. Stored feedback is scanned with the data-handling scan before it leaves the demo. Feedback never changes a patient's state.

### 6.2 Outside the product

The facilitator's notes for each session (where the tester stopped, what they said aloud, the time per task), written on the session checklist (T-508). Screen recording only if the tester agreed in the acknowledgement, kept outside the repository and deleted after the exit review.

### 6.3 The five open questions

1. Which screen would you not trust for a real patient, and why?
2. What did you look for and not find?
3. Which words would a colleague at your hospital misunderstand?
4. What in your own trials does this flow not cover?
5. If you could change one thing before your hospital uses this, what would it be?

### 6.4 The flow back as issues

1. **Each evening of a session day** the owner (or the integrator on his word) runs the export: `tools/poc_feedback.py` (part of T-510) reads the stored feedback, runs the scan, and writes one file per item. Items carry the tester's **code** (T1, T2), never a name: the repository is treated as public.
2. **One GitHub issue per item**, labelled `poc`, with the kind, the tester's rating of how much it matters, the language, the page and the scenario. Duplicates are linked, not merged, so the count stays honest.
3. **Triage at the GP exit review (Mon 12-14)** by the owner with the integrator. Each issue gets a severity on the review's scale (Blocker to Low) and one of four outcomes: **before G2** (a card in wave 2), **before G3** (wave 3), **after go-live** (dated), **not doing** (with the reason). Anything a tester rated "would cause a wrong patient decision" becomes a card the same day, whatever its outcome.
4. **The triaged list** is committed as `docs/poc/gp-findings.md` and attached to the GP gate record. New scope enters the plan only as a dated plan change signed by the owner.
5. **The testers hear back** within a week: what will change, when, and what will not, with the reasons.

## 7. Prerequisites: what must be fixed before the PoC

Kept to what the PoC path reaches. Every Blocker and Critical the path reaches is on the list; no Blocker may remain at the freeze. The cards are in TB-PLAN-06 §6.2, wave P. "Path" findings come from the columns "PoC path = yes" of the deep review.

| # | Prerequisite | Findings it closes | Card | Size |
| --- | --- | --- | --- | --- |
| 1 | The demo image starts from a clean build (the CQL jars are in the image; seeding works with Secure cookies), fits its host, and its README states measured times and memory | OPS-001, ROLE-002, UX-001 (Blockers); ROLE-003, OPS-005, OPS-007, LIFE-005, DEP-001 for the demo image | T-501 | M |
| 2 | Work survives a restart; an always-on host | UX-002 (Blocker), OPS-006 | T-501, T-509 | S |
| 3 | A password alone must not open a session: the API session route enforces the second factor; sign-in throttled per address | ROLE-001 (Blocker), ROLE-006, OPS-003 | T-505 | S |
| 4 | Per-tester accounts for PI, sub-investigator and CRC with a seeded delegation log; forced first password change; nobody can make themselves PI of a study; the admin account is the owner's only | UX-040, ROLE-004, ROLE-008, OPS-002, FIT-027; ROLE-010 is avoided in the PoC by not issuing admin | T-505 | M |
| 5 | PoC mode: uploads and chart paste refused; banner; acknowledgement stored; the non-device line on pages and exported files | REG-014 (Critical), PLAN-019, OPS-004, REG-015, DATA-015 | T-502 | M |
| 6 | In-product feedback and its export | UX-006 (Blocker) | T-510 | M |
| 7 | The Japan scenarios: the Alzheimer's trial with its synthetic patients and Japanese protocol; the registry | LIFE-001 (Blocker), UX-004 | T-503 | L |
| 8 | The CGMH scenarios: the RA trial; the amendment step on GZQO; the registry prefill step | LIFE-002, LIFE-010 (the PoC part) | T-504 | M |
| 9 | Wording: "criteria not matched" in place of "excluded" on the pages the script reaches; the intended-use footer; a native read of the clinical strings | CR-078 (part), FIT-C2, T-116 (PoC part), ROLE-023, ROLE-024 | T-506 | M |
| 10 | Japanese and Traditional Chinese criterion labels and to-dos; the test model answers Japanese and English notes; test-model results are labelled; recorded real-pair opinions where they exist | UX-009, LLM-045, UX-007 | T-507, T-515 | M |
| 11 | One clock (the demo day is the real day in the site's time zone) | UX-003, CR-049, CR-050 (PR #86) | T-513, #86 | S |
| 12 | A coded criterion shows its value, unit, date and code | UX-008 | T-514 | M |
| 13 | Workflow fixes on the path: the screening log agrees with the participant page after consent; a referral after an approach pauses the approach; a sub-investigator sees why an action is absent; IRB approval and consent version seeded so an approach is not always an override | UX-011, UX-013, UX-015, UX-014, LIFE-019 (the PoC part) | T-516 | M |
| 14 | The unit of a lab row is read from the row (PR #70 merged) and the shipped rulesets are recompiled | STD-001 (Blocker), STD-040 | #70, T-613 (part) | S |
| 15 | The PI can start a run, if the owner agrees; lists show "data as of" | FIT-003, FIT-U01 | T-512 | S |
| 16 | The PoC pack: the statement and acknowledgement in three languages after a native read; the scripts; the guide; the session checklist; the purge note | REG-015, REG-013 | T-508 | M |
| 17 | Hosting scripts: VM, HTTPS, front door, snapshot, purge, destroy | OPS-003, RSK-55 | T-509 | M |
| 18 | Notices owed by a hosted demo (LOINC, UCUM and the other third-party notices) | STD-044 (the PoC part) | T-617 (part) | S |
| 19 | The build tool with a critical advisory is upgraded and the vulnerable jars in the demo image are replaced | DEP-006, DEP-001 (with PR #78) | #78, dependency batch 0 | S |

Not prerequisites, and said to the testers: profiles, the reminder card and outside-medication checks are not in the demo; the monitor's source-data view does not exist; the two-model signal is live only in step 2.

## 8. The PoC plan

**Owner:** Changfu Kuo. **Build:** the integrator session and the wave-P sessions. **Facilitator:** the owner, or a person he names (Q-01). **Native readers:** Dr Makoto for Japanese, Dr Wenn or a CGMH colleague for Traditional Chinese (or two other native clinicians, so the testers see the text fresh).

| Step | Date | Who | Done when |
| --- | --- | --- | --- |
| 1 Approve this plan; answer Q-01 to Q-04 and Q-07; name the facilitator | Fri 11-13 (G0) | owner | the G0 record |
| 2 Confirm each PI's study list and Dr Wenn's field | Fri 11-13 | owner, Makoto, Wenn | a line in the G0 record; T-503 and T-504 adjusted |
| 3 Invite the testers; book two 60-minute sessions each in 12-08 to 12-11 and the optional first look | by Fri 11-20 | owner | dates in the tracker |
| 4 Wave P builds and merges (§7) | Mon 11-16 to Fri 11-27 | sessions, integrator | each card's acceptance tests |
| 5 Native read of the wording, the scripts and the statement | by Wed 11-25 | native readers | a signed note per language in `docs/poc/` |
| 6 **GP-0 build freeze** | **Fri 11-27** | integrator, owner | tag `poc-1`; the go/no-go list of §8.1 |
| 7 Deploy; smoke test; issue accounts out of band; send the statement and the guide | Mon 11-30 | owner (or the operations person) | both sites answer over HTTPS behind the front door |
| 8 **GP-1 dry run**: the owner walks both scripts in three languages | **Tue 12-01** | owner | every task completes or is struck from the script with a note |
| 9 Optional guided first look | Wed 12-02 or Thu 12-03 | owner, each tester | notes |
| 10 **Sessions** A and B per tester | **Tue 12-08 to Fri 12-11** | testers, facilitator | the session checklists; feedback exported each evening |
| 11 **GP exit review**: triage | **Mon 12-14** | owner, integrator | `docs/poc/gp-findings.md`; the GP record |
| 12 Reply to the testers | by Fri 12-18 | owner | sent |
| 13 Destroy the host; delete snapshots and recordings | after step 12 (or keep to GP-2 if the owner says so) | owner | a record of the deletion |

### 8.1 Go / no-go at the freeze (GP-0) and at the dry run (GP-1)

**Go only if all are true:**

1. Tag `poc-1` is on master with CI green.
2. No open Blocker or Critical finding on the PoC path (the deep review's "PoC path = yes" rows and the register).
3. The image built from the tag starts on a clean host with no manual step, and both sites answer over HTTPS behind the front door.
4. A sign-in needs the second factor on every route, the console and the API alike (a test with TOTP on).
5. An upload and a pasted chart are refused in three languages; a planted identifier in a feedback comment is found by the scan.
6. The acknowledgement is shown once per account and stored.
7. The feedback control stores an item from every page of the scripts; the export writes it with a tester code and no name.
8. Each tester's three accounts exist; the sub-investigator sees only the delegated study.
9. At least two scenarios per site are loaded and each script task has its expected result on the dry run (or is struck with a note).
10. The statement and acknowledgement are final in Japanese and Traditional Chinese after the native read.
11. The purge script has been run once on a planted record, and the incident note names who is called.
12. The decision "the PoC is product evaluation, not research" is recorded (Q-07).

**No-go** on any miss of 2 to 6 or 11. A miss of 9 for J1 alone is a go with J3 and J2 (§4). Any other miss: the owner decides and the GP record says why.

### 8.2 Rules during the sessions

- Nothing is fixed live. A defect is logged; the session goes on with the next task.
- If a tester enters or describes real patient information: stop the session; run the purge; record the event without the content; tell the tester what was done; the tester follows their hospital's own rule.
- If the demo is down for more than 15 minutes, the session is rebooked.
- The facilitator does not explain a screen unless asked; each request for help is a finding.

### 8.3 Exit criteria for GP

Every task attempted by both testers. At least 80 % of tasks completed without help. No finding rated "would cause a wrong patient decision" left without a fix card. Every item triaged. If the criteria are not met, a second round runs on tag `poc-2` in the week of 2027-01-12 together with GP-2; the platform still freezes on 01-08; the go-live dates do not move because of the PoC.

## 9. Sign-off and the data-handling statement

### 9.1 What the clinicians sign

**One thing: the acknowledgement** of §9.3, in their language. It is shown at the first sign-in and stored with the account, the time and the statement's version; a signed page is kept as well. Nothing else is recommended: no contract, no consent form as a research subject (the PoC is not research: Q-07), no validation signature (the PoC is not qualification). If Aimedics wants a confidentiality agreement beyond the statement's point 10, that is the owner's choice (Q-07).

At the end each tester is asked, without obligation, to confirm by mail that the facilitator's notes are a fair record.

### 9.2 The data-handling statement (one page; given to each tester before the first sign-in)

**TrialBox proof of concept: how data is handled**

1. **What this is.** A demonstration copy of TrialBox, a research-support tool that screens records against study eligibility criteria. It runs on a hosted server in Taiwan (Google Cloud, `asia-east1`), outside any hospital. It is pre-release software. It is not validated and is **not a medical device**.
2. **The data in it is not real.** Every patient, chart, name, number and date in the demonstration is synthetic (made by a generator) or comes from public research data sets. No hospital's data is in it. Any likeness to a real person is chance.
3. **Do not enter patient information.** Do not type, paste, upload or photograph anything from a real patient's record, in any field, file, comment or feedback form. This includes names, chart numbers, dates of birth, note text, images and rare details that could identify a person. The demonstration refuses chart paste and uploads; the rule also covers free-text boxes and your feedback.
4. **Not for clinical use, not for trial conduct.** Do not use any output to decide on a patient's care, eligibility, approach or consent. Nothing here is a trial record, a screening log, a source document or an essential record under GCP. Results may be wrong; the demonstration uses a test model.
5. **Your own data.** We keep your name, role, institution, mail address, account name, sign-in and action logs (time, page, action), and the feedback you give (written, spoken in calls, and screen recordings only if you agree each time). Purpose: to run the test, to keep the service secure, and to improve the product. Controller: Aimedics (legal name and address to be filled). Contact: (name and mail to be filled). We do not sell or share it. Feedback is filed under a code, not your name; a named quote is used only with your consent.
6. **Where and how long.** The data is held in Taiwan on Google Cloud. For the tester in Japan this is a transfer outside Japan; we tell you the country and its data-protection regime before you start. Accounts and logs are deleted 90 days after the test ends; feedback is kept without names.
7. **Your rights.** You may ask to see, correct or delete your data, or stop taking part, at any time, without giving a reason.
8. **If something goes wrong.** If patient information is entered by mistake, tell the contact the same day. We delete it, purge the snapshots and logs that hold it, record the event without the content, and tell you what was done. You follow your hospital's own reporting rule.
9. **What your feedback is.** Design input for the product. It is not qualification evidence and not research on you. If we later wish to publish findings from the test, we ask you first and ask the ethics committee whether review is needed.
10. **Confidentiality and interests.** The software and its screens are confidential until release. If you are an investigator at a pilot site or a reader in Study A, your part in this test is recorded in the study's conflict-of-interest file.

The bracketed items of the draft in TB-DR-05b §6.1 (legal name, contact, region) are filled before sending. This is a draft by the plan's authors, not legal advice: counsel reads it once (Q-07).

### 9.3 The acknowledgement

> I have read the TrialBox proof-of-concept data-handling statement (version, date).
>
> ☐ I understand that all patient data in the demonstration is synthetic or public.
> ☐ I will not enter, paste, upload or describe any real patient's information.
> ☐ I will not use any output for patient care, eligibility decisions, consent or trial records.
> ☐ I understand the software is pre-release, not validated and not a medical device, and that its outputs may be wrong.
> ☐ I agree that my account data, activity logs and feedback are used to run the test and improve the product, as the statement says.
> ☐ (optional) I agree to screen recording in feedback sessions.
> ☐ (optional) I agree that my feedback may be quoted with my name.
>
> Name, role, institution, date.

Japanese (key lines, draft for the native read): 「本デモ環境の患者データはすべて合成データまたは公開データです。」「実在の患者さんの情報は、入力・貼り付け・アップロード・記述のいずれも行いません。」「出力を診療、適格性の判断、同意取得、治験記録に用いません。」「本ソフトウェアは開発中であり、バリデーション未了で、医療機器ではありません。」「アカウント情報、操作ログ、フィードバックが、試用の運営と製品改善のために利用されることに同意します。」

Traditional Chinese (key lines, draft for the native read): 「本展示環境之病人資料皆為合成資料或公開資料。」「本人不輸入、貼上、上傳或描述任何真實病人之資訊。」「本人不將任何輸出用於病人照護、資格判定、同意取得或試驗紀錄。」「本軟體為開發中版本，尚未完成確效，非醫療器材。」「本人同意帳號資料、操作紀錄與回饋意見用於本次試用之執行與產品改善。」

## 10. Risks of the PoC

| Risk | Control |
| --- | --- |
| A tester enters real patient information (RSK-55) | PoC mode; the banner; the acknowledgement; the scan of stored input after each session; the purge script; the host destroyed after the PoC |
| The PoC misleads about accuracy (RSK-56) | the statement and the script say what it cannot show; test-model results are labelled; real models only in GP-2 |
| The hosted demo is attacked | the front door admits three mail addresses; the second factor on every route; the throttle; nothing real is on it |
| J1 is not ready (size L in 12 working days) | start it first; J3 and J2 are the fallback; a second Japan session in the week of 12-14 |
| A poor session re-opens the scope | exit criteria and the triage rule are fixed here, before the sessions; new scope only by a dated plan change |
| The owner has no time to facilitate | a named facilitator (Q-01); the first look is optional |
| The wave-P merges collide with the 14 open PRs | the merge order and the lanes of TB-PLAN-06 §6.4 and §6.5; one card per PR |
| The testers' feedback names a colleague or a patient | codes, not names; the scan before export; the comment box repeats the rule |

## 11. Assumptions made where the request was silent

1. The two testers are Dr Makoto and Dr Wenn themselves, each with about four hours in the PoC weeks. If they delegate to a sub-investigator or a CRC, the scripts stay the same.
2. Dr Wenn's field is rheumatology, as the repository's design documents imply for CGMH. Confirm (Q-02).
3. Each tester works in their own language; English is offered, not required.
4. The testers use a hospital or personal PC with a current browser and their own phone. No software is installed.
5. A small cloud cost (about US$110 a month for two months) is acceptable for the PoC host; the review itself spent nothing.
6. The PoC is product evaluation and needs no ethics review; publishing its results later would need the testers' consent and a question to the committee.
7. The testers sign the acknowledgement only.
8. Step 2 (real models on the owner's B200) is wanted, after G1 and G1b.
9. The facilitator speaks the tester's language or English; sessions are not interpreted.
10. The repository is treated as public, so the PoC's address, accounts, tester names and recordings never enter it.
