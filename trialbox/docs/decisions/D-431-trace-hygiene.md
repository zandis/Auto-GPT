# D-431 Prompt text out of stores: no D3/D4 text in the PRODUCTION trace store, a prune on a schedule, no model output in schema-violation details, quiet vLLM logs, an upstream allow-list

- **Task:** T-605 (`docs/plan/28-master-plan-v6.md` §6.2.4)
- **PR:** this branch (`agent/T-605-trace-hygiene`)
- **Date:** 2026-11-11
- **Status:** accepted for new rows; existing trace rows wait for the owner's ruling (see Open)
- **Closes:** LLM-040, LLM-041, LLM-042 (in part), LLM-019 (the body part), REG-012 (the trace part)
- **Builds on:** T-208 / D-346 (7-day PRODUCTION retention, no-text studies), D-126 (schema `trace`)

## Decision

1. **No D3/D4 text in PRODUCTION.** In PRODUCTION a trace whose `tb.data_class` is in
   `production_no_text_classes` (`D3`, `D4`; `services/tracestore/tracestore.yaml`) keeps the call id, span,
   special-category mark and safe attributes, and the prompt and output as `prompt_digest` / `output_digest`
   (sha256 and size) only. DEV and TEST keep redacted text, on synthetic data only.
2. **Prune on a schedule.** A write prunes when the last prune is older than `prune_every_hours` (1) by the injected
   clock. PRODUCTION retention stays 7 days (D-346). No separate job is needed.
3. **Existing rows are kept.** Schema `trace` version 2 adds `traces.policy` (default 0). New rows are written with
   policy 1. Every prune, scheduled or by `POST /v1/prune`, deletes policy-1 rows only. Rows from before this
   decision are neither deleted nor rewritten.
4. **Schema-violation details hold no model output.** The audit event `llm.schema_violation` and `LlmSchemaError`
   carry `path: validator` only (`verdict: enum`; `tb_contracts.schema.schema_error_codes`). The retry message
   sent back to the model in the same call keeps the full message.
5. **vLLM logs no requests.** Every vLLM service in compose sets `VLLM_LOGGING_LEVEL=WARNING`, so request and
   prompt lines (INFO) never reach the container log. An environment setting was chosen over a command flag
   because the request-logging flag changed name across vLLM versions and an unknown flag stops the server.
6. **Only allow-listed fields go upstream.** The gateway sends `messages`, `max_tokens`, `max_completion_tokens`,
   `response_format`, `reasoning`, `reasoning_effort` and the sampling fields (then forced) to the model server,
   and drops the rest (`n`, `logit_bias`, `stop`, `chat_template_kwargs`, `user`, ...).

## Open

- **Existing trace rows: owner ruling needed.** Rows written before this decision (policy 0) may hold redacted D3
  note text and are older than 7 days on some boxes. They wait for the owner's ruling: delete them, rewrite them to
  digests, or keep them to their old 90-day rule. The ruling becomes one statement on `policy = 0`.
- A time-limited, audited debug switch for D3 text (review LLM-040) is not built.
- A cap on `max_tokens` per role (LLM-019) is not built. Not verified on a vLLM server.
