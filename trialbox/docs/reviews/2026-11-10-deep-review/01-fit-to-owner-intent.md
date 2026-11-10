# TB-DR-01 Fit to the owner's intent

| Field | Value |
| --- | --- |
| Date | 2026-11-10 |
| Code read | `origin/master` ca8f287 (the deep-review branch, same commit) |
| Method | Requirements trace. Every owner requirement was listed from: TB-PLAN-05 §1.1 and §5 (92 URS rows), TB-PLAN-04 §3 to §6, TB-IU-01 (C1 to C12), the Study A protocol, the owner decision records of 2026-11-09 and 2026-11-10, the owner-marked rows of `docs/DECISIONS.md` (D-125 to D-147), and `docs/plan/sites/*`. Each was then looked up in the code (`services/console`, `services/edc`, `services/datacore`, `services/orchestrator`, `libs/tb_common`, `catalogue/`) and in the tests. Status words: **done**, **partial**, **missing**, **contradicts**. The column "How" says **R** (I opened the code or grepped it in this review) or **S** (taken from the status document or the critical register, not opened) |
| What was run | `grep` and file reads over the tree; a Python script over `docs/plan/25-traceability.csv` (row counts, ids against the plan and the code); the route list of the console (228 routes) |
| What was not run | No test passed here. `tests/console/test_team_pages.py` was tried with `TB_SCRATCH` in my scratch folder; the local Postgres did not start there (`pg_ctl start failed`, most likely the socket path is too long under the scratch folder). No browser walk, no server, no GPU, no Docker. So every "done" below is "done by reading the code and seeing that a test file exists", not "done by a passing run" |

## 1. Summary

The software is a good pre-screening and site-tracking tool. It is not yet the product the owner described on 2026-11-09. Of the 92 URS rows, I rate 13 done, 43 partial, 33 missing and 3 contradicted by the code. The nine scope items of TB-PLAN-05 §1.1: none is fully done; items 2 (delegation, candidates, referral) and 5 (EDC prefill) are closest.

What a clinician-investigator gets today: protocol to criteria with PI approval, whole-hospital screening scope, candidate list with cited evidence, delegation log, referral with an unknown doctor, IRB warning, opt-out register, lifecycle with visits and SAE register, built-in forms, REDCap sync, EDC prefill with confirmation and signature, three languages.

What is absent: the whole profile set (page, twin, vectors, similar patients, setpoints, gaps, annotations), the steward and clinician roles, a monitor who can do SDV, the data-operations console and statistics page, the reminder card and calendar file, outside-medication confirmations, the full consent record, invoice and site-file outputs, and all software support for Study A.

Counts: **Critical 1, High 15, Medium 10, Low 1** (27 findings; 9 are already in the critical register and are cited, not re-reported). Plus 22 unstated needs (§4).

Top 5:

1. **FIT-005 (Critical)**: the IRB amendments filed on 2026-11-10 promise things the code does not do (names never enter; opt-out clears vectors and profiles in minutes; the audit chain is signed daily and copied to the hospital). Nobody traces the filed text to tests.
2. **FIT-003 (High)**: a PI cannot start a feasibility count, a screening run or a case question. Only coordinator and admin accounts can. A site where the PI works alone cannot screen.
3. **FIT-004 (High, registered CR-068, CR-030)**: scope item 4, the patient profile, does not exist in any form. Seven URS rows and both IRB amendments depend on it.
4. **FIT-001 (High)**: `25-traceability.csv` says "planned" on all 273 rows and names a gate, never a test or a file. It cannot show what is built. Only 5 of its 64 test ids appear anywhere in the code.
5. **FIT-016 (High)**: Study A needs an index-date snapshot, frozen-release record, sampling frames per stratum, a "tuned patients" exclusion list and model-agreement export. None exists, and the weekly-sample record must start at go-live.

## 2. Findings

`| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |`

### 2.1 The trace itself

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| FIT-001 | High | The traceability matrix does not trace to code. All 273 rows have status `planned`, including rows whose feature is merged (delegation log, referral, IRB warning, EDC prefill, TOTP). The `evidence` column holds a gate name ("gate: feature complete" 91 times), never a test path. 59 of the 64 `TST-*` ids are named nowhere in `tests/`, `tools/`, `services/`, `libs/`. `TST-IQ-02` is in the plan and not in the CSV. 29 rows have `-` as the requirement. Owner requirements outside §5 (plan v4 §5, D-125, D-131, D-132, TB-IU-01 C1 to C12, the IRB amendment items, Study A) have no row at all | by a run: `python3` over the CSV: `status Counter({'planned': 273})`; `grep -rhoE 'TST-[A-Z0-9]+-[0-9]+' tests tools services libs` gives only TST-E2E-01, TST-GOLD-01, TST-GOLD-02, TST-SEC-01, TST-SEC-10; `tst in plan not csv ['TST-IQ-02']` | Add columns `code_path`, `test_path`, `verified_on`, `verified_how` (run or read). Allow status `planned / built / verified / deviates`. Generate the file from markers in the tests (`@pytest.mark.urs("URS-PI-13")`) with a tool `tools/trace_check.py` that fails CI when a URS has no test or a test names an unknown URS. Seed it from the table in §3 of this file. Acceptance: the tool passes on master; every "built" row names a test that exists; the IRB commitments (FIT-005) are rows | new | no |
| FIT-021 | Low | The Japan go-live date is written two ways. The header of TB-PLAN-05 says "Japan Fri 2027-05-14"; §1.4 of the same plan and the brief say Thu 2027-05-13 (first clinic day), with the morning mail on Fri 05-14 | by reading: `docs/plan/25-master-plan.md:14` and `:52` | State one date (Thu 2027-05-13) in TB-PLAN-06 and in the status file | new | no |

