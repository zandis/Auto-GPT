# D-630 The B200 script starts the qualification only when the servers' logs are being followed

- **Task:** B200-FLAKY (a test flaky under load, reported by lane B through the integrator, 2026-11-13)
- **PR:** this branch (`agent/B200-FLAKY-wait-for-the-log-follow`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** T-114 (the owner's script for G1b on the B200)

## Context

`tools/b200_qualify.sh` follows the two model servers' logs in the background (`docker logs -f ... &`) and then
starts the qualification, whose `log_marker` step searches what the servers wrote during the run. The script
did not wait for the followers: the run could start, and in the stand-in test even end, before `docker` had
attached. Under load the test saw no `logs -f` call at all. On the real box the run takes minutes, so the gap
is small, but a marker written in the first moments could be missed by the same race.

## Decision

After it starts the two followers the script waits until both log files hold something (a running server has
written lines, and `docker logs -f` prints them at once), for at most 30 seconds. If a file is still empty it
says so and goes on: an empty server log is the qualification's finding, not the script's.

## Consequences

- The run starts with both followers attached. The test that showed the race is deterministic; a second test
  forces the slow start.
