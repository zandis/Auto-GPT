# TB-REC-01 TrialBox completeness record (decks vs design vs code)

| Field | Value |
| --- | --- |
| Document ID | TB-REC-01 (record; Annex A of TB-DS-19) |
| Title | Completeness record: pages and functions in the decks, the design set and the code |
| Version | 1.1 (record; a record is issued once and corrected only by a new version) |
| Date | 2026-11-07 |
| Owner | Product owner (Changfu Kuo) |
| Author | Claude for Aimedics |
| Status | Record of the check of 2026-11-07; specifications for every gap are in TB-DS-19 |
| Approvals | None needed (record) |
| Basis | Decks `trialbox-introduction.pptx`, `trial-ready-cohort-AD.pptx`; design set at the versions in TB-DS-00R on 2026-11-07; code master `a1e55fa` and commit `38d93ce` |

Date: 2026-11-07. Checked: the two decks shown to Dr Higuchi (`trialbox-introduction.pptx`, 51 slides; `trial-ready-cohort-AD.pptx`, 42 slides), the design set in this folder, and the code on master `a1e55fa` plus the unmerged clinic-workbench commit `38d93ce` (branch `claude/project-thread-0iudms`). Specs for every gap are in `19-platform-functions.md` (TB-DS-19), with requirements FR-PLAT-01..30 in TB-DS-01 and screens S22–S37 in TB-DS-09.

## Summary

| | Count |
| --- | --- |
| Pages and functions checked | 74 |
| **Built** (code and documents agree) | 32 |
| **Built, not merged** (code on a branch only) | 3 |
| **Partial** (part built, rest specified) | 15 |
| **CLI only** (works on the box from the command line, no page) | 6 |
| **Not built** (now specified) | 18 |
| Rows that a deck slide shows or relies on | 42: 27 built, 3 built on the unmerged branch, 8 partial, 3 command line only, 1 not built |
| **Not written down anywhere before today** | 23, now in TB-DS-19 |

