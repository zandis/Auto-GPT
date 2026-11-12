# TB-DS-15 Site Acceptance Protocol (IQ / OQ / PQ)

| Field | Value |
| --- | --- |
| Document ID | TB-DS-15 |
| Title | Site Acceptance Protocol (installation, operational and performance qualification) |
| Version | 0.6 |
| Date | 2026-11-07 |
| Owner | Aimedics engineer |
| Author | Claude (for Aimedics) |
| Status | Reference, **hospital stage (H)**: run only when a hospital installs TrialBox for real patient data; not a build gate (`20-build-map.md`). One executed copy per site: SAT-JP (Japan head hospital), SAT-CG (CGMH). |
| Related | TB-DS-00, TB-DS-01, TB-DS-03, TB-DS-04 §7.3 (SAT summary, superseded in detail by this document), TB-DS-11, TB-DS-12, TB-TMPL-01, TB-REV-006 finding M-11 |

**Approvals of this protocol (before execution)**

| Role | Name | Signature | Date |
| --- | --- | --- | --- |
| Aimedics engineer | (to be named) | | |
| Product owner | Changfu Kuo | | |
| Hospital IT lead, Japan head hospital | (to be named) | | |
| Hospital IT lead, CGMH | (to be named) | | |
| Site PI, Japan head hospital | (to be named) | | |
| Site PI, CGMH | (to be named) | | |

## 1. Purpose and approach

This protocol shows, at each hospital, that TrialBox is installed as specified (IQ), works as specified in that hospital's environment (OQ), and performs acceptably with that hospital's real data and studies (PQ). It follows GAMP 5 (2nd ed.) in a lightweight, risk-based form suited to a non-device research tool outside the regulated EDC path. Steps are scaled to risk (TB-DS-11): steps that control hazards H-01, H-04 and H-07 are mandatory and cannot be waived.

**Planned dates** (TB-PLAN-01 MS-10, MS-12..14; TB-DS-00 §2.H "Pilot dates", recommended, owner decision OI-14 pending): Japan head hospital IQ/OQ 2027-01-12 to 01-15, PQ and go-live (pilot Phase 1) about 2027-02-08; CGMH IQ/OQ 2027-02-15 to 02-19, PQ and go-live about 2027-02-22 (or 2027-03-15 / 2027-03-29 with one engineer alone, TB-DS-00 §2). An executed copy records the dates chosen. What is tested at go-live and what at the week-6 readiness check follows the TB-DS-00 §2 "M1 content by date" table.

IQ and OQ can run before ethics approval. PQ uses the site's real studies and starts only when the ethics approval for the pilot is in hand (TB-TMPL-01).

## 2. Roles during execution

| Role | Who | Does |
| --- | --- | --- |
| Executor | Aimedics engineer | Runs each step, records actual results and evidence |
| Site witness | Hospital IT lead (IQ, OQ); site PI or delegate (PQ) | Watches or checks the evidence; initials each step |
| Reviewer | Product owner or Japan maintenance lead | Reviews the executed protocol and deviations |
| Approver | Hospital IT lead and site PI | Sign the summary report |

## 3. Prerequisites

