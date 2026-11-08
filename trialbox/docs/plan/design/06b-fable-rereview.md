# TrialBox design set — independent re-review (round 2)

| Field | Value |
| --- | --- |
| Document | TB-REV-006b, Independent re-review of the TrialBox design set after the TB-REV-006 fixes |
| Reviewer | Fable (independent: clinical informatics architecture + software quality / regulatory audit) |
| Date | 2026-11-07 |
| Reviewed | `00-baseline-decisions.md` (TB-DS-00 v0.2), `00-document-register.md` (TB-DS-00R v0.2), `01-SRS.md` (TB-DS-01 v0.2), `02-architecture.md` (TB-DS-02 v0.2), `03-security-privacy.md` (TB-DS-03 v0.2a), `04-verification-operations.md` (TB-DS-04 v0.2), `05-open-source-reuse.md` (TB-DS-05 v0.2), `07-data-dictionary.md` (TB-DS-07 v0.1), `08-interface-control.md` (TB-DS-08 v0.1), `09-ui-ux-spec.md` (TB-DS-09 v0.1), `10-terminology-mapping.md` (TB-DS-10 v0.1), `11-risk-management.md` (TB-DS-11 v0.1), `12-configuration-management.md` (TB-DS-12 v0.1), `13-project-plan.md` (TB-PLAN-01 v0.1), `14-ethics-pack.md` (TB-TMPL-01 v0.1), `15-site-acceptance-protocol.md` (TB-DS-15 v0.1a), `16-regulatory-position.md` (TB-DS-16 v0.1); `../trialbox-architecture/trialbox-redcap-fhir.html` (report v7, unchanged) |
| Baseline for the status table | TB-REV-006 (`06-fable-review.md`): findings F-01..F-62, conflicts X-01..X-40, missing items M-01..M-22 |
| Checked against | repository `zandis/Auto-GPT`, `trialbox/` at master `a1e55fa` (read-only): `services/console/auth.py`, `services/console/app.py`, `services/console/home.py`, `libs/tb_common/smallcell.py`, `libs/tb_common/objstore.py`, `services/llm_stub/handlers.py`, `services/channels/`, `services/orchestrator/scenarios/retention.py`, `docs/DECISIONS.md`, `docs/HARDENING.md`, `deploy/check_host.sh`, `deploy/docker-compose*.yml`, test and marker counts |
| Status | Review only. No other file was changed. New findings are numbered R2-nn so they can be cited beside the F/X/M numbers. |

---

## 1. Summary

The set has moved from a well-shaped draft to something close to a baseline. Of the 124 items raised in TB-REV-006, **93 are closed, 20 are partly closed and 11 are open** (section 2). All seven Critical findings are closed or reduced to one owner decision. The two clinical-governance gaps (consent explainer, AE dismissal) are settled by recorded decisions. One ID scheme, one numbers table (TB-DS-00 N-01..N-19), one data classification, one access matrix, one port table and a 239-marker crosswalk now exist and, where I checked them against the repository, they are accurate (roles, password length, lockout, sessions, small-cell default, test and marker counts, D-99 absence, TPM warning-only). Eleven of the thirteen documents I listed as missing have been written, and the remaining ones are in the register with owners and dates.

What still stops me from calling the set baseline-able today is smaller than last time but real:

1. **The January scope is written three ways.** TB-DS-00 §2 (M1) and the SRS M1 tags say: chat command box, full PHI pass (rules + NER + LLM tagger), REDCap read connector, pentest and site acceptance at **both** hospitals by January 2027. TB-PLAN-01 shows that this is 657 h against 330 h and recommends Variant 1: tiles only, PHI pass rules + NER, Japan first (≈ 8 Feb), CGMH ≈ 15 Feb. The register already dates the missing documents to Variant 1. OI-14 (owner decision) is still "pending". Until the owner decides, the SRS release rule, the VVO gates, the SAT dates and the ethics timetable each rest on a different scope.
2. **Who approves a ruleset is answered three ways** (new finding R2-02): the code and SRS AM-01 say the coordinator (admin too, as built); TB-DS-03 §5.2, TB-DS-07 §7, TB-DS-11 H-01 and TB-DS-12 §2 say the site PI / investigator. This is the one authorisation that decides which criteria run against patients, and a GCP reviewer will ask.
3. **A consistency pass was not finished in four documents.** TB-DS-03 still carries pre-decision sentences (Medplum as the pilot FHIR store in §1.1 and K3, per-user REDCap tokens in the §6 key table, "NFR-SEC" in §9, a backup table that puts SQLite stores in Postgres and leaves month-end snapshots unrecoverable); TB-DS-05 still picks "EDC-lite on Medplum" against Arch ADR-04; TB-DS-04 still speaks of "Should-level" rows and "OMP-O09/SIU" messages; TB-TMPL-01 §3 describes a data-class scheme that is not BD-02. None of these is hard to fix; all of them are the kind of thing a hospital security officer or privacy office reads first.
4. **External inputs that no document can replace**: ethics committee meeting dates at both hospitals, the Japan head hospital's legal category (OI-12), its export specification and SS-MIX2 layout (IC-01), CGMH's warehouse views (IC-03), a REDCap development server, a GPU test box, a pentest firm, and counsel review of TB-DS-16 and the APPI / PDPA bases.

My estimate: the document work in (2) and (3) is **two to three working days**; (1) is a decision the owner can take this week; (4) is calendar time the plan already shows. After that the core documents (TB-DS-00, 00R, 01, 02, 03, 04, 07, 08, 11, 12, 15) can be issued as 1.0 for the hospital IT review and for an engineer joining. The ethics pack can go to the PIs as soon as its §3 is corrected and the privacy offices have read it; it does not need the whole set baselined.

---

## 2. Status of every TB-REV-006 item

Status words: **closed** = fixed in the set as written (residual notes in the line); **partly** = fixed in part, or fixed in some documents while another still contradicts; **open** = not fixed, or waits on something outside the documents. "Where" names the document and section that carries the fix.

### 2.1 Findings F-01..F-62

