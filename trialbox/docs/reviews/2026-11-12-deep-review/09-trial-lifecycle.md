# TB-DR2-09 Trial lifecycle, deep

| Field | Value |
| --- | --- |
| Document id | TB-DR2-09 |
| Date | 2026-11-12 |
| Tree | `514ae9b` (branch `claude/deep-review-2026-11-12`) |
| View | clinical-trial operations: ICH E6(R3), J-GCP / 臨床研究法, Taiwan GCP, as a site would be inspected |
| Run (reproduced here) | (1) `tests/unit/test_lifecycle.py`, `test_lifecycle_mediums.py`, `test_consent_record.py` (31 passed); `test_amendments_d364.py`, `test_retention.py`, `test_decommission.py`, `test_optout_worker.py` (56 passed); `tests/console/test_study_state_d386.py`, `test_sdv.py`, `test_sae_d277.py`, `test_prescreen_log.py`, `test_amendment_rescreen.py` (56 passed). (2) My own probe of the state machine, the SAE clock, visits, deviations, consent and contact rules against a real PostgreSQL (`scratchpad/LIFE/exp/test_life_exp.py`, 6 probes, output quoted below). (3) The eligibility text of two real public trials, taken from ClinicalTrials.gov (NCT03887455 Clarity AD, early Alzheimer's disease; NCT02629159 SELECT-COMPARE, rheumatoid arthritis; only the `eligibility_criteria` field was read), through `doc_parser.parse` and `Compiler.compile` with the stub model (`scratchpad/LIFE/exp/test_real_protocols.py`). (4) `tb_common.ruleset.seed_working_copy` with `TB_ENV=PRODUCTION` into an empty folder. (5) `tools.e2e_simple` to the end: **PASSED in 660.3 s**, every stage 0 to 17, the re-run and the audit stage (see the note in §13 for the three things it needed). (6) `tools/audit_verify.py` on that run's audit chain (1,043 events, PASS), then tampering attempts on copies. |
| Read only | `services/datacore/lifecycle.py` (whole), `orchestrator/lifecycle_api.py`, `scheduler.py`, `scenarios/microbatch.py`, `scenarios/retention.py`, `criteria_compiler/service.py` (compile, approve), `doc_parser/parser.py`, `console/screening_log.py`, `sitestore.py`, `study_setup.py`, `notify.py`, `sae_pages.py`, `saerecord.py`, `sdv_page.py`, `home.py` (parts), `datacore/store.py`, `datacore/sponsor.py`, `tb_common/retention.py`, `tb_common/audit.py` (verify), `deploy/install.sh`, `deploy/docker/python.Dockerfile`, runbook 20 and 25, user guide 02 and 03, the site close-out record, decisions D-364, D-386, D-387, D-397, D-399, D-407, D-413, D-426, D-465, D-467, D-469 |
| Not touched | the UI in a browser (another reviewer), the EDC prefill pages, a real model, any cloud |

## 1. Reading in ten lines

1. Since the last review the front and middle of the lifecycle were built out for real: study state, identifiers, amendment record, re-screen list, pre-screen log, screen-failure criterion, consent versions and re-consent list, contact-attempt rule, randomisation fields, SAE clock in hours with rule sets per study, possible deviations, monitor pages, a close-out procedure. 25 of the 29 old findings are fixed or mostly fixed; the tests for them pass here.
2. Both sites' trial types now have a ruleset (AD-MAB in Japanese, RA-JAK in Chinese). They are tidy synthetic protocols of 10 and 16 criteria. A real protocol is not tidy: the Clarity AD text gives 48 lines, with two alternative diagnosis groups and three study phases, and the compiler flattens all of it into one AND list with no warning (LIFE-002).
3. **A new box starts with eight studies already "approved"** by the project owner "via project chat" or by a synthetic coordinator account, and the timers run two of them weekly and three quarterly on the hospital's data (LIFE-001). Reproduced with `TB_ENV=PRODUCTION`.
4. Screening over time has two holes. The weekly re-check only looks at criteria the model flagged `time_sensitive`; RA-JAK has none, so its weekly re-check re-evaluates nothing (LIFE-003). And a patient a SCREEN excluded is never looked at again until a person runs SCREEN by hand; nothing schedules one (LIFE-004).
5. The screening log silently loses a row when the patient is on the opt-out register, also when that patient consented or enrolled (LIFE-005).
6. "Closed" is one click, final, unguarded, and stops the visit and SAE mails of subjects still on study (LIFE-006).
7. SAE: the register and the clock are careful, but nobody is told when an SAE is entered unless an optional mailbox is set, the investigator's mail goes on working days only, and three of the six rule sets show a wrong or noisy regulator clock (LIFE-007, LIFE-008). My advice: the clock stays off until the trial office confirms the study's rule set (§7).
8. Audit: the hash chain verifies and catches an edit and a plain truncation. A truncation with `HEAD.json` rewritten passes, because the signed off-box heads that would catch it are never scheduled (LIFE-010). Form values and state steps change without a reason, and their old and new values live only in tables the service can update and delete (LIFE-011).
9. Retention is still the opposite of GCP: outputs go after 365 days and the protocol file after 90, whatever the study's state (old LIFE-027, open, LIFE-009).
10. Counts: 22 findings. Critical 1, High 10, Medium 10, Low 1. No Blocker.

## 2. Status of the previous review's findings (`2026-11-10-deep-review/07-trial-lifecycle.md`)

"Run" = I ran the test or a probe here. "Read" = code read, test present, not run by me.

| Old ID | Severity | Status | Evidence |
| --- | --- | --- | --- |
| LIFE-001 | Blocker | **fixed** (as a synthetic scenario) | `rulesets/AD-MAB/` (ja, 10 criteria), `tests/fixtures/protocols/AD-MAB_治験実施計画書_v1.docx/.pdf`, `tools/synth/rates.yaml:190` (`ad` archetype), `tests/integration/test_ad_mab.py` (read). Residual: a real AD protocol's structure, new LIFE-002 |
| LIFE-002 | High | **partly** | `rulesets/RA-JAK/` (trial, zh-TW, 16 criteria), `tests/integration/test_ra_jak.py` (read). Open half: `docs/plan/sites/site-survey.md` still has no study-list table; `grep -i "study list\|Wenn"` = no hit |
| LIFE-003 | Medium | fixed | `docs/plan/design/21-synthetic-hospital-spec.md:108` now names AD-MAB |
| LIFE-004 | Medium | partly | `labels.yaml` for GZQO, RA-JAK, RA-COH, GOUT-COH; AD-MAB and NEUR-COH carry Japanese labels in the IR itself and no other language |
| LIFE-005 | High | **fixed** | Run: without the jars `e2e_simple` exits 2 with a plain line naming `make jvm-deps`; `service.py:284-291` raises `CompileFailed("cql_translate")`; `Makefile:223` `demo-bundle: jvm-deps`; `demo/Dockerfile:40-62` |
| LIFE-006 | Medium | fixed | `tools/e2e_simple.py:935-941` (`subpi`, delegation entry) |
| LIFE-007 | Medium | open (deferred, T-679) | `GZQO_questions.xlsx` still read by no service; D-467 is a different thing (aggregate feed) |
| LIFE-008 | High | **fixed**, with a new defect | `sitestore.py:236-243`, `scheduler.py` `require_open`; run: `test_study_state_d386.py` passes. New: LIFE-006 |
| LIFE-009 | High | **fixed** | `service.py:79-96` (`amendment_record`), D-364 §3 "version in force on the run day"; run: `test_amendments_d364.py` passes |
| LIFE-010 | High | **fixed**, one gap | `studies.py:471-545` (`rescreen_list`), `pi_marks.version`; run: `test_amendment_rescreen.py` passes. Gap: a screen failure "back for a new look" cannot leave `screen_fail` (LIFE-012) |
| LIFE-011 | Medium | **open** | `review.py:170` still "not a regulated e-signature"; `approval.py` has no re-authentication; shipped manifests unchanged (see LIFE-001, LIFE-018) |
| LIFE-012 | Medium | fixed | `lifecycle.py:667-716` (`schedule_version`, `in_force_on`) |
| LIFE-013 | High | **fixed** | D-386 §6, `sitestore.py:343` (`study_identity`: NCT, jRCT, UMIN, Taiwan id shape) |
| LIFE-014 | High | **fixed**, residual | D-397; `test_microbatch_cadence.py` (read); stage 17 of `e2e_simple`. Residual: LIFE-003, LIFE-004 |
| LIFE-015 | High | **fixed** | D-387; run: `test_prescreen_log.py` passes |
| LIFE-016 | Medium | fixed | `lifecycle.py:941-951` (`check_criterion`), `subject_step.criterion` |
| LIFE-017 | Medium | fixed | `lifecycle.py:914-927` (`contact_check`); run: fourth attempt at a limit of three → `why: limit` |
| LIFE-018 | High | **fixed** (as warnings, by decision) | `teamstore.py:165-178` (`icf_versions` history), `lifecycle.py:1126-1173`; run: `icf_check` gives `icf_superseded`, `icf_not_yet`; re-consent list lists the on-study subject on the old version |
| LIFE-019 | High | **fixed** | Run: an enrolment form with no consent form → `held: consent_missing`; an enrolment dated before consent → flag `enrolment_before_consent` (`lifecycle.py:603-607`, `:1094-1108`) |
| LIFE-020 | Medium | fixed | `forms.csv` `en_rand`, `en_rand_date`, `en_rand_no`; no arm stored |
| LIFE-021 | High | not checked by me | EDC is another reviewer's area; D-368, D-461, D-414 and their tests exist |
| LIFE-022 | High | **fixed** | Run: aware 11-01 09:00 → not overdue at +23 h, overdue at +25 h, `due_at 2026-11-02T09:00+09:00` |
| LIFE-023 | High | **fixed**, with new defects | Six rule sets (`lifecycle.py:168-175`), `sae_rule` per study; run: `test_sae_d277.py` passes. New: LIFE-008 |
| LIFE-024 | Medium | fixed, with a new defect | `ae_expected`, `ae_sponsor_related`, `ae_unblinded` on the form. New: LIFE-008 (a) |
| LIFE-025 | Medium | partly | `lifecycle.py:819-902` (`possible_deviations`, `decide_deviation`), class and sponsor date on the form. Missing kinds: LIFE-015 |
| LIFE-026 | High | **fixed** | `sdv_page.py`, `authz.py:341-352`; run: `test_sdv.py` passes |
| LIFE-027 | High | **open** | `scenarios/retention.py:60-78` unchanged: no study hold. Card T-305c exists and waits behind T-305b. New LIFE-009 carries it |
| LIFE-028 | Medium | fixed as a document | `docs/runbook/20-close-out-and-decommissioning.md`, `close-out-record.md`, `purge-certificate.md`, `trialbox decommission-plan`. Per-study close: LIFE-017 |
| LIFE-029 | High | **fixed** | `home.py:381-402` (`others_of`: "elsewhere", study named only to an account that may see it; enrolled elsewhere → an open item) |

## 3. Findings

Format: every row has ID, Severity, Evidence, Impact, Fix, Card, Flag. Detail by ID in §3.1.

| ID | Sev | Finding | Evidence | Impact | Fix | Card | Flag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| LIFE-001 | Critical | A new box is seeded with eight shipped rulesets, all `status: approved`, and the timers run them on the hospital's data | Run: `seed_working_copy(<empty>)` under `TB_ENV=PRODUCTION` copies AD-MAB, GZQO, RA-JAK (trials), GOUT-COH, RA-COH, NEUR-COH (cohorts), RA-BIO, ONC-OSI (NHI), each `approved`, by `zandis (project owner)` "project chat" or `crc1@hospa.test` "e-mail". `deploy/docker/python.Dockerfile:34`; `orchestrator/app.py:109`; `console/backend.py:259`; `scheduler.py:259-264` (NAV weekly for every approved `nhi`), `:221-231` (COHORT for every approved cohort); `sitestore.py:243` (no recorded state = `open`) | Real patients are read (notes included, by the model) for studies nobody at the site approved. The rule "only the delegated PI approves" is bypassed by the installer. An inspector sees three fictitious sponsor trials listed as approved and open | Seed as `draft` outside DEV/TEST/demo, or seed nothing in VALIDATION/PRODUCTION; NHI rules and cohort definitions become approved only by the site's own approval; the timers skip a ruleset whose approver is not an account of this box | NEW-LIFE-1 "No pre-approved study on a site box" S | Go-live both |
| LIFE-002 | High | A real protocol's structure is lost: alternative groups, group headings and other study phases become one flat AND list; one IR per line is forced; no warning | Run: Clarity AD text → 21 inclusion + 27 exclusion lines; "MCI due to AD: a, b, c" and "Mild AD dementia: d, e" are six ANDed criteria; the heading "Diagnosis: Mild Cognitive Impairment…" is criterion 1; "Key Inclusion Criteria that must be met…" is glued to the end of criterion 6; "Extension Phase" and "Part B" criteria ("completed the Core Study", "completed Week 207") are in the same list; compile: 48 criteria, `warnings: []`. `parser.py:271-306`; `service.py:230-231` | For the Japan site's real trial type, an MCI patient must also meet "probable AD dementia". If the model classes that line structured, MCI patients are excluded silently; if human, every patient carries contradictory open items. The PI's review sheet shows 48 rows and nothing says two are alternatives | Parser: keep a section's phase and a bullet's parent line; refuse or warn on a second "Inclusion" section and on a line that ends with ":" followed by bullets. IR: an `any_of` group over criteria. Review sheet: show groups. Until then the paste page says "one phase, one population; rewrite alternatives as one line" | NEW-LIFE-2 "Protocol structure: groups and phases" M | Go-live JP (first), then TW |
| LIFE-003 | High | The weekly re-check only re-evaluates criteria the model flagged `time_sensitive`. RA-JAK has none, so its re-check re-evaluates nothing | Read and run of the shipped data: all 16 RA-JAK IR files have `time_sensitive: false`, including "serious infection ≤ 30 days" (window −30), "DAS28 ≥ 3.2 within 90 days", pregnancy, eGFR; `microbatch.py:211-213` (`ts` empty → `due = []`); prompt rule `ir_extract_v3.md:11` ("events within 90 days") is not met by the shipped ruleset itself | A pool candidate who had sepsis last week, became pregnant, or whose DAS28 fell stays on the PI's clinic list as passing. CGMH's trial type | Derive it, do not ask the model: every structured or mixed criterion is re-checked each run (SQL only, cheap); a note criterion when the patient has a new note since the last answer. Keep `time_sensitive` as a display hint | NEW-LIFE-3 "Re-check by rule, not by flag" S | Go-live TW (both) |
| LIFE-004 | High | A patient excluded by a SCREEN is never screened again until a person runs SCREEN; nothing schedules one | `scheduler.py:186-199,236` (INGEST, MICROBATCH, NAV, COHORT, RETENTION, CALIBRATION only); D-397 §3 ("A patient excluded by SCREEN is not screened again until the next SCREEN"); `microbatch.py` `seen_from` | Exclusions that expire by time (anticoagulant in 90 days, stroke in 12 months, infection in 30 days, age, "RA ≥ 6 months", "MTX ≥ 3 months") or by a new result (eGFR, DAS28, MMSE) never bring the patient back. Over a two-year recruitment the list decays without notice | Each weekly run also re-evaluates the excluded patients whose failing criteria are all time- or value-dependent, inside the night budget; the week page shows "last full screen: N days ago" | NEW-LIFE-4 "Excluded patients come back" M | Go-live both |
| LIFE-005 | High | The screening log and its XLSX drop every opted-out patient, also one who consented or enrolled | `screening_log.py:208-211` (`if pid in gone: continue`), `:187` (pre-screen), `:393`; `sdv_page.py` (sheet 404 for an opted-out patient) | A screening number disappears from the log (GZQO-0003 missing between 0002 and 0004) with no row and no reason. An enrolled subject is missing from the enrolment log and from the monitor's list. D-441 keeps the trial record of a consented or enrolled subject; the log does not | Keep the row of any patient who has a screening number: number, dates, status, and "opted out of further research use on <date>"; hide only patients never numbered. Monitor sheet: same rule | NEW-LIFE-5 "Opt-out keeps the numbered log row" S | Go-live both |
| LIFE-006 | High | "Closed" is final, one form post, with no check of subjects on study or open SAE reports; a closed study mails nothing. There is no "closed to recruitment" state | `sitestore.py:236-241` (`closed: ()`), `study_setup.py:533-558` (reason only), `notify.py:58,354-355` (`CARE_STATES = open, paused`) | At last-patient-in a coordinator picks "closed" (the natural word). Visit and overdue-SAE mails stop for every subject in follow-up, and the state cannot be taken back | Refuse `closed` while a subject is consented, enrolled or on study, or an SAE report is open, naming the count; rename `paused` to "closed to recruitment / paused" in the three languages; allow the PI to take back a close made the same day | NEW-LIFE-6 "Close only an empty study" S | Go-live both |
| LIFE-007 | High | Nobody is told when a serious AE is entered, unless an optional mailbox is set; the investigator's mail goes on working days only | `sae_pages.py:205-207` (`TB_SAE_OFFICE_MAILBOX`, default empty, `config.py:707`; not asked by `install.sh`, the wizard or runbook 01); `notify.py:124` (`today.weekday() < 5`), no holiday calendar | An SAE typed on Friday 18:00 has its 24-hour sponsor report due Saturday 18:00; the PI's first mail is Monday 07:00. Japan goes live on 2027-05-13, after Golden Week; the same rule would have been silent for five days | On save of a serious AE: one mail at once to the study's PI and the office mailbox (pseudonym, due times, no term); make the mailbox a required answer when any study has a clock; the unacknowledged-SAE mail goes every day | T-602 (add) or NEW-LIFE-7 S | Go-live both |
| LIFE-008 | High | Three SAE rule sets show a wrong or noisy regulator clock | Run: `jp_gcp_ii`, fatal, `ae_expected=1` → rows sponsor and IRB only, no regulator row (`lifecycle.py:299`). `tw_trial` has a TFDA clock (7/15) at the site for every study, company-sponsored too (`:173`); Japan has `jp_gcp` vs `jp_gcp_ii`, Taiwan has no such split. `ae_related` is never read by the clock: an unrelated SAE runs the regulator clock (run) | (a) In a 医師主導治験 a known (expected) death or life-threatening reaction still has a 15-day PMDA report; the box shows none. (b) In a sponsor trial at CGMH the TFDA report is the sponsor's; the site's worklist shows it overdue for ever, which trains staff to ignore red. (c) Same noise for unrelated events | Rule sets carry the class table (expected × grave × related), confirmed by each trial office; add `tw_trial_sponsor` (no regulator clock); show no deadline at all until the study's set is confirmed (today the country default runs with a note) | T-602 (add) M | Go-live both |
| LIFE-009 | High | Retention deletes study records while the study runs (old LIFE-027, open) | `scenarios/retention.py:60-78` (outputs 365 days, attachments 90 days, by object age only); `settings.example.yaml:42`; `record-inventory.md:169` ("retention period per study is not a setting yet") | The candidate list a mark was made on, the evidence shown, the review workbook and the protocol file the criteria were compiled from are gone 3 to 12 months later; only hashes remain. First deletions come 90 days after the first protocol upload | Hold: nothing of a study is pruned while its state is not `closed`; after close, the study's period (a per-study setting the trial office gives). Do not wait for T-305b: the hold is a 20-line filter on the job's ruleset | T-305c (re-order: before go-live, drop the T-305b dependency) S | Go-live both |
| LIFE-010 | High | The signed off-box audit heads are never made; a truncated chain with a rewritten `HEAD.json` verifies | Run: copies of an `e2e_simple` chain: edit of line 6 → FAIL "hash mismatch"; last 3 lines removed → FAIL "head anchor says event 251"; last lines removed and `HEAD.json` set to the new last line's hash → **PASS** (on the partial chain of 251 events and again on the full one: 1,043 → 1,038 events, PASS). `grep -rn "sign-head\|sign_head" deploy tools/trialbox` = no caller; `install.sh:506-512` installs `logs daily` only; `audit_verify.py:22` calls `--sign-head` "the nightly timer" | Whoever can write the audit folder can drop the newest events without trace until the next nightly archive, and older ones if the archive share is writable too. D-355's control exists as a tool and is not in force | `install.sh`: `--init-key` at install, a nightly `--sign-head` after `logs daily`, `--heads` in the daily verify; refuse a finished PRODUCTION install with no anchor target | NEW-LIFE-8 "Signed heads on a timer" S | Go-live both |
| LIFE-011 | High | A recorded value or state changes with no reason, and the old and new values are not in the tamper-evident chain | `datacore_api.py:230-231,397-399` (audit `data.entry` = field names only); `store.py:141-146` (`history`: who, when, old, new, source; no reason); `lifecycle_pages.py:170` (undo sends no note). Run: `UPDATE subject SET state='enrolled'` and `DELETE FROM subject_step` by the service connection succeed and leave no trace | Where the built-in forms are the trial record (a registry on the box, the "own EDC"), a consent date or the day the site learned of an SAE can be changed without "why", and the before/after exists only in a table the same service can rewrite. ALCOA and E6(R3) ask for who, when, what and why | Reason required when a saved value is changed and on undo; sha256 of old and new value in the `data.entry` and `life.step` events; `REVOKE UPDATE, DELETE` on `history`, `subject_step`, `ae_ack`, `deviation_call` from the service roles (`30-service-roles.sh`) | NEW-LIFE-9 "Reason for change and append-only trails" M | Go-live both |
| LIFE-012 | Medium | A patient cannot be re-screened: one screening number per study and patient for ever, and `screen_fail` is final | Run: `screen_fail → candidate` refused `final`; `sitestore.py:107-115` (`PRIMARY KEY (ruleset, pid)`), `:606-609` (an existing number is returned). The re-screen list puts screen failures under "back for a new look" (`studies.py:538-539`) | After an amendment relaxes a criterion the PI marks Approach again and the participant page cannot move; the only way is "undo", which records the screen failure as a mistake | A re-screen makes a new record with a new number that points to the old one (`rescreen_of`); the log shows both | NEW-LIFE-10 M | Later |
| LIFE-013 | Medium | State-machine gaps where two stores disagree for ever | Run: `approached → withdrawn` refused `order`; a death on an AE form while `approached` → `held … order`, state stays `approached`; a death after `completed` → `held … final`. The opt-out worker sets the registry to `withdrawn` (D-441) and `FROM_REGISTRY` maps it to lifecycle `withdrawn` (`lifecycle.py:66-67,537-543`), which `approached` cannot reach | The screening log says withdrawn, the participant page says approached with a permanent "held" note; a death in follow-up after completion cannot be recorded as a state | `candidate`/`approached` + registry `withdrawn` → `screen_fail` with reason `other` (or a new `opted_out`); allow `completed → withdrawn` only for reason 5 (death) with a note, or record it as an event without a state | NEW-LIFE-11 S | Later |
| LIFE-014 | Medium | A manual step takes any past day | Run: `consented` on 2020-01-01 after `approached` on 2026-11-08 accepted; `enrolled` on 2019-01-01 accepted; only a future day is refused (`lifecycle.py:448-452`) | The participant trail can show enrolment before consent with no flag when the steps are typed and no form exists (sponsor studies) | Refuse a day earlier than the previous standing step's day, or flag it as the forms do | NEW-LIFE-12 S | Later |
| LIFE-015 | Medium | Missed and overdue visits are never proposed as deviations; a visit after withdrawal is not flagged | Run: v1 missed, v2 37 days overdue → `possible_deviations` gives only `consent_version`; a visit done 19 days after the withdrawal date → no flag (`lifecycle.py:845-854` looks at done visits only) | The two commonest visit deviations are the ones not proposed | Add kinds `visit_missed`, `visit_overdue` (after the window closes) and `visit_after_withdrawal` | NEW-LIFE-13 S | Later |
| LIFE-016 | Medium | "Data collected so far may be used: No" on the withdrawal form is stored and read by nothing | `grep -rn wd_data_use services libs` = the form only | ODM, REDCap CSV, write-back and the monitor sheet keep giving the subject's data with no mark | Exports carry the flag per subject and leave the subject's values out of statistics exports when it is No; the participant page shows it | NEW-LIFE-14 S | Later |
| LIFE-017 | Medium | Closing one study while others go on is not a procedure that can be followed | Runbook 20: "steps 1 to 5 only, for that study", but step 2 stops every service and freezes the whole chain ("a later event on this box is a finding"); step 3's archive is the whole-box backup, handed over with the backup private key; `:28` still says "A switch that stops one study's runs on the box is not built yet" (it is: D-386) | The common case (CGMH's shared box, several studies) has no per-study archive; following the text hands every study's data and the box's backup key to one study's file | `trialbox study archive STUDY`: the study's logs (XLSX and CSV), subject trails, SAE register, consent and criteria versions, the audit events of the study with the chain positions, `SHA256SUMS`; runbook 20 gains a "one study" path without a freeze | NEW-LIFE-15 M | Later |
| LIFE-018 | Medium | Criteria approval has no re-authentication and says it is not an e-signature (old LIFE-011) | `review.py:170`; `approval.py` (CSRF and a confirm page) | The record an inspector reads for "who approved the eligibility rules" is a session click | Step-up at Approve with the EDC signing mechanism (D-281) | T-205 mechanism (add) S | Later |
| LIFE-019 | Medium | The study subject number typed on the enrolment form is not on the screening log; the column is filled from REDCap only; no duplicate check | `screening_log.py:232` (`rc.get(pid).subject_no`); `grep en_subject_no` = the form only | With REDCap off the enrolment log has no subject number; two subjects may carry the same one | Fall back to `en_subject_no`; refuse a second record with the same number in a study | NEW-LIFE-16 S | Later |
| LIFE-020 | Medium | The user guide does not cover half of what was built | `docs/user-guide`: 0 hits for "effective", "paus", "possible deviation", "pre-screen log", "attempt", "randomis", "schedule"; one for "re-screen" (in the consent paragraph) | Coordinators meet the amendment record, the re-screen list, the study state, visit schedules, the contact rule and the possible-deviations list with no page that explains them. See the SOP table, §5 | One page per procedure in the user guide, in three languages | NEW-LIFE-17 "User guide for the lifecycle pages" M | Go-live both |
| LIFE-021 | Medium | The two PoC trial rulesets are far simpler than the real thing, and no test compiles a real protocol | AD-MAB 10 criteria vs 48 lines of Clarity AD; RA-JAK 16 vs SELECT-COMPARE's joint counts, erosions, washout, MTX dose range; the stub turns every line of both real texts into `human` (run) | The claim "the compiler handles the sites' trial types" rests on text written to fit the compiler | Add the two public texts as fixtures with a recorded real-model cassette and an expected class split; see §8 | NEW-LIFE-18 M (after the GCP run) | PoC |
| LIFE-022 | Low | A SCREEN fails whole, with "Internal error", when a PDF font file is missing, after all patients were evaluated | Run: `e2e_simple` → job `failed`, step `reporting`, `ReportError: font NotoSansJP-Regular.ttf not found` (`reports/common.py:62-67`) | On a box the fonts are in the image; a broken image loses a night's list for a cosmetic reason | Fall back to the built-in font for the PDF and say so; never fail the list | NEW-LIFE-19 S | Later |

Known and not repeated here: the newest-500-jobs lookup (`bk.list_jobs(limit=500)`, scale review F-14) is how the week page, the Approach page, the screening log's criterion pick list and the re-screen list find a study's list. It bites the lifecycle hardest for a paused or closed study, whose last list falls out of the window while D-386 promises it stays readable.

### 3.1 Detail

**LIFE-001.** Output of the run:

```
seed: …/trialbox/rulesets copied: True
AD-MAB   trial  approved crc1@hospa.test          e-mail       ['pi@hospa.test', 'crc1@hospa.test']
GOUT-COH cohort approved zandis (project owner)   project chat None
GZQO     trial  approved zandis (project owner)   project chat ['pi@hospa.test', 'crc1@hospa.test']
NEUR-COH cohort approved crc1@hospa.test          e-mail       None
ONC-OSI  nhi    approved zandis (project owner)   project chat ['onc-dr@hospa.test', 'nurse-onc@hospa.test']
RA-BIO   nhi    approved zandis (project owner)   project chat ['nurse-rheu@hospa.test', 'rheu-dr@hospa.test']
RA-COH   cohort approved zandis (project owner)   project chat None
RA-JAK   trial  approved crc1@hospa.test          e-mail       ['pi@hospa.test', 'crc1@hospa.test']
```

`seed_working_copy` has no environment check (`tb_common/ruleset.py:238-249`). Runbook 01 step 2 also says the bundle "loads images, models and approved rulesets". Not checked: whether the mail gateway refuses the `hospa.test` recipients (it should, they are not internal); the jobs still run and store their outputs. If shipping NHI rules and alliance cohort definitions as product content is intended, they still need the site's own approval record before a timer uses them; the three synthetic trials have no place on a site box at all.

**LIFE-002.** The parser (`items`, `ie_block`) treats every bullet as a criterion and every non-bullet line as a continuation of the line before, or, when it is first in a section, as a criterion. Every section whose title matches "inclusion criteria" is appended to one list, so "Core Study", "Extension Phase" and "Extension Phase Part B" merge. The compiler then demands exactly one IR per line (`service.py:230`), so even a model that understands the alternatives cannot return one OR criterion for two lines. The IR has `and`/`or`/`not` inside one criterion (`criterion_ir.py:366`) and nothing across criteria. The registry's `\>=` escapes are passed through unchanged. SELECT-COMPARE parses cleanly (7 + 3 lines), but its content is exactly what the IR cannot say: "≥ 6 swollen joints of 66 and ≥ 6 tender of 68", "≥ 3 erosions OR ≥ 1 erosion and RF positive", a dose range with a stability period, "up to 20 % of the population".

**LIFE-003, LIFE-004.** These are one failure seen from two sides: the product has a full SCREEN (by hand) and a weekly delta, and the delta's two inputs are a model's flag and "not seen since the last SCREEN". AD-MAB flags 4 of 10 criteria, GZQO 5 of 23, RA-JAK 0 of 16. `time_sensitive` is in the IR the PI approves, but the approval page does not ask "which answers can change with time".

**LIFE-008.** I state the regulatory classes as an operations lead would brief them, not as legal advice; each trial office confirms. Japan, 治験 (薬機法施行規則 273): unknown death or life-threatening 7 days; known death or life-threatening 15 days; unknown other serious 15 days. The box: `if days <= 0 or (party == "regulator" and expected): continue`. Taiwan: the expedited report to TFDA for an unexpected serious reaction is the sponsor's; the investigator reports to the sponsor at once and to the IRB by the IRB's rule. The user guide says correctly that "the trial office's SAE log and SOP still govern".

**LIFE-010.** The four attempts, on copies under `scratchpad/LIFE/aud*`:

```
aud   : audit chain PASS: 1 files, 251 events, head da4ea001d7dde491…
aud1  : audit chain FAIL … 2026-11-12.jsonl:6: hash mismatch                      (actor edited)
aud2  : audit chain FAIL … HEAD.json: the chain ends at event 248 …, the head anchor says event 251
aud3  : audit chain PASS: 1 files, 248 events, head 560cb4bc6e9bd944…            (truncated + HEAD.json rewritten)
audf  : audit chain PASS: 1 files, 1043 events, head c15071fda250084d…           (the full e2e run)
audf3 : audit chain PASS: 1 files, 1038 events, head d931306cea2581c9…           (5 events dropped + HEAD.json rewritten)
```

The hash is unkeyed, so a full rewrite with a new head also passes; that is the design, and the signed heads on the hospital share are the answer to it. The nightly `logs daily` does compare the chain with the archive's `HEAD.json` (`tools/trialbox/logs.py:347-355`), which protects events older than the last archive as long as the share is not writable from the box account that tampers.

**LIFE-011.** What the chain holds for a lifecycle change: `life.step` (record, from, to, reason code, source), `data.entry` (record, event, form, field names), `console.sae` (dates old and new: the SAE register is the good example), `console.study_state` (state, previous, reason). So state changes are in the chain; values of forms are not, except SAE dates. The `audit.journal` table is append-only by role (`30-service-roles.sh:163`); the data-core tables are not.

## 4. Stage × (in product | tested | documented | gap)

"Tested" = an automated test exists (R = I ran it green here). "Documented" = a page for the user or the operator, not a decision record.

| Stage | In the product | Tested | Documented | Gap |
| --- | --- | --- | --- | --- |
| Protocol → criteria | parse PDF/DOCX/paste, IR per line, CQL + SQL + equivalence, review workbook, PI approval, version tags, amendment record, version in force by date; compiler writes only the working copy (D-469) | yes (`test_compiler_service`, R `test_amendments_d364`, `test_g1_b3_rulesets_default` read) | user guide §3 "Start a study" (one paragraph); nothing on amendments | LIFE-001, LIFE-002, LIFE-018, LIFE-021 |
| Feasibility | funnel with unknowns, controlled rounding, small-cell and complementary suppression, sponsor copy, opportunity feed with a floor of 10 (D-467) | yes (`test_feas_unit`, `test_opportunity_feed` read) | user guide (short), plan 32 | sponsor questionnaire (old LIFE-007, deferred). Not run by me beyond the e2e stage |
| Screening | SCREEN on demand; nightly INGEST; after-ingest and weekly MICROBATCH; rule engine for structured/mixed, model for notes, unknown as a first-class answer; night budget declared as a setting | yes (`test_microbatch_cadence`, `test_screen_*`, e2e stage 17) | user guide "Work the list" | LIFE-003, LIFE-004 |
| Pre-screen (identified view before referral) | candidates page with purpose, IRB-text record, reveal with reason and cap | yes (`test_irb_text_gate`, `test_reveal_paths` read) | user guide | — |
| Lists | week page, clinic-day list, ready / needs information, marks with version, "elsewhere" flag across studies, not-matched list with weekly sample of ten | yes (R `test_amendment_rescreen`, `test_not_matched_sample` read) | user guide | 500-jobs lookup (scale F-14) |
| Hand-off to the treating physician | referral record (route, answer, reason); Approach waits for the answer; nothing is sent to the physician (owner's decision) | yes (`test_team_pages` read) | user guide | — |
| Contact | staff mails only (N1, N2, pseudonym + screening number, never name or chart number); outcomes in two taps; attempt limit and spacing per study; nothing is ever sent to a patient | yes (R `contact_check`; `test_lifecycle_mediums`) | mails yes; the contact rule no | LIFE-020 |
| Opt-out | register (office, steward, hospital registry sync), worker every 5 min, every list path reads it | yes (R `test_optout_worker`) | user guide; privacy pack; opt-out notice | LIFE-005, LIFE-013; 60 erase entries owed (T-206b, `erasure-registry.md:5`) |
| Consent | record only (date, version, who, copy, LAR, witness, order of signatures), paper is the source; ICF version list with history; warnings; re-consent list and `rcN` events; explainer as a reading aid | yes (R `test_consent_record`; `test_consent_pages` read) | user guide "Consent" | no e-consent (right for go-live) |
| Screening log | ICH-style log by screening number + pre-screen log; XLSX with "about" sheet (identifiers, state history); sponsor column layout | yes (R `test_prescreen_log`) | user guide (exports line) | LIFE-005, LIFE-019 |
| Enrolment | enrolment form, PI eligibility confirmation, subject number as typed from the sponsor, randomisation yes/date/number (no arm) | yes (R `test_lifecycle*`) | user guide (one line) | LIFE-012, LIFE-014, LIFE-019 |
| Visits | schedule per study with versions, windows, due/open/overdue/done/missed/stopped, worklist, mails | yes (R) | **no** | LIFE-015, LIFE-020 |
| SAE | AE form (seriousness, outcome, relatedness, expectedness, unblinding record, report dates), clock per rule set, register with acknowledgement, follow-ups, trail, no patient text. Not a CIOMS/E2B form: no suspect drug, dose, dechallenge, concomitants, reporter | yes (R `test_sae_d277`; `test_sae_pages`, `test_sae_record` read) | user guide "SAE register" (good) | LIFE-007, LIFE-008 |
| Deviations | form (date, kind, class, reported to EC, sponsor date); proposals from the box's own facts, confirm or dismiss with reason; no CAPA link | yes (R `test_lifecycle_mediums`) | **no** | LIFE-015, LIFE-020 |
| Monitoring / SDV | monitor grant by dates and visit id; enrolled subjects only; source-reference sheet; visit record; every read audited | yes (R `test_sdv`) | user guide 02 | LIFE-005 (opted-out subject 404) |
| Close-out | study state `closed`; runbook 20 (8 steps), `decommission-plan` (dry run), close-out record, purge certificate | yes (R `test_decommission`); drill named, not run | runbook 20; site templates | LIFE-006, LIFE-009, LIFE-017 |
| Archive / retention | audit chain kept and archived nightly; retention job by object age | yes (R `test_retention`) | security 06; record inventory | LIFE-009 (no study hold, no period per study) |
| Audit trail | hash chain, one writer, append-only journal by role, browser for privacy office and steward, per-patient report, verify | yes (`test_audit*` read; R tamper probes) | security 06 | LIFE-010, LIFE-011 |

## 5. Procedures the product implies

| Procedure | Document exists | The product supports or enforces it | Gap |
| --- | --- | --- | --- |
| Criteria review and approval | user guide §3 (paragraph) | enforces: only the delegated PI approves; amber rows opened first | LIFE-001 (pre-approved), LIFE-018 |
| Amendment (new criteria version, effective date, re-screen) | **none** for users (D-364 is a decision record) | supports: record, version in force, re-screen list, schedule versions | LIFE-020; no page says who does what on amendment day (criteria, ICF version, schedule, re-consent are four separate pages) |
| Screening-list review by the PI | user guide "Work the list", "weekly sample" | supports; marks audited | — |
| Reveal of a chart number | user guide; privacy pack | enforces: reason, cap per hour, one audit shape (D-438) | — |
| Opt-out | user guide; `opt-out-notice.md`; privacy pack | enforces on lists; worker | LIFE-005; restore undoes opt-outs typed since the backup (architecture note F-8) |
| Contact attempts | **none** | enforces limit and spacing | LIFE-020 |
| Consent recording and re-consent | user guide "Consent" | supports (warnings, list) | — |
| SAE entry and reporting | user guide "SAE register"; says the office SOP governs | supports (clock, register) | LIFE-007, LIFE-008; no "who is told" line |
| Deviation recording | **none** | supports | LIFE-020 |
| Monitoring visit / SDV | user guide 02 | enforces grant window and scope | — |
| Study pause / close | **none** for users | enforces list and mail stop | LIFE-006, LIFE-020 |
| Close-out and purge | runbook 20, TB-SITE-11, TB-SITE-12 | `decommission-plan` only; the rest by hand | LIFE-017 |
| Backup and restore | runbook 05, 22 | yes (other reviewer) | restore vs opt-outs (F-8) |
| Model update re-qualification | `validation/model-change-protocol.md`, runbook 11, 14 | `qualify` (other reviewer) | after a model change no step says "re-screen open studies" or "the PI is told the judge changed" (not checked further) |
| Account joiner / leaver | runbook 03, 25 | supports (disable, end date, unused list) | — |
| Retention per study | **none** | no | LIFE-009 |

## 6. The state machine of a patient in a study, as implemented

Four stores each hold a state. They are joined by the pseudonym and the screening number.

```
(A) candidate list (job output, recomputed per run)        (B) PI mark (site.pi_marks, event log, with criteria version)
    in scope ──► listed: ready | needs information             approach | need_info | not_suitable | not_now
            └─► excluded ("criteria not matched")              "withdrawn" = mark taken back; referral wait holds Approach
                 ▲ sent back by PI / weekly sample

(C) candidate registry = screening-log status (orch)       (D) lifecycle subject (datacore.subject, subject_step)
    candidate ─► contacted ─► consented ─► enrolled            candidate ─► approached ─► consented ─► enrolled ─► on_study ─► completed
        │            │                                              │            │            │  │          │           │
        ├─► declined ┤                                              └─► screen_fail ◄─────────┘  └──────────┴───────────┴─► withdrawn
        ├─► screen_fail                                             (reason: not_eligible + criterion | declined | lost_contact | other)
        └─► withdrawn  (opt-out worker: candidate, contacted)       undo = reverse the last standing step, as a new step

Screening number: given once at Approach (B → C), one per (study, patient), never re-used.
Study: startup ─► open ⇄ paused ─► closed (final);  startup ─► closed.
```

Transitions come from: a person (console, `/api/v1`), the forms (`derive`: never backwards, never past an end state, consent never implied by a TrialBox form), the screening log (REDCap read-back), the sponsor's weekly sheet (proposals a person confirms), the opt-out worker.

Illegal or missing, each checked by a run unless marked (read):

| # | Transition | Today | Should be |
| --- | --- | --- | --- |
| 1 | `screen_fail` → re-screen | refused (`final`); same number returned | new record, new number, linked (LIFE-012) |
| 2 | `approached` → `withdrawn` (opt-out, patient asks to be left alone) | refused (`order`); registry says withdrawn, subject stays `approached`, held for ever | end as `screen_fail` / other, or a state `opted_out` (LIFE-013) |
| 3 | death recorded while `candidate` / `approached` | held (`order`) | end state with reason; contact already stops through the death check (read, `home.py:374-379`) |
| 4 | `completed` → death or withdrawal of data use in follow-up | held (`final`) | an event without a state change, or `completed → withdrawn` for death only |
| 5 | manual step dated before the previous step | accepted | refused or flagged (LIFE-014) |
| 6 | `consented` by a manual step with no consent form | accepted through the API; flagged `no_consent_form` on the page | fine as a flag; the console no longer offers it (D-399) |
| 7 | `enrolled` → `screen_fail` (enrolled in error, not randomised) | refused (`order`); only `withdrawn` | acceptable; say so in the guide |
| 8 | `on_study` → `completed` with visits open | accepted by hand; derivation needs every visit done or missed and the last one done | acceptable; show the open visits on the confirm line |
| 9 | study `closed` with subjects on study | accepted, final | refused with the count (LIFE-006) |
| 10 | study `closed` → anything | none | a same-day take-back by the PI |
| 11 | opted-out patient with a screening number | row removed from both logs | row kept with the reason (LIFE-005) |
| 12 | excluded → listed, when time or a new result changes the answer | only by a manual SCREEN | by the weekly run (LIFE-004) |
| 13 | listed (pool) → excluded, when a new exclusion appears | only for `time_sensitive` criteria and a visit in 14 days | every structured criterion, every run (LIFE-003) |

What is right and should stay: one table of legal steps; undo as a new step; derivation that reports what does not fit (`held`) instead of forcing it; the mark, the registry and the subject are separate facts with their own trails.

## 7. Visits, SAE, deviations, close-out: carry at go-live, or freeze?

| Part | What it is worth at go-live | What it risks | Verdict |
| --- | --- | --- | --- |
| Visits | A reminder list for studies whose record is on the box (registries, IITs). For a sponsor trial the sponsor's EDC and the CRC's own calendar already do this | Low: no schedule saved = no visit rows, no mail. The code is small and tested | **Keep, frozen.** No new work before go-live except LIFE-020's page. Off by default is already the case |
| SAE clock and register | Small. Every site has an SAE SOP, a paper or office log and the sponsor's safety form; the box is a second clock | Real: a second clock that is wrong for three rule-set cases (LIFE-008), silent on weekends and holidays (LIFE-007), on by a country default nobody confirmed. A red line that is wrong teaches people to ignore red; a missing red line is read as "nothing due" | **Keep the AE form and the PI's acknowledgement. Freeze the clock:** no deadline, no overdue alert and no SAE mail for a study until its rule set is saved and confirmed on the set-up page and the office mailbox is set. Then fix LIFE-007 before the first study turns it on. Do not build CIOMS/E2B fields; that is the sponsor's form |
| Deviations | The form is harmless and useful for registries. The proposals work only from TrialBox's own forms, which are mostly empty in a sponsor trial | Low | **Keep the form. Freeze the proposals as they are** (LIFE-015 later). No CAPA link: out of scope for this product |
| Close-out | No study closes in the first months. The whole-box decommissioning text is good enough for a retired box | Medium, and it is not in the close-out code: it is retention (LIFE-009) and the one-click close (LIFE-006), both of which can hurt in year one | **Do not build more close-out before go-live.** Do LIFE-006 and the retention hold (LIFE-009) now; `study archive` (LIFE-017) before the first study closes |

## 8. What to drop or simplify

- The country-default SAE clock (`COUNTRY_DEFAULT`, `RULE_ALIASES`, `TB_SAE_RULES`, `TB_SAE_REPORT_DAYS`, `TB_SAE_FOLLOWUP_DAYS`): four ways to set one thing. Keep the study's confirmed rule set; drop the box-wide settings and the default.
- `time_sensitive` as a model output that drives behaviour. Keep it as a label at most (LIFE-003).
- The synthetic trial rulesets in the production image (LIFE-001). Ship them in the demo image and the test tree only.
- Two "status" vocabularies for one person (registry `contacted`/`declined` and lifecycle `approached`/`screen_fail` with `REGISTRY_OF`/`FROM_REGISTRY`). It works, but every new transition must be written twice and LIFE-013 is what falls between them. Later: make the registry status a view of the lifecycle subject.
- The possible-deviations engine should not grow before a site asks for it.
- `ic_reconsent*` fields on the first consent form (the "old re-consent slot") beside the `rcN` events: two places for one fact; hide the old slot for new records.

## 9. What the plan must change (inputs to plan v7)

| # | Task | Size | Depends on | When |
| --- | --- | --- | --- | --- |
| 1 | NEW-LIFE-1: no pre-approved study on a site box; timers skip a ruleset this box did not approve | S | — | before any site install; first |
| 2 | NEW-LIFE-3 and NEW-LIFE-4: re-check every structured criterion each run; excluded patients come back; "last full screen" on the page | S + M | goldens move (state the reason) | before go-live; before G-gate runs that measure recall over time |
| 3 | NEW-LIFE-5, NEW-LIFE-6: the log keeps numbered rows; close only an empty study | S + S | — | before go-live |
| 4 | T-602 additions: SAE clock off until confirmed; mail at entry; daily mail; rule-set classes; `tw_trial_sponsor` | M | each trial office gives its class table (a site input, not a gate) | before the first study with a clock |
| 5 | T-305c re-cut: the study hold now, without T-305b; the per-study period later | S now, M later | D-386 state (done) | hold before go-live |
| 6 | NEW-LIFE-8: signed heads on a timer; install refuses PRODUCTION with no anchor target | S | the hospital share exists (site input) | before go-live |
| 7 | NEW-LIFE-9: reason for change, value hashes in the chain, append-only trails by role | M | — | before a study keeps its record on the box |
| 8 | NEW-LIFE-2: protocol structure (phases, alternative groups, warnings); NEW-LIFE-18: two real public protocols as fixtures | M + M | the GCP run of §10 first, to see what the real model does | Japan PoC with a real AD protocol |
| 9 | NEW-LIFE-17: user guide for the lifecycle pages, three languages | M | — | before site training |
| 10 | Later, in this order: NEW-LIFE-15 (study archive), NEW-LIFE-10 (re-screen record), NEW-LIFE-11/12/13/14/16/19 (S each), T-205 step-up at Approve | M, M, S×6, S | — | after go-live |

Order matters for two: (1) before anything is installed at a site; (2) before any measurement that claims "screening keeps up with the hospital".

## 10. Needs GCP / owner hardware

1. **Real protocol through the real judge.** On the GCP box with the production judge and verifier: paste `scratchpad/LIFE/pub/clarity_ad.txt` (ClinicalTrials.gov NCT03887455, eligibility field) as ruleset `ADREAL` and `select_compare.txt` (NCT02629159) as `RAREAL` on the console's criteria page (or `Compiler.compile` as in `scratchpad/LIFE/exp/test_real_protocols.py` with the gateway client instead of the stub). Record per text: number of criteria, class split (structured / mixed / note / human), `needs_review` count, `time_sensitive` flags, compile time, and for Clarity AD the class and logic of the lines "Meet the NIA-AA core clinical criteria for probable Alzheimer's disease dementia" and "Participants who have completed the Core Study". Pass: no line of the Extension Phase is an active criterion without a warning, and neither diagnosis-group line is `structured` (else MCI patients are excluded silently).
2. **AD-MAB against the planted gold with the real models.** `tests/integration/test_ad_mab.py` scenario on the `jp-ad` synthetic site with the real judge: record recall and precision of the three note criteria (MMSE 22 to 30, CDR 0.5 or 1, amyloid positive) against `rulesets/AD-MAB/tests/expected.json` and the generator's gold, and the share answered unknown. Pass: the plan's note-criterion gate; no planted candidate excluded on a note answer.
3. **Cost of re-checking everything weekly (for LIFE-003/004).** MICROBATCH on RA-JAK and GZQO at the 50,000-patient site with `ts` = every structured and mixed criterion and the excluded list included: record seconds per 1,000 patients re-checked (SQL path only) and the number that changes list. Pass: the weekly run of every open study fits the night budget (`TB_MICROBATCH_NIGHT_BUDGET`) with the measured speed.

## 11. Small certain fixes (not applied)

1. **LIFE-001** `libs/tb_common/ruleset.py:238` `seed_working_copy`: return `False` when `tb_env()` is VALIDATION or PRODUCTION (or copy with `status: draft` and the `review` block removed). Test that fails first: a new case in `tests/unit/test_g1_b3_rulesets_default.py`, "under `TB_ENV=PRODUCTION` an empty folder holds no approved ruleset after start".
2. **LIFE-006** `services/console/study_setup.py:547` (before `set_study_state`): when `state == "closed"`, ask the lifecycle API for the study's subjects and return 409 `sstate.subjects_on_study` if any is `consented`, `enrolled` or `on_study`. Test: `tests/console/test_study_state_d386.py`, "closing a study with an enrolled subject is refused and the state stays open".
3. **LIFE-005** `services/console/screening_log.py:210-211`: replace `if pid in gone: continue` by keeping the row (it has a screening number by construction) with `status` shown and a field `opted_out: True`; leave the pre-screen filter (`:187`) only for patients with no number. Test: `tests/console/test_prescreen_log.py`, "an enrolled subject who opts out stays on the screening log and its XLSX with the note".
4. **LIFE-003** `services/orchestrator/scenarios/microbatch.py:211`: `ts = {c.id for c in rs.active() if (c.time_sensitive or c.class_ in FILTERED) and c.kind in ("inclusion", "exclusion")}`. Test: `tests/unit/test_microbatch_cadence.py`, "an RA-JAK pool patient with a new serious-infection code in the 30-day window is a change on the weekly list". Goldens for MICROBATCH will move; state the reason.
5. **LIFE-010** `deploy/install.sh:510`: a second cron line after `logs daily`: `python3 tools/audit_verify.py /data/audit --sign-head` (targets from `TB_AUDIT_ANCHOR_TARGETS`), and `--init-key` in the secrets step. Test: `tests/unit/test_audit_anchor.py` plus an install-script test that the cron file names `--sign-head`.

## 12. What is good

- The lifecycle module is one readable file with one table of legal steps, and every refusal has a plain reason key. Derivation holds instead of forcing; consent is never implied by a TrialBox form.
- The SAE register: one place per fact, no patient text, a trail with old and new dates, "sent late" shown, follow-ups, and the guide says the office SOP governs.
- Amendments: the version in force by date, the version on every mark, and a re-screen list in three groups. This is more than most site tools do.
- Staff mails carry a pseudonym and a screening number and nothing else; nothing is ever sent to a patient.
- The monitor's scope (grant window, enrolled subjects, cited items only, every read audited).
- The audit chain catches an edit and a truncation by itself; the journal is append-only by database role.
- Opportunity feed and feasibility: floor, rounding, complementary suppression, a signed feed. Careful work.
- Almost every decision of the last two days came with a test that passes here.

## 13. What was not checked

- The e2e passes, but it walks the happy path: none of LIFE-001 to LIFE-016 is a case in it.
- The console in a browser, the three languages on the pages, the EDC prefill and signature pages, the REDCap bridge, the consent explainer with a model.
- Whether the mail gateway refuses the shipped rulesets' `hospa.test` recipients (LIFE-001).
- The opportunity hub and the sponsor sample (D-467) beyond the decision and the suppression functions.
- `tests/integration/test_ad_mab.py`, `test_ra_jak.py` (not run: they build a site; the machine was at load 20).
- Japanese and Taiwanese reporting rules are stated from working knowledge; no legal text was fetched. Each trial office confirms.
- The real-model behaviour on real protocol text (§10, test 1). LIFE-002's parser half is reproduced; its model half is an expectation.
- Only the `eligibility_criteria` field of the two ClinicalTrials.gov records was read; nothing else of those records was used.

Note on the runs. `e2e_simple` needed three things this checkout does not have: the CQL translator jar (taken from the local Maven cache via `TB_CQL_TRANSLATOR_LIB`), a PostgreSQL data folder the `postgres` user can enter (the scratch folder's parent is mode 700 and is reset; I used `TB_PG_DIR=/var/tmp/tb-dr2-life/pglocal`), and the report fonts (`TB_FONTS_DIR` pointing at a copy in my scratch folder). Each missing piece stopped the run with a plain message, except the font, which failed the SCREEN job itself (LIFE-022). With the three in place it passed in 660 s on a machine at load 20. In its audit chain the lifecycle left: `life.step` 9, `life.log_sync` 24, `life.refused` 2, `life.schedule` 1, `data.entry` 11, `console.sae` 1, `life.report` 2.
