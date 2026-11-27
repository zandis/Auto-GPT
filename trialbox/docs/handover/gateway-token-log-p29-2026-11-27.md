# P29: the gateway logs the token counts of each call

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** P-29 (the integrator's R1+1 batch D, part H, comment 7210967559 on #1504)
- **Date:** 2026-11-27
- **Base:** int/r1plus1
- **Findings:** [`gateway-token-log-p29-2026-11-27/findings.json`](gateway-token-log-p29-2026-11-27/findings.json)
  (P29-01)

## What was there

The gateway's ledger record of an answered call (`llm.gateway.call` in the audit trail) already held `tokens_in` and
`tokens_out`, read from the server's `usage`, and `tools/run_metrics.py` sums them. Two gaps: the service log had no
line per call, so the counts could be read only by someone who reads the audit trail; and a server that gave no
`usage` left both counts at 0, which read as a call of no tokens.

## Change

- `services/gateway/core.py`: after the ledger record of an answered call, one INFO line on the logger
  `gateway.tokens`: call id, alias, build id, cache, `tokens_in`, `tokens_out`, `tokens_reported`, `tokens_estimated`
  and latency. Counts and labels only; never the prompt or the answer. `tokens_reported` (also in the ledger record)
  is true only when the server gave both counts as whole numbers.
- `tests/unit/test_gateway_token_log_p29.py`: the line carries the ledger's counts and none of the prompt's lines or the
  answer, through the service's JSON formatter (the scrubber leaves the counts as they are); a server without `usage`
  gives `tokens_reported` false; the stub's counts are logged as estimates.

## What ran

The new test on the base: 3 failed. At the head: 3 passed, with the gateway's own tests. The checks of the
hand-back ran from `trialbox/`.

## Not done

- `tools/run_metrics.py` still sums every call's counts; it does not yet leave out a call whose `tokens_reported` is
  false: P29-01.
- A refused call (`llm.gateway.refuse`) gets no line: it has no answer, so no counts.