| ID | Status | One line |
| --- | --- | --- |
| F-01 | partly | M1/M2/C split done (TB-DS-00 §2, SRS tags, release rule); but TB-DS-00 M1 ≠ TB-PLAN-01 Variant 1 and OI-14 is still an open owner decision (R2-01). |
| F-02 | partly | Decided: HAPI + console-native TOTP (BD-01, ADR-14; SRS, VVO, OSS aligned); TB-DS-03 §1.1, K3, area table "EDCL on Medplum" and §6 key table still carry the old text (R2-03). |
| F-03 | closed | D0–D4 only; TB-DS-03 §2 maps zones Z0–Z6 onto networks and volumes; TB-DS-07 §2.1 uses the same table. (TB-TMPL-01 §3 regresses it: R2-05.) |
| F-04 | closed | Owner decision recorded (BD-07): requester may release, but only when the content hash equals the ethics-approved version (SRS FR-CON-06, TB-DS-09 S9, TB-DS-11 H-11, TB-TMPL-01 §6). PI-only release not adopted; risk accepted and recorded. |
| F-05 | closed | SRS §1.3 and AM-01 re-audited against `a1e55fa` (five roles, `auditor` M1, lockout B, TPM documented not enforced); PR #22 no longer cited in design documents; D-99 repo entry is a P1 register item (TB-DS-00R §3). |
| F-06 | closed | SRS Appendix D crosswalk: 239 markers, 136 distinct IDs (I count 136); controls renamed SC-NN; marker migration planned. |
| F-07 | closed | Ethics on the critical path: TB-PLAN-01 MS-04 (submit 2026-11-20) / MS-11 (approval by 2027-01-15), TB-TMPL-01 pack, VVO §12 two-pass pentest. Committee dates themselves are still an external input. |
| F-08 | closed | N-01 k = 10 external / 5 internal; SRS FR-DEID-11a/b; VVO TC-DEID-047 now 10; code default 5 confirmed. |
| F-09 | closed | N-02 audit 10 years everywhere checked (SC-73, TB-DS-07 R-AUD, VVO). |
| F-10 | closed | N-05 30 min / 8 h; N-06 5 → 15 min; `auth.py` IDLE 30, ABSOLUTE 8 h, MAX_FAILURES 5, LOCKOUT 15 confirmed. |
| F-11 | closed | One metric (N-07) in SRS NFR-PERF-14, TB-DS-03 §13.6, VVO G5/OQ-12, TB-DS-15 OQ-12 (200 notes). |
| F-12 | partly | N-08 ±182 d, D2 only, M2 (SRS FR-DEID-07). Arch §6.1 sequence still says "date shift for D3/D2 copies" and the `shift_days` row is tagged [target, M1] (R2-18). |
| F-13 | closed | N-09 / N-10 in SRS; Arch cites. |
| F-14 | closed | N-11 / N-12 in SRS; Arch §8.9 cites. |
| F-15 | closed | N-15 RTO 2 working days. |
| F-16 | closed | SRS AM-01 with an ID; TB-DS-03 §5.2 investigator "Yes, audited"; matches `can_view_phi` and D-104. |
| F-17 | closed | SRS FR-MAIL-03 "never D4" (status P: built encrypted attachments to be removed); SC-45, T15 agree. |
| F-18 | closed | BD-06 one hub per country (ADR-15); VVO fixture two JP sites + TW counts-only. |
| F-19 | closed | Real NFR family names in Arch §10; residual "NFR-SEC" in TB-DS-03 §9 row "Requirements" (R2-03). |
| F-20 | closed | SRS FR-SEC-01..13 with SC references; TB-DS-03 controls carry an SRS-ID column. |
| F-21 | partly | Capacity numbers now labelled estimates and Arch §7.5 has a capacity model, but nothing is measured yet and BD-10 fixes the hardware (256 GB / 8 TB) before P7; keep as a plan risk, not a document defect. |
| F-22 | closed | BD-11 night schedule (22:00 ingest, 23:30–02:00 PHI pass, 02:00–05:30 screening); Arch §6.1/§6.10 agree; current 02:00 job marked built. |
| F-23 | closed | BD-05 / ADR-13: project-level read token in M1, writes through the module under the user's session in M2 (TB-DS-08 ICD-04/05/07). Stale "REDCap per user" row in TB-DS-03 §6 (R2-03). |
| F-24 | closed | BD-08; SRS FR-TC-03/04; TB-DS-09 S11; TB-DS-11 H-06: investigator tasks, investigator-only dismissal with reason. |
| F-25 | closed | DR-09 M1; TB-DS-03 §11.5 erasure pipeline; TB-DS-07 §8; consortium recomputation documented. |
| F-26 | closed | SRS [S12] MHLW GL 第7.0版, [S15] ASVS 5.0; NFR-COMP-01 cites both. |
| F-27 | open | Report v7 unchanged (hardware tiers vs revised recommendation, RAM, cost). Accepted as "informative, superseded in detail" in TB-DS-00R; a one-line banner in the report itself would prevent a hospital reading the wrong box (R2-21). |
| F-28 | closed | TB-DS-nn scheme (TB-DS-00 §1), register TB-DS-00R, control tables and approval blocks in every document, TB-DS-12 §6 document control. |
| F-29 | closed | Compound rows split, conditional priorities removed, model/detector choices moved to CON-/Arch (spot-checked FR-DEID, FR-TC, FR-CHAT, FR-MAIL, NFR-PERF rows). |
| F-30 | closed | TB-DS-07 data dictionary (26 stores, tables, classes, PII flags, retention); Arch §8.16. |
| F-31 | partly | WBS with hours exists (TB-PLAN-01) and is honest about 2× capacity; the plan is not yet resolved (Variant 1 recommended, decision pending) and its Variant 1 arithmetic is off (R2-10). |
| F-32 | closed | VVO TC-EDC-007 "stays 1 (Unverified), never 2". |
| F-33 | closed | HbA1c 3D045/3D046 in TB-DS-10 §5 and VVO TC-ING-031; terminology specification exists (TB-DS-10). |
| F-34 | partly | Arch §8.13.1 path (two 3-digit levels) and message table corrected against JAMI Ver.1.2h and says SS-MIX2 has no appointment type; SRS FR-ING-03 and TB-DS-08 ICD-02 still list SIU^S12 for SS-MIX2 (R2-09). |
| F-35 | closed | FR-AUTH-06 B; SC-15 status corrected. |
| F-36 | closed | "TPM sealing documented, not enforced" (SRS DR-07, §1.3); `check_host.sh` only warns — confirmed. |
| F-37 | closed | BD-09 / ADR-16 (filesystem object store, Mailpit); Arch §7.2, SRS, VVO updated; compose still runs MinIO — that is M1 build work (WP-08), correctly tagged. |
| F-38 | partly | CKIP dropped from TB-DS-03 §13.3 (GPL); TB-DS-05 §6 still does not survey a zh-TW NER alternative, so the Taiwan PHI pass has no named component. |
| F-39 | closed | FR-CHAT-04 "shall not start any job"; TB-DS-08 ICD-09 model proposal always `confirm`. Residual wording "the built `classify_intent`" (R2-19). |
| F-40 | closed | N-13 single-patient check ≤ 60 s; SRS, Arch, TB-DS-09 S7, TB-DS-15 PQ-05 agree. |
| F-41 | closed | BD-03 canonical roles (five built + `auditor`), affiliations separate; SEC §5.2 and VVO §3.5 cite. |
| F-42 | partly | §7.2 is now one table with gateway 8020, rc-bridge 8096, MinIO removed; Annex A.3 ("every container in a runtime view") is still not met (reverse proxy, embed-service, llm-stub, fed-agent absent from §6). |
| F-43 | closed | SRS §1.3 and TB-DS-03 state 669 test functions / 239 markers (I count the same); report unchanged (informative). |
| F-44 | closed | QS-16/17 marked targets; QS-9 now cites N-17, but also the withdrawn NFR-USAB-02 (R2-17). |
| F-45 | closed | TB-DS-03 §11.2 Taiwan basis for identified lists rewritten to HSRA/IRB with [LEGAL]; as far as checked. |
| F-46 | partly | Hospital legal category is now an assumption (OI-7 / SRS OI-12) and the DPIA splits by category; the article cited for Chapter 5 differs between §2.1 ("Art. 121") and §11.1 ("Arts. 73 ff.") (R2-11). |
| F-47 | partly | SAT protocol written (TB-DS-15); test design specifications (TB-TDS-nn) and completion-report template (TB-TMPL-06) are register items, not yet written. |
| F-48 | partly | IQ/OQ/PQ labelled and written as a protocol (TB-DS-15); supplier assessments for category-3/4 components still absent (SC-04 "Partial"; TB-DS-12 CI-3P lists them but assesses none). |
| F-49 | closed | SRS FR-ERR-01..08, FR-LOG-01..04; TB-DS-08 §2.2 error model. |
| F-50 | closed | Arch §7.2/§7.3 egress and EMR/DWH rows added; as far as checked. |
| F-51 | closed | FR-FED/EDCL/TC re-tagged M2 / C. |
| F-52 | open | TB-DS-05 §3 still cites the December 2016 Wikipedia list for SNOMED membership; "(unverified)" cells still feed Use/Reject verdicts. |
| F-53 | closed | TB-DS-09 UI/UX specification (screens S1–S15, card state machine, keyboard map, i18n, states, accessibility). No wireframes, which is acceptable for a text specification. |
| F-54 | closed | SRS FR-AUTH-11 and TB-DS-03 §5.2: CRO accounts off by default, enabled per site with investigator approval. |
| F-55 | closed | Arch §5 headings use C4 names. |
| F-56 | partly | Arch §12 glossary still exists beside SRS Appendix C; not re-checked for drift; low value either way. |
| F-57 | closed | NFR-PERF-08 states the RTX PRO 6000 proxy and the pending real-5090 run. |
| F-58 | closed | TB-DS-03 §13.2 cat. 7 lists old and new ARC formats. |
| F-59 | closed | FR-DEID-13 levels U I G in VVO §6.2. |
| F-60 | closed | Arch §6.2 now "subject to AS-03 / OI-05". |
| F-61 | closed | VVO E10 criterion-level agreement (kappa and %), SRS FR-REP-04. |
| F-62 | closed | Arch §6.4 "Built today: weekly microbatch … [target, M1] nightly incremental". |

