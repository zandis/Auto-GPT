# TB-DS-11 Risk Management File

| Field | Value |
| --- | --- |
| Document ID | TB-DS-11 |
| Title | Risk Management File |
| Version | 0.7 |
| Date | 2026-11-07 |
| Owner | Aimedics product owner (Changfu Kuo) |
| Author | Claude (for Aimedics) |
| Status | Reference, **hospital stage (H)**. Applies when a hospital uses real patient data; the build on synthetic data follows `20-build-map.md`. |
| Related | TB-DS-00 (baseline), TB-DS-01 (SRS), TB-DS-02 (architecture), TB-DS-03 (security and privacy), TB-DS-04 (verification and operations), TB-DS-16 (regulatory position), TB-REV-006 (review, finding M-04) |

**Approvals**

| Role | Name | Signature | Date |
| --- | --- | --- | --- |
| Product owner (Aimedics) | Changfu Kuo | | |
| Aimedics engineer (risk file maintainer) | (to be named) | | |
| Clinical reviewer, Japan head hospital (site PI) | (to be named) | | |
| Clinical reviewer, CGMH (site PI) | (to be named) | | |
| Security owner (Aimedics) | (to be named) | | |

## 1. Purpose and scope

This file records the hazards that TrialBox could contribute to, their causes, the controls that reduce them, how each control is verified, and the risk that remains. It follows the structure of ISO 14971:2019 (risk analysis, evaluation, control, residual risk, benefit-risk, production and post-production information) because that is the structure clinical reviewers, ethics committees and vendor auditors expect.

TrialBox is **not** a medical device (TB-DS-16). Applying the ISO 14971 structure does not claim device status. It is used here because ICH E6(R3) asks for a risk-based approach to computerised systems used around trials, IEC 81001-5-1 asks for a maintained risk record for health software, and ISO/IEC 27001:2022 clause 6.1 asks for an information-security risk assessment. Security risks are analysed in detail in TB-DS-03 §3 (threat model); this file carries the clinical and use-related hazards, and links to TB-DS-03 for the security mechanisms.

Scope: the hospital stage — the first install that uses real patient data (two-phase pilot BD-16; content by date per TB-DS-00 §2.H) — and the later releases (EDC pre-fill, trial conduct, consortium hub; tag L in TB-DS-20). Hazards that exist only in later releases are marked (L).

**Build stage.** No hazard in this file is live while the system runs only on synthetic and public data (TB-DS-20 §1): there is no patient whose care, opportunity or privacy can be affected. The file applies from the first real-data install. Controls that are already built (tag S0) are kept on in the build and tested by `e2e_simple` and the unit suites, so they are proven before that install.

## 2. Intended use and reasonably foreseeable misuse

**Intended use (from TB-DS-16 §2).** TrialBox helps hospital research staff find patients who might be eligible for a clinical study, estimate how many such patients a hospital has, and prepare research records. Every output is a suggestion that a qualified person reviews. TrialBox does not diagnose, treat, prevent or monitor disease, does not decide a patient's eligibility, and never contacts patients.

**Users.** Investigators (PI), coordinators (CRC, study nurse, SMO staff), CRO specialists (aggregates only), hospital IT and admin, auditors (TB-DS-00 BD-03).

**Reasonably foreseeable misuse considered in this file:**

| ID | Misuse |
| --- | --- |
| MU-01 | A coordinator treats the patient list as the final eligibility decision and enrols without checking the chart. |
| MU-02 | A PI treats "not listed" as "not eligible" and stops manual screening during the pilot. |
| MU-03 | A user accepts all pre-filled values without reading them ("accept all"). (L) |
| MU-04 | A user relies on TrialBox to report adverse events and stops the usual AE process. (L) |
| MU-05 | A user forwards a patient list or screenshot outside the hospital. |
| MU-06 | A user uses the chat box to ask clinical questions about treatment. |
| MU-07 | A sponsor or CRO asks for patient-level data "just this once". |
| MU-08 | A site uses an approved ruleset for a different protocol version. |

## 3. Risk criteria

### 3.1 Severity

Severity is judged by the worst credible consequence for a patient, a study, or the hospital.

| Level | Name | Description |
| --- | --- | --- |
| S1 | Negligible | Inconvenience; no effect on a patient or on study data. |
| S2 | Minor | Wasted staff time; a correctable data entry error caught before use; a study enrols slightly fewer patients. |
| S3 | Serious | A wrong value in a study record used for analysis; an eligible patient denied the chance to join a study; a reportable privacy incident involving a few patients; a protocol deviation. |
| S4 | Critical | An ineligible patient enrolled and exposed to an investigational product because of a TrialBox error; a missed serious adverse event; a privacy breach involving many patients or identifying data leaving the hospital. |
| S5 | Catastrophic | Death or permanent harm contributed to by TrialBox output. Not considered credible for a suggestion-only tool with mandatory human review, but kept for completeness. |

