# H121: the update's size check on a site's database roles

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders.

- **Card:** H-121, a red from the MVP walk on the bench host (the walk's 7125822972, the integrator's 7125878918).
  `trialbox update` failed twice in the same way, at 108 s with exit 1: `ERROR: permission denied for database hapi`.
- **Date:** 2026-11-24
- **Findings:** [`update-size-check-roles-h121-2026-11-24/findings.json`](update-size-check-roles-h121-2026-11-24/findings.json)
  (H121-01 to H121-06)
- **Files:** `tools/trialbox/update.py` (`DB_SIZE_ROLES`, `ComposeBox.db_size`, `db_bytes`, `space_needs`),
  `tools/rehearse_box/box.sh` (the `doctor` phase), the new test `tests/unit/test_update_size_roles_h121.py`.

## 1. What failed, and why on that box

`tools/apply_update.sh` runs `python3 -m tools.trialbox update` from the box's INSTALLED tree, not from the new
bundle. So the update path that runs is always the installed release's. The walk box was installed from a master
before H-99 (a9cc50c9). That release's `space_needs` asked `SELECT pg_database_size('hapi')` as `trialbox` on
`trialbox_wf`.

On a site's roles that read is refused, because `deploy/docker/db-init/30-service-roles.sh` takes every right on
`hapi` from PUBLIC. The function then raises `ERROR:  permission denied for database hapi`. These are the walk's
words, and the error is an ERROR from the function, not the FATAL of a refused connection. The walk named the H-99
lines because it read master's source; the code that ran was the older line.

