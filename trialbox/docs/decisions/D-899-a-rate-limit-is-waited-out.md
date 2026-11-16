# D-899 a build's pinned download waits out a rate limit

- **Task:** FETCH-429. The red `demo-boot` on #820 (run 43836470900, 2026-11-16) was not that PR's change
- **PR:** this branch (`agent/FETCH-429-a-rate-limit-is-waited-out`)
- **Date:** 2026-11-16
- **Status:** accepted

## Cause

Three PRs (#817, #819 and #820) built their images at the same time. Maven Central answered
`HTTP Error 429: Too Many Requests` to `tools/fetch_pinned.py` three times for the translator's quick jar, and the
demo image's build failed. The fetch asks three times (D-632) and waits 2, then 5 seconds between asks, so its whole
retry window was 7 seconds. That is shorter than any rate limit.

## Decision

1. A rate-limit answer (HTTP 429, or 503) makes the next ask wait longer:
   - the server's `Retry-After` in seconds, when it gives one, capped at 120 seconds (`RATE_LIMIT_MAX`);
   - otherwise 30, then 60 seconds (`RATE_WAITS`).
2. There are still three asks in all (D-632 stands). Every other fault keeps its 2 and 5 seconds.
3. A pinned file with another sha256 is still refused at once.

## Test

`tests/unit/test_fetch_pinned.py`:

- A 429 or a 503 waits 30 seconds, and three of them wait 30 and 60 with the 429 in the reason. There are still three
  asks.
- A numeric `Retry-After` is used, and a very large one is capped at 120.
- A `Retry-After` given as a date gets the plain wait.
- A 404 keeps its 2 seconds.
- The existing tests are unchanged.
