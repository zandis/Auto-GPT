# D-424 PoC mode: the hosted demo signs in without a second factor

- **Task:** PoC mode (owner's request of 2026-11-11; no plan card)
- **PR:** this branch (`agent/poc-mode-no-2fa`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-192 (TOTP for local accounts), D-279, D-320 (T-505a), T-505b (per-tester accounts), T-509 / D-330
  (the PoC host)

## Context

The owner wants the two external testers of the hosted PoC demo to sign in with a password alone. Until now
`TB_CONSOLE_MFA=off` was allowed only in DEV and TEST, and the PoC accounts file turned TOTP on.

## Decision

1. **A marker for the hosted demo.** `TB_DEMO_HOSTED=1` names the hosted PoC demo. `deploy/gcp/hosted-demo-startup.sh`
   writes it into every site's settings; `tools.demo` passes it to the console.
2. **Off only there.** `TB_CONSOLE_MFA=off` is allowed in DEV and TEST, as before, and with `TB_DEMO_HOSTED=1`. It is
   refused in VALIDATION and PRODUCTION even with the marker: the console does not start.
3. **On the record and on the page.** When off on the demo, the console writes one audit event `console.mfa_off`
   (actor `console:start`) at each start, and the sign-in page shows "Second factor is off on this demo box" in en,
   ja and zh-TW.
4. **Off by default on the PoC host; one switch back.** The boot script sets `TB_CONSOLE_MFA` from metadata
   `tb-console-mfa` (default `off`; `totp` or `off` only). Setting it to `totp` and booting again turns TOTP back on;
   each tester then enrols at the next sign-in.

## Note on the plan

`docs/plan/28-master-plan-v6.md` §2 GP-0 asks for "per-tester accounts and a second factor" on the hosted demo (its
D-311 S1 evidence line does not). The owner dropped the second factor for the PoC on 2026-11-11; the plan file is not
edited here.

## Open

- The front door (Cloudflare Access, T-509) and per-tester passwords stay; they are now the only checks before the
  console. ROLE-001's fix (T-505a) is still in force whenever TOTP is on.
