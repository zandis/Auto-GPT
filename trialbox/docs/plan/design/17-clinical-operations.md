# TB-DS-17 Clinical operations and workload design

| Field | Value |
| --- | --- |
| Document | TB-DS-17 Clinical operations and workload design |
| Version | 0.9 |
| Date | 2026-11-07 |
| Owner | Product owner (Changfu Kuo); author Claude for Aimedics |
| Status | Reference. What is built in each step is in `20-build-map.md`; TOTP, the two-phase pilot and the measurement in §9 are hospital stage (H), and the ruleset approval is one page with one Approve (BD-13 as simplified). Workload figures marked **(E)** are estimates to be replaced by the pilot baseline (§9). |
| Approvals | Product owner; site PIs (Japan head hospital, CGMH); one CRC per site; Japan maintenance lead |
| Depends on | TB-DS-00 current version (wins on any conflict), TB-DS-20 build map, TB-DS-01, TB-DS-09 and TB-DS-07 (versions per TB-DS-00R), TB-TMPL-07 (baseline and test instruments) |

## 0. Purpose and the one rule

This document designs TrialBox around the people who will use it in clinic: principal investigators (PIs), clinical research coordinators (CRCs) and study nurses, research assistants and data managers, SMO staff, the research office, site IT, the ethics office and monitors. It also covers the whole study cycle for trials, registries and observational studies, the alerts and lists people receive, the data sources, the Medplum question, monitoring, and how the pilot measures whether the load went down.

**The one rule: TrialBox may not add net work to any clinical role in steady use.** Each new interaction must remove a larger one (§2). If a feature cannot show this on the workload budget, it is not built, or it is moved to a role whose load it does reduce. **The pilot is the one stated exception:** in pilot Phase 1 staff keep their usual screening, so TrialBox adds a small, agreed amount of time; savings are claimed and measured only in Phase 2 (BD-16, §2.2 "Phase 1" rows).

Role names follow BD-03 (TB-DS-00 §3). PI = `investigator`; CRC / study nurse = `coordinator`; SMO CRC = `coordinator` with study scope and expiry; CRA / monitor and sponsor staff = `cro` (aggregates only); ethics office and inspectors = `auditor`; research office = `coordinator` with the `office` flag (FR-STUDY-10); site IT = `admin`. "RA" (research assistant / data manager) is not a role: an RA gets `coordinator` with study scope, or `viewer` for aggregate-only work.

Release tags follow the one legend in TB-DS-00 §2 and TB-DS-20 §1: **S0** built; **S1–S5** the build step; **H** hospital stage (real data); **L** later. Older M1 / M2 / C values survive only as "(was …)" notes. Workload figures describe steady use at a hospital (H); during the build nothing here runs on real patients.

### 0.1 Sources

| Ref | Source | What it supports |
| --- | --- | --- |
| [C1] | Penberthy LT et al., "Screening intervention to identify eligible patients and improve accrual to phase II–IV oncology clinical trials", *J Oncol Pract* 2013;9(4):e174–e181 (PMC3710186). | In that oncology programme, about 80 % of coordinator time went to screening patients. One setting; not a general rate. |
| [C2] | Applied Clinical Trials, "Streamlining clinical trials with eSource: insights from MSK" (Memorial Sloan Kettering). | More than half of trial data is entered twice (EMR, then EDC); about 20 % of study cost goes to duplication and verification; ≥ 3 min per transcribed data point (cited AstraZeneca/Sanofi analysis); query resolution takes about 50 % of coordinator time; eSource projected to save > 50 % (projections, not measurements). |
| [C3] | 広島大学病院 CRC業務手順書 第6版. | Japanese CRC duties: screening support, IC explanation assistance, source documents and CRF support, AE response support, monitoring and audit support. |
| [C4] | Clinical decision-support alert-fatigue literature (general; no figure is taken from it). | Override rates for interruptive alerts are high; batching, de-duplication and relevance filtering are the accepted mitigations. |
| [TB] | TB-DS-00, TB-DS-01, TB-DS-09, answers A1–A44 and the 2026-11-07 messages. | Scope, roles, numbers. |

No workload figure in this document is a measurement at our sites. All per-week minutes are **(E)** until §9's baseline replaces them.

**Context, not basis.** [C1] (one oncology programme) and [C2] (eSource projections at one US centre) show why screening and transcription are worth attacking; they are **not** used as figures for AD or RA work at our sites. §1–§2 use only (E) figures.

## 1. Personas with real behaviour

Each persona lists: how they work today; weekly time on the tasks TrialBox touches (E); pain points; what TrialBox removes; target time; and every input they must still give, with the reason for each field.

### 1.1 PI — clinic-bound investigator

**Today.** Runs outpatient clinics most days, between 30 and 60 patients a session. Has 3–5 minutes between patients and uses a phone in the corridor or a clinic PC that is logged into the EMR. Sees study candidates only when a CRC flags them, or when they happen to remember a protocol during a visit. Signs off eligibility, consent, AEs and CRFs in batches at the end of the day or week.

| Task touched by TrialBox | Today (E, min/week, 2 active studies) | Pain |
| --- | --- | --- |
| Thinking of candidates during clinic, asking CRC to check | 30–60 | Misses candidates; recall depends on memory |
| Reviewing CRC-prepared eligibility notes | 30–60 | Paper or e-mail with chart numbers; no evidence trail |
| Feasibility answers for sponsors / own grant | 60–120 per request | Guesses counts or asks IT for a query that takes weeks |
| AE review and sign-off | 30–60 | Finds out late; reviews from scratch |
| Ethics paperwork for TrialBox use | one-off | Another system to explain to the committee |

