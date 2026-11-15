# D-737 `eval qualify --box` fills in the paths the running box serves

- **Task:** BOX-QUALIFY, lane G's blocker 5 for R4 (qualifying on an installed box)
- **PR:** this branch (`agent/BOX-QUALIFY-the-box-fills-in-qualify-s-paths`)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-313 (one qualify command), D-734 (qualify names an installed release)

## Context

`tools/qualify.py` on a box needs `--model-dir judge=/verifier=`, `--server-log` and `--audit-dir`. On a box the
weights sit under `TB_MODELS_DIR` in a folder named by the profile's compose overlay, the model servers log to
Docker's json-file logs, and the gateway's audit is a named volume: nothing gave an operator those paths.

## Decision

1. `python3 -m tools.trialbox eval qualify --box ...` (`tools/box_qualify.py`) asks the running box through
   `docker compose ps -q` and `docker inspect` (`TB_COMPOSE`, `TB_DOCKER`, as the updater uses them):
   - `llm-service` is the judge and `llm-verifier` the verifier: the weight folder is the host source of the
     `/models` mount joined with the `--model=` argument; the log is `.LogPath`;
   - the audit folder is the host source of the gateway's `/data/audit` mount.
2. An option the operator gave is kept (a role named by `--model-dir`; `--server-log` and `--audit-dir` given at all),
   and the box's value is not added. Each filled option is printed.
3. What the box cannot say (a server not running, no mount, no log path) is printed and left out, never guessed;
   qualify then fails its own step for it.
4. The gateway's address and service token stay the operator's to give, as before.

## Test

`tests/unit/test_box_qualify.py` with a stand-in for compose and docker: before, a collection error (no module);
after, 7 passed.
