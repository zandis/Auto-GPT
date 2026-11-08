# TB-DS-19 Platform pages and supporting functions

| Field | Value |
| --- | --- |
| Document | TB-DS-19 Platform pages and supporting functions |
| Version | 0.5 |
| Date | 2026-11-07 |
| Owner | Aimedics (author: Claude, for Changfu Kuo) |
| Status | Internal reference for the build (SIMPLE-PLAN.md). Not a gate. **Build tags (TB-REV-006f F6-08, F6-25):** built in step 4: S22 My account, S24 Data sources, S26 Jobs (Cancel + Retry), S29 Help panel, S37 Notices received, search in the header command field; S36 REDCap connection (token + test) in step 3. Hospital stage (H): S23, S25, S31–S35, password-reset links, TOTP recovery, mail templates, opt-out pages, backup and update pages, user guides. Later (L): S27 report archive, S30 About, print views. The SRS priority column (TB-DS-01 (version per TB-DS-00R)) carries the same tags. |
| Approvals | Product owner: — · Aimedics engineer: — (none needed for the build; TB-DS-00 §1 control block) |
| Audited code | `zandis/Auto-GPT` master `a1e55fa`, plus the unmerged clinic-workbench commit `38d93ce` on `claude/project-thread-0iudms` |
| Related | TB-DS-01 §3.1.29 FR-PLAT-01..30 (new), TB-DS-09 S22–S37 (new), completeness table `19a-completeness-table.md` |

## 1. Why this document exists

The clinical pages (feasibility report, patient list, chart panel, coordinator work list) are specified in TB-DS-09 and TB-DS-17. A product a hospital can run also needs the ordinary pages around them: accounts, settings, data sources, help, exports, backup, updates and so on. Several of these exist only as command-line tools today, some exist only in the documents, and a few were not written down anywhere. This document lists every one of them in one place, says what is built, and specifies what is missing.

Status words used below:

- **Built**: in the code and in the documents.
- **Partial**: in the code, but something listed here is missing.
- **CLI only**: works today from the command line on the box, with no web page.
- **Documented**: specified in the documents, not built.
- **New**: not specified anywhere before this document.

Release tags follow the one legend in TB-DS-00 §2 and TB-DS-20 §1: **S0** built; **S1–S5** build step; **H** hospital stage; **L** later. The tag of each entry is the TB-DS-01 tag of its FR-PLAT row.

## 2. Built today (for reference)

| Function | Code location | Notes |
| --- | --- | --- |
| Login, logout, server-side sessions, CSRF | `services/console/auth.py`, `app.py /login /logout` | 30 min idle, 8 h absolute (N-05); lockout 5 fails / 15 min (N-06) |
| Hospital sign-in (trusted header from a reverse proxy) | `app.py` `TB_CONSOLE_SSO_*` | Role from a header, default role configurable |
| Accounts page: add, reset password, set scope, disable | `app.py /ops/users`, `templates/users.html` | Password shown once on screen; roles admin, coordinator, investigator, viewer, cro |
| Language switch EN / JA / zh-TW | `app.py POST /lang`, `i18n*.py` | Per session (cookie) |
| Role homes | `home.py /home`, `home_admin.html`, `home_crc.html` | PI and coordinator workbench in commit `38d93ce`, not yet on master |
| Admin system page: service checks, models, policy, ingest button | `templates/overview.html`, `app.py /ops/ingest` | No GPU, disk, backup or audit-chain tiles yet |
| Jobs list and job page | `app.py /jobs`, `/pilot/jobs/{id}` | Orchestrator has `POST /jobs/{id}/cancel`; no button on the page |
| Audit page | `app.py /audit`, `_audit_table.html` | Recent entries; no filters, no export |
| Exports | Feasibility PDF/XLSX/JSON (`services/deliverables/render.py`), sponsor pack ZIP, registry screening log XLSX | No CSV of the audit, no PDF of the patient list |
| Print styles | `static/console.css @media print` | Not checked page by page |
| Phone layout | `console.css` media queries | Tested in the Playwright walk |
| Error page | `templates/problem.html` | Plain message, no reference id shown to the user |
| Mail commands including HELP | `services/channels/grammar.py` | 20+ commands; mail templates are in code |
| Encrypted mail attachments | `services/mail_gateway/outbound.py` | 7z AES-256 or S/MIME |
| Install from a signed bundle, first admin account | `deploy/install.sh`, `tools/make_bundle.sh`, `tools/sign_bundle.py` | Prints the first admin password once |
| Site settings wizard | `tools/settings_wizard.py` | CLI only; writes `settings.yaml` and `.env` |
| Signed update, verify | `tools/apply_update.sh`, `tools/verify_update.py` | CLI only; no rollback command |
| Audit chain verify | `tools/audit_verify.py` | CLI only |
| Terminology build and mapping check | `tools/build_terminology.py`, `tools/mapping_check.py` | CLI only |
| Retention job | `services/orchestrator/scenarios/retention.py` | Deletes old attachments and outputs (D-78) |
| Backup | `docs/RUNBOOK.md §5` | Manual `rsync` of the audit volume; restore = reinstall + restore volumes |

