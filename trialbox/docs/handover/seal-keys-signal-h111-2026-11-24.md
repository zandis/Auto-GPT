# H-111: a signal during the TPM seal no longer destroys the only KEK (H-BK-1)

**Reader:** the integrator, the independent reviewer, and the people who build TrialBox

Lane H, 2026-11-24. External review H-BK-1 (High, keys; comment 7120476442, routed in 7120987904). A High on the
key path: it rides alone. Synthetic keys only; no TPM was used (the review host has none).

## The fault

`deploy/hardening/seal_keys.sh`, `KEK_BACKEND=tpm`, a box with no `kek.json` and plain site keys. The script set a
trap that shredded the new KEK and removed the new credential on `EXIT INT TERM HUP`, ran `tools.keys init` (it
writes `kek.json`, wraps each key under the new KEK and removes the plain file), and only then moved the sealed
credential into place. A SIGTERM, SIGHUP or Ctrl-C between the two left wrapped keys and no KEK anywhere:
`site_hmac.key` and `pid_map.key` (pseudonyms, the chart-number map) could not be opened again, and a re-run could
not open the KEK either. A signal that reached the shell alone ran the trap and carried on.

## The invariant

**At every instant, each site key is either there plain, as it was, or the KEK that opens its wrapped copy is sealed
in `/etc/credstore.encrypted/trialbox-kek`, the credential's final place.**

Why it holds, step by step:

| Step | Plain keys | Credential in place | A stop here leaves |
| --- | --- | --- | --- |
| KEK made in `/run/trialbox/kek.new` | all | no | plain keys; the trap shreds `kek.new` |
| sealed to `trialbox-kek.new` | all | no | plain keys; the trap removes both new files |
| `chmod 600`, `mv` into place, `sync` | all | yes | plain keys and an unused credential |
| `tools.keys init` (kek.json, each key wrapped, then its plain file removed) | some | yes | each key plain or opened by the credential |
| unseal to `/run/trialbox/kek`, boot unit | none | yes | wrapped keys and the credential |

The `mv` is a rename in one folder: the credential is either the old name's or the new one's, never half. Nothing in
the script removes the credential: the trap removes only `kek.new` (a copy in /run) and `trialbox-kek.new` (never
placed, so never a KEK anything is wrapped under). HUP, INT and TERM exit with the signal's code (129, 130, 143), so
a stopped run never goes on to the next step. Each wrapped key and `kek.json` is written through a temporary file,
fsync and a rename (`tb_common.kek._write_private`), so a key is never half-written.

## A re-run finishes what a stopped run began

- **A credential with no kek.json and no wrapped key** (a stop after the place, before the first wrap): its KEK is
  opened (`systemd-creds decrypt`) and used for `keys init`. A credential beside wrapped keys with no `kek.json` is
  still refused as before ("put kek.json back from the backup, or remove the credential").
