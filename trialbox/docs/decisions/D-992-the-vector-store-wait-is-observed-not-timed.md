# D-992 the vector store's wait test orders its events instead of timing them

- **Task:** D971-FLAKE (lane D), reported by lane C2 through the integrator (#639, 2026-11-17)
- **PR:** this branch (`agent/D971-FLAKE-the-wait-is-observed-not-timed`)
- **Date:** 2026-11-17
- **Status:** accepted
- **Builds on:** D-971 (the vector store is backed up only while no build runs)

## Context

`tests/unit/test_backup_vector_store.py::test_a_running_build_is_waited_for` started a `threading.Timer(0.3, ...)`
that ended the build, then ran the backup and asserted `waited_s >= 0.2`. Under load the backup began its wait late
and measured 0.153 to 0.163 s. Lane C2 saw this in three local `-n 6` runs on three unrelated branches. The test
bounded a wall-clock gap it did not control. It has not failed on a train yet.

## Decision

The test now orders its events instead of timing them:
1. it wraps `backup._build_locks` and records every look;
2. on the first look that finds the build running, it sets an Event;
3. a thread waits for that Event and only then ends the build.

It asserts:
- the backup found the build running (`["S"]`) and read the store only once the build had ended (the last look is empty,
  and the store was read after the lock was released);
- `waited_s >= LAKE_QUIET_POLL_S`. The code sleeps that long after a busy look, so this bound holds whatever the load.

The product code and every other test are unchanged. No floor is lowered: the old 0.2 s floor measured the timer,
not the product.

## Test

The test was run 12 times on 4 cores while busy loops kept every core loaded:
- the old test failed 7 of 12;
- the new test passed 12 of 12.

The other 6 tests of the file pass.