## 3. Functions to add or finish

Each entry: purpose · who · fields and actions · release · status · where it will live. Requirement IDs are in TB-DS-01 §3.1.29; screens in TB-DS-09.

### 3.1 Accounts and sign-in

**FR-PLAT-01 Forgot password.** A user who forgot the password clicks "Forgot password" on the login page. The page says the box has no outside mail service for this and shows the site's admin contact (from site settings). The admin resets the password on the accounts page (built). · All users · H · New · `login.html`.

**FR-PLAT-02 Set-password link instead of a shown password.** When the admin adds an account or resets a password, the box sends a one-time link to the user's hospital mailbox (valid 24 h, one use). The admin no longer reads the password off the screen. If mail is not configured, the current "shown once" behaviour stays. · admin · H · Partial (shown-once built) · `/ops/users`, mail gateway.

**FR-PLAT-03 Two-factor recovery.** At TOTP enrolment the user gets 10 one-use recovery codes. The admin can reset a user's TOTP (the user enrols again at next login). Both are audited. · All users, admin · H · Documented (S14) · S14, S12.

**FR-PLAT-04 My account page.** Shows name, role, affiliation, studies in scope, expiry date, last login. Actions: change password, re-enrol TOTP, view recovery-code count, set language, open notification settings (S19). · All users · S4 · New · S22.

**FR-PLAT-05 Session warning.** Two minutes before the idle timeout a dialog says "You will be signed out at 14:35" with "Stay signed in". Needs a small script; the console today has none (strict CSP), so this uses a same-origin script allowed by the CSP. · All users · H · Documented (S14) · `base.html`.

### 3.2 Site set-up and settings

**FR-PLAT-06 First-run checklist.** After install the admin home shows a checklist until every line is done: settings valid · data source connected · first ingest done · code-mapping coverage shown · mail test sent and received · backup target reachable · first accounts created · full-size dry run done (FR-OPS-07). Each line links to the page that does it. · admin · H · New (CLI wizard built) · S31.

**FR-PLAT-07 Site settings page.** Shows the site settings in plain words: hospital name, departments, internal mail domains, night schedule (BD-11), small-cell limits (N-01), retention days, data-source type, GPU profile. The admin may edit a fixed safe list (hospital display name, admin contact, mail footer, night-schedule times, retention days within the allowed range); everything else stays in `settings.yaml` and the page shows "changed by hospital IT in the settings file". Every change is audited (FR-AUD-01g). · admin (edit), auditor (read) · H · CLI only · S23.

**FR-PLAT-08 Data sources and ingest status.** One row per source (CSV, SQL view, FHIR, SS-MIX2): type, last successful ingest, patients and records loaded, validation pass rate, rejected rows with reasons (no PHI), next scheduled run, "Run ingest now" (built button). History of the last 30 ingests. · admin; coordinator read (last ingest only) · S4 · Partial · S24.

**FR-PLAT-09 Code mapping page.** Shows how local codes map to standard ones (diagnoses, drugs, labs) with coverage per category, the top unmapped local codes with counts, and the result of the last mapping check. Admin can download the mapping file, upload a corrected one (validated before use, previous version kept) and re-run the check. · admin; coordinator read · H · CLI only · S25.

