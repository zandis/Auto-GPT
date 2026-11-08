# TB-DS-09 User Interface and Interaction Specification

| Field | Value |
| --- | --- |
| Document | TB-DS-09 UI / UX specification |
| Version | 0.10 (reference; frozen for the build stage) |
| Date | 2026-11-07 |
| Owner | Aimedics (author: Claude, for Changfu Kuo) |
| Status | Frozen reference for the build stage (TB-DS-20). Closes review finding M-03 (TB-REV-006). Implements FR-UI-01..11, FR-CHAT-01..07, and the UI parts of FR-FEAS, FR-SCR, FR-CASE, FR-EDC, FR-CON, FR-TC, FR-AUTH (TB-DS-01). |
| Approvals | Product owner: — · Clinical lead JP (PI): — · Clinical lead CGMH (PI): — · CRC representative: — |
| Build stage | The **Release** column of §2 now gives the build step (S1–S5), S0 (built, kept), H (hospital stage) or L (later), per `20-build-map.md`; the old tag is kept as "(was …)". The `auditor` column and every TOTP step-up are H. |
| Canonical values | TB-DS-00 (roles BD-03, BD-04 reveal rule, BD-08 AE dismissal, BD-13 ruleset approval (one page, one Approve, F6-07), BD-15 consent explainer, BD-16 pilot phases, BD-17 step-up, BD-18 screening number, N-05 session, N-13 latency). |

## 1. Purpose and principles

This document specifies every screen, its role access, layout, states, copy rules, keyboard flow, language and accessibility behaviour. It is the reference for building the console (`services/console`) and the REDCap External Module panels, and for usability testing (TB-DS-04).

| # | Principle | Rule that follows |
| --- | --- | --- |
| P1 | The person decides | Every model output is a card with evidence; the system never excludes, enrolls, saves a form or releases anything on its own (FR-UI-05, FR-CHAT-05). The one exception is the consent explainer: the **committee-approved file** uploaded to the study's approval record goes live automatically once the record is complete and confirmed (BD-15). |
| P2 | Negative is a question, not a verdict | On "does not meet", the primary action is **Send to PI**, never Exclude (FR-UI-06). |
| P3 | Evidence before conclusion | Each card shows the quote, its date and source type before the verdict label. |
| P4 | One screen, one job | Each page has one primary task and one primary button. |
| P5 | Simple first | Each role lands on its work list with one command field in the header (FR-UI-01, S1); advanced filters are folded. |
| P6 | Least data | Pseudonyms by default; chart numbers only after an audited reveal (BD-04, FR-UI-10). |
| P7 | Familiar to the site | Labels in the site language, local date display, hospital terms (TB-DS-10). |
| P8 | Pilot phase is visible (H, hospital stage only) | During pilot Phase 1 every page shows "Pilot phase 1 – keep your usual screening; this list adds to it"; in Phase 2 "Pilot phase 2 – TrialBox list first; spot-check list shown" (BD-16). |
| P9 | No added load | A screen or notice is added only if it removes a larger task for the same role; no value already held in EMR, DWH or REDCap is typed again; most screens need one click (TB-DS-17 §2, NFR-USAB-06..08). |
| P10 | No scores for clinicians | `investigator` and `coordinator` never see a numeric score, probability, confidence or model name (FR-UI-17); evidence is the quote, its date and "from records" / "from note". |
| P11 | Nothing research before consent | Before consent the system never asks for a research procedure; missing data is worded "would need checking after consent" (FR-SCR-12). |

**Intended-use label** (footer of every page and every report, fixed text, localised): "TrialBox helps research staff find and check possible study participants. It does not diagnose, treat or decide eligibility. A qualified investigator makes every decision." (non-device positioning, TB-DS-03).

## 2. Roles and screen access

Roles per BD-03. "P" = pseudonyms only; "R" = may reveal chart number for patients in own study scope (audited).

| Screen | admin | coordinator | investigator | viewer | cro | auditor | Release |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S1 Header command field on every page (home = role work list S16 / S8 / S13 / S4) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (H) | S4 (was M1 as a separate entry screen) |
| S16 PI home "This week" | — | — | ✓ | — | — | — | S4 (was M1 (grouping and clinic-PC layout before pilot week 7, TB-DS-00 §2; AE cards M2)) |
| S17 RA / data status home | — | ✓ (study scope) | ✓ | ✓ aggregates | — | — | H (data status); reconciliation L (was M1 (data status, before pilot week 7); reconciliation and imports M2 (TB-DS-00 §2)) |
| S18 PI list (clinic-day or Monday mail + page) | — | ✓ P/R | ✓ P/R | — | — | — | S2 (was M1 mail; PWA push M2) |
| S19 Notification settings | ✓ | ✓ | ✓ | ✓ | ✓ | — | S2 (delivery day and time); rest H (was M1 (e-mail); push M2) |
| S20 Ruleset approval (one page, one Approve) | — | ✓ prepare, pre-tick code mapping, Send to PI | ✓ Approve | — | — | ✓ read (H) | S2 (was M1, BD-13 v0.5) |
| S21 Study set-up | ✓ scope assignment on request only | ✓ edit (with `office` flag: sections 1, 3, 4, 5, 8 of all studies, read 2, 6–7) | ✓ confirm approval record and team | — | — | ✓ read | S3 (three sections); rest H (was M1 (FR-STUDY-07)) |
| S2 Feasibility input | — | ✓ | ✓ | ✓ | ✓ (own sponsor studies) | — | S1 (was M1) |
| S3 Feasibility report | — | ✓ | ✓ | ✓ (k=5 inside) | ✓ (k=10, N-01) | ✓ read | S1 (was built / M1) |
| S4 Study list | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | S1 (was built) |
| S5 PI workbench: patient list | — | ✓ P/R | ✓ P/R | — | — | — | S2 (was built) |
| S6 Chart panel with criterion cards | — | ✓ P/R | ✓ P/R | — | — | — | S2 (was built) |
| S7 Single-patient check (CASE) | — | ✓ | ✓ | — | — | — | S0 (was built) |
| S8 CRC home (Today, Marks today, pre-screens, this week, my studies) | — | ✓ | ✓ read | — | — | — | S4 (was study cards built; sections M1 (WP-17); tasks, queries M2) |
| S9 Consent explainer | — | ✓ view, upload approved file, switch off | ✓ view, confirm, switch off | — | — | ✓ read | S0 (draft); approved-file process H (was draft built; BD-15 v0.5 M1) |
| S10 Pre-fill side panel (REDCap) | — | ✓ | ✓ | — | — | — | L (was M2) |
| S11 Trial-conduct tasks (visits, AE, con-meds) | — | ✓ prepare | ✓ decide | — | — | — | L (was M2) |
| S12 Admin: users, roles, scopes | ✓ | — | — | — | — | ✓ read | S0 (was built) |
| S13 Admin: health, jobs, ingest, models, audit, support bundle | ✓ | — | — | — | — | ✓ read | S4 (tabs: health, jobs, data sources) (was built / M1) |
| S14 Login, 2FA, password | all | all | all | all | all | all | S0 (TOTP H) (was built + TOTP M1) |
| S15 Audit browser | ✓ | — | — | — | — | ✓ | H (was M1) |
| S22 My account | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | S4 (was M1) |
| S23 Site settings and retention | ✓ edit safe list | — | — | — | — | ✓ read | H (was M1) |
| S24 Data sources and ingest | ✓ | ✓ last ingest only | — | — | — | ✓ read | S4 (was M1 (button built)) |
| S25 Code mapping | ✓ | ✓ read | — | — | — | ✓ read | H (was M1) |
| S26 Jobs | ✓ | ✓ own studies | ✓ own studies | — | — | ✓ read | S4 (Cancel + Retry) (was list built; filters, cancel M1) |
| S27 Report archive (per study) | — | ✓ | ✓ | ✓ aggregates | ✓ sponsor copies | ✓ | L (was M1) |
| S28 Search results | ✓ | ✓ | ✓ | ✓ | ✓ studies only | ✓ | S4: merged into the header field (was M1) |
| S29 Help panel and user guide | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | S4 (help panel); user guide H (was M1) |
| S30 About | ✓ (models, hashes) | ✓ | ✓ | ✓ | ✓ | ✓ | L (was M1) |
| S31 First-run checklist | ✓ | — | — | — | — | — | H (was M1) |
| S32 Mail templates | ✓ | — | — | — | — | ✓ read | H (was M1) |
| S33 Patient notice and opt-outs | ✓ record | ✓ record | — | — | — | ✓ read | H (was M1 (notice public in hospital network)) |
| S34 Backup and restore | ✓ | — | — | — | — | ✓ read | H (was M1) |
| S35 Updates | ✓ | — | — | — | — | ✓ read | H (was M1) |
| S36 REDCap connection | ✓ | — | — | — | — | ✓ read | S3 (token + test only) (was M1) |
| S37 Notices received | ✓ | ✓ | ✓ | ✓ | ✓ | — | S4 (was M1) |

