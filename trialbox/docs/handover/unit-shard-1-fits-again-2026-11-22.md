# H-73: unit-shard (1/6) fits its limit again; a shot master could not draw is not compared

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** H-73 (the integrator's red of 2026-11-22, 03:14 UTC; part B "also yours or lane K's (9k-17)")
- **Date:** 2026-11-22
- **Decision:** [D-1355](../decisions/D-1355-the-unit-workers-steal-queued-tests.md)
- **Findings:** [`unit-shard-1-fits-again-2026-11-22/findings.json`](unit-shard-1-fits-again-2026-11-22/findings.json)
  (H73-01 to H73-03)
- **Tests:** `tests/console/test_visual_regression_9k17.py` (`test_h73_*`)

## Pull request body (draft)

**Part A.** `unit-shard (1/6)` was cancelled at 40 minutes with no failing test (train 117 job 137064085949; trains
115 and 116: 136736718671, 136754566093; also 136673602037). In every shard-1 job read, green or cancelled, the
progress stops near 86 % or 92 % for 9 to 15 minutes. The `--durations=30` lists of the green jobs 136657143745,
136810764192 and 136799318979 name the cause: the seven role cases of
`tests/console/test_prefs_10f1.py::test_no_preference_opens_a_route_or_shows_a_patient_value_the_defaults_do_not`,
150 to 260 s each (sum 1,127 to 1,440 s). xdist's default `load` schedule sends a worker the next tests as one run of
the collection, so the seven neighbours go to one worker and run one after another while the other three idle. It
is not the PostgreSQL start race of H-72: the stalled worker is busy (85 % CPU) and the walks are pure HTTP.

The fix: `make test` passes `--dist worksteal` whenever it runs workers (`trialbox/Makefile`, D-1355): an idle
worker takes half of a busy worker's queue. The split, the shards' files and the 40-minute limit are unchanged.
`.github/workflows/trialbox-ci.yml` is not touched, so nothing collides with #1295.

**Part B.** The `visual` job failed when master's Chromium could not capture a shot ("not drawn on master: ...
Unable to capture screenshot", jobs 137064002520 and 136754404730). `tools/visual_regression.py` now takes a failed
capture again (only the failed shots, at most `CAPTURE_TRIES` = 3 times in all), and a shot the pull request drew
but master could not (master's own error recorded, or master's whole shoot failed) is "not compared": listed by
name in the report with master's error and not counted against the card. A shot only missing on master (a new page)
still differs; the pull request's own failure still counts (exit 2 as before); a shot drawn on both sides is
compared exactly as before. Files outside the card: `tools/visual_regression.py` and
`tests/console/test_visual_regression_9k17.py` (lane K, card 9k-17).

## Measurement

Per shard, from the 11 runs of trialbox-ci between 2026-11-20 and 2026-11-22 03:38 UTC that ran the shards (job
minutes from the API; before this change, schedule `load`):

| shard | green median | green max | not green |
| --- | --- | --- | --- |
| 1/6 | 33.6 | 39.9 | 4 cancelled at 40.3 |
| 2/6 | 19.3 | 28.1 | 1 failure |
| 3/6 | 22.7 | 33.9 | 1 failure |
| 4/6 | 28.2 | 31.9 | 1 failure |
| 5/6 | 23.0 | 31.1 | |
| 6/6 | 27.4 | 34.5 | 2 failures |

Shard 1's progress (job start to the percentage line, minutes): 86 % at 16.7 to 25.3, then 13 to 21 minutes for the
rest in the green jobs; the cancelled ones reached 86 % at 21.1 to 25.3.

Locally (4 cores, `-n 4`, no `PYTHONUNBUFFERED`, a base temp path over 100 characters, root), the 28 console files
of shard 1 (372 tests):

- `--dist load`: 2,044 s; the seven cases 257 to 300 s each, 1,923 s together; at 96 % one worker at 85 % CPU, three
  idle. 5 failures of `tests/console/test_grant_box.py` ("failed in reporting": the fonts were not fetched yet).
- `--dist worksteal`: AFTER_LOCAL

Estimate for CI (not measured on CI): AFTER_CI
