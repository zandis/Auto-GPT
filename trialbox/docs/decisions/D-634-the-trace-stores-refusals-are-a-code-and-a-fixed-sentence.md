# D-634 The trace store's refusals are a code and a fixed sentence

- **Task:** TRACE-ERR (from lane C2's review, through the integrator, 2026-11-13)
- **PR:** this branch (`agent/TRACE-ERR-a-code-and-a-fixed-sentence`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** §8.14 (the trace store: redacted traces, reads with a purpose, every attempt logged)

## Context

The trace store's two refusals answered with the exception's own text: `HTTPException(detail=str(e))`. What an
exception says is whatever the code that raised it put there. Today those are two short sentences of ours, but
the write path takes a whole trace (model input and output) and anything below it that raises a `ValueError`
would have its text sent back to the caller. An answer should not depend on what an exception happens to say.

## Decision

Both refusals answer in the gateway's shape, `{"error": {"code": ..., "message": ...}}`, with a code and a
sentence that are fixed in the service:

- a trace that cannot be stored: 422, `trace_invalid`;
- a read without a user, a purpose or the read role: 403, `trace_read_denied`.

The exception's text is not in the answer. The service's log gets the exception's type and the refusal's code,
not its text. The store's own access log is unchanged: it records every read attempt as before.

## Consequences

- A caller tells the two cases apart by the code, not by matching a sentence.
- No other route of the service builds an answer from an exception.
