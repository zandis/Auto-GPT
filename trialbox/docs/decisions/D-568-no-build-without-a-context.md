# D-568 No local build is routed in PRODUCTION without a known context; the install writes it into the pin

- **Task:** LLM-007 (TB-PLAN-07 v7.2, `docs/plan/33-plan-v7.md`, wave 1, lane D; finding LLM-007 of
  `docs/reviews/2026-11-12-deep-review/06-llm.md`)
- **PR:** this branch (`agent/LLM-007-no-build-without-context`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** T-603 (the gateway refuses a prompt over the build's `context_length`; callers size their reads
  from it), D-409 (the shared-quota profile: `JUDGE_MAX_LEN` and `VERIFIER_MAX_LEN` come from the partition's
  serving record), T-012b (the site pin; `context_length` is a field a site override may set)
- **Read by:** T-114 (the shared-quota qualification), HW-003 and LLM-005 (the vendor record)

## Context

The three shared-quota builds have no `context_length` in the registry: the partition's size is known only when it
is measured. With no context the gateway's size check is off (`over_context` is false for an unknown context) and
the note judge keeps its default budget of 28,000 estimated tokens. On a partition served at 16k the model server
answers 400, the judge counts failures, and over 10 % failures stops the job.

## Decision

1. **`pin_model --install` writes the context into the site pin** for a build whose registry row has none: the
   value the server is started with, `JUDGE_MAX_LEN` for the build on `serving` and `VERIFIER_MAX_LEN` for the
   build on `verifier` (the same variables compose passes to `--max-model-len`). A build already pinned without a
   context gets it added. A value that is not measured yet (unset, empty, or the platform's placeholder
   `unmeasured`) is said in the build's line and the install's result stays the pair's: the platform's pin job
   must not fail before the partition is measured. A value that is set and is not a whole number above zero is a
   mistake in `deploy/.env`: the install's result is not ok. In both cases the weights' pin is kept and rule 3
   holds the build back.
2. **A row that names a context keeps it.** The variables are not read for it: the registry's value is the one the
   pair was measured with, and the gateway's start check already refuses a server whose `max_model_len` is below it.
3. **In PRODUCTION `Registry.resolve` refuses a build served by a local model server (`serving: vllm`) whose
   context is unknown**, with the code `context_unknown`. TEST and DEV route it as before (a qualification run on
   a new partition is how the value gets measured). Stub builds and hosted builds are not touched: the stub has no
   limit to exceed, and a hosted provider's limit is not this box's setting.

## Consequences

- A shared-quota box whose `.env` holds the two lengths gets them into the pin at install; one that does not is
  told at install, and its PRODUCTION gateway refuses the build with a reason that names the fix.
- The front-desk shared-quota build is in no installed pair; it stays unrouted in PRODUCTION until a pin gives it
  a context.
- No new setting: the two variables exist (compose). No limit, no new store.
