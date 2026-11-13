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
   adapter's own cap". A time limit from the size needs a rate (seconds per patient), and the only measurement is
   tonight's one ingest; a rate written down now would be the kind of number OD-10 forbids, and it would cut the
   very nights the gate exists to measure (a slower night is a finding, not a time-out). The adapter's cap is a
   memory cap and says nothing about time. If a bound per part is wanted later, it can be derived from a few
   nights' reports, which item 3 now makes available.
3. **The report is written before every part, marked NOT FINISHED** (`Report.progress`): `generate`, `ingest
   (nightly)`, the back-fill, `site publish and lake rebuild`, `screen (cascade)`, `backup (nightly steps)`.
   Whatever cuts the gate (a time limit, a kill, a runner that goes away), the last report holds every finished
   part's result, seconds and peak memory, the rows of the checks made so far, and the part it was in. A check
   without a row was not reached. A process that was still running is shown as such, with no peak yet. The JSON
   has `unfinished` and `ok: false`; the last line reads `Gate: NOT FINISHED (in: <part>)`, never green or RED.
4. **The first write replaces an earlier run's report** in the same folder, so an old "green" cannot be taken
   for tonight's.
5. The nightly workflow is not changed: it already prints `scale_gate.md` into the job's summary and keeps it as
   an artifact, whatever the test's exit code.

## What this does not do

- It does not make the publish at 50,000 patients pass or fail: it lets the gate reach it and report it.
- A running service's peak memory is read when its block ends; a report written while the lake runs does not
  have the lake's peak.
- The suite's default limit stays for every other test.

## Tests

`tests/unit/test_scale_gate_partial_report.py` (the gate at 200 patients, as `test_scale_gate_logic.py` runs it):
a gate cut in the site publish leaves the ingest's row, result and peak, names the part, and is neither green nor
RED; a gate cut in `generate` or in the ingest names that part; a gate that ends says nothing of the kind and
lists every check; an earlier run's report is replaced at once; the gate's test carries its own limit (0 by
default, the variable's value when set) and the variable is declared; the suite's default limit is still there
and the nightly job has its own. **Interrupt:** the cut is an error that is no `Exception`, as a time limit's is.
