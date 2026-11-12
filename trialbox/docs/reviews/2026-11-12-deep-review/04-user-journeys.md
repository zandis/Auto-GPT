# TB-DR2-04 User journeys, module by module and role by role

| | |
| --- | --- |
| Document id | TB-DR2-04 |
| Date | 2026-11-12 |
| Tree | `514ae9b` (branch `claude/deep-review-2026-11-12`) |
| Area | 4. User journeys across the full multi-role lifecycle (prefix `JRN`) |
| Run | `make e2e-simple` (owned by this review); the PoC console `python -m tools.demo --lang en --keep` on 127.0.0.1:18100 (in-process box, stub model, synthetic Taiwan hospital, PostgreSQL 16 through `tools.pglocal`); every role walked in Chromium with Playwright (Node): 7 route crawls (84 routes each) and 20 action walks; `tests/e2e/journeys/test_journeys.py` (7 passed, 112 s); `tests/console/test_identity.py` + `test_pi_runs.py` (49 passed, 18 s); `tools.opportunity_feed sample` |
| Only read | `libs/tb_common/authz_matrix.yaml`, `services/console/*.py` and templates around each finding, `tests/e2e/journeys/journeys.yaml`, `demo/README.md`, `demo/Dockerfile`, plan file 32 (opportunity feed), the three earlier reviews |
| Not run | Docker image, the compose stack, mail, real models, OIDC, TOTP in the browser (the demo's built-in accounts run with the second factor off), the box's operations service (backup, update), phone layout |
| Evidence | 12 screenshots under `evidence/JRN/`; scripts and raw results in the reviewer's scratch folder (`JRN/walk/*.js`, `walk-*.json`, `crawl-*.json`, `demo.log`) |

## 1. Reading in ten lines

1. The day-to-day work of an **existing, approved study** runs end to end in the real app: list, case, marks with undo,
   approach, contact, consent, enrolment, visits, SAE register, deviations, screening log, EDC review, break-glass,
   opt-out, audit browser, monitor page. No 5xx and no traceback in the server log during the whole walk.
2. A **new study cannot get its first approval through the console** (JRN-001, Blocker). The PI's approval answers 403
   until the steward names the PI; the steward's delegation page answers 404 until the study is approved. Every test
   and demo writes the PI entry straight into the database, so nothing caught it.
3. The **opt-out register confirms an opt-out that does not happen** when the pseudonym is typed the way every screen
   shows it (8 characters) or mistyped (JRN-002, Critical). The patient stays on the PI's list.
4. FIT-003 is half fixed: the PI has the right to start FEAS, SCREEN and CASE, but the PI's "New request" page says
   "You are signed in as a viewer", and the CASE button is disabled. Only "Refresh" on an existing feasibility report works.
5. **Closing a study is one click, final, with no confirmation and no check** (JRN-004): a coordinator, also an SMO
   coordinator, closed a study with two participants on study, open SAE reports and three unanswered deviations.
   There is no close-out or archive journey after it.
6. **EDC item map**: a CRF with more than 76 items cannot be saved from the browser (a hidden 1,000-field form limit;
   raw JSON error) (JRN-005).
7. The role model is now right in shape (matrix, steward, privacy office, monitor grant, administrator without patient
   pages). 20 of the 28 earlier ROLE findings are fixed. What remains is mostly menu and page leftovers.
8. Missing journeys: privacy office from a chart number to the disclosure report; erasure; monitor finding their page;
   SDV of values typed into the built-in forms; sponsor dashboard as a served product (only an offline sample page).
9. `make e2e-simple` **passes** (499 s, 224 checks) once the jars, the fonts and a database folder the `postgres` user
   can reach are in place; on a fresh checkout it fails three different ways first.
10. Speed of the key tasks is good: today's candidates 0 clicks after sign-in, why-unknown 1 click, not suitable
    2 actions, consent 4 clicks and 3 typed fields.

## 2. `make e2e-simple` (owned by this review)

| Attempt | Setting | Result | Time |
| --- | --- | --- | --- |
| 1 | fresh checkout, `TB_TEST_ROOT` in the scratch folder | exit 2: "the CQL translator jars are missing … run `make jvm-deps`" (clear message, at once) | 0.9 s |
| 2, 3 | jars fetched to scratch with Maven (`TB_CQL_TRANSLATOR_LIB`) | exit 1: `initdb … Permission denied`, then `database "postgres" does not exist`: the session's `/tmp/claude-0` is reset to mode 0700, the `postgres` user cannot reach it, and the second run reused the half-built cluster (JRN-018) | 8 s |
| 4 | root under `/var/tmp/trialbox-0/JRN` | exit 1 after the SCREEN job: `ReportError: font NotoSansJP-Regular.ttf not found` (three jobs "failed in reporting"); the tool stops on an `AssertionError` (JRN-009) | 2 min 54 s |
| 5 | fonts fetched to scratch (`TB_FONTS_DIR`), run beside a second seeding process, load 11 to 15 on 4 cores | stopped by my 590 s limit, no result | 9 min 50 s |
| 6 | same, `nice 10`, load 7 to 13 | **PASSED**: 19 stages, 224 checks, 0 error lines; "e2e_simple PASSED in 499.0 s (chain 182.0 s)" | real 8 min 22 s, user 5 min 7 s |

The same code ran inside `tools.demo` at start: PASSED in 669.3 s under load. The tool's own check "whole run within
15 min" held both times. On an idle 4-core machine expect about 5 minutes (user CPU 5 min 7 s).

## 3. How the app was brought up

`TB_DEMO_PASSWORD=… TB_FONTS_DIR=… TB_CQL_TRANSLATOR_LIB=… python -m tools.demo --dir <root>/demo --lang en --port 18100 --keep`.
Seeding took 11 minutes under load (the README says 3 to 6). Steady memory 932 MB RSS plus PostgreSQL. Accounts walked:
`pi`, `subpi`, `crc`, `cra` (CRO, GZQO and GOUT-COH), `viewer`, `stw`, `admin`; created in the walk through `/ops/users`:
`prv` (privacy office), `smo1` (SMO coordinator, GZQO), `inv2` (investigator on no log), `stw2`. Demo day 2026-11-12.

## 4. Status of the previous reviews' findings (journey and role parts)

Verified by a run unless marked "read". "Fixed" means the behaviour is gone on this tree.

| Old ID | Severity | Now | Evidence |
| --- | --- | --- | --- |
| ROLE-001 2FA bypass through `/api/v1/session` | Blocker | fixed | a bearer token sent as the `tb_console` cookie gets 303 to sign-in; `test_identity.py` passes (API asks both factors) |
| ROLE-002 demo image does not start | Blocker | fixed (read) | `demo/Dockerfile:41-62` fetches FHIRHelpers and fonts; image not built here |
| ROLE-003 memory and start-up claims | Critical | fixed (docs) | `demo/README.md:83-88` now says 1.82 GB peak, 0.8 GB serving, 4 GB host, up to 10 min; measured 932 MB serving, 11 min under load |
| ROLE-004 / UX-040 shared accounts, no persistence | High | fixed (read; `--keep` run) | `--accounts`, `--keep` in `tools/demo.py`; `--keep` used in this walk |
| ROLE-005 opt-out kept by any coordinator, lift without reason | High | fixed | crc and smo1: 403 on `/site/opt-outs`; lift without a reason: 400 "say why … (at least 10 characters)". New defect in the same page: JRN-002 |
| ROLE-006 no per-address throttle | Low | fixed (read) | `auth.py` `SOURCE_FREE`, `SOURCE_MAX_WAIT` |
| ROLE-007 `/healthz` leaks env and schema | Low | **open** | `{"status":"ok","service":"console","pilot":true,"env":"DEV","checks":{"db:w88b07193a6_auth":"ok"}}` without sign-in |
| ROLE-008 delegation bootstrap fails open | High | fixed, **and it now fails closed for a new study** | `inv2` (on no log): 403 on list, patient, subjects, marks, SAE ack, state, IRB; but see JRN-001 |
| ROLE-009 / FIT-022 no steward, privacy, monitor | High | fixed | 7 roles in the matrix; monitor as a dated grant on the delegation log |
| ROLE-010 admin sees PHI without break-glass | High | fixed | admin: 403 on every patient page; job files served to admin are the aggregate ones (4.6 KB JSON without candidates) |
| ROLE-011 CRO and SMO see every study by default | High | fixed, one leftover | account without studies refused (400); cra 404 on RA-JAK, SITE5B. Leftover: JRN-011 (research-office counts) |
| ROLE-012 / FIT-002 monitor has no SDV | High | **partly** | `/studies/GZQO/monitor` works under the PI's grant (visit id, end date, read-only). Not linked from any menu; shows only prefill-confirmed values (JRN-008) |
| ROLE-013 audit viewing for the privacy office | High | fixed | `/audit` for steward and privacy only; filters by kind, event, person, pseudonym, job, dates; chain verify "2139 events … verifies" |
| ROLE-014 privacy-office requests | High | **partly** | one-patient audit report and CSV exist, by 32-character pseudonym only; no way from a chart number; no erasure request (JRN-006) |
| ROLE-015 SMO and admin set IRB dates | Medium | fixed | smo1 POST `/studies/GZQO/irb` 403 |
| ROLE-016 reveal reason "other" without text | Medium | fixed | 400 "For 'other', write why … (10 characters or more)" |
| ROLE-017 page and API disagree | Medium | fixed | pi gets `screening-log.xlsx` 200; research office is a matrix row |
| ROLE-018 wrong role descriptions | Medium | fixed | `/ops/users` text is generated from the matrix |
| ROLE-019 API body checked before session | Low | fixed | anonymous POST with `{}`: 401 |
| ROLE-021 orphan `/ops/identity`, `/ops/flags` | Medium | fixed | linked from the admin home "Accounts" tile |
| ROLE-022 no backup, update, ingest-history screens | Medium | fixed (pages) | `/admin/ops` (backups, update and rollback, logs, secrets, network sheet), `/data-ops`. The operations service itself did not run in the demo |
| ROLE-025 duplicate account name message | Medium | fixed (en) | "Refused: user prv exists" |
| ROLE-020, 023, 024, 026, 027, 028 | Low/Medium | not checked | |
| UX-001 demo fails without the jars | Blocker | fixed for the image (read); still true for `make demo` on a checkout, with a clear message | attempt 1 above |
| UX-002 demo resets on restart | Blocker | fixed | `--keep` |
| UX-003 three clocks | High | **partly** | one console clock, but the seed leaves the box five days ahead: "Data as of 2026-11-17", "MICROBATCH run of 2026-11-18" on 2026-11-12 (JRN-010) |
| UX-004 one synthetic hospital for both sites | High | not checked | |
| UX-006 no in-product feedback | Blocker | fixed | feedback form on every page; `/feedback/export.csv` for the admin |
| UX-007 two-model signal never shown | High | **open in the default demo** | 0 "First check / Second check" blocks on the patient page walked; rows say "test model" |
| UX-008 evidence column empty for coded facts | High | fixed | "0.65 mg/dL · 2026-09-03 · LOINC 2160-0", "2026-08-20 · ICD-10-CM M10.9", reasons for every unknown |
| UX-009 English in ja and zh-TW pages | High | partly | 4 criterion labels still English on the ja and zh-TW list; one raw key (JRN-014) |
| UX-011 screening log and participant disagree on consent | High | fixed | after the consent form: log row "enrolled · 2026-11-12 (form 1.0)" |
| FIT-003 the PI cannot start any run | High | **partly** | right and API work (raw POST SCREEN as pi: job done); no working control (JRN-003) |
| FIT-006 "excluded" wording | High | fixed (pages) | "Criteria not matched"; `/excluded` redirects |
| FIT-007 not-matched list without safeguards | High | fixed | weekly sample of ten, send-back, steward's site check (not enforced on synthetic data, and the page says so) |
| FIT-009 thin consent record, no version check | High | mostly fixed | explainer, assistant, LAR, witness, order, language fields; an unapproved version saves with a warning and lands on the re-consent list. A future date is accepted (JRN-007) |
| FIT-017 no data-operations console | High | partly | `/data-ops` with sources, held nights, history; statistics and export ledger not seen |
| FIT-018 "Conflicts" name clash | High | fixed | "Clinical conflicts" (steward) and "Trial-record differences" (study) |
| FIT-024 list not prioritised, unknown does not name the gap | High | partly | clinic list by next visit; each unknown says why; "To do" names the action, not who can answer |
| FIT-025 SAE banner and clock | High | mostly fixed | rule set per study, "The site has not confirmed these deadlines", conservative 00:00 clock |
| FIT-001, 004, 005, 012, 016, 023 | High/Critical | not checked (outside the walk) | |
| J-01, J-02 requests by mailbox allow-list, 20 jobs a day | High | not checked with a new account | seeded crc started 4 jobs; PI limits are in `test_pi_runs.py` (passed) |
| J-03, J-04 viewer reads patients API and job pages | High | fixed | viewer bearer: 403 on `/patients`, `/screening-log`, `/subjects`; 403 on job pages and files |
| J-10 data management only for coordinator | High | fixed | steward pages |
| J-12 no list of excluded patients | High | fixed | `/studies/{rs}/not-matched` |
| J-26 SCREEN of a new study fails on practitioner scope | High | fixed | SCREEN RA-JAK with no scope set: done, 2,530 in scope (the set-up page still says the run "stops until you choose", JRN-015) |
| J-07 PDF with NUL bytes | High | not checked | |

## 5. Findings

| ID | Severity | Finding | Evidence | Impact | Fix | Card | Flag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| JRN-001 | Blocker | A new study cannot get its first approval in the console. After the CRC compiles a pasted protocol (`JRN-T1`), the PI sees "Criteria waiting for your approval", but the approval page has no "Approve" control and says "Only the study's investigator ticks the criteria and approves them"; POST `/approve` as pi: 403. D-380 says the steward names the PI first, but `/studies/JRN-T1/team` answers 404 for steward, PI, CRC and admin, because a study is "known" only once a ruleset folder exists, and that is written at approval. | Run: `walk/pi5.js`, `pi6.js`, `stw1.js`, `raw.js` (403, 404, 404, 404); `evidence/JRN/JRN-09-pi-approval.png`; `services/console/studies.py:30-37`, `team.py:245-262`; `tools/e2e_simple.py:478` and `tools/feas_demo.py:222-236` write the PI entry through `TeamStore` directly; `journeys.yaml` J-CRC-02 only amends an existing study | No site can start its first study, or any later new study, without a database write by the vendor. In the PoC a clinician who pastes own criteria is stuck at step 2 | Let `known_study` accept a ruleset id with a job awaiting approval, so the steward's delegation page opens; on the approval page tell a non-named investigator "the steward must name the study's PI on the delegation log" with the link for the steward; show the steward a task "name the PI of JRN-T1". Add the journey "new study from protocol to first list" to `journeys.yaml` without seeding the PI | NEW-JRN-1 "First approval of a new study: steward names the PI before approval" (S) | PoC |
| JRN-002 | Critical | The opt-out register accepts any 8 to 64 character string as a pseudonym and answers "Recorded: the patient opted out. The patient is removed from screening, lists and later exports." Typed as every screen shows a patient (`e7543f47`), the entry is stored for that 8-character string; the patient `e7543f47686f…` stays on the PI's list and opens (200). `deadbeef` is accepted the same way. | Run: `walk/stw2.js` step 2, then pi GET patient page 200; `services/console/team.py:90` (`_PID = ^[A-Za-z0-9_-]{8,64}$`), `team.py:961-966` (no check that the pseudonym is whole or known) | A patient who opted out keeps being screened and listed while the register shows them as opted out: a privacy and regulatory failure that nobody sees | Accept only a whole pseudonym (32 hex) or a chart number; resolve a unique short form against the box and show what was matched; refuse an unknown pseudonym unless it came from a chart number; show on the register how many lists the patient left | NEW-JRN-2 "Opt-out by pseudonym: whole and known, or refused" (S) | Go-live both |
| JRN-003 | High | The PI has the right to start FEAS, SCREEN and CASE (T-512) but no working control. The PI's menu item "New request" opens "You are signed in as a viewer … a coordinator or administrator starts requests" with no form; the CASE page shows the same warning and a disabled button; no PI page has a SCREEN starter. Only "Refresh" on an existing feasibility report works. A hand-made POST `/pilot/request` SCREEN as pi runs the job. | Run: `walk/pi2.js`, `pi3.js`; `evidence/JRN/JRN-05-pi-new-request.png`; `templates/request.html:18` (`{% if not user.can_request %}`), `templates/case.html:5,27`; `tests/console/test_pi_runs.py:68-76` posts a hand-built body and never looks for the form | FIT-003 stays true for the person at the screen: the PI cannot ask "how many fit" for a study without a report, cannot re-run the list, cannot ask a CASE question | Render the forms when the account may run in at least one study (`h.may_run`), listing only those studies; enable the CASE button on the same rule; assert the controls in `test_pi_runs.py` | T-512 follow-up, NEW-JRN-3 "PI run controls on the request and CASE pages" (S) | PoC |
| JRN-004 | High | Closing a study is one click, final and unchecked. `study.state` grants every coordinator, including an SMO coordinator. The CRC closed GZQO while 2 participants were on study, SAE reports to the IRB and regulator were open and 3 possible deviations were unanswered: 303, "Closed is final. A closed study cannot change state." No confirmation page (the backup button has one), no list of open items, no second person. After closing, the home card, the list, the participant page and the deviation page show no "closed" mark; the request form still offers the study and the job fails after it is created. An SMO coordinator paused the study with a one-word reason. | Run: `walk/close.js` (RA-JAK), `walk/last.js` (GZQO, smo1 pause 303); `evidence/JRN/JRN-16-crc-closed.png`; `libs/tb_common/authz_matrix.yaml:158` | A mis-click or an external coordinator ends list making and mails for a recruiting study for good; only a database change brings it back. Open safety work is not surfaced at close | Confirmation page that lists participants on study, open SAE reports, unanswered deviations, unsigned EDC values and open monitor grants; closing by the PI (or the PI confirms the CRC's request); a "closed" badge on every study page; "closed to recruitment" (no lists) apart from "closed" (all participants off study); refuse the request at the form | NEW-JRN-4 "Study close: confirm, open-item check, PI, visible state" (M) | Go-live both |
| JRN-005 | High | The EDC item map cannot be saved when the form holds more than 1,000 fields: 13 fields per item, so 77 items or more fail with a raw JSON answer `{"detail":"Too many fields. Maximum number of fields is 1000."}` (HTTP 400, no page). The demo's own REDCap dictionary (77 rows shown) already fails. | Run: `walk/e5.js`, `e6.js` (1,005 fields submitted, 77 items); `services/console/edc_pages.py:623-625` (`form_of` uses the framework default) | A real eCRF has hundreds of items: prefill and copy-assist cannot be set up from the browser for any real study. The limit is a framework default, not a declared setting (OD-10) | Read the form with a field limit derived from the dictionary size (items × fields per row + a margin), or post the map as JSON; answer with the console's error page | NEW-JRN-5 "Item map form limit from the dictionary size" (S) | Go-live both |
| JRN-006 | High | Privacy-office journey has a missing step. A patient asks "who saw my record" and gives a chart number. The one-patient audit report takes a 32-character pseudonym only ("Chart numbers are not searched here"), and by design no page gives the privacy office a pseudonym back. There is no erasure or access request record. | Run: `walk/prv1.js` steps 3, 3b; `/audit?bad=pid` text | APPI 開示 and PDPA 查詢 requests cannot be answered from the console; the office would have to record an opt-out and read the pseudonym out of its own audit line | "Report for a chart number": the box derives the pseudonym at the door and returns the report without showing it (audited, capped as the opt-out lookup is); a request log (access, erasure) with state | T-206b for erasure; NEW-JRN-6 "Disclosure report by chart number, request log" (M) | Go-live both |
| JRN-007 | High | The consent form saves a consent date in the future without a word: GZQO-0002 "Consent: given 2027-03-01 on version 1.0". The screening log and the enrolment report then carry it. An unapproved form version is warned about; a date after today, or after enrolment or a visit, is not. | Run: `walk/crc3.js` step 17 | Consent before any study procedure is the first thing an inspector checks; a typing error becomes the record and the visit windows anchored on consent move | Refuse a consent date after the site's day; warn (and list as a possible deviation) when consent is after enrolment or after the first visit | NEW-JRN-7 "Consent date checks" (S) | Go-live both |
| JRN-008 | High | The monitor's journey has a dead start and a thin end. After sign-in the CRO account sees only "Feasibility reports"; nothing links to `/studies/{rs}/monitor` (typed URL). The source-reference sheet shows only values a person confirmed in EDC prefill: for a subject whose consent, visit and adverse event were typed into the built-in forms it says "No CRF value of this subject has been confirmed yet". The monitor cannot read the screening log, deviations or the SAE register (403). | Run: `walk/ext.js`; `evidence/JRN/JRN-14-cra-monitor.png`, `JRN-15-cra-sdv.png` | A monitoring visit cannot be done in the product for a study on the built-in forms; the monitor does not find the page without being told the address | Under a grant, show "Monitoring: GZQO (visit MV-01, until …)" on the reports page and in the menu; add to the sheet the built-in form values with their audit trail, the consent facts, deviations and SAE dates of enrolled subjects, read-only | T-303 follow-up, NEW-JRN-8 "Monitor entry point and SDV of built-in forms" (M) | Go-live both |
| JRN-009 | Medium | `make e2e-simple` does not ask for its inputs. The target depends on neither `$(JVM_DEPS)` nor `$(FONTS)` (`make test` does). The jar check fails at once with a clear line; the font is found missing only after 2 min 54 s, as three "failed in reporting" jobs and an `AssertionError` | Run: attempts 1 and 4; `Makefile:195-197`, `Makefile:96` | A new developer or a CI job on a clean runner loses a run before learning what to fetch | Make the target depend on `$(FONTS) $(JVM_DEPS)`, or check the fonts next to the jar check in `tools/e2e_simple.py` | NEW-JRN-9 "e2e-simple checks fonts up front" (S) | Later |
| JRN-010 | High | The PoC demo is seeded five days ahead of its own day. Stage 17 (screening cadence) leaves the list "From the MICROBATCH run of 2026-11-18 · data snapshot 2026-11-17", every patient page "Data as of 2026-11-17", every new report "snapshot 2026-11-17, run 2026-11-12", on demo day 2026-11-12. A visit done today is then flagged "outside the window 2026-11-17 to 2026-11-21". | Run: `evidence/JRN/JRN-01-pi-week.png`, `walk/crc1.js`, `crc2.js`, `crc4.js` | The two PoC clinicians read data dated in the future and false deviations: the first minutes of the PoC go to explaining the clock (UX-003 again) | Run the cadence stage on a copy, or roll the box back to the demo day after it; assert in `tools/demo.py` that no page date is after the demo day | T-513 follow-up, NEW-JRN-10 (S) | PoC |
| JRN-011 | Medium | An SMO coordinator scoped to GZQO reads the research-office yearly counts of every study (GOUT-COH, RA-JAK) on the page and in the XLSX. | Run: `walk/smo2.js`; `authz_matrix.yaml:98` (`report.office: coordinator: true`, no scope) | An external party sees other sponsors' recruitment numbers | Filter the rows by `sees_study`; refuse a scoped account the site-wide XLSX | NEW-JRN-11 (S) | Go-live both |
| JRN-012 | Medium | Pages and menus leak across roles without giving rights. The steward and the privacy office open `/pilot/registry/{rs}` (pseudonym rows with status, and "Add", "Take over", "Save" forms that answer 403), `/jobs`, `/pilot/case`, `/pilot/cascade`; their "More" menu lists Runs, Single case, Registry. The viewer gets the forms of `/pilot/protocol`, `/pilot/consent` and `/pilot/case` (POST 403). The administrator's list page `/pilot/registry` opens while `/pilot/registry/GZQO` is 403. | Run: route crawls (§7), `walk/prv1.js`, `raw.js` | Roles with `phi.view: false` read pseudonymous rows; staff press buttons that only refuse | Guard these GET routes with the same matrix rows as their POSTs; build the "More" menu from the matrix | NEW-JRN-12 "GET guards and menu from the matrix for the pilot pages" (S) | Go-live both |
| JRN-013 | Medium | Any investigator who is on the study's log with any tick acknowledges a serious adverse event. `subpi` (screen and refer only) acknowledged the SAE of GZQO-0004: 303. The matrix row is `sae.ack: investigator: true`; the code comment says "the study's investigator only". An investigator on no log is refused (403). | Run: `walk/ext.js` last line, `walk/inv2.js`; `authz_matrix.yaml:434`, `lifecycle_pages.py:274-279` | The banner "until the investigator acknowledges it" is cleared by someone the PI did not delegate safety review to | `sae.ack: investigator: [pi, task:sae]` with a delegation tick "SAE review" | NEW-JRN-13 (S) | Go-live both |
| JRN-014 | Medium | The participant page prints the raw key `life.vstate.unplanned` in the Status column of every visit before enrolment, in en, ja and zh-TW. | Run: `walk/pi4.js`, `walk/close.js`; `i18n_life.py:103-108` has six states, not this one | Visible on the page the CRC uses most | Add the key in three languages; a test that every state the lifecycle can return has a label | NEW-JRN-14 (S) | PoC |
| JRN-015 | Medium | Wrong or contradicting sentences on working pages: (a) the banner "Criteria waiting for your approval: JRN-T1" is shown to the CRC and to an investigator on no log; (b) the admin home says "Approvals 0 waiting for approval" while one waits; (c) `/ops/users` says "Leave empty for every study" and then refuses an SMO or CRO account without studies; (d) study set-up says "Not set yet: a screening run of this study stops until you choose" and the run proceeds on the whole hospital; (e) after a forced password change the sign-in page shows no "password changed, sign in again". | Run: `walk/inv2.js`, `crc4.js`, `adm1.js`, `first.js`; `i18n_home.py:73` | Small, but each one costs a support call at a site | Fix the five texts and conditions | NEW-JRN-15 (S) | PoC |
| JRN-016 | Medium | In the PoC demo a run blocks the browser with no progress: FEAS refresh 12.3 s, FEAS 4.2 s, SCREEN of RA-JAK 22 s (2,530 in scope), the PI's SCREEN of GZQO over 30 s (the HTTP client gave up; the job finished). The in-process backend runs the job inside the request. | Run: `walk/pi2.js` (timeout), `pi3.js`, `crc4.js` | A tester presses the button twice or leaves; on the hosted demo a proxy may cut the request | Start the job in a worker thread in `InprocBackend` and redirect to the job page at once, as the real orchestrator does | NEW-JRN-16 (S) | PoC |
| JRN-017 | Medium | A POST of the item map without item rows replaces the stored map with nothing: 303, then "No item map yet" (8 items gone, "to review" 3 became 0). No confirmation, no earlier version offered. | Run: `raw.js crc POST /studies/GZQO/edc/map token_ref=edc` | A broken form post or a script loses the study's map | Refuse an empty map; keep versions and show "restore the previous map" | NEW-JRN-17 (S) | Go-live both |
| JRN-018 | Low | `tools.pglocal.ensure` reuses a half-initialised cluster: after a failed `initdb` the folder has `PG_VERSION`, the next run starts it and fails with `database "postgres" does not exist` until someone deletes the folder. `_grant_traverse` adds `o+x` once; when the parent's mode is reset later, every new run fails with "Permission denied". | Run: attempts 2, 3; `tools/pglocal.py:98-122`, `190-199` | Lost time on shared or sandboxed machines | Treat "no `postgres` database" as not initialised (remove and re-init); say which parent folder the server user cannot enter | NEW-JRN-18 (S) | Later |
| JRN-019 | Medium | In the stub-model demo a pasted protocol with plain diagnoses ("Diagnosis of gout", "Type 1 diabetes mellitus") compiles to "left to a person" for 3 of 6 criteria, with the warning "the box would do little of the screening for this trial". Not checked with a real model. | Run: `walk/crc3.js` step 18b | A PoC clinician who pastes own criteria concludes the product cannot code a diagnosis | Say on the page that the demo's compiler is a stand-in, or ship cassettes for the PoC studies the two clinicians will paste | NEW-JRN-19 (S) | PoC |
| JRN-020 | Medium | The sponsor journey exists only as an offline sample. `python -m tools.opportunity_feed sample` writes a static HTML board (two synthetic sites, signed feeds, three languages). There is no served hub, no sponsor account, no steward page for the approved list, no OPPORTUNITY job, no "send us your protocol" request. In the console the sponsor's person is the CRO account: reports in the sponsor form and the sponsor pack zip. | Run: `evidence/JRN/JRN-17-sponsor-board-sample.png`; plan file 32 §3 (T-741, T-742, T-743 open) | "Sponsor dashboard / opportunity feed" must not be shown as a product module yet | Keep it out of the go-live scope; build T-742 before T-743 | T-741, T-742, T-743 | Later |
| JRN-021 | Medium | The product's own PQ journeys (`journeys.yaml`, 8 journeys, 35 steps; the 7 tests of `test_journeys.py` pass) do not walk: first approval of a new study, a run started by the PI, visits, SAE record and reports, deviations, the monitor's visit record, EDC sign and send, study close, account creation and first sign-in by a new role, backup and update, the privacy report. JRN-001 to JRN-005 all sit in these gaps. | Read: `tests/e2e/journeys/journeys.yaml`; run: 7 passed in 112 s | The PQ script passes while a site cannot start a study | Add one step per gap; never seed through `TeamStore` in a journey | T-315a follow-up, NEW-JRN-20 (M) | Go-live both |
| JRN-022 | Low | `/healthz` without sign-in still returns the environment and the database schema name (ROLE-007). | Run: curl | Small information leak | Return `{"status":"ok"}` to callers without a session | NEW-JRN-21 (S) | Go-live both |
| JRN-023 | Low | Language leftovers in the en demo and on ja and zh-TW pages: seed task note "HbA1c の最新値を確認", SAE term "肺炎"; four criterion labels in English on the ja and zh-TW list (Willing to self-inject, Bariatric surgery, Planned surgery, Participation in another interventional …). | Run: `walk/crc1.js`, `close.js` | Reading friction for the PoC clinicians | Seed notes per `--lang`; labels for the four criteria | T-507 follow-up | PoC |
| JRN-024 | Low | While seeding, the report figure code warns "Glyph 24746 (悪) / 27507 (歳) missing from font(s) Noto Sans TC": Japanese text is drawn with the Taiwan font. The PDF was not opened. | `demo.log` (reviewer scratch); `services/orchestrator/reports/common.py:120` | Empty boxes in a Japanese chart | Pick the figure font by report language | NEW-JRN-22 (S) | Go-live JP |
| JRN-025 | Low | The reason shown for one unknown is hard to read: serum urate "unknown" lists three allopurinol dispensings and "a code of this family that the list does not hold". | Run: patient page text (`walk/p1.js`) | The PI cannot tell what to order | Say "no serum urate result in the last 365 days; the patient is on urate-lowering therapy" | T-507 follow-up | PoC |

### 5.1 Detail for JRN-001

Sequence walked: (1) crc, `/pilot/protocol`, id `JRN-T1`, six pasted criteria, "Compile": 303 to the job page "FEAS
JRN-T1 v1.0.0 waiting for approval". (2) pi signs in: banner "Criteria waiting for your approval: JRN-T1 v1.0.0".
(3) pi opens the approval page: six "Codes checked" buttons and no "Approve"; pressing one answers "Codes marked as
checked. The investigator sees your tick." (the PI is treated as a preparer). (4) pi POST `/pilot/jobs/{id}/approve`:
403. (5) pi, stw, crc, admin GET `/studies/JRN-T1/team`: 404 "the study is not one of yours". (6) stw POST
`/studies/JRN-T1/team` with `role=pi`: 404. The draft ruleset exists only as `ruleset_JRN-T1_v1.0.0-draft.zip` in the
job's outputs, so `ruleset_infos()` does not list it and `known_study()` is false. The mail route (the PI replies
APPROVE) was not tried; the console is the route the journeys describe.

### 5.2 Detail for JRN-004

RA-JAK: close without a reason: 400 "Give a reason to pause or close the study." With a reason: 303, the state form
disappears. GZQO: smo1 (affiliation SMO, scope GZQO) POST `state=paused`: 303; smo1 `state=open`: 409; crc
`state=closed`: 303 with participants GZQO-0001 and GZQO-0004 "On study", the SAE of GZQO-0004 with IRB and regulator
reports "open", three deviations "to answer", the monitor grant MV-01 still running, signed EDC values of GZQO-0003 not
all sent. Afterwards `/studies/GZQO/subjects/GZQO-0004`, `/studies/GZQO/deviations`, `/studies/GZQO/week` and the home
card do not say "closed"; the participant page still offers its step forms.

## 6. Journeys by role (numbered steps as walked)

Result codes: **W** works · **B** breaks (status, text) · **D** dead end (no next action on the screen) · **M** missing
step (the lifecycle needs it, no screen) · **X** wrong role.

### 6.1 Principal investigator (`pi`)

| # | Module | Step | Result |
| --- | --- | --- | --- |
| 1 | Sign-in | name and password; second factor off in this demo | W, 3.3 s to the landing page |
| 2 | Home | lands on "This week's patients · GZQO", worklists (Clinic next 2 weeks 13, Ready 3, Needs information 75 …), SAE banner | W; dates five days ahead (JRN-010) |
| 3 | Criteria | banner for a new study, approval page | **B/D** no approve control, POST 403 (JRN-001). Amendment of an existing study: covered by the product journey J-PI-02 (passes) |
| 4 | Feasibility | open report; "Refresh" | W, 12.3 s blocking (JRN-016) |
| 5 | Feasibility, first run | "New request" | **D** "You are signed in as a viewer" (JRN-003) |
| 6 | Screening run | any SCREEN control | **M** none on any PI page; hand-made POST works (JRN-003) |
| 7 | List | clinic list, worklists, all 79 | W |
| 8 | Case review | open patient: why it fits, still open, needs you, to do, 24 criteria with dated evidence or a reason | W |
| 9 | Need info | note, one click; "Sent to the coordinator's task list. Undo" | W |
| 10 | Not suitable | without a reason: nothing happens (browser asks for the reason); with a reason: "Set aside for now … Undo" | W |
| 11 | Undo | one click: "Undone. The patient is back as before." | W |
| 12 | Approach | one click: "Approved. The coordinator has a task to contact this patient."; screening number GZQO-0004 | W |
| 13 | Referral | "Ask treating doctor", purpose page, route form, "Please confirm" | W to the confirmation page (not sent in this walk; J-PI-04 passes) |
| 14 | Not-matched sample | ten patients, "Send back" with a note | W |
| 15 | SAE | "Acknowledge" on the list page | W |
| 16 | Delegation log | add monitor grant for `cra`, MV-01, 3 days | W |
| 17 | EDC | turn prefill on with the sponsor's letter and the re-entry numbers | W |
| 18 | CASE | page opens | **D** button disabled, "signed in as a viewer" (JRN-003) |
| 19 | Participants, visits, deviations | read | W, read-only ("Only the study's coordinator records steps"); raw key (JRN-014) |
| 20 | Study state | pause, close, identifiers, IRB text record | W as forms; close not tried as pi (JRN-004) |
| 21 | Break-glass | form to open a grant | W (walked as `inv2`: grant opens one patient for 60 minutes) |
| 22 | Monitoring page | "No monitoring visit recorded yet" | W |
| 23 | Close-out, archive | | **M** only the state "closed" (JRN-004) |

### 6.2 Sub-investigator (`subpi`, ticks: see candidates, ask a treating doctor)

| # | Step | Result |
| --- | --- | --- |
| 1 | lands on the list; patient page has Need info, Not suitable, Not now, Show chart number; no Approach | W |
| 2 | Need info | W |
| 3 | typed Approach, SCREEN, self-promotion to PI on the log | W (403, 403, 403) |
| 4 | other study RA-JAK; EDC page | W (403; 403 without the enter-data tick) |
| 5 | acknowledge an SAE | **X** 303 without a safety tick (JRN-013) |

### 6.3 Coordinator (`crc`)

| # | Module | Step | Result |
| --- | --- | --- | --- |
| 1 | Home | "My work": SAE banner, visits today, tasks by due day, coming clinic visits, one card per study with the six steps and "Next: … Go" | W |
| 2 | Protocol | paste criteria under a new id, "Compile" | W, 0.5 s to "waiting for approval"; then the study is stuck (JRN-001) |
| 3 | Feasibility | "Go" on the RA-JAK card, "Count eligible patients" | W, 4.2 s |
| 4 | Screening run | "Find candidates for the next visits", no doctor ids | W, 22 s blocking; 156 to review of 2,530 |
| 5 | Contact | task "Contact patient 2c519139 (GZQO): PI approved", one click to the patient, "Reached, visit booked" | W, with Undo |
| 6 | Screening log | row GZQO-0004 "Reached, visit booked · contacted"; XLSX download | W |
| 7 | Consent | Participants, GZQO-0004, "Record consent", date, version, taken by, copy given, Save | W; unapproved version warned; future date accepted (JRN-007) |
| 8 | Enrolment | "Enrolled" with the day; undo the last step; again | W |
| 9 | Visits | "Open the visit form" v1, done today | W ("outside the window", because of JRN-010) |
| 10 | Adverse event | serious, with onset and day learned | W; "Related to the study treatment: required" caught the first save |
| 11 | SAE register | case page: three first reports with due days, "Record the report sent", follow-ups | W |
| 12 | Deviations | confirm one, dismiss one with a reason | W |
| 13 | Enrolment report | counts by step and month, CSV and XLSX | W |
| 14 | IRB | approval number, dates, form version for RA-JAK | W |
| 15 | EDC | item map: read the dictionary | W (9 fields read) |
| 16 | EDC | save the item map | **B** 400 raw JSON "Too many fields" (JRN-005) |
| 17 | EDC | review page of a drafted visit: value, source, confirm, change with reason and password, signature text | W (seeded draft; drafting a new visit not completed in this walk) |
| 18 | Study state | close | W, and that is the problem (JRN-004) |
| 19 | Opt-out register, audit, admin pages | | W (403) |
| 20 | Close-out, archive, retention | | **M** |

### 6.4 SMO coordinator (`smo1`, scope GZQO)

Created by the admin; first sign-in with the one-time password forces a new password. Lands on "My work" with GZQO only;
RA-JAK and GOUT-COH pages 404; opt-out 403; IRB save 403; `/jobs`, `/audit` 403. **X**: research-office counts of all
studies (JRN-011); pause and close of the study (JRN-004).

### 6.5 Monitor / sponsor's CRA (`cra`, CRO account, studies GZQO and GOUT-COH)

| # | Step | Result |
| --- | --- | --- |
| 1 | lands on "Feasibility reports" (sponsor copy, small counts hidden); sponsor pack zip | W |
| 2 | find the monitoring page | **D** no link (JRN-008) |
| 3 | `/studies/GZQO/monitor` under the PI's grant: "Read-only, enrolled subjects only. Visit MV-01; the grant ends 2026-11-15"; three enrolled subjects | W |
| 4 | source references of GZQO-0003 (prefill values with record item and signature) | W |
| 5 | source references of GZQO-0001, GZQO-0004 (built-in forms only) | **M** "No CRF value … confirmed yet" (JRN-008) |
| 6 | record the visit (date, subjects verified, findings) | form present; not submitted in this walk |
| 7 | candidates, patient page, subjects, EDC trail, screening log, deviations, SAE, audit; study outside the scope | W (403; 404) |

### 6.6 Viewer

Lands on "Feasibility reports"; research-office counts with "<5"; every patient page and API 403. Leftover forms on
`/pilot/protocol`, `/pilot/consent`, `/pilot/case` (JRN-012).

### 6.7 Data steward (`stw`)

| # | Module | Step | Result |
| --- | --- | --- | --- |
| 1 | Home | lands on "Break-glass" (grants to review within 7 days) | W |
| 2 | New study | learn that a study needs its PI named; open its delegation log | **M/B** nothing tells the steward; 404 (JRN-001) |
| 3 | Opt-out | record by pseudonym (short form) | **B** silently wrong (JRN-002) |
| 4 | Opt-out | lift without a reason | W (400) |
| 5 | Conflicts | "Clinical conflicts": none open in the demo | W (empty; J-STW-03 passes with a seeded conflict) |
| 6 | Data operations | sources, held nights, ingest history with filters | W (no held night in the demo; J-STW-04 passes) |
| 7 | Audit | filters, one-patient report, "Verify the chain": "2139 events in 1 day files" | W |
| 8 | Not-matched | record the site check | W (form) |
| 9 | Items, staff directory | read, add | W |
| 10 | Registry, jobs, CASE pages | | **X** readable, forms refuse (JRN-012) |

### 6.8 Privacy office (`prv`)

Lands on "Opt-out register". Opt-out by chart number: W (no pseudonym shown back). Audit browser and one-patient report
by pseudonym with CSV: W. Report by chart number: **M** (JRN-006). Erasure request: **M**. Registry, jobs, CASE pages
readable: **X** (JRN-012). Patient pages 403: W.

### 6.9 Administrator / hospital IT (`admin`)

| # | Module | Step | Result |
| --- | --- | --- | --- |
| 1 | Home | tiles: system 3/3, job queue, models and policy, reference data, operations, backups, update, accounts, approvals, audit of the last 24 hours | W; "Approvals 0" is wrong (JRN-015) |
| 2 | Accounts | create privacy, steward, investigator; one-time password in groups of four; SMO or CRO without studies refused; duplicate name refused | W |
| 3 | Sign-in and recovery | enrolment code for an account (shown once, 24 hours) | W |
| 4 | Feature flags | five flags, each change needs a reason | W (page) |
| 5 | Backups | "Back up now" asks to confirm; "No backup target is set"; "The box's operations service has never run on this box" | W as a page; the operation itself cannot run in the demo |
| 6 | Update and rollback, logs, secrets, network sheet | pages open with clear empty states | W (not exercised) |
| 7 | Data sources | "Ingest synthetic site A": "Ingest started." | W |
| 8 | Data operations | read-only view of nights | W |
| 9 | Patient pages, audit browser, opt-out, staff | | W (403) |
| 10 | Break-glass | form to open a grant | W (page) |
| 11 | First-run wizard, real backup and restore, update apply | | not walked (needs the box) |

### 6.10 Sponsor

No sponsor role and no served dashboard (JRN-020). The sponsor's reader is the CRO account of §6.5.

## 7. Role × module matrix

Cells: **W** the role does its part · **R** reads only, as intended · **–** refused, as intended · **D** dead end ·
**M** missing · **X** wrong role · **B** breaks · blank: not this role's module.

| Module | PI | sub-PI | CRC | SMO CRC | Monitor (CRO) | Viewer | Steward | Privacy | Admin (IT) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Sign-in, forced password change | W | W | W | W | W | W | W | W | W |
| Second factor in the browser | not walked | | | | | | | | |
| Home | W | W | W | W | W | W | W | W | W |
| Protocol to criteria (new study) | **B** JRN-001 | – | W then stuck | W then stuck | – | – (form shown, X) | **M** | – | – |
| Criteria approval (amendment) | W (product journey) | – | prepares | prepares | – | – | – | – | – |
| Feasibility run | D first run, W refresh | – | W | not walked | – | – | – | – | W by right, not walked |
| Feasibility report | R | R | R | R | R sponsor copy | R | R | R | R |
| Screening run | **M** control | – | W | not walked | – | – | – | – | W by right, not walked |
| Weekly list, case review | W | W | R | R | – | – | – | – | – |
| Marks, undo | W | W (no Approach) | – | – | – | – | – | – | – |
| Referral | W | W | answers | answers | – | – | – | – | – |
| Contact outcome | R | R | W | not walked | – | – | – | – | – |
| Consent, enrolment, participant steps | R | R | W | not walked | – | – | – | – | – |
| Visits, schedule | R | R | W | not walked | – | – | – | – | – |
| SAE record and reports | ack W | ack **X** | W | not walked | – (M for SDV) | – | – | – | – |
| Deviations | R | R | W | not walked | – (M for SDV) | – | – | – | – |
| EDC prefill | switch W | – | review W, map **B** | not walked | – | – | – | – | switch off by right |
| Monitoring / SDV | grants W | – | – | – | W, **D** entry, **M** built-in forms | – | grants | – | – |
| Screening log, enrolment report | R | R | W | R | – | – | – | – | – |
| Candidate registry | R | R | W | R (own study) | – | – | **X** | **X** | list only |
| Delegation log | W | R | R | R | – | – | names PI (**B** for a new study) | R | R |
| IRB and consent-form versions | W | R | W | R | – | – | R | R | R |
| Opt-out register | – | – | – | – | – | – | W (**B** JRN-002) | W | – |
| Break-glass | W | W | – | – | – | – | reviews | – | W |
| Audit browser | – | – | – | – | – | – | W | W, **M** by chart number | – |
| Data operations, conflicts, items | – | – | – | – | – | – | W | – | R (data-ops) |
| Accounts, identity, flags | – | – | – | – | – | – | – | – | W |
| Backup, update, logs | – | – | – | – | – | – | – | – | pages W |
| Study state, close | W by right | – | W (**X** unchecked) | **X** | – | – | – | – | – |
| Close-out, archive | **M** | | **M** | | **M** | | | | |
| Research-office counts | – | – | R | **X** all studies | – | R | – | – | R |
| Sponsor dashboard, opportunity feed | | | | | **M** | | **M** approved list | | |

## 8. Time and clicks for the key tasks (one browser, machine under load 7 to 13)

| Task | Role | Clicks after sign-in | Typing | Server time |
| --- | --- | --- | --- | --- |
| Find today's candidates | PI | 0 (the landing page is the clinic list) | none | list page 1.0 to 1.5 s |
| Open a case and see why a criterion is unknown | PI | 1 | none | 0.95 s; the reason is in the evidence column |
| Need info | PI | 1 | optional note | 2.0 s |
| Not suitable, then undo | PI | 2 (reason, button) + 1 | none | 2.4 s + 1.6 s |
| Approach | PI | 1 | none | 1.8 s |
| Record the contact outcome | CRC | 2 (task, outcome) | none | 1.5 s + 2.2 s |
| Record consent | CRC | 4 (Participants, subject, Record consent, Save) + 1 radio | date, version, name | 4.0 s for all pages |
| Enrol | CRC | 1 | date | 0.5 s |
| Create an account and read the password | Admin | 2 | name, mailbox | 0.5 s |
| FEAS / SCREEN | CRC | 2 | none | 4.2 s / 22 s blocking |

## 9. Every 4xx and 5xx seen, and the server log

Browser side, all walks and crawls: **5xx: 0.** 403: about 340, all from deliberate probes of pages outside a role
(§7) except those listed as findings. 404: `/pilot/mailbox` for every role (test page, off); `/studies/JRN-T1/team`
(JRN-001); CRO outside its scope. 400: account without studies (3, intended), close without a reason (intended),
opt-out lift without a reason and bad pseudonym (intended), reveal "other" without text (intended), item map
(JRN-005). 409: SMO reopening a paused study. 422: viewer POST `/pilot/case` with a text body (body checked before
the right on this form route). Sign-in failures: 6, all from my own wrong one-time passwords.

Server log while serving (3,379 lines): no ERROR, no WARNING, no traceback. Inner calls: 3,336 × 200; 34 ×
`GET /studies/GZQO/settings` 404 and 3 × RA-JAK (read as "no settings yet"); 2 × `GET /studies/RA-JAK/redcap-link` 404;
3 × `POST /studies/…/entry/…` 409 (form validation). Slowest inner call: `GET /setup/main/feasibility` 3.3 s, which
makes `/site` take 2.6 to 4.1 s. During seeding: the font warnings of JRN-024.

## 10. What to drop or simplify

- The "pilot" request pages as a second way in: `/pilot/request`, `/pilot/case`, `/pilot/protocol`, `/pilot/consent`,
  `/pilot/cascade`, `/pilot/registry`, `/jobs` carry the oldest guards and the most role leftovers (JRN-003, JRN-012).
  Put the run buttons on the study card and the feasibility page for the roles that may run, and take these pages out
  of every menu except the coordinator's.
- "Candidate registry" beside "Participants" and "Screening log": three lists of the same people with three status
  vocabularies ("the consent status here is the coordinator's note, not the consent record"). Keep the screening log and
  the participants; make the registry an export.
- Two delegation mechanisms for one question ("who is the PI"): the log entry and the steward's naming step. Keep the
  rule, but give it one screen and one task (JRN-001).
- The sponsor board as a "module" in material shown to sites: it is a sample page (JRN-020).

## 11. What the plan must change (inputs to plan v7)

1. NEW-JRN-1 (S) before anything shown to a PoC clinician: first approval of a new study. Depends on nothing.
2. NEW-JRN-2 (S) and NEW-JRN-13 (S), NEW-JRN-11 (S), NEW-JRN-12 (S): the four role and privacy repairs, one branch.
3. NEW-JRN-3 (S) closes FIT-003 for real; NEW-JRN-16 (S) and NEW-JRN-10 (S) with it for the PoC.
4. NEW-JRN-4 (M) study close, then a "close-out and archive" card (M) that does not exist in the plan: final lists,
   export package, retention date, account end dates. Depends on NEW-JRN-4.
5. NEW-JRN-5 (S), NEW-JRN-17 (S) before any EDC prefill pilot; NEW-JRN-7 (S) before the first real consent.
6. NEW-JRN-8 (M) monitor entry and SDV of built-in forms; NEW-JRN-6 (M) privacy report by chart number; both before
   go-live in either country.
7. NEW-JRN-20 (M): the PQ journeys grow by the gaps of JRN-021, and the rule "a journey never writes the database
   directly" goes into `test_journeys.py`. Order: with each fix above, its journey step.
8. T-741 to T-743 stay "Later" and out of the go-live scope.

## 12. Needs GCP / owner hardware

1. Hosted PoC image on the GCP VM: build `demo/Dockerfile`, start with `--accounts` and TOTP on; record time to first
   answer and VmHWM; pass: under 10 minutes and under 2.5 GB (the README's own numbers); then walk §6.1 steps 1 to 12
   on a phone.
2. On a real box with the operations service on: `/admin/ops` "Back up now", "Check the newest backups", one update
   bundle applied and rolled back; record each operation's duration and the page's state after it; pass: every state
   the page shows matches `tools.trialbox` on the box.
3. With the real judge and verifier: paste the six criteria of JRN-019; record how many are "left to a person"; pass:
   the three diagnosis and lab criteria are coded; and SCREEN of RA-JAK from the browser: time from click to job page
   (pass: the request returns in under 2 s, the job page shows progress).

## 13. Small certain fixes

| For | File:line | Change | Test that fails first |
| --- | --- | --- | --- |
| JRN-002 | `services/console/team.py:961-966` | in `to_pid`, accept a typed pseudonym only if it matches `^[0-9a-f]{32}$` (as `entry_pages._PID`); else `refused(OptOutError("type the whole pseudonym (32 characters) or the chart number"))` | `tests/console/test_team_pages.py`: POST `/site/opt-outs` with `pid=e7543f47` expects 400 and an unchanged register |
| JRN-003 | `services/console/templates/request.html:18`, `case.html:5,27` | replace `user.can_request` by a flag from the view (`may_run_any`: `h.may_run(user, kind, rs)` for any listed study) and list only those studies | `tests/console/test_pi_runs.py`: `'data-testid="start-feas"' in pi.get("/pilot/request").text` and the CASE button not `disabled` |
| JRN-005 | `services/console/edc_pages.py:625` | read this form with `request.form(max_fields=<items in the stored dictionary> * 13 + 50)` | `tests/console/test_edc_pages.py`: save a 100-item map through the form, expect 303 |
| JRN-014 | `services/console/i18n_life.py:103-108` and the ja, zh-TW blocks | add `life.vstate.unplanned` ("Not planned yet" / 「未予定」 / 「尚未排定」) | a test that renders the participant page of a consented, not enrolled subject and finds no `life.vstate.` |
| JRN-001 (first half) | `services/console/studies.py:30-37` | `known_study` also true when a job of that ruleset is in `awaiting_approval` | `tests/console/test_team_pages.py`: steward GET `/studies/NEW1/team` after a compile is 200, and the PI's approval then 303 |

## 14. What is good

- Authorisation is now one table, and the walk agrees with it almost everywhere: an investigator on no log, the viewer,
  the CRO and the administrator are refused every patient page and action tried; an SMO account is held to its study.
- The patient page: why the patient fits, what is still open, what needs a person, a to-do, and for every criterion the
  dated coded value or a plain reason for "unknown". One click from the list.
- Undo on every mark and on participant steps; reasons required where they matter (not suitable, lift an opt-out,
  reveal "other", pause or close).
- The SAE case page (three receivers, due days, sent and acknowledged, follow-ups, the rule set named) and the
  possible-deviation list are real working tools.
- Honest empty states on the operations pages ("The box's operations service has never run on this box").
- The audit browser with one-patient report, CSV and chain verification.
- No server error in the whole walk (some 700 page loads in the crawls plus the action walks).

## 15. What was not checked

TOTP enrolment and sign-in in the browser; OIDC; the Docker image; phone layout; ja and zh-TW beyond two pages; the
referral answer and print; the monitor's visit record submit; a new EDC draft, sign and send in the browser (the review
page of a seeded draft was read); copy-assist; ODM import; REDCap read-back from the page; site set-up wizard and chart
upload; cohort studies beyond opening their pages; the mail route for approval; job cancel and retry; backup, restore,
update on a box; J-01, J-02, J-07; ROLE-020, 023, 024, 026 to 028; UX-004; FIT-001, 004, 005, 012, 016, 023. Six
screenshots that an earlier work-in-progress commit holds (`JRN-03`, `04`, `06`, `10`, `11`, `13`) were removed from
the working tree to keep the evidence folder at twelve files.
