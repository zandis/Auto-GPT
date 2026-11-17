# Does an opt-out reach every store? A brute-force search, 2026-11-17 (card V-1)

**Reader:** the integrator; lane B2 (erasure in the stores), lane C2 (site set-up, mail), lane D (backup and
restore), lane A2 (the recall ledger), lane E (EDC drafts)

**Verdict.** Criterion 8 of plan 8 does not hold today. The erasure registry owes erasure in 26 stores, and 25 of
them are inside the box; criterion 8 allows none. In the unit box, after one opt-out and one worker tick, the
synthetic patient was still found in 12 stores. These are the lake's snapshot, its Parquet copy and its NDJSON
(with the name, chart number and phone of a note), OMOP's before-images (the same values), job outputs and an
attached chart, a model call's trace, the encrypted identity, the two recall tables, a job's request and an EDC
draft. All 12 are on the registry's owed list. The search found no store that the registry calls erased, or does
not list, still holding the patient. All 31 stores with a clear that the marker reached were clean. Two more things
fail. A restore brings the patient's rows back into the stores until the worker's next tick. Two log lines of the
product write a pseudonym, and the log scrubber keeps it. The FHIR store, the backups and a practice space's stores
were not searched, because they exist only under compose. The tool that searches them on a live box is built and
tested on fakes, and was not run on a box.

## What ran, and what did not

| What | How | Ran |
| --- | --- | --- |
| The reach test | `tests/unit/test_erasure_reach.py`. One box per module: every store's migrations in one throwaway PostgreSQL; the lake made by the night's ingest; the object store, the set-up folder, the mail outbox, the trace store, the recall ledger, the twin, the job queue and OMOP. One marker patient beside five of site A's synthetic patients. The opt-out is the register's `add`, which the console's opt-out route calls (the route itself was not driven). Then `datacore.optout_worker.run_once`, twice | yes |
| The search | `tools/erasure_reach.py`. Every table of every schema, each row read as text, for each value as it is, JSON-escaped, and with its backslashes doubled; integer `person_id` columns against the OMOP person id. Every file of the lake, object, set-up and audit folders: DuckDB and Parquet files opened and read row by row, `.gz` unpacked, all else as bytes. The log records the run wrote. It does not ask the registry where to look | yes |
| The restore | `tests/unit/test_erasure_reach_restore.py`: seed, `trialbox backup`, opt out, tick, `trialbox restore` (the real `pg_dump` and `pg_restore`), search, tick, search | yes |
| The tool on fakes | `tests/unit/test_erasure_reach_tool.py`: files of each kind, the FHIR store's answers (gone, there, down), live mode with nothing set, no value printed, the owed table against the registry and this page | yes |
| The FHIR store (HAPI), the backups on the NAS, a practice space's OMOP store and lake | `python -m tools.erasure_reach live --marker m.json` on a compose box | **not run**: compose only. No attempt was made to stand the compose stack up for this card |
| The vector store | needs pgvector; the unit cluster here offers none | **not searched** (`vec.note_chunk`, `vec.embedding`) |
| The lake's `site`, `fhir_ledger`, `backfill`, `ndjson-rerun`, `tmp` and `holds` | the unit ingest makes none of them (no set-up publish, no FHIR load, no back-fill, no re-run) | **not searched** |

The three files take 31 seconds together on this machine (the module box takes 18 of them).

