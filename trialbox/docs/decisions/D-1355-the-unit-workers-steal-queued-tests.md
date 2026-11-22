# D-1355 The unit workers steal queued tests (H73)

- **Task:** lane H, card H-73 (the integrator's red of 2026-11-22: `unit-shard (1/6)` cancelled at 40 minutes) ·
  **Date:** 2026-11-22
- **Status:** proposed
- **Builds on:** D-201 (pytest-xdist, one worker per core), D-475 (the six shards), D-564 item 7 (the shards' limit
  is measured; measure again when the suite changes)

## Decision

1. `make test` runs pytest-xdist with `--dist worksteal` whenever it runs workers (`PYTEST_N` other than 0). The
   split into six shards, the files of each shard and the 40-minute limit are unchanged.
2. Cause, from the shard-1 logs: under xdist's default `load`, a worker that runs low is sent the next tests as one
   run of the collection. The seven role cases of
   `tests/console/test_prefs_10f1.py::test_no_preference_opens_a_route_or_shows_a_patient_value_the_defaults_do_not`
   (150 to 260 s each in the `--durations=30` lists) are neighbours in the collection, so they went to one worker
   and ran one after another while the other three idled: the progress stopped near 86 % or 92 % for 9 to 15 minutes
   in every shard-1 job read. Their sum (1,127 to 1,440 s) matches the tail. With `worksteal` an idle worker takes
   half of a busy worker's queue, so the seven spread over the workers.
3. Measured from 11 runs of 2026-11-20 to 22 (green median, green max): shard 1 33.6 / 39.9 min, 4 of 11
   cancelled at 40; shard 2 19.3 / 28.1; shard 3 22.7 / 33.9; shard 4 28.2 / 31.9; shard 5 23.0 / 31.1; shard 6
   27.4 / 34.5. The card page holds the local measurement of `load` against `worksteal` and the estimate for CI.
4. The limit is not raised: D-564's rule (slowest median x 1.5) gives 33.6 x 1.5 = 50 today, but the cause is a
   schedule, not a grown suite; measure again with the green shard jobs after this change.
