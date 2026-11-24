# H115: lane H's tests as an ordinary user

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders.

- **Card:** H-115 (the integrator, comment 7122477662), from the walk's run 1 (comment 7122185694). rc1's first line
  is the whole test set three times in a row on the bench host, as an ordinary user in a clean checkout.
- **Date:** 2026-11-24
- **Findings:** [`tests-as-an-ordinary-user-h115-2026-11-24/findings.json`](tests-as-an-ordinary-user-h115-2026-11-24/findings.json)
  (H115-01 to H115-13)
- **Files:** the new helper `tests/host_modes.py`, the fixtures of
  `tests/unit/test_install_refuses_unsafe_folders_10k4.py`, `tests/unit/test_rehearsal_real_servers_h89.py`,
  `tests/unit/test_rotate_kek_safety_h97.py` and `tests/unit/test_ops_runner_on.py`, and the new test
  `tests/unit/test_test_root_modes_h115.py`. No product file changes, and no assertion changes.
- **Files outside the card** (the lane H lead's go): `tools/pglocal.py` (the body of `mark_test_root`, with a new
  private helper), the `Makefile` (the `mkdir` of `TMPDIR` in `test-locked` and `test-random-locked`) and
  `tools/full_set.py` (the test root it gives its stages, with a new helper, for the review's 1462-1). All are
  shared test infrastructure, with no interface change (sections 4 and 5).

## 1. How it was reproduced

In the card's container, an ordinary account (uid 1000, home under a folder root owns) had its own clone and its
own `make venv`. It ran the tests through `setpriv --reuid --regid --clear-groups` with a clean environment.

| As | umask | Layout | Run 1's six files |
| --- | --- | --- | --- |
| root | 022 | plain pytest | 477 passed |
| the ordinary user | 022 | plain pytest | 477 passed |
| the ordinary user | 002 | plain pytest | 56 failed: 10K-4 43, H-89 10, H-97 rotate 3 (the walk's counts) |
| the ordinary user | 002 | `make test`'s layout, test root made under umask 002 | 138 failed |

The difference is the umask. On Ubuntu, an ordinary user whose group is its own gets umask 002. Root, and sudo,
get at least 022. The walk's message ("the audit anchor folder's parent `/` is owned by another account") is the
10K-4 check's text "has a parent folder / that another account owns or may write". Here the folder can be written
by its group.

## 2. The causes, test by test

Every failure was (a): the test assumed a host whose folders are closed to others. Each fixture now builds its
own tree with a host's modes, and the product's checks are unchanged.

- **10K-4, 43.** `fake_host` builds a stand-in for `/`, which came out 0775. `finish_check.anchor_problem` rightly
  refuses an anchor folder under a parent that another account may write. The fixture now closes its stand-in tree
  (`as_root_makes_it(root)`). The tests that want an open folder (`/srv/open`) still open it after the fixture.
- **H-89, 10.** The bench's engine probe result and its folder came out 0664 and 0775. `rehearsal_real.read_probe`
  rightly refuses a probe that group or others may write. The bench now closes its own folder. The page's steps test
  wrote step 2b's file "with the umask". That step runs under sudo, whose umask is at least 022, so the fixture now
  writes it as sudo does.
- **H-97 rotate-kek, 3.** The box folder (`kill-<n>`, `round-<n>`) came out 0775. `keys._safe_folders` rightly
  refuses a passphrase file in a folder others can write. `_box` now closes its folders before `keys init`.
- **ops runner, 4.** Not a mode. `test_doctor_fails_a_runner_that_never_ran` (four parameters) asked the machine's
  own systemd. On a box where `trialbox-ops.timer` is enabled, doctor rightly says "is enabled: see systemctl
  status" instead of "systemctl enable --now". Patching `doctor._timer_state` to "enabled" fails exactly those four.
  The test now gives doctor a host whose systemd cannot be asked.

`tests/host_modes.py` (`as_root_makes_it`) takes away group and others' write from a tree that a fixture built.
It leaves links, other accounts' entries and sticky folders as they are.

## 3. The sweep

85 unit files grep for `os.geteuid`, `getuid`, `chown`, `st_uid`, `root`, `sudo` or `/etc/`. The clone is shallow,
so the card ran all 85, not only the files it could tie to lane H. The run was as the ordinary user, with umask 002.

- 82 files pass.
- `test_host_commands_own_environment.py` 39, `test_backup_schedule_timer.py` 1 and `test_restore_from_the_host_h100.py`
  1 fail on one cause. The shared `box` fixture writes `deploy/.env` with the umask, and the launcher rightly refuses
  a box file that group or others can write. #1455 (H-110 (e)) adds `chmod 0o600` there. Its version of the file,
  run on master as the ordinary user, gives 137 passed for the three files, so this card leaves the file to #1455
  (H115-04).

## 4. The test root above `tmp_path`

`make test` puts `TMPDIR` and pytest's basetemp under `TB_TEST_ROOT`, by default `/var/tmp/trialbox-<uid>/tb-tests-<branch>`.
The Makefile's `mkdir -p` and `tools/pglocal.py mark_test_root` make those folders with the runner's umask, so
they are 0775 under umask 002. pytest's basetemp is 0700. Some product checks walk the real folders from `/`
(`tools/backup_key_ceremony.py _root_path`, `tools/keys.py _safe_folders` and the shell checks that `install.sh`
and `seal_keys.sh` make), and they rightly refuse that chain. A fixture cannot change this without changing folders
above `tmp_path`.

With the parents at 0775, these fail: `test_backup_key_ceremony.py` 59, `test_kek_passphrase_review_h96.py` 17,
`test_kek_passphrase_file_h96.py` 22, `test_rotate_exposed_passphrase_h97.py` 15, `test_rotate_kek_safety_h97.py`
9, `test_poc_stops_review_h94.py` 3, `test_restic_password.py` 1, the runbook install commands file 1 and
`test_seal_keys_order.py` 1. All of them pass when the parents are 0755. The walk's run 1 counts (ceremony 45,
kek review 7) fit this cause (H115-03).

**The fix (the lane H lead's go).** `mark_test_root` makes the folders it creates 0700, whatever the umask. It takes
group and others' write from the test root, and from the folders up to the per-user scratch root when the test root
lies under it. That includes a 0775 root left by an earlier run, as the bench host has. It changes only folders
this user owns. It never changes a sticky folder, `/`, the home folder, a system folder or anything above the
scratch root, and the search bit that `_grant_traverse` gives a database server's account stays. `test-locked` and
`test-random-locked` make `TMPDIR` with `mkdir -m 0700 -p`. A conftest umask was not used, because it would hide
the product's behaviour under the operator's real umask. `tests/unit/test_test_root_modes_h115.py` covers the three
cases.

**Proof**, by `make test`'s own steps (`pglocal mark`, then `make test-locked` with `PYTEST_N=4`). The run took
the six files, the nine files above, the new test and seven database-backed neighbours that start a pglocal
cluster: `test_pglocal_ensure_lock_h72.py`, `test_audit_writer.py`, `test_db_roles.py`, `test_db_reconnect.py`,
`test_e2e_targets_mark_their_root.py`, `test_dev_loop.py` and `test_db_connections_given_back.py`.

| As | umask | Test root before | Result | Folders after |
| --- | --- | --- | --- | --- |
| the ordinary user | 002 | `trialbox-1000` and the root 0775, from an earlier run | 740 passed, 1 skipped | 0755 and 0755 |
| the ordinary user | 022 | new | 740 passed, 1 skipped | |
| root (the server runs as another account) | 022 | `trialbox-0` and the root 0775 | 741 passed | 0755 and 0755 |

A fresh run as root, with no `/var/tmp/trialbox-0` before it, created the scratch root and the test root at 0700.
`_grant_traverse` then added the search bit only (0701), so the database server's own account reached its data
folder: the database-backed neighbours and `test_backup_key_ceremony.py` gave 144 passed.

The one skip is `test_seal_keys_order.py:162` ("changing a file's owner needs root"), which skips on master too.


## 5. The review of #1462

The external review (comments 7125529374 and 7125532955) found 1 High, 2 Mediums and 6 Lows at `1c5b54a5`. Each
fix below has a test in `tests/unit/test_test_root_modes_h115.py` or `tests/unit/test_ops_runner_on.py`. Every
one of those tests fails with `1c5b54a5`'s `tools/pglocal.py`, `tools/full_set.py` and `test_ops_runner_on.py`
helper, and passes now (as root, and as the ordinary user under umask 002).

| Id | Severity | What was wrong | The fix | Its test |
| --- | --- | --- | --- | --- |
| 1462-1 | High | `tools.full_set`, the walk's runner for rc1 line 1, put the test root under `--out`. That folder and the clone above it carry the runner's umask, so the bench host's run would fail again | the run's test root lies under the per-user scratch root, one per `--out` (`full_set.scratch_test_root`) | `test_the_full_sets_test_root_is_closed_under_umask_002` |
| 1462-2 | Medium | `exists()` then `mkdir()`: two runs starting at once on a fresh host stopped with `FileExistsError` | a folder another run made a moment ago is no error, and is checked like the rest | `test_a_folder_another_run_makes_at_the_same_moment_is_no_error` |
| 1462-3 | Medium | a scratch root another account made first was used silently, and its owner could swap the test root | a folder in the chain that another account owns (not root, not sticky) is refused | `test_a_scratch_root_another_account_made_first_is_refused` |
| 1462-4 | Low | a group's setgid folder lost group write, and `TB_SCRATCH=/` closed every folder up to `/` | setgid counts as shared, and nothing is climbed when the scratch root is `/` or a top-level folder | `test_a_folder_the_user_shares_or_did_not_mean_is_never_changed` (2 cases) |
| 1462-5 | Low | a scratch root named through a link was never closed | the scratch root is compared as a real path | `test_a_scratch_root_named_through_a_link_is_closed` |
| 1462-6 | Low | `lstat`, then a `chmod` that follows links | one descriptor opened without following a link, then `fstat` and `fchmod` | `test_a_root_swapped_for_a_link_between_the_look_and_the_change_moves_nothing` |
| 1462-8 | Low | two more doctor checks asked the machine's systemd | the file's `_check` gives every check a host of its own | `test_no_check_here_asks_the_machines_own_systemd` |

The proofs again after these fixes, with the master of 38a06e5d merged, by `make test`'s own steps on the 20 files
above plus `tests/unit/test_full_set.py`. As the ordinary user at umask 002, with 0775 roots from an earlier run,
754 passed and 1 skipped, and the roots ended 0755. At umask 022, 754 passed and 1 skipped. As root, with 0775
roots, 755 passed. As root with a fresh scratch root, the database-backed neighbours and the ceremony gave 144
passed. The walk's runner's layout was also run: `--out` at 0775 inside the clone, and the test root
`full_set.scratch_test_root` names. `test_backup_key_ceremony.py` and `test_kek_passphrase_review_h96.py` gave 120
passed as the ordinary user at umask 002, where the review saw 76 failed at `1c5b54a5`.

Left as they are:

- **1462-7.** `tools/engine_probe.py` writes its result with the caller's umask. This is H115-05, a product change
  the card did not make.
- **1462-9.** `test-pure` and `ci` still make the test root with a plain `mkdir -p`. Nothing fails from it: `ci`
  runs `make test` next, and `test-pure`'s tests use pytest's own base folder. Using `pglocal mark` there would also
  refuse an existing unmarked root that `mkdir -p` accepts today.

## 6. Not verified

- The bench host. The card cannot run there, and the walk's next run is the proof.
- CI's runner, whose umask is 022, was not emulated beyond the root and umask-022 runs above.
- The whole unit and integration suites were not run (rule 7117447272), only run 1's six files, the sweep's files
  and the touched files.
