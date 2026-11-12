# D-475 The pull-request `unit` job in parallel shards, the coverage ratchet on their combined coverage, and a fast `cross-card` job

- **Task:** T-747 (no plan row: the integrator's card prompt of 2026-11-12 is the row)
- **PR:** this branch (`agent/T-747-ci-unit-shards`)
- **Date:** 2026-11-12
- **Status:** proposed (in review)
- **Builds on:** D-201 (test isolation, one cluster per xdist worker), D-206 (the CI gate and its job names),
  T-651 (the coverage ratchet), D-384 (`e2e-simple` keeps its plain name across a matrix)

## Context

The `unit` job of `.github/workflows/trialbox-ci.yml` ran the whole unit suite (about 6,580 tests) on one runner:
35 to 43 minutes of pytest in the runs of 2026-11-12 (set-up under a minute), up to 55 on a busy day. Every push of
every pull request runs it, and every merge to master sends the next pull request through it again. Separately,
four pull requests in one day each lost a full round to a test that fails only when two cards meet (an audit event
without a label, a new route without a permit row, a new table without an inventory row, ...).

## Decision

1. **Shards by test file.** The job `unit-shard` runs the suite as a matrix of N jobs (`fail-fast: false`), each
   `make test PYTEST_N=auto SHARD=i/N`. A test file belongs to shard `sha256(path) mod N + 1`
   (`tools/test_shard.py`; the pytest side is `--shard`, registered in `tests/conftest.py`, applied after every
   other selection). Whole files stay together, so module- and session-scoped fixtures are built once per shard as
   before, and adding or removing a file moves no other file. Only a change of N moves files.
2. **N = 8, from the measured durations.** The one-runner job spent 35 to 43 minutes in pytest in the runs of
   2026-11-12 (up to 55 on a busy day) and under a minute in set-up (caches warm). Each shard pays the set-up
   (about 30 s), the collection (about 30 s) and its workers' cluster starts again. The first two rounds on this pull
   request ran N = 6 (estimated from the test counts: at most 1.36 times the mean per shard): the shards took 4 to
   16 minutes, because the hash put `test_e2e_simple` (one test, 7.8 minutes) with `test_omop_core`,
   `test_recall_cert` and `test_feas_demo` in one shard, and `test_rc_demo`, `test_nav_retro` and the two PoC walks
   (2 to 2.5 minutes each) in another (`--durations=30`, printed by every shard). At N = 8 these heavy files fall in
   four shards; the shard times of the N = 8 round are in the pull request body. More shards would queue for runners:
   a pull request already starts about 20 jobs. N is the matrix and nothing else.
3. **No test drops out silently.** Each shard writes a record (`--shard-record`): pytest's own collection before the
   shard was taken (after `-m`) and the node ids the shard kept. `python -m tools.test_shard check` in the job `unit`
   fails unless all N shards are present, every shard collected the same suite, and every collected test was kept by
   exactly one shard.
4. **The coverage ratchet on the combined coverage, unchanged.** Each shard keeps its coverage data file (line
   coverage under `sys.monitoring`, as before); `unit` combines them (`coverage combine`), writes the JSON report
   (`coverage json`, the same report pytest-cov wrote) and runs `tools.coverage_ratchet` on it with its baseline and
   tolerance as they were. The artifact `coverage` keeps its name.
5. **`unit` stays the required check.** A job named exactly `unit` needs the shards, runs when one failed
   (`!cancelled()`) so the check turns red instead of staying skipped, and passes only when every shard passed, the
   union check passed and the ratchet held. It is skipped, like every gate job, when the pull request does not touch
   TrialBox (`needs.changes.outputs.trialbox`). The shards are named `unit-shard (i/N)`, as `e2e-simple (omop)`
   keeps the plain name free (D-384).
6. **A fast `cross-card` job.** `make cross-card` runs the tests that fail only when two cards meet
   (`CROSS_CARD_TESTS` in the Makefile: the audit-label test, the erasure registry, the role labels and route matrix,
   the record inventory, the migrations, the authz matrix, the declared settings, the data classes, the decision
   index, the wording check, the direct-model-call check and the test-isolation tests): 190 tests, 51 s on two local
   workers, no coverage, no JVM or fonts. The unit shards run them too.
7. **Locally** `make test SHARD=i/N` repeats one CI shard and `python -m tools.test_shard files i/N` lists its files
   (`docs/DEVELOPING.md`).

## Open

- The hash balances by file, not by duration. If one shard is regularly much slower than the rest, the remedy is a
  larger N or splitting the slow file, not a duration table (a table goes stale and moves files when it is refreshed).
  Each shard prints its 30 slowest tests. `tests/integration/test_e2e_simple.py` (7.8 minutes, one test) sets the
  floor of its shard and repeats what the `e2e-simple` job checks; whether the unit run needs it is for its owner.
- The branch-coverage nightly (`trialbox-nightly-quality.yml`) still runs the whole suite on one runner; it is not on
  the pull-request path.
