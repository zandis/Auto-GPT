# D-728 A gateway timeout and a failed context lookup are said, as fields

- **Task:** GW-SIGNALS (lane G's findings through the integrator, 2026-11-14: PR #585 comments, findings note on #592)
- **PR:** this branch (`agent/GW-SIGNALS-a-timeout-and-a-failed-lookup-are-said`)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** D-636 (no decision by the text of an error), D-456 (upstream_down and upstream_failed), D-445,
  T-603 (the client's context lookup), SCR-18 (#578: the run counts the prompts it sized on the default)

## Context

1. A model server that timed out under a batch call gives the refusal `upstream_failed` (never sent again, D-456).
   That it was a timeout was in the refusal's message text only (`llm-service: ReadTimeout`), so a caller that wanted
   to tell a slow server from a broken answer had to read the text, which D-636 forbids.
2. `tb_llm.GatewayClient.contexts()` returned `{}` on any failed `GET /v1/models` (an HTTP error status, a dropped
   connection, an answer that is not JSON), with no log line and nothing a caller could read. SCR-18 (#578) made the
   screening run count the prompts it sized on the default when the lookup gave nothing; why the lookup gave nothing
   was still said nowhere.

## Decision

1. A batch upstream timeout is an `Upstream` error of its own kind, `timeout` (an interactive one stays `busy`). The
   gateway's refusal carries the kinds of the model servers' errors, sorted, as `upstream_kinds`: in its answer
   (`error.upstream_kinds`) and in its audit record (`llm.gateway.refuse`, `detail.upstream_kinds`). A refusal the
   gateway made before sending anything has none. The refusal's code is unchanged: a timeout is still
   `upstream_failed`. `tb_llm.GatewayRefused.upstream_kinds` gives them to the caller (empty from an older gateway).
2. `contexts()` still gives an empty map on a failed lookup (the caller keeps its own default; the gateway still
   checks the prompt's size), and now logs a warning naming why (`HTTP <status>`, the error's type, or "not JSON"),
   never a body, and keeps it in `GatewayClient.last_context_error` (None after a lookup that answered). A failure
   is not kept as an answer: the next call asks again, as before.

## Test

`tests/unit/test_gateway_failures_said.py` (before: `10 failed, 2 passed`): the kinds of a timeout, a 503 met
twice and a refused connection, in the answer and the audit; a timeout still `upstream_failed` and sent once; no
kinds on a refusal made before any server; `tb_llm` gives them, and none from an older gateway's refusal; a failed
lookup logged and kept for 503, 401, a refused connection and an answer that is not JSON, and asked again; a lookup
that answers clears the error.
