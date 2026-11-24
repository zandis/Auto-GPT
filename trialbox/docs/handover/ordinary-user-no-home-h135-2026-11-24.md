# H-135: the policy set as an ordinary user with no home folder

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders.

- **Card:** H-135 (the integrator's ruling 7142024686). Lane H's lines kept listing the same 11 failures for a user
  with no home folder, called "same on master". A standing red that each line excuses is a finding.
- **Date:** 2026-11-24
- **Findings:** [`ordinary-user-no-home-h135-2026-11-24/findings.json`](ordinary-user-no-home-h135-2026-11-24/findings.json)
  (H135-01 to H135-03)
- **Files:** `tests/unit/test_poc_stops_h94.py` (the `_firstrun` helper) and
  `tests/unit/test_kek_passphrase_review_h96.py` (one test and a new helper). No product file changes, and no
  assertion changes.
- **Files outside the card:** none yet. `tests/unit/test_cloud_run.py` is lane G's: a `question:` went to the lead
  first (section 3), and the file is not touched.

## 1. How it was reproduced

On master `ecbb1f89`, in the card's container. The account was `nobody` (uid 65534, passwd home `/nonexistent`),
through `setpriv --reuid --regid --clear-groups` and `env -i` (a `PATH` and `LANG`, `HOME=/nonexistent`, nothing
else). It ran in its own copy of the repository, which it owned, with its own virtualenv. CI's conditions were
kept: umask 022, `PYTEST_ADDOPTS="--cov --cov-report= --durations=30"`, `COVERAGE_CORE=sysmon`,
`-n auto --dist worksteal`, and a test root of more than 100 characters under `/var/tmp/trialbox-<uid>/`, marked
by `python -m tools.pglocal mark`, with `TMPDIR` 0700 inside it and pytest's basetemp under it. That is how
`make test-locked` runs.

The four files gave the 11 failures, and 191 passed:

| Test | Count | Message |
| --- | --- | --- |
| `test_poc_stops_h94.py::test_a_poc_box_s_first_run_goes_through_every_converted_point_of_box_install` | 1 | rc 1: "the home of uid 65534 is a link or not a regular file (or there is no home)", then "no terminal, no screen and no root-only file for the one-time code" |
| `test_poc_stops_h94.py::test_on_production_box_install_stops_as_before` (force1, force2, force3) | 3 | the same stop, in place of the expected last line |
| `test_poc_stops_h94.py::test_on_production_the_host_check_s_code_stays_the_exit_code` | 1 | the same stop: no "TrialBox is ready" |
| `test_poc_stops_review_h94.py::test_h1_box_install_ends_with_the_host_check_s_code_for_a_kept_kind` (4 parameters) | 4 | the same stop: no `FAIL  .env mode 644` or `FAIL  free space on` |
| `test_kek_passphrase_review_h96.py::test_tools_keys_refuses_a_folder_owned_by_another_user` | 1 | `DID NOT RAISE KekError` |
| `test_cloud_run.py::test_a_part_records_its_run_and_a_new_run_runs_it_again` | 1 | `complete run FAILED: 1/1 checks, 0/1 screenshots` |

## 2. The causes, and the choice per test

Three causes, not one. Only the first is about the home folder.

**(a) box-install's one-time code file, 9 tests (H135-01).** On a first run with no terminal and no screen,
`deploy/box-install.sh` `show_code` keeps the one-time code in a root-only file in the home that the passwd entry
names (`code_file`, never `HOME`; H-97). The tests' `_firstrun` helper gave the script `HOME` under `tmp_path`,
which the script rightly ignores. So the file went to the runner's real passwd home. For `nobody` that home does not
exist, the script has nowhere safe for the code, and it stops. That is right for a box.

The choice: **the test gets its own passwd home under `tmp_path`.** The product is right. On a box the script runs as
root, whose home exists. A box with no terminal, no screen and no home has nowhere to show the code, and it must
stop, not print the code to a log. A variable of the caller may not decide where a secret goes, so no variable was
added either. `_firstrun` now puts a stand-in `getent` on the run's `PATH`. It answers `passwd <the runner's uid>`
with a home under `tmp_path` (`pwhome`, 0700), and passes every other question to the host's `getent`. That is the
pattern of `tests/unit/test_first_run_code_h97.py` and `tests/unit/test_poc_stops_bench_h94.py`.

This also fixes a side effect for root and for CI's runner. Before, each of these runs wrote the code file into the
runner's real home and removed that name at its end (`drop_code_file`). Shown as root: a synthetic marker file at
`/root/trialbox-firstrun-code` was deleted by master's
`test_on_production_the_host_check_s_code_stays_the_exit_code`, and it was left alone by the same test on this branch.

**(b) the T-3 test's "another user" is `nobody`, 1 test (H135-02).** This is not a home folder. The test makes
`os.stat` say that uid 65534 owns the passphrase file's folder. `tools/keys.py` `_safe_folders` accepts a folder
owned by root or by the user that runs it. When the runner is `nobody`, 65534 is the runner, so the folder is its own
and the check rightly passes.

The choice: **the test, not the product.** The product is right. The test's premise is "the folder is another
user's", and on `nobody` the number it picked is not another user. The assertion names the uid
(`"is owned by uid 65534, not root"`), so the number stays. When the runner is 65534, the new helper
`_runner_is_not(65534, m)` shows `tools.keys` a runner of uid 65533. Everything the real runner owns (stat, lstat and
fstat) is shown as 65533's, so the file is still the runner's and the folder is still another user's. The file's own
owner check therefore cannot answer for the folder's. The stand-in lives in a `monkeypatch.context()` around the call
only. Left in place to the end of the test, it changed the owners that the shared teardown check of `rulesets/` reads,
and that check failed.

**(c) the cloud run's screenshot browser, 1 test (H135-03, lane G's file).** See section 3.

## 3. `test_cloud_run.py` (lane G)

`tests/unit/test_cloud_run.py` and `tools/complete_run.py` are lane G's (the cloud run, D-150;
[the GPU VM hand-over](gpu-vm-handover-2026-11-16.md),
[audit C](lane-g-2026-11-16/audit-c-lane-g.md)). The test runs whenever the preinstalled node tools folder exists
(its `skipif`, line 51). The part's screenshot is taken by `tools/stage_shots.js`, whose browser library looks for
its browser through the caller's `PLAYWRIGHT_BROWSERS_PATH` (this container sets `/opt/pw-browsers`), else in
`~/.cache`. Under `env -i` the variable is gone. The launch fails with "Executable doesn't exist at
/nonexistent/.cache/ms-playwright/...", the shot is lost, and `complete_run` rightly reports FAILED with exit 1.

This is the environment, not a uid or a mode. Root under `env -i` with `HOME=/root` fails the same way. `nobody` with
the variable set launches the browser. `node` must also be on `PATH`. The runs here put the container's node folder
on it.

The question to the lead (lane G to read) proposes a body-only change to `tools/complete_run.py` `_node_env`. It
already gives `NODE_PATH` the preinstalled node tools when unset. It would also give `PLAYWRIGHT_BROWSERS_PATH` the
preinstalled browsers folder when unset and when that folder exists. The VM, whose browsers are in root's home cache,
would be unchanged. The alternative is the same default in the test's own environment (line 56). Neither is made
until the go.

## 4. The done test

The policy set is the files that `grep -lE` with the ruling's pattern finds in `tests/unit/*.py`: 238 files on this
branch merged with master `cf7c1917` (236 on `ecbb1f89`). They were run under the conditions of section 1.

| As | Result |
| --- | --- |
| `nobody`, `env -i`, its own copy | 1 failed (`test_cloud_run.py`, section 3), 5454 passed, 13 skipped |
| root | 5459 passed, 9 skipped |

On the branch before the merge (236 files), root gave 5412 passed, 9 skipped and 1 error. The error was at the
teardown of the module fixture `box` in `test_host_commands_own_environment.py`, reported against
`test_restore_from_the_host_h100.py::test_r1_whatever_stops_one_put_back_step_the_rest_still_go_back_and_it_is_audited`:
`DROP DATABASE ... WITH (FORCE)` got "permission denied to terminate process". That file alone then gave 65 passed,
and the run after the merge had no error. Neither file is this card's, and its cause was not looked into.

Mutants, each put back after it ran:

| Mutant | As `nobody` | As root |
| --- | --- | --- |
| `_firstrun` without the stand-in `getent` | the 9 of cause (a) fail | not run |
| the T-3 test without `_runner_is_not` | fails (`DID NOT RAISE`) | passes (the helper does nothing for root) |
| `tools/keys.py` `_safe_folders` without its folder-owner check | the T-3 test fails | the T-3 test fails |

## 5. Not run, not verified

- CI itself. Its runner is uid 1001 with a home, so cause (a) wrote into `/home/runner` there, and causes (b) and (c)
  do not arise. The `test_cloud_run.py` test skips on CI, which has no preinstalled node tools folder.
- The whole unit suite. Only the policy set and the touched files were run.
- `test_cloud_run.py` stays red as `nobody` under `env -i` until the lead's go on section 3.