The values searched for are the pseudonym, its first 16 characters (a per-patient file's name carries them), the
recall hash of the pseudonym, the chart number, a national-ID-shaped number, the name, the phone, the date of birth
and the OMOP person id. All are invented. The national-ID shape has no valid second digit.

How each store was seeded is in `reach.json` (`seeded_by`). The ingest, the OMOP load, the job queue, the twin, the
recall ledger, the trace store, the mail outbox and the object store were written by their own code. Every other
table with a `pid` or `pid_hash` column got one planted row: 19 rows went in (`planted`), and `sitesetup.input`
got one row with its file in the set-up folder. A kept store got none,
because a planted row in the register or its copies would steer the opt-out. `derived.score_row` and
`derived.conflict` refused the planted row (a check and a foreign key) and were not seeded.

A store is **seeded** when the search found the marker there before the opt-out. Only a seeded store's absence after
the tick means anything. The 190 stores the marker never reached are counted below, not listed; their test cases
are skipped as "not seeded". Every count on this page comes from `erasure-reach-2026-11-17/reach.json`, which the
module writes when `TB_REACH_OUT` names a folder, or from the owed table the tool generates.

## The result per store

`reach.json` holds 251 stores: the registry's 245 entries and 6 the walk found that the registry does not list.
Verdicts: 31 clean, 5 kept, 12 owed, 0 leak, 190 not seeded, 13 not searched; no unlisted store held the patient.
`clean`: seeded and gone. `kept`: still there, and the registry keeps it with a decision. `owed`: still there, and
the registry owes it. `leak`: still there, and the registry says erased or no patient data. `unlisted`: a store the
registry does not know.

The table below is printed by `python -m tools.erasure_reach table erasure-reach-2026-11-17/reach.json`.

**The mail outbox** (3 stores: clean 1, not_seeded 2)

| Store | Registry | Searched | Seeded | Found after | Values found | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| `mail.intake` | no_patient_data | yes | no | no | - | not_seeded |
| `mail.send_keys` | owed | yes | yes | no | - | clean |
| `mail.sent` | no_patient_data | yes | no | no | - | not_seeded |

**Logs** (1 stores: not_seeded 1)

| Store | Registry | Searched | Seeded | Found after | Values found | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| `logs:captured` | unlisted | yes | no | no | - | not_seeded |

**Traces** (2 stores: not_seeded 1, owed 1)

| Store | Registry | Searched | Seeded | Found after | Values found | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| `trace.access_log` | no_patient_data | yes | no | no | - | not_seeded |
| `trace.traces` | owed | yes | yes | yes | name, pid, pid_prefix | owed |

**Lake files** (20 stores: not_searched 7, not_seeded 10, owed 3)

| Store | Registry | Searched | Seeded | Found after | Values found | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| `lake:.rebuild.lock` | no_patient_data | yes | no | no | - | not_seeded |
| `lake:CURRENT` | no_patient_data | yes | no | no | - | not_seeded |
| `lake:CURRENT.tmp` | no_patient_data | no | no | no | - | not_searched |
| `lake:FEED` | no_patient_data | yes | no | no | - | not_seeded |
| `lake:audit` | unlisted | yes | no | no | - | not_seeded |
| `lake:backfill` | owed | no | no | no | - | not_searched |
| `lake:db` | owed | yes | yes | yes | chart, dob, name, phone, pid, pid_prefix | owed |
| `lake:embed_cache.duckdb` | owed | yes | no | no | - | not_seeded |
| `lake:fhir_ledger` | owed | no | no | no | - | not_searched |
| `lake:gates` | unlisted | yes | no | no | - | not_seeded |
| `lake:holds` | no_patient_data | no | no | no | - | not_searched |
| `lake:locks` | no_patient_data | yes | no | no | - | not_seeded |
| `lake:ndjson` | owed | yes | yes | yes | dob, pid, pid_prefix | owed |
| `lake:ndjson-rerun` | owed | no | no | no | - | not_searched |
| `lake:night_runs.json` | unlisted | yes | no | no | - | not_seeded |
| `lake:parquet` | owed | yes | yes | yes | chart, dob, name, phone, pid, pid_prefix | owed |
| `lake:site` | owed | no | no | no | - | not_searched |
| `lake:site_key.json` | unlisted | yes | no | no | - | not_seeded |
| `lake:source.jsonl` | unlisted | yes | no | no | - | not_seeded |
| `lake:tmp` | owed | no | no | no | - | not_searched |

**Object store** (3 stores: not_searched 1, owed 2)

| Store | Registry | Searched | Seeded | Found after | Values found | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| `objects:attachments` | owed | yes | yes | yes | pid, pid_prefix | owed |
| `objects:ctgov` | no_patient_data | no | no | no | - | not_searched |
| `objects:outputs` | owed | yes | yes | yes | pid, pid_prefix | owed |

**Outside the database and folders** (4 stores: not_searched 3, not_seeded 1)

| Store | Registry | Searched | Seeded | Found after | Values found | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| `outside:audit` | keep | yes | no | no | - | not_seeded |
| `outside:backups` | owed | no | no | no | - | not_searched |
| `outside:fhir_store` | owed | no | no | no | - | not_searched |
| `outside:sitesetup_space_omop` | owed | no | no | no | - | not_searched |

**Database tables** (218 stores: clean 30, kept 5, not_searched 2, not_seeded 175, owed 6)

| Store | Registry | Searched | Seeded | Found after | Values found | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| `datacore.subject` | erase | yes | yes | no | - | clean |
| `edc.draft` | owed | yes | yes | yes | pid, pid_prefix | owed |
| `omop.condition_occurrence` | erase | yes | yes | no | - | clean |
| `omop.condition_occurrence_y2026` | erase | yes | yes | no | - | clean |
| `omop.note` | erase | yes | yes | no | - | clean |
| `omop.note_y2026` | erase | yes | yes | no | - | clean |
| `omop.observation_period` | erase | yes | yes | no | - | clean |
| `omop.person` | erase | yes | yes | no | - | clean |
| `omop.tb_id_map` | keep | yes | yes | yes | pid, pid_prefix | kept |
| `omop.tb_record` | keep | yes | yes | yes | dob, person_id, pid, pid_prefix | kept |
| `omop.tb_record_event` | owed | yes | no | yes | chart, dob, name, phone, pid, pid_prefix | owed |
| `omop.tb_withheld` | keep | yes | no | yes | pid, pid_prefix | kept |
| `omop.visit_occurrence` | erase | yes | yes | no | - | clean |
| `omop.visit_occurrence_y2026` | erase | yes | yes | no | - | clean |
| `optout.optout_events` | keep | yes | no | yes | pid, pid_prefix | kept |
| `orch.candidate_events` | erase | yes | yes | no | - | clean |
| `orch.candidates` | erase | yes | yes | no | - | clean |
| `orch.feedback` | erase | yes | yes | no | - | clean |
| `orch.jobs` | owed | yes | yes | yes | pid, pid_prefix | owed |
| `orch.judged_pairs` | erase | yes | yes | no | - | clean |
| `orch.pool` | erase | yes | yes | no | - | clean |
| `orch.submissions` | erase | yes | yes | no | - | clean |
| `pidmap.identity` | owed | yes | yes | yes | pid, pid_prefix | owed |
| `pidmap.pending` | erase | yes | yes | no | - | clean |
| `pidmap.pid_map` | keep | yes | yes | yes | pid, pid_prefix | kept |
| `profile.tb_patient_profile` | erase | yes | yes | no | - | clean |
| `recall.recall_known_positive` | owed | yes | yes | yes | pid_hash | owed |
| `recall.recall_observation` | owed | yes | yes | yes | pid_hash | owed |
| `site.contact_outcomes` | erase | yes | yes | no | - | clean |
| `site.excluded_review` | erase | yes | yes | no | - | clean |
| `site.pi_marks` | erase | yes | yes | no | - | clean |
| `site.screening_no` | erase | yes | yes | no | - | clean |
| `site.weekly_seen` | erase | yes | yes | no | - | clean |
| `sitesetup.fact` | erase | yes | yes | no | - | clean |
| `sitesetup.input` | owed | yes | yes | no | - | clean |
| `study.rc_record` | erase | yes | yes | no | - | clean |
| `team.approach_overrides` | erase | yes | yes | no | - | clean |
| `team.candidate_views` | erase | yes | yes | no | - | clean |
| `team.referral_events` | erase | yes | yes | no | - | clean |
| `team.referrals` | erase | yes | yes | no | - | clean |
| `tuned.tuned_patients` | erase | yes | yes | no | - | clean |
| `vec.embedding` | erase | no | no | no | - | not_searched |
| `vec.note_chunk` | erase | no | no | no | - | not_searched |

What the groups say:

- **The mail outbox.** A held mail that carried the patient's own file was dropped by the worker (`mail.send_keys`
  clean). A held mail of a list stays, and its row names no patient (only the file's key). `mail.sent` and
  `mail.intake` hold subjects and senders; the marker never reached them.
- **Logs.** The run wrote 2 log records, and neither held a marker value. Reading the logging code found two lines
  that write a pseudonym when a step fails: `libs/tb_common/derived_store.py:731` and
  `services/patient_profile/twin.py:440`. The box's JSON formatter (`libs/tb_common/logging.py:132`) scrubs chart
  numbers and phones but keeps a pseudonym. The box keeps each service's log (json-file, 10 files of 100 MB,
  `deploy/docker-compose.yml:13`), and nothing on the opt-out reaches it. Shown by
  `test_no_log_line_names_an_opted_out_patient` (V1-09).
