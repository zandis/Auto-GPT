# D-960 the random-order shards and the pure tests, as the nightly runs them

- **Task:** T-653-RANDOM, lane D backlog (#639, 2026-11-16; the owner's ruling to complete everything as soon as possible)
- **PR:** this branch (`agent/T-653-RANDOM-the-random-order-shards-are-green`)
- **Date:** 2026-11-16
- **Status:** accepted

## Decision

The nightly's random-order shards 1/6 and 3/6 were red from harness faults that appear only under `uv run --with
pytest-randomly` (run 43752018548, 2026-11-15).

1. `tests/unit/test_host_python_runs.py`: the `host_path` fixture finds PyYAML where it was imported from, not in the
   interpreter's own purelib, which under `uv run --with` holds only the added plugin.
2. `tests/unit/test_test_hygiene.py`: the probe's nested pytest runs with `-p no:randomly`, because the probe checks
   the order of its own two tests.
3. `make test-pure` (pure tests, no PostgreSQL) runs every night as the nightly matrix entry `pure`; T-653's acceptance
   names it, and no workflow ran it.

No assertion was changed or removed. The other two nightly reds are not this card's: perf-5k is a cascade regression
(lane A2, reported on #639), and the compose job's failures are triaged on #639.

## Test

Under `uv run --with pytest-randomly==3.16.0 ... --randomly-seed=N` on the two files: before, 2 to 3 failed per seed
(seeds 1 to 4); after, 0 failed (seeds 1 to 3) and 26 passed in plain order. `test_test_hygiene.py` pins the `pure`
matrix entry and the target's no-cluster settings.
