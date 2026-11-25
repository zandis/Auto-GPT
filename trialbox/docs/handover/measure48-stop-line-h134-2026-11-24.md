# H-134: the measure48 host form's stop-line test under CI load

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** H-134 (lane H)
- **Date:** 2026-11-24
- **Findings:** [`measure48-stop-line-h134-2026-11-24/findings.json`](measure48-stop-line-h134-2026-11-24/findings.json)
  (H134-01 to H134-02)
- **Test:** `tests/unit/test_measure48_host_h67.py::test_the_stop_line_interrupts_the_runs_measure_and_no_other_process_of_that_name`

## The fault

On CI (job 138687984359, shard 7, PR #1482, outside that PR's diff) the test failed on
`assert 'the stop line (64 min): SIGINT' in host.log`. The host log said
`DECISION s05-stub: not started (stage 4 not started: 1.02 h left before the stop line, its high is 1.05 h)`.

## The mechanism

The test ran `tools/measure48-host.sh run` with `TB_M48_LINE_MIN=64`, `TB_M48_TIME_SCALE=150` and the stand-in's
measure of pair-32k hanging. The host form counts the run's time as `USED0 + (date +%s - T0) * SCALE`
(`tools/measure48-host.sh`, `used()`), and every stage starts only when its high ends before the line
(`tools/measure48-vm.sh`, `gate()` and `stage()`; `tools/measure48_vm.py`, `gate()`). The line is 3,840 scaled
seconds:

| Gate | High | Scaled seconds left for it | Wall time from the start of the steps |
| --- | --- | --- | --- |
| stage 4, s05-stub | 1.05 h | 60 | 0.4 s |
| stage 6, the ladder | 0.80 h | 960 | 6.4 s |

On a loaded runner the steps before a gate took longer than that, the stage was "not started", the run ended at
the gate and the ladder never reached the hang, so no SIGINT was sent. Both forms were seen here: s05-stub not
started, and the ladder not started ("no option was kept").

## The change

The test only. The product's rule and its scripts are unchanged. The test puts a stand-in `date` on the rig's
`PATH` that answers `date +%s` from a file the test holds, and hands every other form to the real `date`. The clock
stands still from the start, so every gate sees no time used, however slow the machine. When the hanging
`measure --option pair-32k` has started (the calls file, as in the SIGTERM test), the test moves the clock 30 s,
75 minutes scaled, past the 64-minute line. The run's next poll sends the SIGINT. No assertion changed; the line, the
scale and the hang are the ones the test had.

## The proof

30 runs of the test (6 copies side by side, 5 each), beside 8 busy processes on 4 cores:

| Tree | Passed | Failed |
| --- | --- | --- |
| master ef215849 | 23 | 7 |
| the card's head | 30 | 0 |

Mutants, each against the card's test at the head, each red:

- No SIGINT at the stop line (`kill -INT` removed from `watched()`): fails, no `measure.pair-32k.json` was written.
- The SIGINT sent to every process matching the measure's pattern, not only the run's own: fails, "the stop line's
  SIGINT reached a process that is not the run's".
- The test's clock never moved: fails, the run ends at the cap (exit 3, not 1).

## Not done

- The CI job was not rerun; its log was read.
- The VM form's own test (`tests/unit/test_measure48_vm_h53.py`) was not changed; it was not seen red.
