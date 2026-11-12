# 12. Identity and TLS (D-192, D-193)

The console is reached at `https://<TB_TLS_HOSTNAME>` through Caddy on 443; its own port is no longer published.
Local accounts sign in with a password and a TOTP code. The hospital account (AD through Authelia, OIDC) is optional
and off by default. All settings are in `deploy/.env`; the list with comments is
`deploy/identity/identity.env.example`.

**Ask hospital IT on day one** (lead time 2 to 6 weeks): a DNS name for the console (and one for Authelia when the
site uses the hospital account), the firewall rule for 443 from the clinic PCs, and a certificate for those names from
the hospital's CA (the first choice: every hospital PC already trusts it). Only when hospital IT cannot issue one:
permission to install Caddy's root certificate on every staff PC by group policy (a personal device never trusts it). For the hospital account: a read-only AD
bind account, the AD groups to map (below) and LDAPS (636) from the box to a domain controller.

**TLS.**

1. Put `TB_TLS_HOSTNAME` (and `TB_TLS_MODE`) in `deploy/.env`. With the hospital's certificate set
   `TB_TLS_MODE=hospital`, `TB_TLS_CERT_FILE` (certificate and chain, PEM) and `TB_TLS_KEY_FILE` (key, PEM, 0600
   root), then check them with `python -m console.cli check-tls` (in the console container, or on the host with the
   same variables). It fails on a missing file, a key that is not the certificate's, a name the certificate does not
   carry, or a certificate that is not valid today, and warns 30 days before it ends.
2. Add the overlay: append `:deploy/docker-compose.identity.yml` to `COMPOSE_FILE` in `deploy/.env` (after the
   secrets overlay), then `docker compose up -d --wait`.
3. Internal CA only: copy the root certificate out once (`docker compose cp
   caddy:/data/caddy/pki/authorities/local/root.crt deploy/secrets/tls/caddy-root.crt`) and have hospital IT install
   it as a trusted root on the staff PCs (group policy). Never copy anything else out of the `caddy-data` volume: it
   holds the CA's private keys.
4. Open `https://<TB_TLS_HOSTNAME>/login` from a clinic PC: no certificate warning.

**Local accounts (TOTP, the default).** `TB_CONSOLE_MFA=totp` is the default and can be turned off only in DEV and
TEST. An account sets up its authenticator only with a one-time **enrolment code** from an administrator (valid 24
hours, works once): after the password the console shows a key, the person adds it to an authenticator app (or a
hospital device) and types the enrolment code and the app's code. Without a valid enrolment code an account with no
authenticator cannot sign in at all, so knowing a password is never enough to register a device. Every later sign-in
asks for the current code; a code works once. A wrong or reused code, or a wrong enrolment code, counts as a failed
sign-in: five failures in 15 minutes lock the account for 15 minutes, and the lock is in the audit trail
(`console.lockout`).

- **After the upgrade, and for every new account**: **Sign-in and recovery** (`/ops/identity`) lists the accounts
  without an authenticator at the top. For each, check who it is and choose **Enrolment code**; hand the code over in
  person or read it out on a call back to the extension in the staff directory. The code is shown once and never
  written to a log or the audit (`console.enrol_code` records who issued one for whom).
- **The first administrator** (no other administrator can issue a code): on the box,
  `python -m console.cli enrol-code admin` in the console container prints the code. This shell step is the
  supervised path; record it in the install checklist.
- **Lost phone**: on the same page choose **Reset authenticator** for that person, after the same identity check. The
  account is signed out everywhere and the page shows the enrolment code for the new device. An administrator's own
  authenticator is reset by another administrator, or with `console.cli reset-totp NAME` (prints the code).
- **Locked out**: wait 15 minutes, or an administrator chooses **Unlock** on the same page (`console.cli unlock
  NAME`). All actions are audited (`console.totp_reset`, `console.enrol_code`, `console.unlock`;
  `console.totp_enrolled` says whether it was a first device or one after a reset).
- **Sessions** end after `TB_CONSOLE_IDLE_MINUTES` without activity (default 10; set the hospital's policy for shared
  clinic PCs, at most 60) and after `TB_CONSOLE_SESSION_HOURS` in all (default 8). A page that refreshes itself (a
  running job) does not count as activity. Cookies are Secure, HttpOnly and SameSite=Strict; an explicit
  `TB_CONSOLE_SECURE_COOKIE=0` is refused in PRODUCTION.
- The trusted-header SSO (`TB_CONSOLE_SSO_HEADER`, D-93) runs only with TOTP off (DEV, TEST) and OIDC off, never signs
  in a local account, and Caddy strips identity headers from every request: a hospital uses the OIDC sign-in below.
