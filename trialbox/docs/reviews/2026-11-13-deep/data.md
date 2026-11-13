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
   A chart merge is not applied to records a delta night carries over (DATA-006). A person's status on an OMOP
   record would be undone by any later change to the source record; no screen sets one yet (DATA-007).
4. **Input:** a CSV cut off mid-row passed the night, and the cut value became the newest lab result in OMOP.
   **Fixed here** (DATA-005).
5. **The nightly backup's "1 changed" error** came from hard links in the site set-up's work lake. NEW-B-17 (#449)
   fixed it on master after the handover was written. Tonight's run is the first with the fix.
6. **Backup on a busy night:** the audit head is copied after the day file. One event written during the read gives
   a backup whose restore fails half-way, after the databases are replaced (DATA-009).
7. **Restore** drops file owners and does not stop the services (DATA-010, DATA-011).
8. **Derived rows** of patients who left the feed or opted out are kept and served (DATA-008, the old CR-119).
9. Closed items are mostly closed in code: CR-053, CR-056, CR-057, CR-085, DI-12. DI-11 stays open by design.
10. **Scale:** one patient's ruleset query costs almost a whole-hospital run (11 s against 30 s at 20,000
    patients); kept snapshots have no byte budget and pass the 2 TB disk; the OMOP loader holds every record in memory
    (4.5 GiB at 4.4 M rows); the goldens and the contracts let real breaking changes through (section 6).

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
| DATA-006 | High | A chart merge is not applied to what a delta night carries over | open | B2 |
| DATA-007 | Medium (latent) | A person's status on an OMOP record is undone by a later source change | open (file held by #493) | B2 |
| DATA-008 | Medium | Derived rows are never retired; they are rebuilt for opted-out patients | open | B2 with C2 |
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
| DATA-035 | Medium | A CSV row of another width inside a file is read with None cells (short) or crashes the night (long) | open (file held by #483, #487) | E |
| DATA-024 | High | One patient's ruleset query scans every fact table: 11 s for 1 pid against 30 s for all at 20,000 patients | open | A2 (compiler) |
| DATA-025 | High | Kept snapshots have no byte budget; month-ends keep their NDJSON; no free-space check before a build | open | B2 |
| DATA-026 | High | The OMOP loader holds every record in memory: 4.5 GiB at 4.4 M rows (PERF-027, behind its flag) | open (file held by #493) | B2 |
| DATA-027 | Medium | Per (patient, criterion) note reads and a new lake connection per call | open | B2 |
| DATA-028 | Medium | Half of each DuckDB snapshot is the FTS input column and free blocks | open | B2 |
| DATA-029 | Medium | The OMOP load rewrites and re-checks whole tables every night; the export spills at default `work_mem` | open | B2, D (settings) |
| DATA-030 | Medium | Provenance outweighs the data (810 bytes per clinical row); `tb_record_event.at` has no index | open | B2 |
| DATA-031 | Medium | The goldens did not catch dropped lab comparators ("<0.3" read as 0.3) | open | E |
| DATA-032 | Medium | The lake reader never compares the table layout's hash within a version | open | B2 |
| DATA-033 | Medium | The contracts check accepts a new required field in stored documents | open | D |
| DATA-034 | Low | The limits lint does not see `timeout_s`, the spill ceiling or `RANKING_CHUNKS` | open | D |

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
- **Review.** The adversarial review found no privilege widened: `table_exists` reads names only, and `connect` still
  takes a group role only by membership. It found the tick test depended on the test before it (it passed in the
  module, failed alone); the test now makes its own opt-out.
- **Still to do (C2).** Open the OMOP store inside `run_once`'s per-store `try`, so one store cannot stop the others.
  Exercise the vec, profile and pending clears as `tb_orchestrator` (the test cluster has none of their tables).
  `with_survivors` could check SELECT on `pid_alias` rather than USAGE on the schema (the same on a box today).

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
- **Fix (this branch).** While the conflict is open, both lakes keep the **earliest** claimed date. The patient is in
  before any source says they died and out from the first claim on: a death fails closed (D-400) in the window the
  sources dispute. A steward's choice stands, "keep unknown" included (then D-400's "dead, no date" applies, as the
  steward chose). The conflict stays open for the steward. Test: `tests/unit/test_death_date_conflict.py` (both
  lakes; fails before).
- **Review.** The first version took the latest date and overrode a steward's "unknown"; the adversarial review
  showed that a later date (or a future-dated typo) counts a patient alive whom one source records as dead, against
  D-400, and that the console says "kept unknown". Changed before the push.
- **Note.** OMOP's own `death` table still holds the first source's date (`omop/load.py:1253`, `:1305`), as before.

### DATA-005 (Critical, fixed): a CSV cut off mid-row passes the night

- **Symptom.** The last line of `lab.csv` was `L2,20000001,HBA1C,HbA1c,6`: the export stopped while writing
  `6.8,%,2026-09-01 ...`. The night passed. The lake held an undated HbA1c of 6 with the mapping's default unit.
  The OMOP load dates a required date it lacks with the load night (`omop/load.py:893-897`, flagged `imputed`), so
  the cut value became the newest HbA1c and flipped "latest HbA1c ≥ 7".
- **Evidence (verified).** `passed True held False errors []`; OMOP measurement rows `(9.1, 2026-08-01)` and
  `(6.0, 2026-10-01)`.
- **Root cause.** `sources/csv/source.py` read rows with `csv.DictReader`, which fills a short row with None and puts
  a long row's extra cells under a None key; nothing checked the width.
- **Fix (this branch).** The pre-pass that already parses the whole file quarantines it when its last line is short
  and the file ends without a line end: a cut-off export. The night is held, as for an unreadable file (T-615b).
  Spaces-only and Ctrl-Z lines are no record. A short row that ends its line (an exporter that drops empty trailing
  cells) is read as before. Test: `tests/unit/test_csv_short_row.py` (4 of 5 fail before).
- **Review.** The first version quarantined a file for any row of another width. The adversarial review showed that
  this holds a whole night for one row, against STD-025 (T-615a: a row the mapping cannot read is rejected and
  counted; the night is held only above `REJECT_MAX_PCT`), and for an exporter's dropped empty cells. Narrowed before
  the push; the rest is DATA-035.
- **Still to do (E).** The OMOP load should not impute a date for a measurement or observation that criteria read by
  date; such a row should stay undated.

### DATA-006 (High, open): a chart merge is not applied to what a delta night carries over

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
- **Severity.** Reported Critical; the adversarial review rates it High: a merge is a manual `pid-merge`, the effect
  lasts until the next full night, and the opt-out side of a merge is handled by `with_survivors` (on a box only
  since DATA-002). No reader applies the alias map elsewhere.

### DATA-007 (Medium, latent): a person's status on a record is undone by a later source change

- **Evidence (verified).** `set_status(c1, 'rejected')`; an unchanged reload keeps `rejected`; a reload where only
  `recordedDate` changed gives `coded`. The rejected diagnosis counts again.
- **Root cause.** `omop/load.py` `_write` (about line 1079): on `update` and `restore` the status is the batch's;
  only `same` keeps the old one. A vocabulary load changes concept ids and so every content hash: it would reset
  every person-set status in one night (inferred).
- **Fix.** Carry a person-set status across `update`; reopen it for review only when the coded fact (code or date)
  changed; keep concept ids out of the content hash. `omop/load.py` is held by #493.
- **Severity.** No production code calls `omop.load.set_status` today (only its definition, `load.py:1455`): no
  screen or route can reject a record yet. It must be fixed before one does.

### DATA-008 (Medium, open): derived rows are never retired (CR-119 still holds, and goes further)

- **Evidence (verified).** Night 1: P_A and P_B, 4 rows. Night 2: P_B gone from the lake and P_A opted out:
  `inserted=0, unchanged=2, retired=0`. P_B's rows stay current and `latest_many(as_of=night 2)` returns its value
  with the pid, age and sex in `inputs`. A rebuild of one snapshot is deterministic, but the store built night by
  night is not equal to a rebuild of the last night.
- **Root cause.** `derived_store.py:700-733` looks only at patients in the snapshot; `orchestrator/derive.py:146`
  passes no exclusion; `erasure.CLEARS` has no `derived` clear: the four tables are registered as owed to T-206b
  (`erasure.py:272-278`).
- **Severity.** Screening reads the store only when the flag `derived.stored_read` is on; its default is off
  (`derived_store.py:648-657`), and the twin skips opted-out patients. High once the flag is on.
- **Fix.** Supersede the current rows of every pid not in the snapshot; skip the register's patients; add a
  `derived` clear (score rows, input links, conflicts, the failed-pid list).

### DATA-009 (High, open): a busy night gives a backup that cannot be restored

- **Evidence (verified).** The backup copies `2026-11-14.jsonl` before `HEAD.json` (`_walk` order), and takes the day
  file only up to the line it had when the read began (`backup.py:635-713`). One `AuditLog.append` in between: the
  copy's `verify()` says "the chain ends at event 1, the head anchor says event 2". `restore` then raises
  `AuditAnchorBroken` at `backup.py:1712`, which is not a `BackupError`, after the databases, the folders and the
  `.pre-restore-*` copies are in place. No `restore_failed` event is written. The restored box's audit refuses every
  write. The drill cannot see this: its box is idle while it backs up.
- **Mitigation the finder missed.** The screening hold is taken earlier in the restore (`backup.py` about 1616) and
  `release_own_hold` falls back to "held" on any error (`backup.py:1417-1427`): the box most likely stays held, and
  `--reanchor` exists. Still High: no `restore_failed`, no hint to the kept copy.
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
| DATA-035 | `sources/csv/source.py`: a short row that ends its line is still filled with None; a long row puts its extra cells under a None key, and a trailing separator on data lines crashed the ingest (`TypeError: '<' not supported between NoneType and str`, found by the adversarial review). | Send a row of another width to STD-025's reject count in `pipeline.py` (held by #483, #487). |

## 4. The adversarial review

One reviewer, given the diffs and the reproductions and asked to refute them:

| Item | Verdict | What changed |
| --- | --- | --- |
| DATA-001, DATA-002, DATA-003 fix | holds with changes | the tick test made self-contained |
| DATA-004 fix | holds with changes | earliest date, not latest; a steward's "unknown" stands |
| DATA-005 fix | holds with changes | narrowed to a cut-off last line; the rest is DATA-035 |
| DATA-006 | holds | Critical → High |
| DATA-007 | holds | High → Medium (latent: no caller of `set_status`) |
| DATA-008 | holds | High → Medium (flag off by default; owed to T-206b) |
| DATA-009 | holds | High kept; the hold's fall-back added |

## 5. Closed findings checked in code

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

## 6. Scale, plans, contracts

Measured on this machine: the scale gate at 2,000 dense patients (522 records and 40.6 notes each); the OMOP store
built by its own migrations with 20,000 persons and 4.4 M clinical rows in 19 year partitions; the lake at 20,000
patients (the 2,000-patient snapshot copied ten times with new ids, 11 M records). All synthetic; scratch deleted.

| Id | Evidence | Fix |
| --- | --- | --- |
| DATA-024 | `rulesets/RA-JAK/sql/RA-JAK.sql`: 1 pid 1.8 s / all 2.4 s at 2,000; 11.2 s / 30.0 s at 20,000; about 28 s per patient at 50,000 and 280 s at 500,000, at the 300 s lake limit. The pid filter applies to `base` only (`RA-JAK.sql:9-14`); every fact subquery reads its whole table first. `evaluate_case` (`case.py:286`) and small batches (`evaluate.py:132`) pay it. (Verified.) | The compiler filters each fact table by the pids: tried on 36 references, 1 pid 11.2 s → 2.9 s, 30 pids 14.6 s → 4.9 s, results identical on 8 pids. Sort lake tables by pid at build. |
| DATA-025 | Per dense patient: NDJSON 0.55 MB, Parquet 0.05 MB, DuckDB 0.23 MB per snapshot. Kept: 3 nightly + up to 36 month-ends (`pipeline.py:68-69`); pruning drops NDJSON only of snapshots not kept (`pipeline.py:1560-1572`). One snapshot: about 41 GB at 50,000, 415 GB at 500,000; 39 snapshots: 1.6 TB and 16 TB against a 2 TB disk. No `disk_usage` check before a build. (Measured, then arithmetic.) | Month-ends as Parquet only, or NDJSON gzipped (263 MB → 23 MB measured); a byte budget derived from the disk; refuse a build below the measured snapshot size. |
| DATA-026 | `omop/load.py:1060-1067` reads every `tb_record` into a dict: 4.42 M rows, 13 s, 1,078 bytes a row, peak 4.5 GiB; about 28 GB at 50,000 against the adapter's 6 GiB. The dual write reports "failed" and does not hold the night. (Verified.) | Diff in SQL: COPY the batch's keys and hashes into a temp table and join. |
| DATA-027 | `Lake.connect` about 80 ms a call; `evaluate_patients` (`evaluate.py:758-770`) runs `window()` per (patient, criterion), two lake calls each (`DOCUMENT_SQL` 236 ms at 2,000). The cascade's `NOTES_SQL` already reads a batch. (Verified.) | Read notes per batch of pids; reuse the connection per worker. |
| DATA-028 | A 438 MiB snapshot uses 1,208 of 1,752 blocks; `document_chunk.tok` is 92 MiB and is read only by `create_fts_index` (`store.py:1360`). Note text is held 6–7 times a night. (Verified.) | Drop `tok` after the index; write the file compacted; keep Parquet only where it is read. |
| DATA-029 | `observation_period` rebuilt from all tables every load (1.25 s, `load.py:1343-1356`); `fact_relationship` too; 175 relational checks in 6.1 s, twice per feed load; the export join spills 108 MB at the default 4 MB `work_mem`. PERF-014 open. (Verified at 4.4 M rows.) | Recompute for changed persons only; check changed rows only; set `work_mem` from RAM in the `db` service. |
| DATA-030 | `tb_record` 513 bytes a row, `tb_record_event` 138, clinical rows about 160; `tb_record_event` grows for ever; `at > ?` is a sequential scan (240 ms at 4.4 M). (Verified.) | An index on `tb_record_event (at)`; a retention rule for before-images (with T-206b). |
| DATA-031 | A scratch change made `_value` drop `value_cmp`: `tools.goldens --check --profile ci` said "IDENTICAL: 23 goldens"; unit tests caught it (7 failures). The ci data has no censored value. (Verified.) | Plant censored values, unit variants, missing dates and text results in the ci data; list which data set covers which mapping branch. |
| DATA-032 | Renaming `observation.value_cmp` without a version bump: `Lake.connect` accepted the old snapshot, the query failed later with a BinderException. `make goldens REASON=<any>` rewrites the layout file. (Verified.) | Refuse a snapshot whose layout hash differs within a version; a test that requires a version bump when the hash changes. |
| DATA-033 | A new required field in `job.schema.json` or `ingest_report`: `gen_contracts.py --check` and `criterion_ir --check` return 0; old stored jobs then fail `model_validate_json` on read (`orchestrator/db.py:280-378`, `clients.py:186`). (Verified.) | Validate committed samples of earlier documents against the current schemas; a new required field needs a default or a migration. |
| DATA-034 | `Lake.query(..., timeout_s=300)` (`store.py:1507`) is not matched by the lint (it looks for `timeout`); the 50 GB spill ceiling and 25 % share (`store.py:620-633`) and `RANKING_CHUNKS = 5` are not declared. `limits_lint`: "101 literals, clean". (Verified.) | Widen the pattern; derive the query limit from the job and the lake size. |

Checked and fine: snapshot generations are hard links, not copies; timestamps are naive site time, so date casts
carry no zone error; the lake rebuild streams row groups (2.83 GiB peak at 2,000 dense patients); DuckDB memory and
spill caps come from the cgroup; the vector search by patient is exact on a btree. Year partitions make a lookup by id
probe 20 partitions (34 ms for 1,000 ids): acceptable. PERF-009 is fixed (`store.py:449`). Still open: PERF-010,
PERF-014, PERF-023, PERF-027 (measured, DATA-026).

## 7. What is good and should not be changed

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

## 8. Needless weight

- Three hand-made privilege checks across schemas (`with_survivors`, `_schema_url`, `_omop_store`), each wrong under
  the role model. This branch puts them on one helper; the remaining `to_regclass` calls on another schema should
  use it too.
- Two advisory-lock styles: `hashtext` of a name with no schema (`'trialbox-omop-load'`, `'dataops.built.build:*'`,
  cluster-wide, so separate test prefixes and lakes wait for each other) and a 64-bit key with the schema
  (`JobLease`). One helper.
- `recover_all(cfg)` runs twice on each delta night; `_Aliases` and `apply_aliases` are the same logic twice.
- `backup-verify` unpacks the whole box only to hash it; three scans of the audit folder at restore.
- 59 "owed" erasure entries point to a card (T-206b) with no code.
- In each DuckDB snapshot, the FTS input column and free blocks (about half the file); Parquet beside DuckDB for every
  kept snapshot; uncompressed NDJSON for every month-end.

## 9. What was not run, and why

- `tests/integration/test_e2e_simple.py` and `make backup-drill` stop at "FHIRHelpers-4.0.1.cql not found in the
  cql-translator jars": `make jvm-deps` cannot fetch from Maven Central on this machine (Kotlin and SLF4J artefacts
  not found through the proxy). This is the same gap the 2026-11-12 review had. For lane G or CI.
- No Docker daemon: no compose stack, no restore into containers, no running-services restore (DATA-011 is by
  reading). No pgvector: the vector store's plans are by reading.
- The roles defects show only on the roles cluster. The nightly compose log of tonight should no longer show
  "permission denied for schema omop" once this branch is on a train.

## 10. For the owner

| Question | Recommendation |
| --- | --- |
| DATA-014: may the audit keep the pid of who opted out (it is kept 10 years or for ever)? | Log a keyed hash of the pid; correct the registry text. A decision, D-TBD. |
| DATA-004: when two sources disagree on a death date, the box now uses the earlier one until the steward decides. Before, the patient was out at every date. | Keep it: it follows D-400 (a death fails closed) and no longer excludes before any claimed death. A decision, D-TBD, if you want it recorded. |
| DATA-005: a cut-off last line now holds the night for that source. | Keep it: the night before stays served; the steward sees why. |
| Allow-list entries | none asked |
