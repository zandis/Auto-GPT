# D-981 A part the gateway gave up on is asked in halves; parts are sized by time

- **Task:** G4 of the integrator's second review of the P1b run (#639, 2026-11-16). Four protocols (NCT00974064, NCT01181232, NCT01745731, NCT02378311) failed at ir_extract with "gateway refused ir_extract: upstream_failed".
  - A part of 12 to 15 lines could not be written within the gateway's 180 s read timeout (`TB_GATEWAY_UPSTREAM_READ_S`).
  - The refusal was never retried.

  **Date:** 2026-11-16. **Status:** reserved.
- **Decision**
  - **A new type, `LlmUpstreamFailed` (a subclass of `LlmError`, so every existing handler still catches it).** `tb_common.llm` raises it for the gateway's `upstream_failed` and for the endpoint's own read timeout. A shorter request may get an answer; the same one will not. It is never a model that is down (`LlmModelFault`).
  - **A part refused with it is asked again as two halves** (`Compiler._ask_in_halves`), at most two levels deep. The halves are cut where `extraction_parts` would cut. The decision is by type, never by the error's text (D-651, D-700).
    - Any other failure, or a single line, fails as before.
  - **A part is also sized by time.** `lines_per_part` takes the smaller of the answer cap (D-911) and the lines the model can write within the read timeout: `read_s × TB_EXTRACT_TOKENS_PER_S × 0.6 / 400`.
    - The rate's default of 40 tokens per second is a guess, kept low on purpose. It needs measuring on the box's GPU.
    - With it, a part holds 10 lines instead of 15.
- **Test:** `tests/unit/test_extract_slow_part_in_halves.py`.