### 2.2 Conflicts X-01..X-40

| # | Status | One line |
| --- | --- | --- |
| X-01 | closed | One classification (D0–D4), zones mapped (F-03). |
| X-02 | closed | k = 10 / 5 (N-01). |
| X-03 | closed | 10 years (N-02). |
| X-04 | closed | 30 min / 8 h (N-05). |
| X-05 | closed | One PHI metric (N-07). |
| X-06 | partly | N-08 settled; Arch §6.1 wording still implies a shift on D3 copies (R2-18). |
| X-07 | closed | N-09 / N-10. |
| X-08 | closed | N-12. |
| X-09 | closed | N-12 MedTxt floor. |
| X-10 | closed | N-15. |
| X-11 | closed | Investigator reveal: yes, audited, everywhere. |
| X-12 | closed | Mail never carries D4. |
| X-13 | closed | One hub per country (BD-06). |
| X-14 | closed | Family names fixed in Arch; one stale "NFR-SEC" in TB-DS-03 §9 (R2-03). |
| X-15 | partly | BD-01 decided; TB-DS-03 §1.1 and K3 still say "Medplum, or HAPI if the check fails" (R2-03). |
| X-16 | partly | Priorities now match a plan — but TB-DS-00 M1 and TB-PLAN-01 Variant 1 are two different January plans (R2-01). |
| X-17 | closed | FR-FED/EDCL/TC are M2 / C. |
| X-18 | closed | Role list matches `auth.py`. |
| X-19 | closed | PI workbench / CRC home statuses corrected (FR-UI-02 P, etc.); PR #22 removed from design documents. |
| X-20 | open | D-99 is still cited (TB-DS-03 §5.2, TB-DS-07 §4.1) and still absent from `docs/DECISIONS.md`; tracked as a P1 register item for the next repository change. |
| X-21 | closed | Lockout B. |
| X-22 | closed | Crosswalk Appendix D; SC-NN rename. |
| X-23 | closed | GL 7.0. |
| X-24 | closed | ASVS 5.0. |
| X-25 | open | Report hardware section unchanged; set uses BD-10; report marked informative (F-27). |
| X-26 | closed | TB-DS-nn scheme. |
| X-27 | closed | Form status 1. |
| X-28 | closed | 3D045/3D046. |
| X-29 | closed | TPM: documented, not enforced. |
| X-30 | closed | BD-09 in Arch/SRS/VVO; compose change is M1 work. |
| X-31 | partly | CKIP removed; no replacement surveyed (F-38). |
| X-32 | closed | Grammar first, model proposal confirm-only. |
| X-33 | closed | N-13. |
| X-34 | closed | `auditor`. |
| X-35 | closed | Port table matches compose (gateway 8020 confirmed; rc-bridge 8096 reserved). |
| X-36 | closed | NFR-USAB-02 withdrawn; N-17 pre-screen −50 %. |
| X-37 | closed | DR-09 M1. |
| X-38 | closed | BD-11. |
| X-39 | closed | Egress rows added (F-50). |
| X-40 | closed | FR-AUTH-11. |

### 2.3 Missing documents and sections M-01..M-22

