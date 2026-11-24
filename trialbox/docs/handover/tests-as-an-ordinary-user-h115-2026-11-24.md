# H115: lane H's tests as an ordinary user

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders.

- **Card:** H-115 (the integrator, comment 7122477662), from the walk's run 1 (comment 7122185694). rc1's first line
  is the whole test set three times in a row on the bench host, as an ordinary user in a clean checkout.
- **Date:** 2026-11-24
- **Findings:** [`tests-as-an-ordinary-user-h115-2026-11-24/findings.json`](tests-as-an-ordinary-user-h115-2026-11-24/findings.json)
  (H115-01 to H115-05)
- **Files:** the new helper `tests/host_modes.py`, and the fixtures of `tests/unit/test_install_refuses_unsafe_folders_10k4.py`,
  `tests/unit/test_rehearsal_real_servers_h89.py`, `tests/unit/test_rotate_kek_safety_h97.py` and
  `tests/unit/test_ops_runner_on.py`. No product file changes, and no assertion changes.

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

## 4. Open: the test root above `tmp_path`

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
kek review 7) fit this cause. The fix belongs to the test tooling, outside the card, and waits for a ruling (H115-03).

## 5. Not verified

- The bench host. The card cannot run there, and the walk's next run is the proof.
- CI's runner, whose umask is 022, was not emulated beyond the root and umask-022 runs above.
- The whole unit and integration suites were not run (rule 7117447272), only run 1's six files, the sweep's files
  and the touched files.
