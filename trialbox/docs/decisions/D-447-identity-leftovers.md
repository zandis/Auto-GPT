# D-447 Identity leftovers: breached-password list, password history, `doctor` without MFA, WebAuthn through the provider, single-use actor assertions

- **Task:** T-109b (`docs/plan/28-master-plan-v6.md` §6.2, §6.2.9)
- **PR:** this branch (`agent/T-109b-identity-leftovers`)
- **Date:** 2026-11-11
- **Status:** accepted (native WebAuthn for local accounts not built, see Open)
- **Closes:** CR-033 (rest), SEC-17; CR-118 (the "generous AMR set" item; the other Low items are listed under Open);
  D-192 "Open" (breached list, password history, `doctor` without MFA, WebAuthn)
- **Builds on:** D-192 (TOTP, OIDC), D-279 (forced change, lock-out, step-up), D-320 (API second factor), D-391
  (OIDC signing), D-143 (signed actor assertion)

## What was there already (master, 2026-11-11)

- Second factor for local accounts (TOTP, `console/totp.py`, D-192), for the API session route (D-320), at signing
  (D-279 step-up; D-391 a fresh provider sign-in for directory accounts), the forced first change (D-279).
- WebAuthn for directory accounts: Authelia's `webauthn` block in `deploy/identity/authelia/configuration.example.yml`
  with the `two_factor` policy; the console accepts the provider's `amr` (D-192) at sign-in and at signing (D-391).
- The console refused `TB_CONSOLE_MFA=off` outside DEV and TEST, but accepted `TB_OIDC_REQUIRE_MFA=0` everywhere, and
  `doctor` had no check of either.

## Decision

1. **Breached-password list, offline.** `TB_CONSOLE_BREACHED_PASSWORDS_FILE` names a file the operator provides: one
   SHA-1 (or a fixed-length prefix of at least 10 hex digits) per line, optionally `:count`, sorted (the Have I Been
   Pwned "ordered by hash" download is this format). `console/breached.py` binary-searches it on disk, so a 40 GB file
   costs about twenty reads and no memory. A listed password is refused at account creation, reset and change
   (`account.err.breached`). A configured file that cannot be used refuses every new password
   (`account.err.breached_list`, fail closed, logged). Unset: no check. **No list ships**: the useful public one is
   tens of gigabytes and changes, so the operator copies it in; nothing enters the licence register or NOTICE. The
   tests build a synthetic list at run time.
2. **Password history.** `auth` version 5 adds `users.pw_history` (the replaced scrypt hashes, newest first). The
   owner's own change (`/account/password`, `owner=True`) may not be the current password or one of the four before it
   (`account.err.reused`; five in all). A password someone else sets (an administrator's reset, the command line, the
   demo's re-seed) is not held to it, since its owner replaces it at once (D-279); the replaced hash is kept either way.
3. **`doctor` check `console_mfa`.** FAIL in PRODUCTION and VALIDATION (WARN in DEV and TEST) when any way in asks for
   no second factor: `TB_CONSOLE_MFA` other than `totp` (its default outside DEV and TEST), OIDC with
   `TB_OIDC_REQUIRE_MFA=0`, or a trusted identity header (`TB_CONSOLE_SSO_HEADER`). The console now also refuses to
   start with `TB_OIDC_REQUIRE_MFA=0` outside DEV and TEST; a test pins that doctor and the console agree.
4. **WebAuthn is the provider's.** The console does not implement WebAuthn itself: a security key or passkey is
   registered and checked by Authelia, and the console accepts the assurance the ID token reports, at sign-in and at
   signing (D-391). What changed is what counts as two factors (CR-118 "generous AMR set"): `amr` must hold `mfa`, or
   factors of two kinds (known: `pwd`, `pin`, `kba`; held: `otp`, `hwk`, `swk`, `sc`, `sms`, `tel`, `pop`; inherent:
   `fpt`, `face`, `iris`, `retina`, `vbm`, `bio`). One value alone (`swk`, `pop`, `hwk` with only `user`) no longer
   counts. Local accounts keep TOTP.
5. **An actor assertion is used once (SEC-17).** The assertion becomes `v2.<exp>.<session>.<nonce>.<hmac>`: a random
   nonce under the MAC, so two calls in one second carry two assertions. The verifier (`verify_actor`) remembers each
   accepted assertion until it expires (`ReplayGuard`, in process memory) and refuses a second use ("already used";
   the orchestrator answers 403 and audits `actor.refused`). A refused assertion is not used up. `v1` (no nonce) is
   refused. The 120 s life stays. A client retry (`ServiceClient`, after a 5xx or a dropped connection) signs again
   (`resign`), so retries keep their old behaviour. The orchestrator is one uvicorn process; a restart forgets the
   guard, which reopens the window only for assertions issued in the two minutes before it.

## Open

- **Native WebAuthn for local accounts** (registration and assertion in the console, CBOR and COSE parsing,
  attestation policy, a credentials table) is not built: it is a large piece of security code for a path the
  identity overlay already covers; a site that wants security keys uses the hospital account. If the owner wants it
  for local accounts, it is a card of its own (a library such as `webauthn` would change `uv.lock`).
- **The assertion is not bound to the request** (method and path). Single use closes the replay; an assertion caught
  in flight could still be spent on another call before the real one. Binding needs every call site of
  `actor_header` (console `backend.py`, `edc_pages.py`, `tools/role_demo.py`) to pass the method and path.
- CR-118, the other Low items: the first OIDC account sees every study (the same rule as a hospital local account
  without a scope; changing it is a policy question for the owner); `totp.key` in the same backup as the database
  (FG-E / T-117b); Caddy's root key unconstrained, Caddy on `trialbox-net`, HSTS without `includeSubDomains`
  (`deploy/identity/`, not this card's files); docs drift (this card updated RUNBOOK §12 only).
- `tb_common/crypto.load_or_create_key` (used by `console/totp.py`) ignores a key wrapped under the KEK and accepts an
  empty file; not touched here (use `kek.load_key_file`).
- Not verified against a running Authelia: the `amr` values it reports for WebAuthn and passkeys.

## Evidence

`tests/console/test_identity_d447.py` (the breached list with full hashes and prefixes, fail closed; history of
five on the store and on the account page; the three messages in three languages; `doctor` FAILs PRODUCTION without
MFA and agrees with the console; the `amr` table; a replayed assertion refused, a refused one not used up, `v1`
refused, a retry re-signed, the orchestrator's 403); `tests/unit/test_migrations.py` pins `auth` version 5;
`tests/unit/test_trialbox_doctor.py` lists the new check.
