# RUNBOOK §4 part: the morning mail did not arrive

**Reader:** the box owner.

*T-635 (OPS-074). The morning notices go at 07:00 and 07:30 site time (§2). Users notice first; the administrator
checks in this order. Ticket priority P1 when nobody got it, P3 for one person (§21).*

**Drill (T-213b):** `test_runbook_04_morning_mail_missing` (Docker drill: the mail relay is stopped overnight; the
checks below find it in the order given, and "Send notices now" sends once the relay is back, with no second mail
to anyone who already had one).

| Check | How | If so |
| --- | --- | --- |
| 1. Is the box up? | the console's login page; the Operations page (§15) | if not: §4 table, then §21 |
| 2. Did the console's timers run? | `TB_ENV` is VALIDATION or PRODUCTION, or `TB_CONSOLE_TIMERS=on` (§2); `docker compose logs console --since 12h` names the timer runs | a DEV or TEST box sends no notices on its own: set the variable, `docker compose up -d console` |
| 3. Was a notice sent? | the audit has `notice.sent` for this morning | not sent: go to 4. Sent: go to 5 |
| 4. Did the night's jobs finish? | the Jobs page; `selftest.failed` in the audit (the canary failed, so the model jobs did not run and there is little to tell) | fix the cause (§4 table: "Notes never exclude"); the users get the next morning's mail |
| 5. Did the mail leave the box? | `docker compose --project-directory deploy exec mail-gateway python -m tools.trialbox mail status` (T-108c: every send not yet out, with its last error); `docker compose logs mail-gateway --since 12h` | a refused relay, a password change at the mail server (§5 Secrets), the recipient's daily limit (`TB_MAIL_PER_RECIPIENT_PER_DAY`, default 200). See "The mail outbox" below |
| 6. Did the mail reach the person? | the hospital mail server's log for the box's sender | spam filter, a full mailbox, a changed address on **Users** |
| 7. One person only | their notice settings (`/settings/notices`) | they turned it off, or are not a recipient of the study |

When the cause is fixed: the administrator's **Send notices now** sends the morning's notices. A notice goes at most
once per person and day, so nobody gets two.

## The mail outbox (T-108c, D-401)

A mail that cannot leave never fails its job and never stays half sent. The mail gateway holds it in one of three
states; `mail status` lists them (no mail body is shown) and exits 1 while one waits for a person.

| State | Meaning | What happens |
| --- | --- | --- |
| `queued` | the mail server could not be reached or refused for now (DNS, connect, TLS, a 4xx), or the recipient had 200 mails today | tried again by itself: after 1, 2, 4 … minutes, at most an hour apart, 12 tries (about seven hours); then `failed` |
| `failed` | refused for good (a 5xx: unknown address, sign-in refused) or out of tries | waits for a person |
| `uncertain` | the message may have arrived: the answer after the message was lost, or the gateway stopped mid-send | waits for a person; never sent again by itself |

When the mail server is back, send the queue at once (it does nothing when the queue is empty):
`docker compose --project-directory deploy exec mail-gateway python -m tools.trialbox mail resolve`.
For a `failed` or `uncertain` key, check the recipient's mailbox or the mail server's log for the Message-ID, then
`mail resolve <key> --sent` (it arrived), `--resend` (send it again now) or `--drop` (give up); add `--by <name>`.
Each decision is audited as `mail.resolved`. A refused sender gets at most 10 refusal replies a day; further
refusals are still audited.
