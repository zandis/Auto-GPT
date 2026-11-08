# TB-DS-01 TrialBox — Software Requirements Specification

| Field | Value |
| --- | --- |
| Document ID | TB-DS-01 |
| Title | TrialBox Software Requirements Specification (SRS) |
| Structure | ISO/IEC/IEEE 29148:2018, clause 9.5 (SRS content) |
| Version | 0.12 (reference; frozen for the build stage) |
| Date | 2026-11-07 |
| Owner | Aimedics; product owner Changfu Kuo |
| Author | Claude (TrialBox project, design thread) |
| Status | Reference. Frozen for the build stage (TB-REV-006f §4.4). The living page is `20-build-map.md`; build decisions go into the code's `docs/DECISIONS.md` as D-nnn entries. |
| Baseline | TB-DS-00 v0.10 Baseline decisions and canonical numbers. Where this document and TB-DS-00 differ, TB-DS-00 wins. |
| Companion documents | TB-DS-00 Baseline; TB-DS-00R Document register; TB-DS-02 Architecture (arc42 + C4); TB-DS-03 Security, privacy and compliance; TB-DS-04 Verification, validation and operations; TB-DS-05 Open-source reuse; TB-REV-006 Review of design set v0.1 |
| Source report | "TrialBox on REDCap and FHIR", https://claude.ai/artifact/ENoJXMpqMJjqtaYWiNwXaa (v7) |
| Code baseline | Repository `zandis/Auto-GPT`, directory `trialbox/`, branch master at commit `a1e55fa` (re-checked 2026-11-07). The clinic workbench (six-step bar, PI workbench, CRC "My work") is commit `38d93ce` on branch `claude/project-thread-0iudms`, not merged; status columns refer to master. |

### Approvals

| Role | Name | Decision | Date |
| --- | --- | --- | --- |
| Prepared | Claude (for Aimedics) | Prepared | 2026-11-07 |
| Reviewed | Independent design reviews TB-REV-006 to TB-REV-006g | Findings applied up to v0.11 (006g §R pass 2 and 006f §8 model fold-in) | 2026-11-07 |
| Approved | Changfu Kuo, product owner | Pending | — |
| Acknowledged | Site IT / information-security contact, Japan head hospital | Pending | — |
| Acknowledged | Site IT / information-security contact, CGMH | Pending | — |

---

## 1. Introduction

### 1.1 Purpose

This document states what TrialBox shall do and how well. It covers the **build stage** (five steps on synthetic and public data, `SIMPLE-PLAN.md`, `20-build-map.md`) and, tagged H, the **hospital stage** that starts only when a hospital chooses to use real patient data; the intended first hospitals are a Japanese head hospital and Chang Gung Memorial Hospital (CGMH, Taiwan), with hospital-stage dates in TB-DS-00 §2.H. It is the requirement reference for TB-DS-02 (design), TB-DS-03 (security controls SC-nn) and TB-DS-04 (verification). Every requirement has a unique, stable ID that those documents cite.

Readers: the product owner, the TrialBox engineer, hospital IT and information-security staff, hospital ethics offices, the consortium steering committee, and reviewers.

### 1.2 Scope

TrialBox is an on-premises research appliance installed inside a hospital. It:

1. reads the hospital's EMR and registry data, pseudonymises it, and converts it to FHIR R4;
2. turns trial eligibility criteria into deterministic filters plus narrow, schema-bound language-model checks on clinical notes ("filter-first");
3. produces a complete feasibility report from a set of criteria (flow A, before ethics approval, on pseudonymised data);
4. produces a patient list for an approved study (flow B, inside the hospital) with links to the EMR and to REDCap;
5. supports pre-screening and consent preparation, and later (L) eCRF pre-fill and trial-conduct suggestions, always with a person confirming each value;
6. reads from the hospital's REDCap (S3), writes into it later through an External Module (L), and can later offer its own forms (EDC-lite, L);
7. later (L) coordinates feasibility and duplicate detection across hospitals of one country without moving patient-level data.

TrialBox does not diagnose, treat, or decide eligibility. A person makes every decision.

**Build stage.** TrialBox is built and tested on synthetic and public data in five steps (`SIMPLE-PLAN.md`, `20-build-map.md`). Nothing below is a gate for that build. **Hospital stage (H):** only when a hospital chooses to use real patient data, the pilot runs in two phases (TB-DS-00 BD-16): **Phase 1** (weeks 1–6) is parallel and additive: staff screen as usual and TrialBox lists may only add candidates, approached after the PI has confirmed suitability from the chart; **Phase 2** (weeks 7–12) is TrialBox-first with a 20 % manual spot-check per study, entered only after the week-6 recall checkpoint and the ethics committee's approval. What is installed at go-live and what follows before week 7 is listed in TB-DS-00 §2 "M1 content by date".

### 1.3 Product perspective and built inventory

TrialBox extends the existing appliance at master `a1e55fa`. What exists today, checked against the code:

| Area | Built today | Evidence |
| --- | --- | --- |
| Jobs | E-mail and console driven FEAS, REVIEW/APPROVE, SCREEN (v4 cascade), CASE, COHORT, NAV, MICROBATCH (Monday 03:00), CONSENT | SPEC.md §5, §8.2; D-91, D-103 |
| Ingest | HIS CSV/SQL adapter with per-site mapping YAML, to pseudonymised FHIR R4 NDJSON (HMAC pid, AES-GCM pid map); nightly ingest 02:00 | SPEC.md §3.1, §5; D-84 |
| Stores | HAPI FHIR with CQL `$evaluate`; DuckDB lake per snapshot with note chunks and bge-m3 embeddings; object store; snapshot retention 3 nightly + 36 month-ends | D-78, D-105 |
| Console accounts | Roles `admin`, `coordinator`, `investigator`, `viewer`, `cro`; affiliations `hospital`, `smo`, `cro`; study scopes; account expiry; scrypt passwords ≥ 12 characters; lockout 5 failures → 15 min; sessions 30 min idle, 8 h absolute; CSRF per session; trusted-header SSO from allowlisted proxies; `/ops/users` | `services/console/auth.py`; D-93, D-101, D-104 |
| Console pages | Report-first pages per role: `/home`, `/studies/{rs}/feasibility`, `/studies/{rs}/week` (weekly list), `/studies/{rs}/patients/{pid}` with investigator marks (approach / not suitable / need info) and audited chart-number reveal; pilot workspace (`/pilot/*`: request, protocol, case, cascade, registry with XLSX export, consent, mailbox, sponsor-pack release) | D-104; console routes |
| Not built | No 2FA; no `auditor` role; no coordinator task inbox, recruitment pipeline view or six-step bar; no header command field; no REDCap connector; no free-text PHI pass; no consortium hub | code search at `a1e55fa` |
| Models | Local vLLM serving of judge and verifier; profiles for DGX Spark, RTX 5090 and RTX 4090; two-model agreement before note exclusion | D-89, D-95, D-97 |
| Integrity | Append-only hash-chained audit log (`tools/audit_verify.py` on demand); signed offline update bundles; nftables egress control; small-cell suppression with default k = 5 (`libs/tb_common/smallcell.py`) | SPEC.md §10; D-78 |
| Retention | Daily retention job: attachments 90 d, outputs 365 d; audit chain never touched (10 years) | `services/orchestrator/scenarios/retention.py` |
| Disk keys | TPM / `systemd-creds` sealing of `site_hmac.key` and `pid_map.key` is **documented as an operator procedure, not enforced by the installer** | `docs/HARDENING.md` §1–2 |
| Tests | About 669 test functions; 239 `@pytest.mark.req` markers, citing 136 distinct spec-v4 IDs (Appendix D) | test tree at `a1e55fa` |

The target system adds: the REDCap read connector and simulator (S3), console-native TOTP 2FA and the `auditor` role (H), the free-text PHI pass (S1 rules + NER; LLM tagger H), the role work list with a header command field (S4), and later REDCap writes through an External Module, EDC pre-fill, trial-conduct suggestions, the consortium hub with cross-site GUID, and an evaluation of Medplum (TB-DS-00 §2, BD-01); EDC-lite is L. The **clinical layer** (S2, S4; parts H) adds role homes and the clinic-day list and CRC digest (FR-UI-14..19, FR-NOTIF), study set-up and the screening log with the REDCap record link (FR-STUDY, FR-RC-16), and monitoring and annual-report views (FR-REP-06, FR-REP-09); TB-DS-00 §2.H says which of these a hospital install has at go-live; `20-build-map.md` says in which build step each is built.

```
 Hospital EMR / HIS / registries ──► TrialBox appliance ◄──► Hospital REDCap
   (SS-MIX2, vendor export,          (ingest, FHIR store,       S3: API read
    CGMH self-developed HIS)          lake, engine, models,      L:  External Module
                                      UI, mail, audit)               writes
                                         │  L:  signed aggregates + GUID filters only,
                                         ▼      within one country (BD-06)
                                   Country hub (another TrialBox)
```

### 1.4 Definitions, acronyms and abbreviations

The glossary is Appendix C (one glossary for the whole design set, with Japanese and Traditional Chinese terms).

### 1.5 References

Standards and regulations (versions per TB-DS-00 BD-12):

| Ref | Document |
| --- | --- |
| [S1] | ISO/IEC/IEEE 29148:2018 Requirements engineering |
| [S2] | HL7 FHIR R4 (4.0.1); JP Core IG 1.2.0; TW Core IG as pinned in the repository; IPA IG |
| [S3] | HL7 FHIR to OMOP IG, STU 1 (targets OMOP CDM v5.4) |
| [S4] | OHDSI OMOP Common Data Model v5.4 |
| [S5] | SS-MIX2 標準化ストレージ仕様書 (JAHIS / MEDIS-DC) |
| [S6] | ISO 25237:2017 Health informatics — Pseudonymization |
| [S7] | ISO/IEC 20889:2018 Privacy enhancing data de-identification techniques |
| [S8] | US HIPAA Privacy Rule, Safe Harbor (45 CFR 164.514(b)(2)) — global checklist only |
| [S9] | ISO/IEC 27001:2022, ISO/IEC 27002:2022, ISO/IEC 27701:2019 |
| [S10] | ICH E6(R3) Good Clinical Practice (2025); J-GCP (医薬品の臨床試験の実施の基準に関する省令) |
| [S11] | Japan APPI (個人情報の保護に関する法律), incl. Chapter 4 (private business operators; Art. 41 仮名加工情報) and Chapter 5 (administrative organs and incorporated administrative agencies, which covers national-university, national and public hospitals); 人を対象とする生命科学・医学系研究に関する倫理指針 (2023) |
| [S12] | MHLW 医療情報システムの安全管理に関するガイドライン **第7.0版** (2FA expected for systems in operation in 令和9年度, i.e. from April 2027) |
| [S13] | Taiwan Personal Data Protection Act (個人資料保護法), Art. 6 (sensitive data incl. medical records); Human Subjects Research Act (人體研究法); Cyber Security Management Act (資通安全管理法) |
| [S14] | WCAG 2.2 level AA |
| [S15] | OWASP ASVS **5.0** |
| [S16] | REDCap API and External Module framework documentation (public) |
| [S17] | CTCAE v5.0 (v6.0 when released and adopted by the sites) |

Project documents:

| Ref | Document |
| --- | --- |
| [P1] | trialbox/SPEC.md (v1.0) |
| [P2] | trialbox/docs/ARCHITECTURE.md |
| [P3] | trialbox/docs/DECISIONS.md (entries D-01..D-105; there is no D-99 entry, see note below) |
| [P4] | trialbox/docs/INTEGRATION_SCENARIOS.md |
| [P5] | Target architecture report v7 (artifact ENoJXMpqMJjqtaYWiNwXaa) |
| [P6] | Measurement records: PR #14 (consumer GPU, filter-first), PR #15 (public-data validation), PR #19 (50,000-patient run), PR #21 (capped RTX PRO 6000 as 5090 proxy) |
| [P7] | trialbox/docs/HARDENING.md |
| [P8] | trialbox/spec/v4/ (spec-v4 requirement IDs used by the test markers, Appendix D) |
| [O1] | Owner decision 2026-10-25: TrialBox stays outside the regulated e-signature path (recorded in the project thread of that date) |
| [O2] | Owner decision 2026-10-26: no second person for the consent guide (TB-DS-00 BD-07); superseded 2026-11-07 by BD-15 (TB-DS-00 v0.5 onward): the committee-approved explainer file goes live automatically once the approval record is complete |
| [O3] | Owner statement 2026-11-05: filter-first; models only where filters cannot decide (recorded in D-95) |
| [O4] | Owner answers A1–A44 and preference statements P-HW, P-ENTRY, 2026-11-07 (Appendix A) |

Note on decision IDs. Decisions are cited by their entry in [P3]. "D-99" appears only in the message of commit `e211bad` (coordinator screen, audited reveal, subject style); it has no entry in DECISIONS.md, so this document cites the entries that do record that behaviour: D-93 (coordinator role), D-101 (approval record, investigator role), D-104 (role pages, investigator reveal), D-88 (outcome-first subjects). D-105 is the lake rebuild (embeddings as float32), not a user-interface decision.

### 1.6 Document conventions

- "shall" = mandatory; "should" = recommended; "may" = permitted.
- **Priority** (re-tagged 2026-11-07, TB-REV-006f F6-01; the build map `20-build-map.md` is the source): **S1–S5** = built in that step of the simple build plan; **S0** = built today and kept working (regression tests only); **H** = only when a hospital uses real patient data (hospital stage); **L** = later. Each cell keeps the earlier tag as "(was M1)", "(was M2)", "(was C)" or "(was SC-nn)"; nothing is deleted. The M1/M2/C scheme and the pilot dates now apply only inside the hospital-stage documents (TB-PLAN-01, TB-DS-15, TB-TMPL-01).
- **Verification**: **T** Test, **I** Inspection, **A** Analysis, **D** Demonstration.
- **Status** against master `a1e55fa`: **B** Built (behaviour present and tested), **P** Partly built (named part present), **N** New, **W** Withdrawn.
- **Numbers**: every threshold that TB-DS-00 §4 fixes is written with its value and the citation "(N-nn)". A number without an N-nn citation is local to this document.
- **Source codes**: A1–A44, P-HW, P-ENTRY = owner answers [O4] (Appendix A); D-nn = decision log [P3]; BD-nn, N-nn = TB-DS-00; SC-nn = TB-DS-03 control; F-nn = TB-REV-006 finding.
- IDs are stable. A removed requirement keeps its ID with status **W**, Pri "—" (the earlier tag kept as "(was …)") and its pointer in the Requirement cell. A split requirement keeps its root ID with letter suffixes (FR-FEAS-04a…); a row split in v0.10 or later carries "(split from <root>)" in Pri. Build status, schedule and examples go in the Notes column, never in the Requirement text.

---

## 2. Overall description

### 2.1 Stakeholders and user classes

Roles are the code names (BD-03). Display labels are for people; access is decided by the role.

| User class (display label) | Role | Main goals | Highest data class (BD-02) | Interfaces |
| --- | --- | --- | --- | --- |
| Principal investigator (PI) | `investigator` | Feasibility before a study; weekly patient list; mark suitability; approve sponsor release and cross-site queries (A36, A41); dismiss AE suggestions (BD-08) | D4 after audited reveal, study scope only | Role work list, study pages, e-mail, REDCap panel (L) |
| Sub-investigator | `investigator` | Review candidates; contact patients (A38) | D4 after audited reveal, study scope only | Study pages, e-mail |
| CRC / study nurse | `coordinator` | Pre-screen, prepare consent; after the pilot fill eCRFs and manage visits | D4 after audited reveal, study scope only | Role work list, pilot workspace, e-mail, REDCap panel (L) |
| SMO specialist | `coordinator` with affiliation `smo`, study scope and expiry | Support site feasibility and tracking | D4 after audited reveal, study scope only, until expiry | Role work list |
| Research office (治験事務局 / 臨床研究支援センター; CGMH 臨床試驗中心) | `coordinator` with all-study scope and the `office` scope flag (FR-STUDY-10) | Onboard each study on S21 with the study team; request accounts; annual progress report to the committee (FR-REP-09); monitoring-visit logistics | D3 (pseudonymised logs); D4 only if also on a study team | Role work list, S21, reports |
| Treating physician who is not a study investigator | — (no account needed) | Agrees before a study is introduced to their patient (主治医の了承; attending agreement at CGMH) | — | Asked by the coordinator (FR-SCR-07b task) |
| CRO specialist | `cro` (off by default, BD-03, F-54) | Aggregate feasibility | D1 (aggregates, small cells suppressed) | Role work list, aggregate views |
| Read-only staff | `viewer` | Read aggregate reports of scoped studies | D1 (internal form, k = 5 per N-01) | Role work list, reports |
| Auditor / monitor (new, H) | `auditor` | Read and export audit records; read screening logs | D3 (audit records hold pseudonyms only) | Audit pages |
| Site admin / hospital IT | `admin` | Install, update, users, monitoring, support bundles | D1 for operations; clinical views only through a study scope | Admin pages, CLI |
| Consortium steering committee (L) | — (no account on a site box) | Governance of the country hub; data-use agreement | D1 | Hub reports |
| Sponsor | — (never an account) | Receives site-released aggregate reports only (A36, A37) | D1 | Released files |
| Patient | — | Contacted only by the treating doctor (A38); reads consent materials | — | Printed or REDCap e-Consent material |
| TrialBox engineer | — (no site account by default) | Build, release, support (A32) | D0 / D1 (diagnostics bundles after PHI scan) | CI, release pipeline |

### 2.2 Product functions (summary)

| # | Function | Groups | Release (build step per `20-build-map.md`) |
| --- | --- | --- | --- |
| 1 | Nightly ingest, mapping, pseudonymisation, PHI pass, FHIR conversion | ING, DEID | S1 (PHI tagger H) (was M1) |
| 2 | Criteria compilation from text, protocol file or e-mail | FEAS | S1 (was M1) |
| 3 | Feasibility report with funnel (flow A) | FEAS, REP | S1 (was M1) |
| 4 | Patient list for an approved study (flow B) | SCR, UI | S2 (was M1) |
| 5 | Single-patient check | CASE | S0 (was M1) |
| 6 | Consent explainer | CON | S0 (approved-file process H) (was M1) |
| 7 | REDCap read connector and simulator | RC | S3 (was M1) |
| 8 | Accounts, roles, 2FA, audit, security controls | AUTH, AUD, SEC | S0 (2FA, audit browser, security controls H) (was M1) |
| 9 | Header command field; e-mail in / out | UI, CHAT, MAIL | S4 (header command field); e-mail S0/S2 (was M1) |
| 10 | Local models, GPU time-sharing, model gates | MOD | S0; time-sharing and 32 GB fit S5 (was M1) |
| 11 | Japanese and Taiwanese conventions; languages | JP, I18N | S4 (was M1) |
| 12 | Installation, update, monitoring, backup, support | OPS, LOG, ERR | S4 (health, jobs, data sources); install, update, backup H (was M1) |
| 13 | eCRF pre-fill with cards; REDCap writes via External Module | EDC, RC | L (was M2) |
| 14 | Trial-conduct suggestions | TC | L (was M2) |
| 15 | EDC-lite forms | EDCL | L (was C) |
| 16 | Country hub, cross-site GUID | FED, DEID | L (was M2) |
| 17 | OMOP export | OMOP | L (was C) |
| 18 | Role homes, notices and lists | UI, NOTIF | S2 (lists, N1/N2 mail); S4 (role homes) (was M1) |
| 19 | Study set-up, screening log, registry support, monitoring views | STUDY, REP | S3 (study set-up, three sections); S2 (screening log, registry cohort list); reconciliation L (was M1 (registry reconciliation M2)) |

### 2.3 Operating environment

| Item | Japan head hospital | CGMH (Taiwan) |
| --- | --- | --- |
| EMR | SSI or Fujitsu (HOPE) EMR, SS-MIX2 storage where installed (A5) | Self-developed EMR / HIS (A27); CGRD research database |
| REDCap | Present (A3) | Present (A3) |
| Patients (design point) | 500,000 (N-18) | 500,000 (N-18) |
| Concurrent studies | 20 (N-18) | 50 (N-18) |
| Peak concurrent users | 10 (N-18) | 10 (N-18) |
| Hardware (BD-10, estimates until measured) | 1 × RTX 5090 32 GB, 256 GB RAM, 8 TB mirrored NVMe (≈ US$8–10k) | 2 × RTX 5090, 256–384 GB RAM, 16 TB mirrored NVMe (≈ US$13–16k) |
| Night schedule (BD-11) | 22:00–23:30 ingest; 23:30–02:00 PHI pass; 02:00–05:30 screening (judge, then verifier); 05:30–06:00 reports and mail; weekend window Saturday 22:00–Monday 06:00 | same |
| OS / runtime | Ubuntu LTS, Docker Compose, NVIDIA driver, vLLM | same |
| Network | Hospital internal network only; no inbound internet; egress allowlist only | same |
| Languages | Japanese by default | Traditional Chinese by default |
| Users' devices | Hospital desktop browsers (current Chromium / Edge); PI list readable on a phone | same |

### 2.4 Design and implementation constraints

