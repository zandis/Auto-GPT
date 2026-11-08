# TB-PLAN-01 Project Plan and Work Breakdown

| Field | Value |
| --- | --- |
| Document ID | TB-PLAN-01 |
| Title | Project Plan and Work Breakdown |
| Version | 0.7 |
| Date | 2026-11-07 |
| Owner | Product owner (Changfu Kuo) |
| Author | Claude (for Aimedics) |
| Status | **Superseded for the build stage** by `SIMPLE-PLAN.md` and `20-build-map.md` (owner direction 2026-11-07: Claude builds; no Japan-team hours, no pilot dates, no hospital gates). The engineer-hours plan below is kept as reference for a future hospital pilot (H). The pilot-dates decision card was withdrawn. |
| Related | TB-DS-00 §2 (scope baseline and the "M1 content by date" table, which this plan follows), TB-REV-006d D-02, D-05, D-06, D-08, TB-DS-04 §8 and §12, TB-DS-11, TB-DS-12, TB-DS-15, TB-DS-17, TB-TMPL-01, TB-TMPL-07, TB-REV-006 findings F-07, F-31, M-12, TB-REV-006c findings C-01..C-04, C-16, C-21 |

**Approvals**

| Role | Name | Signature | Date |
| --- | --- | --- | --- |
| Product owner | Changfu Kuo | | |
| Aimedics engineer | (to be named) | | |
| Japan maintenance team lead | (to be named) | | |
| Site PI, Japan head hospital | (to be named) | | |
| Site PI, CGMH | (to be named) | | |

## 1. Resources

| Resource | Capacity assumed | Notes |
| --- | --- | --- |
| Aimedics engineer (one person) | 35 productive hours per week | Reviews and integrates code written with Claude, runs tests on the GPU box, does site work. Coding by Claude reduces writing time, not review, testing, debugging on real hardware, meetings or site visits. |
| Claude | Not the constraint for writing code and documents | Cannot run anything at the hospitals, cannot sign, cannot attend committees. |
| Japan maintenance team | **Needed for the recommended dates (owner decision, MS-01a): about 15 h/week of engineering help from 2026-11-23 (≈ 150 h to 02-05) plus ≈ 70 h of WP-11 / WP-01 drafting, on top of ≈ 38 h already assigned below (WP-11 24 h, WP-01 8 h, WP-07 6 h): ≈ 260 h to 02-05.** Not yet confirmed; without it the dates are the one-engineer dates (§5). | Test running, translation and string review, Japanese user documentation, Japan site liaison, moderation of the Japanese formative sessions (WP-00b), later maintenance. |
| Site staff (each hospital) | IT contact ~4 h/week; PI time for ethics pack and SAT; 2 CRCs + 2 PIs for the workload baseline (≈ 10 min/day each for 2 weeks, WP-00) | Chart review is **not** site clinical time: it is a funded pilot-team line (§1a). |
| Research office (each hospital) | ≈ 2 h for the baseline, ≈ 30 min/week for the Phase-1 log upload (TB-DS-04 §8.9); recruits the formative-test participants (WP-00b) | 治験事務局 / 臨床研究支援センター (Japan), 臨床試驗中心 (CGMH). |
| External | Pentest firm; GPU box supplier | Booked separately. |

Available engineer time from Monday 2026-11-09 to Friday 2027-01-22: 11 weeks less about 1.5 weeks of year-end holidays = **about 9.5 weeks ≈ 330 hours**. To Friday 2027-02-05 (the week before the recommended Japan go-live): about **11.5 weeks ≈ 400 hours**.

**Hours by source to 2027-02-05 (TB-REV-006d D-05).** In engineer hours only: engineer ≈ 400 h + Japan-team engineering help ≈ 150 h + drafting moved to the Japan team ≈ 70 h ≈ **620 h against ≈ 630 h** to go-live (§5): about 10 h short, covered by the TB-DS-04 §12.5 cut order (chat box first) or by MS-01a confirming 16 h/week. The ≈ 38 h of translation and string review already assigned to the Japan team are other effort and are not counted. With the engineer alone: ≈ 400 h, so go-live is about 2027-03-15 (Japan) and 2027-03-29 (CGMH). WP-15 pilot support (96 h) starts at go-live and is **not** in the go-live totals; it is counted in the February–March capacity (§5).

