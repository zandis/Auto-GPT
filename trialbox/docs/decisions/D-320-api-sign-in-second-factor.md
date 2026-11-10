# D-320 The API sign-in asks for the second factor; a session belongs to one channel

- **Task:** T-505a (wave P of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.3)
- **PR:** this branch (`agent/T-505a-demo-identity`)
- **Date:** 2026-11-10
- **Status:** accepted
- **Closes:** ROLE-001 (Blocker), CR-033 (the API route part); with D-279: ROLE-006, OPS-003 (lock-out part)

## Context

The deep review found that `POST /api/v1/session` opened a session with a password alone while
`TB_CONSOLE_MFA=totp` was on, and that the bearer token it returned also worked as the `tb_console` cookie, so it
opened `/ops/users` and `/admin` (ROLE-001, `docs/reviews/2026-11-10-deep-review/02b-role-journeys-authz.md`). The
route also cleared the failure count on a right password, which undid the D-192 rule that a known password does not
reset the count of wrong codes. D-279 added `sessions.via`, the forced first change and the per-address lock and
wait; it left this route's second factor and the channel rule to this card.

## Decision

1. **Two factors in one call.** With TOTP on, a local account sends `code` (the authenticator code) with its user
   name and password. The code is checked by `Identity.step_up`, the check the signature already uses: replay guard,
   and a wrong or replayed code is a failed sign-in from that address, so it counts towards the five that lock the
   account from that address. No pending token and no second route: an API client has the code at hand when it signs
   in, and one call keeps the client simple.
2. **Answers.** Password alone: 401 `login.code`, no session. Wrong or replayed code, or a locked address: 401
   `login`. No authenticator yet: 403 `login.enrol`; the authenticator is enrolled on the sign-in page only, with the
   administrator's enrolment code, never over the API. A key file that does not open the secret: 503. A password
   someone else set: 403 `account.must_change` (D-279), checked after the code.
3. **The failure count.** With TOTP on, a right password no longer clears the count; only a right code does, for
   that address. With TOTP off (DEV and TEST, D-192) the route works as before.
4. **One channel per session.** A session opened on this route has `via` `api` (TOTP off) or `api+totp`.
   `UserStore.session(token, api=...)` reads a token only on its own channel: the pages' cookie lookup refuses an API
   token, and the API's bearer lookup refuses a page's cookie token. The other channel's token reads as no session and
   is not ended. `DELETE /api/v1/session` ends API sessions only.
5. **Audit.** Each refusal is `console.login_failed` with `via: api`, `factor: totp` and the reason (`no_code`,
   `wrong`, `replay`, `locked`, `none`, `key`); a success is `console.login` with `via: api+totp`.

## Consequences

- API clients send `code` when TOTP is on. The phone and desktop apps are not built yet; the demo tools run with TOTP
  off and are unchanged. T-505b turns TOTP on for the hosted demo and seeds the tester accounts.
- A password-only probe of the route still tells a right password from a wrong one (401 `login.code` against 401
  `login`), exactly as the page does when it moves on to `/login/totp`. The per-address wait and lock bound it.
- Sessions written before this change have `via` empty or a page value; they stay page sessions.

## Evidence

`tests/console/test_api_identity.py`; `tests/console/test_identity_d279.py` (the signature test now signs in with a
code); the console tests that use bearer tokens pass unchanged.