| ID | Prerequisite | Evidence |
| --- | --- | --- |
| PR-01 | Release bundle signed and its baseline manifest available (TB-DS-12 §4) | Manifest file and signature check output |
| PR-02 | Hardware delivered per TB-DS-00 BD-10 (Japan: 1 × RTX 5090, 256 GB RAM, 8 TB mirrored NVMe; CGMH: 2 × RTX 5090, 256–384 GB RAM, 16 TB mirrored NVMe), UPS connected | Delivery note, photo of labels |
| PR-03 | Network: server in the agreed zone, firewall rules for the export source, mail server, NTP, backup target; no inbound rule from outside the hospital | Hospital firewall change record |
| PR-04 | Site mapping file (CI-MAP), rule book (CI-RB) and settings (CI-SET) reviewed and signed (TB-DS-12 §8) | Signed files |
| PR-05 | Accounts list: one named person per role for the tests | List approved by the PI |
| PR-06 | For PQ only: ethics approval of the pilot (Phase 1, and Phase 2 if already approved) and the opt-out notice published | Approval letter stating which phases are approved; notice URL |
| PR-07 | **PI device path confirmed** (TB-REV-006c C-16): which path the investigators will use to open the PI list and approval pages — (a) personal phone on hospital Wi-Fi or VPN, (b) hospital-issued phone with a browser allowed for internal apps, or (c) clinic PC only; whether a TOTP app is allowed on that phone; whether clinic PCs allow a second browser window beside the EMR (≤ 480 px layout, FR-UI-19) | Written answer signed by the hospital IT lead, collected at the site survey (TB-PLAN-01 MS-05); if (c), S16 is tested in the clinic-PC layout only and the PI list mail is checked to be usable without a working link (ICD-13) |
| PR-08 | **Clinic-PC and network layout**: one clinic PC per pilot clinic room identified, with the EMR window and the TrialBox page open side by side; mail reaches the PI and CRC inboxes from the appliance sender | Photo or screenshot of the layout (no patient data); test mail received |
| PR-09 | **REDCap project inspection** (R-05) for each pilot study: field names for consent, enrolment, screen-fail, withdrawal and sponsor subject number recorded; the REDCap admin has added `tb_screening_no` (BD-18) or the site has agreed to `mrn` link mode | Filled project-link sheet (TB-DS-08 §4.1a) signed by the REDCap admin |
| PR-10 | **Workload baseline complete** (WP-00, TB-PLAN-01 MS-05b: 2027-01-11 to 01-22, or the two normal weeks before a moved go-live), finished before this site's Phase 1, outside 年末年始 and Lunar New Year | Baseline summary (TB-TMPL-07 §2–§3) signed by the site PI |
| PR-11 | **Chart-review reviewers funded and named** (TB-PLAN-01 §1a) | Names, hours and funding line in the ethics pack checklist (TB-TMPL-01 §8) |

## 4. Installation qualification (IQ)

| Step | Action | Expected result | Actual / evidence | Pass/Fail | Initials |
| --- | --- | --- | --- | --- | --- |
| IQ-01 | Verify bundle signature and SBOM before install | Signature valid with the Aimedics release key; SBOM present | | | |
| IQ-02 | Run `install.sh` from the bundle; GPU profile auto-detected | Profile `rtx5090` (Japan) or two-card profile (CGMH) selected; install completes | | | |
| IQ-03 | Physical configuration audit: compare installed image digests, model hashes, prompt versions and ruleset tags with the baseline manifest | All identical (TB-DS-12 §9) | | | |
| IQ-04 | Disk encryption active; key sealed to TPM or passphrase held by hospital IT (SC-20) | Encrypted volumes listed; key custody record signed | | | |
| IQ-05 | Key ceremony: HMAC site key generated on the box, split shares created and handed to named custodians (SC-21) | Ceremony record signed by custodians | | | |
| IQ-06 | Network: no listening port reachable from outside the hospital; egress only to the allowlist (TB-DS-02 §7) | Scan from outside the server zone shows only the console port inside the hospital; egress test to a non-allowed host fails | | | |
| IQ-07 | Time synchronisation to the hospital NTP server | Offset < 1 s on all containers | | | |
| IQ-08 | Health page green; version and baseline shown | All checks green | | | |
| IQ-09 | Backup target configured; first backup written | Backup present, encrypted | | | |
| IQ-10 | Host hardening checklist (TB-DS-03, SC-96, SC-97) | All items met or accepted in writing by the hospital security officer | | | |

## 5. Operational qualification (OQ)