### 3.2 Probability

Probability of the harm, taking the whole chain (the error happens, no control catches it, harm follows).

| Level | Name | Guide |
| --- | --- | --- |
| P1 | Improbable | Less than once in the life of the product at all sites. |
| P2 | Remote | Once in several years across all sites. |
| P3 | Occasional | About once a year across all sites. |
| P4 | Probable | Several times a year. |
| P5 | Frequent | Monthly or more. |

### 3.3 Acceptability matrix

| | P1 | P2 | P3 | P4 | P5 |
| --- | --- | --- | --- | --- | --- |
| **S5** | R | U | U | U | U |
| **S4** | A | R | U | U | U |
| **S3** | A | A | R | U | U |
| **S2** | A | A | A | R | R |
| **S1** | A | A | A | A | A |

A = acceptable. R = reduce as far as practicable; accept only with a benefit-risk justification recorded here. U = unacceptable; the release is blocked until controls move the risk to A or R.

## 4. Hazard analysis

Each hazard lists causes, the initial risk (before TrialBox-specific controls, assuming normal hospital practice), the controls, the verification of each control, and the residual risk. Control IDs refer to the security controls in TB-DS-03 (renamed SC-NN in its revision; earlier drafts used SEC-NN with the same numbers) and to requirement areas in TB-DS-01 (FR-AREA-*). Numbers such as thresholds are from TB-DS-00 §4.

### 4.0 Trace from hazards to requirements and verification

The hazard sections below name their controls in words; this table gives the requirement IDs (TB-DS-01, version per TB-DS-00R) that implement each control and the verification that proves it (test suites TS-nn and gates Gn in TB-DS-04; site checks OQ/PQ in TB-DS-15, hospital stage). Security controls SC-nn are in TB-DS-03 §4.

| Hazard | Requirements implementing the controls | Security controls | Verification |
| --- | --- | --- | --- |
| H-01 Missed eligible patient | FR-SCR-01, FR-SCR-05, FR-SCR-12, FR-FEAS-12, FR-AUTH-13, FR-ING-17, FR-MOD-06, FR-UI-11b, NFR-PERF-08, NFR-PERF-09 | SC-32, SC-40, SC-63, SC-75 | TS-SCR, TS-FEAS, TS-AUTH, TS-ING; gates G1–G3; `e2e_simple`; OQ-03, OQ-05; pilot E1 (H) |
| H-02 Wrong exclusion shown | FR-SCR-06, FR-SCR-07, FR-UI-05, FR-UI-06, FR-UI-17, FR-JP-03, FR-JP-04 | SC-62, SC-63 | TS-SCR, TS-JP, TS-UI (browser walk: no score or model name); OQ-04, OQ-14 |
| H-03 Ineligible patient enrolled | FR-SCR-07, FR-SCR-10a, FR-UI-12, FR-REP-06 | — | TS-SCR, TS-UI, TS-REP |
| H-04 PHI leak | FR-DEID-01, FR-DEID-02, FR-DEID-04, FR-DEID-05a..d, FR-DEID-11a, FR-DEID-11b, FR-MAIL-03, FR-MAIL-06, FR-AUD-02, FR-SEC-05, FR-SEC-12, NFR-PERF-14 | SC-30, SC-31, SC-46, SC-50, SC-51, SC-60 | TS-DEID, TS-MAIL, TS-SEC; gate G5; OQ-12 |
| H-05 Wrong pre-filled value (L) | FR-EDC-02, FR-EDC-06, FR-TC-02, FR-RC-13, FR-ERR-05, FR-AUD-01i, NFR-PERF-15 | SC-48, SC-62 | TS-EDC, TS-RC |
| H-06 Missed AE suggestion (L) | FR-TC-03, FR-TC-04, FR-AUD-01j, FR-NOTIF-03 | — | TS-TC, TS-NOTIF |
| H-07 Wrong reveal | FR-DEID-03, FR-UI-10, FR-UI-13, FR-AUTH-05c, FR-AUTH-05d, FR-AUD-01b, FR-STUDY-06, FR-CHAT-05 | SC-11, SC-16, SC-12 | TS-AUTH, TS-DEID, TS-AUD, TS-STUDY |
| H-08 Model drift or silent change | FR-MOD-05, FR-MOD-06, FR-MOD-08, FR-SEC-04, FR-UI-11b, FR-PLAT-27 | SC-41, SC-42, SC-66 | TS-MOD, TS-SEC; gates G1–G3 on every model change |
| H-09 Downtime or data loss | FR-OPS-04, FR-PLAT-26, FR-PLAT-28, NFR-AVAIL-03 | SC-75, SC-100, SC-101 | TS-OPS, TS-DR, TS-AVAIL |
| H-10 Wrong feasibility numbers | FR-FEAS-03, FR-FEAS-04a, FR-FEAS-04f, FR-FEAS-04h, FR-FEAS-08, FR-FEAS-13, FR-DEID-11a, FR-REP-01 | SC-50, SC-54 | TS-FEAS, TS-REP; `e2e_simple` funnel assertion |
| H-11 Consent explainer differs | FR-CON-01, FR-CON-06, FR-CON-08, FR-CON-09, FR-CON-10, FR-AUD-01f | — | TS-CON; OQ-06a |
| H-12 Chat gives advice or acts | FR-CHAT-01, FR-CHAT-03, FR-CHAT-05, FR-CHAT-06 | SC-65 | TS-CHAT |
| H-13 Prompt injection | FR-SEC-08, FR-SEC-10, FR-MOD-05, FR-MOD-09 | SC-61, SC-67 | TS-SEC (injection suite), TS-MOD |
| H-14 Linkage error (L) | FR-DEID-12, FR-DEID-13, FR-DEID-14, FR-FED-04, FR-FED-10 | SC-52, SC-53 | TS-FED |
| H-15 Pre-consent procedure prompted | FR-SCR-12 | — | TS-SCR (wording by consent state); OQ-14 |
| H-16 Workload rises | NFR-USAB-08, NFR-USAB-10, FR-NOTIF-08, FR-NOTIF-09, FR-SCR-10c | — | TS-USAB, TS-NOTIF; pilot E11 (H) |
| H-17 Wrong REDCap link | FR-STUDY-08, FR-RC-15, FR-RC-16 | SC-47 | TS-RC (simulator, two projects), TS-STUDY; OQ-11 |