- **kek.json there, back end `file`, the credential there, no `/run/trialbox/kek`** (a stop during or after `keys
  init`): the KEK is opened from the credential and unsealed to `/run/trialbox/kek`, any key still plain is wrapped,
  and the boot unit is written (it was written only on the first run's last step before).
- **A key there plain and wrapped** (a stop between its wrap and the removal of its plain file): `tools.keys wrap`
  removes the plain file when the wrapped copy opens to it under this KEK (`wrap_plain`); a wrapped copy that does not
  open to it is still refused, and both are kept.

## The review of #1457 (7122962689): three Mediums and two Lows fixed

- **1457-1 (Medium), two runs at once.** Both used `kek.new`, so one run could wrap the keys under the other run's
  KEK and place its own credential. Fix: one run at a time on the secrets folder, with an exclusive `flock` on the
  folder itself (fd 6). That is the same lock `tools.keys rotate-kek` takes. A second run is refused and nothing is
  changed. A host without flock stops; on a PoC box the installer's seal step turns that stop into its own
  stop_or_warn, as it does for every seal failure. The invariant above now holds for any number of runs.
- **1457-2 (Medium), the re-run's ownership** (was H111-02). D-887's hand-over is now a function, `hand_over`. It is
  called on both ways out that say done, so the `kek.json` branch (a re-run) calls it too.
- **1457-3 (Medium), the folder fsync.** `wrap_plain` fsyncs the secrets folder after each wrapped copy's rename and
  before it removes the plain file. That covers the newly wrapped key and the finished pair, and it also puts
  `kek.json`'s rename on disk before the first plain key goes.
- **1457-4 (Low).** `cred_open` opens the credential under `umask 077` and removes any name at `kek.new` first.
- **1457-5 (Low).** The clean-up ignores HUP, INT and TERM once it starts. Its `shred` inherits that, so a second
  signal can no longer leave the plain KEK in /run.
- **1457-6 (Low), not fixed:** D-887 hands the folder of a caller's `TB_KEK_FILE` to the services' user. The
  root-only test `test_seal_keys_order.py::test_the_sealed_files_belong_to_the_services_user` asserts exactly that
  hand-over (its `TB_KEK_FILE` folder is not `/run/trialbox`), so changing it changes what a test asserts. It goes to
  a follow-up card on the `TB_KEK_FILE` seam, as the lead ruled.
- Not done: `keys check` in the `kek.json` branch (the reviewer's advice, not a finding).

## The second review of #1457 (7125647598): the Medium and two Lows fixed

- **1457-1, the rest (Medium): two secrets folders on one host.** `kek.new` and the credential belong to the host,
  but the first lock covered one secrets folder. A seal for a second folder could take the first's `kek.new`. Fix: `arm`
  also takes an exclusive `flock` on the credential's folder (fd 5; root's, 0700), before the trap is set, so a refused
  run removes nothing of the other's. One TPM seal at a time per host. The folder lock (fd 6) stays for the
  `kek.json` branch and the other back ends. For the TPM path the host lock now covers it, so a mutant that removes
  the folder lock alone is not caught by the TPM tests.
- **1457-7 (Low): `chown -h`.** The hand-over never follows a link; the secrets folder is the services' user's.
- **1457-8 (Low): the re-run test's root case.** Run as root, the test also asserts that the sweep reached `kek.json`.
- **1457-4's untested half:** a link at `kek.new` is removed before the credential is opened. The stand-in records
  a link at its output, because the clean-up's `shred -u` would empty the link's target and hide the write.
- **1457-6 (Low): not here.** It is card H-118, a separate pull request after this one (ruling 7125341668).

## Tests

`tests/unit/test_seal_keys_signal_h111.py` (19 cases at 3287e70a, 24 after the first review round, 26 after the second). A host root of its own (`TB_HOST_ROOT`), a stand-in sealing
tool on PATH whose "sealed" credential is a copy of the KEK, and a stand-in `python3` on PATH that runs the keys
commands, sends the signal at a named step, and checks the invariant at every step (after the seal, after the place,
after each key's wrap, after `keys init`). The script reads none of the stand-ins' variables. The signal goes to the
script's process group (as Ctrl-C or a service stop does) or to its shell alone.

- `test_the_invariant_holds_at_every_step_of_a_full_seal`: the invariant at each step of a whole run.
- `test_a_signal_during_keys_init_leaves_keys_that_open_and_a_rerun_completes[TERM|HUP|INT-group|shell]`: the
  reviewer's case, after the first key is wrapped and its plain file removed and the second is wrapped: the run exits
  with the signal's code, every key opens, a re-run completes.
- `test_a_kill_at_each_step_of_the_sealing_block[before_seal|after_seal|after_place|after_init-group|shell]`.
- `test_a_failed_seal_leaves_the_plain_keys_untouched` (it passes on master too: kept as the guard).
- `test_a_credential_beside_wrapped_keys_without_kek_json_is_still_refused`.
- `test_a_wrap_stopped_before_the_plain_file_went_is_finished_by_keys_wrap`.
- `test_the_passphrase_path_after_a_ctrl_c_during_keys_init`.
- The second review round: `test_two_secrets_folders_on_one_host_never_leave_keys_the_credential_cannot_open`
  (1457-1, fails at 730f267f), the `-h` and root assertions in
  `test_a_rerun_after_a_stop_hands_the_kek_and_the_new_files_to_the_services_user` (1457-7, 1457-8), and
  `test_the_kek_opened_from_the_credential_is_never_written_through_a_link` (1457-4's `rm -f`; it passes at 730f267f,
  which had the `rm -f`, and catches the mutant without it).
- The review round, each failing at 3287e70a: `test_two_runs_at_once_never_leave_keys_the_placed_credential_cannot_open`
  (1457-1), `test_a_rerun_after_a_stop_hands_the_kek_and_the_new_files_to_the_services_user` (1457-2),
  `test_a_plain_key_goes_only_once_its_wrapped_copy_is_on_disk` (1457-3),
  `test_the_kek_opened_from_the_credential_is_owner_only` (1457-4),
  `test_a_second_signal_during_the_clean_up_leaves_no_plain_kek` (1457-5). A mutant that removes each fix is
  caught by its test, for each of the two folder fsyncs too.

On master's `seal_keys.sh` 15 of the 19 fail; on master's `tools/keys.py` 5 fail. Mutants planted, each caught:
master's order; the place moved after `keys init` in the new code; HUP/INT/TERM not exiting; the trap removing the
credential; no reopening from the credential on a re-run; an orphan credential refused; no boot unit on a re-run; a
credential reused beside wrapped keys; master's `wrap_plain`.

**The rehearsal.** The box rehearsal (`tools/rehearse_box`) runs the passphrase back end on a plain VM with no TPM
and has no stand-in for the sealing tool; the TPM path is proven only by these unit tests, with the stand-in. The
passphrase path's code is unchanged here except for `wrap_plain`, which the rehearsal's install runs.

## Other key paths, looked at once

- **The passphrase back end** (H-96, H-97): no trap, and the KEK comes again from the passphrase and `kek.json`.
  Not the same fault: a Ctrl-C during `keys init` loses nothing. It shared one gap: a key left plain and wrapped made
  the re-run stop ("plain and wrapped"); `wrap_plain` now finishes it (the test above).
- **`tools.keys rotate-kek`** (H-97): no trap; the new KEK is made, the new files written beside the old, the
  journal committed, then the renames with `kek.json` last; a stopped rotation is finished or rolled back. No new
  secret is removed while the old one is gone. Read only; `test_rotate_kek_safety_h97.py` run, green.
- **`deploy/install.sh`'s seal step** calls this script; its one trap (the progress line) holds no secret.
- **`deploy/box-install.sh`**: its traps remove the first-run code file, not a key or KEK.
- **The shamir back end** (finding H111-03): the shares are written to the media before `kek.json`, so nothing is
  lost; but a stop between `keys init` and its `keys unseal` leaves a re-run that cannot open the KEK by itself.
- **A re-run's ownership** (finding H111-02, fixed in the review round as 1457-2): the "kek.json exists" branch
  exited before the D-887 `chown`.

## Files outside the card

None. `tools/keys.py`: `wrap_plain` only (H-110 is in `rotate`).

## Not verified

- A real TPM and `systemd-creds` (none on the review host): the stand-in copies the KEK.
- A power cut: neither the `sync` after the place nor the folder fsync was tested against a real loss. The order of
  the calls is shown (1457-3); a mutant that removes the `sync` is not caught.
- The rehearsal job was not run (no Docker here, and it has no TPM).
