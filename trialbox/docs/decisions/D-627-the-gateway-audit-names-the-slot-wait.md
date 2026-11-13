# D-627 The gateway's audit record names how long a call waited for a slot

- **Task:** GW-SLOTWAIT (asked by lane G after GPU run C, through the integrator, 2026-11-13)
- **PR:** this branch (`agent/GW-SLOTWAIT-audit-names-the-wait`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-445 (the gateway under load: slots per endpoint from the serving record)

## Context

An endpoint takes at most its slots (the server's `max_num_seqs`); a call beyond them waits in the gateway. The
audit record of a call gives `latency_ms`, the time the model server took to answer. The time before that, spent
waiting for a slot, was recorded nowhere, so a slow run could not be told apart: a slow server, or a queue in
front of it. Lane G's load measurements need the two apart.

## Decision

Every record the gateway writes for a call (`llm.gateway.call` and the refusals) carries `slot_wait_ms`: the
time the call spent waiting for a slot, summed over the endpoints it tried, whether it got the slot or was sent
away busy. A call that needed no slot (a cache hit, a refusal before dispatch, an endpoint without slot control)
has 0. `latency_ms` is unchanged and does not include it.

## Consequences

- From the audit alone: time in the queue and time at the server, per call.
- No new event, no new setting, no change to what a caller receives.