| Step | Action | Expected result | Actual / evidence | Pass/Fail | Initials |
| --- | --- | --- | --- | --- | --- |
| OQ-01 Ingest | Run the first full ingest from the site's export (SS-MIX2 or vendor export in Japan; HIS / data warehouse at CGMH) | Ingest report produced; validation errors ≤ 0.5 % (SC-32) | | | |
| OQ-02 Pseudonymisation | Check 5 patients: chart number not present in any lake table or FHIR resource; present only in the encrypted pid map | No chart numbers or names outside the vault | | | |
| OQ-03 Mapping | Compare 20 patients field by field with the EMR screen: demographics, 3 diagnoses, 5 laboratory results, 3 prescriptions, 2 notes each | ≥ 99 % of compared fields correct; every mismatch explained and fixed or accepted by site IT (hazard H-01) | | | |
| OQ-04 Conventions | 10 records with 和暦 or 民國 dates, 「〜の疑い」 diagnoses, 保険病名 cases, full-width codes | All normalised correctly; suspected diagnoses not treated as confirmed (H-02) | | | |
| OQ-05 Dry run | Full-size night run with the site's pilot studies (TB-DS-00 N-18) | Finishes inside the night window (BD-11); duration, GPU and disk use recorded | | | |
| OQ-06 Roles | Log in as each role (admin, coordinator, investigator, viewer, cro, auditor); open each main page and one patient | Each sees and can do only what the role × action matrix SRS AM-01 allows, including: only the study's investigator can sign off the clinical criteria and only a coordinator (or data manager) can confirm the code mapping, on desktop, and a ruleset runs only with both (FR-AUTH-13, BD-13); the first sign-off in a session asks for a TOTP code once and later ones in the same session do not (BD-17, FR-AUTH-05d); no score, probability or model name appears on any page for investigator or coordinator (FR-UI-17); cro sees aggregates only (H-07) | | | |
| OQ-06a Study set-up and consent explainer | On S21 for a test study: coordinator enters the ethics approval record (committee, number, date, ICF version, committee-approved explainer file); investigator confirms it. Repeat with (i) a committee-edited explainer file and no ICF amendment, (ii) the study flagged industry-sponsored without a sponsor approval, (iii) explainer switched off | The approved file (not the generated draft) goes live only after the investigator confirms; there is no release button or RELEASE command; (i) the edited file replaces the live one on the same record with no regeneration (FR-CON-09); (ii) go-live is blocked until sponsor approval is recorded (FR-CON-10); (iii) only the ICF is used (FR-CON-07) (BD-15) | | | |
| OQ-06b Flow-B ethics gate | Run SCREEN for a test trial with no ethics approval record for screening, then with an expired one, then with a current one; repeat for a test **opt-out registry** study; run FEAS for the same studies each time | SCREEN refused in the first two cases for both study types with a message naming the missing record; runs in the third; FEAS runs in all cases (FR-STUDY-06, BD-20) | | | |
| OQ-07 2FA and sessions | Log in with TOTP; wrong code 5 times; idle 30 min | 2FA required; lockout after 5 failures for 15 min; session ends after 30 min idle (N-05, N-06) | | | |
| OQ-08 Reveal | Coordinator reveals one chart number with a reason | Chart number shown for a limited time, watermarked; audit event written (SC-16) | | | |
| OQ-09 Mail | Send a feasibility command by e-mail from an allowed sender and from a non-allowed sender | Allowed: report returned with pseudonyms only and small cells suppressed; non-allowed: refused and logged (BD-04, SC-45) | | | |
| OQ-10 Output classifier | Try to export a file containing a chart number | Export blocked (SC-51) | | | |
| OQ-11 REDCap | Run the connector suite against the hospital REDCap development server (or the simulator if no server is available; record which) | Data dictionary and records read; for each pilot study the project link (PR-09) maps consent, enrolment, screen-fail and withdrawal correctly on 5 test records, joined by `tb_screening_no` (or `mrn`) (FR-RC-16); a renamed field disables the link with `RC-LINK-FIELD`; screening-log export keyed on screening number with the TB-TMPL-03 columns; no writes in M1 (BD-05) | | | |
| OQ-12 PHI pass | Run the PHI pass on 200 site notes (the pre-pilot gate set, NFR-PERF-14 / FR-SEC-12, TB-DS-03 §13.6); two site staff check the scrubbed notes. At go-live this is the rules + NER pipeline; a miss on N-07 blocks go-live (TB-DS-04 §12.5 item 4, §12.6). When the LLM tagger is released before week 7, OQ-12 is re-run (G5) before any scrubbed note leaves the identified zone | Leak rate ≤ 0.5 % of identifier spans and zero direct identifiers (N-07) (H-04) | | | |
| OQ-13 Model gate | Run the gate sets on the installed box | Within N-11, N-12; results recorded | | | |
| OQ-14 Language and labels | Native speaker (a CRC and a physician at the site) reviews the UI, reports and mail in the site language, with a fixed list first: the three PI marks and "Ask treating doctor", the "Not suitable" reasons, the pre-consent wording "would need checking after consent", the contact outcomes, and the PI list mail. Proposed terms to review: JA 「声をかける」 (Approach), 「情報が必要」 (Need info), 「今回は見合わせる」 (Not suitable); zh-TW 「邀請」, 「需要更多資訊」, 「暫不邀請」 (TB-DS-09 §6) | No label reads as an eligibility decision (not 「対象外」 / 「不符合」) or as a pre-consent research instruction; agreed terms recorded and fed into the Japan team's string review (TB-PLAN-01 WP-07); other issues listed | | | |
| OQ-15 Audit chain | Run chain verify; tamper test on a copy | Verify passes on the live chain; tampered copy fails | | | |
| OQ-16 Backup and restore | Restore configuration, pid map and registry to a scratch volume | Restored data equal; time recorded (N-15) | | | |
| OQ-17 Update and rollback | Install a signed test update; roll back | Both work; data unchanged; unsigned update refused | | | |
| OQ-18 Opt-out | Add a test patient to the opt-out registry; run screening | Patient absent from counts and lists | | | |

