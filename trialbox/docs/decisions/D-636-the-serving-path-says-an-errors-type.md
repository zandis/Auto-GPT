# D-636 The serving path says an error's type or its own sentence, never the error's text

- **Task:** SERVING-ERRTEXT (lane C2's list in D-700 for the serving path, through the integrator, 2026-11-13)
- **PR:** this branch (`agent/SERVING-ERRTEXT-the-type-or-a-fixed-sentence`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-700 (across every service, a general error's text is used only in listed places), D-634 (the
  trace store)

## Context

D-700's test reads every service for the text of a general error (`Exception`, `ValueError`, ...) put into an
answer, a record or a report outside a log line, and lists what it found by lane. Four places are in the
serving path: the embed service, the gateway's start check, the model stub and the model guard.

## Decision

Each place says a sentence the service wrote, or the error's type; the text of an error nobody wrote goes to
the log only.

| Place | Was | Now |
| --- | --- | --- |
| `embed_service/embedder.py`, the mode in `TB_EMBED_MODE` | the `ValueError`'s text | the service's own sentence, written where it refuses (the setting's value and the modes it serves) |
| `gateway/app.py`, a model server that does not answer the start check | `"<Type>: <text>"` in the list of unchecked builds | the type; the text in the gateway's log |
| `llm_stub/app.py`, a stub handler that cannot read its messages | the `ValueError`'s text as the answer's detail | a fixed sentence and the type |
| `model_guard/__init__.py`, the guard's own settings at start | a `ValueError` caught as such | the guard's own error class for its three refusals, so its sentences are its own and any other `ValueError` is not printed as one |

In the same card, found by lane A2 by reading: `gateway/core.py` decided "busy", "unavailable" and "down" from
the endings of the error texts it had collected for the attempts. The texts are the gateway's own, so nothing
wrong was decided, but it was a decision read from wording. Each collected error now carries a kind (`busy`,
`open`, `retried`, `other`) beside its text, and the answer is decided from the kinds; the texts are unchanged
in the audit and in the answer.

The four files leave D-700's list of other lanes' places; a test holds them at zero.

## Consequences

- An operator still reads why the embed service or the model guard refused to start: those sentences are the
  services' own. Why a model server did not answer is in the gateway's log, by type in the readiness answer.
