# D-704 A held mail's reason and a missing attachment name the error's type

- **Task:** NEW-TRUST-8 (the mail gateway's three files of D-700's list, placed with this lane by the integrator,
  2026-11-13)
- **PR:** this branch (`agent/NEW-TRUST-8-mail-gateway-error-text`), on top of NEW-TRUST-7
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** D-700 (the list of places across services), D-557 (the text-free log line)

## The problem

The mail gateway kept a general error's text in three reasons of a held message, which the person who decides
the message reads, and answered a missing attachment with the storage key:

- a message whose preparation failed after it had waited in the outbox: `prepare: <the error's text>`;
- a send whose answer was lost: `<Type>: <the error's text>`;
- a failure after the message had left: `after the message left: <Type>: <the error's text>`;
- `attachment not found: <key>` in the answer to the orchestrator.

## The decision

The three reasons keep the error's type (`prepare: OSError`, `TimeoutError`, `after the message left:
ValueError`), and each failure writes the gateway's log line with the type and where it was raised
(`tb_common.http.trace_of`). The missing attachment is answered with a fixed sentence.

The mail gateway joins this lane's exact list in `tests/unit/test_error_text_across_services.py`.

## Kept, with the reason

- **What the mail server answered when it refused a message before anything left** (`_not_sent`: a refused
  recipient, a DNS or TLS failure): the reason holds the error's type and its text. It is the mail server's own
  answer about that message, and it is what the person deciding the held message needs to see (which recipient
  was refused, with what code); the held message's record names its recipients already.
- **The mail tool's own stderr** (`mail_gateway/admin.py`): the gateway's sentence about a held message, to the
  administrator who typed its key.
- **The reply to a sender who may not send**: it names that sender, to that sender (D-700).

## Review

No reviewer was asked: three reasons and one answer made type-only, by the rule a reviewer judged in D-700 and
D-557, held by D-700's exact list.

## Reuse check

`tb_common.http.trace_of`; nothing is added.

## Dropped (D-311)

No sign-off step.
