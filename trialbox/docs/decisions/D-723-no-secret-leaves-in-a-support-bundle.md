# D-723 No secret of the box leaves in a support bundle

- **Task:** SUPPORT-SECRETS (OPS-002 of the deep review of 2026-11-12; lane G's review of 2026-11-13; the owner's
  order through the integrator, 2026-11-13). Takes over PR #324 (another session's branch, which this lane does not
  push to): its one commit is on this branch, with credit (`git cherry-pick -x`).
- **PR:** this branch (`agent/SUPPORT-SECRETS-no-secret-leaves-in-the-bundle`)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** D-405 (the support bundle), D-406

## Context

`tools/support_bundle.py` redacted a secret by the NAME that stood next to it (`KEY=value`, `key: value`) and the
user:password of a URL. Its name list knew `PASSWORD` and `PASSWD` only: `SMTP_PASS`, `IMAP_PASS`, every
`TB_DB_PW_*` and `TB_KEK_PASSPHRASE` left the box in `env.redacted` and in `docker compose config`. #324 widened the
list. A list of names is never complete, and a value can turn up where no secret name stands next to it: a command's
output, a JSON detail, a log line, a percent-encoded URL.

## Decision

1. **The name rule** is #324's: `PASS` and `_PW` join the secret-like names (`PASSPHRASE` with them).
2. **The values are what is looked for.** `secret_values`: every setting of `deploy/.env` and of the process
   environment (a passphrase typed in front of the command) whose name is secret-like and is not a path or a
   mode. Before the manifest is written, every file of the bundle has every form of each value (as text, and both
   percent-encodings a URL uses) replaced by `[redacted]`, whatever stood next to it; the count is in the manifest
   (`secrets_hidden`) and in the closing line.
3. **The last look is on the finished archive.** It is read back and any value still in it, in any of those forms,
   stops the bundle: nothing is written, and the refusal names the settings, never a value.
4. A value shorter than 4 characters is not looked for by value (it would be replaced inside ordinary words); it
   is still redacted by its name. Every secret the box makes is far longer.

## Test

`tests/unit/test_support_bundle_no_secret.py`: a box with every secret setting of the tree set to its own value
(one that a URL must encode among them; one only in the process environment; one quoted under a name the rule
does not know), every command printing every value in six forms, and a service log that logged one. No value is in
the archive in any form. A guard lists every secret-like setting of `.env.example`, the settings table, the
installer and the compose files: a new one fails the test until it is in the list. With the value pass taken out,
the bundle is refused. The manifest's checksums are of the files as they leave.

## Not covered

- A secret the box holds only in a FILE (`deploy/secrets/`, the secrets volume) and that is not also a setting:
  its value is not read here (the bundle never reads those files, and refuses them as members). If a service
  logged one, the name rule and the log scrubber are what stand in the way.
- A value in another encoding (base64 in a header, a JSON escape of a quote inside the value). The forms are text
  and the URL encodings.
