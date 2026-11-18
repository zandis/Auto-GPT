# D-1137 The size test is a stub-model measurement on a named machine, never the capacity statement

- **Task:** H-23 (the integrator, PR #639, 2026-11-17 08:12 UTC: "Size test on the reference machine's shape")
- **PR:** this branch (`claude/lane-h-23-size-test`)
- **Date:** 2026-11-17
- **Status:** proposed (merges on green CI)
- **Builds on:** T-687 and D-471 (the scale gate), D-674 (its report), D-748 and D-924 (S1 in batches), D-973 (the
  model's share), D-146 (screen the whole hospital), D-315 (no default site zone); T-667 (the capacity statement)

## Context

The integrator asked for the time and peak memory of ingest, a feasibility run and a screening run at a hospital's
size (up to 20 studies and 200,000 patients) under the stub model, and for the size at which a stage first slows. The
nightly scale gate measures one study at 50,000 patients. Lane G's and lane B2's earlier figures at 5,000 and 50,000
are superseded (validation reset of 2026-11-14) or measure one stage only (the bench gate at 5,000).

## Decision

1. **What the size test measures.** `tools/size_ladder.py` drives the product's own tools and adds no generator or
   instrument. At each size it runs:
   - lane B2's scale gate (`tools/scale_gate.py`): the synthetic hospital, then the night's ingest, the lake's
     rebuild with the site publish, and the cascade of one study. Each part runs in its own process under its compose
     service's memory cap (`deploy/docker-compose.yml`). The model stand-in answers at once;
   - the orchestrator's own FEAS and SCREEN jobs for each study in turn, in one process under the `orchestrator` cap.
     They read the lake service (under the `lake` cap) over HTTP and are judged by the stub model. SCREEN is asked for
     the whole hospital (D-146).

   The studies are the eight shipped rulesets. A rung of more than eight studies runs the same rulesets again, in the
   same order, and the results say so. For each stage the test records the wall time, the peak resident memory of the
   process tree against its cap, the time per patient (FEAS and SCREEN: per patient and study), the stage's own counts
   (records, patients in scope, model calls, the stub's own time), and the spread of repeats where there are repeats.
2. **Where a stage first slows** is the first size whose time per unit is more than 1.5 times the lowest time per unit
   at every smaller size. Stages shorter than 5 s are not judged, because start-up costs dominate them.
3. **What it may be quoted as:** "a stub-model measurement on <the named machine>, at <commit>". It is never the
   capacity statement (T-667). It is never a figure for the reference workstation, a GPU box, a real model or WSL2. It
   may not be used to predict a size it did not reach.
4. **Limits found go to their owning lane.** The size test changes no product file. A limit is recorded with its
   stage, size, time and memory, and the function where the time goes when a profile shows it. It is handed to the
   lane that owns that code: B2 for the lake, the synthetic hospital and the scale tools; A2 for screening and the
   cascade; D for the installer and sizing.
5. **The results file keeps only a summary.** The raw runs, the generated hospital and its databases are removed after
   each size. The committed results are the page `docs/plan/measurements/size-test-2026-11-17.md` and its small JSON.

## Amendment (H-23b, 2026-11-18): a lifted cap, the run's conditions, the cascade's stages

The integrator asked for the figures H-23 could not reach (2026-11-18 12:03 UTC, "H-23's size ladder finished").
What the ladder measures changes in three ways; the rest of this decision stands.

6. **A cap may be lifted for a measurement, and is then named.** A run may be given a compose memory setting from the
   environment (`TB_MEM_ORCH`, `TB_MEM_LAKE`, `TB_MEM_ADAPTER`), as compose reads `deploy/.env`. No product file and
   no shipped default changes. Each run records the caps in force, the settings that moved them and whether the night's
   ingest ran the HL7 validator or the structural check alone. A row under a moved cap is its own row, marked
   "lifted", and is quoted as "with the cap lifted to X", never as the shipped shape. The first-slow rule uses the
   shipped cap's row at a size when that row finished, else the lifted row, and names the sizes it judged on a lifted
   cap.
7. **The gate's cascade may be traced stage by stage.** `--trace-cascade` runs the scale gate's own cascade child again
   over a size kept with `--keep`. Each top-level stage of `run_cascade` (and the return of S1's row read) is timed,
   with the process's resident peak within it. With `--trace-frames`, Python's tracer also reports the stage's traced
   peak and the largest allocation sites still held. The tracer slows the run several times, so its times are not the
   ladder's. The stages are wrapped in the child process only.
8. **The validator is a condition, not noise.** The ingest's time and memory depend on whether the HL7 validator runs
   (about 2 to 3 times the time). Figures are compared only between runs with the same validator.

## Tests

`tests/unit/test_size_ladder.py`: the plan parser and its refusals; the shipped studies, cycled; the spread, the
per-unit rates and the 1-, 5- and k-study marks; the first-slow rule (the factor, the 5-second floor, a single size);
the stage rows and the summary on made-up runs; a failed job, and a job cut at its cap, shown as FAILED; a stage killed at its cap not judged for slowing; the results file's keys and compaction;
the job child compiles; no run without `TB_TZ`. H-23b adds: the conditions a run records (the caps, the settings that
moved them, the validator); a lifted cap as its own row, marked, and named in the first-slow result; the trace child
compiles with the gate's cascade and names stages that exist; the stage memory table; no run without a plan or a
trace. It needs no data and no processes, and runs in seconds.