| # | Status | One line |
| --- | --- | --- |
| M-01 | closed | TB-DS-07 Data dictionary. |
| M-02 | closed | TB-DS-08 ICD with JSON Schemas, error register, conformance tests; IC-01..05 are external confirmations. |
| M-03 | closed | TB-DS-09 UI/UX specification. |
| M-04 | closed | TB-DS-11 Risk management file (14 hazards, ISO 14971 structure, benefit-risk). |
| M-05 | closed | TB-DS-10 Terminology and mapping (with honest "verify" marks; TM-01..06). |
| M-06 | closed | TB-DS-12 Configuration management plan. |
| M-07 | closed | TB-DS-00R register; approval blocks; TB-DS-12 §6. |
| M-08 | closed | TB-TMPL-01 ethics pack with JA / zh-TW / EN opt-out notices; §3 data-class text needs correcting (R2-05). |
| M-09 | open | User guides and admin runbook: TB-DS-17, planned 2027-01-22 / 02-28 (WP-11). |
| M-10 | open | SOPs TB-SOP-01..09 planned Dec 2026 – Mar 2027; none written. |
| M-11 | partly | SAT (IQ/OQ/PQ) protocol written (TB-DS-15); PV procedure and completion-report templates (TB-TMPL-05/06) planned. |
| M-12 | closed | TB-PLAN-01 WBS with hours, dependencies, milestones, risks. |
| M-13 | partly | TB-DS-16 outlines the 開示書; SLA, 委託 / data-processing agreement template not drafted; vendor pack TB-DS-21 is P3. |
| M-14 | partly | TB-DS-16 drafted as a standalone position; needs counsel review (RP-01..04) before it is given to a hospital. |
| M-15 | open | Prompt specification and model cards: TB-DS-18, planned 2027-01-29. |
| M-16 | closed | SRS Appendix D. |
| M-17 | closed | Arch §5.2 requirement column per container and §10.3 ADR → quality-scenario trace. |
| M-18 | open | Training plan TB-DS-19, planned 2027-01-29 (needed before shadow mode; SC-05 is a pilot gate). |
| M-19 | open | DR plan TB-DS-20 planned 2027-01-22; TB-DS-03 §10 and TB-DS-07 backup columns still disagree (R2-04). |
| M-20 | open | Sponsor vendor-qualification pack TB-DS-21, P3. |
| M-21 | open | SBOM and licence register: produced per release (TB-DS-08 ICD-11 `sbom`); none exists yet. |
| M-22 | partly | Added: SRS FR-ERR/FR-LOG, AM-01; Arch §8.16, §7.5; SEC SRS-ID column, BD-05 token policy; VVO ethics path. Not added: EDC-lite and OMOP runtime views (A.3 still unmet), TDS, OSS coverage of zh NER / Playwright+axe / PDF / PHP toolchain. |

### 2.4 Counts

| Group | Closed | Partly | Open | Total |
| --- | --- | --- | --- | --- |
| Findings F | 48 | 12 | 2 | 62 |
| Conflicts X | 34 | 4 | 2 | 40 |
| Missing M | 11 | 4 | 7 | 22 |
| **All** | **93** | **20** | **11** | **124** |

Of the 11 open items, 7 are documents the register already schedules (M-09, M-10, M-15, M-18, M-19, M-20, M-21), 2 are the unchanged informative report (F-27, X-25), 1 is a repository entry (X-20) and 1 is a citation (F-52).

---

## 3. New findings (round 2)

Severity as in TB-REV-006: Critical blocks baselining; High must be fixed before approval; Medium should be fixed in the next revision; Low is editorial or minor technical. Repository checks are against `a1e55fa`.

