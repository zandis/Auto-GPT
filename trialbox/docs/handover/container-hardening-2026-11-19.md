# Container hardening: the four controls on the 15 services (2026-11-19)

**Reader:** the people who build TrialBox: lane H, the integrator, and the owners of the adapter, the orchestrator
and the GPU serving profiles. Findings for builders, so in one language.

Plan 10 row 10G-1 (review 16-17 and 9l-18), decision D-1323. Findings in the register's `--add-from` form:
`container-hardening-2026-11-19/findings.json`.

## What changed

`deploy/docker-compose.yml` has 15 services. Each carries `cap_drop: [ALL]`, `no-new-privileges:true`,
`read_only: true` with a `/tmp` tmpfs, and a fixed numeric non-root user, or a written exception:

| Service | cap_drop ALL | no-new-privileges | read_only (tmpfs) | user |
| --- | --- | --- | --- | --- |
| db | yes | yes | yes (`/tmp`, `/var/run/postgresql`) | 999:999, group_add ssl-cert |
| fhir-store | yes | yes | yes (`/tmp`) | 65532:65532 |
| lake, embed-service, doc-parser, criteria-compiler, audit-writer, mail-gateway, gateway, console, llm-stub | yes | yes | yes (`/tmp`) | 10001:10001 |
| adapter | yes | yes | **exception** (H10G1-01) | 10001:10001 |
| orchestrator | yes | yes | **exception** (H10G1-01) | 10001:10001 |
| llm-service | yes | yes | **exception** (H10G1-02) | **exception** (H10G1-02) |
| model-guard | yes | yes | yes (as before) | 10001:10001 |

`tests/unit/test_container_hardening.py` merges every stack of `tests/unit/test_compose_limits.py` (the YAML level)
and renders each with `docker compose config` (where the plugin is), and fails on a missing control without an
exception, an exception whose control is applied, an unexplained `cap_add`, or a service outside the 15 that is not
listed with a reason.

## What was and was not run

No Docker daemon in the container where this was made: nothing was brought up. Shown here: the YAML and the rendered
configuration of every stack; the HL7 validator against an unwritable and a writable copy of its package cache (as
uid 10001). Not shown: that each service starts and works under the controls. To be run on a compose box before the
row is trusted: every stack up and healthy, `trialbox doctor`, the four walks, backup and restore, an update, and the
box rehearsal's later steps.