**TrialBox removes:** drafting the eligibility rules (the LLM reads the protocol and drafts them, BD-13; the PI sees one page of criteria with source quotes); remembering candidates (the PI list before each clinic day, §5.1, with Monday as the fallback when clinic days are unknown, puts the clinic's candidates in front of them); hunting for evidence (each criterion card carries a quote and date, TB-DS-09 §4); waiting for IT feasibility queries (flow A, minutes instead of weeks); writing the ethics description from scratch (TB-TMPL-01).

**Target:** ≤ 20 min/week for the list and marks, ≤ 10 min per feasibility approval (E). Net change must be ≤ 0 against the baseline in pilot Phase 2 and after.

**Device path (to confirm per site, TB-DS-15 PR-07).** Many hospitals do not let personal phones reach the clinical LAN. The PI flow therefore works three ways: (a) personal phone on hospital Wi-Fi or VPN, (b) hospital-issued phone, (c) **clinic PC only**, in a narrow window beside the EMR (FR-UI-19). Where no link works from the phone, the PI list mail still shows pseudonyms, visit times and counts, so the PI can act on the clinic PC.

**Who introduces a study (主治医の了承).** Many candidates in an AD memory clinic or a rheumatology department are followed by doctors who are not study investigators. Japanese practice expects the treating doctor's agreement before a study is introduced; CGMH likewise expects the attending's agreement. The PI's list therefore shows **Your clinic** first, **Other study doctors** folded, and **Other doctors** with **Ask treating doctor**, which gives the CRC an item to approach that doctor (FR-SCR-07b). Who may introduce the study is one rule (BD-19): the treating physician, or a study investigator after the treating physician has agreed, as the approved protocol states; S21 records which, and the ethics pack says the same (TB-TMPL-01 §2, §7).

**Inputs the PI must still give** (all others are defaulted or taken from the record):

| Input | Where | Taps | Why it cannot be removed |
| --- | --- | --- | --- |
| Mark per candidate: Approach / Need info / Not suitable (+ reason from the study's list) / Not now, re-check on <date>; Ask treating doctor for others' patients | PI list on phone or clinic PC (S16, S18) | 1 (2 with reason) | The PI decides; a model never excludes (TB-DS-09 P1, FR-SCR-07) |
| Approve the ruleset (BD-13 as simplified) | S20, one page: each criterion in plain words with its protocol quote, threshold, time window and missing-data rule; amber rows opened once; code rows folded (the CRC may pre-tick them); **Approve all**, or edit one line | 1 + one tap per amber row (TOTP only in a hospital install, H) | Investigator responsibility for what the study definition means clinically. The LLM drafts the ruleset (BD-13); the PI reviews meaning, not codes |
| Confirm the study team (S21); the ethics record only when the site's `ethics_gate` setting is on (H) | S21 | 1 | The investigator vouches for the team; with the gate on, also for the approval, which then gates identified lists (FR-STUDY-06, BD-20) |
| Approve a feasibility report leaving the site (FR-FEAS-08, FR-REP-03) | Approval card | 1 | Site approves sponsor reports (answer, 2026-11-07 01:16) |
| Confirm or dismiss an AE suggestion with reason (BD-08, L) | AE card | 1–2 | Only the investigator may dismiss (BD-08) |
| Approve cross-site query (L) | Approval card | 1 | PI approves cross-site queries (answer 01:16) |

The PI never types criteria, chart numbers, dates or form values in TrialBox. Data entry is desktop only (FR-UI-09).

### 1.2 CRC / study nurse — desktop, many studies

**Today.** Desktop worker with EMR, REDCap (or the sponsor EDC), Excel and phone open at once. Supports 3–8 studies. Screens charts by hand against paper or Excel criteria, keeps a paper or Excel screening log, phones patients to arrange visits, transcribes EMR values into the EDC, answers monitor queries, prepares for monitoring visits [C3].

| Task touched by TrialBox | Today (E, h/week, 5 studies) | Pain | Evidence |
| --- | --- | --- | --- |
| Pre-screening charts | 6–10 | Repetitive reading; misses in free text | [C1]: up to ~80 % of coordinator time in one oncology programme |
| Screening log upkeep (paper / Excel) | 1–2 | Duplicate of what was already decided | (E) |
| Visit planning and phone calls | 2–4 | Appointment lists printed per clinic | (E) |
| EMR → EDC transcription | 4–8 | Double entry, ≥ 3 min per data point | [C2] |
| Query resolution | 2–5 | Up to ~50 % of time in [C2]'s setting | [C2] |
| Monitoring visit preparation | 1–2 per visit | Reprinting logs, finding source | [C3] |

**TrialBox removes:** first-pass chart reading (cascade + cards, N-17 target ≥ 50 % less pre-screen time, TB-DS-00 §4, from pilot Phase 2); the screening log (kept automatically from PI marks, contact outcomes and REDCap reads, with a TrialBox-issued screening number, FR-SCR-10a, BD-18, exported in REDCap import format, S2–S3); the printed visit list (§5.2 digest); later (L), most structured EMR → EDC transcription (pre-fill cards, N-09) and query look-up (data-quality view, §8).

**Target:** pre-screen time −50 % (N-17); screening log 0 h; transcription −50 % for structured fields later (L) (E, to be measured against N-09 acceptance).

**Inputs the CRC must still give:**

| Input | Where | Taps / typing | Why |
| --- | --- | --- | --- |
| Upload the protocol (or paste criteria for a pre-approval feasibility) once per study | S2 feasibility input | upload + 1 | The LLM drafts the ruleset from it automatically (BD-13) |
| Pre-tick the code rows of the drafted ruleset and send it to the PI (BD-13 as simplified) | S20 on desktop, pre-filled, with the lab-lead review reference | 1 to confirm; edit only flagged codes | The CRC or data manager knows the local codes; the PI approves the clinical meaning |
| Contact outcome per approached patient: Reached – visit booked · Reached – declined · Not reached (retry date) · Not approached (physician decision) · Lost contact | S8 CRC home, one pick-list | 1 | Contact happens outside TrialBox (doctor contacts patients, answer 01:16); the log needs the outcome. Each maps to a registry status and reason category (TB-DS-07 §4.1) |
| Write TrialBox's screening number into the REDCap field `tb_screening_no` when creating the REDCap record | REDCap, as today | typing one short number the CRC would otherwise write in their own log | Lets TrialBox read consent, enrolment and screen-fail from REDCap with no other entry (BD-18). It replaces the log entry, so it is not a new task |
| Consent date and enrolment | **Read from REDCap** where the study is in REDCap (read connector, S3); one tap "Consented" otherwise | 0–1 | Zero duplicate entry: if REDCap holds it, TrialBox reads it |
| Set up the study once (S21): type, team, REDCap link, screening-number format, reasons list; ethics approval record with the **committee-approved explainer file** uploaded; sponsor approval for sponsored trials | S21, one page, mostly pre-filled from documents already uploaded | one form per study, ≈ 20–30 min (E); upload once per approval | Today this information is spread over the CRC's binder, the research office's list and REDCap; it decides what runs against patients and who sees what (FR-STUDY-07). The explainer then goes live automatically (BD-15); the investigator confirms the record |
| Accept / edit each pre-fill value (L) | S10 panel inside REDCap | 1 per field, "Accept all rule-filled" for structured | Human confirms each value (answer 00:04) |

### 1.3 Research assistant / data manager — registries and Excel

**Today.** Keeps disease registries and observational cohorts (at CGMH: RA-BIO, RA-COH, GOUT-COH) in REDCap or Excel. Pulls lab values from the EMR or DWH by hand or by monthly IT extract, copies them into the registry, chases missing visits, cleans data before analysis, exports to SPSS/R/Stata.

| Task | Today (E, h/week) | Pain |
| --- | --- | --- |
| Finding new cohort members | 1–3 | Depends on clinicians remembering to refer |
| Copying EMR values into the registry | 4–10 | Double entry; transcription errors |
| Checking registry against EMR | 1–3 | Done rarely, so errors last |
| Export and recoding for analysis | 1–2 per export | Each export re-done by hand |

**TrialBox removes:** cohort finding (the same ruleset engine, with no contact step where the study runs under an opt-out or waiver, §4.2); value reconciliation (registry vs EMR, §6.4, read-only; L); later (L), proposed values for new visits (pre-fill into REDCap) and a repeatable export.

**Target:** reconciliation from hours to a weekly 15-minute review of mismatches (E); copying −50 % once pre-fill is built (L) (E).

**Inputs:** cohort definition (once, same as criteria); accept or reject each reconciliation mismatch (1 tap: "EMR right" / "registry right" / "leave"); the column mapping when importing a personal database (§6.2, once per file layout).

### 1.4 SMO CRC — multi-site, works under an affiliation

**Today.** Employed by an SMO and placed at several hospitals; each hospital has its own login, network and rules. Carries a laptop, works from a desk the hospital provides. Often covers one or two studies per site.

**Pain:** a different login per hospital; access that lingers after the contract ends; no single view across sites.

**What TrialBox does:** one `coordinator` account per site box with study scope and an expiry date (BD-03, S12); the account stops working on the expiry date without anyone remembering to remove it; the CRC home is the same layout at every site, so there is nothing new to learn at the next hospital.

**What TrialBox does not do:** merge sites into one view. Each box is on-prem and only counts cross sites (BD-06), so the SMO CRC has one home per hospital. This is deliberate. Inputs are the same as §1.2.

### 1.5 Site admin / IT

**Today.** Runs the EMR interfaces, the DWH and the hospital network; looks after REDCap where the hospital hosts it. Has no time for a new system that needs daily care.

**TrialBox gives:** install from one signed bundle (FR-OPS-01); one health page (S13); e-mail only when something is wrong (FR-OPS-08), de-duplicated (§5.4); user creation with expiry (S12). No remote access by default (FR-OPS-09).

**Target:** ≤ 30 min/week after the first month (E). **Inputs:** create users and scopes; keep the nightly export running; act on red health items.

### 1.6 Ethics office

**Today.** Receives protocols, consent forms and amendments on paper or a submission system; does not want a new login.

**TrialBox gives:** the submission pack (TB-TMPL-01) as files for their existing process; the consent explainer draft, generated from the ICF and submitted **together with the ICF** in the same submission (BD-15); if the committee asks for wording changes, the edited approved version is what goes live (no ICF amendment needed); an ICF amendment carries a new draft with it; the pre-approval feasibility description (counts only, k = 10 outside the site, N-01). The ethics office needs **no TrialBox account**. If the committee wants to inspect use, it gets an `auditor` account (read-only, S15).

**Inputs:** none in TrialBox and no extra review step: the explainer is reviewed with the ICF it belongs to. After approval the CRC uploads the approved file to the study record and the PI confirms; it then goes live automatically. The fingerprint check (FR-CON-06) is an automatic safeguard, not a person's task. The committee also approves pilot Phase 2 explicitly at week 6 (BD-16) and each study's identified pre-screening (FR-STUDY-06).

### 1.7 Monitor / CRA

**Today.** Visits the site or monitors remotely; checks the screening log, informed consent, eligibility source and CRF against source (SDV); raises queries in the EDC.

**What TrialBox gives the CRA (role `cro`, aggregates only, BD-03):** a study view with counts: screened, approached, consented, enrolled, screen failures by reason (suppressed under k = 10, N-01), enrolment against the feasibility forecast, and the number of unverified or queried fields per form (L, §8).

**What it does not give:** patient-level rows. Sponsors never get patient-level data (answer 01:16). Patient-level SDV stays where it is today: on site, in the EMR and REDCap, under the hospital's own monitoring arrangement. TrialBox helps the **CRC** prepare for that visit (screening log export, list of unverified fields), which is where the time is saved.

### 1.8 Research office — 治験事務局 / 臨床研究支援センター; CGMH 臨床試驗中心

**Today.** Onboards every study (contracts, IRB submissions, the list of active studies and investigators), requests accounts, manages SMO contracts and monitoring-visit logistics, and each year compiles the progress report to the committee (実施状況報告 / IRB 期中報告: numbers screened, consented, enrolled, withdrawn, SAEs) by e-mailing each CRC for counts. Decides, with IT, whether a new system gets installed.

| Task touched by TrialBox | Today (E) | Pain |
| --- | --- | --- |
| Annual progress-report numbers per study | 30–60 min per study per year, plus the CRC's time to count | Counts gathered by e-mail from each CRC; inconsistent definitions |
| Study onboarding records | 1–2 h per study | Same data in several places (binder, list, REDCap) |
| Account requests and expiry for SMO staff | 10 min per person | Access left open after contracts end |

**TrialBox gives:** S21 study set-up, shared with the study team, so the onboarding record is entered once (FR-STUDY-07); the **annual progress-report export** per study, counts per status and year from the screening log and REDCap reads (FR-REP-09); the study list (S4) with PIs and status; account expiry on SMO accounts (S12).

**Role:** `coordinator` with the `office` flag (FR-STUDY-10): all studies' set-up records and pseudonymised logs; no chart-number reveal unless also a study team member.

**Inputs:** S21 sections with the study team (once per study); account requests to `admin` (as today). **Saving (E):** the CRC's annual counting disappears; the office's report time drops to minutes per study.

The research office is included in the site interviews and the formative usability test (TB-TMPL-07).

## 2. Workload budget

### 2.1 Rules

1. **No new task without removing a larger one.** Every row in §2.2 shows the task it replaces. A row whose net is positive for a clinical role is a design defect.
2. **Zero duplicate entry.** A value already in the EMR, the DWH, REDCap or an earlier TrialBox screen is never typed again. TrialBox reads it, or carries it forward. Enforced as NFR-USAB-07 (TB-DS-01).
3. **Defaults so most screens need one click.** Every action screen opens with the most likely answer pre-selected (study from context, this week, the user's own patients, the next step in the six-step bar). Target: median one primary action per screen, ≤ 3 for any task (NFR-USAB-01, NFR-USAB-08).
4. **Pilot work is pilot-team work, and the pilot's added time is stated.** The pilot has two phases (BD-16). In **Phase 1 (weeks 1–6)** staff screen as usual, so TrialBox's savings are not yet realised; the PI mark and contact outcome add a little time on top, which the sites agree in advance (§2.2 Phase-1 rows). In **Phase 2 (weeks 7–12)** staff pre-screen from the TrialBox list with a 20 % manual spot-check, and the savings in §2.2 are measured. The comparison of lists (FR-SCR-13) is produced by the pilot team, who import the CRC's existing log weekly; the CRC only keeps the log as today. The **chart review** (≈ 78 h per study, TB-DS-04 §8.4) is pilot-only time, funded from the pilot budget with backfill, and is not counted in the clinical budget (TB-TMPL-01 §5).
5. **One channel per task.** A person finishes each task in one place: the phone page, the desktop page, the mail, or (L) the REDCap panel (NFR-USAB-05).

### 2.2 Interactions per role per week (E)

Minutes are per week for a PI with 2 recruiting studies and a CRC with 5 studies. "Saved" is time removed from the today column in §1. **The "Saved" column applies from pilot Phase 2 and in steady use**; Phase 1 is shown in its own rows below the table. The release tag shows when the feature arrives.

| Role | Interaction | Freq./week | Cost (min) | Replaces | Saved (min) | Net | Release |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PI | Open the clinic-day or Monday list, mark 5–15 candidates | 1–2 | 10–15 | Ad-hoc candidate recall, CRC paper notes | 40–80 | −30 to −65 | S2 (was M1; list built, clinic-day mail §5.1) |
| PI | Approve the ruleset on S20 (one page) | ≤ 0.5 | 6 | Reading CRC criteria notes, writing the checklist with the CRC | 30 | −24 | S2 (BD-13) |
| PI | Confirm study approval record and team on S21 | ≤ 0.1 | 3 | Signing the paper study start list | 5 | −2 | S3 (team); approval record H (was M1) |
| PI | Approve feasibility report release | ≤ 0.5 | 5 | Assembling counts with IT | 60–120 | −55 to −115 | S1 (was M1) |
| PI | Confirm / dismiss AE task | 0–3 | 2 each | Finding the AE in notes late | 5 each | −3 each | L (was M2, BD-08) |
| CRC | Upload protocol, pre-tick code rows on S20, send to PI | ≤ 0.5 | 10 | Building a screening checklist by hand | 60 | −50 | S2 (BD-13) |
| CRC | Study set-up S21 incl. approved explainer upload | ≤ 0.1 (once per study) | 20–30 | Binder, research-office form, ad-hoc lists | 30–60 | −10 to −30 | S3 (FR-STUDY-07; approval-record upload H) |
| CRC | Consent explainer | 0 | 0 beyond the S21 upload (draft generated with the ICF, goes live automatically, BD-15) | Writing a patient leaflet | 60–120 per study | −60 to −120 | S0 (draft); go-live H (was M1) |
| CRC | Work the daily digest, "Today" and "Marks today" on S8 | 5 | 5 each | Printing clinic lists, re-reading charts | 60–120 per day of screening | −200 to −500 | S4 (sections 1, 2, 4 and 6 of §3.2 are new; section 7, study cards, is built); tasks and queries L (FR-UI-04b, FR-SCR-08). Saving assumes the step-4 sections ship |
| CRC | Record contact outcome; write screening no. into REDCap at record creation | 5–20 | 0.2 each | Paper/Excel screening log entry | 0.5–1 each | −1 to −15 | S2 (FR-SCR-10c, BD-18) |
| CRC | Screening log export for monitor | ≤ 1 | 2 | Rebuilding the log | 30–60 | −28 to −58 | S2 (FR-SCR-10b) |
| CRC | Accept pre-fill cards in REDCap | per visit | 1 per form + review | Transcription ≥ 3 min per data point [C2] | (E) −50 % structured | negative | L (was M2) |
| RA | Review reconciliation mismatches | 1 | 15 | Manual EMR-vs-registry check | 60–180 | −45 to −165 | L (was M2, FR-STUDY-03) |
| RA | Personal database import (once per file layout) | one-off | 30 | Manual re-keying | hours | negative | L (was M2); the hospital-stage comparison log uses ICD-14 `shadow_log` (H) |
| Admin | Health page and alerts | 1–3 | 10 | — (new system) | — | +10 to +30 | S4 (S13 tabs; accepted: IT is not a clinical role; keep ≤ 30 min) |
| CRA | Remote aggregate view | 1 | 5 | E-mail requests to CRC for counts | CRC saves 15 | −15 for CRC | L (FR-REP-05) |
| Research office | Annual progress-report export per study | 1 per year | 5 | E-mailing CRCs for counts, compiling | 30–60 per study (and the CRC's counting) | −25 to −55 | S2 (FR-REP-09) |
| Ethics | — | 0 | 0 | — | — | 0 | — |

The admin row is the only positive one in steady use and is kept under a ceiling. If any clinical row turns positive in Phase 2 (§9), the feature behind it is changed before any later (L) work is added.

**Pilot Phase 1 (weeks 1–6) — added time, agreed in advance (E).** Usual screening continues, so no saving is claimed.

| Role | Added in Phase 1 | Per week (E) | Who pays |
| --- | --- | --- | --- |
| PI | Mark TrialBox candidates on top of usual practice; confirm suitability from the chart for TrialBox-only finds | +10 to +20 min | Clinical, agreed by the PI |
| CRC | Record contact outcomes for TrialBox candidates; read the existing weekly list mail (the digest arrives with the release before week 7, TB-DS-00 §2) | +15 to +30 min | Clinical, agreed by the CRC and department head |
| CRC, physician reviewers | Blinded chart review, ≈ 78 h per study over 12 weeks (two reviewers in strata A/B, one in C; TB-DS-04 §8.4) | ≈ 6.5 h per study-week | **Pilot budget**, with backfill or seconded reviewers (TB-TMPL-01 §5); not clinical budget |
| CRC, PI | Baseline self-log before go-live | ≈ 10 min/day for 2 weeks | Pilot budget (TB-TMPL-07) |
| Pilot team | Weekly import of the CRC's log for the comparison (FR-SCR-13) | 1–2 h per site | Pilot team |

**Phase-2 clinical cost.** In Phase 2 everyone keeps a 20 % manual spot-check of the clinic list (≈ 20 % of today's pre-screen time); it is clinical time and is included in the Phase-2 measurement.


### 2.3 One-click defaults (examples)

| Screen | Default |
| --- | --- |
| Home | The role's work list opens first; the header command field is on every page (FR-UI-01) |
| PI list | Opens on today's clinic (clinic day) or the study with the most new candidates; Your clinic first; sorted by visit time |
| Mark | "Approach" is the primary button ("Ask treating doctor" for others' patients); "Not suitable" asks for a reason from the study's pick-list |
| Contact outcome | Pick-list with "Reached – visit booked" first; date defaults to today |
| Step-up | None in the build. Hospital stage only (H, BD-17): one TOTP per session for the first approval or reveal |
| Feasibility input | Study name proposed from the pasted text; sites = own site; data window = last 3 years |
| Reconciliation | "EMR right" pre-selected when the EMR value is newer and from a structured source |
| Notification settings | Role defaults from §5.3; one switch to snooze for 1 week |

## 3. The key centre: one home per role

Each role lands on one home after login (FR-UI-14). The home is the role's work list; there is no separate entry page. The command field (S1) sits in the header of every page. Ordering is fixed so people learn where things are. Counts are pseudonymised; chart numbers appear only after an audited reveal (BD-04, FR-UI-13).

### 3.1 PI home (S16) — "This week"

Order, top to bottom:

1. **Needs your decision** (approval and safety cards): AE suggestions (L, BD-08), ruleset approvals (BD-13, one page: criteria with protocol quotes, amber rows opened once, **Approve all** or edit a line), study approval records and teams to confirm (S21), feasibility release requests (FR-FEAS-08), cross-site query approvals (L). Oldest first. Each card has one primary action.
2. **Clinic candidates** for today (on a clinic day) or the next 7 days, per study, in three groups: **Your clinic**, **Other study doctors** (folded), **Other doctors** (Ask treating doctor); sorted by visit time, then by most criteria met. Each row: pseudonym, visit time, "6 of 9 met, 2 unknown", new dot, mark buttons; after Approach on a patient seen today, "CRC notified" / "CRC on the way" (FR-SCR-07c).
3. **Waiting for others**: items the PI marked "Need info" or "Ask treating doctor" and their status.
4. **My studies** (folded): enrolment against forecast per study, one line each.

**Never shown on the PI home (or any clinician screen, FR-UI-17):** admin or health information; job queues; model names, scores, confidence or probabilities (the built patient page still shows `confidence` and the judge model; removed in build step 2, FR-UI-17); patients outside the PI's studies; patients without a coming visit (they are on the full study list, one tap away); chart numbers before reveal; anything that needs typing.

Phone layout (390 px): sections 1 and 2 only, as cards; 3 and 4 behind "More" (FR-UI-09). Clinic-PC layout (≤ 480 px beside the EMR) shows the same in one column (FR-UI-19).

### 3.2 CRC home (S8) — "Today" and "This week"

Order:

1. **Today**: visits today of candidates and enrolled patients, by time; for each, the next step in the six-step bar (find, PI review, contact, explain, consent, enrol) and, **before consent**, "Would need checking after consent: MMSE (last 2026-07-01)" (never "to collect"; TrialBox never prompts a research procedure before consent, FR-SCR-12); after consent, "To collect at the screening visit".
2. **Marks today** (FR-UI-18): PI marks made today on patients with a visit today, refreshed automatically while the page is open (no mail, no push), with the clinic room and an "I'm going" button that shows "CRC on the way" on the PI's screen. This supports the real recruitment moment: the doctor introduces the study during the visit and the CRC explains in detail (IC補助) while the patient is still in the hospital. A study may also switch on an in-hours immediate notice for this case (FR-NOTIF-03, off by default, counted in the CRC budget). "Ask treating doctor" items appear here too.
3. **Tasks from PIs** (L, FR-SCR-08): "Need info" items, "Approach" items to contact, oldest first, with due dates.
4. **Pre-screens to prepare**: new candidates per study since the last list, not yet sent to the PI.
5. **Queries and data checks** (L): unverified fields and reconciliation mismatches per study.
6. **This week**: visits in the next 7 days (folded list), pipeline counts found → contacted → consented → enrolled per study.
7. **My studies** (folded): one line each with pending counts (built, FR-UI-04a).

**Built today:** only section 7 (study cards with next action, week counts, registry counts). Sections 1, 2, 4 and 6 are build step 4 (TB-DS-20; visits from the appointment source FR-ING-03b at hospital stage, from the synthetic hospital in the build; candidates from the weekly list; counts from the registry). Sections 3 and 5 are L (FR-UI-04b, FR-SCR-08, pre-fill). Numbering matches TB-DS-09 S8 (1–7).

**Never shown on the CRC home:** model internals, scores or model names (FR-UI-17); studies outside scope; admin pages; patients whose consent or contact preferences say "do not contact" (S0 of the cascade, FR-SCR-01); duplicate rows for the same patient across studies (one row with study badges).

### 3.3 RA / data manager home (S17) — "Study data status"

Order:

1. **Data checks this week**: reconciliation mismatches per registry (EMR vs registry, §6.4), oldest first.
2. **Cohort changes**: new patients meeting the cohort definition. For a **dynamic** cohort, also patients whose data no longer meets it; for an **enrolled** cohort (e.g. RA-BIO, GOUT-COH) membership is fixed by enrolment and only new candidates are shown (cohort kind set on S21, FR-STUDY-02).
3. **Data status per study**: last data pull, record counts, missing-value rate per key field, last export.
4. **Imports**: personal database imports and their mapping status (§6.2).

**Never shown:** patient names or chart numbers (RA work is pseudonymised; reveal follows the same audited path when the RA has `coordinator` scope); trial recruitment screens unless the RA is on a trial.

### 3.4 Other homes

| Role | Home | Contents |
| --- | --- | --- |
| `admin` | S13 health | Red items first, then last ingest, night schedule, backups, users expiring in 14 days |
| Research office (`coordinator` + `office`) | S4 study list with S21 status | Studies missing set-up items or with approvals expiring in 60 days; annual report export (FR-REP-09) |
| `cro` | Study aggregate view (L) | Enrolment vs forecast, screening outcomes (k = 10), open queries count |
| `auditor` | S15 audit browser | Filters preset to the last 30 days |
| `viewer` | S3 feasibility reports | Own site, k = 5 inside (N-01) |

## 4. Full study cycle

Legend for "Where": **TB** = TrialBox web (on-prem); **Mail** = e-mail channel; **RC** = REDCap; **EMR** = hospital EMR; **Out** = outside any system (phone, in person).

### 4.1 Interventional trials

| # | Step | Who | Where | Automated | Person does | Release |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | Feasibility | CRC or PI; sponsor asks | TB (S2/S3) or Mail | Criteria → ruleset draft; counts and funnel on the lake; k-suppression; report with versions (FR-REP-01) | Paste criteria; PI approves release outside the site | S1 (was M1) |
| 1 | Study set-up | CRC or research office with the study team; PI confirms | TB (S21) | Pre-filled from uploaded protocol and ICF; REDCap link test | Fill type, team, REDCap link, screening-number format, reasons, and which introduce rule the approved protocol allows (BD-19); PI confirms approval record and team | S3 (was M1) |
| 2 | Protocol → ruleset | LLM drafts; CRC prepares and pre-ticks codes; PI approves (BD-13, one Approve) | TB | Protocol ingested; ruleset drafted with a source quote per criterion; codes proposed (TB-DS-10); review pages pre-filled | CRC pre-ticks the code mapping and sends the page; PI approves on the one page with one Approve (S20, FR-FEAS-12) | S2 (was M1) |
| 3 | Ethics | PI, CRC; ethics office | Out (their process) + TB for the pack | Submission pack from TB-TMPL-01; consent explainer draft generated from the ICF and added to the same submission (BD-15); identified lists blocked until the approval record exists (FR-STUDY-06) | Submit as today; enter the approval and upload the approved explainer on S21; PI confirms; sponsor approval recorded for sponsored trials | H (was M1) |
| 4 | Candidate list | System | TB, Mail (pseudonyms only, BD-04) | Weekly list Monday 03:00 (FR-SCR-02a), nightly changes (FR-SCR-02b); PI list mail on clinic days or Monday (§5.1) | — | S2 (was M1) |
| 5 | Contact by the doctor | PI (doctor contacts patients); CRC arranges | Out; EMR for chart | Reveal after reason (FR-UI-13); "Open in EMR" (FR-SCR-04a); screening number assigned on Approach (BD-18); "Marks today" on S8 | PI marks Approach; introduces the study in clinic; CRC explains in detail while the patient is there or by phone; CRC records the outcome | S2 (was M1) |
| 5a | Treating doctor is not an investigator | CRC asks the treating doctor (主治医の了承); the treating doctor introduces the study, or a study investigator does so after the treating doctor's agreement, as the approved protocol states (BD-19, S21) | Out | "Ask treating doctor" item on S8 (FR-SCR-07b) | CRC asks; records agreement or not as a contact outcome | S4 (was M1) |
| 6 | Consent | PI / CRC | Out (paper or e-consent outside TB); TB for explainer | The uploaded committee-approved explainer is live automatically once the approval record is complete; fingerprint check withdraws anything else (BD-15); site can switch the explainer off | Explain; sign; consent date read from REDCap, or CRC taps "Consented" for non-REDCap studies | H (was M1) |
| 7 | Screening eCRF | CRC | RC (or sponsor EDC) | TB reads the REDCap record through the project link (`tb_screening_no`, FR-RC-16) to update the log (S3). Later: pre-fill cards (S10, L) | Create the record and enter as today, writing the screening number into `tb_screening_no`. Later: accept each value | S3 read; L pre-fill |
| 8 | Enrolment | PI confirms eligibility; CRC registers | RC / sponsor system | Log updated from REDCap read | Confirm in REDCap | S3 (was M1) |
| 9 | Visits | CRC | TB (lists), RC (data) | Visit windows (due, overdue, out of window) from protocol schedule and appointments (S11) | Book; collect | L (window list); visits shown from appointments H (FR-ING-03b) |
| 10 | AE / con-med | PI decides; CRC prepares | TB (S11) | Suggestions from labs and notes, graded CTCAE v5.0; con-med checks; investigator task (BD-08) | PI confirms or dismisses with reason | L (was M2) |
| 11 | Monitoring | CRA; CRC prepares | Out / RC for SDV; TB for aggregates and prep | Screening log export (FR-SCR-10b, S2); unverified-field list (L); aggregate CRA view (L) | CRC prints nothing; CRA reads aggregates | S2 log; L rest |
| 12 | Close-out and archiving | CRC, PI | TB, RC | Final screening log and audit export per study; retention ≥ GCP (N-03); ruleset frozen | Request archive pack; PI signs off | S2 (export); archive pack L |
| 13 | Annual progress report | Research office | TB | Counts per status and year (FR-REP-09) | Export; paste into the committee form | S2 (was M1) |

### 4.2 Registries and observational studies

| # | Step | Who | Where | Automated | Person does | Release |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | Cohort definition | PI or RA | TB | Same protocol / criteria → LLM-drafted ruleset path (BD-13); S0 checks the consent scope of the study (opt-in, opt-out, waiver) | Paste definition; PI approves (BD-13) | S2 (was M1) |
| R2 | Data pull | System | TB lake | Defined variables per cohort member, from the nightly snapshot (BD-11), with source and date per value | — | S1 (in TB, pseudonymised) |
| R3 | EDC / REDCap fill | RA | RC | Later (L): proposed values as cards in REDCap (S10); never auto-saved; form stays Unverified | Accept each value | L (was M2) |
| R4 | Data quality | RA | TB | Reconciliation registry vs EMR (§6.4); missing-value and out-of-range report | Decide per mismatch | L (FR-STUDY-03) |
| R5 | Export | RA, PI | TB | Study-scoped export with data dictionary; D2 pseudonymised with date shift if leaving the identified zone (N-08); OMOP optional (L) | Request; PI approves if leaving the site | L; OMOP L |

Where the registry already lives in the hospital REDCap, R2 and R4 use the read connector (S3, BD-05); nothing is written to REDCap (writes are L).

## 5. Alerts and lists

### 5.1 PI list — on each clinic day, or every Monday

PIs run fixed clinic days, and stable AD or RA patients return every 4–12 weeks, so a Monday list of the next 7 days alone misses the moment of the visit.

- **When (default where the appointment source exists):** **07:00 on each of the PI's clinic days**, with that day's candidates first and the rest of the week folded below. **Fallback** (no appointment source, or the PI's choice on S19): Monday 07:00 after the weekend re-check window (Saturday 22:00 to Monday 06:00, BD-11), with the next 7 days.
- **What:** for each of the PI's studies, candidates in three groups: Your clinic, Other study doctors, Other doctors (Ask treating doctor). Per row: pseudonym, visit time and clinic, "met / unknown / needs PI" counts, new marker. Patients with no appointment source show "next visit: unknown" (FR-ING-03b). A link to the full study list sorted by next visit (S5) covers candidates beyond 7 days.
- **Channel:** e-mail (S2) with pseudonyms only and a link to the on-prem list (BD-04, FR-MAIL-03); PWA push (L) with no patient content (§5.5). The mail is useful even when the link cannot be opened from the PI's device: pseudonyms, times and counts let the PI act on the clinic PC. The screening number never appears in mail (it is D4, BD-18); it is shown on the on-prem list. **Clinic days** are proposed from the appointment source (practitioner schedule, FR-ING-03b) and confirmed once by the PI on S19 (`clinic_days` in TB-DS-07 `notify_settings`); with no appointment source the Monday list is used. **Release:** from go-live the built weekly list and the existing list mail; the clinic-day list from the release before pilot week 7 (TB-DS-00 §2).
- **Empty day or week:** no mail is sent. A one-line "nothing new" is sent only if the PI opts in.
- **Subject (FR-MAIL-02 grammar):** `[AD-01] TODAY list: 3 candidates in your clinic · J-2027-0215-01` (clinic day) or `[AD-01] WEEK list: 4 candidates with visits Mon–Fri · J-2027-0215-01` (Monday).

### 5.2 Daily CRC digest

- **When:** working days, generated 05:30–06:00 (BD-11), delivered at the CRC's chosen time (default 07:30).
- **What:** today's visits with the next step for each; new pre-screens; PI marks since yesterday; (L) tasks due and unverified fields.
- **Channel:** e-mail (S2); PWA push (L).
- **Merged across studies:** one digest per person per day, never one per study.

### 5.3 Real-time only for safety and approvals

| Event | Recipient | Real-time? |
| --- | --- | --- |
| AE suggestion graded ≥ 3 (CTCAE v5.0) | Study PI(s) | Yes (L) |
| AE suggestion grade 1–2 | Study PI(s) | No, in the next digest or the next PI list |
| Approval request (ruleset, feasibility release, cross-site query) | Approver | Yes, but at most one message per 2 h per approver (batched) |
| PI marks Approach on a patient with a visit **today** | The study's coordinators on duty (S8 "I'm on duty today" toggle, one tap, default on; FR-UI-18) | On screen: "Marks today" pane, auto-refresh (always). By mail/push: only if the study switches on the in-hours immediate notice (off by default; study and clinic room only; outside the weekly CRC count but at most 2 per day per CRC) |
| Approval result | Requester | No, next digest; real-time only if the requester is waiting on the page |
| System failure (FR-OPS-08) | Admin | Yes, de-duplicated |
| Everything else | — | Digest or list only |

### 5.4 Alert budget and fatigue rules

Alert budget per role per week (excluding safety and the admin's failure alerts):

| Role | Budget | Contents |
| --- | --- | --- |
| PI | ≤ one list per clinic day (at most 5) + ≤ 2 | PI list (one per clinic day, or Monday) + ≤ 2 approval batches |
| CRC | ≤ 7 (+ N3 ≤ 2 per day) | 5 daily digests + ≤ 2 approval requests or results (ICD-13 N4); in-hours notices (N3) are outside the weekly count but capped at 2 per day per CRC and are never dropped by the budget |
| RA | ≤ 2 | Weekly data-status mail + import results |
| Admin | as needed, de-duplicated | FR-OPS-08 events |
| CRA (`cro`) | ≤ 1 | Weekly aggregate summary (L) |

Rules:

1. **Batching.** Non-safety items are held for the next digest or list. Approval requests are batched per approver per 2 h.
2. **No duplicates.** One item reaches one person through one channel once. If it was read on the web, the push and mail versions are dropped. The same patient in several studies is one line with study badges.
3. **Snooze.** Each person can snooze non-safety notices for 1 day or 1 week with one tap; safety alerts cannot be snoozed but can be routed to a named deputy PI.
4. **Quiet hours.** Default 20:00–07:00 local and weekends: nothing is sent except safety alerts, which can also be held to 07:00 if the site decides.
5. **Budget enforcement.** If a role would exceed its budget, the extra items are merged into the next scheduled message, never sent separately. The admin page shows per-role counts so the budget can be checked (FR-NOTIF-08).
6. **Every notice says why it was sent and how to stop it** (one link to settings).

### 5.5 Channels

| Channel | Release | Content rule |
| --- | --- | --- |
| E-mail (existing mail channel) | S2 (was M1) | Pseudonyms only; link to the on-prem page (BD-04, FR-MAIL-03); allowlisted recipients (FR-MAIL-06) |
| PWA push to phone (installed from the TrialBox web page, no app store) | L (was M2) | **No patient content at all**, not even pseudonyms: "AD-01: 4 candidates this week · open TrialBox". Web Push messages travel through the phone vendor's push service, so the hospital must allow outbound access to it and the payload is encrypted (RFC 8291). Opening the item needs the phone on the hospital network or VPN and a TrialBox login. |
| LINE / Microsoft Teams | L (was C) | Same content rule as push (TB-DS-00 §2 "Could / later") |
| SMS / phone calls to staff | Not planned | — |

Assumption to be confirmed per site (TB-DS-15 PR-07): PIs may use hospital-issued or personal phones depending on the site's policy; the PWA must work on both, and must not cache patient data on the phone (no offline list). **Fallback if phones cannot reach the hospital network:** the PI uses the clinic PC layout (FR-UI-19), and the mail stays readable with pseudonyms and counts only.

## 6. Data sources

### 6.1 Hospital systems

| Source | Site | Path | Release |
| --- | --- | --- | --- |
| EMR (SSI, Fujitsu) via SS-MIX2 standardized storage | Japan head hospital | Nightly export, FR-ING-03; appointments from the vendor's 予約 export (FR-ING-03b) | H (was M1) |
| CGMH self-developed EMR | CGMH | Site extract via mapping file | H (was M1) |
| Hospital DWH | Both, where present | Read-only extract via mapping file; same pseudonymisation | H (if the site provides it) |
| CGRD (Chang Gung Research Database, de-identified) | CGMH | Pre-approval feasibility counts only (answer 00:47) | H (was M1) |
| Hospital REDCap | Both | Read connector (records, data dictionary), BD-05 | S3 read (simulator in the build); L write via External Module |

### 6.2 PI personal databases

Many PIs hold their own cohort in Excel, Access, FileMaker or a personal REDCap project. They are valuable and often the only record of research variables (scores, phenotypes) that the EMR does not hold.

**Safe import path (into the pseudonymised lake):**

1. The PI or RA uploads the file on the on-prem web page (never by e-mail; mail is D1/D3 only, FR-MAIL-06). The file lands in the identified quarantine area, encrypted, and is deleted within 7 days after import, as for any extract (FR-ING-18).
2. A mapping step asks once per file layout: which column is the chart number (or name + birth date for matching), which are dates, which are values, which columns to drop. Identifier columns are matched to the pid through the pid map and then dropped; free-text columns go through the PHI pass (FR-DEID) before leaving the identified zone.
3. The importer declares ownership and consent scope: owner (PI), study, ethics approval number, consent type (opt-in / opt-out / waiver), allowed use (this study only by default).
4. The data appear as a study-scoped dataset in the lake, visible only to that study's roles. Using it for another study needs a new ethics approval number and the owner's approval.
5. Every import is audited (who, file hash, row counts, dropped rows with reason).

| Format | Release |
| --- | --- |
| XLSX / CSV with an admin-written mapping file | H (built path FR-ING-07a) |
| XLSX / CSV with a self-service mapping wizard for the PI / RA | L (was M2) |
| Personal REDCap project on the hospital REDCap | S3 read connector; real project H |
| Access (.accdb) and FileMaker (.fmp12) | Export to XLSX/CSV first (L wizard); native readers L |

### 6.3 Ownership and consent scope

| Data | Owner | Who may use it | Basis |
| --- | --- | --- | --- |
| EMR / DWH data in the lake | Hospital | Studies approved at the site, by role and scope (AM-01) | Hospital ethics approval per study; APPI / PDPA per TB-DS-03 |
| CGRD | Chang Gung Medical Foundation | De-identified feasibility counts | CGRD rules |
| PI personal database | The PI's study | That study only by default | The study's own ethics approval and consent |
| Registry in REDCap | Registry PI | Registry roles; read by TrialBox under a project token (BD-05) | Registry approval |
| Patient contact preferences | Patient, held by the hospital | Cascade step S0 removes "do not contact" patients before anyone sees them | Hospital opt-out records |

### 6.4 Reconciling registry values against EMR values

For each registry variable mapped to an EMR source (e.g. CRP, eGFR, DAS28 components, prednisolone dose), TrialBox compares the registry value with the EMR value for the same patient and date window and lists:

- **Match**: not shown.
- **Mismatch**: registry and EMR differ beyond a tolerance per variable (unit-normalised, TB-DS-10).
- **Missing in registry**: EMR has a value in the window, registry does not.
- **Missing in EMR**: registry has a value with no EMR source (could be outside data; shown for information).

The RA decides per item. TrialBox never changes the registry (read only, BD-05). Later (L) the accepted correction is proposed as a card in the REDCap panel and saved by the RA in REDCap.

## 7. Medplum: role statement (aligned with BD-01)

**Today and in the build steps:** TrialBox runs on HAPI FHIR 8.12 with the built console accounts (S0); TOTP is added at the hospital stage (H, BD-01). Nothing in S1–S5 depends on Medplum.

**Later (L) candidate.** A spike evaluates Medplum for four jobs. Migration happens only if the spike passes (BD-01).

| Job | What it would add for clinical staff | What it would not change |
| --- | --- | --- |
| FHIR store (replace HAPI) | Nothing visible; faster to build new screens on | Screens, roles, lists, the lake |
| Auth (accounts, OIDC, hospital SSO) | One login with the hospital account where the site wants it | 2FA stays required; roles stay BD-03 |
| Questionnaire-based EDC-lite (**L**: both pilot sites have REDCap and the registries live there; built only if a named study without REDCap appears, TB-DS-00 §2) | Studies without REDCap get simple forms with pre-fill cards | REDCap stays the EDC where the site has it; EDC-lite is not a regulated EDC |
| Subscriptions and notifications | Server-side triggers for the later (L) push alerts (§5.5) | Push still travels through the phone vendor's push service; content rules of §5.5 still apply |

**What Medplum is not:** a hospital EMR, a patient app, or a reason to move data off the box. It runs on the same on-prem appliance.

## 8. Monitoring

| View | Who | Contents | Release |
| --- | --- | --- | --- |
| Site monitoring view | PI, CRC (study scope); research office (all studies, `office`) | Screening log (screening number, pseudonym, status, dates, reason category; FR-SCR-10a, ICH E6(R3) columns in TB-TMPL-03); funnel found → contacted → consented → enrolled; enrolment against the feasibility forecast (forecast = feasibility count × site's planned approach and consent rates, editable by the PI) | S2 (log, funnel); forecast line H (S21 section 8) |
| Data quality | CRC, RA | Unverified fields per form; reconciliation mismatches (§6.4); missing items for coming visits | L for reconciliation (FR-STUDY-03) and for unverified fields (needs REDCap form status via the module) |
| Annual progress report | Research office | Counts per status and year per study (FR-REP-09); k = 5 inside the site | S2 (was M1) |
| Protocol-deviation hints | PI, CRC | Visit out of window; consent date after the first study procedure; eligibility criterion not met at enrolment by the record; prohibited con-med started. Each a card with evidence, never a deviation report on its own | L (was M2) |
| Sponsor / CRA view | `cro` | Aggregates only: counts per stage, screen-failure reasons, enrolment vs forecast, open query count; k = 10 (N-01) | L (FR-REP-05) |

Deviation hints are hints: the PI decides whether a deviation occurred and reports it through the site's normal process.

## 9. Measurement in the pilot

### 9.1 Baseline (before go-live)

- **Time-motion baseline (N-17 baseline):** 2027-01-11 to 01-22 at both sites (TB-PLAN-01 MS-05b), or the two normal working weeks before a moved go-live; it always ends before that site's Phase 1 starts; using the one-page self-log in TB-TMPL-07 (study, task type from §1 tables, start/stop, interruptions) for 2 CRCs and 2 PIs per site, plus one observed clinic half-day per site. Owner: the site PI; administered by the research office; engineer prepares the form (TB-PLAN-01 WP-00, MS-05b). The window avoids 年末年始 (Japan) and Lunar New Year (CGMH); if it cannot, the seasonal caveat is stated with the result. Observation of staff time is agreed with the department head and, where the hospital requires it, noted to the ethics office (TB-TMPL-01 Part F2).
- **Workload baseline:** raw NASA-TLX for the current screening process, reported descriptively; no SUS for the current process (it is not one system).
- **Interviews and formative test before feature freeze** (TB-TMPL-07): 60-minute interviews with 2 CRCs, 1 PI, 1 research-office member, the REDCap admin and the IT security contact per site; a formative usability test in two rounds (TB-PLAN-01 WP-00b): round 1 on S20, S21 and the PI list mail by 2026-12-18 (MS-05c), round 2 on S16, S8 "Today / Marks today", S18 and S19 before pilot week 7 (MS-05d) (TB-DS-09 §11).

### 9.2 During the pilot

Phase 1 (weeks 1–6) measures recall and records added time; Phase 2 (weeks 7–12) measures the savings (BD-16).

| Measure | How | Phase | Success threshold |
| --- | --- | --- | --- |
| Pre-screen time per candidate and per study-week | Same self-log method, weeks 9–10 | 2 | ≥ 50 % reduction against the site baseline (N-17) |
| Net weekly time per clinical role | §2.2 rows, self-log | 1 (reported as added) and 2 (judged) | Phase 2: ≤ 0 for PI and CRC; chart review and comparison are pilot-team time |
| Duplicate entry | Inspection of every input screen against §2.1 rule 2 | before go-live | 0 fields that duplicate a value held in EMR, DWH or REDCap |
| Clicks / taps per task | Instrumented UI (counts only, no content) | 1 and 2 | Mark a candidate ≤ 2; clinical sign-off ≤ 2 plus one per amber row opened; feasibility from text ≤ 3 (NFR-USAB-01); contact outcome ≤ 2; TOTP is not counted (H) |
| SUS (System Usability Scale) | After 4 and 8 weeks, all PI and CRC users | 1 and 2 | Mean ≥ 70 |
| Raw NASA-TLX | After 8 weeks, same people as baseline | 2 | Reported per person, baseline vs Phase 2; **no pass threshold** (n ≈ 4 per role per site) |
| Alerts | Count per role per week; opt-out and snooze | 1 and 2 | Within §5.4 budget; no more than one PI and one CRC per site snoozing all notices for more than two consecutive weeks (reasons reviewed with them) |
| PI list use | Opened by the visit day (clinic-day mail) or within 2 working days (Monday) | 2 (Phase 1 reports use of the built weekly list descriptively) | ≥ 80 % of lists per PI |
| Recall | Per TB-DS-04 | 1 (checkpoint week 6) and 2 | N-16 |

### 9.3 Decision after the pilot

If any clinical role's net time in Phase 2 is positive, or SUS < 70, the next plan starts with fixing that role's home and inputs before adding features.

## 10. Assumptions and open items

| ID | Item |
| --- | --- |
| CO-01 | All workload minutes in §1–§2 are estimates (E) until §9.1 measures them; site interviews (TB-REV-006c R-02) confirm or correct the personas and tasks before feature freeze. |
| CO-02 | Sites allow PWA push via vendor push services (outbound) for the later (L) push; if not, push is off and e-mail stays the channel. |
| CO-03 | PI device path per site (personal phone on Wi-Fi/VPN, hospital phone, clinic PC only) to be confirmed in writing by the IT lead (TB-DS-15 PR-07); no patient data is cached on phones. |
| CO-04 | Consent and enrolment status can be read from REDCap for studies that use the hospital REDCap, once the REDCap admin adds `tb_screening_no` (or the study uses the MRN alternative) and the field map is set on S21 (BD-18); for sponsor-EDC studies the CRC taps once. |
| CO-05 | Real-time AE alert threshold (grade ≥ 3) to be agreed with site PIs. |
| CO-06 | The enrolment forecast formula (feasibility count × planned rates) to be agreed with PIs. |
| CO-07 | CRA patient-level remote view is out of scope under BD-03 and the "sponsors never get patient-level data" answer; changing it needs a new baseline decision. |
| CO-08 | Access and FileMaker native readers are later (L); users export to XLSX/CSV. |
| CO-09 | TrialBox learns that the ICF and explainer are approved when the CRC enters the approval and uploads the approved explainer on S21 and the PI confirms; it has no link to the ethics office system. If a site's ethics office can send a machine-readable approval, that replaces the CRC entry. Committee practice on explainer wording edits and on approving Phase 2 is confirmed per site (TB-REV-006c R-07). |
| CO-10 | BD-15 v0.5 and BD-16..18 in TB-DS-00 are proposed; this document follows them pending the owner's confirmation. |
| CO-11 | Sponsor practice for approving patient-facing supplementary material in industry trials, per site (TB-REV-006c R-09). |
| CO-12 | Research-office fields and numbers for the annual progress report, per site (R-08); FR-REP-09 adjusts to them. |

## 11. Definitions and references

### 11.1 Definitions used in this document

Shared terms are defined once in TB-DS-01 Appendix C. Terms used mainly here:

| Term | Meaning here |
| --- | --- |
| Net time | Minutes a role spends on a TrialBox interaction minus the minutes of the task it replaces (§2.2); negative = load removed |
| Work list | The role's home page (S16, S8, S13, S4); the first page after login |
| Marks today | PI marks made today on patients with a visit today, shown live on S8 (FR-UI-18) |
| Clinic day | A weekday on which the PI holds an outpatient clinic, from the appointment source or set by the PI (`clinic_days`, TB-DS-07 §4.11) |
| Introduce rule | Who may first speak to a patient about a study, as the approved protocol states (BD-19) |
| (E) | Estimate, not a measurement at our sites |

### 11.2 References

| Ref | Document |
| --- | --- |
| [O1] | ISO/IEC/IEEE 29148:2018 §9.3 Operational concept (OpsCon) content, used as the frame of §1–§5 |
| [O2] | ICH E6(R3) Good Clinical Practice: investigator and delegated-staff duties, screening log (§4, §8) |
| [O3] | 人を対象とする生命科学・医学系研究に関する倫理指針 (Japan); 人體研究法 (Taiwan): who approaches participants and consent scope (§4.2, BD-19) |
| [O4] | Sources [C1]–[C4] of §0.1 (context only) |
| [O5] | TB-DS-00 (BD-03, BD-13, BD-15..BD-20, N-17), TB-DS-01, TB-DS-07, TB-DS-09, TB-DS-20 |

## Change history

| Seq | Version | Date | Author | Change |
| --- | --- | --- | --- | --- |
| 1 | 0.1 | 2026-11-07 | Claude for Aimedics | Folded in TB-DS-00 v0.4: BD-13 (LLM drafts ruleset, PI approves one page), BD-15 (explainer submitted with ICF, released automatically; no manual release step). First draft after the owner's request of 2026-11-07 03:04 (clinical orientation, workload, key centre, full cycle, alerts, data sources, Medplum, monitoring, measurement). |
| 2 | 0.2 | 2026-11-07 | Claude for Aimedics | TB-REV-006c: one rule with the stated pilot exception and two pilot phases, Phase-1 added-time table, chart review as funded pilot-team time, comparison by import (C-01, C-04, C-21); [C1]/[C2] moved to "context, not basis" (C-24); PI device path and clinic-PC fallback (C-16); who introduces a study and Ask treating doctor, step 5a (C-13); S20 two sign-offs and S21 confirmation inputs (C-09, C-07); BD-17 TOTP in tap counts (C-08); CRC contact outcomes, screening number into `tb_screening_no` (C-06); S21 study set-up input (C-07); ethics office and explainer flow to BD-15 v0.5 (C-05); new §1.8 research office and FR-REP-09 annual report (C-18); §3.2 true built state, Marks today pane, pre-consent wording (C-12, C-14, C-15); no scores (C-11); cohort kind (C-22); §5.1 clinic-day delivery (C-20); in-clinic handover row in §5.3; EDC-lite to C (C-27); §9 baseline instrument, owner, window, interviews and formative test (C-03), NASA-TLX descriptive (C-25), snooze as a count (C-26); CO-01, 03, 04, 09, 10 updated; CO-11, CO-12. |
| 3 | 0.3 | 2026-11-07 | Claude for Aimedics | TB-REV-006d: chart review ≈ 78 h (D-07); Phase-1 CRC row reads the existing weekly mail, spot-check moved to a Phase-2 cost line, CRC row sections 1, 1a, 3, 5 new and 6 built, reconciliation M2 (D-02, D-15); study cycle steps 0 feasibility / 1 set-up (D-15); BD-19 introduce rule (D-04); screening number removed from mail, clinic days from the appointment source, release timing (D-03, D-10, D-02); budgets per clinic day and N3 cap (D-10, D-18); "on duty" defined (D-16); baseline window and two formative rounds (D-08, D-06); sign-off taps include amber rows (D-09); PI list use judged in Phase 2 (D-02). |
| 4 | 0.4 | 2026-11-07 | Claude for Aimedics | TB-REV-006e E-04: personal-database import row tagged M2. |
| 5 | 0.5 | 2026-11-07 | Claude for Aimedics | TB-REV-006f: status points at the build map; TOTP, two-phase pilot and §9 measurement are hospital stage; approval is one page. |
| 6 | 0.6 | 2026-11-07 | Claude for Aimedics | TB-REV-006f §R N7-05: §3 home = role work list with the header command field (FR-UI-01 v0.8); §2.3 step-up H; §1.1 and §2.2 approval rows follow the one-page S20; ethics record only with the gate on. Release cells in §2.2, §4, §5.5, §6 and §8 re-tagged S0–S5 / H / L (was M1/M2/C). |
| 7 | 0.7 | 2026-11-07 | Claude for Aimedics | TB-REV-006g Q-33, S-02, S-03, S-05, S-06, S-08: release cells and prose re-tagged S0–S5 / H / L (legend in §0 cites TB-DS-00 §2); §3.2 sections renumbered 1–7 to match TB-DS-09 S8; §4.1 step 2 one-page S20 with one Approve ("S20 part 1/2" removed); new §11 definitions and references; Seq column. |
| 8 | 0.8 | 2026-11-07 | Claude for Aimedics | TB-REV-006g §R R-29, R-30: dependency versions; §1.1 clinic-day PI list (Monday only as fallback); 14 prose tags re-expressed as S2 / H / L. |
| 9 | 0.9 | 2026-11-07 | Claude for Aimedics | TB-REV-006g §F F-02: Depends-on cites TB-DS-01, -07 and -09 "versions per TB-DS-00R". |
