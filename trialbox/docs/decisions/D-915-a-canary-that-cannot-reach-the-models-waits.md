# D-915 A canary that cannot reach the models waits for them; it is not a failure

- **Task:** red of lane G's master run (#639, 2026-11-16, its 04:26 comment). On a real box the canary at orchestrator start met the model servers still loading ("gateway refused judge: upstream_down", 0 of 54 answered) and was recorded as a failure. The gate then stayed shut (tcga BRCA pair level: 0 of 450 excluded, `may_block` false, `note_block_code` "failed") until someone ran a canary by hand, after every reboot. **Date:** 2026-11-16. **Status:** reserved.
- **Decision:**
  - **Unreached.** A model counts as unreached when it answered none of its cases and every call raised a model fault (`LlmModelFault`). That covers the gateway's `upstream_down`, `model_unavailable` and `model_asleep`, and an endpoint that cannot be reached. A failed wake of a model for a model-fault reason counts the same. The report carries `reached` and `unreached` (the roles).
  - **Not a result.** A canary with an unreached model did not run. `preflight` does not record it in the gate or in `selftest.json`, so the last real result stands. It audits `selftest.unreached` (not `selftest.failed`) and returns False, so the night's LLM jobs stay held.
  - **The gate shows it.** The gate keeps `waiting` (when, which roles, why, how many tries). The new code is `waiting`, in `NOTE_BLOCK_CODES` and in en, ja and zh-TW (`screen.judging.why.waiting`; the console's `overview.models.canary.waiting` says it waits for the models and tries again by itself). Doctor and `/metrics` warn rather than show red.
  - **Asked again.**
    - The canary at start retries after `TB_CANARY_RETRY_S` (30 s), doubling up to `TB_CANARY_RETRY_MAX_S` (600 s), until a model answers (`canary_gate.canary_until_reached`).
    - The night gate does not keep an unreached result for the night. It asks again on a tick at least `TB_CANARY_RETRY_S` later, and the night's jobs start once a canary passes.
  - **Still fail-closed.** `waiting` shuts the gate unless a passing pair result younger than `TB_CANARY_MAX_AGE_H` already stands. A model that answers wrongly, or fails for a reason of its own call (a malformed answer, a timeout), is a failure as before. If one model is unreached and the other answered, the canary is still unreached: the pair cannot be scored.
- **Test:** `tests/unit/test_canary_waits_for_models.py`.
