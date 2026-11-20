# The old shared service token is refused outside DEV and TEST (2026-11-20)

**Reader:** the people who build TrialBox: lane H and the integrator. For builders, so in one language.

Card 9g-13 of plan 9, decision D-1349. New findings in the register's `--add-from` form:
`legacy-token-refused-2026-11-20/findings.json`.

## What was there already

- The v1 actor form is refused everywhere actors are verified (D-447).
- The orchestrator refuses the old shared token outside DEV and TEST, on every route, with an audit event (D-464).
- The gateway refuses it outside DEV and TEST, on every model call and swap, with an audit event (D-437).
- Every other service accepted it, with one warning in the log.

## What changed

| Where | Change |
| --- | --- |
| `libs/tb_common/service_auth.py` (shared library; body of `authorize` and the module text only) | Outside DEV and TEST the old shared token is refused with 403. This covers the registry's `legacy` hash and the one token of a box without a registry. The log gets one warning per process, never the token. The orchestrator, and the gateway on changing methods, get it passed on to their own audited refusal. |
| `tools/trialbox/svc_secrets.py` | `legacy_held(deploy)`: where a box still holds the token (`deploy/.env`, `tokens.json`), names only. |
| `tools/trialbox/doctor.py` | Check `legacy_token`: FAIL outside DEV and TEST, with the places and the fix (`sudo python3 -m tools.trialbox secrets rotate`). |
| `tools/trialbox/update.py` | The preflight refuses a PRODUCTION or VALIDATION compose box that holds it, before anything changes. |
| `deploy/install.sh` | The settings wizard's own token is dropped unless `deploy/.env` held a real one before the install. |
| `tools/trialbox/__main__.py` | `secrets init` and `secrets rotate` no longer say the old token "still works". |

## Does any box still present it?

A box from `install.sh` runs the secrets overlay. There every service reads its own token file and the shared
`TB_SERVICE_TOKEN` is cleared, so no service presents the old token. The test reads the overlay for every service.

One path still made a new box *hold* one. An operator who writes `TB_ENV` into `deploy/.env` before the install
(D-837) made the install count as not fresh. The settings wizard's random `TB_SERVICE_TOKEN` was then kept, and
`secrets init` registered it as `legacy`. Nothing presented it, but doctor would now fail and updates would refuse.
`install.sh` now drops that token. The test runs the installer's own lines, with the real `secrets init`.

`deploy/poc.sh` still writes a shared token. Its boxes are TEST or DEV only, which keep today's rule.

## Not verified

No Docker and no box: compose files were read, not started. A box without a token registry in PRODUCTION
(installed before step 8, never re-installed) now loses every service, not only the orchestrator, until
`secrets rotate` and an install re-run. An update applied by an older release's code does not run the new preflight.