The decks mostly hold up. Every clinical page they show runs today except the study-office home, but three of the screenshots (the six-step bar, the PI workbench and the coordinator's "My work") come from a commit that is not merged into master yet. The real gap is the ordinary product pages around the clinical ones: settings, data sources, help, backup, updates, opt-outs and search. Before this audit, most of these were only command-line tools or were missing from the documents.

Legend for the "Documented?" column: **Yes** = in the earlier design set; **Now** = added today in TB-DS-19; **No** = still nowhere.

## A. Clinical pages and functions shown in the decks

| Area | Page or function | In deck? | Documented? | Built? | Gap and fix |
| --- | --- | --- | --- | --- | --- |
| Study cycle | Six-step procedure bar on every study page | Intro 7, 16 | Yes (TB-DS-17, S5) | Unmerged (`38d93ce`) | Merge the workbench commit |
| Study cycle | Protocol upload, criteria compiled by the model | Intro 7, AD 7 | Yes (FR-FEAS, BD-13) | Built | None |
| Study cycle | Investigator approves the criteria once per protocol version | Intro 7, AD 13 | Yes (BD-13, S20) | Partial | Code lets admin and coordinator approve; restrict to the investigator with one Approve on one page (FR-FEAS-12, FR-AUTH-13, S20; step 2) |
| Study cycle | Registry steps found → reviewed → contacted → consented → enrolled | Intro 7, 18 | Yes | Built | None |
| Study cycle | Study set-up page (team, ethics record, REDCap link, reasons) | No | Yes (S21) | Partial | Only protocol upload and site fields exist; build S21 |
| Study cycle | Study office (research office) home | Intro 6 | Yes (office flag, FR-STUDY-10) | Not built | Add the `office` flag and its S21 access |
| Coordinator | Home, one card per study with the next step | Intro 9 | Yes (S8) | Built | None |
| Coordinator | "My work": tasks from PI marks, visits in the next 14 days, pipeline | Intro 18 | Yes (S8) | Unmerged (`38d93ce`) | Merge the workbench commit |
| Coordinator | Single-patient check and per-patient sheet before a visit | AD 12, 13 | Yes (S7) | Built | None |
| Investigator | Weekly list, one card per patient, sorted by visit | Intro 10, AD 11 | Yes (S5, S18) | Built | Clinic-day delivery is build step 2 (FR-NOTIF-01) |
| Investigator | Workbench: worklists, patient table, chart panel | Intro 16, 17 | Yes (S5, S6) | Unmerged (`38d93ce`) | Merge the workbench commit |
| Investigator | Patient page, every criterion with dated quote and source | Intro 11, AD 12 | Yes (S6) | Built | Remove model confidence and model name from the page (FR-UI-17) |
| Investigator | One mark per patient: approach, need info, not suitable | Intro 8, 11 | Yes (FR-SCR-07) | Built | "Not now" mark in step 2 (FR-SCR-07); "Ask treating doctor" later (FR-SCR-07b, L) |
| Investigator | Chart number on request, audited | Intro 10, AD 6 | Yes (BD-04) | Built | Reason field is new (FR-AUD-01b) |
| Feasibility | Report: answer first, summary tiles, three biggest barriers | Intro 12, AD 9 | Yes (S3) | Built | None |
| Feasibility | Criteria funnel in protocol order | Intro 13, AD 10 | Yes (S3) | Built | None |
| Feasibility | Projection per month with range | Intro 12, AD 6 | Yes (S3) | Built | None |
| Feasibility | Site fields and "finalise report" | Intro 9 | Yes | Built | None |
| Feasibility | Sponsor pack (PDF, XLSX, provenance README) | Intro 8, 19 | Yes (FR-REP) | Built | None |
| CRO | CRO home: reports only, small cells hidden, access ends on a date | Intro 14 | Yes (AM-01) | Built | None |
| Admin | Admin home: accounts, approvals, audit of last 24 h, models | Intro 15 | Yes (S12, S13) | Built | Health tiles to complete (FR-PLAT-28) |
| Admin | Model status and the "one model never excludes" rule on the page | Intro 15 | Yes (S13) | Built | None |
| Screening | Nightly screening, filters first, two models must agree | Intro 5, 22 | Yes | Built | None |
| Screening | Screening log export per study | AD 13 | Yes (FR-SCR-10a) | Partial | XLSX built; add screening number and the ICH E6(R3) columns |
| Consent | Consent guide drafted for the ethics committee | AD 13 | Yes (S9, BD-15) | Partial | Draft built; release-after-approval step to build |
| Channels | Every step is also an e-mail command | AD 7 | Yes (FR-MAIL) | Built | None |
| Channels | Weekly list by encrypted mail | AD 11 | Yes | Built | None |
| Data | Hospital export as CSV, FHIR or SS-MIX2 | AD 7 | Yes (FR-ING) | Built | SS-MIX2 hardening for more vendors is later (L) |
| Language | Japanese and Chinese throughout | Intro 17 | Yes (FR-I18N) | Built | Native review of the mark labels (OQ-14) |
| Deploy | One signed file on a USB stick, first admin, host check | Intro 48, AD 39 | Yes (FR-OPS-01) | Built | None |
| Deploy | Signed updates, tampered ones rejected | Intro 48, AD 39 | Yes (FR-OPS-02) | CLI only | Updates page (FR-PLAT-27) |
| Deploy | Nightly audit backup | Intro 48, AD 39 | Yes (FR-OPS-06) | Partial | Only a manual copy of the audit volume; backup page and restore tool (FR-PLAT-26) |
| Accounts | Roles admin, coordinator, investigator, viewer, CRO | Intro 8, AD 39 | Yes (BD-03) | Built | `auditor` role is in the design, not in the code |
| Accounts | Hospital sign-in when configured | Intro 48, AD 39 | Yes (FR-AUTH-04) | Built | Trusted-header only; OIDC/SAML is C |
| Monitor | Audit chain verification | AD 13 | Yes (FR-AUD-03) | CLI only | "Verify chain now" on the audit page (FR-PLAT-29) |

## B. General platform pages and supporting functions

| Area | Page or function | In deck? | Documented? | Built? | Gap and fix |
| --- | --- | --- | --- | --- | --- |
| Sign-in | Login, logout, sessions, CSRF | No | Yes (S14) | Built | None |
| Sign-in | Lockout after 5 failures | No | Yes (N-06) | Built | None |
| Sign-in | Idle and absolute timeout | No | Yes (N-05) | Built | Two-minute warning dialog (FR-PLAT-05) |
| Sign-in | Two-factor (TOTP) | No | Yes (FR-AUTH-01b) | Not built | Build TOTP with recovery codes and admin reset (FR-PLAT-03) |
| Sign-in | Forgot password | No | Now | Not built | Login page link to admin contact; admin resets (FR-PLAT-01) |
| Accounts | Add account, scope, reset password, disable | Intro 15 | Yes (S12) | Built | S12 claimed 2FA status and reset as built; corrected |
| Accounts | Invite by set-password link (no password on screen) | No | Now | Partial | Password is shown once on screen today (FR-PLAT-02) |
| Accounts | My account page | No | Now | Not built | S22 (FR-PLAT-04) |
| Accounts | Monthly access report | No | Yes (FR-AUTH-09) | Not built | As specified |
| Site set-up | First-run checklist | No | Now | CLI only | Settings wizard and install script exist; web checklist S31 (FR-PLAT-06) |
| Site set-up | Site settings page | No | Now | CLI only | `settings.yaml` + wizard only; S23 (FR-PLAT-07) |
| Site set-up | Data sources and ingest status | No | Now | Partial | "Run ingest now" button only; S24 (FR-PLAT-08) |
| Site set-up | Code mapping (terminology) page | No | Now | CLI only | `build_terminology` and `mapping_check` tools; S25 (FR-PLAT-09) |
| Site set-up | REDCap connection page | No | Now (parts in ICD-04, S21) | Not built | S36 (FR-PLAT-10) |
| Site set-up | Mail templates (site header, footer, contact) | No | Now | Partial | Templates fixed in code; S32 (FR-PLAT-11) |
| Daily use | Notification settings | No | Yes (S19) | Not built | As specified |
| Daily use | Notices received | No | Now | Not built | S37 (FR-PLAT-17) |
| Daily use | Job monitor with filter and cancel | No | Now | Partial | List built; cancel exists in orchestrator, not on the page (FR-PLAT-12) |
| Daily use | Report archive per study | No | Now | Not built | S27 (FR-PLAT-13) |
| Daily use | Search (study, pseudonym, screening number) | No | Now | Not built | Header command field (FR-PLAT-14) |
| Daily use | Export of every table (CSV/XLSX/PDF) | Intro 8 | Now (as one rule) | Partial | Feasibility and log exports built; audit CSV, list PDF, jobs CSV to add (FR-PLAT-15) |
| Daily use | Print views | No | Now | Partial | Print CSS exists; A4 views with header and footer (FR-PLAT-16) |
| Daily use | Night-update banner | No | Now | Not built | FR-PLAT-18 |
| Daily use | Language switch | Intro 17 | Yes (§6) | Built | Remember per user, not just per session |
| Help | Help panel on every page | No | Now | Not built | S29 (FR-PLAT-19); mail HELP command is built |
| Help | User guide per role in three languages | No | Yes (register, TB-DS-22) | Not built | FR-PLAT-20 |
| Help | About page with versions and licences | No | Now | Not built | S30 (FR-PLAT-21) |
| Errors | Error pages without stack traces | No | Yes (§7) | Built | Reference id on screen; page-not-found text added to §7 |
| Privacy | Patient notice page (opt-out text) | No | Now | Not built | S33 (FR-PLAT-22) |
| Privacy | Record a patient opt-out, excluded from next night | No | Now | Not built | S33 (FR-PLAT-23) |
| Privacy | Retention job (old files deleted) | No | Yes (FR-OPS-10) | Built | Retention status on S23 (FR-PLAT-25) |
| Privacy | Study close-out | No | Now | Not built | Hospital stage (H, FR-PLAT-24) |
| Operations | Backup page and one-command restore | Intro 48 | Now | Partial | See part A (FR-PLAT-26) |
| Operations | Updates page with rollback | Intro 48 | Now | CLI only | See part A (FR-PLAT-27) |
| Operations | Health page complete (GPU, disk, backup, chain, certificates) | Intro 15 | Yes (S13) | Partial | Services and models built; other tiles (FR-PLAT-28) |
| Operations | Support bundle export | No | Yes (FR-OPS-05) | Not built | As specified |
| Audit | Audit browser with filters, CSV, verify | Intro 15 | Yes (S15) | Partial | Recent list built (FR-PLAT-29) |
| Quality | Phone layout | Intro 16 | Yes (§10) | Built | None |
| Quality | Accessibility WCAG 2.2 AA | No | Yes (§9) | Partial | Labels and focus in place; add automated checks to the browser walk (FR-PLAT-30) |

## What to do, in order

1. Merge the clinic-workbench commit `38d93ce` so master matches the deck.
2. Build My account (step 4); TOTP with recovery codes and set-password links are hospital stage (H).
3. Build the admin pages that replace command-line tools: first-run checklist, settings, data sources, code mapping, REDCap connection, backup, updates.
4. Build the daily-use helpers: search, report archive, notices received, help panel, about, exports and print.
5. Build patient opt-out and the notice page.

## Change history

| Seq | Version | Date | Author | Change |
| --- | --- | --- | --- | --- |
| 1 | — (untitled) | 2026-11-07 | Claude for Aimedics | First issue as `19a-completeness-table.md` with the TB-DS-19 audit. |
| 2 | 1.0 | 2026-11-07 | Claude for Aimedics | TB-REV-006g Q-35: record ID TB-REC-01 and control table; stale "two sign-offs" and M1 wording replaced by the one-Approve S20 and build tags. Counts unchanged (they record the check of 2026-11-07). |
| 3 | 1.1 | 2026-11-07 | Claude for Aimedics | TB-REV-006g §R (R-32) correction: search is in the header command field, not screen S28. Counts unchanged. |
