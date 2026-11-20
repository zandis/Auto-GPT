# D-1349 The old shared service token is refused outside DEV and TEST (9g-13)

- **Task:** lane H, card 9g-13 of plan 9 (`docs/plan/45-plan-9-2026-11-17.md`; review 01 B1-P4, review 10 row 1:
  "refuse the v1 actor header and the legacy shared token in PRODUCTION"). · **Date:** 2026-11-20
- **What was there already:** the v1 actor form is refused (D-447: `verify_actor` takes only `v2`; `v3` is D-483).
  The old shared token (one `TB_SERVICE_TOKEN` for the box) names no service. The orchestrator's route gate
  refuses it outside DEV and TEST on every route, with the audit event `service.route_refused` (D-464). The
  gateway refuses it outside DEV and TEST on every model call and swap, with its own audit event (D-437). Every
  other service accepted it, with one warning in the log: the registry's `legacy` hash from any caller, past
  `CALLERS`, and the one token of a box without a registry.
- **Decision:**
  - `tb_common.service_auth.authorize` (body only; no signature changed) refuses the old shared token, in both forms,
    where `TB_ENV` is not DEV or TEST: PRODUCTION, VALIDATION, and an unset or unknown `TB_ENV` (PRODUCTION by
    D-127). The answer is 403 `the old shared X-TB-Service-Token is refused outside DEV and TEST (D-1349)`. The
    log gets one warning per process that names the fix (`secrets rotate`). Neither carries the token. The access
    log still has one line per refused request.
  - **Mirrored from the v1 refusal (D-447):** where it applies, and its form. D-447 refuses `v1` on every box that
    verifies actors, VALIDATION included; plan 9's row says only "PRODUCTION". So VALIDATION refuses too, which
    is also D-464's and D-437's line ("only in DEV and TEST"). The form is a 403 with a fixed reason and no
    secret. The v1 refusal is audited by the orchestrator (`actor.refused`), not in the library. The token layer
    has no audit writer, so the line here is the log warning.
  - The orchestrator, and the gateway on a changing method, get the token passed on, as before. Their own audited
    refusal answers (`caller_unverified`), so their audit events stay. The gateway's reads (`/v1/models`,
    `/v1/serving/status`, `/readyz`, the mounted `/registry` reads) are refused at the token layer.
  - DEV and TEST are unchanged: the token is accepted, with the same warning.
  - `doctor` gains `legacy_token`. It FAILs where `TB_ENV` is not DEV or TEST while the box still holds the token
    (`TB_SERVICE_TOKEN` in `deploy/.env`, or the `legacy` hash in `tokens.json`). The line names the places, never
    a value, and gives the fix: `sudo python3 -m tools.trialbox secrets rotate`. DEV and TEST PASS, with a note.
  - The update's preflight (`Updater._legacy_token`, after `_from_a_commit`) refuses a PRODUCTION or VALIDATION
    compose box that holds it, before anything changes, and names the same fix.
  - `deploy/install.sh` drops `TB_SERVICE_TOKEN` from `deploy/.env` unless the file held a real one before this
    install. Before this, a `deploy/.env` written ahead of the install (D-837: `TB_ENV`) made the box count as not
    fresh, and the settings wizard's own random token was kept and registered as `legacy`. Such a new box would
    then fail doctor and refuse updates.
- **Why it does not take a box down:** every box from `install.sh` runs the secrets overlay
  (`deploy/docker-compose.secrets.yml`, also in `COMPOSE_FILE`, which the update reuses). There each TrialBox service
  has its own token file and `TB_SERVICE_TOKEN` cleared, and `service_token` reads the file first. So no service
  of such a box presents the shared token, even while the box still holds it for a migration. The host tools that
  call a service (`restore_drill`, `failure_drill_box`, `qualify`, `public_accuracy.onbox`) use `auth_headers`. A
  tool still run with the shared token in its environment is refused, and doctor names the cause.
- **Not proved here:** no Docker daemon and no box. The compose files were read, not started. A box that has no
  token registry (installed before step 8 and never re-installed) and runs PRODUCTION already lost the
  orchestrator under D-464. It now loses the other services too, until `secrets rotate` and an install re-run put
  the overlay in `COMPOSE_FILE`. The preflight runs from the code that applies the update. An update applied by a
  release older than this one does not refuse, but then nothing presents the token (the overlay above).
- **Held by:** `tests/unit/test_legacy_token_refused.py` (both forms in every environment; each callee; one warning
  and no value; the overlay; the installer's lines run as they stand with the real `secrets init`; doctor; the
  preflight), with the changed assertions of `tests/unit/test_service_secrets.py`, `tests/unit/test_service_auth.py`
  and `tests/unit/test_the_publish_of_a_held_night_checks_the_steward.py`.
