**D-279 Only the owner knows a password that signs; failed sign-ins lock per account and address; a directory session
asks the directory again within the hour; with TOTP on, a signature needs a fresh code.** Fix group D-279 (FG-J) of
the critical-issues register (`docs/reviews/2026-11-10-critical-issues-register.md` §4.1 P-1, P-2, P-7 and §7):
CR-034, CR-033 (rest), CR-116, CR-117, SEC-9; deep-review findings ROLE-004 (forced change), ROLE-006, OPS-003
(lock-out part), ROLE-001 (the parts in this group) and REG-025 (the text part). Plan TB-PLAN-06 §6.2.1. Branch
`claude/tb-fix-identity`. Date: 2026-11-10.

*The problem.* An administrator's new account and an administrator's reset showed a password that the owner was never
made to replace, and that password was the only component of the electronic signature (SEC-1, CR-034). Five wrong
passwords from anywhere locked a named account for 15 minutes, so anyone who could reach the console could keep the
administrator or a demo tester out; there was no per-address throttle and failure rows were never deleted (SEC-9,
CR-116, ROLE-006, OPS-003). An OIDC session lived the full 8 hours after the person left the directory (CR-117).

*Forced first change (P-1).* `users.must_change` (auth schema version 3) is set by `UserStore.create(...,
must_change=True)` and `set_password(..., must_change=True)`; the callers that hand a password to someone else pass
it: `/ops/users` add and reset, `console.cli add-user` and `reset-password`, `bootstrap-admin` when it prints the
password, and the first administrator from `TB_CONSOLE_ADMIN_PASSWORD_FILE`. The owner's change on
`/account/password` (current password typed again, the new one different from it) clears it. While it is set: the
sign-in (password or password and TOTP) lands on `/account`; every other page redirects there (GET) or is refused
with 403 `account.must_change` (any other method, and every `/api/v1` call); `POST /api/v1/session` gives no token.
Only `/account`, `/account/password`, `/logout` and `/lang` stay open. The store keyword defaults to False so the
demo tools and fixtures that seed accounts keep working; the per-tester demo accounts (T-505b) decide their own.
A directory account (header SSO or OIDC) has no console password: `set_password` now refuses it, so nobody can give a
directory user a second, local identity (REG-025).

*Per-address lock-out (P-7).* `login_failures.source` holds the address (IPv4 as is; IPv6 by its /64; an IPv4-mapped
IPv6 as IPv4). Five failures in 15 minutes lock the account *from that address only*. After 10 failures in 15 minutes
across all names, an address waits before each try, doubling from 1 second to at most 60 seconds (429 with
`Retry-After` on the page and the API): slowed, never locked, so a hospital behind one NAT address keeps working. A
try while the account is locked from that address is recorded under the address only, so it slows the address and
never counts against the account. 50 failures on one account from all addresses together lock it everywhere (the
backstop against distributed guessing). Rows older than the window are deleted as new ones arrive. A right sign-in
clears that address's count only. `console.lockout` names the address; `unlock` (page and CLI, audited) clears every
address. The address is `request.client.host`, which behind Caddy is the browser's only when uvicorn trusts the
proxy (`TB_CONSOLE_FORWARDED_ALLOW_IPS`, set in `deploy/docker-compose.yml`); otherwise every try shares the proxy's
address and the per-address wait applies to the whole site.

*OIDC session lifetime (CR-117).* Sessions record how they were opened (`sessions.via`: `password`, `password+totp`,
`oidc`, `sso`, `api`). An `oidc` session ends after `TB_OIDC_SESSION_MINUTES` (default 60, 5 to 480), whatever the
idle and absolute limits; the next sign-in goes through the provider, which refuses a person removed from the
directory and re-reads the groups. A refresh-token check against the provider was not chosen: it adds a network call
per request or a background job for a gap this closes to an hour.

*Second factor at signing (P-2).* With `TB_CONSOLE_MFA=totp`, `POST .../edc/sign` (page and API) needs the password
and a fresh code (`otp`) from the signer's authenticator, checked by `Identity.step_up`: replay guard, a wrong or
replayed code is a failed sign-in from that address and is audited as `console.edc_reauth_failed` with the reason. An
account with a password someone else set cannot sign (409). With TOTP off (DEV and TEST only, D-192) the password
stays the one component.

*Not in this group.* The second factor on `POST /api/v1/session` and refusing an API token as a cookie are T-505a
(ROLE-001; `sessions.via` is there for it). The signature row still records the method `password` because
`services/edc/*` belongs to FG D-281 and T-205; directory accounts still cannot sign (T-205, REG-025, with a fresh OIDC
re-authentication). Breached-password list, password history, WebAuthn, `doctor` without MFA: T-109b.

*Evidence.* `tests/console/test_identity_d279.py`; the existing lock-out tests in `tests/console/test_identity.py` and
`tests/console/test_console_app.py` pass unchanged; `tests/unit/test_migrations.py` pins the new auth version.
