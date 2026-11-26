# H145: the console stage runs in parallel, under the unit lock, with no skip

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** H-145 (the integrator's ruling 7161808787 on #1504; the lead's bench result, from 7163415503 item 3)
- **Date:** 2026-11-25
- **Base:** int/system 0894674f (the card was begun on master 6e502f57, merged with master 440089e8 once, then
  with int/system 0894674f once, on the integrator's 7184086631)
- **Change:** `make test-console` only; no test changed
- **Findings:** [`h145-console-parallel-2026-11-25/findings.json`](h145-console-parallel-2026-11-25/findings.json)
  (H145-01 to H145-06)

## What changed

`Makefile`, the console stage (`tools/full_set.py` calls it as the full set's `console` stage):

- `test-console` holds the lock that `make test` holds: `flock -n -E 75` on `$(TB_TEST_ROOT)/.lock`, then
  `test-console-locked`. A second run on the same root stops with exit 75 and says so.
- `test-console-preflight` (a prerequisite of `test-console`) refuses a run whose shell ignores SIGHUP (a run under
  `nohup`), marks the root with `tools.pglocal mark` as `make test` does, then refuses a root that it or any parent
  leaves writable to group or others without the sticky bit. `pglocal mark` closes the folders this user owns up to
  the scratch root; the new check refuses the ones it cannot close.
- `test-console-locked` runs `pytest -q -n $(PYTEST_N) $(XDIST_DIST)` (`--dist worksteal` unless `PYTEST_N=0`, as
  H-73 set for `make test`), with `TMPDIR` and `--basetemp` under the root, and `TB_STRICT_SKIPS=1` (master's
  `tests/conftest.py` hook): a browser file that cannot start node or Chromium fails with its reason. Afterwards it
  empties `TMPDIR`, stops the branch's idle shared cluster and removes a green run's basetemp, as `test-locked` does.

The card's own test, `tests/unit/test_console_stage_parallel_h145.py`, reads the recipes, dry-runs
`test-console-locked` with `PYTEST_N` auto, 4 and 0, and runs the preflight for real: SIGHUP ignored is refused
before the root is made, an open parent (0777) is refused, the same parent with the sticky bit passes.

The strict-skip setting is master's own (`TB_STRICT_SKIPS`, D-201's hook in `tests/conftest.py`). #1498 (H139-13)
puts the same variable on the old serial recipe; nothing of #1498 was copied. Whichever of the two lands second
meets the other in the same lines of the Makefile (H145-05).

## What ran (session container, 4 cores, 15 GB)

| Run | Who | Root | Result | Time |
|---|---|---|---|---|
| card test on master, test file only | root | | 6 failed | |
| card test and `test_xdist_worksteal_h73.py` at the head | root | | 8 passed | |
| `make test-console` at 9f865610 (CI's `PYTEST_ADDOPTS`, `COVERAGE_CORE=sysmon`) | root | 13 characters | 2289 passed, 26 xfailed, 0 skipped | 38 min 53 s |
| the same | root | 113 characters, under `/tmp` | 2289 passed, 26 xfailed, 0 skipped | 35 min 47 s |
| `make test-console` at 85fec752, own clone, `env -i`, umask 022, root marked, `TMPDIR` 0700 in it | ordinary user | 113 characters | 2274 passed, 15 errors (H145-04) | 35 min 43 s |
| the same, with this container's `NODE_PATH` and `PLAYWRIGHT_BROWSERS_PATH` | ordinary user | 113 characters | 2289 passed, 26 xfailed, 0 skipped | 46 min 45 s, sharing the CPU |
| control: master's `make test TESTS=tests/console`, root under the session's scratch folder | root | 113 characters | 173 failed, 830 errors (H145-02) | 11 min |

The lead's bench gave 62 minutes with 8 and with 16 workers under `loadfile`; the runs above used 4 workers under
`worksteal` on another host, so the two times are not compared here.

## Again on int/system (2026-11-26)

The merge with int/system 0894674f met #1498's H139-13 line in `test-console`. Both sides were kept: H139-13's
comment stays, and its `TB_STRICT_SKIPS=1` now stands on `test-console`'s own flock line as well as in
`test-console-locked`, so `tests/unit/test_browser_stages_strict_h139.py` (unchanged) still finds it in the
`test-console` recipe. At the merge, 67f6b70e:

| Run | Who | Result | Time |
|---|---|---|---|
| card test, `test_browser_stages_strict_h139.py`, `test_xdist_worksteal_h73.py` | root | 14 passed | |
| `make test-console`, 113-character root, CI's `PYTEST_ADDOPTS` and `COVERAGE_CORE` | root | 2321 passed, 25 xfailed, 0 skipped | 30 min 18 s |
| the same, own clone, `env -i` with this container's two Playwright variables, umask 022, marked root | ordinary user | 2321 passed, 25 xfailed, 0 skipped | 38 min 56 s, sharing the CPU |
| the policy set (264 files) | root | 6161 passed, 9 skipped (tools not installed here) | |
| `make cross-card`; `make guard` | root | 329 passed; 1199 passed, 1 skipped, 11 xfailed | |

As the ordinary user under the same conditions: the policy set 6157 passed and 13 skipped (tools not installed here,
or root needed); `make cross-card` 329 passed; `make guard` 1199 passed, 1 skipped, 11 xfailed; collect-only 29678,
rc 0. As root: lint, doclint, data-scan, security-scan, limits_lint, decisions_index and the findings register's
check clean.

## R1 (the integrator's review of #1539, 7186855564)

`test-console-locked` exited with pytest's status only, so a failed cleanup after a green run still passed. Now
every cleanup step runs (empty `TMPDIR`, `pglocal stop-idle`, and on a green run the basetemp's removal); a green run
exits with the first cleanup step that failed, and a red run keeps pytest's status. The pytest line is unchanged.
Two tests in the card's file run the target with a stand-in `PY` (no cluster): pytest green and stop-idle exiting 3
fails with `Error 3`; pytest red and stop-idle red fails with pytest's `Error 1`. The first fails on the recipe
before the fix. `pglocal stop-idle` itself exits 0 when it leaves a cluster running because clients remain, so that
case is still not a failure of the stage (H145-06, shown by calling its `main` with `stop_idle` reporting clients:
it prints "has clients; left running" and returns 0; `tools/pglocal.py` is not this card's file).

## The long console tests (H145-03, a follow-up)

From `--durations=30` of the root run on the 113-character root (4 workers):

| Test | Time |
|---|---|
| `test_plain_menu.py::test_with_the_flag_off_every_page_is_byte_for_byte_the_page_without_this_card` | 202 s |
| `test_home_today.py::test_the_role_walk_with_the_flag_on_answers_every_route_as_its_row` | 86 s |
| `test_plain_menu.py::test_with_the_flag_on_the_role_walk_answers_every_route_as_its_declared_row` | 83 s |
| `test_committee_walks_japan.py::test_the_role_walk_at_a_japanese_site` | 81 s |
| `test_matrix_role_walk.py::test_every_console_route_answers_every_column_as_its_declared_row` (setup) | 75 s |
| `test_prefs_10f1.py::test_no_preference_opens_a_route_or_shows_a_patient_value_the_defaults_do_not`, 24 of its role and language cases | 67 to 83 s each |

Under `worksteal` these spread over the workers; splitting them is not this card's work.

## What was not run or not verified

- CI itself: no CI run of the new stage. Whether CI's own scratch folders pass the new parent check is shown only by
  the runs above, not on CI's runner.
- The root runs of the whole stage were at 9f865610, before the preflight checks were added. At the head the
  preflight was run by the card's test (as root and as the ordinary user) and by the ordinary user's whole stage.
- The checks, at the head, as root and as the ordinary user alike: `make cross-card` 329 passed; `make guard` 1198
  passed, 1 skipped, 11 xfailed; the policy set (248 files) 5864 passed and 9 skipped as root, 5860 passed and 13
  skipped as the user (tools not installed here, or root needed); lint, doclint, data-scan, security-scan,
  limits_lint, decisions_index, the findings register's check and collect-only (26696, rc 0) clean as root.
- `tools.text_keys` was not run: no text changed. The whole unit suite was not run: `services/` and `libs/` are
  untouched.
