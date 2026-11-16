# D-973 the nightly's mutation shards end inside 90 minutes; the scale gate says the model's share

- **Task:** lane D, the owner of the nightly; the integrator's request on #639 (2026-11-16), inside D-970's scope (no
  new ruling); D-537 (the owner: no CI job over 90 minutes, the work shrunk, no ceiling raised)
- **PR:** this branch (`agent/CI-NIGHTLY-mutation-in-six-parts-and-the-scale-latency-share`)
- **Date:** 2026-11-16
- **Status:** accepted
- **Builds on:** ENG-006 (`tools/mutation.py --part K/N`, engine.py in two parts), T-687 (D-471, the scale gate)

## Context

The nightly quality run of 2026-11-16 (run 43912198355): the mutation shard `engine-1` took 207 minutes and `engine-2`
149, for `services/matching/cascade/engine.py`'s 563 mutants (20 not run: the 200-minute budget ran out). The job's
timeout was 300 minutes. D-537 sets 90 minutes for any CI job.

The scale gate at 50,000 patients took 74 minutes (68 the night before) with a 2-second model stand-in, and its report
did not say how much of that was the stand-in waiting, so the time could not be read.

## Decision

1. `engine.py` runs in six parts (`--part 1/6` to `6/6`; every mutant in exactly one, as ENG-006 made them). About 356
   minutes of mutants come to about 60 minutes a part.
2. The mutation job's timeout is 90 minutes, and no mutant starts after 75 (`--budget-minutes 75`), which leaves room
   for the set-up (about 7 minutes) and the mutants still running. A mutant not started is listed, as before; the
   score job reads every shard as before.
3. The scale gate's report has one more line, after the screen: the stand-in's calls times its seconds per call, as a
   share of the screen and of the night up to the screen's end. It is an upper bound, since calls that overlap wait at
   the same time; the line says so.

## Test

`tests/unit/test_nightly_shards_under_90.py`: the mutation job's timeout is at most 90 minutes with at least 10 minutes
over the budget; the engine.py shards are parts 1 to N of N, each once, N at least 6; `latency_share` words and numbers;
no line without a latency or calls; the gate calls it.
