# D-916 The command-line canary is the gate's result

- **Task:** lane G's hand-over, F35 (#639, 2026-11-16, by way of the integrator). An operator at the box's command line could not run or read the gate's canary. `POST /models/canary` answered 403 to an operator's token. **Date:** 2026-11-16. **Status:** reserved.
- **Decision:**
  - **By design, unchanged.** `POST /models/canary` is the console's call alone (`route_callers.yaml`), and `GET /models` is a protected read (D-130). An operator's token does not call the orchestrator.
  - **The supported ways.** The admin Models tile's "Run now", and `sudo python3 -m tools.trialbox selftest` at the box (RUNBOOK §4).
  - **What was missing.** The second ran `python -m orchestrator.selftest` in the orchestrator's container, which printed the report and recorded nothing. So a pass there left the gate shut until the next night or a console click.
  - **The canary at the command line records the gate's result.** It is written as the night's canary is (`selftest.record`, shared with `preflight`):
    - `<orchestrator data dir>/selftest.json`, written whole and then moved into place (`orch_data_dir`: `TB_ORCH_DIR`, else `<data dir>/orchestrator`, as the orchestrator itself uses);
    - the audit's `selftest.passed` or `selftest.failed`, with `by: trialbox selftest`;
    - D-915's rule: a canary that could not reach a model writes nothing, audits `selftest.unreached` and exits 2, and the box command says "not run, wait a minute and run it again".
  - **The running gate takes it.** The orchestrator's gate re-reads `selftest.json` when the file changed and holds a newer result than its own (`at_epoch`, now in milliseconds). It applies it as its own record would:
    - a pass clears a failed wake check only if the pass came after it;
    - an older result written later is not taken;
    - the process's own writes are not read back.
- **Test:** `tests/unit/test_selftest_records_the_gate.py`.
