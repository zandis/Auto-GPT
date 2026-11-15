# D-880 the judge's server renders message content as strings

- **Task:** CONTENT-FORMAT, the answer to G-1's token half (#639, #649; the integrator's yes of 2026-11-15)
- **PR:** this branch (`agent/CONTENT-FORMAT-the-server-renders-strings`)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-567 (the pinned chat template), D-392 (DEP-007)

## Decision

1. Every server started with the pinned `--chat-template` (the judge, which also answers the front desk: the
   rtxpro6000, gb10, rtx5090 and shared-quota overlays and the platform's gpu pair) gets
   `--chat-template-content-format=string`. vLLM 0.32 detected the Gemma 4 template as taking list parts and wrapped
   each string; the template's list branch for the system turn writes `item['text'] | trim + ' '`, one space before
   `<turn|>` that its string branch does not, so the server's ids had one token more on every system prompt.
2. The serving record reads the flag into `chat_template_content_format`; `template_problems` requires `string`. A
   record measured before this names no format and is measured again with the pair's canary.

## Test

`tests/unit/test_chat_template_content_format.py`: before, 3 failed; after, 3 passed.