### 2.2 Roles: who may do what

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| FIT-002 | High | The monitor cannot monitor. URS-CRA-01 to 03 and the owner decision ("SDV access to enrolled subjects only, limited to the cited record items") need a monitor who sees the enrolled subjects of one study, the cited items behind each CRF value, and the record's audit trail. The only monitor-like role, `cro`, is aggregate-only: it is refused on every patient-level page, including the EDC trail | by reading: `services/console/auth.py:32-33` (five roles), `:214` (`aggregate_only` = viewer, cro); `libs/tb_common/authz.py` `edc_allowed`: "role in (viewer, cro) → False"; `services/console/app.py:522-549` | Add a `monitor` grant per study (not a sixth global role): read-only on `/studies/{rs}/subjects` limited to enrolled records, `/edc/trail/{record}` and a source-reference sheet per record; every other route 403; each view audited with the monitoring-visit id; time-boxed to the visit dates. Build inside T-102's one permission function. Tests: monitor sees an enrolled subject's trail, gets 403 on a candidate, a screen failure and another study | new | no |
| FIT-003 | High | The PI cannot start any run. `can_request` is admin and coordinator only; the orchestrator's role table gives the investigator `APPROVE` and `STATUS` and the comment says "never a run". So a PI cannot ask "how many patients fit?" (FEAS), cannot run SCREEN, cannot refresh feasibility, cannot ask a CASE question. The owner said the PI is "the ones with full authorization" and that a sub-PI's ticked tasks include "screen and see candidates". In the delegation log the task `screen` only means "see candidates". At a small site the PI may be the only user | by reading: `services/console/auth.py:177-179`; `libs/tb_common/authz.py` `ROLE_COMMANDS` ("investigator": APPROVE, STATUS); `services/console/home.py:467` (feasibility refresh needs `can_request`) | Owner question Q1. Recommended: the logged PI may start FEAS, SCREEN, CASE and STATUS for own studies; a sub-investigator with a new tick `run` may start SCREEN and CASE; daily limits stay. Tests: PI starts FEAS and SCREEN on own study (200), on another study (403); sub-PI without the tick (403) | new | yes |
| FIT-022 | High | No steward role; the administrator holds every patient-level right. This contradicts URS-ADM-01 ("the admin sees no patient data") and every URS-STW row's actor. The staff directory and the opt-out register are kept by coordinator and admin accounts | by reading: `services/console/auth.py:182-193` (`can_view_phi`, `can_reveal` include admin); `libs/tb_common/authz.py` `ROLE_STUDY_TASKS["admin"] = {"screen"}` | As registered. Add to T-102: the steward pages named in URS-STW-02, 04, 09, 11, 12, 13 need the role first, so T-102 is the first card of wave 2, not a side task | registered CR-023, CR-024 (card T-102) | yes (admin demo account shows patient rows) |
| FIT-020 | Medium | Break-glass is specified three ways. (a) Owner decision 2026-11-09: a reason and "a second person on the steward/admin rota confirms". (b) TB-PLAN-05 WS-06.6: second person, 24-hour grant. (c) Owner decision 2026-11-10: reason from a fixed list, one patient or one job, 60 minutes, steward reviews afterwards; no second person is named. Nothing is built, so the builder must pick | by reading: `docs/reviews/2026-11-09-owner-decisions-data-and-profile.md` rows "Break-glass" and "Data steward and admin access"; `docs/plan/25-master-plan.md:197`; `grep -rIlE 'break.glass' services libs` gives no file | Owner question Q2. Recommended: one rule for both uses: reason from a list plus text, one patient or one job, 60 minutes, steward and PI told at once, steward reviews within 7 days; a second person only for a reveal outside the reader's lists by a non-admin (URS-STW-10) | new (the missing build is registered CR-029, card T-309) | no |
| FIT-027 | Medium | "Sub-investigator" is not an account role. It is an `investigator` account plus a row in the study's delegation log. Until a study's log names a PI, every investigator of the study acts as its PI (D-147). A demo study without a seeded log will show a "sub-investigator" tester the PI's rights, including criteria approval | by reading: `libs/tb_common/authz.py` `study_tasks` ("until the study's log names its PI"); `docs/DECISIONS.md` D-147 item 1 | PoC prerequisite: seed every demo study with a log that names the PI and one sub-investigator with `screen` and `refer` ticked and `approach` not ticked, so the three roles differ on screen. For production: warn on the study page while no PI is named; refuse real-data SCREEN for a study with no named PI | new | yes |

