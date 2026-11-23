# H-83: the unit split measured again: eight shards, the costliest files pinned

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** H-83 (finding H73-02; the integrator's red of 2026-11-22, 11:31 UTC: `unit-shard (4/6)` took 39:05 of 40)
- **Date:** 2026-11-22
- **Decision:** below, "The decision" (a number is needed: lane H's blocks are used up)
- **Findings:** [`unit-shard-split-measured-again-2026-11-22/findings.json`](unit-shard-split-measured-again-2026-11-22/findings.json)
  (H83-01); H73-02 is closed in
  [`unit-shard-1-fits-again-2026-11-22/findings.json`](unit-shard-1-fits-again-2026-11-22/findings.json)
- **Cost table:** [`unit-shard-costs-h83.json`](unit-shard-costs-h83.json); **pins:** `tools/test_shard_pins.json`
- **Tests:** `tests/unit/test_test_shard.py` (the H-83 section)

## Pull request body (draft)

**The measurement.** I read the 57 unit-shard jobs of the TrialBox CI runs of trains 117 to 124 (runs 44892354521,
44989523501, 44993980995, 44997557464, 45000477302, 45004047123, three runs of train 123 (45008451042,
45011639429, 45014360930), and the finished shards of 45018665784). The job times come from the API. Each job's
`--durations=30` list comes from its public log. All jobs ran on image ubuntu-24.04 20261111.635.

| Shard (of 6) | Jobs | pytest, median (min) | pytest, max (min) | Set-up (min) |
| --- | --- | --- | --- | --- |
| 1 | 9 | 27.4 | 32.8 (train 123, 2nd run) | 0.2 to 0.7 |
| 2 | 10 | 16.7 | 21.3 | 0.4 to 0.6 |
| 3 | 9 | 24.0 | 34.6 (train 119) | 0.2 to 0.6 |
| 4 | 9 | 27.5 | 38.5 (train 123, job 137183491766: 39:05 in all) | 0.4 to 0.7 |
| 5 | 10 | 20.7 | 26.8 | 0.3 to 0.6 |
| 6 | 10 | 19.1 | 27.4 | 0.3 to 0.7 |

- **Where the 39:05 went:** all of it was pytest (38.5 minutes). Set-up took under a minute in every job.
  - That job's own tests ran about 1.55 times their usual time: `test_ingest_streams` took 158 s against 100 s, and
    `test_plain_menu` (flag off) took 154 s against 95 to 101 s.
  - The tests that wait rather than compute stayed the same: `test_g1_box_install_run` took 58 s against 55 s.
  - The same thing happened to shard 4 on train 119 (38.0) and to shard 3 on trains 117, 119 and 121 (33.5 to 34.6,
    with `test_e2e_simple` at 723 to 738 s against 467 to 480 s).
  - So the runners differ: a slow runner takes up to 1.55 times as long on CPU-bound tests. About one shard job in
    four runs on such a runner (13 of 56 jobs read 1.15 times or more on their listed tests).
  - There is no new heavy test, and nothing points to one shard. Shard 4 is simply one of the two largest shards,
    and it got the slow runner.
- **The spread:** on a normal runner the hash put 16.5 to 27.5 minutes on the six shards, about 132 runner-minutes
  in all. Even split perfectly, six shards come to 22.3 minutes each, about 34.5 on the slowest runner seen. That is
  14 % under the limit, not the 30 % asked for.
- **The per-file table** ([`unit-shard-costs-h83.json`](unit-shard-costs-h83.json)) holds 1,208 files and 22,942
  tests, collected locally with `make test`'s `-m`.
  - A test in a `--durations=30` list counts its median over the runs it appears in.
  - Every other test counts its old shard's residual, which runs from 0.43 to 1.81 s a test: four workers times the
    shard's median normal-runner minutes, less its listed tests, divided by its other tests.
  - So the table is exact for each old shard and estimated for each file. The logs list only the 30 slowest tests
    of each shard, and no full per-test run was made.
  - The 20 costliest files carry 26.6 % of the time.

**What moved.**

1. `tools/test_shard.py` now places a file by its pin when `tools/test_shard_pins.json` is for this N. Every other
   file keeps the hash.
   - The pins are what `python -m tools.test_shard plan docs/handover/unit-shard-costs-h83.json` gives. It takes the
     20 costliest files of the table, costliest first, and puts each on the shard with the lowest cost so far. The
     shards start with their hashed files.
   - A new file keeps the hash, and no pin moves when a file is added.
   - `check` is unchanged. It proves the union from the shards' own records, whatever the split.
2. The `unit-shard` matrix goes from 6 to 8 shards (`.github/workflows/trialbox-ci.yml`). The random-order nightly
   goes from 6 to 8 as well (`.github/workflows/trialbox-e2e.yml`), because a test holds it to the gate's shards.
3. The limit stays at 40 minutes.

| Split | Per shard, normal runner (min, estimated from the table) | Max | Max × 1.55 (slowest runner seen) |
| --- | --- | --- | --- |
| hash, 6 (now; matches CI by construction) | 27.0 16.5 23.4 27.4 18.9 18.5 | 27.4 | 42.5 (measured 38.5) |
| hash, 8 | 23.0 13.4 12.5 14.3 12.6 21.5 21.2 13.3 | 23.0 | 35.6 |
| 20 pins, 6 | 22.3 21.5 21.9 22.3 22.3 21.5 | 22.3 | 34.5 |
| **20 pins, 8 (this card)** | 16.8 16.8 16.8 16.1 16.2 16.7 16.4 16.1 | **16.8** | **26.1** |

- **Expected after:** each shard should take about 16 to 17 minutes on a normal runner and about 26 on the slowest
  runner seen. That leaves 35 % of the 40-minute limit, against 2 % for job 137183491766. These figures are
  estimated from the table, not measured on CI.
- **Tail:** the longest single test is `test_e2e_simple`, at 8 minutes, or 12 on a slow runner. It sits on shard
  4 of 8.
- **Cost:** two more runners for each full-tier push, which are free on a public repository. `unit` still waits for
  the slowest shard, so it should come about 10 minutes sooner.

**Proof that no test is lost or doubled.**

- Locally, `pytest --collect-only --shard i/8 --shard-record` for i = 1..8, then `tools.test_shard check`:
  "22951 tests, each in exactly one of 8 shards (1: 3580, 2: 2823, 3: 2623, 4: 2472, 5: 2397, 6: 3200, 7: 3953,
  8: 1903)".
- CI's `unit` job runs the same check over the eight records, unchanged.
- `test_every_test_file_is_in_exactly_one_shard[8]` now runs with the pins.

**Tests added** (`tests/unit/test_test_shard.py`):

- every pin names an existing file, on a shard in 1..N (so the list cannot rot);
- the pins are exactly `plan` of the committed table;
- the pins' N is the workflow matrix's length;
- under the pins, every shard is within 10 % of the mean;
- a pinned file goes to its pin, and every other file keeps the hash;
- a new file moves no file;
- the plan is deterministic;
- the CLI prints the plan;
- the table is not older than the suite by more than a quarter. A tree with 25 % more test files than the 1,223 it
  was measured on fails, and the fix is to measure again.

**Workflow lines.**

- `trialbox-ci.yml`: four comment lines are added after line 301, and the matrix line 318 changes to
  `[1, 2, 3, 4, 5, 6, 7, 8]`.
- `trialbox-e2e.yml`: line 139 (the random-order matrix) changes. Lane R's new job is not touched.
- Draft #1295 changes line 38, line 124 and the line after the unit-shard checkout (321). Line 318 is two unchanged
  lines above that, and git merges the two without a conflict (checked with `git merge-tree`).

## The decision (a number is needed)

**The unit shards: eight, with the costliest files pinned from a measured table.**

- The unit tier runs in eight shards.
- A test file's shard is its pin in `tools/test_shard_pins.json` when the pins are for that N. Otherwise it is the
  hash of D-475.
- The pins are `tools.test_shard plan` over a per-file cost table measured from CI's shard jobs, and they are never
  edited by hand. The table states how it was measured.
- The shards' records prove the union as before.
- The table is measured again, and the plan re-run, when a shard comes within 30 % of its limit on a runner, or when
  the tree has a quarter more test files than the table (a test holds this).
- The limit stays at 40 minutes. D-564's derivation from 24.8 × 1.5 stays beside it. By this card's figures the limit
  could be read as 26.1, rounded up to 30, but that is not done before eight green runs of the new split are
  measured.

## What was not done or not verified

- No CI run of the new split exists yet. The minutes per shard after the change are estimated.
- The per-file costs below each shard's 30 slowest tests are a shard average, not measured per test. A file
  heavier than its shard's average can make one shard longer than estimated. The next measurement, from the eight
  shards' `--durations=30` lists, will show it.
- The shards' artifacts (records, traces) were not read; they need a token.
- `tests/console/test_prefs_10f1.py` is not touched. It is lane K's (H73-01). It is pinned alone with the hash's
  files on shard 8, where its seven cases spread over the four workers through worksteal (D-1355).
