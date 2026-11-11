# RUNBOOK §4 part: the morning mail did not arrive

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
| 5. Did the mail leave the box? | `docker compose logs mail-gateway --since 12h` | a refused relay, a password change at the mail server (§5 Secrets), the rate limit |
| 6. Did the mail reach the person? | the hospital mail server's log for the box's sender | spam filter, a full mailbox, a changed address on **Users** |
| 7. One person only | their notice settings (`/settings/notices`) | they turned it off, or are not a recipient of the study |

When the cause is fixed: the administrator's **Send notices now** sends the morning's notices. A notice goes at most
once per person and day, so nobody gets two.
