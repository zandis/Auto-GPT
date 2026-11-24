# H-110: the external review pass's findings on lane H, checked on master

**Reader:** the integrator, the independent reviewer, and the people who build TrialBox

Lane H, 2026-11-24. Card H-110, with the small card H-109 inside it (the integrator's comments 7119659794 and
7118926528 on #639). The external review pass found these at old heads. Each was checked on master `8ddecb8d`. A fault
still there is fixed with a test that fails on `8ddecb8d`. A fault already gone names the merged change that removed
it. Synthetic keys, passphrases and settings only. Every new test is in `tests/unit/test_external_pass_h110.py`.

| | Finding | Verdict | Where now, and the test |
| --- | --- | --- | --- |
| (a) | the bootstrap runs a kept tree's installer, not the signed one (High) | fixed in this card | `deploy/bootstrap.sh` step 3; `test_the_installer_that_runs_from_a_kept_tree_is_the_signed_one` (the invariant), the rehearsal's `bootstrap` step |
| (b) | the launcher exits silently when the fingerprint fails | already gone | dcfbf4f8 (HS-1's review, PR #1386): `FP="$(fingerprint ...)" \|\| stop "...cannot be read..."` under pipefail; `test_a_vendor_key_that_cannot_be_read_stops_the_launcher_with_its_reason` holds it |
| (c) | the retention and audit-head job is cron-only; a PRODUCTION install dies | fixed in this card (the job); the "dies" half already gone | H-92 (PR #1388) let a PRODUCTION systemd host past the cron stop; `test_a_systemd_host_without_a_cron_daemon_runs_the_retention_from_a_timer` |
| (d) | a failed timer enable leaves units beside the cron file | already gone | d869a324 (H-92's review, PR #1388): `remove_timers` (verified, it raises) runs before `install_cron` |
| H-109 | `cron_text` raises on "IT <it@site>"; the fallback catches only OSError | already gone; the rest fixed in this card | d869a324: the fallback catches `ValueError` too, and `cron_text` never refused that address (`unit_files` did). The timer now carries it: `test_a_mailto_with_a_name_is_carried_by_the_timer_as_by_cron` |
| (e) | the start path refuses a `.env` others can write, not one they can read | fixed in this card | `tools/trialbox/launch.py` `box_file`; `test_the_start_path_refuses_a_box_file_others_can_read`, the rehearsal's `doctor` step |
| (f) | the site keys' read bits are never checked on a PoC box | fixed in this card | `deploy/check_host.sh`; `test_a_plain_site_key_others_can_read_fails_the_host_check_on_every_box`, the rehearsal's `doctor` step |
| (g) | SECRET_FAILS depends on the host check's wording | fixed in this card | kind markers; `test_each_kept_fail_class_carries_its_kind_marker_and_is_kept_by_it`, `test_the_old_fault_a_0600_key_line_that_names_its_mode_is_not_a_secret_fail` |
| (h) | no `flock` on a PoC box: no install lock | not a fault | D-1091: `deploy/install.sh` warns and lists `install-lock-flock`; none of the five |
| (i) | `stty -echo` with no trap | fixed in this card | the KEK-INPUT block; `test_a_signal_at_the_passphrase_prompt_gives_the_terminal_its_echo_back` |
| (j) | the host restore takes no lock; passwords as `-e NAME` | lock already gone; `-e NAME` not a fault | 8480a690 (H-100's re-review R7, PR #1421): `restore.lock` under `flock`; see below |
| (k) | the peak disk count | still open as H95-02 | no fix guessed; it waits for the bench's measurement |
| (l) | a rotation to the same passphrase is allowed | fixed in this card | `tools/keys.py` `new_kek`; `test_a_rotation_to_the_passphrase_the_box_is_sealed_under_is_refused` |

## (a) The installer that runs is the signed one

**The fault.** The vendor key's signature covers the bundle's manifest, and the manifest covers the host tree by its
sha256. When `/opt/trialbox` already held a tree, the bootstrap printed "kept" and ran that tree's
`deploy/box-install.sh` (with `--box`) or `deploy/install.sh`. Whatever those files held ran as root. Before the
signed tree replaced it, `install.sh` also ran the kept tree's `tools/apply_update.sh` and its other tools. A tree
changed after an install was not covered by the signature that IT had confirmed.

**Now (the integrator's ruling 7119913331).** The installer that runs is always the signed release's own. A kept tree
is the site's data, never its code. The bootstrap compares the kept tree with the checked host tar: each signed file
must be there with its bytes, links followed, and no code may sit beside them (under the two library folders, or a
module, a package folder or a `.pth` file at the top that a `python3` started there would import). Since the review of
#1455 (1455-1) the bytes checked are also the bytes used: each signed file, read through any link, is inside the tree,
and it and every folder down to it are owned by root alone (no group or other write); the folders above the tree are
root's, or shared only with the sticky bit. The bytecode caches in the two library folders are removed before the
compare, never through a link: `python3` would run a cache in place of its signed source.

* When the kept tree is exactly this release, it runs as before ("kept").
* When it is not, none of its code runs. The bootstrap first brings the signed release in. It does so with the
  release's own host-tree module, read from the checked tar (`install` of `tools/host_tree.py`, which `trialbox update`
  uses too). That puts the release at `releases/<bundle id>` and switches `current` to it. It links the release files
  through `current`, and moves each changed file of the kept tree to `releases/.replaced-<time>/`, never deleting it.
  The site's own files in `deploy/` (`.env`, settings, keys, the site folder) are not touched. The tree is then
  compared again. Only when it matches does the now-signed installer run.
* A module or package planted at the top is no release path, so it stays. Then nothing runs (H-94 (1): only the signed
  files run).
* A bundle older than the release the box records (`deploy/updates/installed.json`, `release_seq`) is never brought
  in. The box keeps its code. This is the update path's own rule.

So a fresh bundle over a kept tree (the bench walk's re-install) keeps working. It is the signed release's installer
that runs it now.

**What changes for a site.** The release is switched before the installer's own early checks, not at its load step.
An install that then stops early leaves the new release's files in place, with the old images, as an install that
stopped after its load does. Re-running the same command goes on from there.

**The harm the rehearsal holds.** The `bootstrap` step runs the real bootstrap on the media. The second run keeps the
tree and runs its installer. Then it plants a `box-install.sh` and an `install.sh` that would leave a mark. The
bootstrap brings the signed release in and the signed installer runs. The planted files are set aside and the mark is
never made.

**How the test reads the module.** `tests/unit/test_install_bootstrap.py` asserted that the bootstrap names no host
tree path. By the integrator's ruling 7122559749 the module's path is written plainly, and the assertion allows exactly
that one read from the verified tar (see "Changed assertions" below). The bootstrap still needs only what Ubuntu 24.04
has, because the module is in the verified bundle.

**An older box reinstalled by a newer bootstrap (the integrator's line 7126867935).** On master the bootstrap ran a
kept tree's own installer, so a box installed from a release before H-96 answered the new bundle's
`--kek-passphrase-file` with `install: unknown option --kek-passphrase-file` (exit 2) and could not be reinstalled.
With (a) the older tree is brought up to the signed release first and the signed installer runs.
`tests/unit/test_bootstrap_upgrade_h110.py` installs release N-1 (its installer is the real option parser of
`83e444bb~1`, `tests/fixtures/h110/install_n1_options.txt`) and reinstalls it with release N's bootstrap and
`--kek-passphrase-file`, with and without `--box`; it fails with master's `deploy/bootstrap.sh` on exactly that
message. The rehearsal from a real release N-1 is its own card.

## (c) The retention job on a systemd host with no cron daemon

On a systemd host whose cron daemon does not run (no cron folder, or no `cron` or `crond` service active), the install
writes `trialbox-retention.service` and `.timer` (00:20 daily, `Persistent=true`). The service runs the cron line's
own command. It enables the timer and removes a cron file left there: one schedule, never both, as H-92's backup. The
host check takes either timer in place of its cron file. A warned anchor folder takes the signed head out of the
timer's service too, in `deploy/install.sh`, `deploy/box-install.sh` and `deploy/settings_guard.sh`. A timer that
cannot be enabled is a warning, as the cron line was on such a host. Elsewhere a cron file with no running cron
daemon is a new `stop_or_warn cron-daemon` (M-SC-3, below): PRODUCTION stops, a PoC box warns.

## (e), (f) A secret where others can read it

`box_file` refused a `deploy/.env` only when group or others could write it. It now refuses one that they can read
too (H-94 (5), every box). The host check FAILs a plain site key whose mode gives group or others any bit, on every
box and profile. The install's `tb_kept_fails` keeps that line, so a PoC install ends 1 on it.

## (g) A kept line is kept by its kind, not its words

**The fault.** `tb_kept_fails` kept a host check FAIL line by its words: a FAIL line that said "mode" and named a
secret, or one of a list of phrases. Before this card, the unsealed-key line read "site_hmac.key is a plain file (mode
600)". On a VALIDATION box without the poc profile it was kept as a secret others can read, although only root could
read the key. So a PoC install ended 1 for a fault that is none of the five. Reworded lines would have gone the other
way and been dropped.

**Now (the integrator's ruling 7119913331).** `deploy/check_host.sh` writes the kind where it makes each such line
(`kept N "..."`, which ends the line with `[H-94 (N)]`):

* (5): `.env` mode, and a plain key's mode (f);
* (2): the 64 GB class, the GB10 profile on another architecture, the GB10 driver, the container toolkit, no
  `nvidia-smi`, and free space below 10 %. The image lock's driver FAILs (`tools/images_lock.py`) carry no marker:
  `deploy/install.sh` already stops on them, before anything, with its GPU check (H-94 (2)), and H-89's test holds
  their bytes;
* (3): the poc profile on a PRODUCTION box.

`tb_kept_fails`, the same lines in the five scripts that carry the helper, keeps a FAIL line by that marker alone. The
install's own closing sentence drops the marker, so it reads as before. The unsealed-key line names no mode now and
carries no marker.

**Changed test data (the ruling's terms).** No assertion changed.

* The stand-in host checks print the marker on their kept lines, as `deploy/check_host.sh` does now:
  `tests/unit/test_poc_stops_bench_h94.py` `HOST_CHECK` (the `.env` mode line and the free-space line), and
  `tests/unit/test_poc_stops_h94.py` (the `hostcheck` stand-in, the same two lines).
* The new tests assert the marker for each FAIL class the bench can make (5, 3, 2). A further test pins the old fault:
  the "(mode 600)" line is not kept.

## (j) The restore's passwords as `-e NAME`

Each value is in the environment of the container command only, never on its command line. Docker keeps a container's
environment in its configuration while the container exists. Only root and the docker group can read that, and they
can already read the box's `deploy/.env`. This is not a new exposure to anyone. This card changes nothing there.

## (k) The peak disk count

The external pass says that a load holds the archive and the unpacked layers at once, and that the containerd store
keeps both. That is H-95's own open finding H95-02 (not measured). Counting images twice would guess. A wrong guess
there is a stop on every box (H-94 (2)). It waits for the bench's measurement through the integrator.

## (l) A rotation to the same passphrase

`new_kek` derived the new KEK with a fresh salt, so the same passphrase gave a new KEK id and a rotation audit event.
The old, exposed passphrase still opened the box. A new passphrase that derives the old KEK under the old `kek.json`
is now refused. The same file given twice is caught the same way. The rotation is rolled back, as any failure before
its commit.

## (i) The prompt's echo

The KEK-INPUT block (the same lines in `deploy/install.sh`, `deploy/box-install.sh` and
`deploy/hardening/seal_keys.sh`) traps HUP, INT and TERM around the prompt. Each trap turns the echo back on, then
sends the signal again with its default, so the script ends as before. The traps are reset after the prompt. Every
caller asks before it sets traps of its own.

## The whole-repo sweep's items (the integrator's routing 7120987904)

Checked on the branch, from master `8ddecb8d`. Every new test is in the same file as the card's tests and fails with
master's version of its file swapped in.

| Item | Verdict | The fix, and the test |
| --- | --- | --- |
| M-IB-1 | fixed in this card | (a) above |
| M-IB-2 `.env` rewritten in place | fixed in this card | `tools/box/__main__.py` `write_private`: a new file 0600 from its first byte, on disk, renamed over the old one, its owner kept; `test_the_box_settings_are_replaced_whole_never_rewritten_in_place` |
| M-LH-1 `.env` mode checked, not its owner | fixed in this card | `deploy/check_host.sh`: another user's `.env`, a link or a second hard link FAILs `[H-94 (5)]`; the install `chown`s it to root; `test_a_box_file_not_roots_alone_fails_the_host_check_whatever_its_mode` |
| M-LH-2 the override's folders | fixed in this card | the install uses a copy in `deploy/site` (0644), never the caller's file; `deploy/settings_guard.sh` checks every `COMPOSE_FILE` file and each folder above it before each start (PRODUCTION refuses, a PoC box warns); `test_the_override_root_reads_later_is_a_copy_in_deploy_site`, `test_every_start_refuses_a_compose_file_in_a_folder_others_can_write` |
| M-BK-1 `sign_bundle keygen` overwrites | fixed in this card | the command refuses a folder that holds a pair, unless `--force` (the library call stays as the tests use it); the private key `O_EXCL` 0600; `test_a_vendor_key_is_never_replaced_and_is_private_from_its_first_byte` |
| M-SC-1 egress `apply` races | fixed in this card | `deploy/egress.py`: a temp file of the run's own, on disk before the rename, and one lock around `apply` and `save`; `test_two_applies_at_once_never_break_the_state_file`, `test_apply_and_save_take_the_one_lock_before_anything`, `test_a_second_apply_waits_for_the_first` |
| M-SC-2 no systemd: nothing restores egress at boot | fixed in this card | `stop_or_warn egress-at-boot`: PRODUCTION stops, a PoC box warns and lists it (the integrator's ruling 7122559749); `test_a_host_without_systemd_is_told_nothing_restores_egress_at_boot[PRODUCTION stops, PoC box warns]` |
| M-SC-3 retention needs a running cron | fixed in this card | the timer on a systemd host ((c)); elsewhere a cron file with no cron daemon is `stop_or_warn cron-daemon` (PRODUCTION stops, a PoC box warns); `test_a_cron_folder_with_no_cron_daemon_is_said` |
| L-IB-1 | fixed in this card | (i) above |
| L-IB-2 a caller's `TB_VENDOR_PUBKEY` | fixed in this card | `deploy/install.sh` and `tools/apply_update.sh` refuse one that is not the key in deploy/keys (H-94 (1)); `test_a_callers_vendor_key_never_stands_in_for_the_boxs` |
| L-BK-1 the backup private key made 0644 | fixed in this card | `tools/trialbox/backup.py`: `O_EXCL` 0600; `test_the_backup_private_key_is_made_0600_and_only_once` |
| L-CI-1 prompts and model cards taken for documents | fixed in this card | `tools/ci_docs_only.py` `CODE_READS`; `test_a_prompt_or_a_model_card_is_never_a_documents_only_change` |
| L-RR-1 a product name in a shipped script | fixed in this card | `deploy/gcp/setup-gcp.sh` and `docs/VALIDATION.md` name the role, not the product; no test |

| 1396-1 (High, second half) a model pair that cannot be put back only warned on a PoC box | fixed in this card | `deploy/install.sh`: the line is kept with the host check's kept lines (H-94 (2)): a PoC box ends 1 with it last, as PRODUCTION did; `test_a_model_pair_that_cannot_be_put_back_ends_the_install_1_with_its_line_last` (PoC: exit 0 on master; it proves the exit code and the last line, not the summary before them) |
| ESC-5 backup-install rewrites `.env` in place (ledger 7122384787) | fixed in this card | `tools/trialbox/backup_schedule.py` `set_env` and the box's `merge_env` use one helper, `tools/trialbox/private_file.py` `replace_private` (0600 from the first byte, on disk, renamed); `test_the_box_settings_are_replaced_whole_never_rewritten_in_place` for each caller |
| GP-PL-1 the spool maps only `--dbname` (7121587090) | fixed in this card | `tools/trialbox/platform_day2.py` `spool_args`: `--dbname X`, `--dbname=X`, `-d X`, `-dX` and a positional connection (a URI, a key=value string) are each mapped to the job's variable or refused; `test_the_spool_never_writes_the_jobs_connection_in_any_form`, `test_the_spool_refuses_any_other_connection_in_any_form` |

**The ticker and the embedder test's bound (the integrator's 7120213053).** The 120 s timeout in
`tests/unit/test_poc_real_embedder.py` dated from #1129. It was a hang guard, not a measurement.

* **Measured.** One `deploy/poc.sh` call takes 0.0-0.1 s alone. Under `-n auto` on the seven poc test files (three runs,
  111 calls), the median was 0.1 s, p95 0.1 s and the maximum 0.2 s.
* **The cause of the hang.** `alive_start`'s sleep inherited the caller's stdout and stderr. A stop whose TERM landed
  before `s=$!` left that sleep running: 37 of 3000 start/stop pairs here. A caller reading the output then waited
  for it.
* **The fix.** The sleep holds none of the caller's pipes now, in `deploy/poc.sh` and in `deploy/install.sh` (the
  same pattern). Test: `test_a_ticker_a_stop_orphans_never_holds_the_callers_output`, 1000 pairs per script, which
  return at once.
* **Changed test data.** The bound is 30 s (150 times the measured maximum), with the measurement written beside it.

**Every other Python writer of `deploy/.env` uses the same helper.** `tools/trialbox/memcaps.py` and
`tools/trialbox/pgsize.py` rewrote it in place; the install runs both with `--write`. `tools/image_pins.py`
`write_env` used a fixed temp name and no fsync. All three now call `replace_private`, and
`test_the_box_settings_are_replaced_whole_never_rewritten_in_place` covers all five callers. Each case fails with
its master file. `tools/trialbox/finish_check.py` `_write_env` was already sound (`mkstemp`, then rename).

**Low, listed and not changed: the shell's `sed -i` lines.** These are in `deploy/install.sh`, `deploy/poc.sh` and
the GCP driver. GNU `sed -i` writes a temp file and renames it, so a cut leaves the old file or the new one. It does
not fsync, though, and the temp file takes the old file's mode. The `>>` lines append.

**The integrator's rulings (7122559749), and what they changed.** Four rulings, applied as follows.

* M-SC-2 and M-SC-3 stop on PRODUCTION and warn on a PoC box. Two new keys, `egress-at-boot` and `cron-daemon`; both
  are rows on H-94's page and not driven (root only).
* 1396-1's second half is kind 2: the fix stands, and it stops on every box.
* 1396-2 (the install lock on a PoC box) and 1421-4 (`-e NAME`) are not faults. 1421-4 holds on one condition: the
  restore container runs with `--rm`, so its environment does not outlive it in the engine's inspect.
  `test_the_restore_container_is_removed_when_it_ends_and_its_passwords_are_on_no_command_line` holds that; it fails
  when `--rm` is taken out. `tools/trialbox/box_restore.py` is not changed here.
* The bootstrap reads `tools/host_tree.py` from the verified tar, with its path written plainly.
  `tests/unit/test_install_bootstrap.py` allows that one read, and nothing else under `tools/`.
* H-BK-1 stays with its own card. `deploy/hardening/seal_keys.sh` changed here only in its KEK-INPUT lines, for (i),
  because a test holds the three copies identical.

**Changed assertions, every one in this card.** Four assertions changed (by the integrator's rulings 7122559749 and
7128436810), and one test asserts less text than it claimed (1455-7).

* `tests/fixtures/h94/install_sh_master_stops.json`: four new messages: M-SC-2's and M-SC-3's (7122559749), and
  1455-8's two, `retention-timer` and `cron-daemon-unknown` (7128436810), each its PRODUCTION row (rc 1).
* `test_every_start_refuses_a_compose_file_in_a_folder_others_can_write[TEST]` (7128436810): rc 0 with a warning
  becomes rc 1 with the refusal's words.
* `test_it_needs_only_what_a_bare_ubuntu_has` (in `tests/unit/test_install_bootstrap.py`): "no `tools/` in the script"
  becomes "no `tools/` but the one read of the release's host-tree module from the verified tar". The comment
  allowance the review of #1455 found (1455-7) is gone: the bootstrap's comment no longer names the path.
* The 1396-1 test appended its own "TrialBox is ready" line and asserted it absent; install.sh never prints that
  line. The line and its assertion are gone, and the test is named for what it holds: the exit code and the last line.

**Changed test data.** Seven kinds, none of them an assertion.

* `tests/unit/test_poc_stops_h94.py` `NOT_DRIVEN`: four new keys, `egress-at-boot`, `cron-daemon`, `retention-timer`
  and `cron-daemon-unknown` (root only).
* `tests/unit/test_backup_schedule_timer.py`: its install.sh harness gets a units folder (`SYSTEMD_DIR`), as a
  systemd host has; without one, 1455-8's `retention-timer` stop fires there. Its assertions are unchanged.
* `tools/support_bundle.py` `NOT_SECRETS` (outside the card): `PINNED_KEY`, install.sh's path of the vendor's public key, which holds no secret.
* `tests/unit/test_poc_stops_bench_h94.py`: the bench's stand-ins gain `pgrep`, a host whose cron daemon runs, as a
  site's does. Without one the new `cron-daemon` stop fires on every bench run. The rehearsal (a container with no
  cron daemon) expects that one line exactly when none runs there. It no longer accepts a `compose-file-owner` line
  at all (1455-2 (A)): its work dir is root's while the box runs.
* The H-94 stand-in host checks print the `[H-94 (N)]` marker, as in (g).
* Fixture modes: 0600 in `tests/unit/test_host_commands_own_environment.py` and `tests/unit/test_host_baseline.py`.
* `tests/unit/test_poc_real_embedder.py`: the timeout 120 s becomes 30 s, with the measurement beside it.

**Not done here.** Two rows only.

* L-IB-2 on a box with no key in deploy/keys. The bootstrap always places that key; a box with none still takes the
  caller's key, as before.
* 1421-3 and 1409-2 are with the H-114 worker. ESC-4 is not this card's.

## The review of #1455 at `26ab7d4a` (verdict 7125919328)

High 1, Medium 1, Low 6, all of lane H. All are fixed. Each fix has a test that fails with the `26ab7d4a` version of its file and
passes now. The reviewer's patches for the Lows are applied as given, with two test fixes: run as root, a file is
already root's, so the key-owner and owner-hand-off tests give the file a third uid first.

| | Finding | Verdict | The fix, and the test |
| --- | --- | --- | --- |
| 1455-1 | a kept tree's package at the top, or a bytecode cache, ran as root; the bytes checked were not the bytes used (High) | fixed | `deploy/bootstrap.sh` `kept_diff`, see (a); `tests/unit/test_ocr1455_kept_code.py`: `test_no_code_a_kept_tree_holds_runs_under_the_signed_installer` (2), `test_a_cache_folder_that_is_a_link_out_of_the_tree_never_runs`, `test_a_signed_file_another_user_could_change_is_never_what_runs` (3) |
| 1455-2 (A) | a PoC start warns, then runs a compose file in a folder others can write (Medium) | fixed (the integrator's ruling 7128436810) | `deploy/settings_guard.sh`: a stop on every box, H-94 (1); `deploy/install.sh` copies a compose file from outside the tree into `deploy/site` and starts only from there; the rehearsal's work dir is root's while the box runs (`tools/rehearse_box/rehearse.sh`) and its filter no longer accepts the line (`tools/rehearse_box/box.sh`); `test_every_start_refuses_a_compose_file_in_a_folder_others_can_write[TEST]` (rc 0 becomes rc 1 with the refusal's words, as ruled), `test_the_install_starts_only_from_compose_files_in_its_tree`; the integrator's conditions 7129418551: `test_the_copy_of_an_outside_compose_file_is_roots`, `test_the_copy_is_refreshed_from_the_source_at_each_install`, `test_the_original_of_a_copied_compose_file_is_never_what_starts` |
| 1455-2 (B) | the install checked the override by name, then copied it by name (Medium) | fixed | `deploy/install.sh`: opened once, checked through the open file, copied from it, written whole and renamed; `test_the_override_copied_is_the_file_that_was_checked`, `test_the_override_s_owner_and_mode_are_those_of_the_file_copied` |
| 1455-3 | a plain key another user owns passed at 0600 (Low) | fixed | `deploy/check_host.sh` `kept 5`; `tests/unit/test_ocr1455_key_owner.py` |
| 1455-4 | a signal that ends the script left the ticker holding the caller's pipe (Low) | fixed | `deploy/poc.sh`, `deploy/install.sh`; `tests/unit/test_ocr1455_ticker_signals.py` (6) |
| 1455-5 | the secrets rotation wrote `.env` without the helper; the helper handed a non-root owner on (Low) | fixed | `tools/trialbox/svc_secrets.py`, `tools/trialbox/private_file.py`; `tests/unit/test_ocr1455_env_writers.py` (2) |
| 1455-6 | the vendor keygen's check and its replace were two steps (Low) | fixed | `tools/sign_bundle.py`; `tests/unit/test_ocr1455_vendor_keygen_race.py` |
| 1455-7 | claims and tests that said more than they held (Low) | fixed | this page, the 1396-1 test, the bootstrap test's allowance; the PR body's L-RR-1 row has no test |
| 1455-8 | the timer that cannot be enabled only warns on PRODUCTION; no `pgrep` is silent (Low) | fixed (the integrator's ruling 7128436810) | `stop_or_warn retention-timer` and `stop_or_warn cron-daemon-unknown` (PRODUCTION stops, a PoC box warns); the H-94 fixture gains their two messages, `NOT_DRIVEN` the two keys (root only); `test_a_retention_timer_that_cannot_be_installed_is_a_stop_on_production` (2), `test_a_host_without_pgrep_is_told_its_cron_daemon_cannot_be_checked` (2) |
| 7126867935 | an older box could not be reinstalled by a newer bootstrap (`--kek-passphrase-file`) | fixed by (a) | see (a); `tests/unit/test_bootstrap_upgrade_h110.py` |
| H106-14 / 1452-12 | the heartbeat's sleep held the caller's output; its subshell and sleep held the lock fds 9 and 6 | fixed here (the integrator's 7131125435, 7131128250: the heartbeat fix lives in #1455 only) | `deploy/install.sh`, `deploy/poc.sh`; #1452's `test_h106_14_the_heartbeat_s_sleep_never_holds_the_caller_s_output`, `test_h106_14_the_poc_heartbeat_s_sleep_never_holds_the_caller_s_output`, and `test_the_heartbeat_holds_no_lock_fd_of_the_caller` (2), in `tests/unit/test_ocr1455_ticker_signals.py` |
| the rehearsal red of 04699392 (job 138393178803) | the engine probe made its folder in the work dir, root's while the box runs | fixed | `tools/rehearse_box/rehearse.sh`: in the run folder; `tests/unit/test_rehearsal_work_dir_owner_h110.py` (2) |

**What 1455-1's fix does not cover.** A folder at the top with no `__init__` file is a namespace package. It cannot
shadow a module that exists elsewhere, but it can supply one that does not. No TrialBox tool imports a name that is
missing on a box, so this is noted, not fixed. The folders above the tree accept a shared folder with the sticky bit
(`/tmp`), as `kp_read_file` does.

**Changed assertions (the integrator's ruling 7128436810).** `test_every_start_refuses_a_compose_file_in_a_folder_others_can_write[TEST]`: rc 0 with a warning becomes rc 1 with the refusal. `tests/fixtures/h94/install_sh_master_stops.json` gains 1455-8's two messages; `NOT_DRIVEN` gains `retention-timer` and `cron-daemon-unknown`.

**What the rehearsal changes.** The work dir is the box host's bind mount, owned by the runner; every folder above it in the box host is the container's own. `host_up` makes it root's (0755) while the box runs, and teardown gives it back before the report is written. A run killed before teardown leaves it root's: remove it as root.

**Files outside the card.** `tools/trialbox/svc_secrets.py` (1455-5, the reviewer's patch, its body only).

## The re-review of #1455 at `973a87aa` (verdict 7135580046)

High 1, Medium 1, Low 1. Each fix has a test that fails with the `973a87aa` version of its file.

| | Finding | Verdict | The fix, and the test |
| --- | --- | --- | --- |
| 1455-1 (residual) | code on the installers' python path that the bootstrap never compared still ran as root: a `services/` folder at the top (the box preflight's PYTHONPATH), or a module in `deploy/hardening/` (`host_tier.py` run by path) (High) | fixed (the reviewer's patch) | `deploy/bootstrap.sh` `kept_diff` also looks in every release folder outside the two library folders that holds a signed script: an unsigned module, package or cache folder there is a difference; `deploy/box-install.sh`'s preflight no longer puts `services/` on root's path (the release holds none); `tests/unit/test_ocr1455_services_path.py` (2) |
| 1455-9 | the compose copies reused fd 6, the fd #1452's host lock is held on: the first `exec 6<` dropped the lock (Medium) | fixed | `deploy/install.sh`: the override and the copy loop open their file on a descriptor bash picks (10 or above), never 6 or 9; `tests/unit/test_ocr1455_host_lock_fd.py` (the reviewer's test, with a case for fd 9 too: 2) |
| 1455-10 | the page and the body said less than the push changed (Low) | fixed on the page; the body is the lead's | this page's lists of changed assertions and test data; the copy loop's warning says what happens (a file it could not copy is used where it lies, and refused at the start unless root's alone) |

**LR-18 (High, Lane LR's lifecycle review; routed into #1455 by the integrator's 7136231344).** The bootstrap switched
`current` to the new release before the bundle was verified whole, loaded or given a rollback point. The update path
then recorded the new release as the one before (a failed update rolled images back to N-1 and the tree "back" to
N), and a stop before the load left N's tree over N-1's images with no marker. Fixed:

* `deploy/bootstrap.sh` stages the release (`tools/host_tree.py` `stage`: `releases/<bundle id>` with its site
  paths linked back to the box) and switches nothing. The staged release is compared with the signed tar; the box's
  top must hold no code the release lacks (the switch never moves such a file aside). The staged release's
  installer runs.
* `deploy/install.sh`, `deploy/box-install.sh` and `tools/apply_update.sh` tell a staged run from their own path
  (`<box>/releases/<id>/...`): the code is the staged release's, the box is two folders up. The install lock, the
  `current` checks, the space check and the re-run from the signed tree use the box; `apply_update.sh` gives the
  update `--deploy <box>/deploy`, so its host-tree step records the release the box ran and is the one switch.
  `box-install.sh` goes on from the box once its install step has switched it.
* Test: `tests/unit/test_bootstrap_upgrade_h110.py`, `test_a_running_box_stays_on_its_release_until_the_update_step_switches`
  (a box from N-1 in the host-tree layout; N's installer stops before any load: `current` still names N-1, at its
  start and after). It fails with master's and with `973a87aa`'s `deploy/bootstrap.sh`.
* Changed assertions of this PR's own tests (none on master): the (a) invariant test, the part-3 test and the
  upgrade test now expect the staged release to run and the box unswitched; the planted-module test expects the
  top-code refusal's words. The rehearsal's bootstrap step expects `staged:`, the installer run from
  `releases/<id>`, and no `current`.
* Not done here: an end-to-end update from a real N-1 box (LR-19, LR-20: their own cards).

**The key-owner rule, shared with H-133 (the integrator's ruling 7141781119).** The rehearsal's `test-boxes` step
went red at `a1b4e62c` (job 138679012027): a test box's keys are never sealed (H-106), and the services make them in
the secrets volume as uid 10001, so 1455-3's owner check (root or the installer only) failed both. The one rule now
sits in D-1461 (item 7) and once in the code, `tb_common.kek.key_owner_allowed` with `SERVICES_UID`: a key file is
root's, the services', or the running account's, no one else's, mode 0600. `deploy/check_host.sh` and H-133's
`services_owner()` read it there. Tests, in `tests/unit/test_ocr1455_key_owner.py`:
`test_the_services_uid_of_the_rule_is_the_compose_file_s_user` (the constant equals the user of every service that
mounts the secrets volume; a moved uid fails), `test_the_host_check_and_the_hand_over_read_one_rule` (root, the
services, another uid: the host check and the hand-over give the same verdict) and
`test_a_plain_site_key_the_services_own_passes_the_owner_check`. The real path: the rehearsal's `test-boxes` step.

**What is not covered.** A script root runs later from the kept paths (a cron or systemd job, `apply_update.sh`'s
`ospatch.py`) is covered by the bootstrap's walk at the bootstrap only. Two outside compose files with one base name
would share one copy's name; the only one that can reach the copy loop is the override whose own copy failed.

## Tests, mutants and what was not run

Each new test fails with master's version of its file swapped in, and passes now. (b)'s test passes on master. Test
fixtures changed (their modes only, no assertion): `tests/unit/test_host_commands_own_environment.py` writes its box
`.env` at 0600, and `tests/unit/test_host_baseline.py` writes its plain keys at 0600. The stand-in host checks of
(g) are listed above.

**Not run here.** The rehearsal job (no Docker daemon in this session), so its three new cases have not run. A real
systemd host for the retention timer: the test runs install.sh's own lines with a systemctl stand-in. The whole unit
and integration runs, which CI runs.
