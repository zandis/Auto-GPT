# H-132: the lifecycle review's data-loss findings, fixed

**Reader:** the people who build TrialBox: lane H and the integrator.

**Card:** H-132 (lane H; the integrator's ruling 7136231344, item 1).
**Date:** 2026-11-24. **Base:** master `00bababf8f57df6143b7b47fd36f4c15f5b29e5f`.
**Source:** lane LR's review, `docs/reviews/lifecycle-deep-review-2026-11-24.md` (pull request #1474, not merged).
**Findings:** [`lifecycle-data-loss-h132-2026-11-24/findings.json`](lifecycle-data-loss-h132-2026-11-24/findings.json)
(card H132).

The rule of every fix: never delete what this run did not make, or what is not proven safe to delete; put back
before removing; a refusal changes nothing. Each finding has a test in `tests/unit/test_lifecycle_data_loss_h132.py`
that fails on `00bababf` and passes here, and names the cell of the review's matrix it turns green.

## What was fixed

| LR | Place | Test | Matrix cell |
| --- | --- | --- | --- |
| LR-1 | `tools/trialbox/backup.py`, `_put_back`, `_set_aside_refusal` | `test_lr1_a_folder_that_cannot_be_renamed_aside_is_never_removed_by_the_put_back`, `test_lr1_a_mount_point_target_is_refused_before_the_first_change` | restore, in the container / folder is a mount point / none |
| LR-11 | `tools/trialbox/update.py`, `undo_load`, `load_scope`, `TarWatch`, `stream_image` | `test_lr11_the_undo_of_a_failed_load_touches_only_what_the_archive_made`, `test_lr11_a_record_that_names_no_scope_removes_nothing`, `test_lr11_the_scope_is_read_from_the_bytes_handed_to_the_load` | update, from the shell / N, engine shared / failed load |
| LR-13 | `tools/trialbox/box_restore.py`, `_call`, `_line`, `sweep`, `no_restore_container`, `RESTORE_NAME` | `test_lr13_a_hangup_with_the_terminal_gone_still_tells_the_container_and_waits_for_it`, `test_lr13_a_second_restore_is_refused_while_the_first_ones_container_exists`, `test_lr13_the_restore_container_has_one_fixed_name` | restore, on the host / fresh / HUP (terminal gone); the sweep half of "fresh / KILL" |
| LR-15 | `tools/trialbox/box_restore.py`, `volume_folder`, `data_folders` | `test_lr15_a_data_root_elsewhere_is_asked_of_the_engine`, `test_lr15_no_folder_of_the_box_found_is_refused_before_anything_stops` | restore, on the host / Docker root not the default / none |
| LR-16 | `tools/trialbox/restic_repo.py` (`--no-lock`), `tools/trialbox/launch.py` (`beside`), runbook 5 and 22 | `test_lr16_a_restic_lake_restores_from_a_repository_bound_read_only`, `test_lr16_backup_verify_sees_the_files_beside_the_backup`, `test_lr16_the_runbook_names_how_a_restic_backup_is_opened` | restore, on the host / KEK TPM, KEK file, restic backup / none (stand-in restic) |

**LR-1.** The put-back of a failed restore removed the target folder whenever it existed, even when the rename
aside had never happened: every file of the original went. It now removes a folder only when its aside exists (the
original is safe) or when there was nothing to set aside. A target that is a mount point, or on another filesystem
than its parent, cannot be renamed within it: refused before the first change, with the way out named.

**LR-11.** The undo of a streamed image load compared the whole engine with its record and removed every image that
was not there before. It now undoes only what this load can have made: the archive's pinned tags and its config and
manifest digests, what `docker load` said it loaded, and the tags and digests named in the very bytes handed to the
load (`TarWatch`: an archive swapped on the stick after its pins were read names its own tags there). The scope is
written into the rollback point before the bytes go, so the undo after a kill is scoped too. A record written before
this fix names no scope: nothing is removed, and the rollback's retag of the pinned tags stands.

**LR-13.** On a hang-up with the terminal gone, the line printed before the signal was passed on raised, so the
restore container was never told and ran on while the lock was released. The signal now goes first, and a line
that cannot be written never ends the wait. The restore container has one fixed name, and a second restore is
refused (nothing stopped, nothing swept) while a container of that name exists. The sweep of `deploy/.restore-*`
now runs after the early checks, under the lock.

**LR-15.** Each volume's folder is asked of the engine (`docker volume inspect`); the box file's
`TB_DOCKER_VOLUMES`, else the default, only when the engine names none. A volume the engine knows whose folder is
not there, or no folder of the box found at all, is refused before anything stops.

**LR-16.** (a) Runbook 5 (a new paragraph before "Secrets", so no line another page quotes moves) and runbook 22 (steps 3 and 4) name `--restic-from-box` and
`--restic-share`. (b) `backup-verify` mounts the backup's folder read-only besides the file, so the sidecar, the
repository and its escrow file are there. (c) The restic restore passes `--no-lock`: a restore only reads, and the
host binds the repository read-only.

## Not fixed here

- **LR-2** (`deploy/poc.sh reset` on an installed box) and **LR-10** (`rollback` after the check) wait for answers:
  `deploy/poc.sh` is lane R's file, and LR-10 changes what `tools/update_drill.py` case 7 asserts.
- LR-13's KILL half that is LR-38 (nothing at boot reads the restore's work folder) is not this card.
- LR-16 (c) is shown against a stand-in restic that models the lock rule, not the real binary (not installed here).
- LR-15's container half: a container started by hand with `--services-stopped` and no `--dir` still falls back to
  the default volume paths inside it; the host never starts it so.

## Files outside the card

- `tests/unit/test_restore_from_the_host_h100.py:180` (one assertion widened to the engine's two read-only queries)
  only with the integrator's ruling; asked as a `question:`.
