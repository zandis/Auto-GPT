# H-133b: the five Lows of the review of #1478

**Reader:** the integrator, the independent reviewer, and the people who build TrialBox

Lane H, 2026-11-24. Card H-133b, the follow-up of H-133 (#1478, merged in train 171) for the five Lows of its review
(1478-1 to 1478-5, 7141849706). Synthetic keys only; no TPM was used.

## What changed

| Review id | Place | Fix | Test |
| --- | --- | --- | --- |
| 1478-1 | `tests/unit/conftest.py` | an autouse fixture puts `tools.keys.CREDENTIAL_FILE` under the test root: no unit test stats, locks or opens the host's `/etc/credstore.encrypted` | `tests/unit/test_lifecycle_keys_h133.py::test_no_unit_test_reaches_the_hosts_tpm_credential` |
| 1478-2 | `tools/keys.py` (`cmd_rotate_kek`, `_seal_here`) | `rotate-kek --backend file` by an account that cannot look in the credential's folder is refused before the lock, the journal or any event, unless `--no-tpm` says the box has no TPM credential. `--no-tpm` looks for none and seals none; it is refused beside `--seal-tpm`, where a credential is there, and with another back end. Root is unchanged. Runbook 25 shows `sudo` | `::test_1478_2_an_account_that_cannot_look_for_the_credential_is_refused_with_nothing_changed`, `::test_1478_2_no_tpm_is_refused_with_seal_tpm_or_where_a_credential_is_there[with-seal-tpm]`, `[credential-there]`, `::test_1478_2_no_tpm_is_for_the_file_back_end_only`, `::test_1478_2_no_tpm_on_a_box_without_a_credential_rotates_and_looks_for_none` |
| 1478-3 | `tests/unit/test_seal_keys_signal_h111.py` | the exact mode pin (0644 for `*.pub`, 0600 for the rest) runs on every run, not only as root, and asks `audit_sign.pub` to be there | `::test_a_rerun_after_a_stop_hands_the_kek_and_the_new_files_to_the_services_user` |
| 1478-4 | `tests/unit/test_lifecycle_keys_h133.py` (`Owners`) | as an ordinary user a freed inode (`os.rmdir`, `os.unlink`, `os.remove`, the destination of `os.replace`) forgets the owner recorded for it | the H-133 tests, now catching B7 and B8 below as an ordinary user |
| 1478-5 | `tests/unit/test_lifecycle_keys_h133.py` | `--seal-tpm` on a new board with no `systemd-creds` is refused before the journal, the started event or the credential's folder | `::test_lr6_seal_tpm_on_a_new_board_without_the_sealing_tool_is_refused_before_any_event` |

The refusal of 1478-2, as printed:

> keys: /etc/credstore.encrypted cannot be looked in by this account, so whether this box's KEK is sealed to the TPM
> there is unknown: run rotate-kek as root (sudo python -m tools.keys rotate-kek ...); on a box with no TPM
> credential, give --no-tpm. Nothing was changed

D-1461 gains point 6 ("no TPM credential is assumed but by `--no-tpm`") and its registry row says so.

The five tests of 1478-2 fail with master's `tools/keys.py` (ecbb1f89). With 1478-1's fixture, as an ordinary user
the unreadable-folder test makes the credential's folder mode 000 for real. Root reads any folder, so as root the seam
`_credential_present` answers "cannot tell" instead.

## Mutants

Each was planted alone, then `tests/unit/test_lifecycle_keys_h133.py` and `tests/unit/test_seal_keys_signal_h111.py`
were run (`-n 4`), as root and as an ordinary user. Each was caught both ways:

- B1: no host-credential fixture.
- B2: an account that cannot look in the credential's folder goes on.
- B3: `--no-tpm` beside `--seal-tpm` is accepted.
- B4: `--no-tpm` where a credential is there is accepted.
- B5: `--no-tpm` with another back end is accepted.
- B6: no up-front tool check (H-133's M8, which survived the review).
- B7: the run folder `write_runtime_kek` makes is not handed over (missed as an ordinary user before 1478-4).
- B8: the rotation's runtime KEK is written with no owner (missed as an ordinary user before 1478-4).
- B9: `audit_sign.pub` written 0664 (`tools/audit_verify.py`, planted only).

H-133's mutants M1 to M7 and M9 to M13 were run again, as root, against `tests/unit/test_lifecycle_keys_h133.py`:
each is caught.

## What was run, and how to run it again

From `trialbox/`, at this card's head. The touched set is the 32 test files this command lists, `tests/unit/conftest.py`
left out:

```
grep -rlE "seal_keys|tools\.keys|from tools import keys|import kek|kek as K|rotate-kek|\"unseal\"|'unseal'|trialbox-unseal" tests --include=*.py | grep -v conftest.py
```

Each was run under CI's conditions:

- `env -i`, umask 022;
- `TB_TEST_ROOT` a directory over 100 characters long, marked with `python -m tools.pglocal mark`, with `TMPDIR` inside
  it at mode 0700;
- `PYTEST_ADDOPTS="--cov --cov-report= --durations=30"` and `COVERAGE_CORE=sysmon`;
- `.venv/bin/python -m pytest <the 32 files> -n auto --dist worksteal`.

The ordinary user ran in a worktree of its own.

| Set | Root | Ordinary user |
| --- | --- | --- |
| the 32 files | 676 passed, 2 skipped, 1 xfailed | 674 passed, 4 skipped, 1 xfailed |

The skips: kustomize and kubeconform are not installed (2). As an ordinary user, also `test_seal_keys_order.py:162`
(needs root) and `test_host_baseline.py:159` (needs network admin rights).

H-133's page gave 669 and 667 for this set before H-133b's tests. The review's 32 files were another set (the files
that import `tb_common.kek` or `tools.keys`).

## Files outside the card

- `tests/unit/conftest.py` (shared by every unit test): one autouse fixture, added beside `_no_host_schedule`.

## Not verified

- No real TPM and no real `systemd-creds`.
- Whether CI's runner has `/etc/credstore.encrypted`: with 1478-1 no unit test looks there.
- The whole unit and integration suites were not run here; CI's shards run them. The new autouse fixture imports
  `tools.keys` in every unit test.
- `--no-tpm` on a box whose credential folder cannot be looked in (the rotation goes on and seals nothing) has no test
  of its own.