| ID | Sev | Document · section | Finding | Fix |
| --- | --- | --- | --- | --- |
| R2-01 | High | TB-DS-00 §2 (M1 row), OI-14; TB-DS-01 M1 tags (FR-CHAT-*, FR-DEID-04 LLM tagger, FR-RC read, both-site SAT); TB-PLAN-01 §4 (657 h vs 330 h), §5 Variant 1, §6 MS-12..MS-14; TB-DS-00R §3 ("target dates follow Variant 1") | **The January 2027 scope is still written three ways.** TB-DS-00 M1 promises chat box, full PHI pass (rules + NER + LLM tagger), REDCap read, pentest and SAT at both hospitals in January; TB-PLAN-01 proves that is ≈ 2× capacity and recommends Variant 1 (tiles only, rules + NER, Japan ≈ 8 Feb, CGMH ≈ 15 Feb, M2 ≈ June); the register already uses Variant 1 dates; the SRS release rule, VVO gates and TB-DS-15 dates follow TB-DS-00. OI-14 is "Now" but undecided. Everything downstream (ethics timing, hardware delivery, pentest booking) depends on it. | Owner decides OI-14 this week. Then: rewrite TB-DS-00 §2 as M1a (Japan core, date) / M1b (CGMH + chat parser + LLM tagger, date) / M2 / C; re-tag the ≈ 15 SRS rows affected (FR-CHAT-*, FR-DEID-04 part c, FR-ING-03 if the vendor export comes first, CGMH SAT rows); make VVO §7.1 gate G and TB-DS-15 PR-06 cite the M1a/M1b dates; record the decision in TB-DS-00 change history. |
| R2-02 | High | repo `services/console/app.py` `/pilot/jobs/{id}/approve` guarded by `need_requester` → `can_request` = admin, coordinator; TB-DS-01 AM-01 "Approve a ruleset: coordinator Scope (B), investigator Scope (N), admin No (N; built allows)"; TB-DS-03 §5.2 (investigator "Can approve: Rulesets …"; coordinator "Pre-fill values, registry statuses"); TB-DS-07 §7 ("rulesets — PI approval"); TB-DS-11 H-01 control (g) ("approved by the PI"); TB-DS-12 §2 ("Site PI approves rulesets and site rule books") | **Who approves a ruleset is not agreed.** As built and as the SRS matrix records it, the coordinator approves and the investigator cannot; the security, data-dictionary, risk and configuration documents all say the PI approves. Ruleset approval is the control that decides which criteria run against patients (H-01 (g), SC-40), and TB-DS-15 OQ-06 tests roles against "the role table" without saying which. | Decide once (recommendation: `investigator` approves rulesets for the study; `coordinator` prepares and submits the review workbook; `admin` cannot approve). Put the target in AM-01 with status N and a requirement ID; add the code change to WP-08; make TB-DS-03 §5.2, TB-DS-07 §7, TB-DS-11, TB-DS-12 §2 cite AM-01; name the row in TB-DS-15 OQ-06. |
| R2-03 | Medium | TB-DS-03 §1.1 ("FHIR store (Medplum, or HAPI if the Medplum check fails)"); area table ("EDCL EDC-lite on Medplum"); K3 ("Medplum or HAPI (+ Redis)"); §6 key table ("REDCap API tokens · REDCap per user · Vault"); §9 ("FR-AUTH, FR-AUD, NFR-SEC"); AS-8, A14, SC-13 and §5.1 say the opposite | **Stale pre-decision text in the security document.** The decisions (BD-01, BD-05) were applied to the controls and assumptions but not to the scope statement, the asset table or the key inventory. A hospital security officer reads §1, the asset list and the key table before anything else and will find the document contradicting itself on the FHIR store and on token custody. | Consistency pass over TB-DS-03: §1.1, area table, K3, §6 (one row "REDCap project-level read token · hospital REDCap admin · vault · rotate yearly · M1"), §9 family names. Add "superseded text removed" to the change history. |
| R2-04 | Medium | TB-DS-03 §10 backup table ("Postgres (FHIR store, accounts, registry, jobs)"; "Snapshots / lake: not backed up; rebuilt from the last source extract"); TB-DS-07 §3 (S-01..S-06, S-13..S-17 are SQLite; S-07 "month-ends to backup"; S-08 "rebuildable from S-07"); SC-34 (landing purge ≤ 7 days); TB-DS-00 N-04 (3 nightly + 36 month-end snapshots) | **Backup scope does not match the store inventory, and month-end snapshots are unrecoverable.** Accounts, registry and jobs live in SQLite files, not Postgres, so the backup table misses them by name; and "rebuild from the last source extract" cannot recreate 36 month-end snapshots once the landing zone is purged after 7 days, which defeats the reproducibility purpose of N-04. TB-DS-07 says month-ends are backed up; TB-DS-03 says snapshots are not. | Rewrite TB-DS-03 §10 as a table keyed to TB-DS-07 store IDs (S-01..S-26) with backup yes/no and RPO; decide month-end snapshot backup (size it from Arch §7.5: ≈ 36 × per-snapshot bytes) or reduce N-04; carry the result into TB-DS-20 (DR plan). |
| R2-05 | Medium | TB-TMPL-01 §3 ("D2 pseudonymised with free-text identifiers removed; D1 aggregate inside the hospital; D0 aggregate released outside") and figure ("free-text PHI pass → scrubbed notes D2"); TB-DS-00 BD-02 and TB-DS-07 §2.1 (D1 = confidential, no PHI — configuration, metrics, logs; D2 = de-identified aggregates after suppression and date-shifted exports; scrubbed notes are **D3**) | **The ethics pack describes a different data-class scheme from the one hospital IT receives.** Scrubbed notes are D3 in every other document (they remain pseudonymised patient-level data); D1 is not "aggregates inside the hospital". Two committees of the same hospital would be given two incompatible classifications. | Replace §3's class paragraph and figure labels with the BD-02 table verbatim; add "scrubbed notes remain pseudonymised (D3) and stay inside the hospital". |
| R2-06 | Medium | TB-DS-05 §10 ("Medplum Questionnaire / SDC (EDC-lite) — Use if Medplum is adopted"; pick "EDC-lite on Medplum Questionnaire"), §20 row "EDC-lite … (M2, with Medplum)", §1 ("ADR-06 spike"); TB-DS-02 §5.2 edc-lite ("on HAPI … does not depend on Medplum", ADR-04); TB-DS-07 S-25 ("Medplum (QuestionnaireResponse)"); TB-PLAN-01 WP-25 ("Medplum decision") | **EDC-lite's platform is stated three ways** (HAPI, Medplum, "depends on the Medplum decision") and TB-DS-05 cites a superseded ADR number. M2 item, so not urgent, but the open-source survey is the document that justifies component picks. | TB-DS-05 §10/§20: "EDC-lite on FHIR Questionnaire/SDC on the FHIR store in use (HAPI; Medplum only if ADR-14's M2 spike passes)"; cite ADR-04/ADR-14; TB-DS-07 S-25 engine "HAPI (or Medplum after M2 spike)". |
| R2-07 | Medium | TB-DS-03 §15.1 ("Total: about 6–7 weeks of engineering … This fits inside the build plan if scheduled from the start"); TB-PLAN-01 §4 (657 h ≈ 2× capacity) | **The security document's effort claim contradicts the project plan.** Hospital IT will read §15.1 as the vendor's commitment. | Replace the sentence with "Effort and dates: TB-PLAN-01 WP-08, WP-09, WP-12" and delete the per-row week estimates or mark them "superseded by TB-PLAN-01". |
| R2-08 | Medium | TB-DS-03 §14.1 and §15.1 row 12 ("PMDA consultation is free (non-binding)", "before pilot"); TB-DS-16 (PMDA consultation "before selling to pharma", fee to confirm, RP-0x) [LEGAL] | Two statements about when the PMDA consultation happens and whether it costs money. TB-DS-16 is the controlled document for the regulatory position; TB-DS-03 should not carry its own version. | TB-DS-03 §14: one paragraph pointing to TB-DS-16; remove the fee and timing claims from TB-DS-03. Counsel confirms the fee (TB-DS-16 RP item). |
| R2-09 | Medium | TB-DS-01 FR-ING-03 ("SIU^S12 (appointments)" for SS-MIX2); TB-DS-08 ICD-02 table row "SIU 予約 · SIU^S12 · Appointment · next clinic visit for lists"; TB-DS-02 §8.13.1 (verified against JAMI SS-MIX2 Ver.1.2h: no appointment data type); TB-DS-09 S5 (default sort by next visit) | **The Japan appointment source is undefined.** SS-MIX2 standardised storage has no appointment type, yet the SRS and the ICD require SIU^S12 from it, and the PI list's default sort and the "next visit" column depend on appointments. If the head hospital's 予約 data comes from a vendor table, it needs its own ICD-01 mapping table and an FR-ING row. | Remove SIU from the SS-MIX2 rows; add "appointments: vendor 予約 export via ICD-01 (`appointment` table) or none (list sorts by last encounter)" to FR-ING-03/ICD-02; add it to IC-01 and to the WP-03 export specification request. |
| R2-10 | Low | TB-PLAN-01 §5 Variant 1 ("≈ 517 h, still about 1.5× capacity") | The listed work packages (WP-01 40, WP-02 50, WP-03 60, WP-05 24, WP-06 ≈ 40, WP-08 50, WP-09 50, WP-10 50, WP-11 30, WP-12 40, WP-13 40, WP-16 33) sum to **507 h**; WP-07 (40 h) is excluded although Variant 1's January scope includes the entry page with tiles. 547 h with WP-07; neither is 517. The 657 h total is correct. | Recompute; state whether a reduced WP-07 (tiles only, ≈ 10–15 h) is in January; restate the capacity ratio. |
| R2-11 | Low | TB-DS-03 §2.1 D3 row ("Art. 41 / Art. 121") vs §11.1 ("Arts. 73 ff." for 行政機関等) [LEGAL] | Two article citations for the same Chapter-5 rule. | Counsel supplies one citation; use it in both places. |
| R2-12 | Low | TB-DS-03 SC-22 ("Built": pid map AES-GCM **and** data key wrapped by a KEK in the vault) vs SRS DR-07 P ("encryption built; TPM sealing documented, not enforced"); SC-73 ("Built": 10-year audit **and** per-study GCP floor) | Two control statuses over-claim: KEK wrapping and the per-study GCP retention floor are new. | SC-22 → Partial (AES-GCM built, KEK wrapping M1); SC-73 → Partial (audit built, study-record floor M1). |
| R2-13 | Low | TB-DS-03 OI-11 ("TB-DS-15 OQ-12 reviews 50 … align to 200"); TB-DS-04 §7.3 OQ-12 note ("TB-DS-15 says 50") | Stale: TB-DS-15 v0.1a already says 200. | Close OI-11; delete the note in TB-DS-04 §7.3. |
| R2-14 | Low | TB-DS-04 §7.1 gate G ("Should-level row only"), §9.5 ("Should-level requirements not passed"); §4.1 ("orders OMP-O09", "appointments SIU"); §3.5 ("PI workbench, CRC home"); §6.2 FR-SEC-11 levels "U I S"; §6.4 note ("SC controls traced through NFR-COMP/FR-AUTH") | Leftovers from v0.9: "Should" no longer exists (M1/M2/C); SS-MIX2 prescriptions are RDE^O11 and there is no SIU (Arch §8.13.1); TB-DS-09 names the screens S5/S8; a third-party pentest is a security-test (S) record, not a unit/integration test; FR-SEC rows now exist. | Replace "Should-level" with "M2 or C rows"; fix §4.1 message names; cite S5/S8; FR-SEC-11 → "S (external report)"; update the §6.4 note. |
| R2-15 | Low | TB-DS-01 FR-SEC-11 and NFR-COMP-02 (both: third-party pentest passed before go-live; both M1, T, N); FR-SEC-11 row has an extra empty cell | Duplicate requirement; the matrix counts it twice. | Keep NFR-COMP-02 as the requirement; FR-SEC-11 → pointer ("verified by NFR-COMP-02") or withdraw; fix the table row. |
| R2-16 | Low | TB-DS-01 FR-UI-10 status **B** (rule covers `auditor`, which is M1-new) | Status over-claims by one role. | FR-UI-10 → P ("built for coordinator/investigator/viewer/cro; auditor M1"). |
| R2-17 | Low | TB-DS-02 QS-9 ("… (N-17) · NFR-USAB-02"); TB-DS-01 NFR-USAB-02 ("Withdrawn: replaced by NFR-PERF-13 / N-17") | A quality scenario cites a withdrawn requirement. | QS-9 → NFR-PERF-13. |
| R2-18 | Low | TB-DS-02 §6.1 sequence ("surrogate text and date shift for D3/D2 copies"), hold-out text ("held out of D3/D2 copies"), §8.16 `shift_days` tag "[target, M1]"; TB-DS-00 N-08 and SRS FR-DEID-07 (D2 only, **M2**) | Wording implies a date shift on D3 data and an M1 tag on an M2 feature. | "surrogate text (D3); date shift only on D2 exports (M2)"; `shift_days` → [target, M2]. |
| R2-19 | Low | TB-DS-08 ICD-09 ("the built `classify_intent` may propose a command"); repo: the only `classify_intent` on master is the CI stub handler (`services/llm_stub/handlers.py`); the native converse engine (`services/channels/native/`) and spec-v4 define the task, but no production prompt or gate exists | "Built" over-claims: the task name and the stub exist; the model-side parser is a target (FR-CHAT-07 C). | ICD-09: "the `classify_intent` task of the native converse engine (stub in CI; production prompt and gate [target, C]) may propose …". |
| R2-20 | Low | TB-DS-07 S-12 ("[built] filesystem backend; MinIO removal [M1]"), DD-01; repo `libs/tb_common/objstore.py` docstring ("MinIO in deployment, local filesystem in tests"), `deploy/docker-compose.yml` `minio` service | `FsStore` exists for tests and dev; production use of it is M1 work (WP-08). The dictionary's status is right in substance; the wording should not let a reader think the production path is already filesystem. | S-12 → "FsStore built (tests/dev); production object store on FsStore and MinIO removal [M1]". Resolve DD-01 against the compose files in the same change. |
| R2-21 | Low | `trialbox-redcap-fhir.html` (report v7) header and §Hardware tiers, §Releases ("about 1,050 unit tests"), §Clinical UX review ("PR #22") | The report is now labelled informative in TB-DS-00R, but the file itself says nothing of the kind and it is the document the owner and a hospital contact open first. | Add a two-line banner under the title: "Research report, 7 Nov 2026. Superseded in detail by TB-DS-00..16; hardware per TB-DS-00 BD-10; test counts per TB-DS-01 §1.3." No other edits needed. |
| R2-22 | Low | TB-DS-09 §2 (S9 Consent explainer: coordinator "✓ draft", investigator "✓ draft/release"); TB-DS-00 BD-07, SRS FR-CON-06 and AM-01 ("Release consent explainer: coordinator Scope (requester), investigator Scope (requester)") | The UI specification gives release to the investigator only; the decision and the SRS give it to the requester (either role) under the hash rule. | Align S9 to AM-01 (both roles may release under FR-CON-06), or raise a change request to make it investigator-only — but say which. |
| R2-23 | Low | TB-DS-10 §2, §3, §5, §11 (seven "verify"/"unverified" marks on URIs, MEDIS modifier codes, JLAC analyte codes, licences); TM-01..06 have no owner or date | The marks are honest and right for a v0.1; but TM-01 (JLAC codes) and TM-05 (疑い modifier, 保険病名 heuristic) gate TB-DS-15 OQ-03/OQ-04, so they need owners and dates like the register items. | Add owner and target date to TM-01..06 (TM-01/05 before SAT-JP; TM-02/03 before terminology bundle build). |

