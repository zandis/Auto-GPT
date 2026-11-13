# Deep review 2026-11-13: the data layer

| Field | Value |
| --- | --- |
| Area | Every store, its schema and migrations; transactions and concurrency; idempotency and the outbox; data input; harmonisation and the OMOP view; conflicts and provenance; derived data; backup and restore; erasure; disk at scale; query plans; contracts and goldens |
| Slug | `data` |
| Code read | `master` at `c7dcd5e7` (train 8); the open pull requests by their diffs where they touch the data layer |
| Ordered by | the owner, through lane G (`session_013CtyYQZ6yK86d9MUZJtkSY`) |
| Method | One lead and four reviewers in parallel (backup and restore; erasure, derived data and provenance; input, transactions and the OMOP load; scale, plans and contracts), each running the real code against a throwaway PostgreSQL 16, then one adversarial reviewer on the fixes and the top findings |
| Rules kept | Synthetic data only. No secret read. Nothing that costs money. No IRB or sign-off step. No decision number taken (D-TBD). No file of an open pull request edited. |

## 1. Terms

| Term | Meaning here |
| --- | --- |
| Group role | `tbs_<schema>`: the role a store's connection switches to on a box (D-378, `SET ROLE`). It has rights on its own schema only. |
| Session role | the role a service logs in as (`tb_orchestrator`, `tb_console`, ...). Its list of schemas is in `deploy/docker/db-init/30-service-roles.sh`. |
| Roles cluster | a test cluster set up by the real role script (`tests/unit/test_db_roles.py`, fixture `roles_cluster`). Ordinary unit tests run as a superuser and cannot see role defects. |
| Base cohort | the `base` step of every compiled ruleset (`compile_sql/generator.py`): who is alive and born at each index date. |
| Delta night | a night that reads only the rows changed since the last good night and merges them over that night's snapshot. |
| Verified | reproduced by a command or a test on this tree; the output is quoted. **Inferred** means read in the code and not run. |

## 2. The reading in ten lines

1. **The opt-out did not work on a real box.** On a cluster with the real roles, the opt-out worker failed every tick
   before it cleared anything. This was the "permission denied for schema omop" line in the nightly log. The
   merged-chart rule was quietly off too. **Fixed here** (DATA-001, DATA-002).
2. The cause is one pattern: a check on another schema made through a connection that runs as this schema's group
   role. The unit tests run as a superuser, so they never saw it. Only a test on the roles cluster can.
3. **Who is excluded:** a disputed death date excluded the patient at every date. **Fixed here** (DATA-004).
   A chart merge is not applied to records a delta night carries over (DATA-006). A steward's rejection of a
   record is undone by any later change to the source record (DATA-007).
4. **Input:** a CSV cut off mid-row passed the night, and the cut value became the newest lab result in OMOP.
   **Fixed here** (DATA-005).