**FR-PLAT-10 REDCap connection.** Base URL, REDCap version found, project-level read token (entered once, stored in the secret store, shown masked), "Test connection", list of linked projects with their study (the per-study link is in S21). · admin · S3 · Documented in parts (ICD-04, S21) · S36.

**FR-PLAT-11 Mail templates.** Every outgoing notice (PI list, CRC digest, job finished, alerts, set-password link) has a fixed template in three languages. The admin may edit only the site header, footer, signature and contact line, with a preview. Clinical wording stays fixed. · admin · H · New (templates in code) · S32.

### 3.3 Daily operation

**FR-PLAT-12 Jobs page with cancel, retry and filter.** Filter by study, type, state, date. A running job shows its steps. "Cancel" on a queued or running job (orchestrator endpoint exists) and **"Retry"** on a failed job with the same inputs (TB-REV-006f F6-27), both audited. · admin, coordinator (own studies) · S4 · Partial · S26.

**FR-PLAT-13 Report archive.** One page per study listing every feasibility report, sponsor pack, patient list, screening log and consent explainer that was produced: date, ruleset version, data snapshot, who made it, who downloaded it. Re-download within retention (N-03). · coordinator, investigator, viewer (aggregates), cro (sponsor copies only), auditor · L · New · S27.

**FR-PLAT-14 Search.** One search box in the header: study id or name, pseudonym, screening number. Results stay inside the user's scope. Searching by chart number is allowed only for roles with reveal rights and is audited like a reveal (FR-AUD-01b). · All roles (within scope) · S4 · New · header command field (FR-UI-01); no separate screen.

**FR-PLAT-15 Exports everywhere a table is shown.** Rule: every table a user can see can be downloaded as CSV or XLSX with the same rows and the same small-cell rule; reports also as PDF. Adds: audit CSV (auditor), patient list PDF (print of S5), jobs CSV (admin). Every download is audited. · per page · H · Partial · all screens.

**FR-PLAT-16 Print views.** Print-ready versions of the patient sheet, the PI list and the feasibility report: A4, hospital name, study, date, page numbers, "pseudonymous" footer. · coordinator, investigator · L · Partial (print CSS) · S5, S6, S3.

**FR-PLAT-17 Notices received.** A page listing the notices the box sent to me (from `notify_log`): date, kind, study, opened link. Lets a user find last Monday's list without searching mail. · All users · S4 · New · S37.

**FR-PLAT-18 Night-work banner.** While the night jobs run (BD-11), every page shows "Night update running until 06:00; lists show yesterday's data". · All users · H · New · `base.html`.

### 3.4 Help and information

**FR-PLAT-19 Help on every page.** A "?" in the header opens a short help panel for that page (what it is for, what each action does, who to ask) in the user's language, written in the TB-DS-09 copy rules. No internet needed. · All users · S4 · New · S29.

**FR-PLAT-20 User guide.** One guide per role (PI, coordinator, research office, admin, CRO viewer) in EN/JA/zh-TW, as pages inside the box and as a PDF to print. Content follows TB-DS-22 (user guides). · All users · H · Documented (register row only) · S29.

**FR-PLAT-21 About page.** Version and build, install date, update history, models in use with their file hashes, ruleset versions, open-source components and their licences (generated from the lock file), support contact. · All users (models and hashes: admin) · L · New · S30.

**FR-PLAT-22 Privacy notice page.** A page anyone in the hospital can open without signing in, showing the site's patient notice (opt-out text from TB-TMPL-01 §4 in the site's language) and how a patient can opt out. · public inside the hospital network · H · New · S33.

### 3.5 Data protection

**FR-PLAT-23 Patient opt-out.** An admin or coordinator records an opt-out by chart number (inside the identified zone). From the next night the patient is left out of every feasibility count, list and check, and existing lists hide the patient. The opt-out list is kept, audited and backed up. · admin, coordinator (record); auditor (read) · H · New · S33.

**FR-PLAT-24 Study close-out.** When a study ends, the coordinator closes it: lists and patient pages stop; the screening log and audit stay for the study's retention period (N-03), then are deleted or archived on the admin's confirmation. · coordinator, admin · H · Documented in parts (N-03, retention job) · S21.

