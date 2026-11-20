# The coverage ratchet red while every test passed (card H-63, 2026-11-19)

**Reader:** the people who build TrialBox

Lane H. Findings H63-01 and H63-02 ([findings JSON](coverage-ratchet-lost-lines-2026-11-19.json)).

## What CI saw

- Run 44628868228 (pull request #1229, head b73f83ac, a card that touches no service code). All six unit shards
  passed. The `unit` job 135944262250 failed at `tools.coverage_ratchet`: `services/doc_parser` 87.53 against 88.11,
  `services/guard` 95.18 against 97.19, `services/llm_stub` 90.17 against 93.16, `services/sitesetup` 90.69 against
  91.99, and `services/criteria_compiler/semantics.py` 93.79 under its floor of 95.
- Train 100, as the integrator reported it (19:34 UTC): red on the ratchet only. Shard 3's coverage data held about
  18,000 fewer lines than on train 99, the end-to-end test's lines among them.

## What the data shows

The comparison is between the red run and the green run 44614992770 of train 101 (unit job 135898844783), which was
about one hour older. The shards' `coverage.db` files were downloaded from the two runs' artifacts.

| | Green, shard 3 | Red, shard 3 |
|---|---|---|
| `coverage.db` | 208,896 bytes, 924 files, 152,347 lines | 200,704 bytes, 918 files, 133,725 lines |
| Lines in green and not in red | | 18,738 in 312 files |
| Lines in red and not in green | | 116 (the pull request's own change) |
| Tests | 3186 passed, 185 skipped, 41 xfailed | the same |

The red data is the green data with a block missing. The block is spread over many unrelated files:
`tools/e2e_simple.py` (1478 lines), `tools/catalogue_verify.py` (619), `tools/trialbox/backup_schedule.py` (571),
`services/adapter/sources/ssmix2/source.py` (476), and 308 more. Seven files are missing entirely. This is the shape
of one xdist worker's data: the lines that only that worker's tests ran.

Nothing in the logs explains it. There is no "node down", "crashed", "replacing", "CoverageWarning" or
"Couldn't use data file" line in any of the twelve shard logs. The six artifacts of each run were uploaded and
downloaded with matching digests.

## The cause (shown)

`tests/unit/test_test_shard.py` is in shard 3. Two of its tests start their own pytest:
`test_pytest_shards_partition_a_real_collection` (three runs) and `test_a_bad_shard_option_is_a_usage_error`. Both ran
in `trialbox/` with the outer environment. In CI that environment holds
`PYTEST_ADDOPTS: --cov --cov-report= --durations=30`, so each nested pytest measured coverage too.

At its end pytest-cov (7.1.0, `engine.Central.finish`) combines every `.coverage.*` file in its folder, then deletes
them. An xdist worker of the outer run that has finished all its tests has already saved its
`.coverage.<host>.pid<n>.X<random>x.H<hash>h` file in that same folder. The nested run takes it in, and the outer run
then combines without that worker's lines. The nested run and the tests pass. Whether a worker has finished before
the nested run starts depends on timing, so the loss comes and goes.

A reproduction (outside the repository) showed this. It used two test files under `-n 2 --dist loadfile`. One was
quick. The other waited 4 seconds, then ran `python -m pytest --collect-only` in the same folder.

| Nested run's environment | The quick test's module in the outer run's `.coverage` |
|---|---|
| with the outer `PYTEST_ADDOPTS=--cov=. --cov-report=` | 0 of 4 lines |
| without it | 4 of 4 lines |

Not shown: which worker's data was lost in run 44628868228, and when `test_test_shard.py` ran in it. The `-q` log does
not record the worker of each test. The loss has the size and shape of one worker's data, in the shard that holds the
nested runs.

## Two more ways to the same loss (found while looking, not seen in these runs)

- **A worker that dies after its last test.** No test is pending then, so no test fails. pytest-cov gets no data from
  that worker and says so only in its report, which CI turns off with `--cov-report=`. xdist prints one
  `[gwN] node down` line and the run stays green. This was checked against the red logs: no such line. A native abort
  at exit, like card H-52's, would take this path.
- **A shard whose `coverage.db` never reaches `unit`.** The combine reads a glob, so a missing shard is skipped without
  a word.

## The fix

- `tests/unit/test_test_shard.py`: its nested pytest runs drop `PYTEST_*`, `COV_*` and `COVERAGE_*` from their
  environment, as `tests/unit/test_test_hygiene.py` and `tests/unit/test_traceability.py` already do.
- `tools/coverage_shards.py`, registered by `tests/conftest.py`:
  - A pytest that measures coverage in the folder of a pytest run that already measures coverage stops at once with a
    usage error that names the folder (`TB_COVERAGE_RUN_DIR`). The next test that does what `test_test_shard.py` did
    fails at once. When the guard was added, it caught the second nested call in that file.
  - The controller fails the run when a worker returns no coverage data, and names the worker.
- `unit`: a new step, `Every shard's coverage data is present` (`python -m tools.coverage_shards check`), runs before
  the combine. It reads the number of shards from the shards' records. It stops the job and names any shard with no
  `coverage.db`, an unreadable one, or one with no measured lines. It prints the lines of each shard, so that two runs
  can be compared shard by shard.

The ratchet, its baseline and its floors are unchanged. Nothing is excluded from measurement.

## Tests

`tests/unit/test_coverage_shards_h63.py` (12 tests):

- the shard check: all shards present, one missing, one with no record, empty and unreadable data, and records that
  disagree;
- the worker watch, with stand-in nodes;
- a real `pytest -n 2 --cov` run whose worker `gw1` exits after its last test: green without the watch, exit 1 with
  it, and the worker named;
- a nested `pytest --collect-only` with the outer `PYTEST_ADDOPTS`, which is refused with exit 4;
- the workflow step's place: after the shard check, before the combine and the ratchet.

## Not verified

- A full shard 3 under `--cov -n auto` before and after the fix. The loss depends on timing, and the shard takes about
  25 minutes.
- The fix in CI. No workflow was run for this card. The first full-tier runs with this branch will print the lines of
  each shard at `Every shard's coverage data is present`.
