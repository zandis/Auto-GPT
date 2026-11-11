# D-369 The mail boundary: no patient file as a password zip, a sign-in link by default, sender checks fail closed

- **Task:** T-212a (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-212a-mail-boundary`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** CR-025 (with PV-11 (a), PV-18, MR-048, R-12) and SEC-11

## Context

Spreadsheets with chart numbers went out as a 7z archive, and the password followed in a second mail to the same
person on the same channel (PPAP). `zip` was the default of the site setting, of `ATTACH_PASSWORD_MODE` and of the
wizard. The safer `link` mode (D-127) mailed a sign-in link, but the console then refused every patient-level
download, so the link led nowhere. Owner decision OD-1 asks to stop PPAP for files with chart numbers and to make
`link` the default once a guarded download exists. This decision takes that recommended answer.

Separately, with `TB_MAIL_AUTHSERV_ID` unset the mail gateway trusted the top-most `Authentication-Results` header
whoever wrote it, and a sender that failed authentication still got a detailed refusal mail (SEC-11).

## Decision

1. **Default `link`.** `settings.attachment_encryption` defaults to `link` (schema), `ATTACH_PASSWORD_MODE` to
   `link` (and now accepts it), `prepare(mode=...)` to `link`, and the wizard asks `link | smime` with `link` first
   and a new question `console_url`, written to `.env` as `TB_CONSOLE_URL`.
2. **No password zip for patient files on a real box.** In `zip` mode a mail with a `phi` tag or a `phi` attachment
   is refused (`EncryptionError`, HTTP 422) before anything is built or sent, and the send key is freed. Only a
   synthetic box may still do it: the mail gateway allows it when `TB_ENV` is DEV or TEST, and the in-process test
   box allows it explicitly, because the tests open that archive. The compose test and POC overlays run the mail
   gateway with `TB_ENV=TEST` for that reason. An aggregate attachment that asks for encryption may still be zipped.
3. **The guarded download.** `GET /pilot/jobs/{id}/files/{name}` gives a `phi` output to a signed-in account only
   when the account's mailbox is one of that output's recipients (the people the job would have mailed), the account
   may read patient data (coordinator or investigator), the study is in its scope and, for an investigator, the
   delegation log allows it. Everyone else gets 404 (or the role refusal of D-146). Each download is audited
   (`console.download`) and written to the flow ledger as `identified`, with the recipient. The job page shows the
   link only to those accounts. The administrator still never reads patient data this way (D-280).
4. **Sender authentication fails closed.** With no authserv-id configured, no `Authentication-Results` header is
   trusted, so every request mail is refused; the service logs an error and `/healthz` says
   `sender_auth: closed`. A request whose sender fails authentication is refused with no reply at all: the From:
   address is not proven, so nothing is sent to it. The refusal is still audited.

## Consequences

- A site that keeps `attachment_encryption: zip` on a real box gets its patient mails refused, by design; it moves
  to `link` (with `TB_CONSOLE_URL`) or `smime`. The wizard warns about `zip` and about `link` without a console URL.
- `deploy/settings.example.yaml` (and its byte-identical platform copy) keeps `zip`: it is the synthetic test
  stacks' settings file and the tests read the archive. `.env.example` now says `link` and sets `TB_CONSOLE_URL`.
- A known sender whose mail fails authentication no longer learns why. The administrator sees the reason in the
  audit trail and the mail thread view.
- `require_spf_dkim: false` still turns the sender check off for a site whose MTA adds no results; it is an
  explicit choice and is not changed here.
- Not in this change: the mail bodies of `phi` mails are still plain text (PV-11 b), and the outbox and
  per-recipient limits are T-108c.
