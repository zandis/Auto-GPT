# 3. Who may call what

- **Service tokens** (D-114, D-138). Each of the nine TrialBox services has its own token
  (`deploy/secrets/services/<service>.token`, 0600) and accepts only the callers in `tb_common/service_auth.py`
  `CALLERS`; a doc-parser token at the orchestrator gets 403. Reads are behind the token too (D-130). Tests:
  `tests/unit/test_service_secrets.py`.
- **The model gateway's caller is the token's service** (D-437, T-212b; register CR-040). `X-TB-Caller` is only a
  claim: the gateway accepts it when the service its `X-TB-Service-Token` names may make it (`service_callers` in
  `models/routing.yaml`: orchestrator as `orchestrator` or `matching`, criteria-compiler, doc-parser and the console
  as `converse-native` under their own names only; the operator's host token as any). So the roles of a caller entry
  are bound to the verified service: a doc-parser token cannot use the judge role, nor claim `orchestrator` (D3
  under `phi_on_box`) or `testbench` (every role). Outside DEV and TEST a call with no service identity (the old
  shared token) is refused. The one-GPU swap (`/v1/serving/activate`, `release`) is for the `serving_control`
  services only (orchestrator, operator). Refusals are `caller_unverified`, audited with the verified service.
  Tests: `tests/unit/test_gateway_verified_caller.py`.
- **The signed-in user between services** (D-143, review S-09). The console signs the user it names
  (`X-TB-Actor-Assertion`: actor, console session, two-minute expiry, HMAC with a key derived from the console's
  token); the orchestrator verifies it with the key in `deploy/secrets/services/actor/keys`, which only the
  orchestrator mounts, before a reveal, a screening-log export, a notice or a cancel. An unsigned name is refused
  and audited (`actor.refused`); the reveal and export caps count per calling service and verified person.
- **People** (`services/console/auth.py`). Five roles; study scope, affiliation and expiry per account; scrypt
  hashes; lockout after 5 failures for 15 minutes with a countdown; CSRF token on every form; a
  Content-Security-Policy that allows no outside script. Hospital SSO through a trusted header from listed proxies
  ([Runbook §1](../RUNBOOK.md#1-install-a-new-site-about-one-day)).
- **Identity** (D-192; `services/console/identity.py`, `totp.py`, `oidc.py`; tests `tests/console/test_identity.py`).
  Local accounts sign in with a password and a TOTP code (RFC 6238: SHA-1, 6 digits, 30 s, one step of drift, a code
  works once). It is the default and can be off only in DEV and TEST (Japan's MHLW guideline v7.0 asks for two
  factors from FY2027). A device is registered only with a one-time enrolment code an administrator issues (24 hours;
  also after a reset), so a password alone never registers one. The TOTP secret is AES-GCM encrypted with a key file
  on the console volume, not in the database. A wrong or replayed code counts as a failed sign-in, and a right
  password does not reset the count; the lock is audited (`console.lockout`). An administrator lifts a lock, issues an
  enrolment code or resets another person's authenticator on `/ops/identity` (audited `console.unlock`,
  `console.enrol_code`, `console.totp_reset`; a reset signs the account out). Sessions end after 10 minutes idle
  (`TB_CONSOLE_IDLE_MINUTES`, 1 to 60; a page's own auto-refresh is not activity) or 8 hours
  (`TB_CONSOLE_SESSION_HOURS`, 1 to 12); session cookies are HttpOnly and SameSite=Strict, and Secure by default in
  PRODUCTION, where an explicit off is refused. The trusted-header SSO runs only with TOTP and OIDC off (DEV, TEST),
  never signs in a local account, and Caddy strips identity headers.
  Optional sign-in with the hospital account through Authelia (OIDC code flow with PKCE, off unless
  `TB_OIDC_ENABLED=1`): the ID token's signature (RS256 or ES256 only), issuer, audience, expiry and nonce are
  checked, a second factor must be reported (`amr`), and the role comes only from `TB_OIDC_GROUP_ROLES`; a person in
  no mapped group or in groups of two roles is refused, a `role` claim is ignored, and a directory account never takes
  over a local account. The role table (`console.auth.User`, `tb_common/authz.py`) and the signed actor assertion are
  unchanged. Not done: WebAuthn in the console itself (Authelia offers it), step-up before a reveal, the
  breached-password list and password history (master plan WS-13.1), and removing the trusted-header SSO.
- **Chart numbers.** The coordinator, the administrator and the study's investigator (owner's decision of
  2026-11-09, D-143, reversing D-133) may reveal one, for a listed patient, with a reason, under a rate limit
  (`TB_REVEAL_MAX_PER_HOUR`, 60); viewer and CRO accounts never see one. Each reveal or view is in the audit. The
  screening-log export with chart numbers is audited at the orchestrator too and capped (`TB_EXPORT_MAX_PER_HOUR`,
  10). Mail never carries a chart number, also not the investigator's N1.
- **Mail commands** need an allowed sender, a passing `Authentication-Results` (DMARC, or SPF/DKIM for the From:
  domain), the command's permission group and the daily rate limit.