### H-01 Missed eligible patient (false negative)

| Item | Content |
| --- | --- |
| Harm | An eligible patient is not offered a study (S3 for the patient's opportunity); a study under-enrols (S2). |
| Causes | C1 site mapping error (a lab or diagnosis code not mapped); C2 structured filter wrong (unit, window, code set); C3 note search misses the passage; C4 model judges wrongly (Japanese recall is the weakest measured number: 69 % JA vs 84 % EN on MedTxt findings); C5 missing or stale data (e.g. MMSE older than the window); C6 consent/opt-out registry wrong; C7 ruleset compiled from the wrong protocol version (MU-08); C8 ingest failed silently. |
| Initial risk | S3 × P4 = **U** |
| Controls | (a) Filter-first: structured criteria decided by rules, not models (FR-SCR-*, FR-MOD-*). (b) A single model never excludes on notes; exclusion on a note needs two models to agree (D-97, SC-63). (c) Missing data shown as a task, not an exclusion (FR-SCR-*, FR-UI-*). (d) Site mapping verified field by field at SAT (TB-DS-15 OQ-03, ≥ 99 % fields). (e) Ingest validation report, snapshot rejected above 0.5 % errors (SC-32). (f) Model gate sets before each release: SIGIR ≤ baseline + 1 and never above 8/79; TREC projected loss ≤ 5 % (TB-DS-00 N-11, N-12). (g) Ruleset pinned to protocol version and approved on **one page with one Approve** by the study's `investigator` (FR-FEAS-12, FR-AUTH-13; TB-DS-00 BD-13; superseded the two sign-offs of v0.2, TB-REV-006f F6-07): each criterion in plain language with its protocol quote, threshold, window and absence semantics, codes folded per row; a coordinator may pre-tick the code rows, recorded as a separate audit event; each amber row must be opened once; the engine refuses unapproved or unsigned rulesets (SC-40). The built code still lets `admin` and `coordinator` approve; FR-AUTH-13 changes that in build step 2. (h) Two-phase pilot (TB-DS-04 §8.2): in Phase 1 manual screening continues in parallel and lists are additive only; Phase 2 (TrialBox-first) starts only after the week-6 checkpoint reaches conditional pass and the committee approves it, keeps a 20 % random manual spot-check per study, and a spot-check miss that takes the running pooled estimate below 85 % returns the study to Phase 1. (i) Pilot recall measured by blinded 100-patient chart review per study (TB-DS-00 N-16). (j) Health page alerts on failed ingest (SC-75). |
| Verification | Gate sets G1–G3 in CI and on the real 5090 in build step 5 (TB-DS-04 §4; the only hardware run so far, 6 Nov 2026, was an RTX PRO 6000 capped to 5090 limits); SAT OQ-03/OQ-05 (TB-DS-15); pilot endpoint E1 (TB-DS-04 §8). |
| Residual risk | Phase 1: S3 × P3 = **R**, justified: manual screening continues, so TrialBox can only add candidates. **Phase 2: S3 × P3 = R**, held there by the entry condition, the 20 % spot-check and the fall-back rule; Phase 2 is the point at which H-01 can cause harm that manual screening would not have prevented, so the committee's explicit approval is required. Re-evaluate after the week-6 checkpoint and the pilot recall result. |

### H-02 Wrong exclusion shown to staff as "not suitable"

| Item | Content |
| --- | --- |
| Harm | Staff stop considering a patient who is eligible (S3). |
| Causes | Negated exclusion read as positive ("no history of stroke"); suspected diagnosis treated as confirmed (「〜の疑い」); insurance-only diagnosis (保険病名) treated as a real condition; "other X" confused with the index condition; old resolved condition treated as current. |
| Initial risk | S3 × P4 = **U** |
| Controls | (a) Judge v4 prompt with suspected/resolved paragraph (D-96). (b) Negated-exclusion rewrite at compile time (D-98). (c) 疑い flag and 保険病名 rule: never exclude on a diagnosis code alone (FR-JP-*). (d) Two-model agreement before any note exclusion (SC-63). (e) Primary action on a not-suitable verdict is "Send to PI", never "Exclude" (FR-UI-*). (f) Verbatim quote shown with every verdict (SC-62). (g) No numeric score, probability or model name is shown to `investigator` or `coordinator` (provenance "from records" / "from note" only), so patients are not ranked by model confidence (TB-REV-006c C-11; built `patient.html` changed in TB-PLAN-01 WP-17). (h) One mark vocabulary (Approach / Need info / Not suitable) whose labels never read as an eligibility decision in any language (e.g. not 「対象外」; TB-DS-09 §6, native review TB-DS-15 OQ-14). |
| Verification | TREC hand audit categories (negation, other-X) in the gate; JP convention tests (TB-DS-15 OQ-04); UI inspection of action labels; browser-walk assertion of no score or model name for clinical roles (TB-DS-04 §3.5); formative usability misreading count (TB-DS-04 §3.7). |
| Residual risk | S3 × P2 = **A** |

### H-03 Ineligible patient listed and enrolled (false positive leading to enrolment)

| Item | Content |
| --- | --- |
| Harm | An ineligible patient is exposed to an investigational product (S4). |
| Causes | MU-01; a high-tier listing based on a stale or wrong value. |
| Initial risk | S4 × P2 = **R** |
| Controls | (a) TrialBox never decides eligibility; the intended-use statement is shown on every list and report (FR-UI-*, TB-DS-16 §2). (b) Every listed criterion links to its source and date. (c) Eligibility is confirmed by the investigator under the study protocol (GCP), outside TrialBox. (d) User training covers MU-01 (TB-DS-03 SC-05). |
| Verification | UI inspection; training records; pilot safety log (TB-DS-04 §8.8). |
| Residual risk | S4 × P1 = **A**. The protocol's own eligibility confirmation is the main barrier, and it is independent of TrialBox. |

### H-04 PHI leak

| Item | Content |
| --- | --- |
| Harm | Identifying information leaves the identified zone or the hospital (S3 for a few patients; S4 for many). |
| Causes | Free-text PHI pass misses a name, chart number or address in a note; list or screenshot forwarded (MU-05); e-mail with identifiers; diagnostics bundle contains PHI; consortium message contains identifiers; misconfigured egress; prompt injection makes a model echo identifiers into an output. |
| Initial risk | S4 × P3 = **U** |
| Controls | (a) Pseudonymisation at ingest, identity only in the AES-GCM pid map (SC-30, SC-22). (b) Free-text PHI pass with measured leak rate: ≤ 0.5 % of identifier spans and zero leaked direct identifiers in the test set (TB-DS-00 N-07, SC-31, SC-60). (c) E-mail carries pseudonyms only (TB-DS-00 BD-04, SC-45, SC-46). (d) Small cells suppressed, k = 10 leaving a site (TB-DS-00 N-01, SC-50). (e) Output classifier blocks outbound files containing pids, chart numbers or names (SC-51). (f) Diagnostics bundle allowlist and PHI scan, reviewed by hospital IT (SC-43). (g) No inbound access; egress allowlist (TB-DS-02 §7). (h) Model runtime without egress or tools (SC-64). (i) Only aggregates cross the border (TB-DS-00 BD-06). (j) Watermarked reveal views and training (SC-16, SC-05). |
| Verification | PHI gate G5 (TB-DS-04); SAT PQ PHI review of 50 scrubbed notes (TB-DS-15); pentest (SC-95); egress test at SAT. |
| Residual risk | S3 × P2 = **A** for system causes; MU-05 (a person forwarding a screenshot) remains **R** and is managed by training, watermarking and hospital policy. |

### H-05 Wrong pre-filled value saved to a study record (L)

| Item | Content |
| --- | --- |
| Harm | A wrong value enters the study database and analysis (S3). |
| Causes | Model extracts a value from the wrong date or wrong patient context; unit conversion error; nearest-visit rule picks the wrong value; MU-03 "accept all". |
| Initial risk | S3 × P4 = **U** |
| Controls | (a) Every value shows quote, source and date; the user accepts each value (FR-EDC-*). (b) Rule-filled structured fields with deterministic validators (range, code, window). (c) Form stays "Unverified" (REDCap form status 1) until a person saves it; never set to Complete by TrialBox. (d) Field demotion to manual when edits + rejects exceed 20 % over the last 30 proposals (TB-DS-00 N-10). (e) "Accept all" limited to rule-filled fields with quotes, never narrative fields. (f) Writes only under the user's own REDCap session through the External Module (TB-DS-00 BD-05). (g) Accuracy gate: ≥ 95 % structured, ≥ 90 % narrative accepted unedited (N-09). (h) Source data verification by monitors as usual. |
| Verification | Pre-fill gate G4 (TB-DS-04); contract tests on the REDCap simulator; usability test of the card flow. |
| Residual risk | S3 × P2 = **A** |

### H-06 Missed adverse-event suggestion relied on (L)

| Item | Content |
| --- | --- |
| Harm | A serious adverse event is reported late or not at all (S4). |
| Causes | MU-04; model misses an AE in notes; lab-based grading uses a different CTCAE version; suggestion dismissed by a coordinator. |
| Initial risk | S4 × P3 = **U** |
| Controls | (a) AE suggestions are an extra aid; the intended-use label states that the site's usual AE process stays in force. (b) Suggestions become investigator tasks; only the investigator dismisses one, with a reason (TB-DS-00 BD-08). (c) The model only adds suggestions; it never closes one. (d) CTCAE version fixed per study (TB-DS-00 BD-12). (e) Training. |
| Verification | AE suggestion tests on synthetic charts; inspection of the dismissal permission; pilot safety log. |
| Residual risk | S4 × P1 = **A**, because the AE process does not depend on TrialBox. |

### H-07 Wrong reveal (chart number shown to the wrong person, or for the wrong patient)

| Item | Content |
| --- | --- |
| Harm | Identity disclosed to someone without a need to know (S3); the wrong patient contacted (S3). |
| Causes | Role or study scope misconfigured; pid map mix-up after an MPI merge; a coordinator reveals the wrong row; shared account; identified lists produced for a study whose ethics approval of identified screening is pending or expired (TB-REV-006c C-19). |
| Initial risk | S3 × P3 = **R** |
| Controls | (a) Deny-by-default roles and study scopes (SC-11), with CI tests of every role × route × scope (SC-14). (b) Reveal per patient, reason required, time-limited, audited (SC-16). (c) MPI aliases keep the pid stable across merges (built). (d) 2FA and named accounts (SC-10). (e) Monthly reveal report to the PI (SC-74). (f) The treating physician, or a study investigator after the treating physician has agreed, contacts the patient as the approved protocol states; TrialBox never does (answer 10, BD-19). (g) Flow-B gate for **every study type, including opt-out registries** (BD-20): a SCREEN or CASE job that resolves identities runs only when the study's ethics approval record (committee, number, date, screening covered, not expired) exists (FR-STUDY-06, entered on S21 by the coordinator and confirmed by the investigator); feasibility is not affected. |
| Verification | Authorisation matrix tests; TS-STUDY gate test (TB-DS-04 §4.6); SAT OQ roles and OQ-06 steps (TB-DS-15); audit review. |
| Residual risk | S3 × P1 = **A** |

### H-08 Model drift or silent model change

| Item | Content |
| --- | --- |
| Harm | Accuracy drops without anyone noticing (leads to H-01, H-02, H-05). |
| Causes | Different model build or quantisation installed; vLLM version change; prompt edited; data distribution shifts (new note templates, new EMR version). |
| Initial risk | S3 × P3 = **R** |
| Controls | (a) Model pins: weights, tokenizer, chat template and vLLM version hashed in the ruleset manifest (SC-42). (b) Model change is a release with all gate sets (SC-66). (c) Prompts versioned, changes go through change control (TB-DS-12). (d) Quarterly drift check against the gate sets and a small local sample (TB-DS-04 §10). (e) Per-field acceptance rates monitored (L). |
| Verification | CI gate; release record; quarterly report. |
| Residual risk | S3 × P1 = **A** |

### H-09 Downtime or data loss

| Item | Content |
| --- | --- |
| Harm | Lists and reports delayed (S2); audit or registry lost (S3). |
| Causes | GPU or disk failure; failed update; ransomware on the hospital network; power loss. |
| Initial risk | S3 × P3 = **R** |
| Controls | (a) Nightly encrypted backup with offline copy; RPO 24 h, RTO 2 working days (TB-DS-00 N-15, SC-100). (b) Quarterly restore test (SC-101). (c) Signed updates with one-click rollback (SC-41). (d) Mirrored NVMe; UPS. (e) Manual screening remains possible at all times; TrialBox is not on the clinical care path. |
| Verification | SAT OQ backup/restore and update/rollback steps (TB-DS-15). |
| Residual risk | S2 × P3 = **A** |

### H-10 Wrong feasibility numbers given to a sponsor

| Item | Content |
| --- | --- |
| Harm | A site accepts a study it cannot recruit for, or a sponsor drops a site (S2); reputational harm. |
| Causes | Mapping error; duplicate patients across sources; stale snapshot; small cells mis-suppressed; consortium double-counting (L). |
| Initial risk | S2 × P4 = **R** |
| Controls | (a) Report shows snapshot date, sources and criteria the data cannot answer (FR-FEAS-*, FR-REP-*). (b) Site PI releases every sponsor report (answer 8, SC-54). (c) SAT check of funnel plausibility by the PI (TB-DS-15). (d) Pilot endpoint E4: counts reproduced by an independent SQL query (TB-DS-04). (e) GUID de-duplication across sites (L). |
| Verification | E4; SAT. |
| Residual risk | S2 × P2 = **A** |

### H-11 Consent explainer differs from the approved version

| Item | Content |
| --- | --- |
| Harm | A patient receives information not approved by the ethics committee or, in an industry trial, by the sponsor (S3). |
| Causes | The generated draft goes live instead of the committee-approved text; the committee asked for wording edits without an ICF amendment and the edited text is not the one shown; an ICF amendment is approved but the old explainer stays live, or a new one goes live before its approval; sponsor approval missing in an industry trial; the approval record is entered wrongly. |
| Initial risk | S3 × P3 = **R** |
| Controls | Process per TB-DS-00 BD-15 (TB-REV-006c C-05). (a) The live explainer **is** the committee-approved file stored in the approval record (stamped PDF or its text), not the generated draft; its content hash is stored as an automatic safeguard (FR-CON-06). (b) Committee wording edits without ICF amendment: a new approved file on the same record, no regeneration. (c) ICF amendment: the draft is regenerated for the amendment pack; the previous approved explainer stays live until the amendment's approval record is entered and confirmed (FR-CON-08). (d) Industry-sponsored studies: go-live requires "sponsor approval received" (date, person). (e) Two roles on one screen (S21): the coordinator enters the record, the investigator confirms it; both are audited. (f) Drafts are labelled "draft for ethics submission" and are never shown on the consent page. (g) There is no manual release step and no `RELEASE` command for explainers (TB-DS-08 §6). (h) A site or study can switch the explainer off (FR-CON-07). |
| Verification | TS-CON: draft never shown; edited approved file becomes live; amendment keeps the old file live until confirmed; industry study blocked without sponsor approval; a single role cannot complete the record (TB-DS-04 §4.5); SAT OQ-06 (TB-DS-15). |
| Residual risk | S3 × P1 = **A**. The remaining risk is a wrong upload confirmed by both roles, which the committee's own stamped file makes visible on inspection. |

### H-12 Chat box gives clinical advice or performs an unintended action

| Item | Content |
| --- | --- |
| Harm | A user follows text that reads like clinical advice (S3); an action runs with the wrong study (S2). |
| Causes | MU-06; free-text generation; ambiguous command parsing. |
| Initial risk | S3 × P3 = **R** |
| Controls | (a) The chat box is a command parser over a fixed command list; it never generates free clinical text (SC-65, FR-CHAT-*). (b) When it doesn't understand, it shows the tiles. (c) Every command runs with the user's own rights and shows what it will do before running a write. |
| Verification | Command parser tests in JA/zh-TW/EN; injection tests (SC-67). |
| Residual risk | S2 × P1 = **A** |

### H-13 Prompt injection through chart text

| Item | Content |
| --- | --- |
| Harm | Text inside a note changes a verdict (leads to H-01/H-02) or leaks data (H-04). |
| Causes | A note contains instructions; a pasted document contains hidden text. |
| Initial risk | S3 × P2 = **A** before controls; kept because the cause is new |
| Controls | (a) Patient text only inside a delimited data field; fixed instructions (SC-61). (b) Schema-constrained output and verbatim-quote check (SC-62). (c) Injection test suite in CI (SC-67). (d) No tools or egress for the model (SC-64). |
| Verification | SC-67 suite. |
| Residual risk | S3 × P1 = **A** |

### H-14 Cross-site record linkage error (L)

| Item | Content |
| --- | --- |
| Harm | Two different patients merged (counts too low) or one patient counted twice (counts too high) (S2); re-identification risk if encodings are attacked (S3). |
| Causes | Kana name variants; shared birth dates; weak Bloom-filter parameters; secret leaked. |
| Initial risk | S3 × P2 = **A** |
| Controls | (a) Normalised kana and birth date with tuned thresholds; linkage quality measured on synthetic data. (b) Consortium secret held by the steering committee, rotated yearly (SC-25). (c) Only counts cross the border (BD-06). |
| Verification | Linkage tests; security review of parameters. |
| Residual risk | S2 × P2 = **A** |

### H-15 Pre-consent research procedure prompted (TB-REV-006c C-15)

| Item | Content |
| --- | --- |
| Harm | A test or assessment is done for eligibility before consent, outside routine care (S2; GCP and 指針 / 人體研究法 breach for the site). |
| Causes | "Items to collect at the visit" shown for a patient who has not consented; a new CRC reads it as an instruction. |
| Initial risk | S2 × P3 = **R** |
| Controls | (a) Before consent the wording is "Would need checking after consent: MMSE (last 2026-07-01)", optionally "may be updated in routine care at the visit"; "To collect at the screening visit" only when status ≥ consented (TB-DS-09 S8, TB-DS-17 §3.2). (b) Copy rule in TB-DS-09: TrialBox never prompts a research procedure before consent; the same sentence is in TB-TMPL-01 §2. (c) Training. |
| Verification | Browser walk asserts the wording per status; formative usability counts misreadings (TB-DS-04 §3.7). |
| Residual risk | S2 × P1 = **A** |

### H-16 Clinical workload rises and staff take shortcuts or stop using the tool (TB-REV-006c C-01, C-04)

| Item | Content |
| --- | --- |
| Harm | Staff overload leads to skipped checks (e.g. marking without opening the chart) or abandonment of the pilot (S2). |
| Causes | Parallel manual screening plus TrialBox work in Phase 1; chart review falling on clinical staff; notices above budget; re-authentication too often on phones. |
| Initial risk | S2 × P4 = **R** |
| Controls | (a) Phase 1 added time stated in advance per role and agreed by the sites (TB-DS-17 §2.2); savings claimed only in Phase 2. (b) Chart review is a funded pilot-team line, not clinical time (TB-PLAN-01 §1a). (c) Phase-1 comparison produced by the pilot team by importing the CRC's existing log (TB-DS-04 §8.9). (d) Notice budget with merge (NFR-USAB-10, ICD-13). (e) Step-up re-authentication per TB-DS-00 BD-17 (TOTP only, once per session). (f) Weekly self-log during the pilot (E11) reviewed by the PI. |
| Verification | E11 and NASA-TLX (descriptive) in TB-DS-04 §8.3; pilot safety log. |
| Residual risk | S2 × P2 = **A** |

### H-17 REDCap record linked to the wrong patient (TB-REV-006c C-06, C-17)

| Item | Content |
| --- | --- |
| Harm | A patient's consent or enrolment status is shown on another patient (S2); a patient wrongly appears as already enrolled and is not approached, or is approached twice (S2). |
| Causes | Wrong field mapped on S21; screening number typed wrongly; duplicate link values; MRN merged in the EMR after linking. |
| Initial risk | S2 × P3 = **R** |
| Controls | (a) Project link with field existence check (`RC-LINK-FIELD`) and duplicate check (`RC-LINK-DUP`), never resolved automatically (TB-DS-08 §4.1a). (b) Link mode `mrn` maps through the pid map with MPI aliases. (c) Conflicts between TrialBox outcomes and REDCap statuses are listed for the coordinator. (d) Link configuration confirmed by the investigator on S21. |
| Verification | ICD-04 two-project conformance test on the simulator; SAT OQ with the site's real project (TB-DS-15). |
| Residual risk | S2 × P1 = **A** |

## 5. Summary of residual risks

| Hazard | Initial | Residual | Status |
| --- | --- | --- | --- |
| H-01 Missed eligible patient | U | R | Accepted with justification; Phase 2 only with committee approval; re-evaluate at week 6 and after the pilot |
| H-02 Wrong exclusion | U | A | |
| H-03 Ineligible patient enrolled | R | A | |
| H-04 PHI leak | U | A (system) / R (MU-05) | MU-05 accepted with training and policy |
| H-05 Wrong pre-filled value (L) | U | A | |
| H-06 Missed AE suggestion (L) | U | A | |
| H-07 Wrong reveal | R | A | |
| H-08 Model drift | R | A | |
| H-09 Downtime / data loss | R | A | |
| H-10 Wrong feasibility numbers | R | A | |
| H-11 Consent explainer differs | R | A | |
| H-12 Chat clinical advice | R | A | |
| H-13 Prompt injection | A | A | |
| H-14 Linkage error (L) | A | A | |
| H-15 Pre-consent procedure prompted | R | A | |
| H-16 Workload rise, shortcuts | R | A | Re-evaluate with E11 at week 6 and week 12 |
| H-17 Wrong REDCap link | R | A | |

No hazard remains in the U region after controls. Two items remain in R (H-01 in both pilot phases, MU-05) and are accepted on the benefit-risk statement below.

## 6. Benefit-risk statement

TrialBox's benefit is that it finds more candidate patients, faster, with less coordinator time, and gives feasibility answers in a day instead of weeks. The baseline it is compared with is manual chart screening, which itself misses eligible patients and consumes much staff time. During pilot Phase 1, TrialBox runs alongside manual screening, so it can add candidates but cannot remove any from the usual process. In Phase 2, staff start from the TrialBox list while a 20 % random manual spot-check continues; this is entered only after the week-6 checkpoint and with the committee's explicit approval. Every output is reviewed by a qualified person, and eligibility, consent and AE reporting remain under the study protocol and GCP, outside TrialBox.

The remaining risks in the R region are H-01 (missed eligible patients), which the two-phase design, the spot-check and the pilot recall measurement manage, and MU-05 (a person forwarding identified data), which no software control can remove fully. Both are judged acceptable for a research-support tool against the benefit, on the condition that the week-6 recall checkpoint reaches conditional pass before Phase 2 starts and the pilot recall result (TB-DS-00 N-16) is met before the spot-check is removed after the pilot.

## 7. Production and post-production information

| Source | What is collected | Who reviews | When |
| --- | --- | --- | --- |
| Pilot safety log | Use errors, near misses, wrong verdicts reported by staff | Aimedics engineer + site PIs | Weekly during the pilot |
| Chart review results | Every missed eligible patient with root cause | Product owner + site PIs | Week 6 and week 12 of the pilot |
| Phase-2 spot-check | Eligible patients found by the 20 % manual check that TrialBox did not list | Pilot team + site PIs | Weekly in Phase 2 |
| Workload and notices | E11 self-log, notices per role, snooze counts | Pilot team + site PIs | Weekly; week 6 and week 12 summary |
| Support tickets | Defects and complaints | Aimedics engineer | Each ticket; summary monthly |
| Pre-fill acceptance rates (L) | Per-field accept/edit/reject | Aimedics engineer | Monthly |
| Model drift check | Gate set results on the installed build | Aimedics engineer | Quarterly |
| Security events | Incidents, pentest findings, CVEs | Security owner | As they occur; quarterly summary |

A new hazard, a control that failed, or a residual risk that rose triggers an update of this file and a review by the approvers before the next release.

## 8. Review schedule

This file is reviewed before each release (as part of the release record, TB-DS-12 §7), after the pilot report, and at least every 6 months.

## 9. References

- ISO 14971:2019 Medical devices — Application of risk management to medical devices (structure only; TrialBox is not a device, TB-DS-16).
- ISO/TR 24971:2020 Guidance on the application of ISO 14971.
- ICH E6(R3) Good Clinical Practice (2025), risk-based approach to computerised systems.
- IEC 81001-5-1:2021 Health software security — activities in the product life cycle.
- ISO/IEC 27001:2022 §6.1 (information-security risk; TB-DS-03).
- Shared terms: TB-DS-01 Appendix C.

## Change history

| Seq | Version | Date | Author | Change |
| --- | --- | --- | --- | --- |
| 1 | 0.1 | 2026-11-07 | Claude for Aimedics | First draft, from TB-REV-006 finding M-04. |
| 2 | 0.1a | 2026-11-07 | Claude for Aimedics | TB-REV-006b R2-02: H-01 control (g) cites AM-01 / FR-AUTH-13 / BD-13. |
| 3 | 0.2 | 2026-11-07 | Claude for Aimedics | TB-REV-006c: H-01 (g) two sign-offs (C-09), (h) two-phase pilot with spot-check and fall-back, residual per phase (C-01); H-02 (g) no scores or model names for clinical roles (C-11), (h) mark labels (C-28); H-07 flow-B ethics gate (C-19); H-11 rewritten to BD-15: approved-file record, committee-edit path, sponsor approval, two roles, no RELEASE (C-05); new H-15 pre-consent procedure (C-15), H-16 workload rise (C-01, C-04, C-21), H-17 wrong REDCap link (C-06, C-17); benefit-risk and post-production updated. |
| 4 | 0.3 | 2026-11-07 | Claude for Aimedics | TB-REV-006d: scope uses the two-phase wording (D-01); H-07 (f) BD-19 who approaches (D-04), (g) gate for every study type incl. opt-out registries (D-20); H-16 comparison wording. |
| 5 | 0.4 | 2026-11-07 | Claude for Aimedics | TB-REV-006f: marked hospital stage (H). |
| 6 | 0.5 | 2026-11-07 | Claude for Aimedics | TB-REV-006g Q-04, Q-31, S-06, S-08: §1 scope in build-stage terms with the statement that no hazard is live on synthetic data; new §4.0 trace table (hazard → requirement IDs → SC controls → test suites, gates and site checks); H-01 (g) rewritten to one page, one Approve (FR-FEAS-12, BD-13); (M2) → (L); §9 references; sequence column. |
| 7 | 0.6 | 2026-11-07 | Claude for Aimedics | TB-REV-006g §R: §4.0 trace cites TB-DS-01 v0.10; H-01 verification notes the only hardware run so far (TB-REV-006f L8-01). |
| 8 | 0.7 | 2026-11-07 | Claude for Aimedics | TB-REV-006g §F F-02: §4.0 cites TB-DS-01 "version per TB-DS-00R". |