### 3.1 New-finding counts

| Severity | Count | IDs |
| --- | --- | --- |
| Critical | 0 | — |
| High | 2 | R2-01, R2-02 |
| Medium | 7 | R2-03, R2-04, R2-05, R2-06, R2-07, R2-08, R2-09 |
| Low | 14 | R2-10 .. R2-23 |
| **Total** | **23** | |

### 3.2 What I checked in the repository and found correct

For the record, because status columns drive the release rule: `ROLES = admin, coordinator, investigator, viewer, cro` (no `auditor`); `MIN_PASSWORD = 12`; `MAX_FAILURES = 5`, `LOCKOUT = 15 min`, `IDLE = 30 min`, `ABSOLUTE = 8 h`; `can_view_phi` = admin, coordinator, investigator (SRS AM-01 and TB-DS-03 §5.2 both say "admin: yes as built, target no"); `smallcell.suppress(threshold=5)`; 669 `def test_` functions, 239 `pytest.mark.req` markers, 136 distinct IDs; `DECISIONS.md` has D-98 and D-100 but no D-99; `check_host.sh` warns (does not fail) without a TPM; gateway on 8020; `minio` still in the production compose file; `patient_reveal` audited behind `can_view_phi`. Every one of these matches what the revised documents claim.

---

## 4. Scores (0–5 against industrial standard for the document's type)