5. **The nightly backup's "1 changed" error** came from hard links in the site set-up's work lake. NEW-B-17 (#449)
   fixed it on master after the handover was written. Tonight's run is the first with the fix.
6. **Backup on a busy night:** the audit head is copied after the day file. One event written during the read gives
   a backup whose restore fails half-way, after the databases are replaced (DATA-009).
7. **Restore** drops file owners and does not stop the services (DATA-010, DATA-011).
8. **Derived rows** of patients who left the feed or opted out are kept and served (DATA-008, the old CR-119).
9. Closed items are mostly closed in code: CR-053, CR-056, CR-057, CR-085, DI-12. DI-11 stays open by design.
10. SCALE: see section 5.

## 3. Findings

Severity: **Critical** = a patient wrongly excluded or included, data lost, patient data or a secret exposed, or
who-may-act broken. Owner lanes as in the handover (`35-handover-2026-11-13.md` §2).

| Id | Severity | Finding | State | Owner |
| --- | --- | --- | --- | --- |
| DATA-001 | Critical | The opt-out worker clears nothing on a box | **fixed here** | C2 |
| DATA-002 | Critical | The merged-chart opt-out is off on every box, failing open | **fixed here** | C2 |
| DATA-003 | Medium | The first-run page can never see an empty pid map | **fixed here** | C2 |
| DATA-004 | Critical | A disputed death date excludes the patient at every date | **fixed here** | B2 |
| DATA-005 | Critical | A CSV cut off mid-row passes, and the cut value becomes the newest lab | **fixed here** | E |
| DATA-006 | Critical | A chart merge is not applied to what a delta night carries over | open | B2 |
| DATA-007 | High | A steward's decision on an OMOP record is undone by a later source change | open (file held by #493) | B2 |
| DATA-008 | High | Derived rows are never retired; they are rebuilt for opted-out patients | open | B2 with C2 |
| DATA-009 | High | The audit head is backed up after the day file: a busy night gives a backup that cannot be restored | open (file held by #473) | D |
| DATA-010 | High | Restore drops file owners; services cannot write their volumes after it | open (file held by #473) | D |
| DATA-011 | High | Restore does not require the services to be stopped | open (file held by #473) | D |
| DATA-012 | High | Backup size and time at 50,000 and 500,000 patients do not fit a night | open (PERF-010, PERF-011) | B2 and D |
| DATA-013 | Medium | The default lake drops source conflicts with no record | open | B2 |
| DATA-014 | Medium | The audit says opt-out events carry counts only; two console events carry the pid | open; owner's decision | C2 |
| DATA-015 | Medium | An SMTP refusal of some recipients is recorded as delivered to all | open | C2 |
| DATA-016 | Medium | Codes mapped to concept 0 are not counted in the OMOP load report | open (file held by #493) | E |
| DATA-017 | Medium | The site set-up's work lake is backed up without the lake rules | open (file held by #473) | D |
| DATA-018 | Medium | Restore and verify unpack the whole box on `/tmp`, with no free-space check | open (file held by #473) | D |
| DATA-019 | Low | A job claimed but not yet leased can be taken by a second orchestrator | open | B2 |
| DATA-020 | Low | The FHIR build lock is a session lock on a connection that reconnects | open | B2 |
| DATA-021 | Low | A restore can lift its own hold while the reference pack is missing | open (file held by #473) | D |
| DATA-022 | Low | PR #278 (T-206b, erasure) holds no code and predates the erasure registry | open | C2 |
| DATA-023 | Low | The roles test cluster made first in a fresh test root breaks the rest of the run | open | C2 |

### DATA-001 (Critical, fixed): the opt-out worker clears nothing on a box

- **Symptom.** Every tick of the worker fails before any store is cleared, even the step that copies the hospital's
  refusals into the register. The health line turns red; nobody's records are withheld. This is the line
  "permission denied for schema omop" from the nightly compose log (handover §3).
- **Evidence (verified).** On the roles cluster, connected as `tb_orchestrator`:
  `current_user of the register connection: tbs_optout`; a raw `tb_orchestrator` connection reads
  `to_regclass('omop.probe')` fine; through the register's connection
  `_omop_store RAISED: InsufficientPrivilege permission denied for schema omop`, and the same for `vec`, `pidmap`
  and `profile`; `tick -> None | STATUS failed: ['tick'] | pool_remove calls: 0`.
- **Root cause.** Not the role list and not the order of schema creation: the script makes every schema first
  (`30-service-roles.sh:100`). `Database._open` (`libs/tb_common/db.py:323-327`) switches the register's connection
  to `tbs_optout`. `optout_worker.py:176` and `:306` then ask `to_regclass('"omop".…')` on that connection.
  PostgreSQL checks USAGE on the schema even there, and `tbs_optout` has none. `_omop_store` sits inside the tick's
  one `try` (`optout_worker.py:341`), so the whole tick stops.
- **Fix (this branch).** `Database.table_exists(schema, table)` reads `pg_class` and `pg_namespace`, which every
  role may read. The worker uses it. Test: `tests/unit/test_cross_schema_roles.py` on the roles cluster; four
  tests fail before and pass after.
- **Still to do (C2).** Open the OMOP store inside `run_once`'s per-store `try`, so one store cannot stop the others.

### DATA-002 (Critical, fixed): the merged-chart opt-out is off on every box

- **Symptom.** An opt-out typed under a chart number that was later merged does not hide the surviving pseudonym.
  This affects screening (`opted_out`), the twin build and the OMOP export. It fails open and logs nothing.
- **Evidence (verified).** Same run: with `pid_alias OLDPID0001 → NEWPID0001`,
  `effective (with survivors): ['OLDPID0001']`, even when connected as `trialbox`.
- **Root cause.** `with_survivors` (`libs/tb_common/optout.py:106-112`) asked `has_schema_privilege(n.oid, 'USAGE')`
  as `current_user`, which is `tbs_optout`, so the answer was false and the merge map was skipped.
- **Fix (this branch).** Existence from the catalogue; the right from `session_user` (the service that logged in),
  which is what `Database.connect(url, "pidmap")` will use. Test: as above, for `tb_orchestrator` and `tb_console`.

### DATA-003 (Medium, fixed): the first-run page can never see an empty pid map

- **Symptom.** `box_holds_patients` (`services/console/firstrun.py`) read `pidmap` through the console's `auth`
  connection (group `tbs_auth`). On a box that was refused, the function returned None, and the page treats None as
  "the box holds patients": the chart-number rule could never be chosen on a new box.
- **Fix (this branch).** The catalogue says which tables exist; the map is read on its own connection.

### DATA-004 (Critical, fixed): a disputed death date excludes the patient at every date

- **Symptom.** When two sources agree that a patient died but give different dates, the patient leaves the base
  cohort at every index date, even dates before both claimed deaths.
- **Evidence (verified).** `merge_patients([hospital 2026-10-01, site 2026-10-05])` gave
  `deceased_date None, deceased True`. The base clause (`compile_sql/generator.py:608-609`) at index date
  2026-06-30 returned no row. The OMOP export (`services/omop/export.py`, an open conflict sets the date to None and
  keeps `deceased`) did the same.
- **Root cause.** "Date unknown" plus "died" reads as "died at an unknown time", which the base excludes at every
  date. D-275 says an unknown never excludes.
- **Fix (this branch).** Both lakes keep the **latest** claimed date. The patient is then out only at index dates
  where every source says they had died; between the dates the sources disagree, and the patient stays in. The
  conflict stays open for the steward. Test: `tests/unit/test_death_date_conflict.py` (both lakes; fails before).

### DATA-005 (Critical, fixed): a CSV cut off mid-row passes the night

- **Symptom.** The last line of `lab.csv` was `L2,20000001,HBA1C,HbA1c,6`: the export stopped while writing
  `6.8,%,2026-09-01 ...`. The night passed. The lake held an undated HbA1c of 6 with the mapping's default unit.
  The OMOP load dates a required date it lacks with the load night (`omop/load.py:893-897`, flagged `imputed`), so
  the cut value became the newest HbA1c and flipped "latest HbA1c ≥ 7".
- **Evidence (verified).** `passed True held False errors []`; OMOP measurement rows `(9.1, 2026-08-01)` and
  `(6.0, 2026-10-01)`.
- **Root cause.** `sources/csv/source.py` read rows with `csv.DictReader`, which fills a short row with None and puts
  a long row's extra cells under a None key; nothing checked the width.
- **Fix (this branch).** The pre-pass that already parses the whole file quarantines it when a row's field count
  differs from the header; the night is held, as for an unreadable file (T-615b). Test:
  `tests/unit/test_csv_short_row.py` (short row, long row, the held night; fails before).
- **Still to do (E).** The OMOP load should not impute a date for a measurement or observation that criteria read by
  date; such a row should stay undated.

### DATA-006 (Critical, open): a chart merge is not applied to what a delta night carries over

- **Symptom.** The night after `pid-merge A→B`, a delta night passes clean, but the snapshot still holds patient A
  and A's diagnoses stay under `Patient/A`. Screening on B misses A's history (an exclusion diagnosis); the patient
  counts twice. OMOP, which loads the whole snapshot, does the same. It lasts until the next full night.
- **Evidence (verified).** `passed True errors []`;
  `patients ['0dfe53…'(A), '9e043e…'(B)]`; `conditions {'C50.9': 'Patient/0dfe53…'(A), 'E11.9': 'Patient/9e043e…'}`.
- **Root cause.** `ndjson.write_snapshot` runs the alias pass only on tonight's records (`adapter/ndjson.py:224-226`);
  the base records are copied unchanged. `pipeline.py:748-761` loads the aliases only when tonight has patient rows.
- **Fix.** Apply the alias map to the base records in `_write_type` (drop the old pid's Patient, rewrite references);
  load the aliases always. Or make the next night a full read whenever a merge is newer than the merge base.
  `pipeline.py` is held by #483 and #487: lane B2 after they land.

### DATA-007 (High, open): a steward's decision on a record is undone by a later source change

- **Evidence (verified).** `set_status(c1, 'rejected')`; an unchanged reload keeps `rejected`; a reload where only
  `recordedDate` changed gives `coded`. The rejected diagnosis counts again.
- **Root cause.** `omop/load.py` `_write` (about line 1079): on `update` and `restore` the status is the batch's;
  only `same` keeps the old one. A vocabulary load changes concept ids and so every content hash: it would reset
  every person-set status in one night (inferred).
- **Fix.** Carry a person-set status across `update`; reopen it for review only when the coded fact (code or date)
  changed; keep concept ids out of the content hash. `omop/load.py` is held by #493.

### DATA-008 (High, open): derived rows are never retired (CR-119 still holds, and goes further)

- **Evidence (verified).** Night 1: P_A and P_B, 4 rows. Night 2: P_B gone from the lake and P_A opted out:
  `inserted=0, unchanged=2, retired=0`. P_B's rows stay current and `latest_many(as_of=night 2)` returns its value
  with the pid, age and sex in `inputs`. A rebuild of one snapshot is deterministic, but the store built night by
  night is not equal to a rebuild of the last night.
- **Root cause.** `derived_store.py:700-733` looks only at patients in the snapshot; `orchestrator/derive.py:146`
  passes no exclusion; `erasure.CLEARS` has no `derived` entry.
- **Fix.** Supersede the current rows of every pid not in the snapshot; skip the register's patients; add a
  `derived` clear (score rows, input links, conflicts, the failed-pid list).

### DATA-009 (High, open): a busy night gives a backup that cannot be restored

- **Evidence (verified).** The backup copies `2026-11-14.jsonl` before `HEAD.json` (`_walk` order), and takes the day
  file only up to the line it had when the read began (`backup.py:635-713`). One `AuditLog.append` in between: the
  copy's `verify()` says "the chain ends at event 1, the head anchor says event 2". `restore` then raises
  `AuditAnchorBroken` at `backup.py:1712`, which is not a `BackupError`, after the databases, the folders and the
  `.pre-restore-*` copies are in place. No `restore_failed` event is written. The restored box's audit refuses every
  write. The drill cannot see this: its box is idle while it backs up.
- **Fix.** Copy `HEAD.json` before the day files (or rebuild it from the copied chain); turn audit failures at restore
  into the `restore_failed` path. `tools/trialbox/backup.py` is held by #473 (lane D): put it on that card or the
  next.

### DATA-010, DATA-011 (High, open): restore and the running box

- **DATA-010 (ownership verified; box impact inferred).** A restore run as root of a 10001-owned 0600 file gives
  `restored owner: 0 0`. `shutil.copytree` and `mkdir` (`backup.py:1669-1672`) keep no owner; the runbook has no
  `chown`. Services that run as uid 10001 cannot write their volumes after a restore.
- **DATA-011 (inferred).** `restore()` and RUNBOOK §5/§22 never stop the services or check they are stopped. The
  restore renames each volume's `_data` aside; running containers keep writing the renamed copy, and those writes are
  lost. Fix: refuse unless only `db` runs, or stop the services in `restore`.

### DATA-012 (High, open): backup size and time at scale

Measured here: about 220 MB/s for backup and 400 MB/s for verify on 1 GiB of synthetic files. Every lake snapshot is
copied each night, the dump is a full uncompressed one, every row is hashed, and nothing is incremental. At the
30–50 MB/s of D-455 that is 1–2.5 hours a night at 50,000 patients (100–430 GB) and 6–22 hours at 500,000. The
fixes are PERF-010 and PERF-011 (an incremental lake; pgBackRest as the nightly).

### DATA-013 to DATA-023 (Medium and Low)

| Id | Evidence | Fix |
| --- | --- | --- |
| DATA-013 | `lake/flatten.py:850-871` sets a disagreeing field to None and keeps the first row's provenance; nothing in `tb_conflict`, no count, nothing for the steward. Only the OMOP loader records claims. (Inferred; the merge itself was run.) | Count conflicts in the batch until OMOP is the lake source. |
| DATA-014 | `erasure.py:405-409` says the opt-out's events "carry counts only, never who"; `console/team.py:1101` writes `console.opt_out` with the pid, and `:1090` writes `console.chart_lookup` with it. The audit is kept 10 years or for ever. (Inferred.) | Correct the registry text, then a decision (D-TBD): keep the pid, or log a keyed hash. The owner decides. |
| DATA-015 | `mail_gateway/outbound.py:90-96` raises only when every recipient was refused, then drops the refused list; `mail.sent` names every recipient. (Inferred.) | Return the refused set; fill `SendResult.rejected`; keep the refused recipients as a key of their own. |
| DATA-016 | `test_in_omop.py`: report `skipped {}` while 2 condition rows have `condition_concept_id=0`. (Verified.) | Count `concept_zero:<table>` in the load report and the night's audit event. |
| DATA-017 | One 1.2 MB file of `orch/sitesetup/<site>/lake` stored 3 times; `tmp/spill.bin` and `*.building` taken too. (Verified.) | Apply the lake rules to every `*/lake` root. |
| DATA-018 | `unpack` extracts every dump and folder into `/tmp` (`backup.py:1104`, `:1482`), then copies; a restore needs 3–4 times the box free, in RAM if `/tmp` is tmpfs. (Inferred and measured.) | Work on the data disk with a size check; move, not copy; verify by hashing the stream (#473's `_StreamCheck`). |
| DATA-019 | `JobDB.claim` commits; `run()` takes the lease (`core.py:496-519`) without reading the state again. Needs two orchestrators (the update overlap of D-532). (Inferred.) | Re-read the state after the lease, or lease in the claim's transaction. |
| DATA-020 | `datacore/generations.py:74-85`: the build lock is a session advisory lock on a `Database` that reconnects; a server restart loses it silently. (Inferred.) | Hold it on its own connection, as `JobLease` does. |
| DATA-021 | `complete` (`backup.py:1702`) ignores `refdata.missing`. (Inferred.) | Add it to `complete`. |
| DATA-022 | `origin/agent/T-206b-optout-erasure-retention` adds one "In progress" decision file, from a commit before D-465. None of the 59 entries owed to T-206b is addressed. | Rebase; start with DATA-001, DATA-002, DATA-008. |
| DATA-023 | `roles_cluster` makes its directory in `TB_TEST_ROOT` before the root's marker exists; every later test then refuses the root ("holds files and no .tb-test-root marker"): `test_db_roles.py` alone in a fresh root gives 5 passed, 21 errors. | Mark the root first (call `pglocal.cluster_dir` or touch the marker) in the fixture. |

## 4. Closed findings checked in code

| Finding | Claimed | In code | Note |
| --- | --- | --- | --- |
| The nightly "1 changed" | open in the handover | **closed** by NEW-B-17 (#449, merged 2026-11-13 08:04 UTC) | Hard links in the site set-up's work lake were stored as empty members. Reproduced on the code before #449: "2 changed … sitesetup/newsite/lake/db/2026-11-02.duckdb". #473 adds the check that would have caught it at write time: merge it. |
| "permission denied for schema omop" | open in the handover | **fixed here** | DATA-001. Not the order of schema creation. |
| CR-053 held night promoted by the next delta | open | closed | `merge_base` never returns a held night. |
| CR-056 restore over a non-empty box | open | closed | Site and age checked; a copy kept; schemas dropped first. The drop is committed outside the restore's transaction; the kept copy covers it. |
| CR-057 per-table hash over 1 GB | open | closed | The `rs1` hash sums per-row pieces. |
| CR-085 outbox | open | closed, except DATA-015 | `send_keys` is a real outbox; `drain` is wired. |
| DI-10 restore leaves no audit trace | open | mostly closed | Except DATA-009 and DATA-010. |
| DI-11 a backup is not one point in time | open | open by design (D-455) | Mitigated by re-applied events and kept opt-outs; the audit folder is not one point (DATA-009). |
| DI-12 settings not in a backup | open | closed | `host/` is in the backup and restored only on request. |
| CR-119 derived rows of erased patients | open | open, wider | DATA-008. |
| CR-027 opt-out worker | built | built, did not run on a box | DATA-001. |

## 5. Scale, plans, contracts

SCALE-PLACEHOLDER

## 6. What is good and should not be changed

- The erasure registry and the test that fails on any table with no entry: no store is silently exempt.
- The worker's clear-then-read-back and its counts-only audit event; refusals that fail closed; an opt-out a person
  typed is never lifted by the feed; `keep_optouts` on restore; the OMOP `tb_withheld` filter.
- `tb_conflict`: each claim kept with its source, no silent winner, a resolution must be a claimed value with a
  reason and an authority.
- The OMOP load: one transaction under an advisory lock, an older batch refused, the mass-tombstone guard, the DQD
  hold. Ids stable across nights, tombstones and restores (verified).
- `load_fhir`'s widen-delete-narrow ledger, which heals after a crash; the publish record matched by fingerprint;
  pid-map staging until publish; `JobLease` on its own connection.
- The data core closes a conflict before it changes a value; trail tables are append-only by trigger, including
  TRUNCATE.
- Checksummed migrations (D-204) with a per-schema lock and baseline-gated back-fill.
- The backup: encryption to the hospital's key with authenticated chunks; hashes from the stream; prune gated by
  sidecars with a minimum kept; the lake read under its lock; the hold after a restore; the roles re-applied after a
  restore (verified); the PITR drill (verified).

## 7. Needless weight

- Three hand-made privilege checks across schemas (`with_survivors`, `_schema_url`, `_omop_store`), each wrong under
  the role model. This branch puts them on one helper; the remaining `to_regclass` calls on another schema should
  use it too.
- Two advisory-lock styles: `hashtext` of a name with no schema (`'trialbox-omop-load'`, `'dataops.built.build:*'`,
  cluster-wide, so separate test prefixes and lakes wait for each other) and a 64-bit key with the schema
  (`JobLease`). One helper.
- `recover_all(cfg)` runs twice on each delta night; `_Aliases` and `apply_aliases` are the same logic twice.
- `backup-verify` unpacks the whole box only to hash it; three scans of the audit folder at restore.
- 59 "owed" erasure entries point to a card (T-206b) with no code.

## 8. What was not run, and why

- `tests/integration/test_e2e_simple.py` and `make backup-drill` stop at "FHIRHelpers-4.0.1.cql not found in the
  cql-translator jars": `make jvm-deps` cannot fetch from Maven Central on this machine (Kotlin and SLF4J artefacts
  not found through the proxy). This is the same gap the 2026-11-12 review had. For lane G or CI.
- No Docker daemon: no compose stack, no restore into containers, no running-services restore (DATA-011 is by
  reading). No pgvector: the vector store's plans are by reading.
- The roles defects show only on the roles cluster. The nightly compose log of tonight should no longer show
  "permission denied for schema omop" once this branch is on a train.

## 9. For the owner

| Question | Recommendation |
| --- | --- |
| DATA-014: may the audit keep the pid of who opted out (it is kept 10 years or for ever)? | Log a keyed hash of the pid; correct the registry text. A decision, D-TBD. |
| DATA-004: when two sources disagree on a death date, the box now uses the later one until the steward decides. | Keep it: it is the only reading under which an unknown never excludes. |
| DATA-005: one cut-off row now holds the whole night for that source. | Keep it: the night before stays served; the steward sees why. |