- **Traces.** `trace.traces` kept the model call's body, with the pseudonym and the name, after the tick (owed;
  the store prunes after 7 days).
- **Lake files.** The kept snapshot (`db/`, its generation copy `db/gen/` and its reader copy `db/.open/`), the
  Parquet copy and the NDJSON keep the patient (owed, D-513: withheld on read until retention). The snapshot's
  `document` table keeps the note as the hospital wrote it, by design (`services/lake/store.py:1439`), so the name,
  chart number and phone of the note stay with it. Five top-level entries are not in the registry: `gates`,
  `night_runs.json`, `site_key.json`, `source.jsonl`, and `audit` (the test's own audit folder for the ingest). None
  held a marker value.
- **Database tables.** Every table with a clear that the marker reached was clean. OMOP's yearly partitions
  (`omop.note_y2026` and the like) are made by the loader at run time; the registry names their parents, and the
  tool reads them as their parent's.

## The restore

`test_erasure_reach_restore.py`, on the stores it seeds (the pool, the candidate registry, OMOP and the twin):

1. Before the restore, the tick had cleared all four.
2. The restore put the opt-out typed after the backup back into the register (`optouts_after_backup`: counted,
   1 kept, 0 not kept). The register then holds the patient. Nothing of the patient is in the restore's answer.
3. The restored databases hold the patient again in all four stores. The restore does not run the clears.
4. The restore was complete, so it took its own hold off (`hold: released`, D-522) before any tick. The test runs as
   DEV, where the service-role step counts as done; on a real box that step is configured.
5. The next worker tick cleared all four again. The orchestrator runs a tick when it starts
   (`services/datacore/optout_worker.py:860`).

So "a restore re-applies the opt-out list" holds for the register, not for the stores. Between the restore and the
first tick, what keeps the patient off a list is each reader's own register check (D-441, D-860); the hold of
D-522 applies only when the restore is not complete. That window is V1-10. What needs the compose box: the order in
which the services start after a restore, and whether a list job can run before the orchestrator's first tick.

## The owed list, costed

Generated by `python -m tools.erasure_reach owed` from `tb_common.erasure.owed()`. The tool fails, and
`tests/unit/test_erasure_reach_tool.py` with it, when the registry's owed set and the costed table differ, or when
this page's table is not what the tool prints. "What closing it takes" and the size are read from the stores' code:
a hypothesis, not a measured cost. The backups count as outside the box, because criterion 8 asks for them a
written age-out rule instead.

<!-- erasure-reach owed table: generated by python -m tools.erasure_reach owed; do not edit -->

26 owed entries; 25 inside the box (criterion 8 counts these), 1 outside.

| Store | Inside | What closing it takes | Held open by | Lane | Size |
| --- | --- | --- | --- | --- | --- |
| `edc.draft` | yes | The owner rules whether a draft alone makes a trial subject; then the screening-log clear tokens or deletes a never-consented patient's drafts | D-1032 (open question of D-878) | E | medium |
| `lake:backfill` | yes | Drop the back-fill's working copy when the back-fill ends, and let the worker drop the patient's lines from one that is left | - | B2 | small |
| `lake:db` | yes | Rewrite each kept DuckDB snapshot without the patient (or the owner reverses D-513); close the two whole-lake readers of D-862 | D-513, D-860, D-862 | B2 | large |
| `lake:embed_cache.duckdb` | yes | Prune the patient's vectors across every kept snapshot, and keep the nightly build from embedding them again | D-513 (a rebuild is ruled), D-862 | B2 | medium |
| `lake:fhir_ledger` | yes | Delete the patient's ledger rows in the same step that erases the FHIR store's resources | - | B2 | small |
| `lake:ndjson` | yes | Rewrite the kept nightly and month-end NDJSON extracts without the patient's lines (or the owner reverses D-513) | D-513, D-860 | B2 | large |
| `lake:ndjson-rerun` | yes | The same rewrite as lake:ndjson, for a re-run folder | D-513, D-860 | B2 | small |
| `lake:parquet` | yes | Rewrite each snapshot's Parquet copy without the patient, with lake:db | D-513, D-860 | B2 | large |
| `lake:site` | yes | Delete the patient's lines from the site set-up's published NDJSON and publish again | - | B2, C2 | small |
| `lake:tmp` | yes | Sweep the ingest and rebuild scratch at the start of each run and on the worker's tick | - | B2 | small |
| `mail.send_keys` | yes | A person resolves an uncertain mail and a held mail of lists; the outbox page shows them as owed to a person | D-863, D-874 | C2 | small |
| `objects:attachments` | yes | Delete a patient's own attached file (a chart) at the opt-out; a list until retention | D-513 | B2 | medium |
| `objects:outputs` | yes | Delete per-patient files at the opt-out; rewrite lists or accept retention (owner) | D-513, D-860 | B2 | large |
| `omop.tb_conflict` | yes | Blank a withheld person's conflicts at retention with the before-images | D-867 | B2 | small |
| `omop.tb_record_event` | yes | Nothing to build: blanked at retention. Owed only inside the retention window, which D-1031 rules | D-1031 | B2 | small |
| `orch.jobs` | yes | Blank the pseudonym in a finished job's request (CASE, a reveal) at the opt-out | - | B2 | small |
| `outside:backups` | no | A written age-out rule (backups older than N nights are deleted) and a restore that re-applies the register before any service reads | - | D | medium |
| `outside:fhir_store` | yes | Delete and expunge the patient's resources in HAPI at the opt-out, then the ledger | - | B2 | large |
| `outside:sitesetup_space_omop` | yes | Run the omop clear and a lake clear in each practice space's own stores | D-714 (Reset drops the space) | C2, B2 | medium |
| `pidmap.identity` | yes | Crypto-shred: delete the patient's identity row at the opt-out (the chart number stays in pid_map for the door) | - | B2 | small |
| `recall.recall_known_positive` | yes | Replace pid_hash and draw_id by a token, and keep the certificate from adding the patient again | the review of D-866 | A2 | medium |
| `recall.recall_observation` | yes | Replace pid_hash by a token (the observation's count stays) | - | A2 | small |
| `sitesetup.check_item` | yes | Find and delete a sheet's rows of the patient (the raw values name the chart) | D-869 | C2 | medium |
| `sitesetup.fix` | yes | Delete example values of a sheet's column that name the patient | D-869 | C2 | small |
| `sitesetup.input` | yes | Delete or rewrite a sheet of many patients that names the patient (its file and rows) | D-869 | C2 | medium |
| `trace.traces` | yes | Tag each trace with its patient and delete the patient's traces at the opt-out (or rely on the 7-day prune) | - | B2, A2 | small |

<!-- end of the generated owed table -->

## Findings

| Id | Place (master `d7c91fc3`; the same lines at `3f6a02ec`) | Expected (where it is written) | What happened | Severity | Lane | Basis |
| --- | --- | --- | --- | --- | --- | --- |
| V1-01 | `libs/tb_common/erasure.py:581` (`owed()`) | No owed entry for a store inside the box (plan 8 §3, criterion 8) | 26 owed, 25 inside the box | High | B2 (C2, A2, E, D for their rows) | shown: `test_criterion_8_no_owed_entry_for_a_store_inside_the_box` |
| V1-02 | `libs/tb_common/erasure.py:517` (`LAKE`) | The pseudonym in no store or snapshot (criterion 8) | After the tick the lake's snapshot, its generation and reader copies, the Parquet copy and the NDJSON hold the pseudonym and the date of birth; the snapshot and Parquet also the name, chart number and phone from the note | High | B2 | shown: the `lake:db`, `lake:parquet`, `lake:ndjson` cases |
| V1-03 | `libs/tb_common/erasure.py:467` | The same | `omop.tb_record_event` keeps the before-images of the tombstoned records, the note with its name, chart number and phone among them (kept hidden until retention, D-1031) | High | B2 | shown: the `omop.tb_record_event` case |
| V1-04 | `libs/tb_common/erasure.py:542` | The same | A job's list, a per-patient file and an attached chart of the patient stay in the object store (D-513) | High | B2 | shown: the `objects:outputs`, `objects:attachments` cases |
| V1-05 | `libs/tb_common/erasure.py:295` | The same | `trace.traces` keeps a model call's body with the pseudonym and the name | High | B2, A2 | shown: the `trace.traces` case |
| V1-06 | `libs/tb_common/erasure.py:293` | The identity's crypto-shred (review J-2) | `pidmap.identity` keeps the patient's encrypted identity row | High | B2 | shown: the `pidmap.identity` case |
| V1-07 | `libs/tb_common/erasure.py:186` | The same as V1-02 | `recall.recall_known_positive` and `recall.recall_observation` keep the unsalted recall hash of the pseudonym | High | A2 | shown: the two `recall.*` cases |
| V1-08 | `libs/tb_common/erasure.py:227`, `:383` | The same | A CASE job's request (`orch.jobs`) and an EDC draft (`edc.draft`) keep the pseudonym | High | B2, E | shown: the `orch.jobs`, `edc.draft` cases |
| V1-09 | `libs/tb_common/derived_store.py:731`, `services/patient_profile/twin.py:440`, `libs/tb_common/logging.py:132` | No log line names a patient (`derived_store.py:730`: "no values in the log"); nothing of an opted-out patient stays | A failed recompute logs the pseudonym; the JSON formatter keeps it; the box keeps its logs and the registry has no entry for them | High | B2 | shown: `test_no_log_line_names_an_opted_out_patient` (the derive line); the twin line is read from code |
| V1-10 | `tools/trialbox/backup.py:2367` and `:2372` | "A restore re-applies the opt-out list" (review J-2; plan 8 §5a, V7) | The register is re-applied; the restored stores hold the patient until the worker's next tick, and a complete restore releases its hold before that tick | Medium | D, B2 | shown: `test_after_the_restore_no_store_holds_the_opted_out_patient` |
| V1-11 | `tests/unit/test_erasure_registry.py:77` (`_LAKE_PATH`) | Every store has one registry entry (D-465) | The walk found 4 top-level lake entries the registry does not list: `gates`, `night_runs.json`, `site_key.json`, `source.jsonl`. None held the patient | Low | B2 | shown: `reach.json` (registry `unlisted`) |
| V1-12 | `libs/tb_common/erasure.py:558` to `:566` | A test finds the pseudonym in no FHIR resource (criterion 8) | The FHIR store, the backups, a practice space's stores and the vector store were not searched; the claim is unproven there. The live mode that would search them was not run | Medium | D, B2 | not_run |

The same findings are in `erasure-reach-2026-11-17/findings.json`.

## The tests, and which are xfail

- `test_the_opted_out_patient_is_not_in_the_store[<store>]`: one case per store. 12 are `xfail(strict=True)` with
  their finding (V1-02 to V1-08). A fix that clears a store turns its case red until its line in `KNOWN_LEFT` goes.
- `test_criterion_8_no_owed_entry_for_a_store_inside_the_box`: strict xfail, V1-01.
- `test_no_log_line_names_an_opted_out_patient`: strict xfail, V1-09.
- `test_after_the_restore_no_store_holds_the_opted_out_patient`: strict xfail, V1-10.
- Plain tests: the search sees the control patient; the tick reports no failure; no unlisted or "erased" store holds
  the patient unseen; the restore keeps the opt-out and the next tick clears; the tool's own tests.

## Wiring

The three files are ordinary unit test files. CI's unit shards choose a file by a hash of its path
(`tools/test_shard.py`): `test_erasure_reach.py` and `test_erasure_reach_tool.py` fall in shard 3 of 6,
`test_erasure_reach_restore.py` in shard 6. The tool's file is marked `nodb`. No CI job was added. "The test in a
required job" (plan 8, V7) would take: the unit shards made required on the pull request; or a small job of its own
for these three files (about 35 seconds) made required, plus a nightly step that runs the live mode against the
compose box with a seeded marker patient, which needs the compose walk of V12 to seed one through the box's own
doors.