| Document | Round 1 | Round 2 | One-line reason |
| --- | --- | --- | --- |
| Report `trialbox-redcap-fhir.html` v7 | 3.0 | **3.0** | Unchanged; now correctly labelled informative in the register, but the file itself still carries the contradicted hardware tiers, "1,050 tests" and "PR #22" (R2-21). |
| TB-DS-00 Baseline decisions | — | **4.0** | Exactly what was missing: one scheme, twelve decisions, nineteen numbers with owners. Loses for the M1 row that the plan shows cannot be met, with the decision (OI-14) still pending (R2-01). |
| TB-DS-00R Document register | — | **4.0** | Complete register with owners, approvers, review triggers and a dated list of missing documents. Would be 4.5 with distribution per audience (TB-DS-12 §6 promises it). |
| TB-DS-01 SRS v0.2 | 3.0 | **4.0** | Large, genuine improvement: atomic rows, M1/M2/C, built status re-audited and verified here, AM-01 matrix, FR-SEC/ERR/LOG, Appendix D crosswalk, open-issue list. Loses for the approval-authority target left undefined (R2-02), the SIU appointment source (R2-09), one duplicate and one over-claimed status (R2-15, R2-16). |
| TB-DS-02 Architecture v0.2 | 3.0 | **3.5** | ADR-13..16 close the big decisions; one port table; SS-MIX2 verified against the JAMI specification; own-store data model; capacity model. Loses for wording that still implies date-shifting D3 (R2-18), a scenario citing a withdrawn requirement (R2-17), Annex A.3 still not met, and capacity still unmeasured. |
| TB-DS-03 Security and privacy v0.2a | 3.5 | **3.5** | Content is the strongest in the set (controls with SRS IDs, D-classes, DPIA by hospital category, one PHI metric). Held at 3.5 because the unfinished consistency pass leaves the scope statement, asset table, key table, backup table and effort claim contradicting the decisions (R2-03, R2-04, R2-07, R2-08, R2-12) — these are the sections a security officer reads first. |
| TB-DS-04 Verification and operations v0.2 | 3.5 | **4.0** | Matrix regenerated for 344 rows, gates keyed to N-numbers, honest fixture, PV protocol with E10, ethics on the critical path, SAT handed to TB-DS-15. Loses only for v0.9 leftovers (R2-13, R2-14). |
| TB-DS-05 Open-source reuse v0.2 | 3.0 | **3.0** | Picks aligned to BD-01/BD-09, Medplum version updated. Still: EDC-lite on Medplum against ADR-04 and a superseded ADR number (R2-06), SNOMED from a 2016 Wikipedia list (F-52), no zh-TW NER survey (F-38), no UI-test/PDF/PHP toolchain rows (M-22). |
| TB-DS-07 Data dictionary v0.1 | — | **4.0** | Twenty-six stores, every built table with class, PII flag and retention; FHIR profile table; lake schema and Japan deltas; data-subject handling. Loses for S-25 "Medplum" (R2-06), the S-12 wording (R2-20) and DD-01 (names not yet checked against compose). |
| TB-DS-08 Interface control v0.1 | — | **4.0** | Real ICD: JSON Schemas with `$id`, RFC 9457 errors, error register, auth per interface, conformance tests, versioning rule. Loses for the SS-MIX2 SIU row (R2-09), the `classify_intent` "built" claim (R2-19) and IC-02 (REDCap call table unverified against the site's REDCap 16). |
| TB-DS-09 UI/UX specification v0.1 | — | **3.5** | Screen inventory with role access and release tags, card state machine, keyboard map, i18n/date rules, states, copy rules, WCAG 2.2 AA, usability acceptance. No wireframes (acceptable); S9 release rights disagree with AM-01 (R2-22); phone rules and string-table ownership are thin. |
| TB-DS-10 Terminology and mapping v0.1 | — | **3.5** | Correct structure (code systems, mapping rules, pilot lab table, CTCAE, normalisers, rule-book format, build/update, licences) and honest about what is unverified. Loses because the unverified items gate SAT steps without owners or dates (R2-23). |
| TB-DS-11 Risk management file v0.1 | — | **4.0** | Fourteen hazards with causes, controls, verification and residual risk; misuse list; acceptability matrix; benefit-risk; post-production sources; reviewed each release. Probabilities are judgements without data (expected before the pilot); H-01 (g) names the PI as approver (R2-02). |
| TB-DS-12 Configuration management v0.1 | 0 (missing) | **4.0** | Clear CI classes, baselines, change classes × types, document control, release record, site custody, audits. Loses for §2 "Site PI approves rulesets" without a requirement behind it (R2-02). |
| TB-PLAN-01 Project plan v0.1 | 0 (missing) | **3.5** | Hours-based WBS, dependencies, external inputs, three variants, milestones, risks; honest about 2× capacity. Loses for the Variant 1 arithmetic (R2-10) and because it is a recommendation awaiting the owner, so the set's dates are provisional. |
| TB-TMPL-01 Ethics pack v0.1 | 0 (missing) | **3.5** | Right parts for both jurisdictions, usable opt-out notices in three languages, committee Q&A, checklist. Loses for the data-class paragraph and figure that contradict BD-02 (R2-05) — a privacy office will notice. |
| TB-DS-15 Site acceptance protocol v0.1a | 0 (missing) | **4.0** | Executable IQ/OQ/PQ with expected results, evidence, mandatory steps tied to hazards, deviation form, sign-off. Loses for OQ-06 "the role table" without naming AM-01 (R2-02) and no supplier-assessment reference (F-48). |
| TB-DS-16 Regulatory position v0.1 | — | **3.0** | Sound non-device argument, intended-use statement in three languages, cross-the-line list, 開示書 outline. Draft until counsel reviews (RP-01..04); conflicts with TB-DS-03 §14 on the PMDA consultation (R2-08); SLA and 委託 agreement template not yet included (M-13). |
| **Set as a whole** | **3.0** | **3.5** | Right shape, right principles, now one scheme, one numbers table, one classification, one access matrix, verified built status and real traceability. Not yet 4.0 because the January scope is still undecided (R2-01), one governance rule is contradicted (R2-02), and four documents still carry text that the recorded decisions superseded. |

---

## 5. Verdict

**Can the set be baselined as v1.0 today?** Not as a whole, and not yet for the hospital IT security review. It can be baselined within about a week, once one owner decision is taken and a two-to-three-day consistency pass is done. By audience:

| Audience | Ready now? | What they would hit |
| --- | --- | --- |
| Hospital IT security review (TB-DS-03 with TB-DS-02 §7, TB-DS-07, TB-DS-15, TB-DS-16) | **No** | TB-DS-03 §1.1 names Medplum as the pilot FHIR store, §6 stores per-user REDCap tokens, §10 backs up stores that do not exist and not the snapshots that do, §15.1 promises an effort the plan refutes (R2-03, R2-04, R2-07). Fix these and the document is ready; the controls catalogue itself is good. |
| Ethics committees (TB-TMPL-01 with TB-DS-04 §8, TB-DS-11, TB-DS-16 §2) | **Nearly** | The pack is submittable once §3 uses the BD-02 classes (R2-05) and the privacy offices have reviewed the opt-out wording. It does not depend on the rest of the set being baselined. The committee dates, not the documents, are the critical path. |
| Engineer joining (TB-DS-00, 01, 02, 07, 08, 12 and the repository) | **Yes, as a working set** | The engineer can start from these today; the SRS statuses are verified, the ICD has schemas, the dictionary names every store. They would need to be told the January scope is undecided (R2-01) and who approves rulesets (R2-02) before touching the console roles. |

**What must still happen first, in order:**

*Owner decisions (this week)*
1. OI-14: adopt TB-PLAN-01 Variant 1 (or state another), and let TB-DS-00 §2, the SRS M1 tags, VVO gates and TB-DS-15 dates follow (R2-01).
2. Ruleset approval authority: investigator approves, coordinator prepares (R2-02). Record in TB-DS-00 as BD-13.
3. Month-end snapshot backup: keep N-04's 36 month-ends and back them up, or reduce N-04 (R2-04).
4. Confirm the consent-explainer release rights in the UI (requester, per BD-07) so TB-DS-09 S9 can be aligned (R2-22).

*External inputs (owner and sites; dates from TB-PLAN-01)*
5. Ethics committee meeting dates and submission deadlines at both hospitals (TB-TMPL-01 §8; MS-04 2026-11-20).
6. Japan head hospital: legal category (OI-12), export specification and SS-MIX2 layout including the appointment source (IC-01, R2-09), REDCap development server access, hospital IT contact for IQ.
7. CGMH: data-warehouse view definitions (IC-03), REDCap development server, IRB route.
8. GPU test box (1 × RTX 5090) for the real-card gate run and the PHI-tagger work; hardware orders per BD-10 only after P7 sizing or with a stated acceptance of the estimate risk (F-21).
9. Pentest firm booked for the two-pass schedule (WP-12).
10. Counsel review of TB-DS-16 (RP-01..04) and of the APPI Chapter 4/5 and PDPA Art. 6 bases (R2-08, R2-11, F-45/F-46).
11. Terminology owners: lab lead for TM-01, clinicians for TM-05 (R2-23).

*Document work (two to three days, then issue 1.0 of the core documents)*
12. TB-DS-03 consistency pass: §1.1, area table, K3, §6 key table, §9, §10 backup table keyed to TB-DS-07 store IDs, §14 pointer to TB-DS-16, §15.1 pointer to TB-PLAN-01, SC-22/SC-73 statuses, close OI-11 (R2-03, R2-04, R2-07, R2-08, R2-11, R2-12, R2-13).
13. TB-DS-01: AM-01 approval target and ID; FR-ING-03 appointment source; FR-SEC-11 pointer; FR-UI-10 P (R2-02, R2-09, R2-15, R2-16).
14. TB-DS-02: QS-9 reference; §6.1/§8.16 date-shift wording and tag; either complete the A.3 runtime views or drop the A.3 claim (R2-17, R2-18, F-42).
15. TB-DS-04: "Should" wording, §4.1 message names, §3.5 screen names, FR-SEC-11 level, §6.4 note, OQ-12 note (R2-14, R2-13).
16. TB-DS-05: EDC-lite pick and ADR numbers; SNOMED citation; zh-TW NER survey row; toolchain rows (R2-06, F-52, F-38, M-22).
17. TB-TMPL-01 §3 classes; TB-DS-07 S-12/S-25 wording and DD-01; TB-DS-08 ICD-02 SIU row and ICD-09 wording; TB-DS-09 S9; TB-DS-10 TM owners/dates; TB-PLAN-01 Variant 1 arithmetic; report banner (R2-05, R2-06, R2-09, R2-10, R2-19, R2-20, R2-21, R2-22, R2-23).
18. Repository: add the D-99 entry to `docs/DECISIONS.md` at the next change (X-20).

*Before the pilot, as already scheduled in TB-DS-00R §3*
19. SOPs TB-SOP-01..03 and 07..09 (release/signing, incident response, key ceremony, backup test, mapping change, deviation/CAPA), admin runbook TB-DS-17, training plan TB-DS-19, DR plan TB-DS-20, test design specifications TB-TDS-nn for M1 features, supplier assessments for category-3/4 components, SBOM with the first signed bundle (M-09, M-10, M-11, M-15, M-18, M-19, M-21, F-47, F-48).

When items 1–18 are done, TB-DS-00, 00R, 01, 02, 03, 04, 07, 08, 11, 12 and 15 can be approved as 1.0 (design baseline DB-1 in TB-DS-12 §4) and handed to the hospital IT security review and to a joining engineer with a clear conscience. TB-DS-05, 09, 10, 16, TB-PLAN-01 and TB-TMPL-01 can follow as 1.0 during the first pilot weeks once their external inputs land. "Industrial standard, comprehensive and detailed" will then be a fair description of the core set; it is a near-miss today, for reasons that are small and specific.

---

## Annex: method

- Every listed file was read in full on the project mount at its exact path; the HTML report was read in two parts. Repository checks were read-only (`git log`, `grep`, `sed`) on master `a1e55fa`; nothing in the repository or in any other design file was changed.
- Each TB-REV-006 item was re-checked against the revised text that claims to close it (section reference given per line), not against the change-history entry alone. Where I did not re-verify a line word by word, the status line says so ("as far as checked").
- Standards were applied as checklists (29148, arc42/42010, 29119-3, GAMP 5 2nd ed., IEC 81001-5-1, ISO 27001:2022 Annex A, MHLW 安全管理GL 第7.0版, APPI / PDPA / HSRA, ICH E6(R3)); legal points are marked [LEGAL] and are not legal advice.
- Scores are relative to what a hospital IT security office, an ethics committee, a new engineer and a pharma vendor auditor expect of a document of that type; 4.0 means "would be accepted with minor comments", 3.5 "accepted after a short correction round", 3.0 "returned with a list".

*End of TB-REV-006b.*
