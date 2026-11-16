# D-911 ir_extract is asked in parts; a refused call leaves a trace

- **Task:** red of lane G's frozen-commit run (#639, 2026-11-16: `ir_extract` refused by the gateway, `upstream_failed` / compiler HTTP 422, 11 times on long protocols; the refused calls not in the trace store); **Date:** 2026-11-16; **Status:** reserved
- **Decision:**
  - **The limit:** the prompt caps the answer at `max_tokens` (8,192). A criterion's answer, with its concept candidates and synonyms, takes up to about 330 tokens. One call per protocol was cut off past about 25 lines, and the gateway refuses a malformed answer as `upstream_failed`. The prompt also has to fit the model's context; the gateway says that one as `prompt_too_long`.
  - **Now:** the compiler sends the protocol in parts of `lines_per_part()` lines (400 tokens a line within three quarters of the cap: 15 at 8,192). A part ends at a section boundary where it can. A line is never split from the lines under it (`parent`), and parts are contiguous. The answers are joined in order; a short answer names its part.
  - qualify's longest-prompt check cannot carry `ir_extract`: it measures the judge's context and sends through the judge's role, which the gateway refuses for this prompt.
  - **A refused call** leaves a trace (`span: refusal`) with its reason and upstream kinds. Its prompt is kept, marked special-category, only when the call was cleared for a model and failed there (`upstream_failed`, `upstream_down`, `prompt_too_long`).
- **Test:** `tests/unit/test_ir_extract_in_parts.py`.
