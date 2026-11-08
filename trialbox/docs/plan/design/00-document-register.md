# TB-DS-00R Document Register

| Field | Value |
| --- | --- |
| Document ID | TB-DS-00R |
| Title | Document Register |
| Version | 0.15 |
| Date | 2026-11-08 |
| Owner | Aimedics engineer (configuration manager, TB-DS-12) |
| Author | Claude (for Aimedics) |
| Status | Living |
| Standard | ISO 10007:2017 configuration status accounting; IEEE 828 register practice |

**Approvals**

| Role | Name | Signature | Date |
| --- | --- | --- | --- |
| Product owner | Changfu Kuo | | |
| Aimedics engineer | (to be named) | | |

## 1. Rules

- One ID scheme (TB-DS-00 §1): `TB-DS-nn` design documents, `TB-PLAN-nn` plans, `TB-TMPL-nn` templates, `TB-REV-nnn` reviews, `TB-REC-nn` records. File numbers order files on disk and are not IDs (`13-` = TB-PLAN-01, `14-` = TB-TMPL-01, `18-` = TB-TMPL-07, `19a-` = TB-REC-01); cite the ID. Older IDs used inside some drafts (TB-SRS-001, TB-DD-02, TB-ARC-02, TB-SEC-03, TB-VV-04, TB-VVO-004, TB-OSS-05) are aliases of the IDs below and are being replaced in their next revision.
- Versions 0.x are drafts; 1.0 is the first approved version (TB-DS-12 §6). Living build documents (TB-DS-20, TB-DS-21) are issued at 1.0; the owner's merge of a step PR that uses them is their approval (TB-DS-12 §6).
- The register's own row is updated in the same edit as its control table.
- Status values: Draft · Reference (frozen for the build stage) · Living · Template · Record · Final (review record) · Approved · Superseded. A suffix "hospital stage (H)" means the document applies only once a hospital uses real patient data (TB-DS-00 §2).
- Distribution: every document is available to the product owner and the builder in the project files. The Distribution column names who else receives it and when.
- "Next review" is the planned date of the next review, or the event that triggers it.
- **Build stage (owner direction 2026-11-07, TB-REV-006f §4.4):** TB-DS-01..19 are frozen at the versions below as reference. The one living page is TB-DS-20 (`20-build-map.md`), with this register. Build decisions go into the code's `docs/DECISIONS.md` as D-nnn entries, not TB-DS revisions. Review again when a hospital asks to install.
- Location: `/mnt/project-files/trialbox-design/` (drafts). Approved versions move to the repository under `trialbox/docs/design/`.

## 2. Register

