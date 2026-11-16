# Erasure registry: what an opt-out removes, keeps and still owes

*Generated from `libs/tb_common/erasure.py` by `python -m tb_common.erasure --write` (T-727, D-465). Do not edit by hand.*

228 entries: 86 erase, 27 keep, 115 no patient data. 49 erase entries are owed. `tests/unit/test_erasure_registry.py` fails on a table, lake entry or object prefix the code makes with no entry here.

## 1. Erased on opt-out today

The opt-out worker runs each clear on every tick and reads the store back; a row left fails the tick.

| Clear | What it does | Stores |
| --- | --- | --- |
| `candidate_pool` | MICROBATCH's pool rows go (D-441) | `orch.pool` |
| `candidate_registry` | open candidates become withdrawn; consented and enrolled are kept (OD-8, D-441) | `orch.candidates` |
| `held_mail` | a mail held because its files name an opted-out patient is dropped: its request and recipients go (D-863) | `mail.send_keys` |
| `omop` | tb_withheld, and the live rows deleted and tombstoned at once (D-441) | `omop.condition_occurrence`, `omop.condition_occurrence_ydefault`, `omop.death`, `omop.drug_exposure`, `omop.drug_exposure_ydefault`, `omop.fact_relationship`, `omop.measurement`, `omop.measurement_ydefault`, `omop.note`, `omop.note_nlp`, `omop.note_ydefault`, `omop.observation`, `omop.observation_period`, `omop.observation_ydefault`, `omop.person`, `omop.procedure_occurrence`, `omop.procedure_occurrence_ydefault`, `omop.tb_appointment`, `omop.tb_claim`, `omop.tb_record`, `omop.visit_occurrence`, `omop.visit_occurrence_ydefault` |
| `owed_tables` | T-206b part 1 (D-798): the patient's rows in the site, team, PI feedback and derived tables go (the nightly derive skips an opted-out patient); a batch's failed list loses the pseudonym | `derived.batch_run`, `derived.conflict`, `derived.input_link`, `derived.score_row`, `orch.feedback`, `orch.submissions`, `site.contact_outcomes`, `site.excluded_review`, `team.approach_overrides`, `team.referral_events`, `team.referrals` |
| `pid_pending` | the staged chart number and identity of the patient go; a later night stages them again (D-489) | `pidmap.pending` |
| `profile` | ProfileStore.erase: every version of the twin (D-440) | `profile.tb_patient_profile` |
| `vec` | VecStore.delete_patient: the chunks and every vector no other chunk uses (D-439) | `vec.embedding`, `vec.note_chunk` |

## 2. Erasure owed

