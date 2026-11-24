# H-133: the key operations of the lifecycle review

**Reader:** the integrator, the independent reviewer, and the people who build TrialBox

Lane H, 2026-11-24. Card H-133 (KEYS, High; the integrator's 7136231344, item 2). Source: lane LR's lifecycle review
(#1474, `docs/reviews/lifecycle-deep-review-2026-11-24.md`, not merged when this was written), its High findings LR-3,
LR-4, LR-6 and LR-7 and its "Key operations" matrix. LR-8 waits for the owner's ruling and is not touched here.
Synthetic keys only; no TPM was used (a stand-in `systemd-creds` seals by copying behind a marker).

## The invariant

**At every instant each site key either is still as it was or opens with the KEK sealed in its final place; every key
file the services read stays readable by the services' account; a rotation never destroys a key it did not make.**

## The four findings, each reproduced on master (00bababf) and fixed

| LR | Place on master | What happened | Fix | Test | Matrix cell made green |
| --- | --- | --- | --- | --- | --- |
| LR-3 | `tools/keys.py:918-921, 938`; `libs/tb_common/kek.py:117-130` | `rotate-kek` as root replaced `kek.json`, each wrapped key and `/run/trialbox/kek` with files root's, 0600: the services (uid 10001, the secrets folder's owner) could open no key | `_write_private(owner=)` gives the temporary file to the folder's owner before its rename; `services_owner()` reads that owner from the folder (only when run as root and the owner is not root), never from the environment; `store_key`, `write_meta`, the staged keys and the runtime KEK use it | `tests/unit/test_lifecycle_keys_h133.py::test_lr3_after_rotate_kek_as_root_the_services_still_open_kek_json_every_key_and_the_runtime_kek` (also checks each rename: the file is the services' as it takes its name) | rotate-kek, KEK passphrase, runtime KEK present, services as uid 10001, none |
| LR-4 | `tools/keys.py:455-458`; `libs/tb_common/kek.py:431` | after a restart, `unseal` (runbook 22's step; the installer's re-run calls the same command) left the KEK and the folder it made root's; the services' load raised a bare `PermissionError` that `custody()` did not catch | `write_runtime_kek()`: the KEK the folder owner's, a folder made here 0700 and the owner's; `load_kek` turns an `OSError` into a `KekError` | `::test_lr4_unseal_after_a_restart_leaves_a_runtime_kek_and_folder_the_services_open`, `::test_lr4_a_kek_file_that_cannot_be_read_is_a_kek_error_that_custody_reports` | unseal by hand, services as another uid; seal, second run, after a reboot; boot after power cut, KEK gone from tmpfs |
| LR-6 | `tools/keys.py:354-363` | `rotate-kek --backend file` on a TPM box left `/etc/credstore.encrypted/trialbox-kek` sealing the old KEK; the next boot's unseal was refused, and with no new escrow set the keys were lost at that reboot | when that credential opens to this secrets folder's KEK now (or none is there and `--seal-tpm` asks, a new board); a credential sealing another KEK is never replaced (with `--seal-tpm`: refused); the new KEK is sealed to `trialbox-kek.next` and opened again before the commit; the roll-forward swaps the credential **first**, then the keys, `kek.json` last; the roll-back removes `.next`; no `systemd-creds` is refused before anything changes. The credential's place and the tool's folders are fixed in the code | `::test_lr6_rotate_kek_on_a_tpm_box_seals_the_new_kek_to_the_credential_the_boot_unseal_opens`, `::test_lr6_a_rotation_on_a_tpm_box_cut_short_keeps_every_key_opening_with_the_sealed_kek_or_as_it_was`, `::test_lr6_rotate_kek_on_a_tpm_box_without_the_sealing_tool_changes_nothing`, `::test_lr6_a_credential_sealing_another_kek_is_never_replaced`, `::test_lr6_a_seal_holding_the_credential_folder_makes_rotate_kek_refuse_with_nothing_changed` | rotate-kek, KEK TPM, sealed credential, none |
| LR-7 | `tools/keys.py:868` vs `:989-990` and `:741-743` | `rotate pid_map` cut short after its database commit leaves `pid_map.key.wrapped.next`, the only copy of the key the rows are under; `rotate-kek` wrote its own staged file over it and renamed it away | `rotate-kek`, under the folder's lock and with no journal of its own, refuses any `*.wrapped.next`; `rotate pid_map` takes the same lock, refuses while a KEK rotation journal is there, and syncs the folder after its rename | `::test_lr7_rotate_kek_refuses_while_a_pid_map_rotation_cut_short_has_its_key_staged`, `::test_lr7_rotate_pid_map_waits_for_a_kek_rotation_cut_short_and_for_the_folder_lock` | rotate-kek, prior interrupted rotate pid_map; rotate pid_map, wrapped key, KILL / power cut |

## Why the invariant holds in the rotation