**FR-PLAT-25 Retention status.** On the settings page: what is kept, for how long, when the next deletion runs, and the last deletions (from the retention job). · admin, auditor · H · Partial (job built) · S23.

### 3.6 Backup, update, health

**FR-PLAT-26 Backup page and restore tool.** Shows last backup (time, size, target, result) for every item in FR-OPS-06, next run, and "Test restore" which restores the latest backup into a scratch area and checks the audit chain and counts. A `restore` command restores a box from backup in one step. · admin · H · Partial (manual audit rsync) · S34.

**FR-PLAT-27 Updates page.** Installed version, update history, "Upload update" for a signed bundle (verify signature, show what changes, apply), "Roll back" to the previous version keeping data (FR-OPS-03). · admin · H · CLI only (apply, verify) · S35.

**FR-PLAT-28 Health page, complete.** Adds to the built system page: GPU memory and model loaded, disk use, snapshot count, last backup, last audit-chain check, certificate expiry, night-job progress, and "Export support bundle" (FR-OPS-05). · admin, auditor (read) · H · Partial · S13.

**FR-PLAT-29 Audit browser with filters.** Filters by date, user, action, study; hash-chain status; CSV export; "Verify chain now" button (runs the built verifier). · admin, auditor · H · Partial · S15.

### 3.7 Quality of every page

**FR-PLAT-30 Accessibility and layout checks in the build.** Every page is checked in the automated browser walk for: WCAG 2.2 AA (automated rules), keyboard use, phone width 390 px, print layout, and all three languages with no missing strings. A failing page is reported in the step's completion report (TB-DS-04 Annex A). · build · H · Partial (phone + language walk built) · TB-DS-04 §3.5.

## 4. Role note

The introduction deck names a "study office" home. In the design this is a `coordinator` account with the `office` flag (FR-STUDY-10), not a separate role. The `auditor` role (BD-03) is in the design but not in the code yet (`ROLES` in `services/console/auth.py` has five roles).

## 5. References

| Ref | Document |
| --- | --- |
| [P1] | TB-DS-01 §3.1.29 FR-PLAT-01..30 (requirement text and tags win over this summary) |
| [P2] | TB-DS-09 S12–S15, S22–S37 (screens, six attributes in §3.1) |
| [P3] | TB-DS-00 N-03, N-05, N-06, BD-03, BD-17; TB-DS-03 (security controls behind FR-PLAT-01..03, -26, -27) |
| [P4] | W3C WCAG 2.2 (FR-PLAT-30) |
| [P5] | Repository `zandis/Auto-GPT` master `a1e55fa` and commit `38d93ce` (code locations in §2) |
| [P6] | Annex A of this document: completeness record TB-REC-01 (`19a-completeness-table.md`) |

## Change history

| Seq | Version | Date | Author | Change |
| --- | --- | --- | --- | --- |
| 1 | 0.1 | 2026-11-07 | Claude for Aimedics | First issue, from the completeness audit of the decks against the documents and the code (master `a1e55fa`, commit `38d93ce`). |
| 2 | 0.2 | 2026-11-07 | Claude for Aimedics | TB-REV-006f F6-08, F6-25: build tags per page (steps 3–4, H, L), matching TB-DS-01 v0.8. |
| 3 | 0.3 | 2026-11-07 | Claude for Aimedics | TB-REV-006g Q-34, Q-35, S-02, S-06, S-08: body tags replaced by the TB-DS-01 v0.9 FR-PLAT tags; FR-PLAT-12 adds Retry; approvals row; References §5; the completeness table is registered as record TB-REC-01 and cited as Annex A; Seq column. |
| 4 | 0.4 | 2026-11-07 | Claude for Aimedics | TB-REV-006g §R (R-31, R-32): control table cites TB-DS-01 v0.11; FR-PLAT-14 search lives in the header command field, not a separate S28 screen. |
| 5 | 0.5 | 2026-11-07 | Claude for Aimedics | TB-REV-006g §F F-02 pattern: control table cites TB-DS-01 "version per TB-DS-00R". |