| Store | Card | What is owed | Why it holds patient data |
| --- | --- | --- | --- |
| `edc.draft` | T-206b | the drafts of a patient who never enrolled (an enrolled subject's stay, OD-8) | an EDC draft, by pseudonym |
| `lake:backfill` | T-206b | the clear | the back-fill's working copy of a year's extract |
| `lake:db` | T-206b | withheld on read by every job's scope (D-441, D-860); the compiler's equivalence sample, direct /query | the DuckDB snapshots (nightly and month-end) and their side files |
| `lake:embed_cache.duckdb` | T-206b | pruning by the patient | vectors of note chunks by text hash, never pruned |
| `lake:fhir_ledger` | T-206b | the clear | the FHIR sync ledger: resource ids and hashes per patient |
| `lake:ndjson` | T-206b | withheld on read by every job's scope (D-441, D-860); the compiler's equivalence sample, direct /query | the nightly NDJSON extracts (3 nightly + month-ends kept) |
| `lake:ndjson-rerun` | T-206b | withheld on read by every job's scope (D-441, D-860); the compiler's equivalence sample, direct /query | a re-run of a promoted night until it passes the gate (D-271) |
| `lake:parquet` | T-206b | withheld on read by every job's scope (D-441, D-860); the compiler's equivalence sample, direct /query | the Parquet copy of each snapshot |
| `lake:site` | T-206b | the clear | facts the site set-up published, as NDJSON, by pseudonym |
| `lake:tmp` | T-206b | the clear | the rebuild's and the night's ingest scratch files (removed after each; a crash may leave them) |
| `mail.send_keys` | T-206b | a queued or uncertain mail: its files are asked about before each send (D-863), its row stays until a person or the send ends it | the outbox's send request while queued (attachments by key, a per-patient file's name, recipients) |
| `objects:attachments` | T-206b | the clear | files mailed or uploaded to a job (consent forms, review sheets, case requests) |
| `objects:outputs` | T-206b | kept until retention (D-513): other patients' pages read the same files, so no clear deletes them | job outputs: candidate and excluded lists, micro-batch pids (365 days); withheld on read (D-513, D-860): the console's pages and downloads (a per-patient file by its patient), a submission and a feedback row; the mail outbox asks before each send (D-863) |
| `omop.cohort` | T-206b | a delete by person when a loader writes it | a CDM table keyed by person that no loader writes today |
| `omop.condition_era` | T-206b | a delete by person when a loader writes it | a CDM table keyed by person that no loader writes today |
| `omop.cost` | T-206b | a delete by person when a loader writes it | a CDM table keyed by person that no loader writes today |
| `omop.device_exposure` | T-206b | a delete by person when a loader writes it | a CDM table keyed by person that no loader writes today |
| `omop.dose_era` | T-206b | a delete by person when a loader writes it | a CDM table keyed by person that no loader writes today |
| `omop.drug_era` | T-206b | a delete by person when a loader writes it | a CDM table keyed by person that no loader writes today |
| `omop.episode` | T-206b | a delete by person when a loader writes it | a CDM table keyed by person that no loader writes today |
| `omop.episode_event` | T-206b | a delete by person when a loader writes it | a CDM table keyed by person that no loader writes today |
| `omop.location` | T-206b | a delete by person when a loader writes it | a CDM table keyed by person that no loader writes today |
| `omop.payer_plan_period` | T-206b | a delete by person when a loader writes it | a CDM table keyed by person that no loader writes today |
| `omop.specimen` | T-206b | a delete by person when a loader writes it | a CDM table keyed by person that no loader writes today |
| `omop.tb_conflict` | T-206b | the clear | a source conflict of a person |
| `omop.tb_record` | T-206b | the tombstoned row keeps the person id and the source record id | the record ledger: the person's live records are tombstoned |
| `omop.tb_record_event` | T-206b | the before-images | every change of a record with its before-image |
| `omop.visit_detail` | T-206b | a delete by person when a loader writes it | a CDM table keyed by person that no loader writes today |
| `orch.candidate_events` | T-206b | the events of a patient never consented (OD-8 keeps the rest) | each status change of a candidate, by pseudonym |
| `orch.candidates` | T-206b | a withdrawn row keeps the pseudonym (consented and enrolled rows are kept, OD-8) | the candidate registry |
| `orch.jobs` | T-206b | the clear | a job's request may name a pseudonym (CASE, a reveal) |
| `outside:backups` | T-206b | the backups (with T-728) | every backup: the databases, the lake, the FHIR store |
| `outside:fhir_store` | T-206b | the clear | the FHIR store (HAPI, database hapi): every resource of the patient |
| `outside:sitesetup_space_omop` | T-206b | the opt-out's clear in a practice space's store | the OMOP store of a site set-up space other than the hospital's (schema omop_<hash of the space's lake folder>, made by a publish while the lake is built from OMOP): the space's uploaded patients; Reset of the space drops it whole (D-714) |
| `pidmap.identity` | T-206b | the crypto-shred of the opted-out identity | the encrypted identity of the patient |
| `recall.recall_known_positive` | T-206b | the clear | pid_hash: an unsalted hash of the pseudonym, linkable |
| `recall.recall_observation` | T-206b | the clear | pid_hash: an unsalted hash of the pseudonym, linkable |
| `site.pi_marks` | T-206b | the marks of a patient never consented (the screening log's, OD-8) | the PI's mark on a patient, by pseudonym |
| `site.screening_no` | T-206b | the number of a patient never consented (the screening log's, OD-8) | the screening number given to a pseudonym |
| `site.weekly_seen` | T-206b | with the screening log (LIFE-005): a numbered row keeps its first-listed day (D-762) | the week a pseudonym first appeared on a list |
| `sitesetup.check_item` | T-206b | the clear | the raw value of an uploaded row |
| `sitesetup.fact` | T-206b | the clear | a fact read from an uploaded file, by pseudonym |
| `sitesetup.fix` | T-206b | the clear | example values of an uploaded column |
| `sitesetup.input` | T-206b | the clear | an uploaded file and the patient it belongs to |
| `study.rc_record` | T-206b | the rows of a patient never consented (a consented subject's stay, OD-8) | the REDCap project's records linked to pseudonyms |
| `study.rc_write` | T-206b | the clear | what was written to REDCap, by link value and record |
| `team.candidate_views` | T-206b | the reveal cap counts these rows and they say who saw an identity: a clear that keeps both | a cross-department view of a candidate, by pseudonym |
| `trace.traces` | T-206b | the traces of the patient (7 days kept) | a model call's redacted body: note excerpts |
| `tuned.tuned_patients` | T-206b | a clear that does not redraw a reviewed week's sample | the weekly PI sample of patients not matched, by pseudonym |

## 3. Kept, with the decision

| Store | Decision | Why |
| --- | --- | --- |
| `breakglass.grants` | D-430 | the record of an emergency access to a patient, for the steward's review |
| `breakglass.uses` | D-430 | each use of a break-glass grant, for the steward's review |
| `datacore.ae_ack` | OD-8 | the trial record of a consented or enrolled subject stays (GCP) |
| `datacore.conflict` | OD-8 | the trial record of a consented or enrolled subject stays (GCP) |
| `datacore.deviation_call` | OD-8 | the trial record of a consented or enrolled subject stays (GCP) |
| `datacore.history` | OD-8 | the trial record of a consented or enrolled subject stays (GCP) |
| `datacore.src_record` | OD-8 | the trial record of a consented or enrolled subject stays (GCP) |
| `datacore.subject` | OD-8 | the trial record of a consented or enrolled subject stays (GCP) |
| `datacore.subject_step` | OD-8 | the trial record of a consented or enrolled subject stays (GCP) |
| `datacore.value` | OD-8 | the trial record of a consented or enrolled subject stays (GCP) |
| `edc.copy_tick` | OD-8 | the trial record of a consented or enrolled subject stays (GCP) |
| `edc.decision` | OD-8 | the trial record of a consented or enrolled subject stays (GCP) |
| `edc.sent` | OD-8 | the trial record of a consented or enrolled subject stays (GCP) |
| `edc.signature` | OD-8 | the trial record of a consented or enrolled subject stays (GCP) |
| `edc.signature_void` | OD-8 | the trial record of a consented or enrolled subject stays (GCP) |
| `omop.tb_consent` | D-441 | the refusal itself must reach the lake, or the registry would read as silent |
| `omop.tb_id_map` | D-441 | pseudonym to person id: the worker and the loader must still find the person |
| `omop.tb_withheld` | D-441 | the register's copy the loader reads to keep the patient out |
| `optout.optout_events` | D-441 | the opt-out register itself: the record of the refusal (D-147) |
| `orch.judge_answers` | D-456 | a model's answers (a verdict and a quote; no pseudonym column) kept only while their job is unfinished: deleted when the job ends in any state, and at the orchestrator's start for jobs finished or gone |
| `outside:audit` | D-394 | the audit chain and its journal: append-only, hash-chained; the opt-out's own events carry counts only, never who (D-147, D-441) |
| `pidmap.pid_alias` | D-441 | a merged chart's opt-out hides the surviving pseudonym (append-only) |
| `pidmap.pid_map` | D-441 | the chart number must still be recognised at the door to honour the opt-out |
| `sae.sae_case` | OD-8 | the SAE register of a trial subject |
| `sae.sae_report` | OD-8 | the SAE register of a trial subject |
| `sae.sae_trail` | OD-8 | the SAE register of a trial subject |
| `team.monitor_visits` | OD-8 | a monitoring visit's record: the subjects reviewed are trial subjects (an essential record) |

## 4. No patient data

| Store | What it holds |
| --- | --- |
| `app.flag` | settings and configuration, no patient |
| `app.flag_event` | settings and configuration, no patient |
| `auth.account_notices` | staff, accounts or sign-in state, no patient |
| `auth.account_requests` | staff, accounts or sign-in state, no patient |
| `auth.factor_resets` | staff, accounts or sign-in state, no patient |
| `auth.login_failures` | staff, accounts or sign-in state, no patient |
| `auth.oidc_pending` | staff, accounts or sign-in state, no patient |
| `auth.pending_logins` | staff, accounts or sign-in state, no patient |
| `auth.sessions` | staff, accounts or sign-in state, no patient |
| `auth.users` | staff, accounts or sign-in state, no patient |
| `datacore.contact_rule` | settings and configuration, no patient |
| `datacore.form` | settings and configuration, no patient |
| `datacore.owner` | settings and configuration, no patient |
| `datacore.sae_rule` | settings and configuration, no patient |
| `datacore.schedule` | settings and configuration, no patient |
| `datacore.schedule_version` | settings and configuration, no patient |
| `datacore.source_cfg` | settings and configuration, no patient |
| `datacore.sponsor_layout` | settings and configuration, no patient |
| `dataops.batch` | ingest batches and their steps: counts |
| `dataops.batch_step` | ingest batches and their steps: counts |
| `dataops.built` | which generation each derived artefact is built from: names, states and times (D-491) |
| `dataops.built_kept` | the finished generations of the derived rows and their batch ids: no patient (D-525) |
| `derived.definition` | score definitions |
| `edc.item_map` | settings and configuration, no patient |
| `edc.map_event` | settings and configuration, no patient |
| `edc.reentry_record` | settings and configuration, no patient |
| `edc.switch` | settings and configuration, no patient |
| `edc.switch_event` | settings and configuration, no patient |
| `edc.target` | settings and configuration, no patient |
| `feedback.entry` | in-product feedback from staff, not about a patient (record inventory O-02) |
| `lake:.rebuild.lock` | the lock one lake rebuild holds (T-722), no patient |
| `lake:CURRENT` | the name of the served snapshot |
| `lake:CURRENT.tmp` | the served snapshot's name while it is replaced |
| `lake:FEED` | the date of the last feed snapshot |
| `lake:holds` | a job's hold on a snapshot: job id and date |
| `lake:locks` | lock files of the lake's readers and writers (T-722), rebuild job states (T-690) |
| `library.criterion_library` | the criteria library |
| `library.criterion_library_lexicon_key` | the criteria library |
| `library.criterion_library_meta` | the criteria library |
| `library.criterion_library_text` | the criteria library |
| `library.criterion_library_usage` | the criteria library |
| `library.criterion_library_valueset` | the criteria library |
| `mail.intake` | a mail received: sender, action, job |
| `mail.sent` | a mail sent: subject, recipients, tag |
| `objects:ctgov` | public registry text and its parse |
| `omop.care_site` | sites and providers, no patient |
| `omop.cdm_source` | OMOP vocabulary and metadata |
| `omop.cohort_definition` | OMOP vocabulary and metadata |
| `omop.concept` | OMOP vocabulary and metadata |
| `omop.concept_ancestor` | OMOP vocabulary and metadata |
| `omop.concept_class` | OMOP vocabulary and metadata |
| `omop.concept_relationship` | OMOP vocabulary and metadata |
| `omop.concept_synonym` | OMOP vocabulary and metadata |
| `omop.domain` | OMOP vocabulary and metadata |
| `omop.drug_strength` | OMOP vocabulary and metadata |
| `omop.metadata` | OMOP vocabulary and metadata |
| `omop.provider` | sites and providers, no patient |
| `omop.relationship` | OMOP vocabulary and metadata |
| `omop.source_to_concept_map` | OMOP vocabulary and metadata |
| `omop.tb_concept_attr` | OMOP vocabulary and metadata |
| `omop.tb_load` | a load: batch and counts |
| `omop.tb_map_relation` | OMOP vocabulary and metadata |
| `omop.tb_ruleset_release` | OMOP vocabulary and metadata |
| `omop.tb_term_grouper` | OMOP vocabulary and metadata |
| `omop.tb_vocab_release` | OMOP vocabulary and metadata |
| `omop.vocabulary` | OMOP vocabulary and metadata |
| `orch.cohort_read` | D-648: the point in that record at which a merge read the tables (job, a number) |
| `orch.cohort_stored` | D-648: each alliance table as it was stored (aggregate counts per quarter and criterion, the site, the sender's address, the job), kept so that a re-run reads the tables as they stood |
| `orch.cohort_tables` | aggregate counts per quarter and criterion |
| `orch.cohort_tables_before` | D-648: the alliance tables as the version that began the record found them (aggregate counts, as orch.cohort_tables) |
| `orch.id_limits` | the identifier caps' use rows: staff and kind only |
| `orch.mails` | a mail sent: message id, job, kind, subject |
| `orch.trial_cache` | the public registry cache |
| `pidmap.site_key` | the site key's fingerprint |
| `recall.recall_cell` | recall cells and sequences: counts by criterion, no patient |
| `recall.recall_registration` | recall cells and sequences: counts by criterion, no patient |
| `recall.recall_run_cell` | recall cells and sequences: counts by criterion, no patient |
| `recall.recall_sequence_state` | recall cells and sequences: counts by criterion, no patient |
| `refdata.concept_map` | public or licensed reference data |
| `refdata.ctgov_study` | public or licensed reference data |
| `refdata.pack` | public or licensed reference data |
| `refdata.source` | public or licensed reference data |
| `refdata.synonym` | public or licensed reference data |
| `refdata.term` | public or licensed reference data |
| `refdata.trial` | public or licensed reference data |
| `refdata.withdrawn` | public or licensed reference data |
| `site.approval_opened` | a review trace: job, criterion, who |
| `site.code_ticks` | a review trace: job, criterion, who |
| `site.criterion_labels` | settings and configuration, no patient |
| `site.notify_log` | a notice sent: kind, user, day, subject |
| `site.notify_people` | settings and configuration, no patient |
| `site.site_profile` | settings and configuration, no patient |
| `site.study_identity` | settings and configuration, no patient |
| `site.study_irb_text` | settings and configuration, no patient |
| `site.study_settings` | settings and configuration, no patient |
| `site.study_state` | settings and configuration, no patient |
| `sitesetup.local_code` | settings and configuration, no patient |
| `sitesetup.published` | a publish: when, snapshot, digest, counts |
| `sitesetup.setting` | settings and configuration, no patient |
| `study.rc_connection` | settings and configuration, no patient |
| `study.rc_project_link` | settings and configuration, no patient |
| `study.rc_read_log` | a REDCap read: when, who, ok, counts |
| `study.screen_scope` | settings and configuration, no patient |
| `study.study_settings` | settings and configuration, no patient |
| `team.delegation` | staff, accounts or sign-in state, no patient |
| `team.delegation_checks` | staff, accounts or sign-in state, no patient |
| `team.delegation_history` | staff, accounts or sign-in state, no patient |
| `team.dept_contacts` | staff, accounts or sign-in state, no patient |
| `team.icf_versions` | staff, accounts or sign-in state, no patient |
| `team.irb` | staff, accounts or sign-in state, no patient |
| `team.staff` | staff, accounts or sign-in state, no patient |
| `terminology.concept` | public or licensed reference data |
| `terminology.release` | public or licensed reference data |
| `trace.access_log` | who read a trace and why |
| `tuned.not_matched_check` | the site's check of the sample: who, when, a note |