The box rehearsal ran in CI on #1142 (run 44449244254, both legs): the hardened stack came up ("doctor passed", 17
containers running and healthy), then the SC-1b / D-993 identity check failed. db PID 1 had uid and gid 999 but groups
`999` only, where `id -G postgres` is `999 101`: started as numeric `999:999`, it no longer goes through the setpriv
shim's `--init-groups` and lost postgres's `ssl-cert` group (the TLS key). The fix gives db `group_add: [ssl-cert]` (by
name, resolved in the image's `/etc/group`; user `999:999`, cap_drop, no-new-privileges and read_only unchanged), and
the YAML test pins it. No Docker daemon here, so only the rendered configuration shows it; the rehearsal on the pushed
head is the proof. The rehearsal's later steps (terminology, screen, power-cycle, restore) have NOT yet run under the
hardening: the check aborted before them.

The second rehearsal (run 44458900188, head a103fc28, both legs) passed install, the db identity check, doctor,
terminology, guard, console, screen and power-cycle, and failed on the reference data: step `offline` printed
`no reference data loaded` and `REHEARSAL FAIL: the reference data pack trialbox-refdata-20261109 of the media is not
loaded`; `after-restart` then `REHEARSAL FAIL: the reference data did not survive the restart` (a consequence: the pack
was never loaded). Cause: `deploy/install.sh` loaded the pack with `docker compose cp PACK
criteria-compiler:/tmp/refdata-install.tar` and then `exec`. docker cp refuses to write into a container whose root
filesystem is read-only unless the target is a volume, and the tmpfs `/tmp` is not one; the `cp` failed, the installer
printed a warning to stderr and went on (H10G1-04), and only the rehearsal's later check noticed. The update path had
the same two copies (`tools/trialbox/update.py` `ComposeBox.rulesets` and `ComposeBox.refdata`). Terminology passed
because `deploy/terminology.sh` already loads through a one-off `docker run` with the volume mounted, never a copy.

Fix: both paths run a one-off `docker compose run --rm --no-deps -T` criteria-compiler (same user, read-only root,
cap_drop, no-new-privileges, networks and database URL as the service) with the file bind-mounted read-only at
`/in/refdata.tar` (`/in/ruleset.zip` for a ruleset), and `TMPDIR=/data/objects` for the refdata loader so a pack of
several GB unpacks on the objects volume rather than in the tmpfs `/tmp` that counts against the 3g memory limit. No
control is dropped; no new exception. `test_nothing_copies_a_file_into_a_read_only_service` names any
`compose cp HOST SERVICE:PATH` into a read-only service in install.sh or update.py (it finds the three old lines);
`test_the_update_bundle_loads_the_pack` asserts the new argv.

Checked for the same shape (a write into a now read-only or non-root container): install.sh's other `compose
exec`/`run` (db roles script, adapter `keys-init`, orchestrator migrate and deferred audit, console bootstrap-admin
and enrol-code) write to the database, a volume or a writable-root service; `compose cp caddy:... deploy/...` copies
out, which docker allows from a read-only root. update.py's other `exec`/`run` (pg_dump to stdout, psql, RULESETS_PY,
migrations, the restore script in db's tmpfs `/tmp`, the orchestrator audit) read, write the database or a volume, or
write a tmpfs through `exec` (which works: the rehearsal's screen step writes `/tmp/GZQO.zip` that way). Not proven:
the nightly backup (`tools/trialbox/backup_schedule.py`) dumps into db's tmpfs `/tmp/tb-backup` through `exec`, then
copies it out with `compose cp db:/tmp/tb-backup/. HOST`; whether docker cp sees a tmpfs's files, and whether the dump
fits db's memory limit there, is for a box run. A restore's `reload_refdata` unpacks the pack in whichever container
runs the restore; on a hardened one-off that is a tmpfs `/tmp` unless TMPDIR points at a volume.

No Docker daemon here: the YAML tests and the argv test show the change; the next CI box rehearsal on the pushed head
is the proof (steps `offline` and `after-restart`), and its later steps have still not run under the hardening.

The third rehearsal (run 44469191433, head d44f3f5b, both legs) passed every step (install, the db identity check,
doctor, terminology, the reference data loaded and surviving the restart, screen, power-cycle) but the restic restore
(test: step 24; validation: step 25): the nightly's own backup failed with `cp db:/tmp/tb-backup/. HOST ... Could not
find the file /tmp/tb-backup/. in container`, and the rehearsal printed `REHEARSAL FAIL: the nightly's backup with
restic failed`. Cause: `ComposeOps.snapshot` (`tools/trialbox/backup_schedule.py`, the `self.box._c("cp",
f"db:{CONTAINER_SPOOL}/.", ...)` line) wrote the snapshot into db's `/tmp/tb-backup` through `exec` and copied it out
with `compose cp`; docker cp reads a container's layers and volumes, not a tmpfs mount, so it found nothing. The dump
(several GB on a site) in that tmpfs would also have counted against db's memory limit (`TB_MEM_DB`, 4g by default).

Fix: the dump is streamed, as update's snapshot already does (`pg_dump` to stdout). `snapshot_script(...,
dump_to_stdout=True)` leaves `-f` off `pg_dump`, which then writes to psql's own stdout (nothing else of the script
goes there: `-q`, every query output to its `\o` file); `exec -T db sh -c '... psql -f ...'` hands it to
`<db>.dump` in the 0700 work folder on the host. The small files (snapshot id, exit code, row counts and hashes, the
packs, the hospital's own reference rows) are still written in the tmpfs spool and come back as `exec -T db tar -C
/tmp/tb-backup -cf - .` on stdout, unpacked on the host with tarfile's `data` filter (regular files only); the spool
is removed as before. No new writable path, no dropped control, no new volume. Peak extra memory in db: the script
and those small files (the hospital's own reference rows are the largest: a site's own vocabularies, not the vendor
pack); peak disk: the dump once, in the host work folder, as before. `test_nothing_copies_a_file_out_of_a_tmpfs`
names any `compose cp SERVICE:PATH HOST` whose PATH is on that service's tmpfs (module constants resolved; a path it
cannot resolve counts) in install.sh and every deploy script, every tool under `tools/trialbox` (backup, restore,
restore drill, update, the support bundle in `logs.py`), `tools/box` and the drills; the into-direction test now
reads the same files. Checked: the only copy out of a tmpfs was this one; update's demo box copies out of its own
unhardened container (`docker cp trialbox-demo:/tmp/tb-update-backup`); `runbook_install.py` copies into a single
demo container, not a compose service. `test_the_streamed_snapshot_script_runs_on_this_postgres` runs the streamed
script on a real PostgreSQL: stdout is a dump `pg_restore --list` reads, and the files parse.

The restore side: `backup.reload_refdata` unpacked each vendor pack in the temporary folder (`tb_common.refdata.opened`,
`mkdtemp`). It now unpacks beside the kept packs (`deploy/refdata`, the disk that holds them; a caller can name a
volume, `unpack_in`), the shape the installer and the update use (`TMPDIR=/data/objects`);
`test_reload_refdata_unpacks_beside_the_kept_packs` pins it. On a compose box `trialbox restore` runs on the host, so
this was not a container tmpfs there; it keeps a several-GB unpack off a host or a job whose /tmp is a tmpfs.

The fourth rehearsal (head 5355df18, both legs) passed every step, the restic backup and restore included.

A review of that head asked for four more changes, made here:
- **D1, the side files.** The streamed nightly still wrote `.rows` and the hospital's own reference rows
  (`.site.<table>.copy`) into db's tmpfs `/tmp`, memory under `TB_MEM_DB`. Now every output goes through the stream
  helper (`backup_schedule.EMIT_SH`, run as `sh /tmp/tb-backup/emit NAME`, psql's `\o |...` for the query outputs):
  it copies its input to psql's stdout while `wc -c` counts it through a FIFO, and records "bytes name" in an index;
  the stream ends with the index and a fixed trailer. On the host `split_stream` truncates the stream file to the dump
  (no copy) and writes each small file 0600. db's `/tmp` keeps the script, the snapshot id, the exit code and the
  index: bytes. db's `/tmp` tmpfs is now `size=64m`, so a runaway writer gets "no space left", never an OOM kill
  of db; `test_read_only_services_get_a_tmpfs_for_what_they_write` requires a size on it.
- **H10G1-05, the rollback.** With the cap, `update.RESTORE_SH`'s plain SQL script in db's `/tmp` would make a
  rollback of any real database fail for space. A first fix streamed pg_restore into psql. A second review ran it
  on PostgreSQL 16.15 and found it unsafe: pg_restore without `-f` or `-d` is refused since PostgreSQL 12 (every
  rollback would have failed; the unit test's shim believed otherwise), and a dump with large objects carries its own
  `BEGIN ... COMMIT`, which would end the outer transaction. So RESTORE_SH is back to master's logic (pg_restore
  `-f` to a file; psql `--single-transaction` on that file only after pg_restore succeeded; the file removed), and
  only the file's place changed: `${PGDATA:?}/tb-rollback` on the db-pg volume, made 0700, emptied first (a killed
  rollback's leftover) and removed on every exit. PGDATA is the volume's mount point, so no sibling folder exists;
  the only other postgres-owned mount, the pgBackRest repository, is the hospital's off-box share when archiving is
  on, no place for a plaintext script. The rollback needs free space for one database's plain script (about its
  size or less); the update's preflight (`ComposeBox.space_needs`) now counts the largest database on Docker's
  volumes. `test_compose_rollback_restore_resets_the_role_first_and_never_runs_a_cut_off_script` has master's
  name and assertions plus the folder's place; `test_the_rollback_restore_runs_a_real_dump_under_dash_and_a_failed_one_changes_nothing`
  runs a real `-Fc` dump with a large object through RESTORE_SH under dash, and a cut-off dump changes nothing.
  A streamed rollback could come later only with both conditions the review proved necessary: `pg_restore -f -`
  and pg_restore's own `--single-transaction`.
- **D2, llm-service.** Root without `DAC_OVERRIDE` cannot read a model file of another owner with mode 0600 or 0640.
  `tools/fetch_weights.py` writes 0644 under the caller's umask, and `box_vm.py models-place` only links into the
  VM's cache, but a site's own copy, a cache's files and an update's files keep the modes they came with. rc1 installs
  only on a GPU box, and no rehearsal leg runs the gpu profile. So llm-service keeps `no-new-privileges` but not
  `cap_drop`: a written exception in the compose file, `EXCEPTIONS`, D-1323 and H10G1-02. The GPU overlays add no
  `cap_drop` to llm-verifier (still in `OUTSIDE_THE_15`).
- **D3, a stopped reference-data load.** A limit that ran out (update's 7200 s) killed only the compose CLI: the
  one-off container went on, and its unpack stayed on objects-data, a backed-up volume. The update's and the
  installer's one-off runs are now named (`tb-refdata-load`, `tb-ruleset-import`) and removed (`docker rm -f`)
  before a run and after one that failed or timed out. A load first clears the loader's own `tb-refdata-*` folders
  (`tb_common.refdata.opened`'s prefix) from inside the container (`rm -rf -- "${TMPDIR:?}"/tb-refdata-*`), and a
  failed one gets a sweep run of its own. The update's handler now also catches the timeout itself
  (`subprocess.TimeoutExpired`, which `except UpdateFailed` missed), so the pack goes to `pending/` after a timeout.
- **D4, the stream's length.** `split_stream` compares the byte counts the container recorded with what arrived, and
  checks that the trailer is there and the dump comes first. A short or damaged stream fails the backup instead of
  being sealed as a good one.

Review B1/B2: `split_stream` now needs exactly the expected parts (the dump, rows, packs, each site copy, the exit
code): one missing or one more fails the backup; and the spool is emptied before a run, so a stale index cannot
refuse a good backup.

Not proven (no Docker daemon here): that this head's streamed nightly, its capped db `/tmp`, the rollback's folder
on db-pg and the named runs work on a box. The next CI box rehearsal is the proof for the nightly and the restic restore;
nothing in the rehearsal runs an update rollback, a timed-out load or the gpu profile.

## Findings

- **H10G1-01** (Medium): the adapter and the orchestrator cannot run read-only. The HL7 validator writes `.index.json`
  files into its package cache and renames packages there "for atomic delete"; the cache is `/opt/hl7/home`, an image
  path (`services/adapter/validate/validator.py` passes it as `-Duser.home`). The fix is in the validator: run it
  on a writable copy or a writable home seeded per image revision. Then drop the two exceptions.
- **H10G1-02** (Medium): llm-service (vLLM) still runs as root with a writable root filesystem; its compile and kernel
  caches go under `/root/.cache` and `/tmp`. For rc1 it also keeps its capabilities (no `cap_drop`): root must read
  model files of any mode. To be proved on a GPU box with the caches on a volume, a fixed user, readable weights and
  `cap_drop: [ALL]`.
- **H10G1-03** (Low): the overlay services outside the 15 are not hardened: llm-verifier (gb10, rtx5090, rtxpro6000,
  platform), the rtx5090 model-swap helpers, caddy, authelia, prometheus, the platform doctor. Each is listed with its
  reason in `OUTSIDE_THE_15`.
- **H10G1-04** (Medium): a reference data pack that fails to load at install is a stderr warning, not a failure:
  `deploy/install.sh` (the `for f in deploy/refdata/pending/*.tar` loop, the `install: warning: reference data ... not
  loaded` line) goes on, and an offline box then has no trials; the box rehearsal noticed only at its later check (CI
  run 44458900188). The load itself is fixed here (a one-off run, not `compose cp`); making the failure a FAIL line is
  left open, as it changes what install reports.
- **H10G1-05** (Medium, fixed 37250175): update's rollback (`tools/trialbox/update.py` `RESTORE_SH`) wrote the dump's
  whole plain SQL script into db's tmpfs `/tmp`, memory under db's limit. Fixed by moving the file onto the db-pg
  volume (`${PGDATA:?}/tb-rollback`), the logic as on master; the preflight counts its space. Not yet run on a box.
