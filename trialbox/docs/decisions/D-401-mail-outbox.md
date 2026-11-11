# D-401 The mail outbox: no send key stays in `sending`, an outage never fails a job, `trialbox mail resolve`

- **Task:** T-108c (wave 1 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.4)
- **PR:** this branch (`agent/T-108c-mail-outbox`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** CR-085 (MR-075, R-16); the mail half of D-146's open item "the mail gateway still limits mail per
  sender (all commands, 20 a day)"

## Context

D-127 wrote a send key as `sending` before the SMTP call and `sent` after it, and freed it only for a few SMTP
refusals. A DNS failure, a connect timeout or a TLS error raised something else, so the key stayed in `sending`
forever: every later try of the same mail was refused as "may have arrived", the job failed on its mail step, and
there was no command to settle it. The orchestrator's outbox dispatcher is not wired into any service.

## Decision

1. **The send keys are the mail gateway's outbox.** A key leaves `sending` in the same call: `sent`; `queued` when
   nothing can have left (DNS, connect, TLS, greeting, sign-in, MAIL, RCPT, DATA refused, a 4xx answer to the body);
   `failed` for a 5xx or after 12 tries; `uncertain` when the message may have arrived (the body was on the wire and
   the answer was lost, or a step after the message left failed). The SMTP transport sends MAIL, RCPT and DATA itself
   so that it knows the phase, and raises `NotSent` for everything before the body.
2. **A stale `sending` key becomes `uncertain`.** A key in `sending` for 15 minutes belongs to a process that died;
   the dispatcher marks it on each pass. A send that was only slow and then ends overwrites the mark.
3. **An outage never fails a job.** `/send` answers 202 with `X-TB-Mail-State` (`queued`, `failed`, `uncertain`)
   and the Message-ID the mail will carry; the orchestrator records it and the job stays done. The event is
   `mail.deferred`, `mail.failed` or `mail.uncertain`. A repeat of a held key sends nothing and answers the same.
   A repeat of a key that is in flight right now is still 409 (D-127).
4. **The dispatcher.** A thread of the mail gateway, every `TB_MAIL_POLL_SECONDS`, tries due `queued` keys again
   with back-off (1, 2, 4 … minutes, at most an hour). The request is kept (attachments by object-store key) only
   while the mail may still be sent; it is cleared when the key is sent or dropped. `uncertain` and `failed` are
   never sent by themselves.
5. **`trialbox mail status` and `trialbox mail resolve`** (in the mail-gateway container). `resolve` with no key sends
   the queue now (after the MTA is back; a no-op on an empty queue); `resolve KEY --sent|--resend|--drop` is a
   person's decision, audited as `mail.resolved`. `status` exits 1 while a key waits for a person.
6. **Limits.** At most `TB_MAIL_PER_RECIPIENT_PER_DAY` (default 200; 0 = none) mails to one address in 24 hours;
   one more waits in the queue an hour without using a try. A refused sender gets at most 10 refusal replies in 24
   hours (a mail loop stops; each refusal is still audited). The mail intake now counts each heavy job type on its
   own, with `tb_common.authz.daily_limit`, as the console does since D-146 (J-02); STATUS, APPROVE and the other
   light commands are not counted.

## Consequences

- A user may get a job's mail hours late after an outage instead of a failed job; `mail status` and the audit show
  why. The orchestrator's own outbox (`orchestrator.outbox`) stays unwired; this one is the mail gateway's.
- The mail store has schema version 3 (columns on `send_keys` and `intake`; no new table).
- Not in this change: the console has no page for the held keys (the Operations page could read `/healthz`, which
  now reports the counts), and the orchestrator does not show "mail deferred" on the job page.