| ID | Constraint | Source |
| --- | --- | --- |
| CON-01 | All patient-level processing shall occur on the appliance inside the hospital. No patient-level data leaves the hospital. | A11, A37, [P1] §10 |
| CON-02 | TrialBox shall remain a research support tool and not a medical device: it shall not diagnose, recommend treatment, or decide eligibility. | A33, D-89 |
| CON-03 | Aimedics cannot hold a REDCap licence, receive REDCap source code, host REDCap, or use the REDCap name for its product. TrialBox shall integrate only through REDCap's public API and External Module framework on the hospital's licensed instance. | REDCap licence terms, A16 |
| CON-04 | Filter-first: structured criteria shall be decided by deterministic SQL/CQL; models shall be used only for criteria that require reading notes. | [O3], D-95 |
| CON-05 | A single model shall never exclude a patient on a note-based criterion; exclusion on notes requires agreement of two independent models, otherwise the patient goes to human review. | D-89, D-97 |
| CON-06 | Identified recruitment lists shall be produced only in the identified zone inside the hospital; pseudonymised data (仮名加工情報) shall not be used to contact patients. | [S11], [P4] |
| CON-07 | TrialBox shall stay outside the regulated e-signature path (no 21 CFR Part 11 / ER/ES signatures); regulated trial data stays in REDCap or the sponsor's EDC. | [O1], A16 option D |
| CON-08 | Local models only for any data above D1. A cloud model may be used only for D0 text, and only in development (`may_reach`). | [P1] §7.4, BD-02 |
| CON-09 | No vendor remote access by default. Updates are signed bundles installed by hospital IT. | A23 |
| CON-10 | Free of charge in the academic phase; no licence-enforcement code that blocks clinical use. | A29, A30 |
| CON-11 | One engineer maintains the product; the design shall minimise moving parts. | A32 |
| CON-12 | Default model builds (design choice, not a requirement): judge Gemma 4 26B-A4B (`nvidia/Gemma-4-26B-A4B-NVFP4`, Apache 2.0), verifier Qwen3.5-9B (`cyankiwi/Qwen3.5-9B-AWQ-4bit`, AWQ 4-bit, thinking off, Apache 2.0), both must agree to exclude (FR-SCR-05); chat command parsing helper and lead PHI-tagger candidate = the judge model (LLM survey 2026-11-07); embeddings bge-m3. Kept after a survey of 15 newer open models (report `trialbox-llm-survey/2026-11-07-open-llm-survey.md`, PR #23). Changing them is a model change under FR-MOD-06. | D-95, F-29 |
| CON-13 | Default PHI detectors (design choice): regex rules + Japanese/Chinese NER model + LLM tagger (lead candidate Gemma 4 26B-A4B behind the regex guard; MedPHINER and OpenMed as bake-off comparators), union of hits. The requirement is the measured result (NFR-PERF-14), not the detector set. | F-29 |
| CON-14 | The data classes D0–D4 of the code (`tb_contracts.dataclass`, `tb_common.policy.classes.may_reach`) are the only classification: D0 public, D1 confidential without PHI (incl. suppressed aggregates), D2 de-identified, D3 pseudonymised, D4 identified. Network zones are a separate concept. | BD-02 |
| CON-15 | Pilot identity: HAPI FHIR 8.12 stays; accounts are console-native with TOTP. Medplum is evaluated later (L) and replaces HAPI only if the spike passes; Keycloak is the fallback IdP. | BD-01 |
| CON-16 | Object store: the built filesystem object store replaces MinIO (archived upstream); tests use Mailpit instead of MailHog. | BD-09 |
| CON-17 | Model serving engine (design choice): vLLM on the appliance. Changing the engine is a model change under FR-MOD-06. | D-95 |
| CON-18 | Disk encryption mechanism (design choice): LUKS2 volumes, key sealed to TPM 2.0 via `systemd-creds` where present (FR-SEC-01..01b). | [P7] §1, SC-20 |

### 2.5 Assumptions and dependencies

| ID | Assumption / dependency | Risk if false |
| --- | --- | --- |
| AS-01 | Each pilot hospital provides a read-only data export (SS-MIX2, HIS export or warehouse view) and an IT contact. | No ingest; pilot slips. |
| AS-02 | The Japan head hospital's REDCap admin gives a project-level read token on a development instance before the pilot and on production for the pilot. | REDCap read tested only against the simulator. |
| AS-03 | Hospital stage (H) only: before a hospital uses real patient data, its ethics committee approves (a) feasibility on pseudonymised data before study approval and (b) the two-phase pilot protocol (BD-16), with Phase 2 approved separately at week 6. Nothing in the build stage depends on this. | Flow A at that hospital limited to CGRD or post-approval data; that hospital's start slips by at least one committee cycle. |
| AS-04 | The judge (Gemma 4 26B-A4B, NVFP4) and the verifier (Qwen3.5-9B, AWQ 4-bit) can be time-shared on one RTX 5090 (32 GB) within the night window (BD-11). Time-sharing is unmeasured (swap controller TD-5 not built); the only run so far (2026-11-06) had both models resident and reserved 35 GiB on an RTX PRO 6000 capped to 5090 limits, mostly vLLM pre-allocation (weights 17.1 + 7.5 GiB). Build step 5 measures the fit (FR-MOD-10). | The site needs 2 × RTX 5090 or a shorter context / smaller build (TB-DS-02 ADR-03). |
| AS-05 | Medplum passes the later (L) spike (bulk import, JP Core, OIDC, MFA, CQL path); otherwise HAPI + console accounts (+ Keycloak if SSO is wanted) stay. | Identity design stays as built. |
| AS-06 | One hub per country (BD-06). Japan: the head hospital hosts the hub; Taiwan: CGMH hosts the hub. Only aggregate counts cross the border until counsel confirms the status of Bloom-filter encodings. Year-one membership is not yet named (A24 unanswered). | Hub hardware and governance change; requirements do not. |
| AS-07 | The CGMH EMR can export patients, encounters, diagnoses, labs, prescriptions, notes and appointments with stable codes. | More mapping effort. |
| AS-08 | The build stage has no dates; each of the five steps is a pull request the owner merges or not (`SIMPLE-PLAN.md`). Hospital-stage dates, when a hospital asks to install, are in TB-DS-00 §2.H (asked: January 2027, A31). | — |
| AS-09 | Each site measures its manual pre-screen time before the pilot (baseline for N-17). | NFR-PERF-13 cannot be evaluated. |

### 2.6 Out of scope (this version)

- Diagnosis, treatment recommendations, or any automated eligibility decision (CON-02).
- Regulated e-signatures, a validated Part 11 EDC (A16 option D).
- Direct contact of patients by the system (A38).
- Patient-level data to sponsors (A37).
- Sponsor EDC connectors (Medidata Rave, Veeva) — C (A40, TB-DS-00 §2).
- LINE / Teams notices — C.
- Voice input (A28).
- Free-form conversational chat beyond the fixed command grammar (A19); the parser is replaceable later (FR-CHAT-07).
- Hosting or redistributing REDCap.
- Blockchain-based coordination.
- Pricing, billing and licence enforcement (A29, A30).
- Record-level data crossing a national border (BD-06).

### 2.7 Project obligations (not system requirements)

Activities the project owes before a hospital uses real patient data. They are not properties of the software, so they are not in §3; each keeps a pointer row there (status W). All are hospital stage (H).

| ID | Obligation | Evidence | Pointer |
| --- | --- | --- | --- |
| PO-01 | A third-party penetration test with no open critical or high findings before the first real-data use at each site. | Test report (TB-DS-03 §12) | NFR-COMP-02, FR-SEC-11 |
| PO-02 | A data protection impact assessment for each site before the first real-data use. | DPIA (TB-DS-03) | NFR-COMP-08 |
| PO-03 | A written position paper stating why TrialBox is not a medical device under PMDA (Japan) and TFDA (Taiwan) rules. | TB-DS-16 | NFR-COMP-04 |

---

## 3. Specific requirements

Each table row is one requirement. Columns: **ID**; **Requirement** (the normative text only); **SC** (FR-SEC table only: the TB-DS-03 control); **Pri**, the build tag S0–S5 / H / L defined in §1.6 and TB-DS-00 §2, with the earlier tag kept as "(was …)" and split rows marked "(split from …)"; **Source**; **Ver** (T/I/A/D); **St** (B/P/N/W against master); **Notes** (build status, schedule, context and examples; never normative). A "Fit:" sentence inside a requirement is its acceptance criterion.

§3.3 (DR) and §3.4 (IR) rows are written as specification statements; each reads "The system shall support …" followed by the row text.

### 3.1 Functional requirements

#### 3.1.1 ING — Data ingest and mapping

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-ING-01 | The system shall ingest the hospital's clinical data on a schedule and on demand by an admin, with the schedule set by FR-OPS-12. | S1 (was M1) | [P1] §5, BD-11, F-22 | T | P (02:00 built) | DEV/TEST: on demand. PRODUCTION default: BD-11 window 22:00–23:30 local. Built default is 02:00 and is changed at hospital install (H). |
| FR-ING-02 | The system shall read HIS CSV and SQL exports through a versioned per-site mapping file (YAML) that renames fields, maps values and units, and extends a base profile. | S1 (was M1) | D-84, A5 | T | B |  |
| FR-ING-03 | The system shall read SS-MIX2 standardized storage (HL7 v2.5 in the SS-MIX2 directory layout) for these message types at least: ADT^A08 (patient), ADT^A01/A03 (admission/discharge), PPR^ZD1 (diagnosis), RDE^O11 (prescription and injection orders), OML^O33 / OUL^R22 (specimen lab results), OMG^O19 (examination orders). SS-MIX2 standardized storage has no appointment data type (JAMI SS-MIX2 Ver.1.2h; TB-DS-02 §8.13.1), so appointments are not read from it (FR-ING-03b). | H (was M1) | A5, F-34, R2-09 | T | N |  |
| FR-ING-03b | The system shall read appointments (予約) at the Japan head hospital from the vendor's 予約 export or extended storage through the site mapping file (`appointment` table, TB-DS-08 ICD-01). | H (was M1) | A5, R2-09 | T | N |  |
| FR-ING-03a | Where no appointment source is available, the patient list shall show "next visit: unknown" and sort by last encounter (TB-DS-09 S5). | H (split from FR-ING-03b) | A5, R2-09 | T | N |  |
| FR-ING-04a | The system shall provide a mapping profile for the EMR vendor installed at the Japan head hospital (SSI or Fujitsu HOPE) for the data outside SS-MIX2 standard storage. Fit: on the site's sample export, clinical notes, appointments and every field that TB-DS-08 ICD-01 lists for that vendor are read, at least 99 % of sample rows map without error, and every unmapped field is reported. | H (was M1) | A5 | T | N |  |
| FR-ING-04b | The system shall provide a mapping profile for the other Japanese vendor. | L (was M2) | A5, TB-DS-00 §2 | T | N |  |
| FR-ING-04c | The SS-MIX2 reader shall accept each vendor variant in the synthetic fixture set without loss. Fit: every planted variant in the fixture is read with zero dropped resources. | L (split from FR-ING-04b) | A5 | T | N |  |
| FR-ING-05 | The system shall provide a CGMH mapping profile for its self-developed HIS / warehouse export, targeting TW Core. | H (was M1) | A27 | T | P (generic HIS adapter and TW Core built) |  |
| FR-ING-06 | The system shall read FHIR R4 bulk NDJSON as a source, validating against JP Core, TW Core or IPA as configured. | L (was C) | A5 | T | P |  |
| FR-ING-07a | The system shall read XLSX/CSV registry workbooks as a source through a mapping file. | H (was M1) | [P4] B.8 | T | P |  |
| FR-ING-07b | The system shall read REDCap projects as a source through the REDCap read connector (FR-RC-01..03). | H (was M1) | A3, BD-05 | T | N |  |
| FR-ING-08a | The system shall convert every source to FHIR R4 resources of the types Patient, Encounter, Condition, Observation, MedicationRequest, MedicationAdministration, Procedure, DiagnosticReport, DocumentReference, Consent, Appointment and Practitioner. | S1 (was M1) | [P1] §3.1 | T | B |  |
| FR-ING-08b | The converted resources shall be written as an immutable NDJSON snapshot with a manifest (file list, row counts, sha256, extract time). | S1 (was M1) | [P1] §3.1, SC-29 | T | B |  |
| FR-ING-09 | The system shall keep the source code system and code beside any standard code on every coded element, at least: 標準病名 code beside ICD-10; YJ code beside the ingredient code; JLAC10 beside LOINC. | H (was M1) | A7 | I/T | P |  |
| FR-ING-10 | The system shall validate a sample of each snapshot (default 1 % of resources) against the configured profile and reject the snapshot above 0.5 % validation errors. | S0 (was M1) | [P2] §3, SC-32 | T | B |  |
| FR-ING-11 | The system shall remove from the FHIR store and the lake, at the next snapshot, every resource that has left the source (deletion mirroring). | S0 (was M1) | D-86 | T | B |  |
| FR-ING-12 | At each ingest the system shall process only the resources changed since the last successful snapshot. Fit: a re-run with no source change processes 0 resources. | S1 (was M1) | A20, BD-11 | T | P (MICROBATCH deltas) |  |
| FR-ING-12a | The system shall flag every patient with a changed resource for re-evaluation. | S1 (split from FR-ING-12) | A20, BD-11 | T | P |  |
| FR-ING-13 | The system shall OCR scanned documents without a text layer and store the text as a note flagged "OCR". Fit: character error rate ≤ 5 % on the OCR test set (TB-DS-04 TS-ING). | L (was C) | report §Japanese customs | T | N |  |
| FR-ING-14 | When two sources give different values for the same observation and time, the system shall keep both with provenance and mark the most recent as preferred. | L (was M2) | [P4] E-T1 | T | N |  |
| FR-ING-15a | The system shall produce an ingest report per run with: counts per resource type, validation errors, dropped records with reason, and duration. | H (was M1) | [P2] §3 | T | P |  |
| FR-ING-15b | The ingest report shall be shown on the admin page and mailed to the admin role. | H (was M1) | [P2] §3 | T | P |  |
| FR-ING-16 | The system shall keep 3 nightly snapshots and 36 month-end snapshots (N-04), configurable. | S0 (was M1) | D-78, N-04 | T | B |  |
| FR-ING-17 | The system shall refuse an extract whose files, row counts or sha256 do not match its manifest, and keep the previous snapshot current. | H (was M1) | SC-29, F-20 | T | P |  |
| FR-ING-18 | The system shall delete raw extracts from the landing area after a successful ingest, and at most 7 days after arrival in any case, recording the deletion in the audit log. | H (was M1) | SC-34, F-20 | T | N |  |
| FR-ING-19 | The system shall import a PI's own study database (XLSX or CSV) into the pseudonymised lake as a study-scoped dataset. | L (was M2) | TB-DS-17 §6.2, owner request 2026-11-07 03:04 | T | P (FR-ING-07a path) | Built path: FR-ING-07a. The comparison-log upload of FR-SCR-13 (TB-DS-08 ICD-14 `shadow_log`) reuses this mechanism. REDCap projects use the read connector (BD-05), not this import. |
| FR-ING-19a | The import shall accept files only through the on-prem web upload page. | L (split from FR-ING-19) | TB-DS-17 §6.2, owner request 2026-11-07 03:04 | T | N |  |
| FR-ING-19e | The import shall refuse a file received by e-mail. | L (split from FR-ING-19a) | TB-DS-17 §6.2, owner request 2026-11-07 03:04 | T | N |  |
| FR-ING-19b | The import shall match identifier columns to the pid and drop them before any row enters the lake. | L (split from FR-ING-19) | TB-DS-17 §6.2, owner request 2026-11-07 03:04 | T | N |  |
| FR-ING-19c | The import shall pass free-text columns through the PHI pass (FR-DEID-05) before any row enters the lake. | L (split from FR-ING-19) | TB-DS-17 §6.2, owner request 2026-11-07 03:04 | T | N |  |
| FR-ING-19d | The uploaded file shall be deleted from the landing area under the rule of FR-ING-18. | L (split from FR-ING-19) | TB-DS-17 §6.2, owner request 2026-11-07 03:04 | T | N |  |
| FR-ING-20 | A self-service mapping wizard shall let the PI or RA map columns (identifier, date, value, drop) once per file layout and reuse the mapping for later uploads. | L (was M2) | TB-DS-17 §6.2 | T/D | N |  |
| FR-ING-21 | Each import shall record owner, study, ethics approval number, consent type (opt-in, opt-out or waiver) and allowed use (default: this study only). | L (was M2) | TB-DS-17 §6.3 | T | N |  |
| FR-ING-21a | Using an imported dataset in another study shall require a new approval number and the owner's approval. | L (split from FR-ING-21) | TB-DS-17 §6.3 | T | N |  |
| FR-ING-21b | Every import shall be audited with user, file hash, row counts and dropped rows with reason. | L (split from FR-ING-21) | TB-DS-17 §6.3 | T | N |  |
| FR-ING-22 | The system shall read Access (.accdb) and FileMaker (.fmp12) files natively as study-database sources. | L (was C) | TB-DS-17 §6.2 | T | N |  |

#### 3.1.2 DEID — Pseudonymisation, PHI pass, GUID

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-DEID-01 | The system shall replace each chart number by pid = HMAC-SHA-256(site key, normalised MRN) before data enters the lake or FHIR store. | S1 (was M1) | [P1] §3.1, SC-30 | T | B |  |
| FR-DEID-02 | The system shall keep names, national IDs, insurer numbers and chart numbers only in the AES-256-GCM pid map, readable only by the identified-zone service. | S0 (was M1) | [P2] §3, SC-22 | T | B |  |
| FR-DEID-03 | The system shall resolve a pid to a chart number only for a `coordinator` or `investigator` with scope on that study. | S0 (was M1) | BD-04, D-93, D-104, SC-16 | T | B |  |
| FR-DEID-03a | The system shall audit every reveal (`console.reveal_patient`). | S0 (split from FR-DEID-03) | BD-04, D-93, D-104, SC-16 | T | B |  |
| FR-DEID-04 | The system shall run a PHI pass on every new or changed note before the note is used for any D3 purpose (note search, judge, verifier, feasibility). | S1 (was M1) | A8, SC-31, BD-11 | T | N | Build step 1: rules + NER pass on synthetic notes, used by `e2e_simple` stage 0. Timing follows FR-OPS-12: on demand in DEV/TEST; BD-11 window 23:30–02:00 in production. LLM tagger candidate: Gemma 4 26B-A4B (the judge model) behind the regex guard (LLM survey 2026-11-07: 93–100 % of identifiers found on 120 LLM-written synthetic notes in JA, zh-TW and EN vs 51–64 % for the regex guard; optimistic because the notes were LLM-written; N-07 on real notes before reliance). |
| FR-DEID-05a | The PHI pass shall detect the HIPAA Safe Harbor identifier categories [S8]. | H (was M1) | A8 | T | N |  |
| FR-DEID-05b | The PHI pass shall detect Japanese identifiers: カナ氏名, 保険者番号 and 被保険者記号・番号, 介護保険被保険者番号, マイナンバー, 和暦 dates, Japanese postal codes and addresses. | H (was M1) | A8, A12 | T | N |  |
| FR-DEID-05c | The PHI pass shall detect Taiwan identifiers with checksum validation: national ID (one letter + 1/2 + 8 digits), new-format resident certificate (one letter + 8/9 + 8 digits, issued since 2021), old-format resident certificate (two letters + 8 digits), NHI card number. | H (was M1) | A12, F-58 | T | N |  |
| FR-DEID-05d | The PHI pass shall detect hospital, ward and clinic names and staff names. | H (was M1) | A8 | T | N |  |
| FR-DEID-06 | The system shall replace each detected span by a surrogate of the same type. | H (was M1) | A8, F-29 | T | N |  |
| FR-DEID-06a | The surrogate shall be the same for the same entity within one patient. Fit: on the PHI test set, 100 % of repeated entities get the same surrogate. | H (split from FR-DEID-06) | A8, F-29 | T | N |  |
| FR-DEID-06b | Surrogate dates shall keep their intervals within the patient. | H (split from FR-DEID-06) | A8, F-29 | T | N |  |
| FR-DEID-07 | The system shall shift dates per patient by a random offset fixed for that patient within ±182 days (N-08), only for record-level data that leaves the identified zone at D2 or below; dates kept inside the site at D3/D4 are not shifted. | L (was M2) | N-08, SC-35, F-12 | T | N |  |
| FR-DEID-08 | The system shall keep the scrubbed and the original version of each note separately. | H (was M1) | CON-06 | T/I | N |  |
| FR-DEID-08a | Every D3 use of a note shall use the scrubbed version; only the identified zone (D4) uses the original. | H (split from FR-DEID-08) | CON-06 | T/I | N |  |
| FR-DEID-09 | The system shall record, per note, which detector found each span and the detector versions. | H (was M1) | A8 | I | N |  |
| FR-DEID-10 | The system shall draw a monthly review sample of scrubbed notes per site (default 50 notes), provide a review form, and compute the leak rate as defined in N-07. | H (was M1) | N-07, F-11 | D | N |  |
| FR-DEID-11a | The system shall suppress every count below 10 in any output leaving the site (N-01). | H (was M1) | N-01, SC-50, F-08 | T | N (code default 5) |  |
| FR-DEID-11b | The system shall suppress every count below 5 in any aggregate shown inside the site outside the identified zone (N-01), with controlled rounding of neighbouring counts. | S1 (was M1) | N-01, D-78 | T | B |  |
| FR-DEID-12 | The system shall compute, per patient, Bloom-filter encodings (CLK) of normalised kana/romanised name, birth date and sex, keyed with the country hub's consortium secret. | L (was M2) | A9, A15, SC-52 | T | N |  |
| FR-DEID-13 | Name normalisation for the GUID shall use カナ氏名 where present, NFKC, and a documented transliteration for Chinese names. Fit: linkage precision and recall are reported per variant type on a synthetic set with planted typos, kana variants and transliteration variants. | L (was M2) | A9, A12, F-59 | T | N |  |
| FR-DEID-13a | Where the study's ethics record allows it, the system shall add the Taiwan national ID to the GUID input as a hashed key. Fit: with the setting off (the default) no national ID enters the GUID input. | L (split from FR-DEID-13) | A9, A12, F-59 | T | N |  |
| FR-DEID-14 | GUID encodings shall leave the site only for linkage at the hub of the same country, and only signed. | L (was M2) | A15, BD-06 | T/I | N |  |
| FR-DEID-14a | GUID encodings shall never leave the site together with clinical data other than the study ID and site ID. | L (split from FR-DEID-14) | A15, BD-06 | T/I | N |  |
| FR-DEID-15 | The system shall apply a per-study de-identification profile chosen from: APPI 仮名加工情報 (internal use), 匿名加工情報 (external release), Taiwan PDPA de-identified release. Fit: for each profile a fixture export contains only the fields that profile permits. | L (was M2) | A8, A34 | I | N |  |

#### 3.1.3 FEAS — Feasibility (flow A)

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-FEAS-01a | A `coordinator` or `investigator` (and `cro` where enabled) shall be able to start a feasibility job from a web input page by pasting criteria text. | S1 (was M1) | A10, TB-DS-00 §2 | T | N |  |
| FR-FEAS-01b | The input page shall also accept an uploaded protocol (PDF/DOCX) or a ClinicalTrials.gov or jRCT identifier. | S1 (was M1) | A10 | T | P (CT.gov fetch built) |  |
| FR-FEAS-01c | The same inputs shall be accepted by e-mail. | S1 (was M1) | [P1] §5 | T | B |  |
| FR-FEAS-02 | The system shall split the text into inclusion and exclusion criteria, compile each into the criterion IR, classify each as filter, mixed, notes or human, and show the class of each criterion to the user. | S1 (was M1) | D-98, [P1] §4.3 | T | B |  |
| FR-FEAS-03 | The system shall run the feasibility funnel on D3 data without study approval: total population, then each criterion in order, to likely candidates, with count and percentage at every step. | S1 (was M1) | A10, A26, AS-03 | T | B |  |
| FR-FEAS-04a | The feasibility report shall contain the funnel of FR-FEAS-03. | S1 (was M1) | A10 | T | B |  |
| FR-FEAS-04b | The report shall contain the monthly count of newly qualifying patients over the last 36 months. | S1 (was M1) | [P1] §9.1 | T | B |  |
| FR-FEAS-04c | The report shall contain a Monte-Carlo enrolment estimate for a stated recruitment period and screen-fail rate, with its 95 % interval. | S1 (was M1) | [P1] §9.1 | T | B |  |
| FR-FEAS-04d | The report shall list the criteria the data cannot answer, each with its reason. | S1 (was M1) | D-101 | T | B |  |
| FR-FEAS-04e | The report shall state the data period and the snapshot date. | S1 (was M1) | D-101 | T | B |  |
| FR-FEAS-04f | The report shall carry a notice when a source changed since the previous snapshot used for this study. | S1 (was M1) | D-101 | T | P |  |
| FR-FEAS-04g | The report shall name the model builds, prompt versions and ruleset version used. | S1 (was M1) | D-101 | T | B |  |
| FR-FEAS-04h | The report shall state the small-cell threshold applied (N-01). | S1 (was M1) | N-01 | T | B |  |
| FR-FEAS-04i | The report shall list every default the system chose (FR-FEAS-05). | S1 (was M1) | A10 | T | P |  |
| FR-FEAS-05 | The system shall produce the report with no user input beyond FR-FEAS-01. | S1 (was M1) | A10, F-29 | T | P |  |
| FR-FEAS-05a | Every parameter not given (recruitment period, screen-fail rate, data period, language) shall take a documented default and be listed under FR-FEAS-04i. | S1 (split from FR-FEAS-05) | A10, F-29 | T | P |  |
| FR-FEAS-06 | The report shall be produced in the requester's language (JA, zh-TW, EN) as a web page and PDF, plus an XLSX of the funnel. | S1 (was M1) | D-100, A39 | T | B |  |
| FR-FEAS-07 | The system shall show the feasibility job's status on the feasibility page. | S1 (was M1) | A20 | T | B | Jobs can complete overnight. |
| FR-FEAS-07a | The system shall notify the user on the page and by e-mail when the job is done. | S1 (split from FR-FEAS-07) | A20 | T | B |  |
| FR-FEAS-08 | The system shall build a sponsor pack (report PDF + funnel XLSX, D1 only, k = 10 per N-01) and release it outside the site only after an `investigator` of the study approves the release. | H (was M1) | A36, D-101, SC-54 | T | P (pack and release built; k = 5) |  |
| FR-FEAS-09 | The system shall run a consortium feasibility across the sites of one country through its hub (FED) and show per-site and de-duplicated totals. | L (was M2) | A15, A41, BD-06 | T | N |  |
| FR-FEAS-10 | The system shall answer feasibility from a de-identified research database configured as a separate D2 source (at CGMH: CGRD) and label that source on the report. | L (was M2) | A27, [P4] F.7 | T | N |  |
| FR-FEAS-11 | From an uploaded protocol (FR-FEAS-01b) the system shall draft the study ruleset automatically, attaching to each criterion the verbatim source quote from the protocol with section and page. | S1 (was M1) | BD-13 (TB-DS-00 v0.4) | T | P (parser and compiler built; quote link N) | Built: doc-parser and criteria-compiler. Not built: the quote link. |
| FR-FEAS-11a | The system shall flag on the draft every criterion it cannot compile and keep that criterion in the draft. Fit: no criterion of the protocol text is missing from the draft. | S1 (split from FR-FEAS-11) | BD-13 (TB-DS-00 v0.4) | T | N |  |
| FR-FEAS-12 | The ruleset approval (S20) shall be **one page with one Approve**, listing each criterion in plain language with its protocol quote, operator and threshold, time window and missing-data rule, amber rows first, with the mapped codes and units **folded under each row**. | S2 (was M1) | BD-13, TB-REV-006c C-09, TB-DS-17 §1.1 | T/D | N | TB-REV-006f F6-07, F6-27 (one page, one Approve). |
| FR-FEAS-12a | The `investigator` shall be able to use **Approve all** only after opening every amber row once. | S2 (split from FR-FEAS-12) | BD-13, TB-REV-006c C-09, TB-DS-17 §1.1 | T/D | N |  |
| FR-FEAS-12b | The `investigator` shall be able to edit a single criterion line on the approval page. | S2 (split from FR-FEAS-12) | BD-13, TB-REV-006c C-09, TB-DS-17 §1.1 | T/D | N |  |
| FR-FEAS-12c | Every criterion edit on the approval page shall be audited and the edited line re-checked before approval. | S2 (split from FR-FEAS-12) | BD-13, TB-REV-006c C-09, TB-DS-17 §1.1 | T/D | N |  |
| FR-FEAS-12d | A `coordinator` shall be able to pre-tick the code mapping of each row, recorded as its own audit event. | S2 (split from FR-FEAS-12) | BD-13, TB-REV-006c C-09, TB-DS-17 §1.1 | T/D | N |  |
| FR-FEAS-12e | Approval on a phone shall be possible only when no row is amber. | S2 (split from FR-FEAS-12) | BD-13, TB-REV-006c C-09, TB-DS-17 §1.1 | T/D | N |  |
| FR-FEAS-12f | A re-approval shall show **Changes since vN** (criteria added, removed or changed). | S2 (split from FR-FEAS-12) | BD-13, TB-REV-006c C-09, TB-DS-17 §1.1 | T/D | N |  |
| FR-FEAS-13 | A feasibility report shall offer **Refresh**: re-run the same criteria and ruleset version on the newest snapshot, keeping the earlier report (F6-27). | S2 (new) | TB-REV-006f F6-27 | T | N |  |

#### 3.1.4 SCR — Patient lists (flow B)

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-SCR-01 | For an approved ruleset, the system shall produce a patient list with the v4 cascade: S0 consent and contact preferences, S1 SQL/CQL filters, S2 note search, S3 judge, S4 verifier, tiers; S5 is the person. | S2 (was M1) | D-103 | T | B |  |
| FR-SCR-02a | The patient list shall be refreshed weekly (default Monday 03:00). | S2 (was M1) | [P1] §8.2 | T | B |  |
| FR-SCR-02b | The patient list shall be refreshed each night, in the BD-11 screening window, for patients whose data changed since the last run. | S2 (was M1) | A20, BD-11, F-62 | T | P |  |
| FR-SCR-03 | Each row shall show: pseudonym (or chart number after reveal), the deterministic why-fits sentence, key conditions, missing or stale items, next clinic visit, tier, and evidence quotes for note criteria. | S2 (was M1) | A10, D-104 | T | P (age/sex not on weekly list, D-104 known gap) |  |
| FR-SCR-04a | Each row shall offer "Open in EMR": after reveal, copy the chart number to the clipboard and, where a site URL template exists, open the EMR deep link. | H (was M1) | A10 | T | N |  |
| FR-SCR-04b | Each row shall offer "Open in REDCap", which creates or opens the screening record through the External Module. | L (was M2) | A10, BD-05 | T | N |  |
| FR-SCR-04c | When the study uses EDC-lite, each row shall offer "Open in EDC-lite" in place of "Open in REDCap". | L (split from FR-SCR-04b) | A10 | T | N |  |
| FR-SCR-05 | A note-based exclusion shall require judge and verifier to agree; otherwise the patient is listed in the review tier. | S2 (was M1) | CON-05, D-97 | T | B |  |
| FR-SCR-05a | Without a verifier, the system shall make no note-based exclusion. | S2 (split from FR-SCR-05) | CON-05, D-97 | T | B |  |
| FR-SCR-05b | When no verifier is configured, the report shall state that note-based exclusions are off. | S2 (split from FR-SCR-05) | CON-05, D-97 | T | B |  |
| FR-SCR-06 | Every model verdict shall include a verbatim quote checked against the record. | S2 (was M1) | [P2] §4, SC-62 | T | B |  |
| FR-SCR-06a | A verdict whose quote does not match the record shall be treated as "unknown". | S2 (split from FR-SCR-06) | [P2] §4, SC-62 | T | B |  |
| FR-SCR-07 | An `investigator` shall be able to mark each patient with one of **Approach**, **Need info** or **Not suitable** (with a reason from the study's reason list, FR-STUDY-09). | S2 (was M1) | D-104, TB-REV-006c C-10 | T | P (three marks built; reason list hard-coded, "Not now" N) | Built: three marks. Reason list hard-coded today (FR-STUDY-09). |
| FR-SCR-07a | The same mark vocabulary shall be used on every screen, mail and export. | S2 (split from FR-SCR-07) | D-104, TB-REV-006c C-10 | T | P |  |
| FR-SCR-07g | Each mark shall be recorded as an audited registry event. | S2 (split from FR-SCR-07) | D-104, TB-REV-006c C-10 | T | P |  |
| FR-SCR-07h | A mark shall not change a screening result. | S2 (split from FR-SCR-07) | D-104, TB-REV-006c C-10 | T | P |  |
| FR-SCR-07d | An `investigator` shall be able to mark a patient **Not now, re-check on <date>**. | S2 (split from FR-SCR-07) | D-104, TB-REV-006c C-10 | T | N |  |
| FR-SCR-07i | A patient marked Not now shall be hidden from lists until that date. | S2 (split from FR-SCR-07d) | D-104, TB-REV-006c C-10 | T | N |  |
| FR-SCR-07e | An `investigator` shall be able to replace a mark with a new mark or withdraw it. | S2 (split from FR-SCR-07) | D-104, TB-REV-006c C-10 | T | N | F6-27: a wrong tap must be undoable. |
| FR-SCR-07j | A replaced or withdrawn mark shall stay in the audit record. | S2 (split from FR-SCR-07e) | D-104, TB-REV-006c C-10 | T | N |  |
| FR-SCR-07f | No screen, mail or export shall use "Not eligible", "excluded" or "ineligible" for a mark. | S2 (split from FR-SCR-07) | D-104, TB-REV-006c C-10 | T | N |  |
| FR-SCR-07b | For a candidate whose next visit is with a physician who is not an investigator of the study, the list shall offer **Ask treating doctor** instead of Approach. | L (was M1) | TB-REV-006c C-13 | T | N | Until this is built, the PI marks Need info and the coordinator asks the treating doctor as today. The FR-SCR-08 task follows in a later step. Who may introduce a study is set on S21 (BD-19). |
| FR-SCR-07k | An Ask treating doctor mark shall create a coordinator item on S8 "Today" and in the N2 digest. | L (split from FR-SCR-07b) | TB-REV-006c C-13 | T | N |  |
| FR-SCR-07c | After an Approach mark on a patient with a visit today, the PI's screen shall show whether a coordinator on duty (FR-UI-18) has seen it: "CRC notified" or "CRC on the way". | L (was M1) | TB-REV-006c C-14 | T | N | Depends on the S8 Marks today pane (FR-UI-18). |
| FR-SCR-08 | Each investigator mark shall create a task for the study's coordinators, worded from the mark (Approach: "prepare visit"; Need info: "find <missing item>"; Ask treating doctor: "ask <physician>"), shown on the coordinator home and optionally mailed. | L (was M2) | report §UX, F-05 | T | N |  |
| FR-SCR-09 | (Withdrawn: duplicate of NFR-CAP-02.) | — (was M1) | F-29 | — | W |  |
| FR-SCR-10a | The system shall keep the screening log per study with the ICH E6(R3) screening-log content: screening number (`screening_no`, BD-18), pseudonym, date first listed, date screened by the site, contact outcome events with reason codes, status (mapping in TB-DS-07 §4.1 "Contact-outcome events and status mapping"), reason not approached or screen-failed, consent date and enrolment date (both read from REDCap where linked, FR-RC-16). Column layout: TB-TMPL-03 in TB-TMPL-07. | S2 (was M1) | D-92, BD-18, TB-REV-006c C-06 | T | P (pseudonym, status, dates, reasons built; screening_no and outcome events N) |  |
| FR-SCR-10b | The screening log shall be exportable as XLSX, resolving chart numbers only inside the box and only for roles allowed by AM-01. | S2 (was M1) | D-92 | T | B |  |
| FR-SCR-10c | A `coordinator` shall record a contact outcome in at most 2 taps: Reached – visit booked · Reached – declined · Not reached (retry date) · Not approached (physician decision) · Lost contact; each maps to a registry status or leaves it unchanged per TB-DS-07 §4.1 mapping table. | S2 (was M1) | TB-REV-006c C-06, TB-DS-17 §1.2 | T | N |  |
| FR-SCR-11 | The system shall treat "not mentioned" as unknown by default and allow absence semantics per ruleset. | S2 (was M1) | D-103 | T | B |  |
| FR-SCR-12 | The system shall show missing or stale data on the patient's row. | S2 (was M1) | report §UX, TB-REV-006c C-15 | T | P (wording N) | Wording N (FR-SCR-12a). |
| FR-SCR-12c | The system shall not exclude a patient because data is missing or stale. | S2 (split from FR-SCR-12) | report §UX, TB-REV-006c C-15 | T | P |  |
| FR-SCR-12a | The missing-data text shall depend on consent state: **before consent** "Would need checking after consent: <item> (last <date>)", optionally "may be updated in routine care at the visit"; **after consent** (status consented or later) "To collect at the screening visit". | S2 (split from FR-SCR-12) | report §UX, TB-REV-006c C-15 | T | N |  |
| FR-SCR-12b | The system shall never prompt a research procedure before consent. | S2 (split from FR-SCR-12) | report §UX, TB-REV-006c C-15 | T | N |  |
| FR-SCR-13 | The system shall keep, per study, the comparison of TrialBox's list with the staff's own screening result (found by both, by staff only, by TrialBox only), built from the ICD-14 `shadow_log` upload with identifiers matched to pid inside the box and then dropped. | H (was M1) | BD-16, N-16, TB-REV-006c C-21 | T | N | Process (TB-DS-04 §8.9): the pilot team imports the staff result weekly from the CRC's existing log (Excel, or paper transcribed by the pilot team), writing the mapping once per layout; the CRC keeps the log as today and enters nothing extra (BD-16). |

#### 3.1.5 CASE — Single-patient check

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-CASE-01a | A `coordinator` or `investigator` shall be able to check one patient against one or more approved rulesets by chart number from the console or by e-mail. | S0 (was M1) | D-91 | T | B |  |
| FR-CASE-01b | The same check shall be available from a REDCap record page through the External Module. | L (was M2) | BD-05 | T | N |  |
| FR-CASE-02 | The result shall be one card per criterion: verdict (meets / does not meet / unknown / for a person), evidence quote with date and source, and one primary action ("Send to PI" for a negative verdict, never "Exclude"). | H (was M1) | report §UX | T | P |  |
| FR-CASE-03 | A CASE result shall be available within 60 s at the 95th percentile (N-13) for a patient with at most 200 notes and a ruleset with at most 20 note criteria, with the judge loaded. | H (was M1) | N-13, F-40 | T | N |  |
| FR-CASE-04 | A CASE check shall add the patient to the registry only by explicit user action. | S0 (was M1) | D-93 | T | B |  |
| FR-CASE-05 | A REDCap Data Entry Trigger on a new screening record shall start a CASE check when configured for the project. | L (was M2) | report §REDCap, SC-49 | T | N |  |

#### 3.1.6 EDC — eCRF pre-fill (L)

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-EDC-01 | The system shall compile a form definition (REDCap data dictionary, or EDC-lite Questionnaire when C is built) into a JSON schema per instrument and event: field types, coded choices, validation ranges, branching logic. | L (was M2) | A4 | T | N |  |
| FR-EDC-02 | Fields annotated with a source mapping (format `@TB-SOURCE=<kind>:<code system>:<code>`, codes per TB-DS-10) shall be filled by deterministic rules from FHIR data within the visit window, with unit conversion and without a model. | L (was M2) | CON-04, F-33 | T | N |  |
| FR-EDC-03 | Remaining narrative fields shall be filled by the judge with schema-constrained output. | L (was M2) | A4 | T | N |  |
| FR-EDC-03a | Each narrative value shall carry a verbatim quote, the source document and its date. | L (split from FR-EDC-03) | A4 | T | N |  |
| FR-EDC-04 | Every proposed value shall pass deterministic validators (type, range, choice code, visit window, branching consistency) before it is shown. | L (was M2) | report §EDC | T | N |  |
| FR-EDC-04a | A value that fails a validator shall be shown as a query instead of being corrected. | L (split from FR-EDC-04) | report §EDC | T | N |  |
| FR-EDC-05 | Proposed values shall be shown as cards beside the form. | L (was M2) | A4 | T/D | N |  |
| FR-EDC-05b | The user shall be able to accept, edit or reject each proposed value. | L (split from FR-EDC-05) | A4 | T/D | N |  |
| FR-EDC-05a | No value shall be written to REDCap (or to EDC-lite) without the user's accept or edit action on that value. | L (split from FR-EDC-05) | A4 | T/D | N |  |
| FR-EDC-06 | "Accept all with quotes" shall be offered only for rule-filled fields (FR-EDC-02). | L (was M2) | report §UX | T | N |  |
| FR-EDC-06a | "Accept all with quotes" shall record one confirmation per field. | L (split from FR-EDC-06) | report §UX | T | N |  |
| FR-EDC-07 | Accepted values shall be written through the REDCap External Module under the accepting user's own REDCap session (or, for EDC-lite, as the EDC-lite user). | L (was M2) | BD-05, F-23 | T | N |  |
| FR-EDC-07a | The appliance shall store no personal REDCap API token. | L (split from FR-EDC-07) | BD-05, F-23 | T | N |  |
| FR-EDC-07b | A form filled from accepted values shall stay "Unverified" until the user saves it. | L (split from FR-EDC-07) | BD-05, F-23 | T | N |  |
| FR-EDC-08 | The system shall record per field: proposed value, final value, accepted / edited / rejected, user, time, model build and prompt version; and report acceptance and edit rates per field. | L (was M2) | report §EDC, SC-70 | T | N |  |
| FR-EDC-09 | A field shall be demoted to manual entry automatically when edits + rejects exceed 20 % of its last 30 proposals (N-10). | L (was M2) | N-10 | T | N |  |
| FR-EDC-09a | The system shall tell the admin when a field is demoted. | L (split from FR-EDC-09) | N-10 | T | N |  |
| FR-EDC-10 | Conflicting values from two sources or dates shall be shown together with the most recent pre-selected. | L (was M2) | [P4] E-T1, FR-ING-14 | T | N |  |

#### 3.1.7 CON — Consent support

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-CON-01 | The system shall generate the consent explainer (patient-friendly summary) automatically from the study's ICF (and protocol for context), in the patient's language, as a **draft** for the same ethics submission pack as the ICF. | S0 (was M1) | docs/CONSENT.md, BD-15 (TB-DS-00 v0.5), F-04 | T | B (draft); routing with ICF N | The committee then reviews both together (BD-15 (a)). |
| FR-CON-02 | The explainer shall be available in Japanese, Traditional Chinese and English, and in further languages added per site as translation files. | H (was M1) | A39 | T | P (JA, zh-TW, EN built) |  |
| FR-CON-03 | The system shall provide explainer templates for a legally acceptable representative (代諾者) and for family members. Fit: both templates exist in JA, zh-TW and EN. | L (was M2) | report §Japanese customs | I | N |  |
| FR-CON-04 | A live explainer shall be handed to REDCap e-Consent as an attached document or survey text. | L (was M2) | CON-07 | T | N |  |
| FR-CON-04b | When the study uses EDC-lite, a live explainer shall be handed to EDC-lite consent. | L (split from FR-CON-04) | CON-07 | T | N |  |
| FR-CON-04a | TrialBox shall not collect or store signatures. | L (split from FR-CON-04) | CON-07 | T | N |  |
| FR-CON-05 | Patient-facing letters shall use fixed templates (keigo for Japanese, formal register for Chinese) with named slots. | H (was M1) | report §Japanese customs, F-29 | T/I | N |  |
| FR-CON-05a | The model shall fill only the named slots of a patient-facing letter. Fit: a test shows that text outside the slots is byte-identical to the template. | H (split from FR-CON-05) | report §Japanese customs, F-29 | T/I | N |  |
| FR-CON-06 | The explainer shall go live on the study's consent page automatically, with no Release action or command, when the study's approval record (S21) holds: committee, approval number, approval date, approved ICF version, the **uploaded committee-approved explainer file**, the coordinator's entry and the investigator's confirmation, and — for a study flagged industry-sponsored — the sponsor approval of patient material (FR-CON-09). The live explainer is the uploaded approved file, never the generated draft; its SHA-256 is computed by the system from the upload. If the live file's hash no longer matches the record, the explainer is withdrawn automatically and the reason shown. | H (was M1) | BD-15 (b), (e), TB-REV-006c C-05 | T | N |  |
| FR-CON-07 | A site setting (`admin`) and a study setting (`coordinator` or `investigator` with scope) shall each be able to switch the explainer off. | H (was M1) | BD-15 | T | N |  |
| FR-CON-07a | With the explainer switched off for a study, the system shall generate nothing for that study and use only the ICF. | H (split from FR-CON-07) | BD-15 | T | N |  |
| FR-CON-08 | When a new ICF version is added, the system shall generate a new explainer draft for the ICF amendment pack. | H (was M1) | BD-15 (f) | T | N |  |
| FR-CON-08a | The current approved explainer shall stay live until the amendment's approval record is entered and confirmed. | H (split from FR-CON-08) | BD-15 (f) | T | N |  |
| FR-CON-09 | When the committee approves wording edits to the explainer without an ICF amendment, the `coordinator` shall be able to upload the edited approved file to the same approval record as a new file version with the committee letter date, without regeneration. | H (was M1) | BD-15 (c), TB-REV-006c C-05 | T | N |  |
| FR-CON-09a | The previous explainer file shall stay live until the `investigator` confirms the new file version. | H (split from FR-CON-09) | BD-15 (c), TB-REV-006c C-05 | T | N |  |
| FR-CON-10 | A study flagged industry-sponsored (企業治験 / 廠商委託試驗) shall not go live with an explainer until "sponsor approval of patient material received" (date, sponsor contact) is recorded on S21. | H (was M1) | BD-15 (d), TB-REV-006c C-05 | T | N |  |

#### 3.1.8 TC — Trial-conduct support (L)

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-TC-01 | The system shall list upcoming protocol visits per enrolled participant and flag visits that will fall outside the protocol window. | L (was M2) | A15 | T | N |  |
| FR-TC-02 | The system shall pre-fill each visit's eCRF from EMR data in that visit's window, under FR-EDC-01..10. | L (was M2) | A15 | T | N |  |
| FR-TC-03 | The system shall suggest possible adverse events from new notes, labs and prescriptions since the last visit, quoting the source, with a grade per CTCAE v5.0 [S17] where a lab threshold defines it. | L (was M2) | A15, BD-08, F-24 | T | N |  |
| FR-TC-03a | Each AE suggestion shall be a task for the study's `investigator`. | L (split from FR-TC-03) | A15, BD-08, F-24 | T | N |  |
| FR-TC-03b | Coordinators of the study shall be able to see and prepare an AE suggestion. | L (split from FR-TC-03a) | A15, BD-08, F-24 | T | N |  |
| FR-TC-04 | The system shall never close or dismiss an AE suggestion itself. | L (was M2) | BD-08, F-24 | T | N |  |
| FR-TC-04a | Only an `investigator` of the study shall be able to dismiss an AE suggestion, and only with a reason. | L (split from FR-TC-04) | BD-08, F-24 | T | N |  |
| FR-TC-04b | Every AE-suggestion dismissal shall be audited. | L (split from FR-TC-04a) | BD-08, F-24 | T | N |  |
| FR-TC-05 | The system shall flag new, stopped or protocol-prohibited concomitant medications. | L (was M2) | A15 | T | N |  |
| FR-TC-06 | The system shall re-check the criteria a ruleset marks as ongoing (`ongoing: true`) at each snapshot and notify the study's `investigator` of each violation. | L (was M2) | A15 | T | N |  |
| FR-TC-07 | The system shall list unverified fields and open queries per site for monitors. | L (was C) | report §Trial conduct | T | N |  |

#### 3.1.9 FED — Country hub (L)

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-FED-01 | A TrialBox instance shall be configurable as the hub of one country; other instances of that country register as member sites by certificate from the consortium CA. | L (was M2) | A15, BD-06, SC-53 | T | N |  |
| FR-FED-02 | The hub shall distribute signed, approved rulesets to member sites. | L (was M2) | A41 | T | N |  |
| FR-FED-02a | A site shall run a distributed ruleset only after an `investigator` of that site approves the cross-site query. | L (split from FR-FED-02) | A41 | T | N |  |
| FR-FED-03 | A member site shall return a signed funnel (D1, k = 10 per N-01) and the GUID encodings of likely candidates; no other patient-level data. | L (was M2) | A15, A37, N-01 | T | N |  |
| FR-FED-04 | The hub shall compute per-site and total funnels and remove patients counted at two or more sites by GUID matching, without learning identities. | L (was M2) | A15 | T | N |  |
| FR-FED-05 | Hub–site messages shall use HTTPS with mutual TLS over the hospital network or VPN, or signed and encrypted e-mail where no direct link exists. | L (was M2) | SC-23, SC-53 | T | N |  |
| FR-FED-06 | Each site shall send the hub the daily head hash of its audit chain. | L (was M2) | SC-72 | T | N |  |
| FR-FED-06a | The hub shall countersign each head hash and return the signature, which the site stores. | L (split from FR-FED-06) | SC-72 | T | N |  |
| FR-FED-07 | The hub shall keep a governance record per cross-site query: requester, approving investigator per site, steering-committee reference, purpose, date. | L (was M2) | A41 | I | N |  |
| FR-FED-08 | A consortium feasibility for 3 sites shall complete within one night (BD-11 window), with messages batched nightly by default. | L (was M2) | A11 | T | N |  |
| FR-FED-09 | When a patient opts out or withdraws at a site, that site shall exclude the patient from every later funnel and GUID upload. | L (was M2) | F-25, SC-36 | T | N | Results already released are not recalled; the governance record says so. |
| FR-FED-09a | After an opt-out or withdrawal, the hub shall recompute every open cross-site result from the next uploads. | L (split from FR-FED-09) | F-25, SC-36 | T | N |  |
| FR-FED-10 | No record-level data and no GUID encoding shall cross a national border; only D1 aggregates cross between countries. | L (was M2) | BD-06 | T/I | N |  |

#### 3.1.10 RC — REDCap integration

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-RC-01 | The system shall connect to a REDCap project through the REDCap API with one project-level read token stored in the appliance secret store; no personal tokens. | S3 (was M1) | BD-05, SC-13 | T | N |  |
| FR-RC-02 | The system shall read the project's data dictionary (metadata), instruments, events, arms, repeating instruments and DAGs. | S3 (was M1) | A14, BD-05 | T | N |  |
| FR-RC-03a | The system shall export records, filtered by DAG where configured. | S3 (was M1) | A14, BD-05 | T | N |  |
| FR-RC-03b | The system shall import accepted values through the External Module, preserving REDCap form status (FR-EDC-07). | L (was M2) | BD-05 | T | N |  |
| FR-RC-04 | The system shall create a screening record in a configured REDCap project from a patient-list row on user action, through the External Module. | L (was M2) | A10, BD-05 | T | N |  |
| FR-RC-05 | The system shall accept a REDCap Data Entry Trigger call only after verifying the calling host, the project and the signature. | L (was M2) | SC-49 | T | N |  |
| FR-RC-05a | A verified Data Entry Trigger call shall start only jobs configured for that project, and only read-only jobs. | L (split from FR-RC-05) | SC-49 | T | N |  |
| FR-RC-06a | A REDCap External Module shall show the candidate list on the project home page. | L (was M2) | A2 | D | N |  |
| FR-RC-06b | The module shall show "Check this patient" on record pages (FR-CASE-01b). | L (was M2) | A2 | D | N |  |
| FR-RC-06c | The module shall show the pre-fill side panel on data entry forms (FR-EDC-05). | L (was M2) | A2 | D | N |  |
| FR-RC-07 | The External Module shall contain no clinical logic. | L (was M2) | CON-03, CON-11, SC-47 | I | N |  |
| FR-RC-07a | The External Module shall call the appliance API with the REDCap user's identity, signed per SC-47, and render the returned cards. | L (split from FR-RC-07) | CON-03, CON-11, SC-47 | I | N |  |
| FR-RC-08 | The External Module shall respect REDCap user rights and DAGs: a user sees only records and studies REDCap allows them. | L (was M2) | A13 | T | N |  |
| FR-RC-09 | The system shall provide a REDCap-compatible API simulator implementing the documented API methods TrialBox uses (export/import metadata, records, files, events, arms, DAGs, project info, version; Data Entry Trigger calls), written only from public documentation. | S3 (was M1) | A16 | T | N |  |
| FR-RC-10 | The REDCap API simulator shall be used in CI and in `e2e_simple`. | S3 (was M1) | A16 | T | N |  |
| FR-RC-10a | The connector tests shall run against a hospital REDCap development instance before each release that changes the connector. | H (split from FR-RC-10) | A16 | T | N |  |
| FR-RC-11 | The system shall use REDCap Alerts and Notifications for staff notices when the project is configured so, and its own mail channel otherwise. | L (was C) | report §UX | D | N |  |
| FR-RC-12 | After a feasibility spike, the system shall be able to act as a SMART on FHIR source for REDCap CDIS Clinical Data Pull. | L (was C) | report §REDCap | D | N |  |
| FR-RC-13 | The system shall raise REDCap Data Resolution Workflow queries for pre-filled values that fail validation, when the project uses it. | L (was C) | report §REDCap | T | N |  |
| FR-RC-14 | The connector shall work with the REDCap LTS version in use at each site. Fit: ICD-04 conformance passes against the simulator's default version (16.x LTS, TB-DS-08 §4.4). | S3 (was M1) | A3 | T | N |  |
| FR-RC-14a | The connector shall report an unsupported REDCap version with its number. | S3 (split from FR-RC-14) | A3 | T | N |  |
| FR-RC-15 | The system shall export the screening log of a study (FR-SCR-10a) in REDCap import format (CSV) for a screening-log project, **keyed on `screening_no`**, with `record_id` filled where the link of FR-RC-16 exists. | S3 (was M1) | TB-DS-00 §2, BD-18 | T | N |  |
| FR-RC-16 | Per study, the read connector shall use a **project link** set on S21 (project id, read-token reference, DAG filter, link field `tb_screening_no` or the per-study MRN alternative, consent-date field and event, enrolment field, screen-fail field with its choice map, withdrawal field; TB-DS-08 ICD-04) to join `record_id` ↔ `screening_no` ↔ pid and to read consent, enrolment, screen-fail and withdrawal; nobody types a record ID or pid into TrialBox; nothing is written to REDCap (BD-05, BD-18). | S3 (was M1) | BD-18, TB-REV-006c C-06, C-17 | T | N |  |
| FR-RC-17 | A **REDCap API simulator** (TB-DS-08 §4.4 ICD-04S) shall answer the read methods TrialBox uses, from JSON fixture projects, so step 3 and `e2e_simple` run without a real REDCap. | S3 (new) | TB-REV-006f F6-15, ADR-05 | T | N |  |
| FR-RC-17a | The REDCap API simulator shall ship in the demo and test images and never in a hospital product image. | S3 (split from FR-RC-17) | TB-REV-006f F6-15, ADR-05 | T | N |  |

#### 3.1.11 EDCL — EDC-lite (L)

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-EDCL-01 | The system shall provide study forms on FHIR Questionnaire / QuestionnaireResponse for sites or studies without REDCap. | L (was C) | A16 option C | T | N |  |
| FR-EDCL-02 | EDC-lite shall import a REDCap data dictionary (CSV) and create equivalent forms: field types, choices, validation, branching logic. | L (was C) | A16 | T | N |  |
| FR-EDCL-03 | EDC-lite shall keep a per-field history (who, when, old value, new value, reason) and form status (incomplete, unverified, complete). | L (was C) | [S10] data integrity | T | N |  |
| FR-EDCL-04 | EDC-lite shall export data to REDCap (API import) and as CSV in REDCap import format. | L (was C) | A16 | T | N |  |
| FR-EDCL-05 | EDC-lite shall be labelled on every page and in the documentation "not validated for regulated trials". | L (was C) | CON-07 | I | N |  |
| FR-EDCL-06 | EDC-lite shall provide events (visits), repeating forms and data access by site group. | L (was C) | A15 | T | N |  |

#### 3.1.12 UI — Role work lists, study pages, cards

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-UI-01 | After login every user shall land on their **role work list** (S16 PI, S8 coordinator, S13 admin, S3 viewer/cro). | S4 (was M1) | P-ENTRY | D | N | The function tiles become the "More" menu. There is no separate entry page (TB-REV-006f F6-06). |
| FR-UI-01a | Every page shall have a **header command field** ("What do you need?") that takes the fixed commands of FR-CHAT and searches studies, pseudonyms and screening numbers. | S4 (split from FR-UI-01) | P-ENTRY | D | N | Absorbs FR-PLAT-14. |
| FR-UI-02 | Tiles in the "More" menu shall show only functions the user's role allows (AM-01), each with its count of pending items. | H (was M1) | P-ENTRY, D-104 | T | P (`/home` per role) |  |
| FR-UI-03 | The investigator study pages shall show per study: the feasibility report, the weekly list, and a patient page with per-criterion evidence and the mark actions of FR-SCR-07. | H (was M1) | D-104, F-05 | T | P (pages built; per-criterion cards partial) |  |
| FR-UI-04a | The coordinator home shall list the user's studies with pending items (new candidates, open reveals, jobs). | S4 (was M1) | D-104 | T | P |  |
| FR-UI-04b | The coordinator home shall show the tasks of FR-SCR-08, coming visits, and the pipeline found → contacted → consented → enrolled with a six-step procedure bar. | L (was M2) | report §UX, F-05 | T | N |  |
| FR-UI-05 | Every model output shown to a user shall be a card: proposal, evidence quote with date and source, state pill, one primary action, secondary actions (edit, reject, open source). The provenance line shows "from records" or "from note" with the note date only (FR-UI-17). | S2 (was M1) | report §UX, TB-REV-006c C-11 | I | P |  |
| FR-UI-06 | The primary action on a negative verdict shall be "Send to PI", never "Exclude". | S2 (was M1) | CON-05 | I | N |  |
| FR-UI-07 | Cards and lists shall be operable by keyboard: J/K move, A accept, E edit, R reject, Enter open. Fit: each listed key performs its action on every card list and patient list. | L (was M2) | report §UX | T | N |  |
| FR-UI-08a | Japanese sites shall show Japanese labels by default and Gregorian dates with optional 和暦 display. | H (was M1) | A12, A39 | T | P |  |
| FR-UI-08b | Taiwan sites shall show Traditional Chinese labels by default and Gregorian dates with optional 民國 year display. | H (was M1) | A12, A39 | T | P |  |
| FR-UI-09 | The PI patient list shall be readable on a phone 390 px wide without horizontal page scroll. | S0 (was M1) | D-102 | T | B | Data entry is desktop only. |
| FR-UI-10 | Roles below D4 (`auditor`, and `coordinator` / `investigator` before reveal) shall never be shown names or chart numbers in any view, export or notice; `viewer` and `cro` see D1 aggregates only. | H (was M1) | CON-06, AM-01 | T | P (built for coordinator, investigator, viewer, cro; `auditor` role is new, H) |  |
| FR-UI-11a | The admin pages shall show users and their roles, scopes and expiry. | S0 (was M1) | A23 | T | B (`/ops/users`) |  |
| FR-UI-11b | The admin pages shall show the models, their pins and the active policy in words (for the single-model policy: "single model: never excludes"). | H (was M1) | A23 | T | P |  |
| FR-UI-11c | The admin pages shall show ingest results (FR-ING-15) and job progress. | H (was M1) | A23 | T | P (`/jobs`) |  |
| FR-UI-11d | The admin pages shall show GPU, CPU, memory and disk use and the installed version. | H (was M1) | A23 | T | N |  |
| FR-UI-11e | The admin pages shall show the result of the last audit-chain verification and run one on demand. | H (was M1) | A23 | T | P (`/audit`, CLI) |  |
| FR-UI-11f | The admin pages shall export the diagnostics bundle (FR-OPS-05). | H (was M1) | A23 | T | N |  |
| FR-UI-12 | The intended-use statement ("research support; does not decide eligibility") shall appear in the footer of every page and on every report. | H (was M1) | NFR-COMP-04 | I | N |  |
| FR-UI-13 | Revealed chart numbers shall be shown on a view watermarked with user and time. | H (was M1) | SC-16, F-20 | T | P (reveal + audit built; reason, limit, watermark new) |  |
| FR-UI-13a | A revealed view shall hide the chart number again after 10 minutes. | H (split from FR-UI-13) | SC-16, F-20 | T | P |  |
| FR-UI-13b | A reveal shall require a reason. | H (split from FR-UI-13) | SC-16, F-20 | T | P |  |
| FR-UI-14 | Each role shall land on one home with the fixed ordering and exclusions of TB-DS-17 §3 (PI S16 "This week": decisions, this week's clinic candidates, waiting items, studies; CRC S8 "Today / This week"). | S4 (was M1) | TB-DS-17 §3 | D/I | N | The RA S17 data-status home is H. |
| FR-UI-14a | Every page shall carry the header command field of FR-UI-01. | S4 (split from FR-UI-14) | TB-DS-17 §3 | I | N |  |
| FR-UI-15 | The PI home and the PI list mail shall show, per study, candidates grouped as **Your clinic** (appointment practitioner = this PI) first, then **Other study doctors** (folded), then **Other doctors** (with Ask treating doctor, FR-SCR-07b), for that day or the next 7 days (FR-NOTIF-01), with one-tap marks (FR-SCR-07) and a link to the full study list sorted by next visit; usable on a 390 px phone (FR-UI-09) and at 480 px beside the EMR (FR-UI-19). | S4 (was M1) | TB-DS-17 §3.1, §5.1, TB-REV-006c C-13, C-20 | T | P (weekly list built) |  |
| FR-UI-16 | A patient in several studies shall appear once on a home or digest, with study badges. | S4 (was M1) | TB-DS-17 §5.4 | T | N |  |
| FR-UI-17 | No numeric score, probability, confidence or model name shall be shown to `investigator` or `coordinator` on any screen, list, mail or export. | S2 (was M1) | TB-DS-17 §3.1, H-02, TB-REV-006c C-11 | T | N (built page violates) | The built patient page shows `confidence` and `judge_model` today; removed in build step 2. `auditor` (H) also sees the footer. |
| FR-UI-17a | The model build and prompt version shall appear in the report footer for `admin` and in the audit record. | S2 (split from FR-UI-17) | TB-DS-17 §3.1, H-02, TB-REV-006c C-11 | T | N (built page violates) |  |
| FR-UI-18 | The coordinator home S8 shall have a **Marks today** pane, refreshed automatically (≤ 60 s, polling or SSE) while open, listing PI marks made today on patients with a visit today, for the study's coordinators **on duty** (a coordinator of the study whose S8 "I'm on duty today" toggle is on; one tap, default on, stored as `on_duty_date`, TB-DS-07); it sends no mail or push. | S4 (was M1) | TB-REV-006c C-14 | T | N |  |
| FR-UI-19 | The PI list (S16) shall also fit a clinic PC beside the EMR window (≤ 480 px wide) for sites where phones cannot reach the hospital network (TB-DS-15 PR-07). | S4 (was M1) | TB-REV-006c C-16 | D | N |  |

#### 3.1.13 CHAT — Fixed-command box

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-CHAT-01 | The command box shall recognise the fixed command grammar in JA, zh-TW and EN: feasibility for given criteria; patient list for a study; check a patient for a study; status of a job; help. Fit: on the command test set (≥ 50 phrasings per command per language) ≥ 95 % map to the right command and 0 % to a wrong command; the rest map to "not recognised". | S4 (was M1) | A19, P-ENTRY, F-29 | T | N | Phrasings are written by the builder from the TB-DS-09 §6 vocabulary; site staff add phrasings at install (H). |
| FR-CHAT-02 | One parser shall serve the command box and the e-mail grammar. | S4 (was M1) | A19 | I/T | P (mail grammar built) |  |
| FR-CHAT-03 | A recognised command shall start the job and open its normal page (report, list or cards). | S4 (was M1) | A19 | T | N |  |
| FR-CHAT-03a | The command box shall not produce free-text answers. | S4 (split from FR-CHAT-03) | A19 | T | N |  |
| FR-CHAT-04 | An unrecognised input shall show the tiles and up to three grammar examples closest by edit distance. | S4 (was M1) | A19, F-39 | T | N |  |
| FR-CHAT-04a | The system shall not start a job from an unrecognised input. | S4 (split from FR-CHAT-04) | A19, F-39 | T | N |  |
| FR-CHAT-05 | The command box shall never approve, exclude, save form values, reveal, or release. | S4 (was M1) | CON-02, SC-65 | T/I | N |  |
| FR-CHAT-06 | The command box shall act only within the user's role and study scopes (AM-01). | S4 (was M1) | SC-65 | T | N |  |
| FR-CHAT-07 | The grammar parser shall be replaceable by a model-based parser later without changing the job interface. | L (was C) | A19 | I | N |  |

#### 3.1.14 MAIL — E-mail channel

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-MAIL-01 | The system shall accept job requests by e-mail from allowlisted senders using the subject grammar and attachments, after SPF/DKIM/DMARC verification. | H (was M1) | [P1] §5, SC-45 | T | P (allowlist built; DMARC check new) |  |
| FR-MAIL-02 | Replies shall use outcome-first subjects "[STUDY] CMD kind: headline · job ID". | S2 (was M1) | D-88 | T | B |  |
| FR-MAIL-03 | Mail shall never carry D4 data: no chart numbers or names in bodies or attachments. | S2 (was M1) | BD-04, F-17 | T | P (built mail allows encrypted identified attachments; to be removed) |  |
| FR-MAIL-03a | Patient lists by mail shall carry pseudonyms only, with identified views reached by a link to the on-prem web page after login and reveal. | S2 (split from FR-MAIL-03) | BD-04, F-17 | T | P |  |
| FR-MAIL-04 | Mail shall be in the requester's language. | S2 (was M1) | D-100 | T | B |  |
| FR-MAIL-05 | The mail channel shall carry signed hub messages when no direct link exists (FR-FED-05). | L (was M2) | report §Cross-site | T | N |  |
| FR-MAIL-06 | Outbound recipients shall be allowlisted per study. | H (was M1) | SC-46 | T | P |  |
| FR-MAIL-06a | Outbound attachments shall be only D1 (aggregates, suppressed per N-01) or D3 pseudonymised lists, and D3 lists only to internal recipients. | H (split from FR-MAIL-06) | SC-46 | T | N |  |

#### 3.1.15 AUTH — Accounts, roles, 2FA, sessions

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-AUTH-01a | The system shall provide console-native local accounts with salted, memory-hard password hashes. | S0 (was M1) | BD-01 | T | B | Mechanism: scrypt (built). |
| FR-AUTH-01b | Every interactive login (console, study pages, admin) shall require a TOTP second factor (RFC 6238). | H (was M1) | BD-01, [S12], SC-10 | T | N | EDC-lite logins (L) are included when EDC-lite exists. WebAuthn can be offered in addition. |
| FR-AUTH-01c | A trusted-header SSO login shall satisfy the second factor only where the hospital proxy enforces its own MFA, recorded per proxy in the site configuration. | H (split from FR-AUTH-01b) | BD-01, [S12], SC-10 | T | N |  |
| FR-AUTH-02 | The system shall provide exactly the roles `admin`, `coordinator`, `investigator`, `viewer` and `cro`. | S0 (was M1) | BD-03, D-93 | T | B | The sixth role, `auditor`, is H (BD-03). |
| FR-AUTH-02a | Each account shall carry its study scopes, an affiliation (`hospital`, `smo` or `cro`) and an expiry date. | S0 (split from FR-AUTH-02) | D-101, D-104 | T | B |  |
| FR-AUTH-03 | The system shall accept REDCap users through the External Module: the module passes the REDCap username and project, and the appliance maps them to a TrialBox account with that project's study scope. | L (was M2) | A13 | T | N |  |
| FR-AUTH-04 | When the hospital-IdP setting is on, the system shall authenticate users through the hospital IdP via OIDC or SAML 2.0 (Keycloak as fallback broker). | L (was C) | A13, BD-01 | T | P (trusted-header SSO built) |  |
| FR-AUTH-04a | When the hospital-IdP setting is on, the admin shall be able to disable local passwords for mapped users. | L (split from FR-AUTH-04) | A13, BD-01 | T | P |  |
| FR-AUTH-05a | A session shall end after 30 minutes without activity (N-05). | S0 (was M1) | N-05 | T | B |  |
| FR-AUTH-05b | A session shall end 8 hours after login whatever the activity (N-05). | S0 (was M1) | N-05 | T | B |  |
| FR-AUTH-05c | A revealed chart number shall be hidden again after 10 minutes on screen, independent of the session (FR-UI-13). | H (was M1) | SC-16 | T | N |  |
| FR-AUTH-05d | The system shall ask for a **TOTP code only** (no password) once per session before the first of: a reveal, a ruleset approval, a sponsor-pack release, an approval-record confirmation; later ones in the same session (N-05) need none, and a step-up within 15 minutes of login is skipped. Account, role and scope changes by `admin` always ask for the TOTP code (BD-17). | H (was M1) | SC-12, F-20, BD-17, TB-REV-006c C-08 | T | N |  |
| FR-AUTH-06 | An account shall lock for 15 minutes after 5 failed logins within 15 minutes (N-06). | S0 (was M1) | N-06, F-35 | T | B |  |
| FR-AUTH-06a | Every account lock shall be audited. | S0 (split from FR-AUTH-06) | N-06, F-35 | T | B |  |
| FR-AUTH-07 | The system shall provide machine credentials for the REDCap module and the hub, scoped per project or site and rotatable by the admin. | L (was M2) | SC-13 | T | N |  |
| FR-AUTH-08 | Account changes (create, role change, scope change, disable, password reset) shall require the `admin` role and the re-authentication of FR-AUTH-05d, and be audited. | H (was M1) | [S9] A.5.18 | T | P (admin + audit built) |  |
| FR-AUTH-09 | The system shall produce a monthly access report for the admin: every account, role, scopes, affiliation, last login, expiry, and accounts with no login for 90 days. | H (was M1) | SC-18, [S9] A.5.18 | T | N |  |
| FR-AUTH-10 | Passwords shall be at least 12 characters. | H (was M1) | SC-15, F-20 | T | P (12 characters built) |  |
| FR-AUTH-10a | A password that appears on the configured breached-password list (offline file supplied by hospital IT) shall be rejected. | H (split from FR-AUTH-10) | SC-15, F-20 | T | P |  |
| FR-AUTH-11 | `cro` accounts shall be disabled by default. | H (was M1) | BD-03, F-54 | T | P (role built; site switch new) |  |
| FR-AUTH-11a | An admin shall be able to enable `cro` accounts for a site only after recording the approving `investigator`. | H (split from FR-AUTH-11) | BD-03, F-54 | T | P |  |
| FR-AUTH-11b | A `cro` account shall see D1 aggregates only. | H (split from FR-AUTH-11) | BD-03, F-54 | T | P |  |
| FR-AUTH-12 | The site shall be able to hold one sealed break-glass admin account whose use needs two people. | L (was M2) | SC-17 (gate Y1), F-20 | T/D | N |  |
| FR-AUTH-12a | Each use of the break-glass account shall alert the site security owner. | L (split from FR-AUTH-12) | SC-17, F-20 | T | N |  |
| FR-AUTH-12b | Each use of the break-glass account shall be listed for review within 24 h. | L (split from FR-AUTH-12) | SC-17, F-20 | T | N |  |
| FR-AUTH-13 | Only an `investigator` with the study in scope shall be able to approve a ruleset for that study. | S2 (was M1) | BD-13 (proposed), R2-02 | T | N | Built behaviour differs: `admin` and `coordinator` can approve through `can_request`; changed in build step 2. |
| FR-AUTH-13a | A `coordinator` with the study in scope shall be able to prepare and submit the review workbook. | S2 (split from FR-AUTH-13) | BD-13 (proposed), R2-02 | T | N |  |
| FR-AUTH-13b | An `admin` shall not be able to approve a ruleset. | S2 (split from FR-AUTH-13) | BD-13 (proposed), R2-02 | T | N |  |

#### 3.1.16 AM-01 — Role × data class × action matrix

AM-01 is one requirement: the system shall enforce this matrix, deny every combination not marked, and an automated test shall exercise every cell (SC-14). Pri S0 for the built cells, H for `auditor` cells; Ver T. Data classes per CON-14. "Scope" = only for studies in the account's scope. "B" = built at `a1e55fa`, "N" = new.

| Action (data class) | admin | coordinator | investigator | viewer | auditor | cro |
| --- | --- | --- | --- | --- | --- | --- |
| View aggregate reports, funnels (D1) | Yes | Scope | Scope | Scope (B) | Scope | Scope, sponsor form k = 10, if enabled (FR-AUTH-11) |
| View pseudonymised lists, evidence quotes, CASE sheets (D3) | No (N; built allows) | Scope (B) | Scope (B) | No (B) | Scope (N) | No (B) |
| Reveal chart number (D4), with reason (FR-UI-13) | No (N; built allows) | Scope (B) | Scope (B) | No | No | No |
| Start FEAS / SCREEN / CASE (D3 processing) | No (N; built allows) | Scope (B) | Scope (N) | No | No | FEAS with D1 output only, if enabled (N) |
| Approve a ruleset, one page (BD-13; FR-AUTH-13, FR-FEAS-12) | No (N; built allows) | Prepare and submit only (N; built allows approval) | Scope (N) | No | No | No |
| Pre-tick a ruleset's code mapping, recorded as its own audit event (BD-13) | No | Scope (N) | Scope (N) | No | No | No |
| Mark patient approach / need info / not suitable | No | No | Scope (B) | No | No | No |
| Mark "Ask treating doctor" (FR-SCR-07b) | No | No | Scope (N) | No | No | No |
| Record contact outcome (FR-SCR-10c) | No | Scope (N) | Scope (N) | No | No | No |
| Edit study set-up S21 (FR-STUDY-07) | Scope assignment only, on request | Scope (N) | Scope (N) | No | No | No |
| Edit S21 sections 1, 3, 4, 5, 8 for all studies; read 2, 6–7 (FR-STUDY-10) | `office` flag on any account role (N) | `office` flag (N) | `office` flag (N) | `office` flag (N) | No | No |
| Enter ethics approval record and upload approved explainer file (FR-CON-06, 09) | No | Scope (N) | Scope (N) | No | No | No |
| Confirm approval record and study team (FR-CON-06, FR-STUDY-07) | No | No | Scope (N) | No | No | No |
| Record sponsor approval of patient material (FR-CON-10) | No | Scope (N) | Scope (N) | No | No | No |
| Annual progress-report export (FR-REP-09, D1 internal) | No | Scope; `office` flag all studies (N) | Scope (N) | No | Scope | No |
| Release sponsor pack outside the site (D1) | No | No (N; built: requester downloads the pack) | Scope (N) | No | No | No |
| Release consent explainer | — (no Release action; goes live automatically when the approval record is complete, FR-CON-06, BD-15) | — | — | — | — | — |
| Switch the consent explainer off (FR-CON-07) | Site setting | Scope | Scope | No | No | No |
| Export screening log with chart numbers (D4, inside the box) | No | Scope | Scope | No | No | No |
| Export screening log pseudonymised (D3) | No | Scope | Scope | No | Scope | No |
| Accept / edit / reject pre-fill value (L, D4) | No | Scope | Scope | No | No | No |
| Dismiss AE suggestion, with reason (L) | No | No | Scope | No | No | No |
| See / prepare AE suggestion (L) | No | Scope | Scope | No | No | No |
| Approve cross-site query (L) | No | No | Scope | No | No | No |
| Manage accounts, ingest, updates, models (D1) | Yes | No | No | No | No | No |
| Read and export audit records (D3) | Yes | No | No | No | Yes | No |
| Export diagnostics bundle (D1 after PHI scan) | Yes | No | No | No | No | No |

Built behaviour checked in `services/console/auth.py` (`can_request` = admin, coordinator; `can_view_phi` = admin, coordinator, investigator; `can_mark` = investigator; `aggregate_only` = viewer, cro) and `home.py` (reveal by coordinator and investigator, D-104). Differences to close (build step 2, and H for `auditor`): `admin` may start jobs and read D3 today; investigators cannot start jobs or approve rulesets today; the sponsor pack has no investigator release step; there is no `auditor`.

#### 3.1.17 AUD — Audit

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-AUD-01a | Every job state change and every output file shall be recorded in the append-only hash-chained audit log. | S5 (was M1) | [P1] §10.2, SC-70 | T | B |  |
| FR-AUD-01b | Every chart-number reveal shall be recorded with user, study, pid, reason and time. | S5 (was M1) | SC-16 | T | P (reason new) |  |
| FR-AUD-01c | Every login, failed login, lockout and logout shall be recorded. | H (was M1) | SC-70 | T | P |  |
| FR-AUD-01d | Every account, role, scope and expiry change shall be recorded. | S0 (was M1) | SC-70 | T | B |  |
| FR-AUD-01e | Every investigator mark and registry status change shall be recorded. | S5 (was M1) | D-104 | T | B |  |
| FR-AUD-01f | Every ruleset approval (with the coordinator's code pre-check recorded as its own event), sponsor-pack release, explainer approval-record entry, confirmation, file version and automatic go-live or withdrawal shall be recorded with the approval record. | H (was M1) | D-101, BD-15 | T | P |  |
| FR-AUD-01g | Every configuration change and installed update shall be recorded. | H (was M1) | SC-70 | T | P |  |
| FR-AUD-01h | Every REDCap read (project, method, record count) shall be recorded. | H (was M1) | SC-70 | T | N |  |
| FR-AUD-01i | Every pre-fill accept / edit / reject and REDCap write shall be recorded. | L (was M2) | SC-70 | T | N |  |
| FR-AUD-01j | Every AE suggestion dismissal shall be recorded with reason. | L (was M2) | BD-08 | T | N |  |
| FR-AUD-01k | Every hub message sent or received shall be recorded. | L (was M2) | FR-FED | T | N |  |
| FR-AUD-02 | Audit records shall contain no data above D3 (pseudonyms only). | S0 (was M1) | [P1] §10.1 | T/I | B |  |
| FR-AUD-03 | The system shall verify the audit chain at start and nightly and alert the admin on failure. | H (was M1) | SC-71 | T | P (on-demand tool built) |  |
| FR-AUD-03a | The admin shall be able to verify the audit chain on demand. | H (split from FR-AUD-03) | SC-71 | T | P |  |
| FR-AUD-04 | Audit records shall be retained for 10 years (N-02). | S0 (was M1) | N-02, F-09 | I | B |  |
| FR-AUD-05 | The `auditor` role shall search and export audit records by date, user, study and event type. | H (was M1) | [S10], BD-03 | T | N |  |
| FR-AUD-06 | The system shall store the hub's countersignatures of daily chain heads (FR-FED-06). | L (was M2) | SC-72 | T | N |  |
| FR-AUD-07 | On a single-site box the daily chain head shall be included in the weekly admin mail, so later tampering is detectable from mail archives outside the box. | H (was M1) | SC-72, F-20 | T | N |  |

#### 3.1.18 SEC — Security controls owned by TB-DS-03 (hospital stage unless tagged otherwise)

These rows make the TB-DS-03 controls with pilot gate "Yes" testable from the SRS. Where a control is fully covered by a row elsewhere, that row is listed instead of a new one.

| ID | Requirement | SC | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FR-SEC-01 | All appliance data volumes shall be encrypted at rest (mechanism: CON-18). | SC-20 | H (was M1) | [P7] §1 | T | P (documented, not enforced, F-36) |  |
| FR-SEC-01a | Where a TPM 2.0 exists, the disk key shall be sealed to it. | SC-20 | H (split from FR-SEC-01) | [P7] §1 | T | N |  |
| FR-SEC-01c | Where no TPM 2.0 exists, a passphrase held by hospital IT shall be required at boot. | SC-20 | H (split from FR-SEC-01a) | [P7] §1 | T | N |  |
| FR-SEC-01b | The installer shall check and report the encryption state. | SC-20 | H (split from FR-SEC-01) | [P7] §1 | T | N |  |
| FR-SEC-02 | The HMAC site key and the pid-map key shall be generated on the appliance, stored root-only (0600), sealed with `systemd-creds` to the TPM where one exists, and never exported except in the encrypted backup. | SC-21, SC-22 | H (was M1) | [P7] §2 | T/I | P (documented, not enforced) |  |
| FR-SEC-03 | Internal links that cross a host boundary shall use TLS 1.2 or later (1.3 preferred). | SC-23 | H (was M1) | [S15] | T | P |  |
| FR-SEC-04 | Update and model bundles shall be signed. | SC-41 | H (was M1) | [P1] §10.1 | T | B (bundle signing) |  |
| FR-SEC-04a | The importer shall verify a bundle's signature and hashes and refuse a bundle that does not match. | SC-41 | H (split from FR-SEC-04) | [P1] §10.1 | T | B (bundle signing) |  |
| FR-SEC-05 | The diagnostics bundle shall contain allowlisted content only. | SC-43 | H (was M1) | F-20 | T | N | Hospital IT reviews the bundle before it leaves the site; that review is a release step, recorded in TB-DS-04 §9.5, not a system requirement. |
| FR-SEC-05a | The diagnostics bundle shall pass the PHI scan of the FR-DEID-05 rules with zero hits before it can be exported. | SC-43 | H (split from FR-SEC-05) | F-20 | T | N |  |
| FR-SEC-06 | Remote support shall be possible only as a hospital-initiated, supervised, recorded screen-share. | SC-44 | H (was M1) | CON-09 | I | B (no remote access) |  |
| FR-SEC-06a | The appliance shall have no standing VPN and no inbound support port. | SC-44 | H (split from FR-SEC-06) | CON-09 | I | B (no remote access) |  |
| FR-SEC-07 | Every outbound file (mail attachment, download leaving the site, sponsor pack) shall pass an output classifier that blocks the file if it contains a pid, chart number or name (FR-DEID-05 rules), and records the block. | SC-51 | H (was M1) | F-20 | T | N |  |
| FR-SEC-08 | Prompts shall be fixed, versioned files. | SC-61 | H (was M1) | FR-MOD-09 | I | P |  |
| FR-SEC-08a | Patient text shall enter a prompt only inside a delimited data field. | SC-61 | H (split from FR-SEC-08) | FR-MOD-09 | I | P |  |
| FR-SEC-09 | The model runtime shall run on its own network without egress, with read-only weights and no tools or function calls to the outside. | SC-64 | H (was M1) | D-95 | T | B (compose) |  |
| FR-SEC-10 | CI shall run an injection suite of at least 50 adversarial notes in JA, zh-TW and EN. | SC-67 | H (was M1) | F-20 | T | N |  |
| FR-SEC-10a | Any change of verdict caused by injected text shall fail the build. | SC-67 | H (split from FR-SEC-10) | F-20 | T | N |  |
| FR-SEC-11 | Withdrawn as a duplicate: the requirement is project obligation PO-01 (§2.7, third-party penetration test before go-live). This row is kept only as a pointer for SC cross-references. | — | — (was H) | R2-15 | — | W |  |
| FR-SEC-12 | The PHI pass shall not ship unless it meets NFR-PERF-14 on the pre-pilot gate set (MedTxt + 200 hospital notes per site). | SC-60 | H (was M1) | N-07 | T | N |  |
| FR-SEC-13 | Egress shall be deny-by-default per container, with an allowlist. | SC-64 | H (was M1) | [P1] §10 | T | B (nftables) |  |
| FR-SEC-13a | Every egress denial shall be logged. | SC-64 | H (split from FR-SEC-13) | [P1] §10 | T | B (nftables) |  |

Covered elsewhere: SC-10 → FR-AUTH-01b; SC-11, SC-14 → AM-01; SC-12 → FR-AUTH-05a–d; SC-13 → FR-RC-01, FR-AUTH-07; SC-15 → FR-AUTH-10; SC-16 → FR-UI-13, FR-AUD-01b; SC-18 → FR-AUTH-09; SC-29 → FR-ING-17; SC-30 → FR-DEID-01; SC-31 → FR-DEID-04; SC-32 → FR-ING-10; SC-33 → FR-ING-08b; SC-34 → FR-ING-18; SC-36 → FR-SCR-01 (S0); SC-40 → DR-04; SC-42 → FR-MOD-05; SC-45 → FR-MAIL-01; SC-46 → FR-MAIL-06; SC-50 → FR-DEID-11a/b; SC-54 → FR-FEAS-08; SC-62 → FR-SCR-06; SC-63 → FR-SCR-05; SC-65 → FR-CHAT-05/06; SC-66 → FR-MOD-06; SC-70 → FR-AUD-01a–k; SC-71 → FR-AUD-03; SC-72 → FR-AUD-07, FR-FED-06; SC-73 → FR-AUD-04, NFR-COMP-05; SC-75 → FR-OPS-04, FR-OPS-08. Organisational controls SC-01..05 are TB-DS-03 obligations with no software requirement.

#### 3.1.19 ERR — Errors, idempotency and concurrency

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-ERR-01 | A job interrupted at any point (process kill, power loss) shall resume or restart with no duplicated step and exactly one delivered message per outbound item. | H (was M1) | F-49, FR-WF-1 (spec v4) | T | P |  |
| FR-ERR-02 | A user shall be able to cancel a running job they started; an `admin` can cancel any job. | H (was M1) | F-49 | T | N |  |
| FR-ERR-02a | A cancelled job shall stop at the next step boundary, release the GPU, deliver no output and be audited. | H (split from FR-ERR-02) | F-49 | T | N |  |
| FR-ERR-03 | The same e-mail request delivered twice (same Message-ID) shall start one job only. | H (was M1) | F-49 | T | P |  |
| FR-ERR-04 | A failed ingest shall leave the previous snapshot current. | S0 (was M1) | [P2] §3 | T | B |  |
| FR-ERR-04a | A failed ingest shall alert the admin (FR-OPS-08). | S0 (split from FR-ERR-04) | [P2] §3 | T | B |  |
| FR-ERR-05 | When two users act on the same pre-fill field at the same time, the system shall keep the first accepted value. | L (was M2) | F-49 | T | N |  |
| FR-ERR-05a | When two users act on the same pre-fill field at the same time, the system shall show the second user the conflict with both values. | L (split from FR-ERR-05) | F-49 | T | N |  |
| FR-ERR-06 | A REDCap write that fails (network, rights, validation) shall leave the card in "not saved" with the REDCap error text. | L (was M2) | F-49 | T | N |  |
| FR-ERR-06a | A failed REDCap write shall be retried only on user action. | L (split from FR-ERR-06) | F-49 | T | N |  |
| FR-ERR-06b | A failed REDCap write shall leave no partial record in REDCap. | L (split from FR-ERR-06) | F-49 | T | N |  |
| FR-ERR-07 | A Data Entry Trigger call replayed outside a 5-minute window or with a reused nonce shall be refused and audited. | L (was M2) | SC-47, SC-49 | T | N |  |
| FR-ERR-08 | Every error shown to a user shall state what failed, whether data was changed, and what to do next, in the user's language. | H (was M1) | [S14] | I | P |  |

#### 3.1.20 LOG — Time, logs and export hygiene

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-LOG-01 | The appliance clock shall synchronise with the hospital NTP server. | H (was M1) | F-49, [S12] | T | N |  |
| FR-LOG-01a | A clock drift above 2 s shall raise an admin alert. | H (split from FR-LOG-01) | F-49, [S12] | T | N |  |
| FR-LOG-01b | Audit timestamps shall be stored in UTC. | H (split from FR-LOG-01) | F-49, [S12] | T | N |  |
| FR-LOG-01c | The UI shall show audit timestamps in the site time zone. | H (split from FR-LOG-01b) | F-49, [S12] | T | N |  |
| FR-LOG-02 | Application and container logs shall contain no data above D3. Fit: a planted-identifier test finds zero identifiers in them. | H (was M1) | LLM-45 (spec v4) | T | P |  |
| FR-LOG-02a | Application and container logs shall rotate by size. | H (split from FR-LOG-02) | LLM-45 (spec v4) | T | N |  |
| FR-LOG-03 | Exports leaving the box (XLSX, CSV, PDF) shall be written to an encrypted download store. | H (was M1) | F-49, SC-16 | T | N |  |
| FR-LOG-03b | The user shall be able to remove their own exports from the download store. | H (split from FR-LOG-03) | F-49, SC-16 | T | N |  |
| FR-LOG-03a | D4 exports shall carry a watermark with user and time. | H (split from FR-LOG-03) | F-49, SC-16 | T | N |  |
| FR-LOG-04 | Generated PDFs shall be tagged PDF with document language set and reading order, so that screen readers can read them. | L (was M2) | F-49, [S14] | T | N |  |

#### 3.1.21 MOD — Models, GPU scheduling and model gates

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-MOD-01 | Every model call shall be served by a model running on the appliance. Fit: with all egress blocked, every model function works. | S0 (was M1) | D-95 | T | B | Serving engine: CON-17. Builds: CON-12. |
| FR-MOD-02 | On a one-GPU box the scheduler shall load models by the BD-11 windows: judge loaded by day; PHI tagger 23:30–02:00; judge then verifier 02:00–05:30; without manual action. | H (was M1) | P-HW, BD-10, BD-11 | T | N |  |
| FR-MOD-03 | On a two-GPU box the judge shall run on one card and the verifier and PHI tagger on the other. | H (was M1) | BD-10 (CGMH) | T | N |  |
| FR-MOD-04 | An interactive request arriving while a batch model holds the GPU shall be queued. | H (was M1) | A20 | T | N |  |
| FR-MOD-04b | The user shall be shown the expected wait for a queued request. | H (split from FR-MOD-04) | A20 | T | N |  |
| FR-MOD-04a | Batch work shall yield the GPU to queued interactive work between batches during the day window (BD-11). | H (split from FR-MOD-04) | A20 | T | N |  |
| FR-MOD-05 | Every model call shall be schema-constrained and record model build, prompt version and output hash. | S0 (was M1) | [P1] §7, SC-42 | T | B |  |
| FR-MOD-06 | Every model, prompt or quantisation change shall pass the model gate (NFR-PERF-08..10, 14) before release. | H (was M1) | D-96, D-103, SC-66 | T | P |  |
| FR-MOD-06a | An approved ruleset shall record the judge prompt version it was approved with. | H (split from FR-MOD-06) | D-96, D-103, SC-66 | T | N |  |
| FR-MOD-07 | The admin shall be able to switch off each optional module (verifier, EDC pre-fill, TC suggestions). | H (was M1) | P-HW | T | P | EDC pre-fill and TC suggestions are L; their switches appear when they are built. |
| FR-MOD-07a | The admin page shall state in words the policy that results from the modules switched on (FR-UI-11b). | H (split from FR-MOD-07) | P-HW | T | P |  |
| FR-MOD-08 | Model weights shall be loaded only from signed bundles, pinned by hash. | S0 (was M1) | [P1] §10.1, SC-41 | T | B |  |
| FR-MOD-09 | Prompts shall be stored as versioned files readable by an ethics committee. | S0 (was M1) | report §OpenMausBot | I | B |  |
| FR-MOD-09a | At run time the system shall change prompt text only by filling the prompt's defined slots. | S0 (split from FR-MOD-09) | report §OpenMausBot | I | B |  |
| FR-MOD-10 | Step 5 shall measure on a real 32 GB RTX 5090 whether the judge + verifier pair fits in the time-shared mode (memory, context, sequences, swap time) and record the result and the full serving configuration (model files with sha256, quantisation, vLLM version, `max-model-len`, `max-num-seqs`, `gpu-memory-utilization`, KV dtype) in TB-DS-02 ADR-03 and NFR-PERF-08. Fit: the record exists and N-11 passes in EN, JA and zh-TW on the deployed files. | S5 (new) | TB-REV-006f F6-12 | A/T | N | Moved from the FR-SEC table (TB-REV-006g Q-02). Order of attempts (TB-REV-006f §8.5): (1) time-shared, vLLM sleep mode or stop-start between night passes; (2) both resident with recorded per-container memory caps; (3) QAT Gemma build or 4k context only if (1) and (2) fail; fallback 2 × RTX 5090. Unit: GiB as printed by `nvidia-smi` (32 GB card = 29.8 GiB). |

#### 3.1.22 JP — Japanese and Taiwanese clinical conventions

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-JP-01 | The system shall normalise 和暦 (令和, 平成, 昭和, including kanji numerals and 元年) and 民國 dates to ISO 8601 at ingest. | S4 (was M1) | A12 | T | N |  |
| FR-JP-02 | The system shall apply NFKC and full-/half-width unification to identifiers, codes and text before matching. | S4 (was M1) | A12 | T | P |  |
| FR-JP-03 | The system shall read the 疑い (suspected) and other modifiers of 標準病名マスタ. | H (was M1) | A12, D-96 | T | P (judge v4 prompt) |  |
| FR-JP-03a | The system shall not treat a diagnosis flagged 疑い as confirmed. | H (split from FR-JP-03) | A12, D-96 | T | P |  |
| FR-JP-04 | The system shall not exclude on a diagnosis code alone when the code may be an insurance-only diagnosis (保険病名); a supporting finding or a main-diagnosis flag is required, otherwise the patient goes to review. | H (was M1) | A12 | T | N |  |
| FR-JP-05 | The system shall map 標準病名 to ICD-10, YJ/HOT drug codes to ingredients, and JLAC10/JLAC11 lab codes to LOINC, with unit conversion tables, versioned per release (terminology table in TB-DS-02). | H (was M1) | A12, F-33 | T/I | N |  |
| FR-JP-06 | The system shall provide a per-site abbreviation lexicon, seeded with at least s/o, r/o, #, Ope, used by note search and the site rule book. Fit: on the site's abbreviation test list, note search finds ≥ 95 % of the planted abbreviations. | L (was M2) | A12, F-29 | T | N |  |
| FR-JP-07 | The system shall read coded functional status where present: 要介護度, 障害高齢者の日常生活自立度, 認知症高齢者の日常生活自立度. | L (was M2) | A12 | T | N |  |
| FR-JP-08 | The system shall apply Taiwan conventions: read NHI drug and order codes, validate resources against TW Core profiles, and display dates in the ROC calendar when the site setting asks for it. Fit: on the Taiwan-style synthetic fixture (TB-DS-21) every NHI code maps without error, every resource validates against TW Core, and the feasibility report and patient list show ROC dates when the setting is on. | S4 (was M1) | A12 | T | P | Filed under JP for ID stability; it is the Taiwan counterpart of FR-JP-01..07. |
| FR-JP-09 | Each site shall have a rule book (site instructions to the judge) that is versioned, reviewable and at most 2,000 characters. | L (was M2) | report §Japanese customs | I | N |  |

#### 3.1.23 I18N — Languages

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-I18N-01 | The UI, mail, reports and PDFs shall be available in Japanese, Traditional Chinese and English. | S4 (was M1) | D-100, A39 | T | B |  |
| FR-I18N-02 | Patient-facing materials shall be available in every language configured for the site. | S4 (was M1) | A39 | T | P |  |
| FR-I18N-02a | Adding a language shall need translation files only, without code changes. | S4 (split from FR-I18N-02) | A39 | T | P |  |
| FR-I18N-03 | Criteria and notes in Japanese, Chinese and English shall be processed without first translating them. | S4 (was M1) | report §Models | T | B |  |
| FR-I18N-04 | Machine-translated patient material shall be marked as a draft for ethics-committee review (FR-CON-01). | S4 (was M1) | BD-15 | I | P |  |
| FR-I18N-04a | Only the committee-approved file of translated patient material shall go live (FR-CON-06). | S4 (split from FR-I18N-04) | BD-15 | I | P |  |

#### 3.1.24 OMOP — OMOP export (L)

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-OMOP-01 | The system shall export the lake to OMOP CDM v5.4 tables following the HL7 FHIR-to-OMOP IG, as a nightly job when enabled. | L (was C) | A7 | T | N |  |
| FR-OMOP-02 | The data model shall keep source and standard codes side by side so the export can be added without migrating stored data. | H (was M1) | A7 | I | P |  |
| FR-OMOP-03 | The export shall run the OHDSI Data Quality Dashboard checks and attach the result. | L (was C) | report §OMOP | T | N |  |
| FR-OMOP-04 | The export shall carry pid as person_source_value and apply the N-08 date shift when it leaves the site. | L (was C) | N-08 | T | N |  |

#### 3.1.25 OPS — Installation, update, monitoring, backup, support

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-OPS-01 | The system shall install from an offline signed bundle with one command (`install.sh`), detecting the GPU profile. | S0 (was M1) | D-94, D-95 | D | B |  |
| FR-OPS-02 | The appliance shall refuse unsigned or tampered update bundles. | S0 (was M1) | [P1] §10.1 | T | B |  |
| FR-OPS-03 | The admin shall be able to roll back to the previously installed version with one action, keeping data. | H (was M1) | A23 | T | N |  |
| FR-OPS-04 | The system shall provide a health page: last ingest, job queue, night-job progress, GPU, CPU, memory and disk use, certificate expiry, version, last audit verification. | H (was M1) | A23, SC-75 | T | P (`/healthz`) |  |
| FR-OPS-05 | The admin shall be able to export a diagnostics bundle (logs, metrics, configuration without secrets) under FR-SEC-05. | H (was M1) | A23, SC-43 | T/I | N |  |
| FR-OPS-06 | The system shall back up configuration, pid map, rulesets, registry and audit nightly to an encrypted hospital share, meeting RPO 24 h (N-15). | H (was M1) | N-15 | T | P | EDC-lite data joins the backup set at L. |
| FR-OPS-06a | The restore procedure shall be documented. Fit: a restore that follows the document onto a blank box passes `e2e_simple`. | H (split from FR-OPS-06) | N-15 | T/I | P |  |
| FR-OPS-07 | The first job on each box shall be a full-size dry run (all studies, all patients) that reports duration and resource use (N-18). | H (was M1) | N-18 | D | N |  |
| FR-OPS-08 | The system shall alert the admin by e-mail on: ingest failure, night-job overrun of a BD-11 window, disk above 80 %, audit verification failure, certificate expiry within 30 days, clock drift (FR-LOG-01). | H (was M1) | A23, SC-75 | T | P |  |
| FR-OPS-09 | No inbound remote access shall be enabled by default (FR-SEC-06). | S0 (was M1) | CON-09 | I | B |  |
| FR-OPS-10 | The retention job shall delete expired attachments (90 d) and outputs (365 d) and record each deletion in the audit log. | S0 (was M1) | D-78 | T | B |  |
| FR-OPS-11 | `e2e_simple` (TB-DS-04 §3.4.1) shall run on every build: one synthetic site, FEAS → report → approve → SCREEN → list → N1/N2 mail → REDCap simulator read-back → screening log. | S5 (new) | TB-REV-006f F6-13 | T | N | It is the only build gate (TB-DS-00 §2). |
| FR-OPS-12 | The night schedule (BD-11) shall be a site setting, defaulting to on demand ("Run ingest now" and job buttons) with `TB_ENV=DEV` or `TEST`. | S1 (new) | TB-REV-006f F6-30 | T | P (button built) |  |

#### 3.1.26 REP — Reports

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-REP-01 | Every report shall carry: study, ruleset version, snapshot date, data sources, model builds and prompt versions, pinned run clock, job ID, page numbers, language. | S5 (was M1) | D-101 | T | B |  |
| FR-REP-02 | Re-running a job with the same inputs and versions shall give byte-identical outputs. | S5 (was M1) | D-82 | T | B |  |
| FR-REP-03 | Reports leaving the site shall be D1 with k = 10 (N-01) and released only after `investigator` approval (FR-FEAS-08). | H (was M1) | A36, A37, N-01 | T | P |  |
| FR-REP-04a | The system shall produce a pilot metrics report per study: feasibility turnaround, pooled and per-study recall against the manual chart review with Wilson 95 % bounds (N-16), and every missed patient with its reason. | H (was M1) | A42, A43, N-16 | T | N |  |
| FR-REP-04b | The pilot metrics report shall show criterion-level agreement between TrialBox and the reviewers (per criterion: agreement rate and Cohen's kappa). | H (was M1) | F-61 | T | N |  |
| FR-REP-04c | The pilot metrics report shall show pre-screen time against the site baseline (N-17). | H (was M1) | N-17 | T | N |  |
| FR-REP-04d | The report shall add acceptance and edit rates per pre-fill field. | L (was M2) | N-09 | T | N |  |
| FR-REP-05 | The system shall produce a sponsor / CRA monitoring view for `cro`: counts per stage, screen-failure reasons, enrolment against forecast and open-query counts, aggregates only with k = 10 (N-01, BD-03); no patient-level rows. | L (was C) | report §Trial conduct, TB-DS-17 §8 | T | N |  |
| FR-REP-06 | The system shall show a site monitoring view per study for `investigator` and `coordinator`: screening log (FR-SCR-10a), funnel found → contacted → consented → enrolled, and enrolment against the feasibility forecast (forecast parameters editable by the PI). | H (was M1) | TB-DS-17 §8 | T | N |  |
| FR-REP-07 | The system shall list unverified fields per form and per study from REDCap form status, for the CRC's monitoring preparation. | L (was M2) | TB-DS-17 §8 | T | N |  |
| FR-REP-08 | The system shall show protocol-deviation hints as cards with evidence (visit out of window, consent date after first procedure, criterion not met at enrolment by the record, prohibited con-med). | L (was M2) | TB-DS-17 §8 | T | N |  |
| FR-REP-08a | A protocol-deviation hint shall never create a deviation report. | L (split from FR-REP-08) | TB-DS-17 §8 | T | N |  |
| FR-REP-09 | The system shall export, per study and reporting year, the counts the research office needs for the annual progress report (実施状況報告 / IRB 期中報告): listed, pre-screened, approached, consented, screen-failed with reason categories, enrolled, withdrawn, from the screening log and REDCap reads; k = 5 inside the site (N-01); SAE counts are taken from REDCap where the study records them there. | S2 (was M1) | TB-REV-006c C-18 | T | N |  |

#### 3.1.27 STUDY — Registries and observational studies

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-STUDY-01 | A study shall have one type: interventional trial, registry, or observational study. | S2 (was M1) | TB-DS-17 §4.2, owner request 2026-11-07 03:04 | T | N |  |
| FR-STUDY-01a | For registry and observational studies whose consent scope is opt-out or waiver, the cascade shall skip the contact steps. | S2 (split from FR-STUDY-01) | TB-DS-17 §4.2, owner request 2026-11-07 03:04 | T | N |  |
| FR-STUDY-01b | For registry and observational studies whose consent scope is opt-out or waiver, the cascade shall still apply S0 "do not use" preferences. | S2 (split from FR-STUDY-01a) | TB-DS-17 §4.2, owner request 2026-11-07 03:04 | T | N |  |
| FR-STUDY-02 | For a registry or observational study, the system shall keep the cohort current each night by its **cohort kind** set on S21: **enrolled** (membership fixed by enrolment; show only new candidates) or **dynamic** (re-evaluate the definition nightly; list new members and members who no longer meet it). It pulls the study's defined variables per member with source and date per value, inside the lake. | S2 (was M1) | TB-DS-17 §4.2 R1–R2, TB-REV-006c C-22 | T | N |  |
| FR-STUDY-03 | The system shall reconcile registry values (from the hospital REDCap via the read connector, or an imported dataset) against EMR values per variable with a unit-normalised tolerance, listing mismatches, missing in registry and missing in EMR, for the RA to decide per item. | L (was M2) | TB-DS-17 §6.4; TB-DS-00 §2 (WP-19b; the CCB may pull it into the M1 line only if a pilot study is a registry) | T | N | Later step (WP-19b in the hospital-stage plan); may move earlier if a first study is a registry. |
| FR-STUDY-03a | Reconciliation shall write nothing to REDCap (BD-05). | L (split from FR-STUDY-03) | TB-DS-17 §6.4 | T | N |  |
| FR-STUDY-04 | An accepted reconciliation or a new visit value shall be proposed as a pre-fill card in the REDCap panel and saved only by the user in REDCap. | L (was M2) | TB-DS-17 §6.4, BD-05 | T | N |  |
| FR-STUDY-05 | The system shall produce a repeatable study export with its data dictionary. | L (was M2) | TB-DS-17 §4.2 R5 | T | N |  |
| FR-STUDY-05a | A study export leaving the identified zone shall be D2 with the N-08 date shift. | L (split from FR-STUDY-05) | TB-DS-17 §4.2 R5 | T | N |  |
| FR-STUDY-05b | A study export leaving the site shall need the study `investigator`'s approval. | L (split from FR-STUDY-05) | TB-DS-17 §4.2 R5 | T | N |  |
| FR-STUDY-06 | When the site setting `ethics_gate` is on (default **off** in `TB_ENV=DEV` and `TEST`, **on** in `PRODUCTION`; TB-REV-006f F6-03), a SCREEN or CASE job that resolves identities for **any** study, whatever its type (trial, registry, observational) or consent scope (opt-in, opt-out, waiver), shall run only when the study's ethics approval record (committee, number, date, "identified screening covered: yes", expiry) exists, is confirmed by the investigator and is not expired; feasibility (flow A) is unaffected. | H (was M1) | TB-DS-03 §11.2 P3, H-07, TB-REV-006c C-19, BD-20 | T | N |  |
| FR-STUDY-07 | Each study shall have one set-up record edited on S21 (TB-DS-09): identity and type, cohort kind, consent scope, protocol version pinned to the ruleset, sponsor flag, ethics approval record and explainer file, team and scope (investigators, coordinators, SMO expiry), treating-physician list and who may introduce the study, REDCap project link (FR-RC-16), screening-number format, notification defaults, explainer on/off, forecast parameters. | S3 (was M1) | TB-REV-006c C-07 | T | P (site profile built) | The built site profile (`site_profile`: target_n, screen-fail, competing trials) is reused. |
| FR-STUDY-07a | The study's `coordinator` shall be able to edit the set-up record. | S3 (split from FR-STUDY-07) | TB-REV-006c C-07 | T | P |  |
| FR-STUDY-07b | Only the study's `investigator` shall be able to confirm the ethics approval record and the team. | S3 (split from FR-STUDY-07) | TB-REV-006c C-07 | T | P |  |
| FR-STUDY-07c | The system shall let the `admin` assign study scope only by completing a coordinator's scope request. Fit: no scope change exists in the audit record without a linked coordinator request. | S3 (split from FR-STUDY-07) | TB-REV-006c C-07 | T | P |  |
| FR-STUDY-08 | The system shall assign a per-study `screening_no` when a candidate first gets an Approach mark (format and prefix from S21, or continuing the site's own sequence from a first number entered on S21) and show it on the row and in the log. | S2 (was M1) | BD-18 | T | N |  |
| FR-STUDY-09 | The "Not suitable" reason list shall be set per study on S21, starting from a default set per study type (AD: stage, no study partner, comorbidity, unlikely to attend, other; RA: disease activity, current biologic, comorbidity, unlikely to attend, other; other types: comorbidity, unlikely to attend, other). | S2 (was M1) | TB-REV-006c C-10 | T | N (AD list hard-coded) | AD list hard-coded today. |
| FR-STUDY-10 | An account with the `office` scope flag (research office) shall be able, for all studies of the site, to edit S21 sections 1 (identity and type), 3 (team and scope), 4 (REDCap link), 5 (screening-log settings) and 8 (forecast), to read sections 2 (ethics approval and sponsor approval), 6 and 7, to read the screening logs (D3) and to run FR-REP-09 exports. | H (was M1) | TB-REV-006c C-18 | T | N |  |
| FR-STUDY-10a | An account whose only study role is the `office` flag shall not confirm an approval record, approve a ruleset or reveal a chart number. | H (split from FR-STUDY-10) | TB-REV-006c C-18 | T | N |  |

#### 3.1.28 NOTIF — Lists, digests and alerts

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-NOTIF-01 | The system shall send each `investigator` one PI list mail covering all their studies (pseudonym, visit day and clinic, met / unknown / needs-PI counts, new marker, grouped as FR-UI-15) and a link to the on-prem list. **Default where an appointment source exists: on the morning of each of the PI's clinic days (07:00)** with that day's candidates and the rest of the week folded below; **fallback: every Monday** after the weekend re-check window (BD-11) with the next 7 days. Pseudonyms only (BD-04, FR-MAIL-03); the mail is readable with pseudonyms and counts when the link cannot be opened from the PI's device. No mail on an empty day or week unless the person opts in. | S2 (was M1) | TB-DS-17 §5.1, TB-REV-006c C-16, C-20 | T | P (weekly list built; mail per PI N) |  |
| FR-NOTIF-02 | On working days the system shall send each `coordinator` one digest across all their studies (today's visits with next step, new pre-screens, PI marks since the last digest) at the person's chosen time (default 07:30). | S2 (was M1) | TB-DS-17 §5.2 | T | N | Tasks and unverified fields join the digest at L. |
| FR-NOTIF-03 | Real-time notices shall be sent only for AE suggestions of CTCAE grade ≥ 3 (L, threshold per site), approval requests (batched to at most one per approver per 2 h), admin failure alerts (FR-OPS-08) and, where a study switches it on (off by default), an **in-hours immediate notice** to the study's coordinators on duty (FR-UI-18 definition, not snoozed) for an Approach mark on a patient with a visit today (content: study and clinic room only, never a screening number; outside the weekly CRC count but at most 2 per day per CRC, NFR-USAB-10); all other items go to the next digest or list. | H (was M1) | TB-DS-17 §5.3, TB-REV-006c C-14 | T | N |  |
| FR-NOTIF-04 | Each person shall be able to set channel, delivery times, quiet hours (default 20:00–07:00 and weekends) and a one-tap snooze of 1 day or 1 week for non-safety notices. | H (was M1) | TB-DS-17 §5.4 | T | N |  |
| FR-NOTIF-04a | Safety notices shall not be snoozable. | H (split from FR-NOTIF-04) | TB-DS-17 §5.4 | T | N |  |
| FR-NOTIF-04b | The recipient of a safety notice shall be able to route it to a named deputy `investigator`. | H (split from FR-NOTIF-04) | TB-DS-17 §5.4 | T | N |  |
| FR-NOTIF-05 | An item read on the web shall not be sent again by another channel; one item reaches one person once. | H (was M1) | TB-DS-17 §5.4 | T | N |  |
| FR-NOTIF-06 | The console shall be installable as a PWA on phones without an app store. | L (was M2) | TB-DS-17 §5.5 | T/I | N |  |
| FR-NOTIF-06c | The console shall send Web Push notices (RFC 8291 encrypted) that carry no patient data, not even pseudonyms. | L (split from FR-NOTIF-06) | TB-DS-17 §5.5 | T/I | N |  |
| FR-NOTIF-06a | Opening an item from a notice shall require login on the hospital network or VPN. | L (split from FR-NOTIF-06) | TB-DS-17 §5.5 | T/I | N |  |
| FR-NOTIF-06b | No patient data shall be cached on the phone. | L (split from FR-NOTIF-06) | TB-DS-17 §5.5 | T/I | N |  |
| FR-NOTIF-07 | The system shall send LINE and Microsoft Teams notices under the content rule of FR-NOTIF-06. | L (was C) | TB-DS-00 §2 | T | N |  |
| FR-NOTIF-08 | The admin pages shall show notices sent per role per week against the NFR-USAB-10 budget, and snooze and opt-out counts, without content. | H (was M1) | TB-DS-17 §5.4, §9.2 | T | N |  |
| FR-NOTIF-09 | Every notice shall state why it was sent and link to the person's notification settings. | S2 (was M1) | TB-DS-17 §5.4 | I | N |  |

#### 3.1.29 PLAT — Platform pages and supporting functions (TB-DS-19)

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-PLAT-01 | The login page shall offer "Forgot password" that shows the site's admin contact; the admin resets the password (no self-service mail reset). | H (was M1) | TB-DS-19 | T | N |  |
| FR-PLAT-02 | When an account is added or a password reset, the system shall send a one-time set-password link (24 h, one use) to the user's hospital mailbox. | H (was M1) | TB-DS-19 | T | P (shown once built) |  |
| FR-PLAT-02a | When mail is not configured, the system shall show the new password once to the admin instead. | H (split from FR-PLAT-02) | TB-DS-19 | T | P |  |
| FR-PLAT-03 | TOTP enrolment shall issue 10 one-use recovery codes. | H (was M1) | TB-DS-19 | T | N |  |
| FR-PLAT-03b | The issue and every use of a recovery code shall be audited. | H (split from FR-PLAT-03) | TB-DS-19 | T | N |  |
| FR-PLAT-03a | The admin shall be able to reset a user's TOTP. | H (split from FR-PLAT-03) | TB-DS-19 | T | N |  |
| FR-PLAT-03c | Every TOTP reset shall be audited. | H (split from FR-PLAT-03a) | TB-DS-19 | T | N |  |
| FR-PLAT-04 | Every user shall have a My account page: name, role, affiliation, scopes, expiry, last login; change password, re-enrol TOTP, language, link to notification settings (S22). | S4 (was M1) | TB-DS-19 | T | N |  |
| FR-PLAT-05 | Two minutes before the idle timeout the page shall warn the user and offer to stay signed in. | H (was M1) | TB-DS-19 | T | N |  |
| FR-PLAT-06 | After install the admin home shall show a first-run checklist (settings valid, data source, first ingest, mapping coverage, mail test, backup target, first accounts, dry run) until every line is done (S31). | H (was M1) | TB-DS-19 | T | P (CLI wizard built) |  |
| FR-PLAT-07 | The admin shall see site settings in plain words. | H (was M1) | TB-DS-19 | T | P (settings file + CLI) | S23. |
| FR-PLAT-07a | The admin shall be able to edit only a fixed safe list of settings: display name, admin contact, mail footer, night-schedule times and retention within its allowed range. | H (split from FR-PLAT-07) | TB-DS-19 | T | P |  |
| FR-PLAT-07b | Every settings change shall be written to the audit log. | H (split from FR-PLAT-07) | TB-DS-19 | T | P |  |
| FR-PLAT-08 | The system shall show each data source with last ingest, records loaded, validation rate, rejected rows with reasons (no PHI), next run and the last 30 ingests, with Run ingest now (S24). | S4 (was M1) | TB-DS-19 | T | P (button built) |  |
| FR-PLAT-09 | The admin shall view code-mapping coverage and the top unmapped codes (S25). | H (was M1) | TB-DS-19 | T | P (CLI built) |  |
| FR-PLAT-09a | The admin shall be able to download the mapping file, upload a validated new version with the old one kept, and re-run the coverage check. | H (split from FR-PLAT-09) | TB-DS-19 | T | P |  |
| FR-PLAT-10 | The admin shall set and test the REDCap connection (base URL, version found, masked token in the secret store, linked projects) (S36). | S3 (was M1) | TB-DS-19 | T | N |  |
| FR-PLAT-11 | Outgoing notices shall use fixed templates in EN/JA/zh-TW. | H (was M1) | TB-DS-19 | T | N |  |
| FR-PLAT-11a | The admin shall be able to edit only the header, footer, signature and contact line of a notice template, with preview (S32). | H (split from FR-PLAT-11) | TB-DS-19 | T | N |  |
| FR-PLAT-12 | The jobs page shall filter jobs by study, type, state and date (S26). | S4 (was M1) | TB-DS-19 | T | P (list built) |  |
| FR-PLAT-12a | The jobs page shall offer Cancel on queued or running jobs and **Retry** on failed jobs. | S4 (split from FR-PLAT-12) | TB-DS-19 | T | N |  |
| FR-PLAT-12b | Every Cancel and Retry shall be written to the audit log. | S4 (split from FR-PLAT-12) | TB-DS-19 | T | N |  |
| FR-PLAT-13 | Each study shall have a report archive listing every report, pack, list, screening log and explainer produced, with version, snapshot, maker, downloads, and re-download within retention (S27). | L (was M1) | TB-DS-19 | T | N |  |
| FR-PLAT-14 | A header search shall find studies, pseudonyms and screening numbers within the user's scope, from the header command field (FR-UI-01). | S4 (was M1) | TB-DS-19 | T | N |  |
| FR-PLAT-14a | Chart-number search shall be offered only to reveal roles and shall be audited as a reveal. | S4 (split from FR-PLAT-14) | TB-DS-19 | T | N |  |
| FR-PLAT-15 | Every table shown shall be downloadable as CSV or XLSX with the same rows and small-cell rule; reports also as PDF; every download audited. | H (was M1) | TB-DS-19 | T | P |  |
| FR-PLAT-16 | The patient sheet, PI list and feasibility report shall have A4 print views with hospital, study, date, page numbers and a pseudonymous footer. | L (was M1) | TB-DS-19 | T | P (print CSS) |  |
| FR-PLAT-17 | Each user shall see a list of notices the box sent to them, with links (S37). | S4 (was M1) | TB-DS-19 | T | N |  |
| FR-PLAT-18 | While night jobs run, every page shall show a banner saying lists show yesterday's data. | H (was M1) | TB-DS-19 | T | N |  |
| FR-PLAT-19 | Every page shall have a help panel in the user's language, available offline (S29). | S4 (was M1) | TB-DS-19 | T | N |  |
| FR-PLAT-20 | The box shall hold a user guide per role (PI, coordinator, research office, admin, CRO viewer) in EN/JA/zh-TW as pages and printable PDF (TB-DS-22). | H (was M1) | TB-DS-19 | T | N |  |
| FR-PLAT-21 | An About page shall show version, build, install date, update history, models with file hashes (admin), ruleset versions, open-source licences and support contact (S30). | L (was M1) | TB-DS-19 | T | N |  |
| FR-PLAT-22 | A page reachable inside the hospital without sign-in shall show the site's patient notice and how to opt out (S33). | H (was M1) | TB-DS-19 | T | N |  |
| FR-PLAT-23 | An `admin` or `coordinator` shall be able to record a patient opt-out by chart number (S33). | H (was M1) | TB-DS-19 | T | N |  |
| FR-PLAT-23a | From the night after an opt-out is recorded, the system shall leave the patient out of all counts, lists and checks and hide the patient in existing lists. | H (split from FR-PLAT-23) | TB-DS-19 | T | N |  |
| FR-PLAT-23b | Every recorded opt-out shall be audited and included in the backup set. | H (split from FR-PLAT-23) | TB-DS-19 | T | N |  |
| FR-PLAT-24 | A coordinator shall close a study: lists stop; screening log and audit kept for N-03, then deleted or archived on admin confirmation. | H (was M2) | TB-DS-19 | T | N |  |
| FR-PLAT-25 | The settings page shall show what is kept, for how long, the next deletion run and the last deletions. | H (was M1) | TB-DS-19 | T | P (retention job built) |  |
| FR-PLAT-26 | The admin shall see backup status per item of FR-OPS-06 (S34). | H (was M1) | TB-DS-19 | T | P (manual rsync) |  |
| FR-PLAT-26a | The admin shall be able to run Test restore into a scratch area, with checks. | H (split from FR-PLAT-26) | TB-DS-19 | T | N |  |
| FR-PLAT-26b | The admin shall be able to restore a box with one command. | H (split from FR-PLAT-26) | TB-DS-19 | T | P |  |
| FR-PLAT-27 | The admin shall be able to upload, verify and apply a signed update from a web page (S35). | H (was M1) | TB-DS-19 | T | P (CLI apply/verify built) |  |
| FR-PLAT-27a | The admin shall be able to roll back to the previous version from a web page with data kept. | H (split from FR-PLAT-27) | TB-DS-19 | T | N |  |
| FR-PLAT-28 | The health page shall add GPU memory and loaded model, disk, snapshots, last backup, last chain check, certificate expiry, night-job progress and Export support bundle. | H (was M1) | TB-DS-19 | T | P (services and models built) |  |
| FR-PLAT-29 | The audit browser shall filter by date, user, action and study, show chain status, export CSV and offer Verify chain now. | H (was M1) | TB-DS-19 | T | P (recent list built) |  |
| FR-PLAT-30 | Every page shall pass automated WCAG 2.2 AA rules, keyboard use, 390 px phone width, print layout and all three languages in the browser walk. | H (was M1) | TB-DS-19 | T | P (phone + language walk built) |  |

#### 3.1.30 SYN — Synthetic hospital (TB-DS-21)

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FR-SYN-01 | A deterministic generator (TB-DS-21) shall produce, from a seed, a synthetic hospital of up to 500,000 patients for one or more sites, with Japanese-style and Taiwanese-style identifiers, codes and dates, written in the same landing format the ingest reads. | S1 (new) | SIMPLE-PLAN, TB-REV-006f F6-02 | T | P (600-patient `make_fixtures.py`; 50k structured `eval/hospital_sim`) | Implementation: `tools/synth_hospital`, extended from the built `tools/synth` (TB-DS-21 §2). |
| FR-SYN-02 | The generator shall write clinical notes in JA, zh-TW and EN from templates, with planted findings tied to study criteria and planted PHI spans, and a gold file listing both (TB-DS-21 §5). | S1 (new) | F6-02 | T | N |  |
| FR-SYN-03 | The generator shall be able to take the structured part from Synthea (Apache-2.0) and add TrialBox's own layer for names, codes, 和暦 dates, 保険病名 and appointments (TB-DS-21 §4). | S1 (new) | F6-02, F6-16 | I | P (`tools/synthea_ad_cohort.py`) | Optional source; the built `tools/synth` layer is the default. |
| FR-SYN-04 | Generation of 500,000 patients shall finish within one night (≤ 8 h) on the demo VM. | S1 (new) | F6-02 | T | N | Target; measured in build step 1 (TB-DS-21). |
| FR-SYN-04a | The 5,000-patient CI profile shall generate in under 5 minutes. | S1 (split from FR-SYN-04) | F6-02 | T | N | Target; measured in build step 1. |

### 3.2 Non-functional requirements

#### 3.2.1 Performance and accuracy (PERF)

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| NFR-PERF-01 | Interactive pages (role work lists, study lists, cards) shall render in ≤ 2 s at the 95th percentile with 10 concurrent users (N-13, N-18). | H (was M1) | N-13 | T | N |  |
| NFR-PERF-02 | A recognised command shall start its job and show the job page in ≤ 3 s at the 95th percentile (N-13). | H (was M1) | N-13 | T | N |  |
| NFR-PERF-03 | A single-patient check shall complete in ≤ 60 s at the 95th percentile under the conditions of FR-CASE-03 (N-13). | H (was M1) | N-13, F-40 | T | N |  |
| NFR-PERF-04 | Pre-fill proposals for one instrument of ≤ 50 fields shall appear in ≤ 60 s at the 95th percentile (N-13). | L (was M2) | N-13 | T | N |  |
| NFR-PERF-05 | The night batch shall finish inside the BD-11 windows (ingest by 23:30, PHI pass by 02:00, screening by 05:30, reports and mail by 06:00) for the N-18 design point: 500,000 patients and 20 studies on 1 × RTX 5090; 50 studies on 2 × RTX 5090. | H (was M1) | N-18, BD-11 | T | N | Until measured (OI-03) the design point is an estimate. |
| NFR-PERF-06 | The weekend full re-check of all active studies shall finish inside Saturday 22:00 – Monday 06:00 (BD-11). | H (was M1) | BD-11 | T | N |  |
| NFR-PERF-07a | A feasibility report for one protocol whose criteria are all filters (no note criteria) on 500,000 patients shall be ready within 30 min. | H (was M1) | [P1] §11.3 | T | P (50,000 measured) |  |
| NFR-PERF-07b | A feasibility report for one protocol with note criteria shall be ready by 08:00 the next working day when requested before 20:00. | H (was M1) | A10, A20 | T | P |  |
| NFR-PERF-08 | Each model release shall meet the SIGIR gate (N-11): lost eligible patient–trial pairs ≤ measured baseline + 1 (EN ≤ 5, JA ≤ 4, zh-TW ≤ 2 provisional), never above 8 of 79. | S5 (was M1) | N-11, [P6], F-57 | T | P | **Provisional baseline** (2026-11-06, one run on an RTX PRO 6000 capped to 5090 limits, not a 5090): 4 / 79 EN, 3 / 79 JA lost, filter-first. zh-TW: 1 / 79 via OpenRouter at provider precision, not on a card (gate N-11 zh-TW ≤ 2, provisional). Configuration of that run: vLLM v0.32.0; judge `nvidia/Gemma-4-26B-A4B-NVFP4`; verifier `cyankiwi/Qwen3.5-9B-AWQ-4bit`, thinking off; `max-model-len` 8192; `max-num-seqs` 4; `enforce-eager`; `gpu-memory-utilization` 0.22 (judge) / 0.105 (verifier). Model-file sha256 hashes were not recorded; step 5 records them with the run on the deployed files (FR-MOD-10), which then becomes the baseline (OI-02). SIGIR's 79 pairs cannot rank close candidates (4 / 79 = 5.1 %, Wilson 95 % 2.0–12.3 %; TrialGPT GPT-4 8 / 79 = 10.1 %, 5.2–18.7 %). |
| NFR-PERF-09 | Each model release shall meet the TREC CT 2021/22 gate (N-12): projected true loss of eligible pairs under filter-first ≤ 5 %. | S5 (was M1) | N-12, [P6] PR #15 | T/A | P | **Projected**, not measured: ≈ 3.6 % (95 % CI 2.1–5.6) = raw loss 19.3 % (OpenRouter, provider precision) × a 30-pair audit read by Claude, not a clinician, × the filter-first routing share. N-12 is judged on the point estimate until a site-adjudicated sample exists. |
| NFR-PERF-10 | Each model release shall keep recall of present findings on MedTxt (Japanese) ≥ 69 %. | H (was M1) | [P6] PR #15, F-13 | T | P | 69 % is the measured value (OI-10). |
| NFR-PERF-11 | Against the manual chart review of 100 patients per study, the patient lists shall reach pooled recall across studies ≥ 90 % (point estimate) with Wilson 95 % lower bound ≥ 75 % (N-16). | H (was M1) | N-16, A42, A43 | T | N |  |
| NFR-PERF-11a | Every patient missed by the patient lists in the chart review shall be explained in the pilot validation report. | H (split from NFR-PERF-11) | N-16, A42, A43 | T | N |  |
| NFR-PERF-12 | Pilot turnaround: a feasibility report shall be delivered within one working day of the request. | H (was M1) | A42 | T | N |  |
| NFR-PERF-13 | Pilot effort (N-17): median staff time per pre-screen shall fall by ≥ 50 % against the baseline measured at each site before the pilot (AS-09). | H (was M1) | N-17, A42, F-44 | A | N |  |
| NFR-PERF-14 | The PHI pass shall meet N-07: identifier-span leak rate (gold identifier spans not removed ÷ all gold identifier spans) ≤ 0.5 % overall **and** zero leaked direct identifiers (name, chart number, national ID, phone, address, insurer number). | H (was M1) | N-07, F-11 | T | N | Measured once on the gate set (MedTxt + 200 hospital notes per site, SC-60) before the first real-data use, then monthly on the FR-DEID-10 sample. |
| NFR-PERF-14a | A failed monthly PHI measurement shall stop new notes entering D3 until a measurement passes. | H (split from NFR-PERF-14) | N-07, F-11 | T | N |  |
| NFR-PERF-15 | EDC pre-fill shall meet N-09: ≥ 95 % of proposed values accepted unedited for rule-filled fields and ≥ 90 % for model-filled fields, on the pre-fill gate set. | L (was M2) | N-09 | T | N |  |

#### 3.2.2 Capacity (CAP)

All capacity rows are design estimates until the full-size dry run (FR-OPS-07, OI-03) measures them; measured only to 50,000 patients so far (N-18).

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| NFR-CAP-01 | The system shall hold 500,000 patients with 10 years of encounters, labs, prescriptions and notes per site (N-18). | H (was M1) | N-18 | T | P (50,000 tested) |  |
| NFR-CAP-02 | The system shall run 20 active studies per standard site and 50 at CGMH (N-18). | H (was M1) | N-18 | T | N |  |
| NFR-CAP-03 | The system shall serve 10 concurrent interactive users (N-18) and hold at least 200 named accounts per site. | H (was M1) | N-18 | T | N |  |
| NFR-CAP-04 | A country hub shall serve at least 10 member sites. Fit: a hub test with 10 simulated member sites passes the FED test suite. | L (was M2) | A15 | A | N |  |
| NFR-CAP-05 | The N-04 snapshot set (3 nightly + 36 month-ends) for 500,000 patients shall fit in the BD-10 usable disk (8 TB standard, 16 TB CGMH) with ≥ 20 % free. | H (was M1) | N-04, BD-10, F-21 | A/T | N | Storage model (bytes per patient per snapshot, change rate per night) measured in the dry run and recorded in TB-DS-02. |
| NFR-CAP-05a | Snapshots shall be stored incrementally, sharing unchanged resource files between snapshots by content hash. | H (split from NFR-CAP-05) | N-04, BD-10, F-21 | A/T | N |  |

#### 3.2.3 Availability (AVAIL)

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| NFR-AVAIL-01 | Interactive service shall be available ≥ 99 % in working hours (08:00–20:00 local, working days), excluding announced maintenance (N-14). | H (was M1) | N-14 | A | N |  |
| NFR-AVAIL-02 | Failure of the appliance shall not affect clinical systems (EMR, REDCap). | S0 (was M1) | CON-01 | I | B | Holds because TrialBox only reads from the EMR (CON-01). |
| NFR-AVAIL-03 | Backup and restore shall meet a recovery point objective of 24 h and a recovery time objective of 2 working days on replacement hardware (N-15). | H (was M1) | N-15, F-15 | T | N |  |
| NFR-AVAIL-04 | A failed night job shall resume or restart the next night without data loss and alert the admin. | H (was M1) | A20 | T | P |  |

#### 3.2.4 Maintainability (MAINT)

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| NFR-MAINT-01a | The product shall live in one repository with one CI pipeline. | S0 (was M1) | A32 | I | B |  |
| NFR-MAINT-01b | A release shall be one signed bundle per hardware profile, built by one command from a tagged commit. | H (was M1) | A32 | T | P |  |
| NFR-MAINT-02 | The appliance shall run only these runtime components: ingest/engine services, HAPI FHIR 8.12 (Medplum only after the later spike, CON-15), one relational DB, DuckDB, the filesystem object store (CON-16), vLLM (CON-17), mail gateway, console. Fit: the release image list contains no other database, store or message broker. | H (was M1) | CON-11, BD-01, BD-09, F-37 | I | P | Adding a component needs an ADR in TB-DS-02. |
| NFR-MAINT-03 | Site customisation shall be by configuration (mapping YAML, rule book, settings) only; no site-specific code branches. | H (was M1) | A5 | I | P |  |
| NFR-MAINT-04 | Every release shall pass unit, integration, browser end-to-end and model-gate tests in CI. | H (was M1) | report §Releases, F-43 | T | P |  |
| NFR-MAINT-04a | A test shall be removed or skipped only with a recorded reason in the release notes. | H (split from NFR-MAINT-04) | report §Releases, F-43 | T | P |  |
| NFR-MAINT-05 | Install, update, backup/restore and support documentation shall be available in Japanese. Fit: each of the four guides has a JA edition at the same version as its EN edition. | H (was M1) | A32 | I | N |  |

#### 3.2.5 Usability (USAB)

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| NFR-USAB-01 | In a moderated test with at least 5 PIs or CRCs per site who have read only the one-page quick guide, at least 4 of 5 shall obtain a feasibility report from criteria text unaided, in ≤ 3 user actions (paste, accept or change the study name, submit). | H (was M1) | A10, A19, F-29 | D | N |  |
| NFR-USAB-02 | (Withdrawn: replaced by NFR-PERF-13 / N-17.) | — (was M1) | F-44 | — | W |  |
| NFR-USAB-03 | Primary navigation shall have ≤ 4 items plus "More" per role. | S0 (was M1) | D-104 | I | B |  |
| NFR-USAB-04 | The UI shall meet WCAG 2.2 AA for contrast, keyboard access and focus visibility on the pages of FR-UI-01..13. | H (was M1) | [S14] | T | P |  |
| NFR-USAB-05 | Each person shall be able to finish a task in one channel (page or e-mail) without switching. | H (was M1) | report §UX | D | N | The REDCap panel becomes a third channel at L. |
| NFR-USAB-06 | No new interaction shall be added for a clinical role (`investigator`, `coordinator`) unless TB-DS-17 §2.2 shows a larger task removed for the same role. | H (was M1) | TB-DS-17 §2, §9, BD-16 | A/D | N |  |
| NFR-USAB-06a | In pilot Phase 2 (BD-16) each clinical role's measured net weekly time shall be ≤ its baseline. | H (split from NFR-USAB-06) | TB-DS-17 §2, §9, BD-16 | A/D | N | Phase 1 time is reported as added time agreed in advance; chart review and comparison work are pilot-team time, not counted (BD-16). |
| NFR-USAB-07 | No input screen shall ask for a value already held in the EMR, DWH, REDCap or an earlier TrialBox screen (zero duplicate entry). | H (was M1) | TB-DS-17 §2.1 | I | N |  |
| NFR-USAB-07a | Consent and enrolment status shall be read from REDCap where the study uses it. | H (split from NFR-USAB-07) | TB-DS-17 §2.1 | I | N |  |
| NFR-USAB-08 | Every action screen shall open with the most likely choice pre-selected. | S2 (was M1) | TB-DS-17 §2.3, §9.2, BD-17 | T/D | N | Checked again in S4. A hospital install with TOTP (H) adds one code entry per session; not counted (BD-17). |
| NFR-USAB-08a | Taps per task shall be at most: mark a candidate 2; approve a ruleset 2 plus one per amber row opened (FR-FEAS-12); a sponsor-report release 2; record a contact outcome 2; feasibility from text 3 (NFR-USAB-01). | S2 (split from NFR-USAB-08) | TB-DS-17 §2.3, §9.2, BD-17 | T/D | N | Checked again in S4. A hospital install that turns on TOTP adds one code entry per session (BD-17, H); not counted. |
| NFR-USAB-09 | In the pilot, mean SUS shall be ≥ 70 for PI and CRC users after 4 and 8 weeks. | H (was M1) | TB-DS-17 §9, TB-REV-006c C-25 | D | N | Raw NASA-TLX is reported descriptively per person (baseline vs Phase 2) with no pass threshold, because n is about 4 per role per site. |
| NFR-USAB-10 | Notices per role per week (excluding safety and admin failure alerts) shall stay within the TB-DS-17 §5.4 budget: PI ≤ one list per clinic day (at most 5) + ≤ 2 approval batches, CRC ≤ 5 digests + ≤ 2 approval requests or results (N3 in-hours notices are outside the weekly count but ≤ 2 per day per CRC), RA ≤ 2, `cro` ≤ 1; extra items are merged into the next scheduled message. | H (was M1) | TB-DS-17 §5.4 | T | N |  |

#### 3.2.6 Portability (PORT)

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| NFR-PORT-01 | The system shall run on x86-64 with 1 or 2 RTX 5090 (standard, BD-10) and on arm64 DGX Spark (option), from the same source with per-profile compose files; RTX PRO 6000 only for a large hub. | H (was M1) | P-HW, BD-10, D-95 | T | P |  |
| NFR-PORT-02 | The system shall run without internet access after installation. | S0 (was M1) | CON-01 | T | B |  |
| NFR-PORT-03 | Data exports (FHIR NDJSON, CSV, XLSX) shall use open formats. | S0 (was M1) | A7 | I | B | The OMOP export (IR-11b, L) follows the same rule. |

#### 3.2.7 Compliance (COMP)

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| NFR-COMP-01 | The system shall implement the controls of TB-DS-03 §4 (SC-nn) whose build tag is S0 or H, which map to MHLW GL 第7.0版 [S12], Taiwan Cyber Security Management Act guidance for hospitals [S13], ISO/IEC 27001:2022 Annex A [S9] and OWASP ASVS 5.0 level 2 [S15]. | H (was M1) | A34, BD-12 | I/T | P |  |
| NFR-COMP-02 | Withdrawn from §3: a penetration test is a project activity, not a system requirement. It is kept as project obligation PO-01 (§2.7). | — (was M1) | A34 | T | W |  |
| NFR-COMP-03a | Japan: processing shall follow APPI [S11] under the chapter that applies to the hospital's legal category — Chapter 4 for a private hospital (including Art. 41 for 仮名加工情報 and the academic-research provisions), Chapter 5 for a national-university, national or public hospital (administrative organ or incorporated administrative agency) — and the 生命科学・医学系研究 ethical guidelines (information disclosure and opt-out for feasibility on existing data), per the site's ethics approval. The head hospital's category is OI-12. | H (was M1) | A8, A26, F-26 | I | P |  |
| NFR-COMP-03b | For Taiwan, the system shall run feasibility only on de-identified data that cannot identify a person as disclosed (PDPA Art. 6(1)(4) basis). | H (was M1) | A8, [S13], F-26 | I | N |  |
| NFR-COMP-03c | For a Taiwan study, the system shall produce an identified patient list (flow B) only when the study's ethics record holds a Human Subjects Research Act IRB approval with consent or an IRB waiver of consent (FR-STUDY-06). | H (split from NFR-COMP-03b) | A8, [S13], F-26 | I | N |  |
| NFR-COMP-04 | The UI (FR-UI-12) and the user documentation shall carry the intended-use statement. | H (was M1) | A33 | I | N | The position paper on non-device status (PMDA, TFDA) is project obligation PO-03 (§2.7). |
| NFR-COMP-05 | Screening logs, approval records and study outputs shall be retained for each study's GCP retention period and at least 5 years (N-03); audit records for 10 years (N-02). | H (was M1) | N-02, N-03, A35 | I | P |  |
| NFR-COMP-06 | The REDCap integration shall use only REDCap's public API and External Module framework. | H (was M1) | CON-03 | I | N | Naming and marketing without the REDCap name: CON-03. |
| NFR-COMP-06a | No REDCap code or UI assets shall be copied into TrialBox. | H (split from NFR-COMP-06) | CON-03 | I | N |  |
| NFR-COMP-07 | Third-party components shall be licence-compatible with free distribution to hospitals (Apache-2.0, MIT, BSD, LGPL as libraries; model licences reviewed per model; see TB-DS-05). | H (was M1) | A30 | I | P |  |
| NFR-COMP-08 | Withdrawn from §3: a DPIA is a project activity, not a system requirement. It is kept as project obligation PO-02 (§2.7). | — (was M1) | A8 | I | W |  |

### 3.3 Data requirements

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| DR-01 | The canonical clinical data model shall be FHIR R4 (4.0.1) with JP Core 1.2.0 or TW Core profiles per site. | S0 (was M1) | A5, BD-12 | I/T | B |  |
| DR-02 | Every coded element shall keep source and standard codes and the code system version. | S0 (was M1) | A7 | I | P |  |
| DR-03 | The lake shall be rebuilt from the FHIR snapshot each time a snapshot is taken. | S0 (was M1) | [P2] §3 | T | B |  |
| DR-03a | The lake shall reject any query statement other than SELECT. | S0 (split from DR-03) | [P2] §3 | T | B | Built with a sqlglot parse guard. |
| DR-04 | Each ruleset shall be stored in git with its manifest, IR, value sets, SQL, CQL/ELM and tests. | S0 (was M1) | [P2] §4, SC-40 | T | P (signing new) |  |
| DR-04b | An approved ruleset shall be immutable, tagged and signed. | S0 (split from DR-04) | [P2] §4, SC-40 | T | P |  |
| DR-04a | The engine shall refuse to run an unsigned or unapproved ruleset. | S0 (split from DR-04) | [P2] §4, SC-40 | T | P |  |
| DR-05 | The registry shall store pseudonym, study, status events (who, when, reason) and investigator marks as events. | S0 (was M1) | D-92, D-104 | T | B |  |
| DR-06 | EDC pre-fill records (FR-EDC-08) shall be kept with the study and be exportable. | L (was M2) | A4 | T | N |  |
| DR-07 | The pid map shall be encrypted at rest (AES-256-GCM, built) with a key that is not stored on the same disk in plain form (FR-SEC-02). | S0 (was M1) | [P1] §10.1, F-36 | I | P (encryption built; TPM sealing documented, not enforced) |  |
| DR-08 | The system shall keep inbound attachments 90 days and outputs 365 days (D-78). | S0 (was M1) | D-78 | I | P (GCP floor new) |  |
| DR-08a | The system shall keep 3 nightly and 36 month-end snapshots (N-04). | S0 (split from DR-08) | N-04 | I | P |  |
| DR-08b | The system shall keep registry and screening logs for the life of the ruleset plus 24 months, and at least for the study's GCP retention of 5 years or more (N-03). | S0 (split from DR-08) | N-03 | I | P |  |
| DR-08c | The system shall keep the audit log 10 years (N-02). | S0 (split from DR-08) | N-02 | I | P |  |
| DR-09 | On a patient erasure or correction request, the system shall at the next snapshot correct or remove the patient, purge the patient from the lake, mark registry entries "withdrawn" with the pseudonym kept, and keep the audit record. Fit: after the next snapshot a lake query for the pid returns 0 rows and the registry shows "withdrawn". | H (was M1) | [S11], [P4], F-25 | T | N |  |
| DR-10 | GUID encodings shall be stored only at the site that computed them and at the country hub for the duration of one linkage job, then deleted at the hub. | L (was M2) | A15, BD-06 | T | N |  |

### 3.4 Interface requirements

| ID | Requirement | Pri | Source | Ver | St | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| IR-01 | The system shall read EMR input from an SS-MIX2 storage directory (read-only mount or SFTP drop), a vendor CSV/SQL export, or the CGMH warehouse view (read-only DSN). | S0 (was M1) | A5, A27 | T | P |  |
| IR-02 | The system shall read and write FHIR R4 over REST and as bulk NDJSON. | S0 (was M1) | A6 | T | B |  |
| IR-03a | The system shall read REDCap by HTTPS POST to `/api/` with the project read token, using the export methods of FR-RC-09 and JSON. | S3 (was M1) | A14, BD-05 | T | N |  |
| IR-03b | The system shall write to REDCap only through the External Module under the user's REDCap session, with no API token on the appliance. | L (was M2) | BD-05 | T | N |  |
| IR-04 | The system shall accept the REDCap Data Entry Trigger as an HTTPS POST from the REDCap server carrying project_id, record, instrument, event and DAG, signed per SC-49. | L (was M2) | A14, SC-49 | T | N |  |
| IR-05 | The REDCap External Module and the appliance shall talk over a versioned HTTPS JSON API (`/api/v1/`), with calls signed by a per-project HMAC secret and a 5-minute replay window (SC-47). | L (was M2) | A2, SC-47 | T | N |  |
| IR-06 | The system shall receive mail over IMAP (993) and send over SMTP submission (587/465), accepting D1/D3 attachments only (FR-MAIL-03). | S0 (was M1) | [P1] §5, BD-04 | T | P |  |
| IR-07 | Hub and site shall exchange versioned-schema JSON messages signed with Ed25519, over HTTPS mutual TLS or over e-mail carrying the same signed payloads. | L (was M2) | SC-53 | T | N |  |
| IR-08 | The system shall sign users in through the hospital IdP by OIDC (authorization code + PKCE) or SAML 2.0. | H (was C) | A13, BD-01 | T | P (trusted header built) | Keycloak is the bridge if needed. |
| IR-09 | The system shall write encrypted backups to an SMB/NFS share or an S3-compatible store inside the hospital. | S0 (was M1) | FR-OPS-06 | T | P |  |
| IR-10 | After a reveal the system shall let the user copy the chart number, and open the EMR through a deep-link URL template when the site sets one. | S2 (was M1) | FR-SCR-04a | T | N |  |
| IR-11 | The system shall export PDF, XLSX and CSV in REDCap import format. | S0 (was M1) | A7, A36 | T | P |  |
| IR-11a | The system shall export FHIR NDJSON on request. | S0 (split from IR-11) | A7 | T | P |  |
| IR-11b | The system shall export OMOP CSV/Parquet. | L (split from IR-11) | A36 | T | N |  |
| IR-12 | The system shall use the ports of the TB-DS-02 §7 port table, the single source (N-19). | S0 (was M1) | N-19 | I | P | Gateway 8020, rc-bridge 8096. |

---

## 4. Verification approach

TB-DS-04 holds the full plan.

### 4.1 Build stage (S0–S5)

Each build step is one pull request (TB-DS-20). The step's PR is accepted when:

1. every row tagged with that step and every S0 row passes its verification: Ver T by automated tests in CI, Ver I/A/D by inspection recorded in the PR description;
2. `e2e_simple` (TB-DS-04) passes: criteria → feasibility report → approval → patient list → PI mail → REDCap status from the simulator, on the synthetic hospital (TB-DS-21). It is the only build gate;
3. at step 5, the model gate passes: NFR-PERF-08 (N-11) and NFR-PERF-09 (N-12), and FR-MOD-10 records the 32 GB fit.

### 4.2 Hospital stage (H)

Applies only when a hospital chooses to use real patient data (TB-DS-00 §2.H). Kept as written for that stage:

| Level | Method | Covers |
| --- | --- | --- |
| Unit and integration | Automated in CI on every commit | All requirements with Ver T |
| Access matrix | One generated test per AM-01 cell (role × action × in-scope / out-of-scope study) | AM-01, FR-UI-10, SC-14 |
| End-to-end, full (H) | One automated test: ingest → PHI pass → feasibility → approval → patient list → CASE → consent explainer going live automatically after the recorded ICF approval with hash check → screening-log export to the REDCap simulator, on synthetic JA and TW patients | S1–S5 and H FR paths, IR-01..03a |
| End-to-end with hub (L) | Adds pre-fill, External Module writes, visits and AEs, and two sites of one country with a hub (BD-06) | L FR paths, IR-03b..07 |
| Model gate | SIGIR, TREC CT 2021/22, MedTxt JA, PHI gate set, injection suite; later (L) the EDC pre-fill set; on the real GPU profile | NFR-PERF-08..10, 14, 15; FR-SEC-10 |
| Performance | Full-size dry run (500,000 synthetic patients, 20 and 50 studies) on 1 × and 2 × RTX 5090 | NFR-PERF-01..07, NFR-CAP |
| REDCap acceptance | Connector suite against the hospital's REDCap development instance | FR-RC |
| Security | Configuration review against TB-DS-03, third-party penetration test | NFR-COMP-01, 02, FR-SEC |
| Pilot, two phases (BD-16) | Phase 1 (weeks 1–6): recall by manual chart review of 100 patients per study (pilot-team time) and the FR-SCR-13 comparison; Phase 2 (weeks 7–12, after the week-6 checkpoint and committee approval): pre-screen time and net weekly time against the baseline (TB-TMPL-07), SUS, NASA-TLX descriptive | NFR-PERF-11..13, FR-REP-04, FR-SCR-13, NFR-USAB-06, 09 |
| Inspection | Position paper, DPIA, retention, licences, ethics approvals | NFR-COMP-03..08 |

**Release rule (hospital stage).** The first real-data release ships only if (1) every S0–S5 and H requirement passes its verification, except rows listed by name in the release notes with a waiver signed by the product owner, and no waiver may cover AM-01, FR-SCR-05, FR-SCR-06, FR-DEID-03, FR-DEID-11a, FR-MAIL-03, FR-AUTH-01b, FR-CON-06, NFR-PERF-08..11, NFR-PERF-14 or PO-01; (2) every model-gate row passes; (3) the ethics approvals of AS-03 are on file for each site. A later release applies the same rule to its L rows. The pilot dates are in TB-DS-00 §2.H.

---

## 5. Appendices

### Appendix A — Traceability from the product owner's answers (2026-11-07)

| # | Question (short) | Answer | Requirements |
| --- | --- | --- | --- |
| A1 | Meaning of "Lind" | Lind.care | Benchmark context only; no requirement |
| A2 | REDCap's role | Standalone, both options, deep integration | FR-RC-01..15, NFR-USAB-05, FR-UI-01 |
| A3 | REDCap at pilot sites | Yes, Japan head hospital and Taiwan | FR-RC-14, FR-ING-07b, AS-02 |
| A4 | Human confirms every EDC value | Yes | FR-EDC-05, FR-EDC-07, FR-EDC-08 |
| A5 | EMR data source and compliance | JP, TW and global compliance, customisable; SSI and Fujitsu | FR-ING-02..06, NFR-MAINT-03, DR-01 |
| A6 | FHIR server | Compare and recommend | DR-01, NFR-MAINT-02, CON-15, AS-05 |
| A7 | OMOP | Optional; flexible database | FR-OMOP-01..04, DR-02, FR-ING-09 |
| A8 | De-identification | GUID or variant; notes de-identified to global and local standards | FR-DEID-04..10, 15, NFR-PERF-14, NFR-COMP-03a/b, 08 |
| A9 | GUID scope | Cross-site consortium | FR-DEID-12..14, FR-FED |
| A10 | Single interaction / UX | Easy UI; criteria → feasibility report; after approval → patient list; e-mail or modern channel | FR-FEAS-01..07, FR-SCR-01..04b, FR-MAIL, NFR-USAB-01 |
| A11 | Hardware | 5090 with upgrade options, all local, efficient cross-site | FR-MOD-02, 03, NFR-PORT-01, FR-FED-05, 08 |
| A12 | Japanese customs | All, locally compliant | FR-JP-01..09, FR-DEID-05b/c, FR-UI-08a/b |
| A13 | Login | System login and REDCap login, hospital SSO optional | FR-AUTH-01..12, AM-01 |
| A14 | REDCap modules | All; asked about CI/CD | FR-RC-01..15, NFR-MAINT-04 |
| A15 | Scope | Recruitment and trial conduct | FR-TC-01..07 (L), FR-FED (L) |
| A16 | REDCap test server | Yes, but build our own; whole system e2e | FR-RC-09, 10, FR-EDCL-01..06, §4 e2e |
| P-HW | Hardware comparison, core-only option | Preference 00:17 | FR-MOD-02, 03, 07, BD-10 |
| P-ENTRY | Replaced by the role work list with a header command field (TB-REV-006f F6-06); it was the entry page with a simple chat box as default | Preference 00:17 | FR-UI-01, 02, FR-CHAT-01..07 |
| A17 | Build order | Full system (pilot scope per TB-DS-00 §2 pending owner decision) | §1.6 priorities, §4 |
| A18 | Peak concurrent users | 10 | NFR-PERF-01, NFR-CAP-03 |
| A19 | Chat | Simple, not full chat, upgradable | FR-CHAT-01..07 |
| A20 | Latency | Overnight fine; UI interactions need care | NFR-PERF-01..07, FR-MOD-04 |
| A21 | Data size | 500,000 patients | NFR-CAP-01, NFR-PERF-05 |
| A22 | Studies per site | Up to 20, CGMH 50 | NFR-CAP-02 |
| A23 | Who maintains the box | Hospital IT, with our engineering support | FR-OPS-03..09, NFR-AVAIL-01 |
| A24 | Consortium hub | Not answered | AS-06, OI-06 |
| A25 | First study | Early Alzheimer's (Japan) and rheumatology (CGMH) | §2.3, TB-DS-04 pilot plan |
| A26 | Pre-approval feasibility | Agreed | FR-FEAS-03, AS-03 |
| A27 | Taiwan EMR | CGMH self-developed; CGRD for de-identified feasibility | FR-ING-05, FR-FEAS-10 |
| A28 | Voice | No | §2.6 |
| A29 | Who pays | Academia first, pharma later | CON-10, §2.6 |
| A30 | Pricing | Free now | CON-10, NFR-COMP-07 |
| A31 | Pilot date | January 2027 | AS-08 (hospital stage; build plan has no date) |
| A32 | Team | One engineer, Japan team maintenance | CON-11, NFR-MAINT-01a/b, 05 |
| A33 | Non-device | Yes | CON-02, NFR-COMP-04, FR-UI-12 |
| A34 | Cybersecurity | Must comply; wants advice | NFR-COMP-01, 02, FR-SEC (TB-DS-03) |
| A35 | Retention | GCP period, ≥ 5 years | NFR-COMP-05, DR-08 (N-02, N-03) |
| A36 | Who receives feasibility reports | Site approves release | FR-FEAS-08, FR-REP-03 |
| A37 | Patient-level data to sponsors | No | CON-01, FR-REP-03, FR-FED-03 |
| A38 | Who contacts patients | Doctor | §2.1, §2.6 |
| A39 | Languages | All | FR-I18N-01..04, FR-CON-02 |
| A40 | Sponsor EDC integration | Not now, option | §2.6 (L) |
| A41 | Consortium governance | PI approves queries | FR-FED-02, FR-FED-07, AM-01 |
| A42 | Pilot success criteria | OK | NFR-PERF-11..13, FR-REP-04a–c |
| A43 | Manual chart review | Yes | NFR-PERF-11 |
| A44 | Name | "Branding Research" | OI-07 |

### Appendix B — Open issues

| ID | Issue | Owner | Needed by | Status | Raised |
| --- | --- | --- | --- | --- | --- |
| OI-01 | Medplum spike result (L) against HAPI + console accounts (CON-15) | Engineer | Before any later (L) identity work | Open (L) | 2026-11-07 |
| OI-02 | Real RTX 5090 run: time-shared judge/verifier swap time and accuracy (AS-04); replaces the capped RTX PRO 6000 baseline of NFR-PERF-08 | Engineer | Before hardware order | Open (step 5, FR-MOD-10) | 2026-11-07 |
| OI-03 | 500,000-patient full-size measurement and snapshot storage model (NFR-CAP-01, 05) | Engineer | Before pilot | Open (step 5 for synthetic size; H for a real box) | 2026-11-07 |
| OI-04 | Japanese PHI detector bake-off and licence of MedPHINER | Engineer | Before DEID build | Open (bake-off in TB-DS-05; tagger H) | 2026-11-07 |
| OI-05 | Ethics approvals at each site: pre-approval feasibility, two-phase pilot protocol (BD-16) and the week-6 Phase-2 approval, DPIA, consent-explainer process (AS-03). On the critical path; submission at least one committee meeting before January 2027 | Product owner | Before pilot | Deferred to hospital stage (H) | 2026-11-07 |
| OI-06 | Hub sites and year-one membership per country (A24 unanswered; BD-06) | Product owner | Before the FED build (L) | Deferred (L) | 2026-11-07 |
| OI-07 | Product name: "Branding Research" read as a naming study; trademark checks in JP/TW | Product owner | Before external materials | Open | 2026-11-07 |
| OI-08 | REDCap development instance and project read token at the Japan head hospital (AS-02) | Product owner | Before RC acceptance tests | Deferred (H); simulator covers the build | 2026-11-07 |
| OI-09 | SS-MIX2 availability and note export path for the head hospital's vendor (FR-ING-04a) | Hospital IT | Before ING mapping | Deferred (H) | 2026-11-07 |
| OI-10 | Target MedTxt JA recall above 69 % (earlier draft: 80 %) — reachable with 4-bit models on one 5090? The gap is the verifier's Japanese recall (Qwen3.5-9B 75.6 % JA vs 87.4 % EN alone; the gpt-oss-120b + Gemma 4 pair reaches 88 %). The one experiment that could move it is the step-5 Japanese fine-tune run (Medical-Qwen3-Swallow as verifier). Set a new gate only after measurement | Engineer | Pilot end | Open (step 5) | 2026-11-07 |
| OI-11 | Baseline staff time per manual pre-screen at each site (AS-09, N-17): two weeks of self-log (TB-TMPL-07) for 2 CRCs and 2 PIs plus one observed clinic half-day, outside 年末年始 and Lunar New Year (TB-PLAN-01 WP-00, MS-05b) | Site PI (owner); research office administers | Two weeks before each site's PQ | Deferred (H) | 2026-11-07 |
| OI-12 | Legal category of the Japan head hospital (private → APPI Chapter 4; national-university / national / public → Chapter 5) and the resulting basis for pseudonymised feasibility (NFR-COMP-03a) | Product owner with hospital legal office | Before ethics submission | Deferred (H) | 2026-11-07 |
| OI-13 | Counsel opinion on whether Bloom-filter encodings are personal data across borders (BD-06) | Product owner | Before any cross-border linkage | Deferred (L) | 2026-11-07 |
| OI-14 | Owner decision on the M1/M2/C split and the pilot dates of TB-DS-00 §2 (recommendation: TB-PLAN-01 Variant 1; on a decision card in the project thread) | Product owner | — | Closed: superseded by the build-stage rule (TB-DS-00 v0.8 §2, SIMPLE-PLAN) | 2026-11-07 |
| OI-15 | BD-13 and BD-14 decided by the owner (2026-11-07 03:10); BD-13 one-page approval (F6-07), BD-15 v0.5 (approved file in the record, committee-edit path, sponsor step) and BD-16..BD-20 proposed in TB-DS-00 v0.6 (BD-19 who approaches a candidate, BD-20 ethics gate for every identity-resolving study) — owner to confirm | Product owner | Now | Closed for the build: BD-15..BD-20 apply at hospital stage; reopen at first install | 2026-11-07 |
| OI-16 | PI device path per site: personal phone on hospital Wi-Fi/VPN, hospital phone, or clinic PC only; TOTP app allowed (TB-DS-15 PR-07, FR-UI-19) | Hospital IT lead | Site survey (MS-05) | Deferred (H) | 2026-11-07 |
| OI-17 | REDCap admin agrees to add `tb_screening_no` to each pilot study project, or the study uses the MRN alternative (BD-18) | Site PI with REDCap admin | Before RC acceptance tests | Deferred (H) | 2026-11-07 |
| OI-18 | Ethics committee practice on committee-edited explainers and on approving pilot Phase 2 (BD-15 (c), BD-16) | Site PI with ethics office | First committee response | Deferred (H) | 2026-11-07 |

### Appendix C — Glossary (EN / JA / zh-TW)

The single glossary of the design set. Other TB-DS documents refer here.

| Term | Meaning | Japanese | Traditional Chinese |
| --- | --- | --- | --- |
| ADR | Architecture decision record (TB-DS-02 §9) | アーキテクチャ決定記録 | 架構決策紀錄 |
| AE | Adverse event | 有害事象 | 不良事件 |
| ALCOA+ | Data-integrity principles: attributable, legible, contemporaneous, original, accurate, plus complete, consistent, enduring, available | ALCOA+原則 | ALCOA+原則 |
| APPI | Act on the Protection of Personal Information (Japan) | 個人情報保護法 | 日本個人資料保護法 |
| Appliance | The TrialBox server at one hospital (hardware + software) | アプライアンス | 院內設備 |
| Build tag | S0 built and kept working; S1–S5 build step; H hospital stage (real patient data only); L later (TB-DS-00 §2) | ビルドタグ | 建置標記 |
| Card | UI element with one model proposal, its quoted evidence and one primary action | カード | 卡片 |
| CASE | Single-patient eligibility check job | 単一患者チェック | 單一病人檢核 |
| CCB | Change control board (hospital stage); in the build stage the owner's merge of a step PR is the change decision (TB-DS-12) | 変更管理委員会 | 變更管制委員會 |
| CDIS / CDP | REDCap Clinical Data Interoperability Services / Clinical Data Pull | — | — |
| CGMH | Chang Gung Memorial Hospital, Taiwan pilot site | 長庚記念病院 | 長庚紀念醫院 |
| CGRD | Chang Gung Research Database (de-identified) | — | 長庚研究資料庫 |
| Chart number | Hospital medical record number (MRN) | カルテ番号 / 患者ID | 病歷號 |
| CLK | Cryptographic long-term key: one Bloom filter per record for PPRL | — | — |
| Concomitant medication | Other medicines the participant takes | 併用薬 | 併用藥物 |
| Coordinator | Code role for CRC, study nurse, SMO specialist (BD-03) | 治験コーディネーター (CRC) | 研究護理師 / 臨床研究協調員 |
| CRA | Clinical research associate: the sponsor's or CRO's monitor | モニター（CRA） | 臨床研究專員（CRA） |
| D0–D4 | Data classes: public, confidential without PHI, de-identified, pseudonymised, identified (CON-14) | データ区分 | 資料分級 |
| DAG | REDCap Data Access Group | — | — |
| DET | REDCap Data Entry Trigger: an HTTP call REDCap makes when a form is saved | データ入力トリガー（DET） | 資料輸入觸發（DET） |
| EDC / EDC-lite | Electronic data capture / TrialBox's non-regulated form system on FHIR Questionnaire | EDC | EDC |
| Eligibility criteria | Inclusion and exclusion criteria | 選択基準・除外基準 | 納入／排除條件 |
| EM | REDCap External Module | 外部モジュール | 外部模組 |
| Ethics committee | Committee approving the study | 倫理審査委員会 / 治験審査委員会 | 人體試驗委員會 (IRB) |
| Feasibility | Estimate of how many eligible patients a site has | 実施可能性調査 | 可行性評估 |
| Filter-first | Structured criteria by deterministic SQL/CQL; models only for notes (CON-04) | フィルター優先 | 先篩選 |
| Flow A / Flow B | Feasibility on pseudonymised data / patient list for an approved study | — | — |
| GUID | Consortium-wide pseudonymous patient identifier from PPRL | 共通仮名ID | 跨院假名識別碼 |
| Hub | The TrialBox instance coordinating the sites of one country (BD-06) | ハブ | 樞紐 |
| Identified zone | Part of the appliance where pids can be resolved to chart numbers (D4) | 識別領域 | 可識別區 |
| Informed consent | A person's voluntary agreement to take part in a study after the study has been explained to them | インフォームド・コンセント（同意説明） | 受試者同意 |
| Insurance-only diagnosis | Diagnosis recorded for billing | 保険病名 | 健保申報診斷 |
| Investigator | Code role for PI and sub-investigator (BD-03) | 治験責任医師 / 研究責任者 / 分担医師 | 計畫主持人 / 協同主持人 |
| IQ / OQ / PQ | Installation, operational and performance qualification of a site install (TB-DS-15; hospital stage) | 据付時／運転時／稼働性能適格性確認 | 安裝／操作／性能驗證 |
| Japanese era calendar | Year numbering by imperial era (令和7年 = 2025); dates in Japanese records may use it | 和暦 | 日本年號 |
| Judge / Verifier | Primary note-reading model / second independent model required before a note-based exclusion | 判定モデル / 検証モデル | 判讀模型 / 驗證模型 |
| Lake | DuckDB analytic store built from FHIR snapshots | データレイク | 資料湖 |
| Legally acceptable representative | A person authorised to consent on behalf of a patient who cannot consent | 代諾者 | 法定代理人 |
| MHLW GL | 医療情報システムの安全管理に関するガイドライン 第7.0版 | 安全管理ガイドライン | 日本醫療資訊安全指引 |
| Model gate | Fixed evaluation sets every model, prompt or quantisation change must pass | モデルゲート | 模型關卡 |
| Patient list | The list of likely candidates for an approved study (flow B), with the reason each fits | 候補患者リスト | 候選病人名單 |
| PDPA | Personal Data Protection Act (Taiwan) | 台湾個人資料保護法 | 個人資料保護法 |
| PHI | Personal information within clinical data | 個人を特定する医療情報 | 個人健康資訊 |
| pid | Site pseudonym: HMAC(site key, MRN) | 仮名ID | 假名碼 |
| PPRL | Privacy-preserving record linkage | — | 隱私保護紀錄連結 |
| Pseudonymised / anonymised information | APPI categories | 仮名加工情報 / 匿名加工情報 | 假名化資料 / 去識別化資料 |
| PV | Pharmacovigilance: detection and reporting of adverse drug effects | ファーマコビジランス | 藥物安全監視 |
| QS | Quality scenario: a stimulus, response and response measure for a quality attribute (TB-DS-02 §10) | 品質シナリオ | 品質情境 |
| Referral letter | Letter from one physician to another with the patient's clinical information | 診療情報提供書（紹介状） | 轉診單 |
| ROC calendar | Republic of China year numbering used in Taiwan (民國114年 = 2025) | — | 民國紀年 |
| Ruleset | Compiled, approved form of a study's criteria (IR, value sets, SQL, CQL, tests, manifest) | ルールセット | 規則集 |
| SAT | Site acceptance test (TB-DS-15; hospital stage) | 施設受入試験 | 院端驗收測試 |
| SBOM | Software bill of materials: list of all components and versions in a release | ソフトウェア部品表（SBOM） | 軟體物料清單（SBOM） |
| Screening log | The study's record of every patient screened, with screening number, dates, outcome and reason | スクリーニング名簿 | 篩選紀錄 |
| SDC | HL7 FHIR Structured Data Capture implementation guide for forms | 構造化データ収集（SDC） | 結構化資料擷取（SDC） |
| Shadow mode | Older name for pilot Phase 1 only (BD-16): staff screen as usual; TrialBox lists are additive and compared. Phase 2 is TrialBox-first with a spot-check | シャドーモード | 影子模式 |
| SMO | Site management organisation | 治験施設支援機関 | 試驗場所管理機構 |
| SS-MIX2 | Standardized Structured Medical record Information eXchange 2 | SS-MIX2 | — |
| STRIDE | Threat categories: spoofing, tampering, repudiation, information disclosure, denial of service, elevation of privilege (TB-DS-03) | STRIDE脅威分類 | STRIDE威脅分類 |
| Suspected diagnosis | A diagnosis recorded with the 疑い (suspected) modifier; not a confirmed diagnosis | 疑い病名 | 疑似診斷 |
| TC / TS | Test case / test suite identifiers in TB-DS-04 | テストケース／テストスイート | 測試案例／測試套件 |

### Appendix D — Crosswalk from spec-v4 test-marker IDs to TB-DS-01

The tests at `a1e55fa` carry 239 `@pytest.mark.req("…")` markers; 238 cite 136 distinct spec-v4 IDs [P8] and one is the documentation placeholder `<ID>`. The table maps each to its TB-DS-01 row. "Design" = an engineering rule kept in TB-DS-02 or TB-DS-04 with no SRS row; "Retired" = the spec-v4 feature is not in the M1/M2/C baseline (the tests stay as regression tests of disabled code until removed by a recorded decision). Counts in brackets are markers per ID.

| Spec-v4 IDs (markers) | Spec-v4 subject | TB-DS-01 |
| --- | --- | --- |
| CAS-1 (10), CAS-14 (1), CAS-15 (2) | Cascade stages S0–S5 recorded per run; S2b embeddings via gateway | FR-SCR-01 |
| CAS-2 (1) | Structured criteria never sent to a model | CON-04, FR-SCR-05 |
| CAS-4 (1) | Per-run model budgets | Design (TB-DS-02) |
| CAS-7 (1) | Cascade metrics in the manifest | FR-REP-01 |
| CAS-8 (1), FR-M3-2 (2), RPT-22 (2) | Feasibility samples model stages; estimate with 95 % interval | FR-FEAS-03, FR-FEAS-04c |
| CAS-10 (2), DM-16 (2), SAFE-10 (2), SAFE-12 (2), SAFE-14 (3), SAFE-16 (1), S1-12 (5) | Recall certificate, recall ledger, anytime-valid bounds | Design (TB-DS-04 recall monitoring); no SRS row — see note 3 |
| CAS-12 (1) | Zero S2 hits go to S2b; absence semantics | FR-SCR-11 |
| CAS-16 (2) | Multi-span evidence, each span verified | FR-SCR-06 |
| SAFE-13 (5) | What is never an exclusion | FR-SCR-05, FR-SCR-12 |
| DM-01 (1), DM-10 (2), DM-11 (3) | JSON-Schema contracts; canonical criterion hash; criterion library | Design (TB-DS-02) |
| DM-02 (5) | IR versions run unchanged until recompiled | DR-04 |
| DP-01 (1), DP-39 (2) | Data-platform stages; lineage events | Design (TB-DS-02) |
| DP-04 (5), S1-02 (5) | Write-once landing with manifest and sha256 | FR-ING-08b, FR-ING-17, FR-ING-18 (note 4) |
| DP-18 (2), DP-19 (2), DP-20 (2), S1-03 (4) | Data contracts, reconciliation, publish gate keeps previous snapshot | FR-ING-10, FR-ING-17, FR-ERR-04 |
| DP-22 (1), DP-23 (1), DP-25 (3) | DQ rule categories, OSI licences, planted-defect suite | FR-ING-10, NFR-COMP-07, Design (TB-DS-04) |
| DP-32 (2) | Iceberg tables | Retired (lake is DuckDB per snapshot, DR-03) |
| DP-35 (2), S1-04 (7), PRIV-10 (3) | pid = HMAC; MRN → pid; key handling | FR-DEID-01, FR-DEID-02, FR-SEC-02 |
| ENG-01 (1), ENG-05 (1), ENG-08 (5), ENG-09 (1), ENG-16 (6), S1-13 (7), VV-12 (1) | Repo layout, marker validation, pinned images, environments, dataset classes, public suites, MIMIC e2e | NFR-MAINT-01a/b, NFR-MAINT-04, Design (TB-DS-04) |
| ENG-04 (6), MOD-4 (1), LLM-22 (2) | Every model call through the gateway, schema-constrained, deterministic sampling | FR-MOD-05 |
| FR-CONV-1 (1), FR-CONV-2 (5), FR-CONV-7 (1), FR-UX-10 (5), S1-10 (8) | Intake order, typed intents, native parity, one grammar | FR-CHAT-01..03, FR-CHAT-02 |
| FR-CONV-3 (1) | Proposals expire; OK confirms only an open proposal | FR-CHAT-05 |
| FR-CONV-6 (2), FR-WF-1 (5), FR-WF-9 (3) | State survives restart; exactly-once delivery; leases | FR-ERR-01 |
| FR-CONV-8 (4), LLM-33 (3), PRIV-15 (4), NFR-B12 (1), S1-06 (12) | Class of model calls; D0-only development route; D3/D4 never external | CON-08, CON-14 |
| FR-CONV-14 (2) | External senders quarantined | FR-MAIL-01 |
| FR-CONV-16 (3) | Every turn attributable in the audit ledger | FR-AUD-01a |
| FR-WF-3 (1) | Step identity covers inputs and versions | FR-REP-02 |
| FR-M5-7 (1) | Registry-trial ranking (NAV job) | No SRS row — see note 3 |
| FR-M5-9 (7) | Registry retrieval only over the local mirror | CON-01 |
| FR-M5-14 (4) | Benchmark mode SIGIR / TREC | NFR-PERF-08, NFR-PERF-09 |
| FR-SIG-14 (2) | ASVS level for signing page and admin console | NFR-COMP-01 (ASVS 5.0 L2); signing page retired (CON-07) |
| FR-UX-9 (1) | No PHI in message bodies | FR-MAIL-03 |
| FR-UX-11 (1) | Teams and LINE | C (§2.6) |
| FR-UX-12 (4), FR-UX-21 (2) | Surface inventory; admin plane renders no PHI | AM-01 |
| FR-UX-32 (1) | Message catalogues for all strings | FR-I18N-01 |
| HER-1..HER-26, HER-37 (72 in total), OPS-02 (2), S1-09 (8), S1-11 (19) | Hermes agent and its front-door MCP server | Retired: the command box is a grammar parser (FR-CHAT-01..07, SC-65). Safety intents carried over: HER-3 → FR-CHAT-05; HER-9 → AM-01; HER-14 → FR-AUD-01a |
| LLM-1 (3), LLM-2 (5), LLM-3 (2), LLM-4 (4), LLM-7 (1), LLM-11 (1), LLM-12 (3), LLM-48 (1), NFR-B9 (3) | Gateway is the only model path, fails closed, policy file, property tests | CON-08, FR-SEC-09, Design (TB-DS-02) |
| LLM-5 (1), LLM-46 (1) | Call record in the ledger before return; traces are not the audit trail | FR-AUD-01a, FR-MOD-05 |
| LLM-15 (1), PRIV-29 (6) | PHI tripwire at every boundary | FR-SEC-07 |
| PRIV-30 (2) | PHI guard recall ≥ 0.98 on names and identifiers | NFR-PERF-14 (N-07 metric replaces it; note 5) |
| LLM-30 (1), S1-14 (16), MOD-8 (1) | Public suites on prompt/model change; bake-off; model cards | FR-MOD-06 |
| LLM-41 (4), LLM-45 (4), S1-08 (5) | Cache limits; no identifiers in traces; trace redaction and extended identifier rules | FR-LOG-02, FR-DEID-05c |
| MOD-6 (6), MOD-7 (6), S1-07 (18) | Served build echoed in manifests; immutable builds; model registry | FR-REP-01, FR-MOD-05, FR-MOD-08 |
| PRIV-13 (2) | Every object carries a data class | CON-14 |
| RPT-05 (3), RPT-06 (5), RPT-07 (1) | Disclosure profile per recipient; suppressed cells not recoverable | FR-DEID-11a, FR-DEID-11b |
| RPT-32 (1), RPT-33 (1) | Report sections and headline numbers | FR-FEAS-04a–i |
| RPT-35 (1) | Logic text not released by default | FR-FEAS-08 |
| S1-16 (10) | `trialbox doctor` checks | FR-OPS-04 |
| SEC-40 (2) | Deny-by-default egress | FR-SEC-13 |
| SEC-63 (3), SEC-64 (1) | Model intake verification; weights verified at load | FR-MOD-08, FR-SEC-04 |

Notes:

1. **Marker migration.** Keep `@pytest.mark.req("<spec-v4 ID>")` as it is until code work starts, because ENG-05 validates markers against the spec-v4 IDs. When code work starts, (a) add a marker `@pytest.mark.srs("<TB-DS-01 ID>")` using this table, (b) extend `tools/trace_matrix.py` to read both and fail CI on an SRS ID that does not exist in TB-DS-01, (c) once every test carries an `srs` marker, drop the spec-v4 validation. Retired rows keep their `req` marker until the tests are removed by a recorded decision.
2. **ID collisions.** SPEC.md / SPEC_v3 used IDs such as SEC-3, LLM-33 and FR-M11-2; spec v4 reuses SEC-nn and LLM-nn with other meanings. The markers above are spec-v4 IDs. TB-DS-03 therefore names its controls SC-nn, which no earlier spec uses.
3. **Gaps found by the crosswalk.** Two built behaviours have tests but no TB-DS-01 row: the recall certificate / recall ledger (CAS-10, SAFE-*, S1-12) and the NAV registry-trial ranking (FR-M5-7). They are left to TB-DS-04 (recall monitoring) and to the owner's scope decision (OI-14); add rows if the owner keeps them in a build step (the build map, TB-DS-20, decides).
4. **Landing retention.** DP-04 says raw objects are crypto-shredded after 90 days; FR-ING-18 (SC-34) requires at most 7 days. FR-ING-18 governs; the DP-04 test must be updated when code work starts.
5. **PHI metric.** PRIV-30 (recall ≥ 0.98 per class) and N-07 (span leak ≤ 0.5 % and zero direct identifiers) differ. N-07 is canonical (TB-DS-00); the PRIV-30 test stays as an additional detector-level check.

---

## Change history

| Seq | Version | Date | Author | Change |
| --- | --- | --- | --- | --- |
| 1 | 0.9 (old scheme, TB-SRS-001) | 2026-11-07 | Claude | First full draft from report v7, answers A1–A44, master `a1e55fa`, D-01..D-105. |
| 2 | 0.2 (TB-DS-01) | 2026-11-07 | Claude | Renumbered under the TB-DS scheme (TB-DS-00 §1); version restarted at 0.2 to match the set. Applied review TB-REV-006: priorities re-tagged M1/M2/C per TB-DS-00 §2 with no conditional priorities (F-01, F-51); every TB-DS-00 number written with its N-nn citation (F-08..F-15, F-21, F-40, F-44, F-57) … (full detail in the review record cited). |
| 3 | 0.2a (TB-DS-01) | 2026-11-07 | Claude | TB-REV-006b: FR-ING-03 drops SIU^S12, new FR-ING-03b appointment source (R2-09); FR-AUTH-13 and AM-01 approval target per BD-13 (R2-02); FR-SEC-11 withdrawn as duplicate of NFR-COMP-02 (R2-15); FR-UI-10 status P (R2-16); scope sentence, priority note, AS-08, release-rule note and OI-14 cite TB-DS-00 pilot dates (R2-01); OI-15 added. |
| 4 | 0.3 (TB-DS-01) | 2026-11-07 | Claude | Clinical workload pass with TB-DS-17 and TB-DS-00 v0.4: new FR-FEAS-11/12 (LLM drafts ruleset from protocol with source quotes; one-page PI approval, BD-13 decided); FR-CON-01 and FR-CON-06 rewritten and FR-CON-07/08 added for BD-15 v0.4 (explainer generated from and submitted with the ICF, released automatically, no manual release, switch-off, regenerated on amendment); AM-01 rows for ruleset approval and explainer updated; OI-15 updated … (full detail in the review record cited). |
| 5 | 0.4 (TB-DS-01) | 2026-11-07 | Claude | TB-REV-006c clinical pass with TB-DS-00 v0.5: research office and treating physician in §2.1 (C-13, C-18); FR-FEAS-12 two sign-offs (C-09); FR-SCR-07 one mark vocabulary with per-study reasons and "Not now" (C-10); FR-SCR-07b Ask treating doctor (C-13), 07c CRC-notified status (C-14); FR-SCR-10a ICH E6(R3) log with screening_no, 10c contact outcomes (C-06); FR-SCR-12 pre-/post-consent wording (C-15) … (full detail in the review record cited). |
| 6 | 0.5 (TB-DS-01) | 2026-11-07 | Claude | TB-REV-006d: §1.2, §1.6, AS-03, AS-08, OI-05 and glossary describe the two-phase pilot; "shadow mode" = Phase 1 only (D-01); §1.6 cites the TB-DS-00 §2 M1 content-by-date table (D-02); FR-STUDY-03 reconciliation and FR-ING-19/21 personal-database import M2 (D-02); §1.3 and §2.2 rows 18–19 name the clinical layer (D-17); EDC-lite and FR-EDCL-01..05 tagged C, EDC wording marked C (C-27, D-14) … (full detail in the review record cited). |
| 7 | 0.6 (TB-DS-01) | 2026-11-07 | Claude | TB-REV-006e: FR-SCR-07b/07c from the release before pilot week 7 with go-live fallback (E-01); FR-SCR-13 via ICD-14 `shadow_log`, FR-ING-19 no longer describes an M1 behaviour (E-04); FR-STUDY-10 section labels match S21 (E-05); baseline TB-DS-00 v0.7; history sorted (E-07). |
| 8 | 0.7 (TB-DS-01) | 2026-11-07 | Claude | Completeness audit: new §3.1.29 FR-PLAT-01..30 (platform pages and supporting functions, TB-DS-19); 29 M1, 1 M2. |
| 9 | 0.8 (TB-DS-01) | 2026-11-07 | Claude | TB-REV-006f: Pri column re-tagged S0–S5 / H / L per `20-build-map.md` with the old tag kept as "(was …)"; §1.2 and §1.6 describe the build stage; FR-UI-01 home = role work list + header command field (F6-06); FR-STUDY-06 gate is a site setting, off in DEV/TEST (F6-03); FR-FEAS-12 one page, one Approve, Changes since vN (F6-07, F6-27); FR-SCR-07 mark replace; FR-CHAT-01, NFR-USAB-08 (no TOTP in tap budgets, F6-04), FR-PLAT-12 Retry; new FR-FEAS-13, FR-RC-17, FR-OPS-11/12, FR-MOD-10, §3.1.30 FR-SYN-01..04. Document frozen as reference. |
| 10 | 0.9 (TB-DS-01) | 2026-11-07 | Claude | TB-REV-006f §R: FR-SEC SC column restored and tag moved into Pri (N7-01); DR/IR rows tagged S0–S5/H/L (N7-02); NFR-USAB-08 back to S2 (N7-03); FR-AUTH-02 five roles (F6-19); FR-UI-14 header field, S17 H (N7-07); FR-ING-01 follows FR-OPS-12 (F6-30). §2.2 function table Release column re-tagged. |
| 11 | 0.10 | 2026-11-07 | Claude for Aimedics | TB-REV-006g (Q-02, Q-06..Q-09, S-02, S-03, S-05, S-08): Notes column on every requirement table; 29148 pass splitting compound rows with letter suffixes (45 new rows, IDs stable), fit criteria (FR-ING-04a, FR-ING-13, FR-CHAT-01, FR-JP-06, FR-LOG-02, FR-DEID-13), examples and status prose moved to Notes; FR-MOD-10 moved to MOD; CON-17/18; new §2.7 project obligations PO-01..03 (NFR-COMP-02/-08 withdrawn as pointers); §3 legend and §4 split into build stage and hospital stage; App B Status/Raised; App C 14 terms and 8 missing meanings; entry-page and two-sign-off wording removed; Seq column. |
| 12 | 0.11 | 2026-11-07 | Claude for Aimedics | TB-REV-006g §R pass 2: second 29148 pass, about 120 new rows by letter suffix with existing IDs stable (every row with two or more independently testable "shall" split; DR and IR rows rewritten as "shall" statements; stage prose such as "later (L)" moved out of Requirement cells into Notes; implementation names such as sqlglot and scrypt moved to Notes; Fit criteria added where a row said "support"); FR-SCR-13 process prose moved to TB-DS-04 §8.9; FR-SEC-11 points at PO-01; one layout for withdrawn rows (§1.6); §1.1, AS-03, AS-04 and AS-08 in build-stage terms. TB-REV-006f §8: CON-12/13 name Gemma 4 26B-A4B (NVFP4) as judge and Qwen3.5-9B (AWQ 4-bit, thinking off) as verifier, both Apache 2.0; NFR-PERF-08 adds zh-TW ≤ 2 provisional and records the 6 Nov configuration (RTX PRO 6000 capped to 5090 limits, vLLM v0.32.0; file hashes not recorded); NFR-PERF-09 TREC figure labelled a projection, gate judged on the point estimate; AS-04 no longer claims time-sharing was measured (35 GiB resident is mostly vLLM pre-allocation); FR-MOD-10 requires the serving-configuration record; OI-10 verifier JA gap. Sampled with seven seeded 40-row draws; the last two found 3/40 and 1/40 defects, all fixed. |
| 13 | 0.12 | 2026-11-07 | Claude for Aimedics | TB-REV-006g §F F-03, F-04: NFR-COMP-01 names the TB-DS-03 §4 controls by build tag; FR-SEC-05 split (05a PHI scan), the hospital-IT review moved to TB-DS-04 §9.5; FR-SCR-09 and NFR-USAB-02 "— (was M1)"; §1.6 "split in v0.10 or later". 601 rows. |

*End of TB-DS-01.*