| Step of `rotate-kek` on a TPM box | Keys | Credential | A stop here leaves |
| --- | --- | --- | --- |
| journal (staging), started event | as they were | old KEK | the next `rotate-kek` or `status --audit-dir` rolls back |
| new KEK sealed to `trialbox-kek.next`, opened again; staged keys, `kek.json.next` | as they were | old KEK | roll-back removes every `.next` |
| journal (committing) | as they were | old KEK | roll-forward |
| credential swapped (a rename in one folder, folder synced) | as they were | new KEK | roll-forward; a boot here is refused by `kek.json`'s name, no key lost |
| each key renamed | as it was, or opens with the sealed new KEK | new KEK | roll-forward |
| `kek.json` renamed, runtime KEK, done event | open with the sealed KEK | new KEK | done |

Every file is written through a temporary file, fsync and a rename; each one the services read is theirs before the
rename. A Ctrl-C or SIGTERM partway raises out of the staging (rolled back) or leaves a committed journal (finished by
the next command). The test stops the rotation at every rename it makes (the journal's writes, the sealed new KEK, the
staged keys, the commit, the credential, each key, `kek.json`, the done event): at each stop every key is as it was
or opens with the KEK in the credential, and after `status --audit-dir` every key opens with the credential in place.

## Tests

`::test_lr3_lr4_the_owner_comes_from_the_secrets_folder_never_from_a_caller_variable` sets `SUDO_UID`, `SUDO_GID`,
`TB_SERVICES_UID`, `TB_SECRETS_OWNER` and others in the process environment and in the command's mapping: the owner
is still the folder's.

Root runs the services as a real other account: a child takes on uid 10001 and opens the files by a descriptor of
their folder. An ordinary user cannot give a file away, so there the folder's owner is taken to be uid 10001 and each
change of owner is recorded by inode; the same reads are checked against the recorded owner and the mode, and the owner test
takes the effective uid to be root so the real `services_owner()` and `unseal` run. No test is skipped as either
user. Only as root: the reads by a real uid-10001 process, a real `chown`, and `services_owner()` of a folder root
owns; only as an ordinary user: `services_owner()` returning None when not root. Thirteen mutants of the fix (no `fchown`, the run folder kept, the raw `PermissionError`, the
credential never swapped or swapped last, no seal, no staged-key refusal, `rotate pid_map` without the journal check
or the lock, no tool check, staged keys not handed, a credential replaced without checking whose KEK it seals, the credential folder's lock never taken) each
turn at least one of these tests red.

**Found by the ordinary user's run, before the push.** A first version sealed whenever the credential was there,
and took a credential folder it could not look in as sealed. On a host with a real credential, any `rotate-kek
--backend file` run as root against another secrets folder (a test's) would have replaced the host's credential
with that folder's KEK, and the host's keys would not have opened at its next boot. The rotation now reseals only a
credential that opens to the folder's KEK now; as an ordinary user that cannot look in the credential folder it
seals nothing and says so.

## Overlap with #1457 (H-111)

**The host lock.** #1457 makes `seal_keys.sh` hold an exclusive lock on the credential's folder
(`/etc/credstore.encrypted`) while it seals, whichever secrets folder it is for. A rotation that reads, stages or
swaps the credential (the file back end with a credential there, `--seal-tpm`, or a journal that staged one) takes
the same lock after the secrets folder's, as `seal_keys.sh` does, and is refused while a seal holds it, with nothing
changed; `status` takes it to finish such a rotation. Any other rotation does not take it.

#1457 changes `wrap_plain` in `tools/keys.py` and moves `seal_keys.sh`'s hand-over (D-887) onto the re-run's way out.
This card does not touch `seal_keys.sh`; its `keys.py` lines are elsewhere. With both merged the installer's re-run
hands the files over twice (the second finds nothing root's). A new board sealed by `rotate-kek --seal-tpm` gets its
boot unit from a re-run of `seal_keys.sh` with #1457 (its `kek.json` branch renders it on a TPM box); on master alone
the unit is not rendered (LR-45).

## Findings the card leaves open

In `docs/handover/lifecycle-keys-h133-2026-11-24/findings.json`: H133-05 (Medium, hypothesis: a TPM box rotated to
another back end keeps the old credential and unit), H133-06 (Low: a runtime folder already there is not handed over),
H133-07 (Low, shown: the runtime KEK's place still comes from `--out` or `TB_KEK_FILE`), H133-08 (Low, not run: the
object store's seal file).

## Not verified

- No real TPM: the seal and the open again are a stand-in's. The real `systemd-creds encrypt - -` and `decrypt FILE -`
  forms were read from its manual, not run.
- The database half of LR-7 (rows re-keyed, then `rotate pid_map` run again) was not run: the refusal comes before
  the database is reached.
- The runbook pages are not changed: `docs/runbook/22-replacing-hardware.md` step 3 still does not name
  `--seal-tpm`.