Master's reads (H-99) were already right on a site's roles: `trialbox` on `trialbox_wf`, and `hapi` (the db image's
`POSTGRES_USER`, the cluster's superuser, as the restore connects) on `hapi`. A box installed from a master that has
H-99 updates; a box installed before it needs one reinstall (H121-01).

**The class (H121-06).** The update's checks and its applying code come from the installed tree, never from the
signed new bundle:
- `tools/apply_update.sh` sets `ROOT` from its own folder (line 55), runs `cd "$ROOT"` (line 262) and then
  `python3 -m tools.trialbox update` (line 267);
- that imports `tools/trialbox/update.py` from the installed tree (`tools/trialbox/__main__.py`, line 341);
- `deploy/install.sh` (line 810) links `/usr/local/bin/trialbox` to the installed `__main__.py`.

So a fault in an installed release's update code cannot be fixed by a new bundle, only by a reinstall. Card H-124
takes the update's code from the signed bundle instead.

**Why CI passed.** The roles were never the difference: the box rehearsal uses the same compose file and db-init.
But nothing in CI runs an update path from an older release (H121-02), and nothing in CI ran `ComposeBox`'s size
reads against the box's real database container (H121-03):
- the rehearsal installs and never updates (an update from release N-1 is card H-123);
- the update drill (`tools/update_drill.py`) runs the in-process box;
- H-99's test ran on a local cluster.

## 2. The change

- `DB_SIZE_ROLES` is the one list of which database is read as which role. `ComposeBox.db_size` is the one reader;
  `db_bytes` (the update's limit, the backup's step limits, the restore) and `space_needs` both use it.
- A read that fails now stops the update before anything is changed, with a plain line:
  `the size of database hapi could not be read as role trialbox: <psql's own error>; the space check needs it,
  nothing was changed`. Before, the raw `docker compose ... exec` line was shown. `db_bytes` keeps "no size, so no
  limit" (D-455).
- An answer that is not a number now stops the update with the same plain line. Before, it counted 0 and the space
  check went on without that database (H121-04). The update tests' fakes that answered `""` now answer the size
  query; no assertion changed. They are `FakeRun` in `tests/unit/test_update_path.py`, `STAND_IN_DOCKER` in
  `tests/unit/test_host_tree.py` and one runner in `tests/unit/test_update_safety.py`.
- **The rehearsal (real path).** The `doctor` phase now checks two things on the installed box's own database
  container, through the box's own command line:
  - `trialbox` cannot connect to `hapi`, so the rehearsal's roles are a site's;
  - `ComposeBox.db_size` reads both databases with `DB_SIZE_ROLES`.

  The old role or the old query fails this phase. It adds two `docker compose exec` calls and one Python start,
  about 2 s; not measured, the rehearsal was not run here (H121-05).
- **Harm named.** A box whose size check cannot read a database could never update. The stop already existed, and
  the change only says it plainly, so it is no new guard and no new stop on a PoC box.

## 3. The tests

`tests/unit/test_update_size_roles_h121.py` builds a site's roles with the install's own scripts:
- a cluster whose superuser is `hapi`, with a `hapi` database, as the image's first start makes them;
- then `10-trialbox-wf.sh` and `30-service-roles.sh`.

`20-extensions.sh` needs the image's extensions; it changes no role or grant. The box's command lines
(`compose exec -T db psql ...`) run against the cluster.

- `test_h121_the_cluster_has_a_sites_roles`: `trialbox` is refused on `hapi`, `tb_fhir_store` owns it, `hapi` is
  the superuser.
- `test_h121_the_size_check_reads_both_databases_on_a_sites_roles` (the invariant): `db_size`, `space_needs` and
  `db_bytes` all see both sizes.
- `test_h121_the_walk_boxs_read_is_refused_on_the_same_roles`: the walk box's read gives the walk's exact error.
- `test_h121_a_size_that_cannot_be_read_stops_the_update_plainly`: with the old role put back, the update stops
  with the plain line and `db_bytes` is None.
- `test_h121_an_answer_that_is_not_a_size_stops_the_update_never_counted_zero`.

**Mutants.** Six were planted, and each was caught:
- the old role (`hapi` read as `trialbox`): by the invariant test and by
  `test_update_poc_box_h99.py::test_h99_the_size_reads_work_on_the_real_roles`;
- the walk box's read (every size asked as `trialbox` on `trialbox_wf`): by the same two;
- an answer that is not a size counted 0 (`n = n or 0`): by
  `test_h121_an_answer_that_is_not_a_size_stops_the_update_never_counted_zero`;
- the fix of the red 7134736821 reverted (`_existing` back to `Path.exists()`): by
  `test_h121_the_update_path_runs_as_a_non_root_user_without_docker_s_folder`;
- `tools/packs.py`, `tools/trialbox/backup_schedule.py` and `tools/fetch_weights.py` each back to master's `_existing`
  (three, one at a time): each by `test_1469_8_every_existing_measures_an_unreadable_folder_on_its_readable_parent`.

The rehearsal's check fails on the first two by construction; this was not run.

**The test set** of the pre-push runs is named by rule in
[`update-size-check-roles-h121-2026-11-24/test-set.sh`](update-size-check-roles-h121-2026-11-24/test-set.sh)
(OCR 1469-5): it prints the files, and its comment gives the command.

## 4. The four recurring finding types

- **Ctrl-C or SIGTERM.** The size reads run in the preflight, before the marker and the rollback point. A signal
  there changes nothing. The update's signal handling is #1461's, and its lines were not touched.
- **Files written in place.** None: the change writes no file.
- **Value sets and date windows.** Not in this card's code.

## 5. The two reviews of #1469 (7134151892, 7138768548)

- **1469-6 (Medium), the red of train 167** (7134736821). With the stand-ins now answering the size query, the space
  check measured the rollback script's need on Docker's data root. `Path.exists()` of the runner's
  `/var/lib/docker/volumes` (0710 root) raised PermissionError for its non-root user. `_existing` now walks up past a
  folder it may not look at, as past a missing one. Test:
  `test_h121_the_update_path_runs_as_a_non_root_user_without_docker_s_folder`.
- **1469-7 (Medium): the unit tests measured the host's own engine folder.** The update tests' stand-ins answer
  `docker info` with a folder of the test's own (`FakeRun`, the runner in `test_update_safety.py`, and the helpers
  in this card's test and in H-99's), never the host's `/var/lib/docker`. Tests:
  `test_ocr_1469_7_the_update_paths_stand_ins_never_measure_the_hosts_docker_root`, and the invariant test asserts
  it too. Follow-up named by the review: `volume_bytes` and `_audit_waits` read the box's settings (present on
  master; they catch OSError). Their tests' box `.env` should name a `TB_DOCKER_VOLUMES` of their own: a lane H card.
- **1469-1 (Low):** the rehearsal's size check fails unless both sizes are positive integers.
  `test_1469_1_the_rehearsals_size_check_fails_when_a_size_is_not_read` runs the program from `box.sh`.
- **1469-2 (Low):** `isdecimal()`, not `isdigit()` (which takes `²`, refused by `int()`).
  `test_1469_2_an_answer_of_digit_like_characters_is_no_size_never_a_crash`.
- **1469-3 (Low):** a size that cannot be read is a preflight refusal (`UpdateRefused`: nothing was changed).
  `test_1469_3_a_size_that_cannot_be_read_is_a_preflight_refusal`.
- **1469-4 (Low):** `DB_SIZE_ROLES` is now the one list for the update's dumps and the nightly's reads and dumps.
  The restore's read (`tools/trialbox/box_restore.py`) is #1470's file in those lines: it moves after #1470 (H-129).
  `test_1469_4_the_role_pairs_are_written_once` names it until then.
- **1469-5 (Low):** the test set is named (`test-set.sh`, above), and the mutants are listed (above).
- **1469-8 (Low):** the other copies of `_existing` (`tools/packs.py`, `tools/trialbox/backup_schedule.py` and its
  `_resolve`, `tools/fetch_weights.py`) walk up the same way. Test:
  `test_1469_8_every_existing_measures_an_unreadable_folder_on_its_readable_parent`, four modules. H-124 carries
  the same `packs.py` text.

