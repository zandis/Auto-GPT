# D-674 The scale gate is not cut by the suite's time limit, and a gate that is cut leaves its report

- **Task:** NEW-B-33 (from the nightly reading of 2026-11-13; placed by the integrator the same day)
- **PR:** this branch (`agent/NEW-B-33-scale-gate-fixture-limit-and-partial-report`), cut from master `906889ee`
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** T-687 / D-471 (the scale gate: the night of a 50,000-patient hospital, each part under its
  compose cap), the nightly job's own limit (`timeout-minutes: 340`, "the night is measured, not budgeted; a hang
  ends here"), OD-10 (no fixed limit that is not derived or a declared setting with a reason)

## Context

The nightly of 2026-11-13 (run 109, master `906889ee`, trains 8 to 11):

- **The night's ingest of 50,000 patients passed under the adapter's cap with the real HL7 validator:
  1,553,259 records in 817.8 s.**
- The whole gate is one module fixture of `tests/perf/test_scale_gate.py`. The suite's default limit
  (`timeout = 900` per test, in `pyproject.toml`) applies to a fixture's set-up, and cut the gate about 80 s into
  the site publish: "8 errors in 901.43s".
- The gate wrote its report only at its end. The night left no report: not the ingest's peak memory, nothing for
  the job's summary.
- **The site publish, the screen and the backup have never been measured at 50,000 patients on a schedule**: no
  scheduled run has got past this point with a report.

The 900 s was never meant for the gate. The job's own comment says the night is measured, not budgeted, and
`Params.publish_wait_s` says "the CI job's own timeout is the real bound".

## Decision

1. **The gate's test has its own limit, declared: `TB_SCALE_LIMIT_S`, empty by default, which is no limit.**
   `tests/perf/test_scale_gate.py` carries `pytest.mark.timeout(sg.limit_s())`. What ends a hang is the nightly
   job's `timeout-minutes` and the guards the gate's parts already have. A person who wants a bound on their own
   machine sets the variable.
2. **No limit computed from the site's size.** The integrator's note asked for one "from the site's size and the
   adapter's own cap". The adapter's cap is a memory cap and says nothing about time. For a time limit from the
   size there are measurements, but not ones to build a bound on:
   - tonight's ingest, 817.8 s for 50,000 patients, the first with the real validator on a schedule;
   - D-472's "a lake rebuild of 50,000 patients takes about 805 s" and the 50,000-patient row of
     `eval/hospital_sim/results/scale.json` (`pipeline_s` 804.6): the hospital simulator's, not the gate's, and
     not from a scheduled run;
   - **nothing for the site publish, the screen or the backup at that size**.
   A hang guard from a rate exists elsewhere (`TB_BACKUP_MIN_MBPS`, "a tenth of the measured" throughput of a
   backup step). The same could be done here per part once a few nights' reports exist; a rate written down today
   would be a guess for three of the five parts, and a limit set from it would cut the nights the gate exists to
   measure (a slower night is a finding, not a time-out). Item 3 is what makes those reports exist.
3. **The report is written before every part, marked NOT FINISHED** (`Report.progress`): `generate`, `ingest
   (nightly)`, the back-fill, `site publish and lake rebuild`, `screen (cascade)`, `backup (nightly steps)`.
   Whatever cuts the gate (a time limit, a kill, a runner that goes away), the last report holds every finished
   part's result, seconds and peak memory, the rows of the checks made so far, and the part it was in. A process
   that was still running is shown as such, with no peak yet. The JSON has `unfinished` and `ok: false`; the
   last line reads `Gate: NOT FINISHED (in: <part>)`, never green or RED.
4. **When the gate ends on an error that reaches it, it writes once more**: an error of its own (the generator
   failed, the stand-in did not start), or a cut that raises in the gate (a time limit's signal, an interrupt).
   The processes it started are stopped by then and have their results and peaks, and a note names what ended
   the gate, so a failure of the gate does not read as a cut.
5. **An earlier run's report in the same folder is removed first**, before anything that can fail, so an old
   "green" cannot be taken for tonight's. Each report file is replaced whole (a temporary file, then a rename).
6. `TB_SCALE_LIMIT_S` that is not a number of seconds is refused in words.
7. The nightly workflow is not changed: it prints `scale_gate.md` into the job's summary and keeps it as an
   artifact, whatever the test's exit code.

## What bounds the gate now, said plainly

Before, the suite's 900 s bounded the whole fixture (and cut every night of this size). Now:

- bounded by their own guards: the wait for a service to answer (120 s, 60 s), the stand-in's restart watcher,
  a service's stop, the backup's steps (a time from the data's size);
- **bounded only by the nightly job's 340 minutes**: a child process that never ends (`generate`, the ingests,
  the screen), and the site publish's two waits (`publish_wait_s`, 6 hours each, more than the job has);
- in each of those the last report names the part. One gap: while the lake service starts (up to 120 s) the
  report still names the part before it.
- **Not verified:** what GitHub does when the job's own limit ends it. The line that prints the report into
  the summary is in the same step as the test and probably does not run then; whether the artifact step
  (`if: always()`) still uploads the files after a job-level time-out was not checked. If it does not, a night
  that hangs for 340 minutes leaves its report only on the runner. Changing that is the workflow's, which this
  card does not touch.

## What this does not do

- It does not make the publish at 50,000 patients pass or fail: it lets the gate reach it and report it.
- A running service's peak memory is read when its block ends; a report written while the lake runs does not
  have the lake's peak.
- A check that is made at the end of its part (the rebuild's, after the screen) has no row in a report written
  before that, although the rebuild itself is done.
- The suite's default limit stays for every other test.

## Tests

`tests/unit/test_scale_gate_partial_report.py` (the gate at 200 patients, as `test_scale_gate_logic.py` runs it):
a gate cut in the site publish leaves the ingest's row, result and peak, names the part, and is neither green nor
RED; a gate cut in `generate` or in the ingest names that part; a gate that ends says nothing of the kind and
lists every check; an earlier run's report is replaced at once; the gate's test carries its own limit (0 by
default, the variable's value when set) and the variable is declared; the suite's default limit is still there
and the nightly job has its own. After the review: a gate ended by an error writes once more, with the stopped
lake's result and peak and a note of what ended it; a failure of the gate's own part says so; an earlier run's
report is gone before anything can fail; a cut in the middle of a write leaves the report before it; a limit
that is not a number is refused. **Interrupt:** the cut is an error that is no `Exception`, as a time limit's
is; and the report as a kill would leave it is read inside the part, before the cut.