### 2.3 Scope items that are missing or only partly there

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| FIT-004 | High | Scope item 4 (profiles) is absent: no cited profile page, no twin JSON, no pgvector store, no "patients like this one", no setpoints, no gap finder, no signed annotations, no clinician own-patient view. `POST /studies/{rs}/profile` is the *site* capability profile, not a patient profile. Seven URS rows (PI-07, PI-10, PI-11, PI-12, STW-08, CLN-01 to 03) and items 2, 3 and 6 of both IRB amendments rest on it | by reading: `grep -rIlE 'setpoint\|gap_finder\|patients_like\|similar_patients' services libs` gives nothing; `pgvector` only in `tools/bench_embed.py`; `services/console/home.py:475-489` | As registered. For TB-PLAN-06: build in this order so each step is usable: (1) twin JSON and timeline from structured data (no model), (2) cited narrative with the abstain rule, (3) annotations, (4) vectors and similar patients, (5) setpoints and gaps behind flags. State in the PoC script that profiles are not in the demo | registered CR-068, CR-030 | yes (a tester will look for it) |
| FIT-017 | High | Scope items 6 and 7 are absent: no data-operations console (`/data-ops`), no batch states or held-batch accept/reject, no statistics page, no export ledger or study extract. The catalogue exists only as files (`catalogue/items.csv`, 469 items; `specialties.csv`, 7 specialties, the plan names 4 first templates); no page or screening rule reads it | by reading: route list (no `/data-ops`, no `/api/v1/data/*`); `grep -rIlE 'HELD\|held_batch' services libs` gives nothing; `ls catalogue` | As registered. Add: the statistics page is what a PI reads first at a new site ("is my department's data in, and how complete?"). Give it a study-team view early, before the steward console is complete | registered CR-067 | no |
| FIT-018 | High | The page called "Conflicts" is about trial values (TrialBox against REDCap). The owner's conflict rule is about clinical facts (sheet against feed; unresolved = unknown; blocks "ready"; resolved "at date" by the steward, or the PI for own study). That page does not exist. Two different things will share one name | by reading: `services/console/data_pages.py:1-17`, `:325-330` | Build the clinical conflicts page under the steward console; rename the existing page "Trial-record differences" (ja 試験記録の相違, zh-TW 試驗紀錄差異) so the two never mix. Test: a sheet value that differs from the feed sends the patient to "needs information" until resolved | registered CR-061 (the missing build); the naming point is new | yes (name) |
| FIT-012 | High | Outside-medication checks are not recordable. URS-CRC-06 asks that an outside medication review, an NHI MediCloud check (Taiwan) and an お薬手帳 check (Japan) be stored as confirmed facts with who and when. Concomitant-drug exclusions are among the most common criteria; without this the box can never say "ready" honestly on them | by reading: `grep -rIlE 'お薬手帳\|NHI cloud\|medicloud\|雲端藥歷\|outside_med\|person_reported\|external_lookup' services libs` gives nothing | Add fact sources `person_reported` and `external_lookup` (WS-06.9) and a two-tap form on the candidate page: "outside medication reviewed on (date), source (NHI MediCloud / お薬手帳 / patient interview), result (none found / found: list)". The criterion stays "needs information" until it exists. Tests: a drug exclusion with no review is unknown; with "none found" it is met; the audit names the CRC | new | yes |
| FIT-009 | High | The consent record is thin and the version check does not exist. The built-in consent form has six fields (date, version, taken by, copy given, re-consent, its date). URS-CRC-11 asks for explainer, assistant, LAR (代諾者) and relation, witness, signature order, ICF language. URS-CRC-07 asks that a version not on the approved list warns and is logged; the IRB record stores one free-text `icf_version`, not a list, and the consent entry does not read it | by reading: `services/datacore/builtin/forms.csv` (`tb_consent`: `ic_date, ic_version, ic_by, ic_copy, ic_reconsent, ic_reconsent_date`); `services/console/team.py:120-121` | Extend `tb_consent` (explained by, assisted by, LAR yes/no and relation, witness, patient signed before investigator, thinking-time date, ICF language); make the approved ICF versions a list with dates on `/studies/{rs}/irb`; on save, warn when the typed version is not on the list or is superseded, log `console.consent_version_override`. Tests in `test_entry_pages.py` and `test_team_pages.py` | new | yes |
| FIT-007 | High | The "not matched" list is open today, with the old name, and without its two safeguards. URS-PI-05: the list is shown only after the site's real-data dry run is within its thresholds, and ten patients a week are sampled for the PI. There is no dry-run state and no weekly sample; `/studies/{rs}/excluded` is shown to any PHI role | by reading: `services/console/templates/excluded.html:2-21`; `grep -rIlE 'dry_run_passed\|weekly_sample' services libs` gives nothing | Add a per-site, per-study state `not_matched_list: hidden / shown` set by the steward with the dry-run record id; hidden is the default in PRODUCTION. Add the weekly sample (page and N1), and store each sampled pseudonym in a table Study A can read (FIT-016). Tests: hidden by default in PRODUCTION; shown after the state is set; the sample lists ten and records the PI's answer | the sample is registered CR-014; the gate is new | yes |
| FIT-010 | Medium | No printed reminder card, no calendar file, no "window closes in 2 days" (URS-CRC-08; scope item 8). The intended-use text already tells IRBs that staff "may hand a patient a printed visit reminder" | by reading: `grep -rIlE 'VCALENDAR\|text/calendar\|reminder.card' services libs` gives nothing; `services/console/i18n_life.py` has window states, no closing notice | A4 card per visit in ja and zh-TW (name typed at print time, never stored), `.ics` per visit and per clinic day, the closing notice on the visit list and in N2. Tests: the card renders in both languages without a pseudonym; the `.ics` parses | new | yes |
| FIT-008 | Medium | Contact outcomes do not match URS-CRC-05. Present: reached and booked, reached and declined, not reached (with retry date), not approached (physician), lost contact. Absent: family declined, patient wants time with a retry date, deceased. "Lost contact" is stored as `screen_fail`, which miscounts the screening log | by reading: `services/console/sitestore.py:40-46`; `services/console/i18n_step2.py:75-84` | Add `family_declined`, `thinking` (retry date required), `deceased` (closes every open list row for the patient in all studies and tells the steward), and keep `lost_contact` out of `screen_fail` (own status). Tests in `test_step2.py`; screening-log XLSX carries the new reasons in three languages | new | yes |
| FIT-015 | Medium | EDC routes are REDCap and an ODM file only. URS-CRC-10 also names a plain file and a copy-assist screen for an EDC with no import; URS-CRC-12 asks that a sponsor trial follows the sponsor's EDC export and that the screening log exports in the sponsor's layout. Neither exists. The Japan site's EDC is not known yet (survey) | by reading: route list (`/edc/export.odm.xml` is the only export); `grep -rn -i 'copy.assist' services` gives nothing; `services/console/screening_log.py` has no layout option | Build the copy-assist screen first (it works with every EDC and needs no site integration): one confirmed value at a time, large type, copy button, "entered" tick with time, audit. Then a column-map file for the sponsor's screening-log layout. Decide after survey question on the Japan EDC | new | partly |
| FIT-014 | Medium | The "inputs only" outputs are absent: invoice-ready activity report per study and month, dated indexed site-file bundle (URS-PI-18), dispensing dates on a patient timeline (owner decision "Drug accountability, TMF, site invoicing") | by reading: `grep -rIlE 'invoice' services libs` gives nothing; no timeline page in the route list | One report page `/studies/{rs}/activity?month=` (screened, approached, consented, visits done, SAEs, CRC minutes) with XLSX; one "site file" zip (approved criteria versions, delegation log, IRB record, screening log, enrolment report, each with date and hash, plus an index). Dispensing dates wait for the profile timeline | new | no |
| FIT-011 | Medium | No EMR launch link (URS-PI-16). The plan wants the code by G3 and the site's URL pattern later | by reading: `grep -rIlE 'emr_link\|emr_url' services libs` gives nothing | A site setting `emr_url_pattern`; the click resolves the chart number server-side, counts as a reveal (reason "open the chart"), and is audited. Where no pattern exists, a per-clinic-day slip | new | no |
| FIT-013 | Medium | CRC minutes per candidate are not measured (URS-CRC-13). It is the only planned measure of "does this save work" | by reading: `grep -rIlE 'crc_minutes\|minutes_spent' services libs` gives nothing (only `tools/acceptance.py`) | A start/stop tap on the candidate sheet, stored per candidate and CRC, exported in the activity report. Optional per site | new | no |
| FIT-019 | Medium | D-125's rule "every screen action goes through a documented, token-protected API" is not met for many actions. Page-only actions include: delegation-log edit and monthly check, staff directory, the not-matched review, the SAE register, sheets upload, schedule undo, flags, users. So the later phone app cannot do them | by reading: route list: `post("/studies/{rs}/team")`, `/team/check`, `/site/staff`, `/studies/{rs}/excluded/{pid}/review`, `/studies/{rs}/sae/...`, `/site/sheets` have no `/api/v1` twin | A test that pairs every state-changing page route with an `/api/v1` route or an explicit exemption list; then close the list | new (SAE part registered CR-012) | no |
| FIT-026 | Medium | URS-PI-06: "a prompt or terminology change asks for re-approval". No code marks an approved criteria set stale when a prompt or a vocabulary release changes | by reading: `grep -rn -i 're-approv\|reapprov\|stale_approval' services libs` finds only the criteria-diff view (`services/console/approval.py:11`) | In T-101 (prompt registry, PR #75) and T-105 (vocabulary): pin prompt and vocabulary versions in the approved ruleset; on a change, the study shows "approval needed" and SCREEN keeps the old pin until the PI re-approves | card T-101 covers (add the vocabulary pin and the PI-facing state) | no |

### 2.4 Promises made outside the code

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| FIT-005 | Critical | The IRB amendments (filed by the owner on 2026-11-10) describe the product as it is planned, not as it is. Once approved, the text is the rule the sites are held to. Mismatches found: (1) "names, national IDs and phones never enter": note text keeps them (CR-028). (2) Profiles, the second-model check, the 95 % abstain rule, vectors, similar patients: not built (FIT-004). (3) The clinician role: not built (CR-030). (4) Steward note access audited and kept 10 years: no steward role (CR-024). (5) Opt-out removes from screening, profiles, vectors and exports "within minutes": lists and scope only (CR-027, CR-026, CR-019). (6) "The audit chain is signed daily and a copy kept on the hospital share": unkeyed chain on the box (CR-042, CR-054). (7) k = 5 on anything leaving the team: built for report packs, not as a general gate. Met: pseudonym at the door, referral flow, candidate view with purpose and rate limit, second factor | by reading: `docs/plan/sites/irb-amendment-cgmh.md` §A.3 items 1 to 11, `irb-amendment-japan.md` §A.3; the register rows named | Make the eleven items of each amendment rows of the traceability file (requirement ids `IRB-CGMH-01..11`, `IRB-JP-01..11`), each with a test, and make "every IRB row verified" an entry condition of IQ. If an item will not be ready at go-live, the PI tells the committee before real data, in writing | new (the single gaps are registered; the trace and the gate are not) | no |
| FIT-006 | High | The product's words contradict the intended-use statement. The list is titled "Excluded patients and why" (ja 除外された患者と理由, zh-TW 被排除的病人與原因); the run headline says "{n} excluded"; the route and API say `excluded`. The statement of TB-IU-01 §1 is not in the console footer (condition C1). No forbidden-word check exists | by reading: `services/console/i18n_review.py:7,46,84`; `services/console/i18n.py:129,153,247,508,532,877,901`; 126 lines with 除外 or 排除 in `services/console/i18n*.py` | As registered. For the PoC do the visible half first: the three titles, the headline, the tier label and the footer line (one small PR) | registered CR-078 | yes |
| FIT-016 | High | Study A cannot be run from the product. The protocol needs: (a) a snapshot dated at each study's index date and kept for the study's life; (b) a record of release, mapping, model pair and criteria hashes frozen before sampling; (c) the four sampling frames per study (ready, needs information, not matched on a note, not matched on a structured criterion only) handed to the statistician; (d) a list of "tuned" patients (mapping sample, OQ sample, dry run, weekly samples) to remove; (e) a run on each enrolled patient's snapshot at that patient's screening date; (f) per call, whether the two models agreed and the criterion type. None of these exists as a command, table or export | by reading: `docs/plan/study-a-protocol.md` §3, §4.2, §7.4, §10; `services/lake/store.py` (snapshots by ingest, no as-of date); no `study_a` or sampling tool under `tools/` or `services/` | One card: `trialbox study freeze` (writes the frozen record), `trialbox study frames` (four CSVs per study with pseudonym, tier, stratum, criterion type, model agreement; no quotes), a `tuned_patients` table written by the mapping sample, OQ, dry run and weekly sample, and an as-of filter (`recorded on or before date`) for SCREEN on a past date. The `tuned_patients` table and the weekly sample record must exist at go-live, because those patients are created from day one | new | no |
| FIT-023 | High | Opt-out is honoured on lists and screening scope only. URS-PRV-01 and both IRB amendments promise screening, profiles, vectors, future exports, "within minutes", and a list of past exports | S | As registered | registered CR-019, CR-026, CR-027 | no |
| FIT-024 | High | URS-PI-03 and PI-04: the candidate list is not prioritised and an unknown does not name the missing item or who can answer it | S; `services/console/home.py:540` sorts the worklist by list state only (R) | As registered. Add for the PoC: order "ready" by next clinic visit date, then by count of unknowns | registered CR-013, CR-086 | yes |
| FIT-025 | High | URS-CRC-04: the SAE banner does not name the site rule and who confirmed it; no copy goes to the trial office mailbox; an unknown zone gets the Taiwan clock | S; `services/console/saerecord.py:44-49` holds default follow-up rules in code (R) | As registered. Add: the study's regulatory type (see FIT-U06) chooses the clock | registered CR-009, CR-011, CR-012 | yes |

## 3. The requirements trace

Status: **done / partial / missing / contradicts**. How: **R** = read or grepped in this review; **S** = from the status file or the register. "Test" names a test file that exists; none was run here.

### 3.1 Scope of TB-PLAN-05 §1.1

| # | Scope item | Feature in code | Status | How | Finding |
| --- | --- | --- | --- | --- | --- |
| 1 | Whole-hospital screening, real pair on the gateway | scope setting `PUT /studies/{rs}/screen-scope` (`orchestrator/study_api.py:399-408`, mode `hospital`); cascade engine; gateway. G1 not passed | partial | R, S | CR-069 |
| 2 | Sub-PI delegation, candidate view, referral with unknown doctor | `console/team.py`, `teamstore.py`, pages `team_log`, `team_candidates`, `team_referrals`; `tests/console/test_team_pages.py` (15 tests) | partial (delegation skipped on sibling pages, CR-018) | R | FIT-003, FIT-027 |
| 3 | OMOP CDM core, lake from it, provenance, conflicts, vocabulary | `services/omop/` first slice; default source `legacy` | partial | S | CR-060, CR-061, FIT-018 |
| 4 | Profiles, twin, annotations, pgvector, similar patients, setpoints, gaps | none | missing | R | FIT-004 |
| 5 | REDCap EDC prefill, CRC confirms, GAMP 5 | `services/edc/`, `console/edc_pages.py`, `tests/console/test_edc_pages.py`; controls open | partial | R, S | CR-062, CR-034 to 036, FIT-015 |
| 6 | Steward role, data-operations console, statistics page | none (`/reports/research-office` is a research-office summary) | missing | R | FIT-017, FIT-022 |
| 7 | Catalogue loaded as data, four first templates | `catalogue/*.csv` files; derived definitions stored (#59); not read by screening or pages | partial | R, S | FIT-017, CR-066 |
| 8 | Opt-out, IRB/ICF warnings, delegation-log copy with monthly comparison, SAE acknowledgement and clocks, reminder card and calendar, inputs for drug accountability, TMF, invoicing | opt-out register, IRB page, `/team/check`, SAE register built; card, calendar, invoice, site file, dispensing missing | partial | R | FIT-009, FIT-010, FIT-014, FIT-023, FIT-025 |
| 9 | Platform fixes, MFA and AD/LDAP, Windows hardening, signed audit heads, off-box backups, release identity, SBOM | TOTP and OIDC via Authelia (#67), backups (#63), supply chain report mode (#61); Windows checks and signed heads missing | partial | S | CR-041, CR-042, CR-058 |

### 3.2 Steward (URS-STW)

| ID | Short requirement | Feature in code | Status | How | Finding |
| --- | --- | --- | --- | --- | --- |
| STW-01 | Whole repository on OMOP, lake from it | `services/omop/`, `lake/source.py` flag; default legacy | partial | S | CR-060 |
| STW-02 | State of every source and record; what left the box | per-study Sources page only (`data_pages.py:248`) | missing | R | FIT-017 |
| STW-03 | Local codes mapped once; PI confirms important maps; rulesets pin the release | `/site/codes` mapping page; no versioned vocabulary, no PI confirmation, no pin | partial | R | T-105 (PR #82) |
| STW-04 | Steward resolves clinical conflicts; unresolved = unknown, blocks "ready" | trial-value conflicts only | missing | R | FIT-018 |
| STW-05 | Sheets and dumps read; safe fixes listed; the rest asked | `/site/sheets`, `/site/checks`, `/site/charts`; `tests/console/test_site_setup_pages.py` | done (limits of WS-08.4 open) | R | - |
| STW-06 | Bad night never moves `CURRENT`; deletes propagate; snapshots pinned | partly fixed (CR-108); held night promoted by next delta | partial | S | CR-052, CR-053, CR-063 |
| STW-07 | Clinical items are catalogue concepts mapped to standards | files only | partial | R | FIT-017 |
| STW-08 | Steward sees every profile and note; audited 10 years | none | missing | R | FIT-004, FIT-022 |
| STW-09 | Staff and physician directory with department fallbacks | `/site/staff`, department contacts (`teamstore`) | done (kept by coordinator and admin) | R | FIT-022 |
| STW-10 | Reveal outside lists: reason and second person, expires, weekly review | none | missing | R | FIT-020, CR-029 |
| STW-11 | Accept or reject a held batch | none | missing | R | FIT-017 |
| STW-12 | Quality and coverage per source, department, year; k = 5 outside | readiness page shows coverage shares; no statistics page | missing | R | FIT-017 |
| STW-13 | Export ledger; study extract with de-identification profile | none | missing | R | FIT-017, CR-031 |
| STW-14 | Shared code maps through a registry | none | missing | S | CR-031 |
| STW-15 | Site survey before mapping | `docs/plan/sites/site-survey.md` drafted; not answered | partial (owner and sites) | R | CR-088 |
| STW-16 | Export in signed tiers; readiness page names the tier | none | missing | R | new in T-plan (see card FIT-C7) |

### 3.3 Principal investigator (URS-PI)

| ID | Short requirement | Feature in code | Status | How | Finding |
| --- | --- | --- | --- | --- | --- |
| PI-01 | PI sees everything for own studies, views audited; no chart number by mail | `auth.py:189-196` `can_reveal`, `sees_ids`; reveal with reason; `tests/console/test_role_pages.py` | done (chart numbers in the audit log, CR-016) | R | CR-016 |
| PI-02 | Study screens the whole hospital; PI sees every candidate | scope `hospital`; `/studies/{rs}/candidates` | done in code; real pair unproven | R | CR-069; FIT-003 (PI cannot start it) |
| PI-03 | List prioritised; known, unknown and why | ready / needs-information lists; no priority | partial | R | FIT-024 |
| PI-04 | Unknown names the item and who can answer; never excludes on unknown | unknown goes to needs-information; no item or person named | partial | S | CR-013 |
| PI-05 | Not-matched list with criterion, evidence, source; ten a week; shown after dry run | `/studies/{rs}/excluded` with review button; `tests/console/test_excluded_page.py` | partial | R | FIT-007, FIT-006 |
| PI-06 | Only PI approves; prompt or terminology change asks re-approval | `can_approve` investigator only; logged PI only (D-147); no re-approval trigger | partial | R | FIT-026 |
| PI-07 | Cited profile page, timeline, phenotypes, eligibility, twin | none | missing | R | FIT-004 |
| PI-08 | Specialty items first-class with codes and templates | catalogue files | partial | R | FIT-017 |
| PI-09 | Derived scores name equation, inputs, version; mismatch is a conflict | `libs/tb_common/derived.py`, stored rows (#59); screening does not read them; no conflicts page | partial | S | CR-066, CR-115 |
| PI-10 | Patients like this one | none | missing | R | FIT-004 |
| PI-11 | Signed annotation counts as confirmed data | none | missing | R | FIT-004 |
| PI-12 | Setpoints and gap rules as research tools | none | missing | R | FIT-004 |
| PI-13 | Delegation log with training dates; rights follow it; monthly comparison | `/studies/{rs}/team`, `/team/check` | done (UTC date bug CR-049; siblings CR-018) | R | CR-018, CR-049 |
| PI-14 | Referral requested, answered, recorded, doctor may be unknown; contact after agreement | `/candidates/{pid}/referral`, `/referrals/{id}/answer`; Approach refused while open or declined | done | R | - |
| PI-15 | Missing IRB or ICF warns, logs override, never blocks; SAE clocks by site rules | `/studies/{rs}/irb`, `approach_overrides`; SAE clock defaults | partial | R | FIT-009, FIT-025 |
| PI-16 | One click to the EMR chart | none | missing | R | FIT-011 |
| PI-17 | E-signature with name, time, meaning; approval record viewable | `/edc/sign`, `/edc/trail/{record}`; signature weak | partial | S | CR-034 to CR-036 |
| PI-18 | Invoice-ready activity report; site-file bundle | none | missing | R | FIT-014 |
| PI-19 | Registries and reference data offline | refdata pack, CT.gov offline mode (D-140); full pack not built | partial | S | - |
| PI-20 | Accuracy measured in a pre-registered study | protocol draft only | partial | R | FIT-016, CR-095 |
| PI-21 | Prefill on only after sponsor's written acknowledgement | `edc/service.py:87` `set_switch` with acknowledgement fields; PI only switches on | done (the evidence is typed text, CR-062) | R | CR-062 |

### 3.4 Sub-investigator, CRC, treating physician, monitor

| ID | Short requirement | Feature in code | Status | How | Finding |
| --- | --- | --- | --- | --- | --- |
| SUB-01 | Acts only within ticked tasks; actor recorded | `authz.study_tasks`, `team.standing` | done (siblings CR-018) | R | CR-018 |
| SUB-02 | May screen, see candidates, Approach, refer, enter data; never approve | ticks `screen, approach, refer, enter_data`; "screen" = see, not run | partial | R | FIT-003 |
| SUB-03 | Views logged with study and purpose, rate-limited | purpose page, `console.candidate_view`, 60 per hour | done | R | - |
| CRC-01 | Day starts with the next step | `home_crc.html`, `home.py:350` tasks by due date | done | R | - |
| CRC-02 | Core tasks two taps on a 390 px phone in ja or zh-TW | walk reported in D-147; not re-run | partial (not verified) | S | - |
| CRC-03 | Proposed fact confirmed in one tap beside its quote | `/site/facts`, `POST /site/facts/{fid}` | done | R | - |
| CRC-04 | SAE visible until PI acknowledges; clock per party; site rule named; office mailbox | banner, ack, register (`saerecord.py`); rule naming and office mail missing | partial | R | FIT-025 |
| CRC-05 | Contact outcomes list | five outcomes | partial | R | FIT-008 |
| CRC-06 | Outside medication, NHI cloud, お薬手帳 as confirmed facts | none | missing | R | FIT-012 |
| CRC-07 | Consent version not on the approved list warns | none at consent entry | missing | R | FIT-009 |
| CRC-08 | Reminder card, calendar file, window closing | none | missing | R | FIT-010 |
| CRC-09 | eCRF values drafted with quotes, confirmed one by one | `/edc/review/{record}`, `/edc/decide/{draft_id}` | done | R | CR-109 fixed |
| CRC-10 | REDCap API, ODM, else file or copy-assist; never RPA | REDCap send with read-back; ODM export | partial | R | FIT-015 |
| CRC-11 | Full consent record | six fields | partial | R | FIT-009 |
| CRC-12 | Sponsor EDC export followed; screening log in sponsor layout | REDCap read-back only | missing | R | FIT-015 |
| CRC-13 | CRC minutes with one tap | none | missing | R | FIT-013 |
| CRC-14 | One-page guide per role; in-product help | `/help`, `/site/help`, `/ask`; printed guides not checked | partial | R | - |
| CLN-01 | Own-patient view | none; no role | missing | R | CR-030 |
| CLN-02 | Signed annotation | none | missing | R | FIT-004 |
| CLN-03 | Setpoints and gaps only in a referral, switch off | none (nothing to switch) | missing | R | FIT-004 |
| CRA-01 | Monitor sees only enrolled subjects of one study | `cro` sees no subject at all | contradicts | R | FIT-002 |
| CRA-02 | Cited items behind each CRF value | exists for the study team, not for a monitor | missing | R | FIT-002 |
| CRA-03 | Record audit trail; verified record lockable | trail page; no lock | partial | S | CR-035 |

### 3.5 Administrator and IT (URS-ADM)

| ID | Short requirement | Feature in code | Status | How | Finding |
| --- | --- | --- | --- | --- | --- |
| ADM-01 | Directory sign-in and second factor; admin sees no patient data | TOTP, OIDC via Authelia (`console/totp.py`, `oidc.py`, `tests/console/test_identity.py`); admin has PHI rights | contradicts (second half) | R | FIT-022 |
| ADM-02 | Job rights by role; limits per type | `authz.ROLE_COMMANDS`, `daily_limit` | done | R | FIT-003 |
| ADM-03 | Survives reboot, DB restart, mail outage | restart policies in compose; connection and outbox gaps | partial | S | CR-085, CR-110 |
| ADM-04 | Console screens for backups, updates, logs, secrets, network, first run | `/ops/flags`, `/ops/identity`, `/ops/users`, `/admin`; rest in PR #66 | partial | R | in PR #66 |
| ADM-05 | Nightly off-box encrypted backups, age shown, restore drill | layout and schedule merged (#63); not wired at install | partial | S | CR-058 |
| ADM-06 | Every merge passes lint, types, tests, goldens, image build, audit | PR #81 | partial | S | in PR #81 |
| ADM-07 | One command qualifies a model or prompt change | none | missing | R | T-012, CR-079 |
| ADM-08 | Health tiles, alerts, daily health mail | admin tiles; no mail (`grep 'health.mail'` empty) | partial | R | - |
| ADM-09 | Storage measured and projected; retention per kind | retention scenario exists; no projection | partial | R | - |
| ADM-10 | QMS-lite; 62304-light records | documents only | partial | S | CR-096 |
| ADM-11 | Windows: BitLocker, swap, hibernation, wrapped keys | none | missing | S | CR-041 |
| ADM-12 | Audit chain signed daily, off-box; who read which chart and why | unkeyed chain; no access report | missing | S | CR-042, CR-054 |
| ADM-13 | IT security pack handed over | draft `it-security-pack.md`; evidence not attached | partial | R | CR-090 |
| ADM-14 | Offline install in half a day | rehearsal in PR #68 | partial | S | in PR #68 |
| ADM-15 | Crash-safe update, no downgrade, whole rollback | PR #83 | partial | S | in PR #83, CR-047 |
| ADM-16 | Acceptance box before any site | none | missing | S | CR-071 |
| ADM-17 | Box names release, digests, model hashes, vocabulary | supply chain in report mode | partial | S | CR-081 |
| ADM-18 | Licences and notices shipped | NOTICE page from the pack manifest (D-140) | partial | S | CR-096 |
| ADM-19 | Support channel, SLA, PHI-free support bundle | none | missing | R | CR-096 |
| ADM-20 | Shared GPU platform profile and checks | PR #85 | partial | S | CR-084 |
| ADM-21 | Real data only on hospital hardware; CI scan | scan in PR #81 | partial | S | CR-032 |
| ADM-22 | KEK never a plain platform secret | none | missing | S | CR-041 |

### 3.6 Privacy office (URS-PRV)

| ID | Short requirement | Feature in code | Status | How | Finding |
| --- | --- | --- | --- | --- | --- |
| PRV-01 | Opt-out removes everywhere within minutes | lists and scope | partial | S | FIT-023 |
| PRV-02 | k = 5 with controlled rounding outside the team; signed count files | `deliverables/disclosure.py` (rounding base 5) for packs; no general gate, no signed files | partial | R | - |
| PRV-03 | De-identified export: pseudonyms, date shift, k = 5 | none (`grep 'date_shift'` empty) | missing | R | CR-031 |
| PRV-04 | No chart number by mail; no PHI prompt leaves; names scrubbed; boundary per service | mail rule done; note PHI pass missing | partial | S | CR-028, CR-037, CR-040 |
| PRV-05 | RoPA, DPIA, legal basis, DPA, IRB pack per site | IRB amendment drafts; rest open | partial (owner) | R | CR-091, CR-092 |
| PRV-06 | Instrument text only where licensed | not verified | partial (not verified) | - | - |
| PRV-07 | Every view, reveal, export audited with role, basis, purpose; 10 years | audit events exist; purpose only on candidate view; 10-year rule not found | partial | R | FIT-005 |
| PRV-08 | Incident plan signed and rehearsed | none | missing | S | CR-096 |
| PRV-09 | Destruction procedure with certificate | none | missing | S | - |
| PRV-10 | Says what it is on every surface; no diagnostic words | old words, no footer statement | contradicts | R | FIT-006 |

### 3.7 Other owner statements

| Source | Requirement | Feature in code | Status | How | Finding |
| --- | --- | --- | --- | --- | --- |
| Plan v4 dec. 1 | CRF answers in own Postgres tables | `services/datacore/store.py` | done | R | - |
| Plan v4 dec. 2 | Hospital systems one-way in | no write path to EMR found | done | R | - |
| Plan v4 dec. 3 | SQL only at runtime; CQL in the gate | S | done | S | CR-115 |
| Plan v4 dec. 4 | No randomisation, drug accountability, eConsent, portal | none built | done | R | - |
| Plan v4 §5 | "Complete platform" run with no Aimedics person present | not proven (G1) | partial | S | CR-069, CR-071 |
| D-125 | Windows/WSL2 box, offline installer | PR #68; hardening missing | partial | S | CR-041 |
| D-125 | Every screen action through a documented token API | many page-only actions | partial | R | FIT-019 |
| D-126 | AD/LDAP or local accounts; three study kinds (IIT, sponsor, registry) | OIDC option; lifecycle generic; no study-kind field found | partial | R | FIT-U06 |
| D-131 | Three questions; proposed facts rule; readiness page | `/site/start`, `/site/facts`, `/site` readiness; `matching/proposed.py` | done | R | - |
| D-132 | Start small; safe fixes listed; wizard; assistant; templates; practice site; remote help | `/site/start`, `/ask`, `/site/templates/{name}.xlsx`, `/site/practice`, `/site/remote` | done | R | CR-022 |
| D-133 | Novice blockers fixed | S | done | S | - |
| D-136 | Morning mail shows the screening number | `tests/console/test_step2.py` | done | S | CR-050 |
| D-140 | CT.gov live or offline per site; NOTICE page | `/admin/notice`; modes | done | R | - |
| D-143 | PI sees chart numbers; viewer and CRO masked | `auth.py:189-196` | done | R | CR-016, CR-017 |
| D-146 | Whole hospital; only PI approves; rights by role | as above | done | R | FIT-003 |
| D-147 | Delegation, candidates, referral, IRB warning, opt-out | as above | done (limits named) | R | CR-018, FIT-023 |
| Decisions "History" | All history from the start | not verified (needs a site feed) | partial | - | CR-061 |
| Decisions "Referral" | CRC records the doctor's answer; doctor needs no account | `/referrals/{id}/answer` | done | R | - |
| Decisions "Patient messaging" | Printed card and calendar file now | none | missing | R | FIT-010 |
| Decisions "PI spreadsheets" | Trusted as coded, source shown; disagreement is a conflict | sheets import; no clinical conflict | partial | R | FIT-018 |
| Decisions "SNOMED" | Ask for a licence; ICD-10-CM plus WHO bridge until then | `docs/plan/snomed-inquiry.md` drafted | partial (owner) | R | - |
| Decisions 2026-11-10 | Separate steward; admin by break-glass only | none | missing | R | FIT-020, FIT-022 |
| TB-IU-01 C1 | Statement in footer, PDFs, XLSX, mail | none in the console | missing | R | FIT-006 |
| TB-IU-01 C3, C4 | Box never decides; unknown never excludes; proposed never counts | marks by investigator only (`auth.py:197-200`); `matching/proposed.py` | done (engine holes CR-001, CR-006, CR-007, CR-098) | R, S | CR-001 and others |
| TB-IU-01 C7 | Nothing writes to the EMR; nothing reaches a patient | no such channel | done | R | - |
| TB-IU-01 C8 | Nothing unconfirmed is sent | `edc/service.py` send path with read-back | done | R | CR-035 |
| TB-IU-01 C11 | No accuracy claim before Study A | policy; the public site was not checked here | not verified | - | - |
| Study A §4.2, §7.4, §10 | Snapshot at index date, frozen record, frames, tuned list, model agreement | none | missing | R | FIT-016 |
| IRB amendments, items 1 to 11 | See FIT-005 | mixed | partial | R | FIT-005 |
| Site survey, IT pack | Daily health mail, syslog forward, `/metrics`, signed head on the hospital share | none found | missing | R | CR-042; card T-108 |

### 3.8 `docs/plan/25-traceability.csv` against the plan and the code

| Check | Result |
| --- | --- |
| Every URS of §5 has a row | yes (92 of 92) |
| Every `plan_item` exists in the plan | yes |
| Every `risk` exists in the plan | yes (29 rows carry `-`) |
| Every test id of the plan is in the CSV | no: `TST-IQ-02` is missing |
| Status reflects the code | no: 273 of 273 `planned` |
| Evidence names a test or file | no: a gate name on every row |
| Test ids exist in the code | 5 of 64 (`TST-E2E-01`, `TST-GOLD-01`, `TST-GOLD-02`, `TST-SEC-01`, `TST-SEC-10`) |
| Owner requirements outside §5 | no rows (plan v4, D-125 to D-147, TB-IU-01 conditions, IRB items, Study A) |
| Rows that are now wrong | every row for PI-13, PI-14, PI-15 (IRB part), PI-21, SUB-01, SUB-03, CRC-03, CRC-09, ADM-02, STW-09 says `planned`; the code is merged |

## 4. Unstated needs

The owner did not state these. A clinician-investigator at the Japan site or at CGMH would expect them. Each has a recommended assumption so the build need not wait.

| ID | Need | Why it is obvious at the site | In code today | Recommended assumption |
| --- | --- | --- | --- | --- |
| FIT-U01 | "Data as of" on every list and page | A PI will not trust a list without knowing how old the feed is | not on the lists (R: no such key in the week or candidates templates) | Show the snapshot date and the last successful ingest on the week list, candidates, patient page and N1; amber after 48 hours |
| FIT-U02 | Next appointment beside each candidate, and a list by clinic day | The moment to approach is the next visit; both hospitals run on outpatient clinics | CRC home has a clinic list for marked patients | Order "ready" candidates by next appointment; where the feed has no appointments (survey), say so on the page |
| FIT-U03 | The same patient in several studies | Competing trials are normal; "in another trial within 30 days" is a common exclusion | not found | Show "also a candidate in / enrolled in study X" to roles that may see both studies, else "in another study"; enrolled elsewhere sends the patient to "needs information" |
| FIT-U04 | Deceased or transferred patients never reach a contact list | Calling a family after a death is the worst error a CRC can make | not found; "last seen" flag planned (WS-06.9) | A death or discharge-dead record removes the patient from Approach lists at once; no visit in N months shows a flag (N = 12) |
| FIT-U05 | Protocol amendment mid-study | Criteria change; marks, referrals and numbers must survive; affected patients must be re-shown | re-approval shows a diff of criteria | Keep marks and numbers; list "patients whose result changed with version N" for the PI |
| FIT-U06 | Study regulatory type drives clocks and words | Japan: 治験 (GCP 省令), 特定臨床研究 (臨床研究法, jRCT, CRB), 指針 research; Taiwan: 人體試驗, 人體研究. SAE parties and days differ by type | one clock table by zone (`saerecord.py:44-49`) | A required study field "type" from a per-country list; the SAE parties, days and report names come from it; the site confirms the table (ties to CR-009) |
| FIT-U07 | Registry ids of both countries | A PI identifies a study by jRCT or UMIN number in Japan and by the IRB number and 計畫編號 at CGMH | CT.gov id | Accept jRCT, UMIN and free-text IRB numbers as study ids; no fetch needed |
| FIT-U08 | CGMH is several campuses | Linkou, Taipei, Kaohsiung and others share systems; an IRB approval and a PI may cover one campus | scope is hospital or doctors | Add a campus (institution) filter to the screening scope when the feed carries one; survey question |
| FIT-U09 | Chart numbers keep leading zeros and site format | Excel drops zeros; a wrong pseudonym silently splits a patient | not verified | Validate chart-number format per site at import (length, pattern); refuse a column that Excel turned into numbers; ask |
| FIT-U10 | Scanned and outside documents are not read | In Japan 紹介状 and outside results arrive as scans; the PI must know the box did not see them | charts can be uploaded one by one with OCR | State on the patient page which document types the feed lacks; count them in "needs information" reasons |
| FIT-U11 | Staff rotation | Japan rotates staff on 1 April, six weeks before go-live; Taiwan residents in August | accounts have an end date | A yearly "review all accounts and delegation rows" task for the PI and admin in March and July; accounts unused 60 days are suspended |
| FIT-U12 | Shared clinic PCs | Outpatient rooms share PCs; sessions are left open | not verified | Idle lock at 10 minutes with fast re-entry by TOTP; no patient data in the page title or browser history |
| FIT-U13 | Old hospital browsers and no internet fonts | Hospital PCs run managed, old Edge builds, offline | not verified | State a minimum browser in the IT pack; bundle CJK fonts; test the walk on the oldest allowed build |
| FIT-U14 | Printable paper | Both sites decide in paper-based meetings | job files as XLSX; no print views | Print styles for the candidate list (pseudonym and screening number only), the screening log with a signature line, and the delegation log |
| FIT-U15 | Screening log in the site's SOP shape | Each trial office has its own form | fixed columns | A column-map file per site (shared with FIT-015) |
| FIT-U16 | "This data is wrong" button | A PI will see a mapping error within a day | not found | One tap on any cited fact sends the fact id and a note to the steward's list; never changes data |
| FIT-U17 | Planned downtime and night window | The nightly run must not meet the 07:00 clinic | timers exist | A banner for planned work; N1 says when last night's run did not finish and that yesterday's list stands |
| FIT-U18 | Training before first real use | GCP sites record system training | delegation log has a GCP date | A per-user "trained on TrialBox (date, version)" field; a real-data site warns when it is empty |
| FIT-U19 | Study close-out | Studies end; identified lists must be destroyed (URS-PRV-09) and records archived | not found | A "close study" step: final exports, site-file bundle, lock, destruction certificate for the identified list, retention date shown |
| FIT-U20 | Enrolment target and pace | Every PI is asked monthly by the sponsor | enrolment report exists | Add the target and a projected date to the report |
| FIT-U21 | Minors and patients who need a legal representative | Age of majority is 18 in both countries; some protocols enrol minors or dementia patients | consent has no LAR (FIT-009) | Flag age under 18 and studies marked "LAR allowed" on the candidate sheet; ties to FIT-009 |
| FIT-U22 | Opt-out notice text per study (情報公開文書) | Japan's 指針 route needs a posted notice per study; CGMH may ask for one | IRB amendment mentions a notice | Generate a draft notice per study in ja and zh-TW from the study record for the office to post; TrialBox posts nothing |

## 5. What is good (do not change)

* The safety shape matches the intended use: only an investigator marks Approach; proposed facts go to "needs information"; nothing writes to the EMR; no patient channel exists.
* The referral design fits real hospitals: no field is required, the doctor may be unknown, the CRC records the answer, Approach waits for agreement, and the screening log carries the route.
* The IRB check is a warning with a logged override, as the owner chose.
* Rights come from the delegation log through one function (`team.standing`), with the day range and the ticks.
* The purpose prompt before a candidate page, with the audit and the hourly limit.
* The site set-up path for imperfect data (wizard, sheets with listed fixes, "please check" list, practice site, assistant).
* EDC prefill sends only confirmed values and reads each back from REDCap.
* The prefill switch belongs to the study's PI alone, and an admin can only switch it off.
* Three languages on every new page, with field terms chosen per country (収案, 逸脱, 訪視窗口).

## 6. Proposed task cards for TB-PLAN-06

| Id suggestion | Goal | Files it touches | Acceptance tests | Depends on | Size | PoC prerequisite |
| --- | --- | --- | --- | --- | --- | --- |
| FIT-C1 "Trace that traces" | FIT-001, FIT-005: generate the matrix from test markers; add IRB, intended-use, Study A and owner-decision rows; CI check | `docs/plan/25-traceability.csv`, new `tools/trace_check.py`, `tests/**` markers, `Makefile` | the tool fails on a URS with no test and on an unknown id; the built rows of §3 name real tests; 22 IRB rows exist | T-007 (CI gate) | M | no |
| FIT-C2 "PoC words" (part of the CR-078 fix) | FIT-006: the three titles, headline, tier label, footer statement | `services/console/i18n.py`, `i18n_review.py`, `templates/base.html` | walk finds no "excluded", 除外, 排除 in the PI and CRC pages; the footer shows the statement in the user's language | none | S | yes |
| FIT-C3 "PI may run" | FIT-003 after Q1 | `libs/tb_common/authz.py`, `services/console/auth.py`, `home.py`, `team.py`, orchestrator job authorisation | PI starts FEAS and SCREEN on own study; refused elsewhere; sub-PI needs the `run` tick; limits hold | Q1 | S | yes |
| FIT-C4 "Demo delegation seed" | FIT-027: every demo study has a log naming a PI, a sub-investigator and a CRC with different ticks | demo seed tool, `/site/practice` data | the sub-investigator cannot approve criteria or mark Approach in the demo; the PI can | none | S | yes |
| FIT-C5 "CRC completeness" | FIT-008, FIT-009, FIT-010, FIT-012 | `services/console/sitestore.py`, `i18n_step2.py`, `services/datacore/builtin/forms.csv`, `team.py` (ICF list), `lifecycle_pages.py`, new card and `.ics` renderers, `matching/proposed.py` (new sources) | tests named in each finding; three languages; walk at 390 px | T-102 for the permission calls | L | no (FIT-008 and FIT-012 are worth doing before the PoC if time allows) |
| T-102 (add) | FIT-002, FIT-022: the monitor grant and the steward role inside the one permission function | as T-102 | monitor tests of FIT-002; admin sees no patient row | owner decision #74 | add M | no |
| T-309 (add) | FIT-020 after Q2 | as T-309 | one rule, tested for admin and for a non-admin reader | Q2 | none | no |
| FIT-C6 "Not-matched gate and weekly sample" (extends the CR-014 fix) | FIT-007 | `services/console/app.py` (excluded routes), `templates/excluded.html`, notices, a `tuned_patients` table | hidden by default in PRODUCTION; sample of ten recorded; sampled pseudonyms land in `tuned_patients` | T-102 | M | no |
| FIT-C7 "Study A tooling" | FIT-016 | new `tools/trialbox/study.py` (freeze, frames), lake as-of filter, `tuned_patients` | a frozen record with hashes; four frames per study on the synthetic site; an as-of SCREEN equals a SCREEN on a snapshot built to that date; no quote in any frame | FIT-C6, T-006 goldens | L | no |
| FIT-C8 "Outputs for the office" | FIT-013, FIT-014, FIT-015 (copy-assist first), FIT-U14, FIT-U15 | new report and bundle modules under `services/console`, `services/deliverables`, `edc_pages.py` | activity report totals equal the screening log; the bundle index lists every file with a hash; copy-assist audited | FIT-C5 | L | no |
| FIT-C9 "API twin check" | FIT-019 | `tests/console/` new test, `services/console/*` routes | every state-changing page route has an `/api/v1` twin or is on a short exemption list | T-102 | M | no |
| T-101, T-105 (add) | FIT-026: pin prompt and vocabulary versions in the approved ruleset; "approval needed" state | as the cards | a prompt change marks the study; SCREEN keeps the old pin until re-approval | PR #75, PR #82 | add S | no |
| FIT-C10 "Site realities" | FIT-U01, U03, U04, U06, U08, U09 (the safety-relevant unstated needs) | `home.py`, candidates pages, `saerecord.py`, study set-up, adapter import checks | data-as-of on four pages; a death record removes the patient from Approach lists; study type selects the SAE table; a numeric chart-number column is refused | site surveys for U08 | L | U01 yes (small), rest no |
| FIT-C11 "Tiered export on the readiness page" | URS-STW-16 | `/site` readiness, ingest manifest | the page names the loaded tier and blocks go-live state until all three | site surveys | M | no |

## 7. Questions for the owner

| No. | Question | Recommended answer |
| --- | --- | --- |
| Q1 | May the PI (and a sub-investigator the PI ticks) start feasibility, screening and case runs, or does this stay with the CRC and admin? (FIT-003) | Yes for the logged PI on own studies; a separate `run` tick for sub-investigators; daily limits unchanged |
| Q2 | Break-glass: is a second person needed before access, or a steward review after? Which time limit, 60 minutes or 24 hours? (FIT-020) | No second person for admin break-glass; 60 minutes; steward and PI told at once; steward review within 7 days. Second person only for a non-admin reveal outside own lists |
| Q3 | The IRB texts filed on 2026-11-10 describe profiles, vectors, the clinician role and opt-out "within minutes". If one is not ready at go-live, do you tell the committee, or does that item hold go-live? (FIT-005) | Hold real data for that function only (flag off), tell the committee in writing; never run a function the approved text does not match |
| Q4 | Does the monitor get an account for SDV at the two pilot sites, or does the CRC print a source-reference sheet for the pilot? (FIT-002) | Printed sheet for the pilot; the monitor grant is built but switched off until a sponsor asks |
| Q5 | Which EDC does the Japan site use for its first studies? (FIT-015) | If it is not REDCap, build the copy-assist screen before go-live and leave ODM import to the sponsor |

## 8. Assumptions

* "The owner stated" means the documents listed in the method row; I did not look for owner statements in chat logs or PR threads.
* A feature counts as "done" when the code path exists, a test file for it exists, and no register row says it is broken at its core. No test was run to green here.
* Rows marked **S** rely on the status file and the critical register (PR #73) as copied to the scratch folder; I did not re-check them.
* Open PRs (#64 to #86) were not read. Where a row says "in PR", the status comes from the status file.
* The PoC is a hosted console with synthetic data for the roles PI, sub-investigator and CRC; "PoC path yes" means such a tester would see the gap in a normal screening flow.
* The Japan site may have no CRC account at first; this is an assumption behind the weight of FIT-003, to be confirmed by the site survey.
* Country rules named in §4 (study types, clocks, notices) are named as needs, not as legal statements; the sites confirm them.
