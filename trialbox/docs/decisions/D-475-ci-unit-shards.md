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
2. **N = 6, from the measured durations.** The one-runner job spent 35 to 43 minutes in pytest in the runs of
   2026-11-12 (up to 55 on a busy day) and under a minute in set-up (caches warm). Each shard pays the set-up
   (about 30 s), the collection (about 30 s) and its workers' cluster starts again. By test count the hash puts at
   most 1.36 times the mean in one shard at N = 6 (1.17 at N = 4, 1.37 at N = 5): at N = 6 the largest shard is
   about 43 / 6 x 1.36 + 1.5, near 11 minutes, and about 14 on a 55-minute day, under the 15-minute aim; N = 4 or 5
   would pass 15 on a slow day. More shards would queue for runners: a pull request already starts about 16 jobs.
   The shards' own times on the pull request are in its PR body; N is the matrix and nothing else.
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
- The branch-coverage nightly (`trialbox-nightly-quality.yml`) still runs the whole suite on one runner; it is not on
  the pull-request path.