## 6. Performance qualification (PQ)

Starts only with PR-06 met.

| Step | Action | Expected result | Actual / evidence | Pass/Fail | Initials |
| --- | --- | --- | --- | --- | --- |
| PQ-01 Feasibility | One feasibility report per pilot study from the feasibility page | Report complete (funnel, unanswerable criteria, snapshot date); delivered within one working day | | | |
| PQ-02 Plausibility | PI compares the funnel with known clinic numbers | PI signs the plausibility check (H-10) | | | |
| PQ-03 Independent count | Site IT writes an independent SQL query for 3 structured criteria on the same snapshot | Counts identical (endpoint E4) | | | |
| PQ-04 Patient list (at go-live) | The built weekly PI list page and the existing pseudonym list mail (BD-04) for each pilot study | List produced in the night window; each row shows why-fits, "would need checking after consent" items, next visit; no score or model name (FR-UI-17); the mail carries pseudonyms only and no screening number (BD-18) | | | |
| PQ-04a Clinic-day list and digest (at the week-6 readiness check, with PQ-06a) | Clinic-day PI list (S18), CRC digest (N2), S16 grouping, S19 settings | Rows grouped "Your clinic" / other study doctors / other doctors (FR-SCR-07b); delivered on the PI's clinic days; notices within the NFR-USAB-10 budget | | | |
| PQ-05 Single check | Coordinator checks 5 patients | Each answer within 60 s (N-13); per-criterion cards with quotes | | | |
| PQ-06 Pilot Phase 1 | Confirm the site's usual screening continues, staff know TrialBox lists are additive only in Phase 1, the CRC keeps their own screening log as today, and the research office knows the weekly log upload (TB-DS-04 §8.9) | Written confirmation by the PI; training records (SC-05) | | | |
| PQ-06a Phase-2 readiness (at pilot week 6, not at go-live) | Check the week-6 recall checkpoint, the committee's Phase-2 approval and that the role homes and notification releases are installed; PQ-04a passed; usability tasks T1 (S16 groups), T2 second half (Ask treating doctor), T6 (S8 "Today"), T7 ("Marks today"), T11 (S19 snooze) and T12 (FR-REP-09 export) of TB-TMPL-07 §4 done by two coordinators, a PI and a research-office member | All present, signed by the PI; otherwise the site stays in Phase 1 (TB-DS-04 §8.2) | | | |
| PQ-07 Usability | Two coordinators, one investigator and one research-office member complete the go-live tasks of TB-TMPL-07 §4: T3, T4, T5, T8, T9, T10, T13 and the first half of T2 (Approach mark); T1, the second half of T2, T6, T7, T11 and T12 move to PQ-06a, matching TB-DS-00 §2, on the device path of PR-07 | No critical use errors; tap counts within NFR-USAB-08; issues listed | | | |