- **Passwords** (D-447): at least 12 characters, not one of the account's last five, and not on the box's
  breached-password list. The list is a file the operator provides, because the box has no network: download the
  Have I Been Pwned "Pwned Passwords" SHA-1 file ordered by hash (CC BY 4.0; tens of GB) or another sorted list of
  SHA-1 hashes where the network is, copy it to the box (for example `deploy/secrets/breached/pwned-sha1.txt`, mounted
  read-only into the console) and set `TB_CONSOLE_BREACHED_PASSWORDS_FILE` to its path in the container. Lines are
  `HASH` or `HASH:count`, sorted; a shorter file of hash prefixes (every line the same length, at least 10 hex
  digits) also works. The file is searched in place, never loaded. A configured file that cannot be read refuses
  every new password (the console log says why) until it is fixed. Without the setting nothing is checked: record
  the choice in the install checklist. TrialBox ships no list.
- **`trialbox doctor`** fails in PRODUCTION and VALIDATION (check `console_mfa`) when a way into the console asks for
  no second factor: `TB_CONSOLE_MFA` other than `totp`, OIDC with `TB_OIDC_REQUIRE_MFA=0` (the console refuses it
  too), or a trusted identity header (`TB_CONSOLE_SSO_HEADER`).
- The TOTP secrets are stored encrypted, with the key `totp.key` on the `console-data` volume, not in the database.
  Back up both; with the database but without the key, every person sets up a new authenticator (an administrator
  resets them all).

**Hospital account (OIDC through Authelia, optional).**

1. Copy `deploy/identity/authelia/configuration.example.yml` to `deploy/site/authelia/configuration.yml` and fill in
   the values marked `SITE` (domain controller, base DN, bind account, the two host names).
2. Make the secrets in `deploy/secrets/authelia/` (0600, root): `jwt_secret`, `session_secret`, `storage_key`,
   `oidc_hmac` (each 64 random characters), `ldap_password` (the bind account's), `oidc_jwks.pem` (an RSA 2048 key,
   `openssl genrsa -out oidc_jwks.pem 2048`) and `oidc_client_secret.txt` (the client secret; its digest goes into
   the configuration, as the comment at its top says).
3. In `deploy/.env`: `TB_OIDC_ENABLED=1`, `TB_AUTH_HOSTNAME`, `TB_OIDC_ISSUER=https://<TB_AUTH_HOSTNAME>`,
   `TB_OIDC_CLIENT_SECRET`, `TB_OIDC_LOGOUT_URL=https://<TB_AUTH_HOSTNAME>/logout`, `TB_OIDC_CA` (the internal root
   from TLS step 3, or the hospital's CA chain) and `TB_OIDC_GROUP_ROLES`, for example
   `TB-Coordinators:coordinator,TB-Investigators:investigator,TB-Monitors:cro,TB-Admins:admin`.
4. Open LDAPS for Authelia only: add `authelia=<domain controller>:636` to `EGRESS_EXTRA` and run
   `deploy/network.sh apply` ([Security §2](../SECURITY.md#2-network)).
5. `docker compose --profile oidc up -d --wait`. The sign-in page shows **Sign in with the hospital account**.

Only the groups in `TB_OIDC_GROUP_ROLES` give a role. A person in no mapped group, or in groups that map to two
different roles, is refused, and the refusal is audited (`console.login_failed`, `via: oidc`); a `role` claim or any
other group is ignored. The role is read again at every sign-in, so removing someone from a group takes effect at
their next sign-in. Authelia asks for the second factor (TOTP or a security key, WebAuthn), and the console refuses a
sign-in the provider did not report as two-factor: `amr` must say `mfa` or name two kinds of factor (for example
`pwd` and `hwk`); one value alone, such as `swk` or `hwk` without user verification, is not enough (D-447). WebAuthn
is offered through Authelia only: a person who wants a security key signs in with the hospital account; local
accounts use TOTP. A hospital account never takes over a local account of the same name.
Sign-out also signs out of Authelia. Add the `authelia-data` volume to the backup (the authenticators registered by
directory users). Authelia's OIDC provider is certified but still called beta by its makers (D-192).

The overlay is checked in CI (`.github/workflows/trialbox-identity.yml`: `caddy validate` in both TLS modes,
`docker compose config` of the merged files, and Caddy run in front of a stand-in console: HSTS on 443, identity
headers stripped, 80 and 8090 closed, no query strings in its log). The whole stack with Authelia has not been started
on a box yet. Run the four TLS steps and one sign-in of each kind at IQ.
