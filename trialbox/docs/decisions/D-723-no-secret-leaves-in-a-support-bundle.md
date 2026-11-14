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
2. **The values are what is looked for.** `secret_values`: the secret settings of `deploy/.env` and of the
   process environment (a passphrase typed in front of the command), and the values in the files of the secrets
   folders (`deploy/secrets/`, `TB_SECRETS_HOST_DIR`: tokens, key hex, `.env` lines; public `*.pub`, `*.crt`,
   `*.pem` are not read; files above 64 KB are not read; none of them ever goes in a bundle). A secret setting is
   one of `SECRET_SETTINGS` (every one the tree has; a test fails on a new secret-like setting that is in neither
   it nor `NOT_SECRETS`), or a site's own setting whose name says it holds a secret's value. Before the manifest
   is written, every file of the bundle has every form of each value replaced by `[redacted]`: as text, both
   percent-encodings a URL uses, and as JSON writes it. The count is in the manifest (`secrets_hidden`) and in the
   closing line.
3. **A value is read as compose reads it**, and as it is written: an unquoted value ends before ` #`; a quoted one
   is what is between its quotes, with `\"` and `\\` unescaped. Both forms are looked for.
4. **A setting whose name only looks secret-like keeps its value** (found by the review: `TB_CONSOLE_SECURE_COOKIE`,
   the mail authserv-id, `TB_MEM_AUTHELIA`, `TB_AUTH_HOSTNAME`, the GPU profile's name had their values replaced
   in every file, which broke the JSON files and hid what support needs). Their line in `env.redacted` is still
   redacted by the name rule. True and false, yes and no, 0 and 1 are never looked for.
5. **The last look is on the finished archive.** It is read back and any value still in it, in any of those
   forms, stops the bundle: nothing is written, and the refusal names the settings (or "a secret file" and its
   name), never a value.
6. A value shorter than 4 characters is not looked for by value (it would be replaced inside ordinary words); it
   is still redacted by its name. Every secret the box makes is far longer.

## Test

`tests/unit/test_support_bundle_no_secret.py`: a box with every secret setting of the tree set to its own value
(one that a URL must encode among them; one only in the process environment; one quoted under a name the rule
does not know), every command printing every value in six forms, and a service log that logged one. No value is in
the archive in any form. A guard lists every secret-like setting of `.env.example`, the settings table, the
installer and the compose files: a new one fails the test until it is in the list. With the value pass taken out,
the bundle is refused. The manifest's checksums are of the files as they leave.

## Not covered

- Other encodings: base64 (a Basic auth header), a value in upper case, a value split by a line wrap, a URL that
  encodes some characters and not others. The forms are text, the URL encodings and JSON.
- A secret value that contains `[redacted]` (or is `redacted`): the bundle is refused every time, since the
  replacement holds the value. The refusal says which setting.
- `TB_BACKUP_TARGETS` (a list of folders) holding a URL with a password: its userinfo is redacted where a line
  is, not by value. It holds folders on a box.

## After train 15 (2026-11-14)

The CI runner has Docker, so the audit volume's default folder (`/var/lib/docker/volumes/trialbox_audit-data/_data`)
exists there and cannot be read by the runner's user. Four tests that did not set `TB_AUDIT_HOST_DIR` crashed the
bundle with `PermissionError` in `_audit_part`, and an operator who is not root would hit the same crash on a box.
`_audit_part` now writes `audit-verify.json` with "the audit folder could not be read (EACCES): run the bundle as
root to verify the chain" and the bundle is written. The tests give the box its own audit folder.
