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
module or `.pth` file at the top that a `python3` started there would import).

* When the kept tree is exactly this release, it runs as before ("kept").
* When it is not, none of its code runs. The bootstrap first brings the signed release in. It does so with the
  release's own host-tree module, read from the checked tar (`install` of `tools/host_tree.py`, which `trialbox update`
  uses too). That puts the release at `releases/<bundle id>` and switches `current` to it. It links the release files
  through `current`, and moves each changed file of the kept tree to `releases/.replaced-<time>/`, never deleting it.
  The site's own files in `deploy/` (`.env`, settings, keys, the site folder) are not touched. The tree is then
  compared again. Only when it matches does the now-signed installer run.
* A module planted at the top is no release path, so it stays. Then nothing runs (H-94 (1): only the signed files run).
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

**How the test reads the module.** `tests/unit/test_install_bootstrap.py` asserts that the bootstrap names no host
tree path. The module's member name is built from its two parts, so that assertion holds unchanged. The bootstrap
still needs only what Ubuntu 24.04 has, because the module is in the verified bundle.

## (c) The retention job on a systemd host with no cron daemon

On a systemd host whose cron daemon does not run (no cron folder, or no `cron` or `crond` service active), the install
writes `trialbox-retention.service` and `.timer` (00:20 daily, `Persistent=true`). The service runs the cron line's
own command. It enables the timer and removes a cron file left there: one schedule, never both, as H-92's backup. The
host check takes either timer in place of its cron file. A warned anchor folder takes the signed head out of the
timer's service too, in `deploy/install.sh`, `deploy/box-install.sh` and `deploy/settings_guard.sh`. A timer that
cannot be enabled is a warning, as the cron line was on such a host. No new stop was added.

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
  `nvidia-smi`, free space below 10 %, and the image lock's driver FAILs (marked where the host check passes them on);
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

## Tests, mutants and what was not run

Each new test fails with master's version of its file swapped in, and passes now. (b)'s test passes on master. Test
fixtures changed (their modes only, no assertion): `tests/unit/test_host_commands_own_environment.py` writes its box
`.env` at 0600, and `tests/unit/test_host_baseline.py` writes its plain keys at 0600. The stand-in host checks of
(g) are listed above.

**Not run here.** The rehearsal job (no Docker daemon in this session), so its three new cases have not run. A real
systemd host for the retention timer: the test runs install.sh's own lines with a systemctl stand-in. The whole unit
and integration runs, which CI runs.