### 1a. Pilot-only costs that are not clinical staff time (TB-REV-006c C-04)

| Line | Size | Who does it | Funding / backfill (to decide before the ethics submission, MS-04) |
| --- | --- | --- | --- |
| Chart review | ≈ 78 reviewer hours per study (TB-DS-04 §8.4: two reviewers for strata A and B, one for stratum C, PI adjudication ≈ 5 h). Japan: 1 study ≈ 78 h; CGMH: 1–2 studies ≈ 78–156 h | Funded reviewers: one coordinator-level reviewer and one physician per study | One of: research funds paying reviewer hours at each site's rate; an SMO CRC seconded for the review; reviewers from another department for strata B and C. Names and hours go into the ethics pack checklist (TB-TMPL-01 §8). A study without funded reviewers is not entered. |
| Phase-1 comparison log | ≈ 30 min/week research office + 1 h/week engineer per site | Pilot team (TB-DS-04 §8.9) | Inside WP-15 and the research office's normal duties |
| Workload baseline | ≈ 10 min/day × 4 people × 10 working days ≈ 7 h per site of clinical self-log, plus one observed clinic half-day | Site PI owns; research office administers | Accepted by the department head; noted to the ethics office where the hospital requires it (WP-00) |

## 2. Calendar constraints

| Date | Event | Effect |
| --- | --- | --- |
| 2026-12-29 to 2027-01-03 | Japanese year-end holidays (年末年始) | Japan site, Japan team and many vendors closed; the first week back (01-04 to 01-08) is atypical for clinic workload and is **not** used for the baseline |
| 2027-01-01 | Taiwan New Year's Day | CGMH closed one day |
| About 2027-02-05 to 02-10 | Lunar New Year holidays in Taiwan (New Year's Day falls on 2027-02-06; exact holiday dates per the Taiwan government calendar, unverified) | No CGMH install or go-live in that week |
| Monthly | Ethics committee meetings (both hospitals; exact dates to be obtained) | Submission is typically needed 2–4 weeks before the meeting; approval may need a second round |

## 3. Work breakdown structure

Hours are Aimedics engineer hours unless marked. "Dep." lists the work packages or external items it waits for.

### 3.1 Core pilot (M1, both variants need it)

| WP | Work package | Engineer h | Other effort | Dep. |
| --- | --- | --- | --- | --- |
| WP-00 | Workload baseline (TB-REV-006c C-03): one-page time-motion self-log and observation sheet (TB-TMPL-07 §2), raw NASA-TLX form (§3), 30-min training per site, data entry and summary | 8 | Per site: 2 CRCs + 2 PIs self-log 2 weeks (≈ 7 h total); research office 2 h; one observer for a clinic half-day | Department head agreement; ethics-office note where required |
| WP-00b | Formative usability test (R-03, TB-REV-006d D-06; script TB-TMPL-07 §4): round 1 on clickable prototypes of the go-live screens (S20, S21, list mail) by **MS-05c 2026-12-18**; round 2 on S16, S8, S18, S19 before pilot week 7 (MS-05d). Per site 3 CRCs, 2 PIs, 1 research-office member, 60 min each | 16 (round 1 prototypes 10, round 2 6) | Moderator: Japan team member (Japanese) and the CGMH research-office contact (Mandarin), ≈ 10 h each incl. notes; research office recruits participants | WP-17/19/20 screen specs (TB-DS-09) |
| WP-01 | Ethics and governance pack: pilot protocol section, opt-out notices JA/zh-TW, DPIA summary, chart-review protocol (TB-TMPL-01); submission at both sites | 40 | PI 10 h each, Japan team 8 h | — |
| WP-02 | End-to-end harness (stages 0–7 with stubs), REDCap API simulator, REDCap read connector, contract tests | 50 | — | — |
| WP-03 | Japan head hospital source reader (SS-MIX2 or vendor export) and site mapping | 60 | Site IT 16 h | Export specification from the site |
| WP-04 | CGMH source mapping (self-developed HIS / data warehouse; CGRD zone) | 40 | Site IT 16 h | CGMH schema |
| WP-05 | Japanese and Taiwanese normalisers (和暦/民國, NFKC, 疑い, 保険病名) | 24 | — | WP-03 |
| WP-06 | Free-text PHI pass (rules + NER + LLM tagger, surrogates) and Japanese PHI gate set | 70 | Two annotators 60 h | GPU box for tagger runs |
| WP-07 | Feasibility input page and fixed-command chat box (JA/zh-TW/EN) | 40 | Japan team 6 h string review | — |
| WP-08 | Security hardening: TOTP 2FA, auditor role, session and password rules, k=10 external small cells, MinIO → filesystem store, Mailpit, container and host hardening | 50 | — | — |
| WP-09 | Operations: health page, diagnostics bundle, signed bundles, SBOM, update and rollback | 50 | — | — |
| WP-10 | GPU: day/night scheduler on 1 × 5090 and 2 × 5090; gates G1–G3, G5–G7 on the real card; 500,000-patient synthetic dry run | 50 | — | GPU test box |
| WP-11 | Documentation: admin runbook, PI and CRC quick guides (EN source) | 30 | Japan team 24 h JA; CGMH contact or translator 16 h zh-TW | — |
| WP-12 | Pentest: scoping, two passes (infrastructure, application on frozen release candidate), fixes, retest | 40 | Pentest firm | Feature freeze |
| WP-13 | Install and site acceptance at the Japan head hospital (TB-DS-15) | 40 | Site IT 16 h, PI 4 h | Hardware delivered; WP-01 approval for PQ |
| WP-14 | Install and site acceptance at CGMH | 40 | Site IT 16 h, PI 4 h | As WP-13 |
| WP-15 | Pilot support, phase checkpoints and chart-review logistics, weekly Phase-1 log import (TB-DS-04 §8.9) (Feb–May, 8 h/week; starts at go-live, outside the go-live totals) | 96 | Funded reviewers ≈ 78 h per study (§1a) | Pilot live |
| WP-16 | Project management, CCB, release records (≈ 3 h/week) | 33 | — | — |
| | **Subtotal WP-01..WP-14, WP-16 (as in v0.2)** | **≈ 657** | | |

### 3.1a Clinical layer (M1, TB-REV-006c C-02)

Which of these are at go-live and which arrive before pilot week 7 follows the TB-DS-00 §2.H "M1 content by date" table; the go-live column below is that table's go-live column. These packages carry the TB-DS-01 v0.3 clinical-layer requirements (FR-UI-14..16, FR-NOTIF-01..05/08/09, FR-STUDY-01..03/06, FR-FEAS-11/12, FR-ING-19/21, FR-REP-06/09, FR-AUTH-13, NFR-USAB-06..10) and the TB-REV-006c fixes. They had no hours in v0.2. TB-DS-01 v0.4 rows FR-SCR-07b/07c/10c, FR-CON-09/10, FR-RC-16, FR-UI-17..19, FR-REP-09, FR-STUDY-06..10 and FR-AUTH-05d (BD-17) are inside these packages.

| WP | Work package | Engineer h | Of which needed at go-live (Phase 1) | Release line | Dep. |
| --- | --- | --- | --- | --- | --- |
| WP-17 | Role homes and approval: S16 PI home (phone and clinic-PC ≤ 480 px layouts, built weekly list reused), S8 M1 sections "Today", "Marks today" (auto-refresh), "This week", S17 RA status; S20 approval (superseded: one page, one Approve by the `investigator`, BD-13 / F6-07) with FR-AUTH-13; one mark vocabulary with per-study reasons and "Ask treating doctor"; removal of `confidence` and `judge_model` and any score or model name from clinical pages, built `patient.html` included (FR-UI-17); "Marks today" pane (FR-UI-18); clinic-PC layout (FR-UI-19); treating-doctor routing (FR-SCR-07b/07c); pre-consent wording | 75 | 35 (S20 approval, FR-AUTH-13, BD-17 step-up, score removal FR-UI-17, mark vocabulary, wording) | Go-live + M1 Feb–Mar line (homes) | WP-07 |
| WP-18 | Notification service: clinic-day / Monday list per investigator (ICD-13), CRC digest, real-time classes, S19 settings (quiet hours, snooze), one-item-once rule, budget counter FR-NOTIF-08 | 45 | 0 (the built weekly list page and the existing pseudonym list mail are used from go-live until the release before pilot week 7) | M1 Feb–Mar line, **before Phase 2 (pilot week 7)** | WP-17 |
| WP-19 | Study set-up and screening log: S21 and the study settings store (TB-DS-07), ethics approval record with approved explainer file and sponsor field (BD-15), flow-B ethics gate FR-STUDY-06, TrialBox-issued `screening_no` (FR-STUDY-08, BD-18) and outcome→status mapping, contact outcome in 2 taps (FR-SCR-10c), per-study reason lists (FR-STUDY-09), `office` scope (FR-STUDY-10), REDCap project link and field map with `tb_screening_no` (FR-RC-16, ICD-04 §4.1a), FR-RC-15 keyed on screening number, FR-CON-09/10, FR-REP-09 annual export, weekly Phase-1 log import (ICD-14), **site monitoring view with funnel and forecast (FR-REP-06, +10 h)** | 60 | 35 (S21 core, approval record, FR-STUDY-06 for every identity-resolving study (BD-20), introduce rule (BD-19), screening number and mapping, field map, Phase-1 log import) | Go-live + M1 Feb–Mar line (remaining 25 h before pilot week 7) | WP-02 |
| WP-20 | Protocol → ruleset quote links and the review workbook (FR-FEAS-11) | 25 | 25 | Go-live (the PI approves the first rulesets from it) | Built doc-parser and criteria-compiler |
| WP-19b | Registry / observational support: nightly cohort by cohort kind (FR-STUDY-02), registry–EMR reconciliation (FR-STUDY-03), personal-database import with consent metadata (FR-ING-19/21, ICD-14) | 35 | 0 | M2 (April 2027; TB-DS-00 §2). FR-STUDY-02 cohort kinds are in WP-19 at go-live; the CCB may pull reconciliation into the M1 line only if a pilot study is a registry with REDCap reconciliation in scope | WP-19 |
| | **Clinical layer M1 total** | **≈ 229** (incl. WP-00 8 h and WP-00b 16 h; WP-19b 35 h is M2 and not in this total) | **≈ 113** (incl. WP-00 and WP-00b round 1) | | |

**Capacity check (restated).** The full M1 content is now ≈ 657 + 229 = **≈ 886 engineer hours**, about **2.7 × the 330 hours** to 22 January and **2.2 × the 400 hours** to 5 February. The core pilot cannot be completed by one engineer by either date as written. §5 shows the options with the clinical layer included.

### 3.2 Full system additions (M2)

| WP | Work package | Engineer h | Dep. |
| --- | --- | --- | --- |
| WP-21 | EDC pre-fill engine with cards; pre-fill gate set | 120 | WP-02 |
| WP-22 | REDCap External Module (panels, Data Entry Trigger, writes under user session) | 100 | Hospital REDCap development server |
| WP-23 | Trial-conduct suggestions (visit windows, visit pre-fill, AE and con-med tasks for the investigator) | 100 | WP-21 |
| WP-24 | Consortium hub per country and cross-site GUID | 90 | Steering committee, consortium secret |
| WP-25 | EDC-lite on FHIR Questionnaire/SDC (ADR-04). **Re-tagged C (later)** (TB-REV-006c C-27): both pilot sites have REDCap; built only if a named study without REDCap appears. Not counted in the M2 total. | (160) | ADR-14 M2 spike outcome (HAPI by default; Medplum only if the spike passes) |
| WP-26 | Medplum spike and, if it passes, migration of FHIR store and accounts | 80 | — |
| WP-27 | Validation of M2 (tests, gates, SAT delta at both sites, documentation) | 60 | WP-21..26 |
| | **Total M2 (without WP-25)** | **≈ 550** | |

OMOP export, LINE/Teams notices and sponsor EDC connectors are not planned (TB-DS-00 §2, "Could").

## 4. Critical path

```
Ethics pack (WP-01) ──► submit ──► committee meeting ──► (possible 2nd round) ──► approval ──► pilot PQ / chart review
Export spec ──► source reader + mapping (WP-03/04) ──► dry run (WP-10) ──► SAT OQ (WP-13/14)
GPU box order ──► delivery ──► real-card gates (WP-10) ──► release candidate ──► pentest pass 2 (WP-12) ──► SAT
```

The longest chain is **ethics approval**: submission is needed in November 2026 for a January decision, and a second round would push approval into February. Without approval, installation and the technical parts of site acceptance (IQ, OQ) can still run, but the performance qualification with real studies, pilot Phase 1 and the chart review cannot start.

## 5. Two scope variants

### Variant 1 — Core pilot in January, full system in Q2 2027 (recommended)

To fit the capacity, the January go-live is narrowed further than TB-DS-00 M1, and the Japan site goes first:

| Item | Japan go-live (about 2027-02-08) | February–March | Q2 2027 |
| --- | --- | --- | --- |
| Built core: FEAS, SCREEN cascade, CASE, registry, consent explainer, mail, roles | ✓ | ✓ | ✓ |
| 2FA, hardening, health page, signed updates, rollback | ✓ | ✓ | ✓ |
| Feasibility input page with tiles (reduced WP-07) | ✓ | ✓ | ✓ |
| Chat box | tiles + mail commands only | chat box added | ✓ |
| PHI pass | rules + NER; LLM tagger only if no scrubbed note leaves the identified zone (TB-DS-04 §12.5) | LLM tagger added | ✓ |
| REDCap | read + simulator | ✓ | writes via module (M2) |
| CGMH | mapping | install 2027-02-15..19, go-live about 2027-02-22 (after Lunar New Year) | ✓ |
| EDC pre-fill, module, trial conduct, hub, Medplum (EDC-lite is C) | — | — | M2 releases April–June 2027 |

Engineer hours to go-live under this variant: WP-01 40, WP-02 50, WP-03 60, WP-05 24, WP-06 (rules + NER) ≈ 40, WP-08 50, WP-09 50, WP-10 50, WP-11 (EN + JA) 30, WP-12 40, WP-13 40, WP-16 33 = **507 h**, plus a reduced WP-07 (feasibility input page and tiles only, no chat box) ≈ 10 h = **≈ 517 h** (v0.2 figure), **plus the go-live part of the clinical layer ≈ 113 h (§3.1a, incl. formative round 1) = ≈ 630 h**. Against ≈ 400 h to 2027-02-05 that is **about 1.6 × capacity** (v0.2 compared 517 h with the 330 h to 22 January and said 1.6 ×; measured to the recommended date, v0.2's own figure was 1.3 ×, so v0.2 was optimistic about the February date). The full WP-07 (40 h, with the chat box) would add 30 h; the chat box therefore moves to February–March.

The remaining clinical-layer work (WP-17 homes 40 h, WP-18 45 h, WP-19 25 h, WP-00b round 2 6 h ≈ **116 h**) must land on the M1 February–March line **before pilot week 7**, because Phase 2 (TrialBox-first, TB-DS-04 §8.2) is where N-17 and NFR-USAB-06 are measured and the load reduction depends on these screens. February–March capacity: 8 weeks × 35 h = 280 h, less WP-15 64 h, WP-14 40 h and the chat box and LLM PHI tagger ≈ 60 h, leaves ≈ 116 h, so it fits with **no slack**; any overrun moves Phase 2 by the same amount (SR-12). WP-19b goes to M2 (April) unless CGMH puts a registry study in the pilot.

With the clinical layer the go-live date holds only if **one of** these is true:

- the Japan maintenance team gives about 15 h/week of engineering help from late November (test running, documentation, string review, site liaison; ≈ 150 h by 02-05) **and** about 70 h of WP-11/WP-01 drafting moves to the Japan team, on top of the ≈ 38 h already assigned (≈ 260 h, §1), which brings ≈ 630 h within reach for **2027-02-08**; **or**
- one engineer works alone and the Japan go-live moves to about **2027-03-15** (≈ 630 h ÷ 35 h/week ≈ 17.7 weeks plus 1.5 weeks of holidays from 2026-11-09); CGMH would then follow at about 2027-03-29; **or**
- a second engineer joins for December and January (go-live 2027-02-08 with margin).

**Recommendation (restated in v0.3, proposed, pending owner approval):** Variant 1 with the Japan go-live at about **2027-02-08** **with the Japan team's 15 h/week of engineering help** (v0.2 said no extra staff were needed; with the clinical layer that is no longer true). CGMH goes live after Lunar New Year (6 February 2027; holidays assumed 2027-02-05 to 02-14, to be confirmed by CGMH) at about **2027-02-22**. If the Japan team cannot help, the honest one-engineer date is about **2027-03-15** (Japan) and **2027-03-29** (CGMH). The owner is choosing on a decision card in the project thread (OI-14); TB-DS-00 §2 "Pilot dates" is the place where the chosen dates are recorded.

Full system complete: about **July 2027** with one engineer (M2 ≈ 550 h without WP-25, now tagged C (TB-REV-006c C-27), + WP-19b 35 h ≈ 585 h ≈ 17 weeks from mid-March).

### Variant 2 — Full system first, pilot later

All of §3.1, §3.1a and §3.2 are built and validated before any site goes live. Total ≈ 657 + 229 + 585 (M2 incl. WP-19b, without EDC-lite) = **≈ 1,471 engineer hours ≈ 42 weeks** for one engineer. Pilot go-live about **August 2027** with one engineer, or about **May 2027** with two. Ethics approval can be obtained in the meantime, so it no longer sits on the critical path. The drawback is no real-site feedback for nine months, which raises the risk that the full system is built on wrong assumptions about the sites' data and workflows.

### Variant 3 — Full system in January with more people

Requires about 2–3 additional engineers from early December, a pentest firm able to test twice in two weeks, and both ethics approvals in the first round. Judged unrealistic: new people need onboarding time that the schedule does not have, and validation (gates, SAT, pentest) cannot be compressed safely.

## 6. Milestones (Variant 1)

| ID | Milestone | Target date | Owner | Exit criterion |
| --- | --- | --- | --- | --- |
| MS-01 | Scope decision | 2026-11-10 | Product owner | Variant chosen |
| MS-01a | **Japan team hours confirmed** (owner decision, TB-REV-006d D-05) | 2026-11-20 | Product owner + Japan team lead | ≈ 15 h/week engineering from 11-23 and ≈ 70 h drafting confirmed in writing; otherwise MS-12 and MS-14 take the one-engineer dates |
| MS-02 | GPU test box ordered | 2026-11-13 | Product owner | Order confirmed with delivery date |
| MS-03 | Pentest firm booked | 2026-11-20 | Engineer | Contract with two test windows |
| MS-04 | Ethics submissions sent (both sites) | 2026-11-20 | Site PIs with WP-01 | Receipt from each committee |
| MS-05 | Source export specifications received; site survey including the **PI device path** (personal phone on Wi-Fi/VPN, hospital phone, or clinic PC only; TOTP app allowed) and the appointment source | 2026-11-20 (survey answers by 2026-12-04) | Site IT | Specifications in hand; TB-DS-15 PR-07 answered in writing by the IT lead |
| MS-05a | Site interviews (R-02) and research-office process (R-08): 2 CRCs, 1 PI, 1 research-office member, 1 REDCap admin, 1 IT security contact per site (TB-TMPL-07 §5); REDCap project inspection (R-05) | 2026-12-11 (before feature freeze MS-08) | Product owner + engineer | Notes filed; TB-DS-17 §1 and §4 updated |
| MS-05c | Formative usability round 1 complete (WP-00b: S20, S21, list mail) | 2026-12-18 | Product owner + moderators | Findings filed in TB-DS-09 §11 before MS-08 |
| MS-05d | Formative usability round 2 complete (WP-00b: S16, S8, S18, S19) | before pilot week 7 (with MS-15) | Product owner + moderators | Findings fixed or accepted before the Phase-2 release |
| MS-05b | **Workload baseline complete** (WP-00): two normal working weeks, **2027-01-11 to 01-22 at both sites** (after the 年末年始 recovery week; before Lunar New Year at CGMH) | 2027-01-22, at least two weeks before each PQ | Site PI (owner); research office administers | Self-logs and NASA-TLX forms for 2 CRCs + 2 PIs per site, one observed clinic half-day; summary in TB-DS-04 E6 format. If the go-live moves to March, the window moves to the two normal weeks before go-live and is still outside both holidays |
| MS-06 | GPU box running; first real-card gate | 2026-12-11 | Engineer | G1–G3 measured on a real 5090 |
| MS-07 | Pentest pass 1 (infrastructure) | 2026-12-14 to 12-18 | Pentest firm | Report |
| MS-08 | Feature freeze, release candidate RC1 | 2026-12-23 | Engineer | All M1-Jan tests pass |
| MS-09 | Pentest pass 2 (application on RC1) | 2027-01-05 to 01-08 | Pentest firm | Report; no open critical/high |
| MS-10 | Install and IQ/OQ at the Japan head hospital | 2027-01-12 to 01-15 | Engineer + site IT | TB-DS-15 IQ, OQ signed |
| MS-11 | Ethics approval received (Japan) | by 2027-01-15 | Site PI | Approval letter |
| MS-12 | PQ and go-live, pilot Phase 1 (Japan) | about 2027-02-08 with Japan team help; about 2027-03-15 with one engineer alone (§5) | Site PI | TB-DS-15 PQ signed |
| MS-13 | CGMH install and IQ/OQ | 2027-02-15 to 02-19 | Engineer + CGMH IT | IQ, OQ signed |
| MS-14 | CGMH PQ and go-live, pilot Phase 1 | about 2027-02-22 (or 2027-03-29 with one engineer alone) | CGMH PI | PQ signed; ethics approval in hand |
| MS-15 | Chart-review checkpoint 1 and **Phase-2 decision** | pilot week 6 | Site PIs | Interim recall ≥ conditional pass (TB-DS-04 §8.6); ethics approval of Phase 2 in hand; WP-17 homes and WP-18 notifications released. Otherwise the site stays in Phase 1 |
| MS-15a | Phase-2 measurement complete | pilot week 12 | Site PIs + pilot team | E6, E9, E11 collected (TB-DS-04 §8.3) |
| MS-16 | Pilot report | end of April 2027 (Japan), May 2027 (CGMH) | Product owner + PIs | TB-DS-04 §8.7 report signed |
| MS-17 | M2 releases | April–June 2027 | Engineer | Each with release record |

The 500,000-patient dry run happens on the GPU test box with synthetic data (MS-06) and again on each site box during OQ.

## 7. Schedule risks

| ID | Risk | Likelihood | Effect | Response |
| --- | --- | --- | --- | --- |
| SR-01 | Ethics approval needs a second round | Medium | Go-live slips one month | Submit early (MS-04); run IQ/OQ meanwhile; prepare answers to likely questions (PHI, opt-out, chart review) in WP-01 |
| SR-02 | RTX 5090 supply or price (street prices rose sharply in 2026) | Medium | Real-card gates late; hardware choice unproven | Order immediately; fallback test on a rented 5090 or a capped RTX PRO 6000 as in PR #21 |
| SR-03 | Site export specification late or incomplete | High | Mapping slips week for week | Start with the vendor's standard SS-MIX2 layout; ask for a 100-patient sample extract |
| SR-04 | One engineer unavailable (illness, other work) | Medium | Everything slips | Japan team covers testing and documentation; keep the plan in this document so another engineer can pick it up |
| SR-05 | Pentest finds critical issues late | Low–Medium | Go-live slips | Two-pass pentest; fix window before MS-10 |
| SR-06 | Hospital REDCap development server not available | Medium | Connector accepted only against the simulator | Allowed for M1 (read only); needed before M2 module work |
| SR-07 | Japanese recall below target in real notes | Medium | Pilot recall endpoint at risk | Phase 1 is additive (staff screen as usual) and Phase 2 needs the week-6 recall checkpoint, so patients are protected; prompt and note-search fixes in February releases |
| SR-08 | Chart-review reviewer time not funded or not available | Medium | Recall endpoint delayed | Fund ≈ 78 h per study as a pilot-only line (§1a), decided before MS-04; single reviewer for stratum C |
| SR-09 | Baseline not collected in a normal period (holidays, staff absence, department head declines) | Medium | N-17 and NFR-USAB-06 cannot be judged | Fixed window 2027-01-11..22 outside 年末年始 and Lunar New Year; agreement at MS-05a; report the seasonal caveat if the window must move |
| SR-10 | Ethics committee does not approve Phase 2 (TrialBox-first) | Medium | Pilot stays in Phase 1; no workload result | Ask for Phase 2 in the original submission (TB-TMPL-01 §5); week-6 data supports an amendment |
| SR-11 | PI device path not available (no phone access to the on-prem web) | Medium–High in Japan | PI phone flow fails; only the clinic PC and the pseudonym mail remain | Ask at MS-05 (TB-DS-15 PR-07); clinic-PC layout in WP-17 |
| SR-12 | Clinical-layer packages (WP-17/18) late for pilot week 7 | Medium | Phase 2 measures the old screens; savings understated | Keep §3.1a split; WP-18 first in the February line; move WP-19b to M2 |

## 8. Communication

Weekly: one-page status (done, next, risks, decisions needed) to the product owner. At each milestone: the milestone record. CCB meets weekly during December–January, then fortnightly.

## Change history

| Version | Date | Author | Change |
| --- | --- | --- | --- |
| 0.1 | 2026-11-07 | Claude for Aimedics | First draft, from TB-REV-006 findings F-07, F-31, M-12. |
| 0.2 | 2026-11-07 | Claude for Aimedics | TB-REV-006b R2-01, R2-10: Variant 1 arithmetic corrected (507 h + reduced WP-07 10 h = 517 h, 1.6 × capacity); recommendation stated (Japan ≈ 2027-02-08, CGMH ≈ 2027-02-22); MS-12..14 dates aligned; WP-25 dependency is the ADR-14 M2 spike outcome, HAPI by default (R2-06); pending owner decision OI-14. |
| 0.3 | 2026-11-07 | Claude for Aimedics | TB-REV-006c: WP-00 workload baseline and MS-05b (window 2027-01-11..22, outside 年末年始 and Lunar New Year) (C-03); §3.1a clinical-layer packages WP-17..WP-20 and WP-19b with go-live split (C-02); capacity restated (≈ 895 h full M1; Variant 1 go-live ≈ 620 h vs ≈ 400 h to 02-05); recommendation restated: 02-08 needs the Japan team’s 15 h/week, otherwise ≈ 2027-03-15; §1a pilot-only costs (chart review ≈ 78 h per study, funded, single reviewer for stratum C) (C-04); shadow-log import by the pilot team (C-21); MS-05 device-path survey (C-16), MS-05a interviews and REDCap inspection, MS-15 Phase-2 decision, MS-15a (C-01); SR-09..SR-12; WP-25 EDC-lite re-tagged C (C-27). |
| 0.4 | 2026-11-07 | Claude for Aimedics | TB-REV-006d: follows the TB-DS-00 §2 "M1 content by date" table; WP-18 wording "until the release before pilot week 7"; FR-REP-06 named in WP-19 (+10 h); WP-19b M2 (D-02); resource row and hours by source, MS-01a Japan-team hours (D-05); WP-00b formative test with moderators, MS-05c 12-18 and MS-05d (D-06); totals ≈ 921 h full M1, ≈ 630 h to go-live, ≈ 116 h before week 7 with no slack; WP-15 outside go-live totals; "shadow mode" removed from §1, §4, SR-07 (D-01). |
| 0.5 | 2026-11-07 | Claude for Aimedics | TB-REV-006e: capacity in engineer hours only (≈ 620 h vs ≈ 630 h, ≈ 10 h short; 38 h translation not counted) (E-02); WP-19b out of the M1 total: clinical layer M1 ≈ 229 h, full M1 ≈ 886 h (2.7 × / 2.2 ×), M2 ≈ 585 h (E-03). |
| 0.6 | 2026-11-07 | Claude for Aimedics | Owner direction 2026-11-07 and TB-REV-006f: superseded for the build stage by SIMPLE-PLAN.md and 20-build-map.md; kept as hospital-stage reference. |
| 0.7 | 2026-11-07 | Claude for Aimedics | TB-REV-006g §F F-10 (optional): WP-17 approval wording follows BD-13 one Approve; §2.H cites. |
