# D-976 the gateway's and model-guard's untested branches get tests; no floor moves

- **Task:** lane D (it owns `services/gateway` and `services/model_guard`); D-537's CI findings, the nightly quality run
  43912198355 (2026-11-16)
- **PR:** this branch (`agent/COVERAGE-D-the-gateway-and-model-guard-branches-tested`)
- **Date:** 2026-11-17
- **Status:** accepted
- **Builds on:** D-727 (the nightly branch coverage and its ratchet), D-739 (GUARD-TOKENIZE)

## Context

The nightly's `branch-coverage` job failed on three floors. Two are lane D's:

- `services/gateway/core.py`: branch coverage 87.37 % against its floor of 89.16 % (baseline 89.66 % less 0.5);
- `services/model_guard`: 93.33 % against its baseline of 96.15 % less 0.5. Its last change was lane D's own
  GUARD-TOKENIZE (D-739).

The third, `services/orchestrator/scenarios/evaluate.py` (88.64 % against 90 %), is another lane's and goes to it
through the integrator.

## Decision

Tests for the branches no test walked; no floor or baseline in `tools/coverage_baseline.json` is touched.

- **model-guard** (`tests/unit/test_model_guard_branches.py`): an IPv6 literal as the Host is never a route; a body
  length that is not a number is refused; `HEAD` is not found; a model server that is not there is a 502 that names
  the kind of the error, never where it went; the key file comes first, and an unreadable or empty one falls back to
  the variable.
- **gateway** (`tests/unit/test_gateway_branches.py`): a message whose content is a list of parts; the schema check
  with no schema, a broken answer and a valid one; the stall probe with no endpoint, no URL, a server that answers,
  one that fails and one that is not there, and the endpoint's key sent with it; an empty message list; a model not
  on the route; a release with no swap; an answer that is not a chat completion.

Measured locally with the gateway's tests: `gateway/core.py` 178 of 198 branches (89.90 %, was 88.89 %);
`model_guard` every branch (was 2 of 30 missed). The nightly's coverage job is the measurement of record.

## Test

The two files above (16 tests). They test the code as it is; no product code changes.
