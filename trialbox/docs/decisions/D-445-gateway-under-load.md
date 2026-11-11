# D-445 The gateway under load: one timeout budget, slots and a breaker per endpoint, the swap held by its owner

- **Task:** T-608 (`docs/plan/28-master-plan-v6.md` §6.2)
- **PR:** this branch (`agent/T-608-gateway-under-load`)
- **Date:** 2026-11-11
- **Status:** proposed (merges on green CI)
- **Closes:** LLM-023, LLM-022, LLM-032, LLM-046; the audit and PR #263 review items on the one-GPU swap, the
  `service` field of gateway audit records and the model key copy in `deploy/.env`
- **Builds on:** D-437 (the verified caller; the swap for `serving_control`), D-116 (the one-GPU swap and its hold),
  T-601 / D-276 (at most one retry, on the same build), T-603 (context sizes), D-177 (the model key)

## Decision

1. **One timeout budget across the three layers** (`tb_llm.timeouts`). Gateway to model: connect 5 s, read 180 s
   for a batch role, 30 s for an interactive role (`TB_GATEWAY_INTERACTIVE_TIMEOUT_S`, as before). One call has a
   budget of 210 s inside the gateway (`TB_GATEWAY_CALL_BUDGET_S`) that its retry and any fallback share: no attempt
   starts with less than 1 s left, and each attempt's read limit is cut to what is left. Callers (`tb_llm`,
   `tb_common.llm`) wait 240 s (connect 5 s), longer than the gateway's budget, so the gateway always answers
   before its caller gives up and never works on a call nobody waits for. A test holds the order
   (caller > budget > read).
2. **One retry on a dropped connection, never on a timeout.** `tb_llm.GatewayClient` and the direct (DEV) path of
   `tb_common.llm` send the same request once more after 0.5 s when the connection failed or dropped (connect
   error, connect timeout, a closed or broken connection): the same body, so the same role and, on a patient role,
   the same build (T-601's rule stays: at most one retry, on the same build, never another role's model). A read
   timeout is not retried (the gateway may still be working on it). So one dropped connection no longer counts as a
   model failure toward a screening run's 10 % stop rule.
3. **Slots per endpoint.** Each endpoint takes at most as many calls at a time as its server runs sequences:
   `max_num_seqs` of its server in the serving record (`TB_SERVING_RECORD`; container `judge` is endpoint
   `serving`, `verifier` is `verifier`), else `TB_GATEWAY_SLOTS` (16, the measured profiles). An interactive call
   waits at most 0.5 s for a slot, then gets `model_busy` (503, `Retry-After`); a batch call waits within its
   budget.
4. **No thread exhaustion.** Chat calls run on their own thread limit (`TB_GATEWAY_MAX_INFLIGHT`, 64), never on the
   pool that `/healthz` and the registry view use. A call that finds that limit full is answered `model_busy` at
   once without taking a thread; 8 of the 64 are kept for interactive roles, so a batch flood cannot shut out the
   front desk. `/readyz` and `/v1/serving/status` are `async` and take no thread.
5. **A breaker per endpoint, on `/readyz`.** It opens after 3 failures in a row (`TB_GATEWAY_BREAKER_FAILURES`: a
   connection error, a batch read timeout, an HTTP 5xx after the retry), or when the endpoint is stalled: calls are
   in flight, none finished for 40 s (`TB_GATEWAY_STALL_S`) and its server does not answer `GET /models` within 3 s
   (a watch thread looks every 5 s). An interactive timeout alone does not count: a busy server is not a dead one.
   While open, a call to that endpoint is not sent: an interactive role gets `model_busy`, a batch role
   `model_unavailable` (503, `Retry-After`), and a route with `fallback: any` tries its next build. After 30 s
   (`TB_GATEWAY_BREAKER_OPEN_S`) one call is let through; its answer closes the breaker, its failure opens it
   again. `/readyz` lists each endpoint's breaker and says `degraded` while one is open; with a server that never
   answers it shows the open breaker within 60 s.
6. **The swap belongs to its owners, also on demand.** A hold records the verified service that took it
   (`/v1/serving/activate` with `hold`). While a hold is active a chat call never wakes the sleeping model: a call
   from the holder's own service gets `model_asleep` (activate first), any other call `model_busy` at once, both
   without sending. With no hold active, a call whose own route leads to the sleeping model may still wake it (the
   doc parser and the criteria compiler compile protocols outside a screening run and need their model awake);
   the check and the wake happen under one lock, so a hold taken meanwhile wins. A call extends a hold
   (`touch`) only when it comes from the holder's service. Every `llm.gateway.swap`, `swap_release`,
   `swap_failed` and on-demand swap record carries `service`, and so does the start check's refusal
   (`weights_changed`, `model_mismatch`).
7. **The judge's answer is checked on every path.** `GatewayJudge` (the cascade's offline path) validates the
   answer against the prompt's output schema as `tb_common.llm` does; an answer outside it is `unknown`
   (`refused: schema_invalid`), never read for its verdict.
8. **Tools say what they do not measure.** `tools/judge_eval.py` on the stub is a wiring test (its agreement is 1.0
   by construction: the stub's rules are the fixture's sentence templates) and says so in its report; the
   real-model mode goes through a gateway (`--gateway-url`), with its forced sampling, never straight to a model
   server. `tools/bakeoff.py` lists what its plan does not measure and labels its token figures as estimates
   (`tb_llm.budget`, CJK-aware). The stub's token counts use the same estimate and are marked `estimated` in
   `usage`; the gateway's call record carries `tokens_estimated`.
9. **The model key's two copies must agree.** `trialbox secrets init` and `trialbox update` refuse to go on when
   `deploy/.env`'s `TB_LLM_API_KEY` is set and differs from `deploy/secrets/model/llm.key`, instead of overwriting
   the hand-changed one; `trialbox secrets rotate --service model` makes them equal again. An empty copy is still
   filled from the file.

## Consequences

- A call that hangs costs the gateway at most 210 s and one slot; the 65th parallel call costs nothing.
- A screening run that fails over its 10 % rule now sees real model failures only, not one dropped connection.
- New settings, each declared in `libs/tb_common/config.py`: `TB_GATEWAY_UPSTREAM_READ_S`,
  `TB_GATEWAY_CALL_BUDGET_S`, `TB_GATEWAY_SLOTS`, `TB_GATEWAY_MAX_INFLIGHT`, `TB_GATEWAY_BREAKER_FAILURES`,
  `TB_GATEWAY_BREAKER_OPEN_S`, `TB_GATEWAY_STALL_S`, `TB_LLM_TIMEOUT_S`.

## Open

- `TB_DATA_CLASS` sets the class of every `tb_common.llm` call of a service whose step names none, also below a
  phi prompt's D3 (`tb_llm.client.v1_labels`). The test and PoC stacks need it to make synthetic notes D0, so it
  is not changed here (see the PR's findings).
- The slots are sized from the serving record at start; a record changed while the gateway runs takes effect at
  its next restart.
