# D-410 Acceptance environment: the identity overlay against a test directory, a real-shaped mail server and a test CA

- **Task:** T-213a (first part of T-213; `docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-213a-acceptance-env`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-83 (`tools/acceptance.py` is the site go-live acceptance), D-192 and D-193 (Authelia and Caddy),
  D-311 (no development gates), D-348 (images pinned by digest in `deploy/images.lock`), D-360 (limits and watchdog)
- **Closes:** CR-071 (first half: the environment), OPS-051 (run half: the means to run the directory sign-in on a box)

## Context

The stack with Authelia has never started on a box (RUNBOOK §12, OPS-051). A hospital gives the box a directory over
LDAPS, a mail server and a certificate; the acceptance box (the owner's B200 or the rental workstation) has none of
them. T-213 asked for those mirrors as a compose file and the drills as code; plan v6 split it: T-213a the
environment, T-213b the drills. `tools/acceptance.py` already exists (D-83), so the tool is `tools/acceptance_env.py`.

## Decision

1. **One overlay, after the identity overlay.** `deploy/docker-compose.acceptance.yml` adds the mirrors to the box's
   own stack (base, secrets, the GPU overlay or the stub model, identity): no service of the product is changed
   except where a hospital value goes (Authelia's configuration, secrets and trusted CA; the mail gateway's mailbox).
   It publishes no port; only Caddy's 443.
2. **The test directory is LLDAP** (`lldap/lldap:v0.6.3-alpine-rootless`, digest-pinned in `deploy/images.lock`):
   a small LDAP server with LDAPS and a seed script in the image, so the accounts are files and the run needs no
   Windows server. Authelia runs with `implementation: lldap` there; at a site it is `activedirectory`. The image is
   used by this overlay only: no bundle carries it (the bundle and the image gates read the base and test files).
3. **The mail server is GreenMail** (the image already pinned for tests) with sign-in required and TLS only (IMAPS
   993, SMTPS 465), its keystore issued by the test CA; the mail gateway trusts that CA through `TB_EXTRA_CA`.
4. **TLS is the hospital mode** (`TB_TLS_MODE=hospital`): a test CA issues the certificate for the console and the
   Authelia host, the directory's and the mail server's. The CA key is never written to disk.
5. **The Authelia configuration is the site template** with every SITE value replaced (the tool refuses a template
   whose SITE lines moved, and a result with a SITE value left), plus `certificates_directory` for the test CA and
   the client secret's PBKDF2-SHA512 digest. The console alone holds the plain client secret.
6. **The accounts are synthetic**: one per role of `TB_OIDC_GROUP_ROLES`, one in no mapped group and one in two
   (both must be refused), and a read-only bind account (`lldap_strict_readonly`). Passwords are files, 0600.
7. **The tool** (`python -m tools.acceptance_env plan | prepare | up | check | down`) writes every file under
   `deploy/site/acceptance` (not in git), 0600 for secrets and owned by the container user that reads each one when
   run as root; prints no secret; `--dry-run` prints the docker commands only. `check` reads compose's state (each
   service healthy, each one-shot exited 0) and makes two HTTPS requests through Caddy verified against the test CA
   (the console answers; Authelia's OpenID configuration names the acceptance issuer) and writes `record.json`.

## Not in this decision

- The start on the box itself, the sign-in of each kind and the record: on the owner's B200 or the rental box.
- REDCap: no public image may be shipped; the drills of T-213b use the site's or a licensed test instance.
- A sign-in against Active Directory proper (Windows or Samba AD): at the site, at IQ (RUNBOOK §12).
- The drills, the soak and the nightly runs: T-213b.