| ID | Title | File | Version | Status | Owner | Approver roles | Distribution | Next review |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| — | TrialBox on REDCap and FHIR (research and proposal report) | `../trialbox-architecture/trialbox-redcap-fhir.html`, artifact ENoJXMpqMJjqtaYWiNwXaa | v9 | Draft (informative; carries the "Informative only" banner of TB-REV-006b R2-21; TB-DS documents win where they differ) | Product owner | Product owner | Owner, builder | On scope decision |
| TB-DS-00 | Baseline decisions and canonical numbers | `00-baseline-decisions.md` | 0.11 | Reference, frozen for the build stage (§2 points at TB-DS-20; pilot scope and dates under §2.H hospital stage) | Product owner | Product owner, Aimedics engineer | Owner, builder | On scope decision (TB-PLAN-01 MS-01) |
| TB-DS-00R | Document register | `00-document-register.md` | 0.15 | Living (kept current with TB-DS-20) | Aimedics engineer | Product owner | Owner, builder | Each document change |
| TB-DS-01 | Software Requirements Specification (alias TB-SRS-001) | `01-SRS.md` | 0.12 | Reference, frozen; build tags S0–S5 / H / L; 29148 passes TB-REV-006g and §R pass 2 (split rows, Notes column, DR/IR as "shall"); model pins per TB-REV-006f §8 | Product owner | Product owner, Aimedics engineer, site PIs | Owner, builder; site IT at install (H) | Before design baseline DB-1 |
| TB-DS-02 | Architecture and Design Description (aliases TB-DD-02, TB-ARC-02) | `02-architecture.md` | 0.10 | Reference, frozen | Aimedics engineer | Product owner, Aimedics engineer, hospital IT leads | Owner, builder; hospital IT at install (H) | Before DB-1 |
| TB-DS-03 | Security, Privacy and Compliance (alias TB-SEC-03) | `03-security-privacy.md` | 0.7 | Reference, frozen; mostly hospital stage (H) | Security owner (Aimedics) | Product owner, security owner, hospital security officers, privacy offices | Owner, builder; hospital security and privacy offices at install (H) | Before DB-1; then each release and every 6 months |
| TB-DS-04 | Verification, Validation and Operations (aliases TB-VV-04, TB-VVO-004) | `04-verification-operations.md` | 0.10 | Reference, frozen; §3.4.1 `e2e_simple` is the build gate | Aimedics engineer | Product owner, Aimedics engineer, site PIs | Owner, builder | Before DB-1 |
| TB-DS-05 | Open-source reuse survey (alias TB-OSS-05; TB-DS-05 is the reuse survey, not a build plan; the plan is TB-PLAN-01) | `05-open-source-reuse.md` | 0.5 | Reference (TB-REV-006f §6 additions) | Aimedics engineer | Aimedics engineer | Owner, builder | Every 6 months (versions and licences change) |
| TB-REV-006 | Independent review of the design set (Fable) | `06-fable-review.md` | 1.0 | Final (review record) | Product owner | — | Owner (review record) | Superseded by the next review |
| TB-REV-006b | Re-review of the design set, round 2 (Fable) | `06b-fable-rereview.md` | — (2026-11-07) | Final (review record); findings R2-01..R2-23 applied, R2-21 banner added in report v9 | Product owner | — | Owner (review record) | Superseded by the next review |
| TB-REV-006c | Clinical operations review, round 3 (Fable): 3.4 / 5, findings C-01..C-28, real-world inputs R-01..R-10 | `06c-clinical-review.md` | — (2026-11-07) | Final (review record); document findings applied in the versions above; R-01..R-10 need site input | Product owner | — | Owner (review record) | Superseded by the next review |
| TB-REV-006d | Clinical operations re-review, round 4 (Fable): 4.1 / 5, C-findings 24 closed / 3 partly, new D-01..D-20 | `06d-clinical-rereview.md` | 1.0 (2026-11-07) | Final (review record); D-01..D-20 and the three partly-closed C-findings applied in the versions above; R-01..R-10 still need site input | Product owner | — | Owner (review record) | Superseded by the next review |
| TB-DS-07 | Data dictionary and data model of TrialBox's own stores | `07-data-dictionary.md` | 0.6 | Reference, frozen | Aimedics engineer | Aimedics engineer, privacy offices | Owner, builder; privacy office at install (H) | Before DB-1 |
| TB-DS-08 | Interface control documents | `08-interface-control.md` | 0.7 | Reference, frozen; §4.4 REDCap simulator | Aimedics engineer | Aimedics engineer, hospital IT leads, REDCap admins | Owner, builder; hospital IT and REDCap admin at install (H) | Before DB-1 |
| TB-DS-09 | UI/UX specification | `09-ui-ux-spec.md` | 0.10 | Reference, frozen; Release column re-tagged | Product owner | Product owner, site PIs | Owner, builder | Before DB-1 |
| TB-DS-10 | Terminology and code-mapping specification | `10-terminology-mapping.md` | 0.4 | Reference for build step 2 (code mapping folded into S20 rows) | Aimedics engineer | Aimedics engineer, site PIs | Owner, builder; site lab lead at install (H) | Before DB-1 |
| TB-DS-11 | Risk management file | `11-risk-management.md` | 0.7 | Reference, hospital stage (H) | Product owner | Product owner, Aimedics engineer, site PIs, security owner | Owner, builder | Each release; after pilot report; every 6 months |
| TB-DS-12 | Configuration management plan | `12-configuration-management.md` | 0.3 | Reference; §5.0 build-stage change rule (git, PR, D-nnn) applies now; the rest is hospital stage (H) | Aimedics engineer | Product owner, Aimedics engineer, Japan maintenance lead | Owner, builder | Before DB-1 |
| TB-PLAN-01 | Project plan and work breakdown | `13-project-plan.md` | 0.7 | Superseded for the build by SIMPLE-PLAN and TB-DS-20; hospital-stage reference | Product owner | Product owner, Aimedics engineer, Japan maintenance lead, site PIs | Owner | On scope decision; then monthly |
| TB-TMPL-01 | Ethics committee submission pack (outline and templates) | `14-ethics-pack.md` | 0.4 | Template, hospital stage (H); §0 two-page description | Product owner; site PIs own submitted versions | Product owner, site PIs, privacy offices | Site PI, only when a hospital uses real data (H) | Before submission (target 2026-11-20) |
| TB-DS-15 | Site acceptance protocol (IQ/OQ/PQ) | `15-site-acceptance-protocol.md` | 0.6 | Reference, hospital stage (H) | Aimedics engineer | Aimedics engineer, product owner, hospital IT leads, site PIs | Hospital IT and site PI at install (H) | Before first install |
| TB-DS-16 | Regulatory position (non-device) and サービス仕様適合開示書 outline | `16-regulatory-position.md` | 0.1 | Reference, hospital stage (H; counsel review only before a hospital install) | Product owner | Product owner, regulatory counsel (JP, TW) | Counsel; hospital or authority on request (H) | Before giving to a hospital or authority |
| TB-DS-17 | Clinical operations and workload design (personas, workload budget, role homes, study cycle, alerts, data sources, Medplum role, monitoring, pilot measurement) | `17-clinical-operations.md` | 0.9 | Reference, frozen | Product owner | Product owner, site PIs, one CRC per site, Japan maintenance lead | Owner, builder | Before DB-1; after the pilot time-motion baseline |
| TB-TMPL-07 | Pilot measurement templates: baseline self-log, interview guides (R-02), formative usability script (R-03), screening-log columns (TB-TMPL-03, ICH E6(R3)) | `18-pilot-measurement-templates.md` | 0.4 | Template, hospital stage (H) | Product owner; site PIs own completed forms | Product owner, site PIs, research offices | Site PIs and research offices (H) | Before the site interviews (November–December 2026) |
| TB-DS-19 | Platform pages and supporting functions (accounts, settings, data sources, code mapping, jobs, archive, search, help, about, first-run, mail templates, opt-out, backup, updates, health, audit) + completeness table `19a-completeness-table.md` | `19-platform-functions.md` | 0.5 | Reference; build tags per page | Product owner | Product owner, Aimedics engineer | Owner, builder | Before build step 1 |
| TB-PLAN-02 | Simple build plan (five steps, owner direction 2026-11-07); file carries a one-line control record at the top; this row is its register entry | `SIMPLE-PLAN.md` | 1.0 | Living (owner's plan) | Product owner | Product owner | Owner, builder | Each step |
| TB-DS-20 | Build map: steps 1–5 → requirements, screens, done-when; decisions from TB-REV-006f; deck differences | `20-build-map.md` | 1.3 | **Living** | Claude (builder) | Product owner | Owner, builder | Each pull request |
| TB-DS-21 | Synthetic hospital generator specification (500,000 patients, JA / zh-TW / EN notes, planted findings and PHI) | `21-synthetic-hospital-spec.md` | 1.3 | Build specification (step 1) | Claude (builder) | Product owner | Owner, builder | After step 1 |
| TB-REC-01 | Completeness table (74 pages and functions: deck vs documents vs code), record for TB-DS-19 | `19a-completeness-table.md` | 1.1 | Record | Claude | Product owner | Owner, builder | After step 4 |
| TB-REV-006e | Clinical final check (Fable): 4.2 / 5, E-01..E-09 | `06e-clinical-final-check.md` | 1.0 (2026-11-07) | Final (review record); E-findings applied | Product owner | — | Owner (review record) | — |
| TB-REV-006f | Final design review against the simple build plan (Fable): 3.9 / 5 overall including the LLM choice at 3.5 (§8, v1.2), F6-01..F6-30, L8 findings | `06f-final-design-review.md` | 1.2 (2026-11-07) | Final (review record); applied in TB-DS-20 and the documents above; §8 LLM findings folded into the documents above (TB-DS-00R row 13) | Product owner | — | Owner (review record) | Superseded by the next review |
| TB-PLAN-03 | Optimization plan: documents and build to 4.5 (architecture keep/simplify/replace, model roles and serving per hardware tier, harness, integrations, UI/UX, FHIR platform pick, hardware tiers, 18 → 8 document merge with scoring rule, build steps 0–11, owner decisions) | `22-optimization-plan.md` | 0.1 | Draft for owner decision; Living on acceptance (replaces the step table of TB-DS-20 §2) | Product owner | Product owner | Owner, builder | On owner decision; then each step |
| TB-REV-006g | Document quality audit against ISO/IEC/IEEE 29148, 42010, 29119-3 and related standards (Fable): 3.4 / 5, Q-01..Q-40, S-01..S-11; §R re-audit (v1.1, 4.1 / 5); §F final audit (v1.2): 4.4 / 5, 16 of 18 documents at 4.5, F-01..F-10 applied in the §F pass; §C confirmation (v1.3): 4.5 / 5, 18 of 18 documents at 4.5 | `06g-document-quality-audit.md` | 1.3 | Final (review record); applied in the 006g pass and the §R pass 2 | Product owner | — | Owner (review record) | Superseded by the next review |

All version cells match the documents after the TB-REV-006g §F pass (checked with `tools/doclint.py`, which now also checks TB-DS-02 Annex B coverage, check B).


## 3. Documents still missing

**All rows below are hospital stage (H)** (TB-REV-006f F6-25): none is needed for the five build steps. Their target dates applied to the withdrawn pilot plan and are kept only as a guide; the exception is the D-99 entry, which is written with the first build pull request.

Owners: **PO** = product owner (Changfu Kuo); **ENG** = Aimedics engineer; **JPM** = Japan maintenance team; **PI** = site PIs. Target dates follow TB-DS-00 §2.H "Pilot dates" and TB-PLAN-01 Variant 1 (recommended: Japan go-live ≈ 2027-02-08, CGMH ≈ 2027-02-22; owner decision OI-14 pending) and move with that decision.

| Item | Planned ID | Priority | Owner | Target date | Note |
| --- | --- | --- | --- | --- | --- |
| SOP: release and signing | TB-SOP-01 | P1 | ENG | 2026-12-18 | Before feature freeze |
| SOP: incident response (APPI / Taiwan reporting) | TB-SOP-02 | P1 | ENG + PO | 2026-12-18 | Tabletop before go-live |
| SOP: key ceremony and escrow | TB-SOP-03 | P1 | ENG | 2026-12-18 | Before first install |
| SOP: model change control | TB-SOP-04 | P1 | ENG | 2027-01-15 | CC1 changes |
| SOP: access review, break-glass | TB-SOP-05, -06 | P2 | JPM | 2027-03-31 | Break-glass is M2 |
| SOP: backup/restore test, site mapping change, deviation/CAPA | TB-SOP-07..09 | P1 | JPM + ENG | 2027-01-15 | Restore test before go-live |
| User guides: PI, CRC, admin runbook (JA, zh-TW, EN) | TB-DS-22 (was planned as TB-DS-17; that ID is now clinical operations) | P1 admin, P2 users | ENG (admin), JPM (users) | 2027-01-22 admin; 2027-02-28 users | WBS WP-11 |
| Prompt specification and model cards | TB-DS-18 | P2 | ENG | 2027-01-29 | One card per pinned build |
| Training plan and materials | TB-DS-23 (was planned as TB-DS-19; that ID is now platform functions) | P2 | JPM + PI | 2027-01-29 | Before pilot Phase 1 |
| Disaster recovery plan | TB-DS-24 (was planned as TB-DS-20; that ID is now the build map) | P2 | ENG | 2027-01-22 | Reconcile TB-DS-03 §10 and TB-DS-04 §10.4 |
| Sponsor vendor-qualification pack | TB-DS-25 (was planned as TB-DS-21; that ID is now the synthetic hospital spec) | P3 | PO | When pharma pays | |
| Report templates: feasibility report, PI list mail, screening log (column set now defined as TB-TMPL-03 inside TB-TMPL-07), pilot validation report, test completion report | TB-TMPL-02..06 | P1 (feasibility, list), P2 (others) | ENG + PI | 2027-01-15 / 2027-04-30 | |
| Per-feature test design specifications (ISO/IEC/IEEE 29119-3) | TB-TDS-01..nn | P1 for M1 features | ENG | Rolling, each before its feature freeze | Review finding F-47 |
| SBOM and licence register | Release artefact | P2 | ENG | Each release | TB-DS-12 §7 |
| D-99 entry in `trialbox/docs/DECISIONS.md` | — | P1 | ENG | Next repository change | Recorded only in commit e211bad today |

The requirements crosswalk (spec-v4 → SRS IDs) is now Appendix D of TB-DS-01 v0.2.

## Change history

| Seq | Version | Date | Author | Change |
| --- | --- | --- | --- | --- |
| 1 | 0.1 | 2026-11-07 | Claude for Aimedics | First register, from TB-REV-006 finding M-07. |
| 2 | 0.2 | 2026-11-07 | Claude for Aimedics | Consistency pass: versions and status of 00R, 01, 02, 04, 05, 07–10; TB-DS-05 meaning; missing-documents list with owners and target dates. |
| 3 | 0.3 | 2026-11-07 | Claude for Aimedics | TB-REV-006b pass: versions of 00 (0.3), 01, 02, 03, 04, 05, 07–12, PLAN-01 (0.2), TMPL-01, 15; TB-REV-006b row; pilot dates cite TB-DS-00 §2; R2-21 banner noted as open. |
| 4 | 0.4 | 2026-11-07 | Claude for Aimedics | TB-DS-17 clinical operations added (Draft 0.1); planned user guides renumbered TB-DS-22; TB-DS-01 to 0.3 and TB-DS-09 to 0.2; TB-DS-00 owner decisions of 2026-11-07 03:10 (v0.4) reflected. |
| 5 | 0.5 | 2026-11-07 | Claude for Aimedics | TB-REV-006c pass: TB-REV-006c row; versions of 00 (0.5), 01 (0.4), 07 (0.2), 09 (0.3), TMPL-01 (0.2), 17 (0.2); TB-TMPL-07 added; report row v9 with banner (R2-21 closed); note on rows revised in parallel. |
| 6 | 0.5a | 2026-11-07 | Claude for Aimedics | Versions filled in for 02 (0.3), 04 (0.3), 08 (0.2), 11 (0.2), TB-PLAN-01 (0.3), 15 (0.2), TB-TMPL-07 (0.1); 00 at 0.5a. |
| 7 | 0.6 | 2026-11-07 | Claude for Aimedics | TB-REV-006d pass: versions for 00 (0.6), 00R (0.6), 01 (0.5), 02 (0.4), 03 (0.3), 04 (0.4), 07 (0.3), 08 (0.3), 09 (0.4), 11 (0.3), TB-PLAN-01 (0.4), TMPL-01 (0.3), 15 (0.3), 17 (0.3), TB-TMPL-07 (0.2), 05 (0.2b); TB-REV-006d row; TB-REV-006b and 006c rows repaired (D-15); "Before pilot Phase 1" (D-01). |
| 8 | 0.7 | 2026-11-07 | Claude for Aimedics | TB-REV-006e pass: versions 00 (0.7), 00R (0.7), 01 (0.6), 02 (0.5), 04 (0.5), 05 (0.2c), 09 (0.5), TB-PLAN-01 (0.5), 15 (0.4), 17 (0.4), TB-TMPL-07 (0.3); stale "revised in parallel" note removed; history sorted (E-07). |
| 9 | 0.8 | 2026-11-07 | Claude for Aimedics | TB-DS-19 and completeness table added; 01 (0.7), 09 (0.6); planned training plan renumbered TB-DS-23. |
| 10 | 0.9 | 2026-11-07 | Claude for Aimedics | TB-REV-006f pass: build-stage rule (TB-DS-01..19 frozen; TB-DS-20 living); versions 00 (0.8), 01 (0.8), 02 (0.6), 03 (0.4), 04 (0.6), 05 (0.3), 07 (0.4), 08 (0.4), 09 (0.7), 11 (0.4), PLAN-01 (0.6), TMPL-01 (0.4), 15 (0.5), 17 (0.5), TMPL-07 (0.4), 19 (0.2); new rows SIMPLE-PLAN, TB-DS-20, TB-DS-21, 19a, TB-REV-006e, TB-REV-006f; planned DR plan and vendor pack renumbered TB-DS-24/25; §3 rows marked H. |
| 11 | 0.10 | 2026-11-07 | Claude for Aimedics | TB-REV-006f §R: versions 01 0.9, 02 0.7, 04 0.7, 09 0.8, 17 0.6, TB-DS-21 1.1, 08 0.5, 10 0.1b; TB-DS-10 reference for step 2; TB-DS-12 and TB-DS-16 hospital stage (N7-12). |
| 12 | 0.11 | 2026-11-07 | Claude for Aimedics | TB-REV-006g Q-05, Q-40, S-07, S-09: own row = 0.11 and same-edit rule; Distribution column; IDs TB-PLAN-02 (SIMPLE-PLAN) and TB-REC-01 (19a); file-number ≠ ID rule; status values and living-document version rule; TB-REV-006g row; versions 00 0.9, 01 0.10, 12 0.2, 20 1.1; Seq column. |
| 13 | 0.12 | 2026-11-07 | Claude for Aimedics | TB-REV-006g §R pass 2 and TB-REV-006f §8 fold-in: versions 00 0.10, 00R 0.12, 01 0.11, 02 0.9, 03 0.6, 04 0.9, 05 0.5, 07 0.6, 08 0.7, 09 0.10, 10 0.3, 11 0.6, 12 0.3, 17 0.8, 19 0.4, 20 1.2, TB-REC-01 1.1, TB-PLAN-02 1.0 (control line added to `SIMPLE-PLAN.md`); TB-REV-006f row 1.2 with 3.9 / 5 overall including LLM 3.5; TB-REV-006g row 1.1; `tmp-forkA-new-ids.txt` deleted (R-04). |
| 14 | 0.13 | 2026-11-07 | Claude for Aimedics | TB-REV-006g §F pass: versions 00 0.11, 00R 0.13, 01 0.12, 02 0.10, 03 0.7, 04 0.10, 10 0.4, 11 0.7, 13 0.7, 15 0.6, 17 0.9, 19 0.5, 20 1.3, 21 1.3; TB-REV-006g row 1.2 with the §F result. |
| 15 | 0.14 | 2026-11-07 | Claude for Aimedics | TB-REV-006g §C confirmation: TB-REV-006g row 1.3 (set 4.5 / 5, 18 of 18 at 4.5). |
| 16 | 0.15 | 2026-11-08 | Claude (Fable) for Aimedics | TB-PLAN-03 `22-optimization-plan.md` v0.1 registered (draft for owner decision). The build review of 2026-11-08 (3.3 / 5) lives in `../trialbox-build/fable-review-2026-11-08.md`. |
