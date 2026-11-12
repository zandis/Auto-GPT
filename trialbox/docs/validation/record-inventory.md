# Record inventory: every record the box makes or holds

*Card T-643 (deep review REG-022; TB6-REG-03). Decision D-363. Status: living. No signature (D-311).*

TrialBox makes and holds records that a monitor, an auditor or the trial office may ask for. This page says, for each
one, what kind of record it is, where the record of truth lives, who keeps it, for how long, how it leaves the box for
the investigator site file (ISF) and which audit events cover it. §4 maps every table the code creates to one row
here; `tests/unit/test_record_inventory.py` and `python tools/gen_traceability.py --check` fail or warn when a table
has no row. The release record carries the table of §2 (`release-records/README.md` item 9).

## 1. How to read the tables

**Class.**

| Class | Meaning |
| --- | --- |
| essential | an essential record of the trial in the sense of ICH E6(R3) Appendix C: it shows how the trial was run |
| source | the first place a fact is written down; TrialBox is the system of record for it |
| copy | a copy of a record kept elsewhere (the hospital EMR, the sponsor's EDC, a signed paper log); the other place is the system of record |
| aid | a working aid for the team; useful, not evidence of how the trial was run |
| control | the box's own evidence that it ran as it should (audit trail, access, configuration, validation) |

**Keeper.** The site keeps everything on the box: the box is the site's machine (VMP §2, the regulated user). The
column names who answers for the content at the site.

**Retention.** "Kept" means no job of the box deletes it: the record stays until the site archives the study. How long
the site keeps it after that is the trial's essential-record period, which the sponsor agreement and the law of the
site set (ICH E6(R3) Appendix C; J-GCP and the Taiwanese GCP rules); the box does not set it. Where the box does
delete, the setting is named (`libs/tb_common/retention.py`, `DEFAULTS`: per country, changeable at install). These
are defaults to discuss with the site, not legal advice.

**ISF export.** The page or route that gives the record as a file. "Page only" means there is no file yet: the ISF
bundle of card T-304 builds from this table.

## 2. The records

| Id | Record | Class | System of record | Keeper | Retention | ISF export | Audit events |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R-01 | Audit chain: every action, hash-chained, with the head anchor; one writer copies the services' events from the append-only journal (D-394) | control | the box; the nightly archive on the hospital share | site administrator | 10 years on the box (`audit_years`); the archive is never deleted | the archive's day files and its head anchor; `tools/audit_verify.py` | all |
| R-02 | Export ledger: every file or record set that left the box, to whom, under which approval | control | the audit chain (`flow.export` events) | data steward | as R-01 | `libs/tb_common/flowledger.py` `exports` | `flow.export` |
| R-03 | Screening log: screening numbers, the PI's mark, contact outcomes, registry status; the pre-screen log, one row per PI mark with its criteria version, and the criterion not met on a screen failure (D-387) | essential | the box, pseudonymous; the site's registry resolves the chart number | PI, through the trial office | kept | `/studies/{rs}/screening-log.xlsx`; `/registry/{ruleset}/export.xlsx` | `console.pi_mark`, `console.contact_outcome`, `console.registry`, `registry.export` |
| R-04 | Delegation log copy and its monthly check | copy | the trial office's signed delegation log | trial office | kept | page only | `console.delegation` |
| R-05 | Consent and approval checks: IRB approval and consent-form version per study, every Approach marked despite a warning; whether the approved IRB text covers the cross-department identified candidate view, with its approval number, version and date, as the PI recorded it (D-395); the approved consent-form versions with their history, and every consent saved on a version under a warning (D-399) | aid | the IRB file and the signed consent forms at the site (never in the box) | trial office | kept | page only | `console.irb`, `console.approach_override`, `console.irb_text`, `console.icf`, `console.consent_version_override` |
| R-06 | Research-use opt-out register | copy | the patient's opt-out form at the research office | research office | kept (an event log: an opt-out and a lift) | page only | `console.opt_out` |
| R-07 | SAE register: the case, its deadlines, receipts and follow-ups, its trail, and the study's confirmed SAE rule set | essential | the AE form of the data core (R-09) or the sponsor's CRF for the facts; the register for the clock and the receipts | PI | kept | page only | `console.sae`, `console.sae_ack`, `life.sae_ack`, `life.report`, `life.sae_rule` |
| R-08 | EDC prefill: the switch, the item map, drafts and their fate, decisions, electronic signatures and their voids, what was sent, the copy-assist ticks (D-434) | essential | the sponsor's EDC holds the CRF; the box holds the trail of each prefilled value | PI | kept (drafts are never deleted; decisions, sends and ticks are append-only) | `/studies/{rs}/edc/export.odm.xml`, `/studies/{rs}/edc/copy.csv` | `edc.switch`, `edc.map`, `edc.drafts`, `edc.decide`, `edc.sent`, `edc.reentry`, `edc.copy_view`, `edc.copy_tick`, `console.edc`, `console.edc_copy` |
| R-09 | Data core: study forms, entered values and their history, conflicts, field owners | source | per field (`owner`): the box for a field TrialBox owns; REDCap or another source for a field it owns | PI | kept | `/studies/{rs}/export.{fmt}` (CSV, XLSX, ODM) | `data.entry`, `data.sync`, `data.import`, `data.resolve`, `data.export`, `data.forms`, `data.source` |
| R-10 | Subject lifecycle: the subject's state and every step (a "not eligible" screen failure with the criterion not met and its version, D-387), the schedule of events and its versions with their effective dates (D-364); the study's contact-attempt rule and the coordinator's answer to each possible deviation (D-407) | copy | R-09 and the screening log; a step a person enters is written here first | PI | kept | page only | `life.step`, `life.schedule`, `console.life_step`, `console.life_schedule`, `life.contact_rule`, `life.deviation_call`, `console.deviation_call` |
| R-11 | Referrals to treating physicians and their answers | aid | the box | CRC | kept | page only | `console.referral` |
| R-12 | Candidate views, chart-number reveals and the administrator's break-glass grants | control | the box | data steward | kept | page only | `console.candidate_view`, `console.reveal_patient`, `console.reveal_refused`, `screen.reveal`, `screen.reveal_refused`, `console.breakglass_open`, `console.breakglass_use`, `console.breakglass_end`, `console.breakglass_review` |
| R-13 | User accounts and roles | control | the box (or the hospital's sign-in service, where one is set) | site administrator | kept; a retired account stays | page only | `console.user`, `console.login`, `console.totp_enrolled`, `console.totp_reset` |
| R-14 | Feature flags and every change | control | the box | site administrator | kept | page only | `flag.seed`, `flag.set` |
| R-15 | Study settings, REDCap links and the screening scope | control | the box | trial office | kept | page only | `study.settings`, `study.screen_scope`, `redcap.connection`, `redcap.link` |
| R-16 | REDCap read-back and writes: what the box read from the sponsor's project and what it wrote | copy | the sponsor's REDCap project | trial office | kept | page only | `redcap.read`, `redcap.write`, `console.redcap_read` |
| R-17 | Criterion library and approved ruleset releases | control | the box; the ruleset files of the release | data steward | kept | the ruleset release in the update bundle | `console.study_setup`, `console.proposal` |
| R-18 | Jobs: every screening run with its ruleset, model, snapshot and outputs, and every submission | control | the box | data steward | kept; outputs `outputs_days` | the job's output files | `job.requeued`, `console.cascade`, `console.command` |
| R-19 | Recall ledger: audit draws and the confidence sequences of the excluded lists | control | the box | data steward | kept | page only | (in the job's events) |
| R-20 | Site set-up: inputs, facts read or confirmed, local codes, checks, published settings | aid | the box; the site's sheets and charts in the protected data folder | data steward | kept | page only | `setup.fact`, `setup.resolve`, `setup.publish`, `console.site_fact`, `console.site_map` |
| R-21 | Feasibility answers the site types (site profile) | aid | the box | PI | kept | on the feasibility report | `console.site_profile` |
| R-22 | Screening review traces: criterion labels, code pre-ticks, amber rows opened, the review of the excluded list; the weekly PI sample of ten "criteria not matched" patients with the run and snapshot each was drawn from and the PI's answer, and the site's check that opens the list (D-446) | aid | the box | PI | kept | page only | `console.excluded_review`, `console.view`, `notmatched.sample`, `notmatched.held`, `console.notmatched_answer`, `console.notmatched_check` |
| R-23 | Derived scores with their inputs and definition versions; the derive batch of each snapshot (D-442) | copy | the hospital data they are computed from (R-25) | data steward | kept | page only | `derive.batch`, `derive.failed` |
| R-24 | Pseudonym map and master patient index: the only link from a pseudonym back to a chart number | control | the box (encrypted; the key under the KEK) | site administrator | kept while any record keyed by the pseudonym is kept | never exported | `console.reveal_patient`, `console.chart_lookup` |
| R-25 | The hospital data copy: OMOP rows and TrialBox's extension rows, the lake snapshots | copy | the hospital EMR and its export | data steward | snapshots: `nightly_snapshots` and `month_end_snapshots_months`; OMOP rows replaced by each load | never exported as such | `console.site_patients` |
| R-26 | Mail and notice logs | aid | the mail server; the box keeps the index | site administrator | `mail_log_days` (five years Japan, seven years Taiwan) | page only | `mail.received`, `mail.duplicate_suppressed`, `mail.deferred`, `mail.failed`, `mail.uncertain`, `mail.resolved`, `retention.mail`, `console.notice` |
| R-27 | Study state and identifiers: the state (start-up, open, paused, closed) with every change, who, when and why; sponsor, protocol number, SIV date, registry ids (D-386) | control | the box; the sponsor's and the registries' own records for the identifiers | trial office | kept (the state is an event log) | the screening log's "about" sheet (`/studies/{rs}/screening-log.xlsx`) | `console.study_state`, `console.study_identity`, `scheduler.held` |
| R-28 | Ingest batch register: one row per ingest run (source, snapshot, attempt) with its state (landed, validated, mapped, pseudonymised, published, held, failed, rejected), every step with who, when and the audit event that recorded it, and the steward's accept or reject of a held night with its reason (D-427) | control | the box | data steward | kept (the steps are append-only) | page only | `ingest.done`, `ingest.held`, `ingest.failed`, `dataops.decide`, `dataops.step` |
| R-29 | Patient twin (`tb_patient_profile` v1): one pseudonymous document per study patient and version, built with no model from a named lake snapshot (R-25) and the derived rows (R-23); every item names its source table, row hash and date (D-440) | copy | the hospital data copy (R-25) it is built from | data steward | kept: every version (a new one only when the content changes); erased with every version when the patient opts out (R-06; the opt-out worker, T-206a) | never exported as such | `console.twin_view` |
| R-30 | Monitoring-visit records: the visit date, the CRA's account, the monitoring-visit id of the grant, the subjects verified and the findings; the monitor's reads of the source-reference sheets (D-436) | copy | the sponsor's monitoring visit report | trial office | kept (append-only by code: a correction is a new record) | page only (the monitor page and its API twin) | `console.monitor_visit`, `console.monitor_view` |

R-01 and R-02 also hold the training evidence of `qms-lite.md` §3 (first sign-in and the acknowledgement event).

## 3. Other stores (not records)

| Id | Store | Why it is not a record | Retention |
| --- | --- | --- | --- |
| O-01 | Sign-in state: sessions, pending sign-ins, single sign-on hand-offs, failure counters | transient; every sign-in, failure and lock is in R-01 | until the session or the lock ends |
| O-02 | Feedback entries (in-product feedback) | product feedback, not about a patient or the trial | kept; exported by the owner |
| O-03 | Model traces | debugging aid, redacted at write; the audit trail is the gateway's ledger and R-01 | 7 days in PRODUCTION, 90 in DEV and TEST (`tracestore` `production_retention_days`, `retention_days`; D-346); PRODUCTION D3 and D4 rows hold sha256 and size only (D-431) |
| O-05 | Working pool and the PI feedback of a job | rebuilt by each run; the marks of R-03 are the record | `pool_months_after_ruleset` |
| O-06 | Weekly appearances | "new this week" on the list | kept |
| O-07 | Notice recipients | settings | kept |
| O-08 | Staff directory and department contacts | the referral's "who to ask" | kept |
| O-09 | Public and licensed reference data: registry, terminology, maps, vocabulary releases | public or licensed data, not about the trial | replaced by each pack or release |
| O-10 | Aggregate cohort tables and the public trial cache | aggregate counts and a public registry cache | `outputs_days` |
| O-11 | Embedding cache of the lake | vectors keyed by a text hash; rebuilt from R-25 | kept |
| O-12 | Schema versions | how a database is migrated | kept |
| O-13 | Vector store of note chunks (schema `vec`, D-439): each masked chunk of a note with its offsets, and one vector per chunk text and embedding model | derived from the notes of R-25 after the PHI pass, rebuilt from them; never exported | kept while the note is in R-25; the opt-out worker calls `VecStore.delete_patient` on each tick (T-727, D-465), which removes the patient's chunks and every vector no other chunk uses |

## 4. Store map

Every table the code creates, by module. `tests/unit/test_record_inventory.py` reads this table and the code: a table
with no row, a row for a table the module no longer creates and an id with no row all fail. File stores (no table)
are marked "files".

| Module | Tables | Id |
| --- | --- | --- |
| `libs/tb_common/audit.py` | files: the day files, the head anchor, the archive | R-01 |
| `libs/tb_common/audit_writer.py` | `journal` | R-01 |
| `libs/tb_common/flowledger.py` | files: `flow.export` events in the audit chain | R-02 |
| `services/console/sitestore.py` | `screening_no`, `contact_outcomes`, `pi_marks` | R-03 |
| `services/orchestrator/db.py` | `candidates`, `candidate_events` | R-03 |
| `services/console/teamstore.py` | `delegation`, `delegation_history`, `delegation_checks` | R-04 |
| `services/console/teamstore.py` | `icf_versions` | R-05 |
| `services/console/teamstore.py` | `irb`, `approach_overrides` | R-05 |
| `services/console/sitestore.py` | `study_irb_text` | R-05 |
| `libs/tb_common/optout.py` | `optout_events` | R-06 |
| `services/console/saerecord.py` | `sae_case`, `sae_report`, `sae_trail` | R-07 |
| `services/datacore/lifecycle.py` | `ae_ack`, `sae_rule` | R-07 |
| `services/edc/store.py` | `switch`, `switch_event`, `item_map`, `map_event`, `target`, `draft`, `decision`, `signature`, `signature_void`, `sent`, `reentry_record`, `copy_tick` | R-08 |
| `services/datacore/store.py` | `form`, `value`, `history`, `conflict`, `owner`, `source_cfg`, `src_record` | R-09 |
| `services/datacore/lifecycle.py` | `subject`, `subject_step`, `schedule`, `schedule_version`, `contact_rule`, `deviation_call` | R-10 |
| `services/console/teamstore.py` | `referrals`, `referral_events` | R-11 |
| `services/console/teamstore.py` | `candidate_views` | R-12 |
| `services/console/teamstore.py` | `monitor_visits` | R-30 |
| `services/console/breakglass.py` | `grants` | R-12 |
| `services/console/breakglass.py` | `uses` | R-12 |
| `services/orchestrator/db.py` | `id_limits` | R-12 |
| `services/console/auth.py` | `users` | R-13 |
| `libs/tb_common/flags.py` | `flag`, `flag_event` | R-14 |
| `services/orchestrator/studystore.py` | `study_settings`, `rc_connection`, `rc_project_link`, `screen_scope` | R-15 |
| `services/console/sitestore.py` | `study_settings` | R-15 |
| `services/orchestrator/studystore.py` | `rc_record`, `rc_read_log`, `rc_write` | R-16 |
| `services/criteria_compiler/library/ddl.py` | `criterion_library`, `criterion_library_text`, `criterion_library_valueset`, `criterion_library_lexicon_key`, `criterion_library_usage`, `criterion_library_meta` | R-17 |
| `services/omop/schema.py` | `tb_ruleset_release` | R-17 |
| `services/orchestrator/db.py` | `jobs`, `submissions`, `judge_answers` | R-18 |
| `services/orchestrator/recall/ledger.py` | `recall_cell`, `recall_observation`, `recall_sequence_state`, `recall_run_cell`, `recall_registration`, `recall_known_positive` | R-19 |
| `services/sitesetup/store.py` | `input`, `fact`, `local_code`, `check_item`, `fix`, `setting`, `published` | R-20 |
| `services/console/sitestore.py` | `site_profile` | R-21 |
| `services/console/sitestore.py` | `criterion_labels`, `code_ticks`, `approval_opened`, `excluded_review` | R-22 |
| `libs/tb_common/notmatched.py` | `tuned_patients`, `not_matched_check` | R-22 |
| `libs/tb_common/derived_store.py` | `definition`, `score_row`, `input_link`, `conflict`, `batch_run` | R-23 |
| `services/adapter/pidmap.py` | `pid_map`, `identity`, `site_key`, `pid_alias` | R-24 |
| `services/omop/schema.py` | `tb_record`, `tb_record_event`, `tb_conflict`, `tb_id_map`, `tb_appointment`, `tb_claim`, `tb_consent`, `tb_load`, `tb_withheld` | R-25 |
| `services/lake/store.py` | `document_chunk`, `lake_meta` | R-25 |
| `services/mail_gateway/store.py` | `intake`, `sent`, `send_keys` | R-26 |
| `services/orchestrator/db.py` | `mails` | R-26 |
| `services/console/sitestore.py` | `notify_log` | R-26 |
| `services/console/sitestore.py` | `study_state`, `study_identity` | R-27 |
| `services/datacore/dataops.py` | `batch`, `batch_step` | R-28 |
| `services/datacore/sponsor.py` | `sponsor_layout` | R-10 |
| `services/patient_profile/twin.py` | `tb_patient_profile` | R-29 |
| `services/console/auth.py` | `sessions`, `pending_logins`, `oidc_pending`, `login_failures` | O-01 |
| `services/console/feedback.py` | `entry` | O-02 |
| `services/tracestore/store.py` | `traces`, `access_log` | O-03 |
| `services/orchestrator/db.py` | `pool`, `feedback` | O-05 |
| `services/console/sitestore.py` | `weekly_seen` | O-06 |
| `services/console/sitestore.py` | `notify_people` | O-07 |
| `services/console/teamstore.py` | `staff`, `dept_contacts` | O-08 |
| `libs/tb_common/refdata.py` | `pack`, `source`, `ctgov_study`, `trial`, `term`, `concept_map`, `synonym`, `withdrawn` | O-09 |
| `services/adapter/licensed.py` | `release`, `concept` | O-09 |
| `services/omop/schema.py` | `tb_vocab_release`, `tb_concept_attr`, `tb_term_grouper`, `tb_map_relation` | O-09 |
| `services/orchestrator/db.py` | `cohort_tables`, `trial_cache` | O-10 |
| `services/lake/store.py` | `cache` | O-11 |
| `libs/tb_common/db.py` | `_schema_version` | O-12 |
| `services/vec/store.py` | `embedding`, `note_chunk` | O-13 |

**Erasure.** What an opt-out does to each table, lake folder, object prefix and outside store (erased by a named
clear and read back, kept with its decision, owed by a card, or no patient data) is the generated
[`erasure-registry.md`](erasure-registry.md), from `libs/tb_common/erasure.py` (T-727, D-465); a table with a row
here and no obligation there fails `tests/unit/test_erasure_registry.py`.

The standard OMOP CDM tables (`services/omop/ddl/OMOPCDM_postgresql_5.4_ddl.sql`) are R-25 as a whole. The trace
store's `access_log` is an access record of O-03's own data, kept with it.

## 5. Not done here

- The site's own retention period per study is not a setting yet; "kept" means the box never deletes.
- ISF export for the rows marked "page only" is card T-304.
- REG-022 asked that each site's trial office sign this page; D-311 removed signers. A site that wants it signed
  prints it.