## 7. Deviations

| Field | Content |
| --- | --- |
| Deviation ID | SAT-<site>-DEV-nn |
| Step | Step ID |
| Description | What happened, against what was expected |
| Impact | Effect on the hazard controls in TB-DS-11 and on the pilot |
| Classification | Minor (no effect on a mandatory step) / Major (a mandatory step not met) |
| Action | Fix and re-test; or accept with justification |
| Approved by | Engineer and hospital IT lead (Minor); plus site PI and product owner (Major) |

A Major deviation on a mandatory step (OQ-02, OQ-03, OQ-06, OQ-08, OQ-10, OQ-12, OQ-18, PQ-06) blocks go-live until it is fixed and the step re-run.

## 8. Summary report and sign-off

| Item | Content |
| --- | --- |
| Site | |
| Release and baseline | |
| Steps passed / failed / not applicable | |
| Deviations (IDs, status) | |
| Open issues and workarounds | |
| Conclusion | Accepted for IQ/OQ / accepted for pilot (PQ) / not accepted |

| Role | Name | Signature | Date |
| --- | --- | --- | --- |
| Aimedics engineer | | | |
| Hospital IT lead | | | |
| Site PI | | | |
| Product owner | | | |

## Change history

| Version | Date | Author | Change |
| --- | --- | --- | --- |
| 0.1 | 2026-11-07 | Claude for Aimedics | First draft, from TB-REV-006 finding M-11. Expands TB-DS-04 §7.3; SAT-08 "pre-fill write" removed because M1 is read-only (BD-05). |
| 0.1a | 2026-11-07 | Claude | Consistency pass: OQ-12 sample 50 → 200 notes to match TB-DS-01/03/04. |
| 0.1b | 2026-11-07 | Claude for Aimedics | TB-REV-006b: OQ-06 names SRS AM-01 and checks ruleset approval and consent release (R2-02, BD-13, BD-15); planned IQ/OQ/PQ dates per TB-DS-00 §2 (R2-01). |
| 0.2 | 2026-11-07 | Claude for Aimedics | TB-REV-006c: PR-07 PI device path (C-16), PR-08 clinic-PC layout, PR-09 REDCap project inspection and link (C-06, C-17), PR-10 baseline (C-03), PR-11 funded reviewers (C-04); OQ-06 two sign-offs, BD-17 step-up, no scores (C-08, C-09, C-11); OQ-06a study set-up and explainer per BD-15 (C-05, C-07); OQ-06b flow-B gate (C-19); OQ-11 project link; OQ-14 fixed label list with proposed JA / zh-TW terms (C-10, C-15, C-28); PQ-04 clinic-day list and grouping (C-13, C-20); PQ-06 Phase 1 and PQ-06a Phase-2 readiness (C-01, C-21); PQ-07 adds research office and device path (C-18). |
| 0.3 | 2026-11-07 | Claude for Aimedics | TB-REV-006d: §1 both date sets and the TB-DS-00 §2 content table (D-19, D-02); PQ-04 split into PQ-04 at go-live and PQ-04a at week 6; T6/T7 moved from PQ-07 to PQ-06a (D-02); PR-10 baseline window ends before Phase 1 (D-08); OQ-06b adds an opt-out registry case (D-20); "shadow-mode go-live" removed (D-01). |
| 0.4 | 2026-11-07 | Claude for Aimedics | TB-REV-006e: PQ-07 / PQ-06a split task by task to match TB-DS-00 §2 (E-01); OQ-12 states the go-live pipeline must pass N-07 (E-09). |
| 0.5 | 2026-11-07 | Claude for Aimedics | TB-REV-006f: marked hospital stage (H); not a build gate. |
| 0.6 | 2026-11-07 | Claude for Aimedics | TB-REV-006g §F F-10 (optional): "Pilot dates" cites TB-DS-00 §2.H. |
