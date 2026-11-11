# D-357 Prompt budgets come from the model's context

- **Task:** T-603 (wave 2A of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2)
- **PR:** this branch (`agent/T-603-context-budgets`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** deep review LLM-015, LLM-016, LLM-017, LLM-018, LLM-005 (the cut half), CR-004 (the flag half).
  Builds on D-276 and D-333 (T-601), which it does not change.

## Context

The registry records each build's context (32,768 tokens on the RTX PRO 6000, 16,384 on the Spark, 8,192 on the
RTX 5090), but no code read it. The callers used constants: 2,500 tokens of note excerpts, 28,000 tokens for the
full-record read, 60,000 characters for an uploaded chart. The full record could not fit on the Spark or the 5090,
and a long Japanese or Chinese chart fit no profile. The server then answered HTTP 400. The truncation retry asked
for up to 16,384 answer tokens, again over the context on the smaller profiles. The response cache kept an answer
cut off for length, and its key had no `max_tokens`, so the retry got the same cut-off answer from the cache. And a
note that did not fit the excerpt budget was left out with no sign on the candidate.

## Decision

1. **One estimate, everywhere.** `libs/tb_llm/budget.py`: a CJK character (and full-width forms, Hangul) is one
   token, other text four characters per token, rounded up, plus 8 tokens per message. It is not the models'
   tokenizer. Callers plan with 85 % of the context (`SAFETY`) so a tokenizer that counts more still fits.
2. **The gateway says the context and enforces it.** `GET /v1/models` gives each alias's `context_length` (and
   `max_model_len`, as vLLM names it): the context of the builds the alias can route to on this box, the smallest
   if several could. A request whose estimate plus `max_tokens` is over the context of the build that would take it
   is refused `prompt_too_long` (HTTP 413) before dispatch, with no other build tried.
3. **Callers size from it.** `tb_common.llm.LlmClient.text_budget(prompt, fixed)` is what the variable part of a
   prompt may hold. The note judge cuts its excerpts and its full record to the smaller budget of the judge and the
   verifier (both read the same excerpts). A chart longer than one prompt is read in parts, each part sized from
   the context. `max_tokens` is cut to what fits beside the prompt; a prompt that leaves less than 256 tokens is not
   sent (`LlmPromptTooLong`). Where the context cannot be told, the old constants stay and the gateway still checks.
4. **The retry fits.** The one retry of an answer cut off for length asks for four times the budget, at most
   16,384, and at most what the answering alias's context leaves beside the prompt; when nothing larger fits it is
   not sent.
5. **The cache keeps complete answers only.** `max_tokens` is part of the key. An answer whose `finish_reason` is not
   `stop`, or whose content is outside its schema, is not cached.
6. **A note over the budget is flagged, not skipped.** A note that does not fit is counted (the next older one may
   still fit). An answer that would exclude stays `unknown` (D-276); an answer that keeps the patient stands with
   the reason `notes_over_budget`, and the candidate goes to review (v1: tier `review`; cascade:
   `PatientTrace.notes_over_budget`, never `strong`). A prompt the server still finds too long gives the same
   reason and counts as a model failure, so a box whose sizing is wrong stops the run (`check_judge`).

## Consequences

- The full-record read and long charts work on every profile; `qualify`'s `longest_prompt` step now measures the
  prompt each caller actually sends on the profile.
- A new reason code `notes_over_budget` with its words in English, Japanese and Traditional Chinese.
- The stub can enforce a context (`TB_STUB_CONTEXT`, or the `stub-ctx-8k` / `-16k` / `-32k` personas), so tests show
  the sized prompts are accepted by a server that enforces the limit.

## Not done

- The verifier does not get its own excerpt selection (LLM-005's second half, FG D-276); this card closes the cut.
- The concurrency cap of the long roles (LLM-024) is a serving setting in the compose files, not here.