The **research office** (治験事務局 / 臨床研究支援センター; CGMH 臨床試驗中心) uses a `coordinator` account with the `office` flag (FR-STUDY-10): S4, S21 (all studies, edit with the study team), S3, the screening-log view and the annual-report export (FR-REP-09); no reveal unless also on a study team.

Tiles and menus show only allowed screens (FR-UI-02). A URL to a screen outside the role returns the "Not available for your role" page (§7), never a blank page or a stack trace.

## 3. Screen specifications

Each screen is specified by six attributes: **goal, layout, primary action, data shown, states, latency target**. The longer screen texts below give the detail; §3.1 gives the six attributes of every screen in one table, so no screen lacks one. §3.2 sketches the three role homes.

### S1 Header command field [build step 4; replaces the entry page and S28] (TB-REV-006f F6-06)

- **There is no separate entry page.** After login each user lands on their role work list: S16 (investigator), S8 (coordinator), S13 (admin), S4/S3 (viewer, cro).
- **Header, on every page:** site name, study selector, language, user menu, and one **command field** with placeholder 「何をしますか？」 / 「需要什麼？」 / "What do you need?".
- **The field does two things:** fixed commands (FR-CHAT, ICD-09: feasibility, patient list, check a patient, job status, help) and search (studies, pseudonyms, screening numbers in the user's scope; FR-PLAT-14). Enter submits. `started` → go to the result page; `confirm` → inline card "Start: SCREEN GZQO (latest list)?" with Start / Cancel; `suggest` → up to three chips; `forbidden` → one line, no detail on what exists; search results drop down grouped by kind.
- **"More" menu:** the former tiles (Feasibility, Patient lists, Check one patient, Consent explainer, Reports, Admin), only those the role may use (FR-UI-02).
- **First login:** a three-line "Getting started" card on the work list (language, your studies, try "Who fits <study> this week?").

### S2 Feasibility input [build step 1]

- **Goal:** get a count for draft criteria without writing a ruleset by hand (FR-FEAS).
- **Layout:** two columns on desktop. Left: paste box for criteria text (any of JA / zh-TW / EN) or upload (PDF, DOCX, TXT); study name; lookback (default 3 years); department filter. Right: parsed criteria list as editable rows (concept, code set from TB-DS-10, operator, value, unit, time window), each with a "how parsed" tooltip.
- **Primary action:** **Run feasibility**. Secondary: Save draft.
- **States:** parsing (spinner ≤ 3 s), parsed with warnings (unmapped concept row in amber with "Pick code" button), ready, queued (outside hours, shows when it will run per BD-11).

### S3 Feasibility report [built; additions in build step 1]

- Funnel table: step, criterion label, count, % of previous, with suppressed cells shown as "< 10" (external) or "< 5" (internal) (N-01).
- Breakdown by age band, sex, department; trend by year.
- "Data quality" box: snapshot date, sources included, unmapped-code rate.
- Actions: **Refresh** (same criteria and ruleset version on the newest snapshot; the earlier report is kept, FR-FEAS-13), Download PDF / XLSX (aggregate only), Send to sponsor (cro or coordinator, k=10 applied), Copy as text.
- Never shows patient-level rows.

### S4 Study list [built; kept, step 1]

- **Goal:** see the studies in the user's scope and open one.
- **Columns:** study code and name, type (trial / registry / observational), latest feasibility count, this week's candidates (trials) or new cohort members (registries), last run.
- **Action:** a row opens the study's home (S16 for the investigator, S8 study card for the coordinator, S3 for viewer and cro).
- **Empty state:** "No studies yet. Paste criteria in the command field to start a feasibility count."
- **Phone:** one card per study.

### S5 PI workbench — patient list [built; step 2]

- **Goal:** review this week's candidates for one study (FR-UI-03, FR-SCR).
- **Columns:** pseudonym, age band, sex, department, next visit date, summary state (meets N / unknown N / does not meet N), "new since last week" dot, PI mark. Default sort: next visit date ascending, then most criteria met.
- **Filters (folded):** state, department, mark, new only.
- **Row action:** Enter or click opens S6.
- **Reveal:** "Show chart no." button per row (coordinator/investigator with study scope); asks for a reason (dropdown: contact patient, check chart, other + text) and, only in a hospital install with TOTP on (H, BD-17), one TOTP code at the first step-up of the session; audited `reveal`; shown for 10 minutes, then hidden again (FR-UI-10, BD-04).
- **Screening number:** shown on the row once assigned at the first Approach mark (BD-18).
- **Phone (390 px):** card list instead of table: pseudonym, next visit, three state counts, mark buttons; no horizontal scroll (FR-UI-09). Data entry and reveal are desktop only.

### S6 Chart panel with criterion cards [built; step 2]

- **Layout:** left 40 %: patient summary (age, sex, main conditions, current medicines, last labs with dates); right 60 %: one card per criterion, grouped Inclusion / Exclusion, unknowns first.
- **Card:** see §4. Evidence quote links to the source document view with the span highlighted.
- **PI marks** (investigator), one vocabulary everywhere (FR-SCR-07): **Approach** · **Need info** · **Not suitable** (reason from the study's list, FR-STUDY-09) · **Not now, re-check on <date>**; for a patient followed by a non-investigator, **Ask treating doctor** replaces Approach (FR-SCR-07b). Coordinator sees marks read-only and can add notes.
- **No scores:** the built page shows `confidence` per criterion and the judge model name in the footer; both are removed in build step 2 (FR-UI-17).
- **Summary bar:** "6 of 9 met, 2 unknown, 1 needs PI" and the primary button **Send to PI** (coordinator) or **Mark candidate** (investigator).

### S7 Single-patient check (CASE) [built, S0]

Input: chart number (coordinator / investigator with study scope; audited) or pseudonym, and study. Shows progress (target ≤ 60 s, N-13), then S6 for that patient. If the model is unavailable (night window), shows `MODEL-UNAVAILABLE` text with the expected time (TB-DS-08 §2.3).

### S8 CRC home [study cards built; sections in build step 4; tasks and queries L]

**Order (fixed, TB-DS-17 §3.2):** (1) **Today**: visits today of candidates and enrolled patients by time, with the next step and, before consent, "would need checking after consent" items (FR-SCR-12, P11); (2) **Marks today** (FR-UI-18): PI marks made today on patients with a visit today, refreshed automatically every ≤ 60 s while the page is open, no mail or push; each row has "I'm going" (sets "CRC on the way" on the PI's screen, FR-SCR-07c) and the clinic room; "Ask treating doctor" items appear here too (FR-SCR-07b, step 4); (3) Tasks from PIs (L, FR-SCR-08); (4) Pre-screens to prepare; (5) Queries and data checks (L); (6) This week: visits in the next 7 days and pipeline counts; (7) My studies (folded, FR-UI-04a; built). Sections 1, 2, 4 and 6 and the contact outcome are built in step 4 (TB-DS-20). An **"I'm on duty today"** toggle in the header (one tap, default on; `on_duty_date`) decides who gets the Marks today pane and the in-hours notice (FR-UI-18, FR-NOTIF-03). One row per patient across studies, with study badges and the screening number once assigned (on-screen only, never in mail). "Do not contact" patients never appear (cascade S0). **Contact outcome** is one pick-list tap (FR-SCR-10c), default "Reached – visit booked"; others: Reached – declined · Not reached (retry date) · Not approached (physician decision) · Lost contact. Consent and enrolment are read from REDCap through the project link (FR-RC-16); the CRC writes the TrialBox screening number into the REDCap field `tb_screening_no` when creating the record, as they write it in their log today (BD-18).

**Built today (`a1e55fa`):** one card per study with feasibility line, this week's counts, registry counts and a next action (`home_crc.html`). "Today", "Marks today", the pipeline bar, tasks and the six-step bar are **not built**; sections 1, 2, 4 and 6 are build step 4 work, sections 3 and 5 are L (FR-SCR-08, FR-UI-04b). Contact itself happens outside TrialBox; the coordinator records the outcome.

### S9 Consent explainer [draft built, S0; approved-file process H]

One process, as TB-DS-00 BD-15 (v0.5); TB-TMPL-01 §6 describes the same steps for the committee.

- **Draft with the ICF:** when the study's ICF is added on S21, the explainer draft is generated (FR-CON-01/02) side-by-side with its source paragraphs and attached to the same ethics submission pack (TB-TMPL-01).
- **Approval record (on S21, section "Ethics"):** the coordinator enters committee, approval number, date, ICF version and **uploads the committee-approved explainer file** (stamped PDF or its text); the system computes its SHA-256; the investigator confirms on the same screen (one TOTP step-up if first in session, BD-17).
- **Committee wording edits without ICF amendment:** "Upload edited approved version" on the same record, with the committee letter date; no regeneration; the old file stays live until the investigator confirms (FR-CON-09).
- **Sponsored trial:** if the study is flagged industry-sponsored, go-live waits for "Sponsor approval of patient material received" (date, contact) (FR-CON-10).
- **States:** draft (with ICF) → submitted → approved file uploaded → confirmed → **live automatically** → superseded (new approved file or ICF amendment) or switched off; withdrawn automatically if the live file's hash no longer matches the record.
- **No Release button or command.** The page shows the state, the approval record, the file version and the ICF version.
- **Switch off:** a site setting (admin) and a study setting (coordinator or investigator with scope); then only the ICF is used.
- Templates with keigo / formal register; the model fills only defined slots (FR-CON-05). No reading-level score is shown (no agreed measure for JA / zh-TW; TB-REV-006c C-23); the committee judges readability. Sentence length per paragraph is shown as information only.

### S16 PI home — "This week" [build step 4; AE cards L]

- **Goal:** everything a PI must decide, readable in 3–5 minutes between patients on a phone or on the clinic PC beside the EMR (TB-DS-17 §3.1).
- **Order (fixed):** (1) Needs your decision: AE cards (L, BD-08), ruleset approvals (S20, one Approve), study approval records to confirm (S21), feasibility release requests, cross-site queries (L), oldest first; (2) Clinic candidates for today (on a clinic day) or the next 7 days, per study, in three groups (FR-UI-15): **Your clinic** (the PI is the appointment doctor) first, **Other study doctors** (folded), **Other doctors** (mark **Ask treating doctor**); sorted by visit time then most criteria met; marks Approach / Need info / Not suitable (FR-SCR-07); after Approach on a patient seen today the row shows "CRC notified" or "CRC on the way" (FR-SCR-07c); (3) Waiting for others ("Need info", "Ask treating doctor" items and their status); (4) My studies (folded): enrolment against forecast; link "Full study list by next visit" (S5).
- **Never shown:** admin and health data; job queues; model names, scores, confidence or probabilities (FR-UI-17); patients outside the PI's studies; chart numbers before reveal; any free-text input.
- **Phone (390 px):** sections 1 and 2 as cards; 3 and 4 behind "More". Marking is one tap (two with a reason for Not suitable).
- **Clinic PC (≤ 480 px beside the EMR, FR-UI-19):** same content in one column; used where the hospital does not let phones reach the network (TB-DS-15 PR-07).
- **Empty state:** "Nothing needs you today." No filler content.

### S17 RA / data status home [H; reconciliation and imports L]

- **Goal:** study data status for registries and observational studies (TB-DS-17 §3.3, §6.4).
- **Order:** (1) Data checks this week: reconciliation mismatches registry vs EMR, one row per item with registry value, EMR value, date and source; buttons **EMR right** (default when the EMR value is newer and structured) / **Registry right** / **Leave**; (2) Cohort changes: new candidates; for a **dynamic** cohort also members who no longer meet the definition; for an **enrolled** cohort membership is fixed and only new candidates are shown (FR-STUDY-02, set on S21); (3) Data status per study (last pull, record counts, missing-value rate per key field, last export); (4) Imports and their mapping status (L self-service, FR-ING-20).
- Nothing is written to REDCap in the build or at hospital stage (BD-05); "EMR right" records the decision and puts the item on the RA's REDCap to-do export. Later (L) it becomes a pre-fill card in S10.

### S18 PI list (clinic-day or Monday mail) [build step 2]

- **Mail:** default where the appointment source exists, **on the morning of each of the PI's clinic days at 07:00**: that day's candidates in the three groups of S16, the rest of the week folded below; fallback (no appointment source or PI's choice) **every Monday** after the weekend re-check (BD-11) with the next 7 days. One mail per PI covering all their studies: pseudonym, visit time and clinic, met / unknown / needs-PI counts, new marker. Pseudonyms only, one link to S16 and one to the full study list S5 sorted by next visit (BD-04, FR-MAIL-03). The mail must make sense with pseudonyms and counts alone when the PI's device cannot open the link. No mail on an empty day or week unless the PI opts in. **Never in the mail:** names, chart numbers, the screening number (D4, BD-18) or any score. **Build:** step 2 delivers the clinic-day mail with the Monday fallback (TB-DS-20).
- **Page:** S16 section 2 is the page form of the same list; S5 is the full study list (candidates beyond 7 days, stable patients seen every 4–12 weeks).
- **Without an appointment source:** "next visit: unknown", sorted by last encounter (FR-ING-03b); Monday delivery.

### S19 Notification settings [build step 2: delivery day and time; rest H]

- Per person: channel (e-mail; PWA push L; LINE/Teams L), PI list delivery (**each clinic day 07:00** by default where appointments exist, or Monday); **clinic days** are proposed from the appointment source (practitioner schedule, FR-ING-03b) and the PI confirms them once (`clinic_days`, TB-DS-07), delivery time of the daily digest, quiet hours (default 20:00–07:00 and weekends), snooze 1 day / 1 week (one tap), deputy PI for safety alerts.
- Defaults per role from TB-DS-17 §5.4; budget shown ("You get one list per clinic day and up to 2 approval batches a week").
- **PWA push (L):** "Add to home screen" from the TrialBox page; no app store. Push text never contains patient data, not even pseudonyms ("AD-01: 4 candidates this week · open TrialBox"). Opening requires login on the hospital network or VPN. No patient data is cached on the phone.
- Per study (coordinator, on S21): optional **in-hours immediate notice** for an Approach mark on a patient seen today (study and clinic room only), off by default, outside the weekly CRC count but at most 2 per day per CRC, sent only to the study's coordinators on duty (FR-NOTIF-03).
- Every notice ends with "Why you got this · Change settings".

### S20 Ruleset approval — one page, one Approve [build step 2] (TB-REV-006f F6-07; BD-13 as simplified)

- **Goal:** the investigator approves what the LLM-drafted ruleset means, on one page, with one button.
- **Rows:** one per criterion, grouped Inclusion / Exclusion: plain-language criterion, the **protocol quote** (section and page), operator and threshold, time window, how missing data is treated. The mapped codes and units (JLAC10 / MEDIS / YJ / local, TB-DS-10) are **folded under each row**.
- **Amber rows** (ambiguous wording, unmapped concept, edited by the coordinator) are on top; each must be opened once before **Approve all** becomes active. Tap budget: 2 plus one per amber row (NFR-USAB-08). Allowed on a phone when no row is amber.
- **Coordinator:** prepares the page, may edit local codes and **pre-tick** each row's code mapping (recorded as its own audit event), then **Send to PI**. Neither `coordinator` nor `admin` can approve (FR-AUTH-13).
- **Re-approval:** a new protocol version opens with **Changes since vN** (criteria added, removed, changed) at the top (FR-FEAS-12).
- The study's SCREEN runs once the investigator has approved.

### S21 Study set-up [build step 3: three sections; rest H; FR-STUDY-07]

- **Goal:** one page per study that holds every set-up input that decides what runs against patients and who sees what; filled once, mostly by the coordinator (or research office) with the study team, confirmed by the investigator.
- **In the build (step 3), three sections:** **Study and team** (section 1 and 3 below), **REDCap link** (section 4), **Options** (sections 5 and 7: reasons list, screening-number format, explainer on/off). Section 2 Ethics approval appears only when the site setting `ethics_gate` is on (off in DEV/TEST, TB-REV-006f F6-03); sections 6 and 8 are H. The full list is kept for the hospital stage.
- **Sections (hospital stage, one page, folded after completion):**
  1. **Identity and type:** study name and code, type (trial / registry / observational), cohort kind (enrolled / dynamic), consent scope (opt-in / opt-out / waiver), protocol version pinned to the ruleset, industry-sponsored flag.
  2. **Ethics approval:** committee, approval number, date, expiry, ICF version, "identified screening covered" (yes/no; FR-STUDY-06 gate for flow B), explainer file upload and versions (S9), sponsor approval of patient material (sponsored only). **Investigator confirms.** The gate applies to every study whose SCREEN or CASE job resolves identities, including opt-out registries (BD-20); help text: "Identified lists for this study need this record, whatever the study type."
  3. **Team and scope:** investigators, coordinators, SMO staff with expiry; treating-physician list for list grouping and who may introduce the study (BD-19): default **"as the approved protocol states"**; the coordinator records which the protocol allows: "treating physician" or "treating physician, or a study investigator after the treating physician has agreed (主治医の了承 / 主治醫師同意)". **Investigator confirms.** Account scopes are applied by `admin` on this request.
  4. **REDCap link:** project id, DAG, link mode (`tb_screening_no` field, default; or MRN where the project holds it and the site agrees), consent-date field and event, enrolment field, screen-fail field and choice map, withdrawal field, sponsor subject-number field (FR-RC-16). "Test link" reads three records and shows the join result.
  5. **Screening log:** screening-number format or the site's next number (BD-18); "Not suitable" reason list (default by study type, editable; FR-STUDY-09); retry limit before "Lost contact".
  6. **Notifications:** in-hours immediate notice on/off (default off); digest inclusion.
  7. **Explainer:** on/off for the study.
  8. **Forecast:** target n, screen-fail assumption, competing trials (the built `site_profile`, reused).
- **Rights (AM-01):** coordinator edits; investigator confirms sections 2 and 3; `admin` applies scope only; research office (`office` flag, FR-STUDY-10) edits sections 1, 3, 4, 5 and 8 for all studies of the site and reads sections 2 and 6–7, and never confirms; auditor reads.
- **Inputs already held elsewhere are not asked again** (NFR-USAB-07): the protocol version and ICF come from the documents already uploaded; team members are picked from existing accounts.

### S10 Pre-fill side panel in REDCap [L]

- Rendered by the External Module beside the REDCap data-entry form (TB-DS-08 ICD-07).
- Header: "Proposals for this form: 12 (8 from records, 4 from notes)". Loads ≤ 60 s (N-13); shows "computing" with progress until ready.
- One card per field, in form order; clicking a card scrolls REDCap to the field and outlines it.
- **Accept** fills the REDCap field (user still presses REDCap Save; status stays Unverified). **Accept all rule-filled** button for structured fields only; narrative fields one by one.
- Fields with ≥ 20 % edits + rejects over last 30 proposals show "Manual" and no proposal (N-10).

### S11 Trial-conduct tasks [L]

Visit window list (due, overdue, out of window), AE suggestion tasks graded with CTCAE v5.0 (TB-DS-10 §6) and con-med checks. AE task: coordinator can prepare (add note, attach evidence); only the investigator can **Confirm as AE** or **Dismiss with reason** (BD-08). Dismissal reasons: not clinically significant, known baseline, lab error, other (text).

### S12 Admin users [built, S0]

User table: name, role, affiliation, study scopes, expiry date (SMO/CRO accounts), 2FA status, last login, locked. Actions: add, edit scope, reset password, reset 2FA, disable. Every change audited. Expired accounts shown greyed out. Built today: add, scope, reset password (shown once), disable. Not yet built: 2FA status and reset (FR-PLAT-03), set-password link by mail (FR-PLAT-02), last login and locked columns.

### S13 Admin health [built; tabs in build step 4]

Tiles: last ingest (time, counts, validation rate), night schedule progress (BD-11 phases with times), job queue, GPU memory and model loaded, disk use and snapshot count (N-04), backup last success (N-15), audit chain verified (date, result), version and update history, **Export support bundle** (ICD-12). Red state for any failure with a "What to do" link to the runbook (TB-DS-04). Built today: service checks, models and policy, ingest button; the other tiles are FR-PLAT-28.

### S14 Login and 2FA [built, S0; TOTP H]

Username and password (built). Hospital stage only (H, BD-17): a TOTP 6-digit code after the password; first login enrols TOTP with a QR code and 10 recovery codes. Lockout after 5 fails for 15 min (N-06) with the message "Too many attempts. Try again at 14:35." Session ends after 30 min idle with a 2-minute warning dialog, and after 8 h absolute (N-05).

### S15 Audit browser [H]

Filter by date, user, action, study; shows entries with hash-chain status; export CSV for inspection. No PHI in the list (pid only); reveal events show who, when, reason.

### S22 My account [build step 4, FR-PLAT-04]

Name, role, affiliation, studies in scope, expiry date, last login. Actions: change password, language, (H only: re-enrol TOTP with the current code, recovery codes left), link to S19 notification settings.

### S23 Site settings and retention [H, FR-PLAT-07, FR-PLAT-25]

Read view of the site settings in plain words, grouped: hospital, people and mail, night schedule, small-cell limits, retention, data source, hardware. Editable fields (admin): hospital display name, admin contact, mail footer, night-schedule times, retention days within the allowed range. Other fields show "set by hospital IT in the settings file". Retention block: what is kept, for how long, next deletion run, last 10 deletions.

### S24 Data sources and ingest [build step 4, FR-PLAT-08]

Table, one row per source: type, last success, patients and records, validation rate, rejected rows (count, reason codes, no PHI), next run. Row opens the last 30 ingests. Button "Run ingest now" (built). Amber when the last success is older than 48 h.

### S25 Code mapping [H, FR-PLAT-09]

Coverage tiles per category (diagnoses, drugs, labs, procedures). Table of the top 50 unmapped local codes with counts and example display names. Actions: download mapping file, upload new file (validated, shows what changes, previous kept), run mapping check.

### S26 Jobs [list built; Cancel and Retry in build step 4, FR-PLAT-12]

Filters: study, type, state, date. Each job shows its steps and times. "Cancel" on queued or running jobs, with a confirmation; **"Retry"** on a failed job (same inputs); both audited.

### S27 Report archive [L, FR-PLAT-13]

Per study, newest first: kind (feasibility report, sponsor pack, PI list, screening log, consent explainer), date, ruleset version, data snapshot, made by, downloads. Re-download while within retention (N-03). The `cro` role sees sponsor copies only.

### S28 Search [merged into the S1 header command field in build step 4]

Not a separate screen: search runs from the S1 header field on every page. Matches study id or name, pseudonym, screening number; results grouped by kind and limited to the user's scope. A chart-number search asks for the reason and the step-up (BD-17), and is audited as a reveal.

### S29 Help panel and user guide [help panel step 4; user guide H; FR-PLAT-19, FR-PLAT-20]

"?" in the header opens a side panel for the current page: what the page is for, what each action does, who to ask (site contact). Link "Full guide for my role" opens the role's user guide (pages and printable PDF), in the user's language.

### S30 About [L, FR-PLAT-21]

Version, build, install date, update history, ruleset versions, open-source components and licences, support contact. Admin also sees model names, versions and file hashes (clinical roles never see model names, copy rule 9).

### S31 First-run checklist [H, FR-PLAT-06]

Shown on the admin home until done. Lines: settings valid · data source connected · first ingest done · code-mapping coverage seen · test mail sent and received · backup target reachable · first accounts created · full-size dry run done. Each line has a status and a link to the page that does it.

### S32 Mail templates [H, FR-PLAT-11]

List of notice kinds. Each opens a preview in EN/JA/zh-TW. Editable: site header, footer, signature, contact line. Clinical wording is fixed and shown greyed.

### S33 Patient notice and opt-outs [H, FR-PLAT-22, FR-PLAT-23]

Public part (no sign-in, hospital network only): the site's patient notice in the site's language and how to opt out. Signed-in part: "Record an opt-out" (chart number, date, received by), list of opt-outs (chart numbers shown only after an audited reveal), status "takes effect tonight" / "in effect".

### S34 Backup and restore [H, FR-PLAT-26]

Per item (configuration, pid map, rulesets, registry, audit, month-end snapshots): last backup time, size, result, target. Next run. "Test restore" restores into a scratch area and reports audit-chain and count checks. Text explains the one-command full restore.

### S35 Updates [H, FR-PLAT-27]

Installed version and history. "Upload update": checks the signature, shows the change list, then "Apply". "Roll back to previous version" keeps data. Both audited.

### S36 REDCap connection [build step 3: token and test only, FR-PLAT-10]

Base URL, REDCap version found, token (enter once, then masked), "Test connection", linked projects with their study (link details in S21).

### S37 Notices received [build step 4, FR-PLAT-17]

My notices, newest first: date, kind, study, link. Lets a PI open last Monday's list without searching mail.

### 3.1 Six attributes of every screen

Latency targets are N-13 (TB-DS-00 §4): page ≤ 2 s p95, command-field reply ≤ 3 s, single-patient check ≤ 60 s, one-form pre-fill ≤ 60 s. "Standard states" means loading, empty, error and role-not-allowed as in §7.

| Screen | Goal | Layout | Primary action | Data shown | States | Latency |
| --- | --- | --- | --- | --- | --- | --- |
| S1 Header command field | Start any task or find anything from any page | Header bar: site, study selector, language, user menu, command field, "More" | Enter (run command or search) | Command results, search hits in scope | idle · started · confirm card · suggestions · forbidden · no match | ≤ 3 s reply |
| S2 Feasibility input | Count patients for draft criteria | Two columns: criteria text / parsed rows | Run feasibility | Parsed criteria, codes, warnings | parsing · warnings · ready · queued (night) | parse ≤ 3 s; page ≤ 2 s |
| S3 Feasibility report | Read the funnel and breakdowns | Funnel table, breakdown panels, data-quality box | Refresh / Download | Aggregates only, suppressed cells | running · done · stale snapshot · suppressed | page ≤ 2 s; report per NFR-PERF-07a/b |
| S4 Study list | Open a study in scope | One table (phone: cards) | Open study | Study, type, counts, last run | standard; empty "No studies yet" | ≤ 2 s |
| S5 PI workbench | Review this week's candidates of one study | Table (phone: cards), folded filters | Open patient (Enter) | Pseudonym, visit, state counts, mark, screening no. | standard; revealed (10 min); new-since dot | ≤ 2 s |
| S6 Chart panel | Decide on one patient from evidence | Left summary 40 % / right criterion cards 60 % | Mark (investigator) / Send to PI (coordinator) | Summary, cards with quotes and dates | unknowns first; error card; marked | ≤ 2 s |
| S7 Single-patient check | Check one patient against one study now | Input row, progress, then S6 | Check | S6 content for that patient | running · model unavailable · done | ≤ 60 s |
| S8 CRC home | Run today's study work in one place | Seven fixed sections, header on-duty toggle | Contact outcome (one tap) / I'm going | Today's visits, marks today, this week, my studies | standard; auto-refresh ≤ 60 s; off duty | ≤ 2 s; refresh ≤ 60 s |
| S9 Consent explainer | See the explainer and its approval state | Explainer with source paragraphs; state line | Upload approved file (H) / Switch off | Explainer text, approval record, versions | draft · submitted · approved · confirmed · live · superseded · off · withdrawn | ≤ 2 s |
| S10 Pre-fill panel (L) | Accept proposed values into a REDCap form | Side panel beside the REDCap form, one card per field | Accept | Proposed value, quote, checks | computing · ready · manual field · REDCap error | ≤ 60 s per form |
| S11 Trial-conduct tasks (L) | Act on visit windows, AEs, con-meds | Task list grouped by kind | Confirm as AE / Dismiss with reason (investigator) | Window dates, AE term and grade, con-med flag | due · overdue · out of window · prepared · decided | ≤ 2 s |
| S12 Admin users | Manage accounts and scopes | User table, side form | Add user | Name, role, affiliation, scopes, expiry, 2FA (H), last login | standard; expired greyed; locked | ≤ 2 s |
| S13 Admin health | See whether the box is healthy and what to do | Tiles, tabs (health, jobs, data sources) | Export support bundle | Ingest, night schedule, queue, GPU, disk, backup, audit check | green · amber · red with "What to do" | ≤ 2 s |
| S14 Login and 2FA | Sign in safely | Centred form | Sign in | Username, password; TOTP (H) | idle · wrong password · locked until hh:mm · expiry warning | ≤ 2 s |
| S15 Audit browser (H) | Inspect who did what | Filter bar, result table | Export CSV | Audit entries with chain status (pid only) | standard; chain broken (red) | ≤ 2 s for 1,000 rows |
| S16 PI home | Decide everything due in 3–5 minutes | Four fixed sections; phone cards; clinic-PC column | Mark (one tap) | Decisions due, today's candidates in three groups, waiting items | standard; "Nothing needs you today" | ≤ 2 s |
| S17 RA data status (H) | Keep study data in step with the EMR | Four sections | EMR right / Registry right / Leave (L) | Mismatches, cohort changes, data status | standard; no mismatches | ≤ 2 s |
| S18 PI list mail | Get the list before clinic without opening anything | Mail: today's three groups, week folded, two links | Open S16 | Pseudonyms, visit time, counts | clinic-day · Monday fallback · no mail when empty | sent by 07:00 |
| S19 Notification settings | Choose when lists and digests arrive | One form per person; study section on S21 | Save | Channel, days, time, budget | standard; saved | ≤ 2 s |
| S20 Ruleset approval | Approve what the ruleset means | One page, rows by Inclusion / Exclusion, codes folded | Approve all (investigator) / Send to PI (coordinator) | Criterion, protocol quote, operator, window, missing-data rule | amber rows first · all opened · approved · changes since vN | ≤ 2 s |
| S21 Study set-up | Hold every set-up input of a study | One page, numbered sections, folded when complete | Save section / Confirm (investigator) | Type, team, REDCap link, screening log options | incomplete · complete · confirmed · link test result | ≤ 2 s; link test ≤ 10 s |
| S22 My account | See and change one's own account | One card | Change password | Name, role, scopes, expiry, last login | standard; saved | ≤ 2 s |
| S23 Site settings (H) | Read and adjust site settings within limits | Grouped read view, editable fields marked | Save | Settings, retention, next deletion | standard; value out of range | ≤ 2 s |
| S24 Data sources | See whether data arrives | One row per source, row detail | Run ingest now | Last success, counts, validation, rejects | green · amber (> 48 h) · red | ≤ 2 s |
| S25 Code mapping (H) | Close gaps in code mapping | Coverage tiles, unmapped table | Upload mapping file | Coverage per category, top 50 unmapped | standard; validation diff | ≤ 2 s |
| S26 Jobs | Follow, cancel or retry a job | Filter bar, job list, step detail | Cancel / Retry | Type, state, steps, times | queued · running · done · failed · cancelled | ≤ 2 s |
| S27 Report archive (L) | Re-download a past report | Per-study list, newest first | Download | Kind, date, versions, snapshot | standard; expired (outside retention) | ≤ 2 s |
| S28 Search | (merged into S1) | — | — | — | — | — |
| S29 Help panel | Know what this page does and who to ask | Side panel from "?" | Open full guide (H) | Page help, actions, site contact | open · closed | ≤ 1 s |
| S30 About (L) | Know the version and components | One page | Copy version | Version, build, licences; models for admin only | standard | ≤ 2 s |
| S31 First-run checklist (H) | Finish installation | Checklist on admin home | Open the linked page | Eight lines with status | done · open · failed | ≤ 2 s |
| S32 Mail templates (H) | Adjust site parts of notices | List, preview in three languages | Save | Header, footer, signature, contact | standard; fixed clinical text greyed | ≤ 2 s |
| S33 Patient notice and opt-outs (H) | Publish the notice; record opt-outs | Public notice; signed-in form and list | Record an opt-out | Notice text; opt-outs (pid until reveal) | takes effect tonight · in effect | ≤ 2 s |
| S34 Backup and restore (H) | Know backups work | One row per item | Test restore | Last backup, size, result, target | ok · failed · restore running · restore checked | ≤ 2 s |
| S35 Updates (H) | Apply or roll back an update | History, upload area | Apply / Roll back | Version, change list, signature check | signature ok · signature failed · applied · rolled back | ≤ 2 s; apply per TB-DS-04 §9.4 |
| S36 REDCap connection | Connect the REDCap instance | One form, linked projects list | Test connection | Base URL, version found, masked token | not set · ok · failed with reason | test ≤ 10 s |
| S37 Notices received | Find a past notice | List, newest first | Open | Date, kind, study, link | standard; empty | ≤ 2 s |

### 3.2 Layout sketches of the role homes

Sketches fix region order, not visual design. Widths: desktop ≥ 1280 px; phone 390 px.

```
S16 PI home (phone)                      S8 CRC home (desktop)
┌──────────────────────────────┐        ┌──────────────────────────────────────────────┐
│ ☰  TrialBox · [command field]│        │ TrialBox · study ▾ · [command field] · On duty ●│
├──────────────────────────────┤        ├──────────────────────────────────────────────┤
│ 1 Needs your decision (2)    │        │ 1 Today            │ 2 Marks today (auto)     │
│   [Ruleset GZQO v2  Open]    │        │  09:30 P-7F2 next.. │  P-7F2 Approach [I'm going]│
├──────────────────────────────┤        ├─────────────────────┴──────────────────────────┤
│ 2 Today's clinic · Your clinic│       │ 4 Pre-screens to prepare                      │
│   P-7F2 10:20  6✓ 2? 1!      │        ├──────────────────────────────────────────────┤
│   [Approach][Need info][Not] │        │ 6 This week: visits and pipeline              │
│   ▸ Other study doctors (3)  │        ├──────────────────────────────────────────────┤
│   ▸ Other doctors (2)        │        │ 7 My studies (folded)                         │
├──────────────────────────────┤        └──────────────────────────────────────────────┘
│ More: 3 Waiting · 4 Studies  │
└──────────────────────────────┘        S13 Admin home (desktop)
                                         ┌──────────────────────────────────────────────┐
                                         │ Tabs: Health · Jobs · Data sources            │
                                         │ [Ingest][Night schedule][Queue][GPU][Disk]   │
                                         │ [Backup][Audit chain][Version] [Support bundle]│
                                         └──────────────────────────────────────────────┘
```

## 4. Card component

Schema: TB-DS-08 ICD-07 `card.schema.json` (shared by console and REDCap module).

**Layout (top to bottom):** state pill · title (criterion or field label) · proposed value (pre-fill) · evidence quote(s) with date and source type, newest first, max 3 shown + "more" · checks (validator results) · conflicts (two sources disagree) · provenance line ("from records" or "from note, 2026-12-01"; model build and prompt version only in the admin/auditor footer and the audit record, FR-UI-17) · actions.

**State pill colours** (with text, never colour alone): meets = green "Meets"; does_not_meet = grey "Does not meet — PI to confirm"; unknown = amber "Unknown — data missing"; needs_check = blue "Check"; human = purple "Decided by <role>"; error = red "Could not check".

**State machine:**

```
             ┌──────── edit ────────┐
needs_check ─┼─ accept ─► accepted   │
   │         ├─ reject ─► rejected   ▼
   │         └─────────────────► edited
   ├─ (criterion verdict) ─► meets | does_not_meet | unknown
   │        any verdict ── PI mark ──► human
   └─ (AE) ── investigator dismiss(reason) ──► dismissed
error ── retry ──► needs_check
```

Rules: a model may move a card only to meets / does_not_meet / unknown / needs_check / error. Only a person moves it to accepted, edited, rejected, human or dismissed. Every person transition is audited with user and time; edits store the before and after value.

## 5. Keyboard and interaction

| Key | Action | Where |
| --- | --- | --- |
| J / K | next / previous card or row | S5, S6, S10, S11 |
| Enter | open selected row / source | lists, cards |
| A | accept / primary action | cards |
| E | edit value | pre-fill cards |
| R | reject (asks reason) | cards |
| P | send to PI | criterion cards (coordinator) |
| / | focus the header command field or the filter box | all |
| ? | show shortcuts | all |
| Esc | close panel / dialog | all |

Shortcuts are off inside text inputs. All actions also reachable by mouse and by Tab order (FR-UI-07). Destructive or outward actions (reject, send to sponsor) ask once for confirmation.

## 6. Language, dates and numbers

| Item | Japan sites | Taiwan sites | English |
| --- | --- | --- | --- |
| Default UI language | 日本語 | 繁體中文 | English (selectable everywhere) |
| Date display | 2027-01-15 with optional 令和9年1月15日 (FR-UI-08a) | 2027-01-15 with optional 民國116年1月15日 (FR-UI-08b) | 15 Jan 2027 |
| Date input | accepts 西暦 and 和暦 (R9.1.15, 令和9年1月15日) | accepts 西元 and 民國 (116/1/15) | ISO |
| Numbers | half-width digits; thousands separator "," | same | same |
| Names of people | family name first | family name first | as stored |
| Units | UCUM with local display (mg/dL) | same | same |

**PI mark labels to review with native speakers (TB-DS-15 OQ-14, WP-07; TB-REV-006c C-28).** The built labels 「対応する」 (means "handle") and 「対象外」 (reads as "ineligible") are replaced by proposals for review:

| Mark | English | 日本語 (proposal) | 繁體中文 (proposal) |
| --- | --- | --- | --- |
| Approach | Approach | 声をかける | 邀請 |
| Need info | Need info | 情報が必要 | 需要更多資訊 |
| Not suitable | Not suitable now | 今回は見合わせる | 暫不邀請 |
| Not now | Not now, re-check on … | 後日再確認（日付） | 稍後再評估（日期） |
| Ask treating doctor | Ask treating doctor | 主治医に確認 | 詢問主治醫師 |

Translations live in the Python catalogues `services/console/i18n.py` and `i18n_home.py` (as built), with the test that every key exists in every language (TB-REV-006f F6-20); a missing key falls back to English and is logged. Clinical terms come from TB-DS-10, not free translation. Further languages are added by a translation file only (all-languages requirement; patient materials via FR-CON-02).

## 7. Empty, loading and error states

| Situation | Message (EN; localised) | Action offered |
| --- | --- | --- |
| No candidates this week | "No new candidates for GZQO this week. Last checked 03:12." | Check one patient · Change criteria |
| Snapshot older than 48 h | Amber banner "Data is from 3 Jan — tonight's update did not finish." | Admin: open health page |
| Job running | Progress bar with step names | Leave page (job continues), notify on finish |
| Model unavailable | "Checking is paused until 06:00 for the night update." | Queue the request |
| Role not allowed | "This page is not available for your role." | Back to my work list |
| Upstream (REDCap) error | "REDCap did not respond. Your form is unchanged." | Retry |
| Validation error | Field-level message under the field | Fix and resubmit |
| Unknown error | "Something went wrong. Reference 01JC…" | Copy reference for admin |
| Night update running (FR-PLAT-18) | Grey banner "Night update running until 06:00; lists show yesterday's data." | None |
| Page not found | "This page does not exist. It may have moved." | Back to my work list |

Error pages never show stack traces, SQL or PHI.

## 8. Copy rules

1. Plain words; sentence case; one idea per sentence; ≤ 20 words per sentence in labels and messages.
2. Never "excluded", "ineligible", "not eligible" or "rejected patient" for a model output **or for a human mark**; use "does not meet — PI to confirm" and "Not suitable now". In Japanese avoid 対象外 / 除外 / 不適格; in Chinese avoid 排除 / 不符資格.
3. State the source and date with every clinical claim ("HbA1c 8.2 % on 2026-12-01, lab").
4. Japanese: です・ます調 in UI; patient-facing text uses fixed keigo templates (FR-CON-05). Chinese: formal register 您.
5. No blame in errors; say what happened and what to do next.
6. Buttons are verbs: "Send to PI", "Run feasibility", "Approve all".
7. Numbers below k are shown as "< 10" / "< 5", never as 0 or blank.
8. Before consent, never word missing data as something to collect; write "Would need checking after consent: …" (P11). After consent: "To collect at the screening visit".
9. No numbers from the model (scores, confidence, probabilities) and no model names on clinician screens (P10).

## 9. Accessibility

Target **WCAG 2.2 level AA** for every console page and notice. The criteria that shape this design, with how each is met:

| WCAG 2.2 criterion | How TrialBox meets it | Checked by |
| --- | --- | --- |
| 1.1.1 Non-text content | Icons carry labels; state pills carry text | axe-core in the browser walk |
| 1.3.1 Info and relationships | Tables use header cells; card regions are landmarks | axe-core |
| 1.4.1 Use of colour | State pills and amber rows carry text, never colour alone (§4) | Manual pass |
| 1.4.3 Contrast (minimum) | Text ≥ 4.5:1, large text ≥ 3:1 in both themes | axe-core |
| 1.4.10 Reflow | 390 px phone and ≤ 480 px clinic-PC layouts without horizontal scroll (§10, FR-UI-09, FR-UI-19) | Browser walk |
| 1.4.12 Text spacing | No clipped text with increased spacing (JA and zh-TW line height 1.7) | Manual pass |
| 2.1.1 Keyboard | Every function keyboard-operable (§5, FR-UI-07) | Browser walk |
| 2.2.1 Timing adjustable | Session-expiry warning 2 minutes ahead with "Stay signed in" (S14, N-05) | Browser walk |
| 2.4.7 Focus visible / 2.4.11 Focus not obscured (minimum) | Visible focus ring; sticky header never covers the focused control | Manual pass |
| 2.5.8 Target size (minimum) | Targets ≥ 24 × 24 px; PI mark buttons ≥ 44 × 44 px on phone | Browser walk |
| 3.1.1 / 3.1.2 Language of page and parts | `lang` set per page and on quoted source text in another language | axe-core |
| 3.3.1 Error identification | Field-level messages (§7) | Browser walk |
| 3.3.7 Redundant entry | Values already held are not asked again (P9, NFR-USAB-07) | Design review of each new form |
| 3.3.8 Accessible authentication (minimum) | Password managers and paste allowed; the TOTP code (H) may be pasted | Manual pass |
| 2.3.3 / reduced motion | Respects `prefers-reduced-motion`; no auto-moving content except the Marks today refresh, which does not move focus | Manual pass |

Zoom to 200 % without loss. axe-core runs with zero serious or critical violations in every step's browser walk (NFR-USAB-04, TB-DS-04 §3.5); a manual keyboard pass is done at step 4 and at each hospital release.

## 10. Responsive layout

| Width | Layout |
| --- | --- |
| ≥ 1280 px | Full two-column layouts (S2, S6, S9) |
| 768–1279 px | Columns stack; card panel becomes a drawer |
| 390–767 px | Phone: role work list with the header field, S16 PI home, S20 approval, S3 report, S5 card list, S6 read-only and PI marks only (FR-UI-09); installable as a PWA later (L, S19) |

## 11. Usability acceptance

**Build stage:** step 4 checks the tap budgets of NFR-USAB-08 (S2) with the e2e browser walk; no tap budget counts a TOTP entry. The formative test below is hospital stage (H).

**Formative test in two rounds (TB-REV-006c R-03; TB-PLAN-01 WP-00b):** round 1 on S20, S21 and the list mail before feature freeze (MS-05c, 2026-12-18), round 2 on S16, S8, S18 and S19 before pilot week 7 (MS-05d), on clickable prototypes, with 3 CRCs, 2 PIs and 1 research-office member per site, in Japanese and Mandarin; script in TB-TMPL-07. Tasks: (1) PI: on a phone, open today's list and mark two candidates, one "Ask treating doctor"; (2) PI: sign off the clinical criteria of a 20-criterion ruleset with two amber rows (S20, one Approve); (3) CRC: from "Marks today", go to an Approach mark and record the outcome; (4) CRC: pre-tick the code rows of the same ruleset on S20; (5) CRC / research office: set up a study on S21 including the ethics record and the REDCap link test; (6) CRC: export the screening log; (7) RA: resolve three reconciliation items; (8) everyone: read the Monday or clinic-day mail without opening the link. Measures: task success, taps (TOTP not counted), time, and **misreadings** of "Not suitable", of pre-consent items and of any number shown. Pass: each task completed without help by ≥ 4 of 5 users of that role; no misreading of a mark or pre-consent item as an eligibility decision or a research order; taps within TB-DS-17 §9.2. SUS is collected but judged in the pilot (NFR-USAB-09). Results go into TB-DS-15 site acceptance and back into this document.

## 12. Open items

| ID | Item |
| --- | --- |
| UX-01 | Closed in v0.3: "Not now, re-check on <date>" adopted (FR-SCR-07); confirm in the formative test. |
| UX-02 | Confirm 和暦 / 民國 input acceptance with site staff (some prefer strict ISO). |
| UX-03 | REDCap module panel width inside REDCap 16 layouts (test on both sites' themes). |
| UX-04 | Reveal display time (10 min proposed) to be agreed with each site's privacy officer. |
| UX-05 | Real-time AE alert threshold (grade ≥ 3 proposed) and quiet-hours handling of safety alerts, with site PIs (TB-DS-17 CO-05). |
| UX-06 | Whether sites allow outbound Web Push for the later PWA (L; TB-DS-17 CO-02). |
| UX-07 | PI device path per site (phone on Wi-Fi/VPN, hospital phone, clinic PC only), TB-DS-15 PR-07; decides whether S16 phone or clinic-PC layout is primary. |
| UX-08 | Native review of the mark labels in §6 (TB-DS-15 OQ-14). |

## 13. References

| Ref | Document |
| --- | --- |
| [U1] | W3C Web Content Accessibility Guidelines (WCAG) 2.2, Recommendation 2023-10-05 (§9) |
| [U2] | ISO 9241-210:2019 Ergonomics of human-system interaction — human-centred design (artefacts of §1–§3) |
| [U3] | ISO 9241-110:2020 Interaction principles (principles P1–P11) |
| [U4] | TB-DS-00 (BD-03, BD-04, BD-13, BD-15, BD-17, BD-18, N-01, N-05, N-13), TB-DS-01 FR-UI, FR-CHAT, FR-PLAT, NFR-USAB, TB-DS-08 ICD-07 and ICD-09, TB-DS-10, TB-DS-17, TB-DS-19, TB-DS-20 |
| [U5] | Repository `trialbox/services/console` templates and `i18n.py`, `i18n_home.py` at `a1e55fa`; clinic workbench on branch `claude/project-thread-0iudms` commit `38d93ce` |

## Change history

| Seq | Version | Date | Author | Change |
| --- | --- | --- | --- | --- |
| 1 | 0.1 | 2026-11-07 | Claude for Aimedics | First draft. |
| 2 | 0.1a | 2026-11-07 | Claude for Aimedics | TB-REV-006b R2-22: S9 release by coordinator or investigator as requester (FR-CON-06, BD-15 proposed). |
| 3 | 0.2 | 2026-11-07 | Claude for Aimedics | Clinical workload pass with TB-DS-17: principle P9 no added load; role homes S16 (PI), S8 order (CRC), S17 (RA); S18 weekly visit list; S19 notification settings and M2 PWA push; S20 one-page ruleset approval (BD-13, TB-DS-00 v0.4); S9 rewritten for BD-15 v0.4 (explainer generated from and submitted with the ICF, released automatically, no Release button, switch-off); P1 exception; usability tasks updated; UX-05, UX-06. |
| 4 | 0.3 | 2026-11-07 | Claude for Aimedics | TB-REV-006c: P8 two pilot phases (C-01), P10 no scores (C-11), P11 nothing research before consent (C-15); S8 rewritten with true built state, Marks today pane, contact outcomes, screening number (C-06, C-12, C-14); S6 one mark vocabulary and Ask treating doctor (C-10, C-13); S5 TOTP step-up and screening number (C-08); S9 one BD-15 v0.5 process with uploaded approved file, committee-edit path, sponsor step, no reading-level score (C-05, C-23); S16 three groups, clinic-PC layout, CRC-notified status (C-13, C-14, C-16); S17 cohort kind (C-22); S18 clinic-day delivery (C-20); S19 in-hours notice; S20 two sign-offs (C-09); new S21 study set-up (C-07); research-office access note (C-18); card provenance without model name (C-11); mark labels for native review (C-28); copy rules 2, 8, 9; formative usability test with research office (R-03); UX-01 closed, UX-07, UX-08. |
| 5 | 0.4 | 2026-11-07 | Claude for Aimedics | TB-REV-006d: principles in order P8–P11 and research-office paragraph moved below the table (D-15); S8 and S18 release timing per the TB-DS-00 §2 table, S17 reconciliation M2 (D-02); screening number never in mail (D-03); S21 introduce rule per BD-19 (D-04), gate help text per BD-20 (D-20), `office` rights (D-11); S19 clinic days from the appointment source, budget text, N3 cap and on-duty routing (D-10, D-16, D-18); S20 tap budget with amber rows (D-09). |
| 6 | 0.5 | 2026-11-07 | Claude for Aimedics | TB-REV-006e: S16 tagged "before pilot week 7" (E-01); S8 Ask-treating-doctor go-live fallback; §2 screen table rejoined (E-07). |
| 7 | 0.6 | 2026-11-07 | Claude for Aimedics | Completeness audit (TB-DS-19): screens S22–S37 for platform pages (account, settings, data sources, code mapping, jobs, report archive, search, help, about, first-run, mail templates, opt-outs, backup, updates, REDCap connection, notices); night banner and page-not-found states. |
| 8 | 0.7 | 2026-11-07 | Claude for Aimedics | TB-REV-006f: Release column re-tagged to build steps / H / L (F6-01); S1 becomes the header command field, home = role work list, S28 merged (F6-06); S20 one page, one Approve, Changes since vN (F6-07, F6-27); S21 three sections in the build, ethics section only when `ethics_gate` is on (F6-03); new S4 section (F6-21); Refresh on S3, Retry on S26 (F6-27); translation files named as built (F6-20). Frozen as reference. |
| 9 | 0.8 | 2026-11-07 | Claude for Aimedics | TB-REV-006f §R: every §3 heading carries the §2 build tag (N7-04, F6-01c, F6-08); P8 and §11 formative test marked H; TOTP text in S5, S14, S22 marked H (F6-04); S8 sections renumbered 1–7 (F6-21); header and §11 follow the one-Approve S20 (F6-07). |
| 10 | 0.9 | 2026-11-07 | Claude for Aimedics | TB-REV-006g Q-27, Q-28, S-03, S-06, S-08: §3.1 six attributes (goal, layout, primary action, data, states, latency) for every screen; §3.2 layout sketches of the three role homes; S28 empty heading fixed; "entry page" wording replaced by the header field and role work list (P5, §2 S1 row, §5, §7, §10); §2 S20 row one Approve; remaining M1/M2/C in prose re-tagged; §9 WCAG 2.2 criteria table; References §13; Seq column. |
| 11 | 0.10 | 2026-11-07 | Claude for Aimedics | TB-REV-006g §R residue: UX-06 PWA tagged L; Status as frozen build-stage reference. |
