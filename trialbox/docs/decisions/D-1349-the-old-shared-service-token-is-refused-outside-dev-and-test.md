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
  - The legacy mark is decided before any service's entry (`Registry.identify`): a hash marked `legacy` that a
    service's entry also holds is still the old token, never that service (review of 9g-13, High).
  - No callee is exempt by name but one. The orchestrator is refused at the token layer like every service, and
    `tb_common.http.make_app` (body only) hands that refusal to the service's route gate, which answers with its
    own audited one (`caller_unverified`, `service.route_refused`, D-464). A gate can only replace a refusal with a
    refusal, never admit the call. The gateway's changing calls are still passed on to the gateway, which refuses
    the token itself (D-437); its reads are refused at the token layer. The gateway's own route gate, refusing it on
    every route with its audit event, is a separate change in its file (`services/gateway/app.py`, another lane's,
    asked on #639); without it `POST /v1/serving/release` answers 200 to the old token when the model swap is off.
  - The gateway takes `TB_ENV` from `deploy/.env` (`env_file`) as every service does: the base compose file no
    longer sets it as `${TB_ENV:-PRODUCTION}`, which the shell that runs compose could override (review, High).
    `authorize` reads the environment the process was started with (`environment_name(os.environ)`).
  - DEV and TEST are unchanged: the token is accepted, with the same warning.
  - `doctor` gains `legacy_token`. It FAILs where `TB_ENV` is not DEV or TEST while the box still holds the token
    (`TB_SERVICE_TOKEN` in `deploy/.env`, or the `legacy` hash in `tokens.json`). The line names the places, never
    a value, and gives the fix: `sudo python3 -m tools.trialbox secrets rotate`. DEV and TEST PASS, with a note.
  - What counts as holding it (`svc_secrets.legacy_held`): `TB_SERVICE_TOKEN`; `TB_SERVICE_TOKEN_FILE` where no
    registry reaches the services (one token file for the whole box); the `legacy` hash; a `COMPOSE_FILE` without
    the secrets overlay (no service holds a token of its own). Quotes around a value are read as compose reads them.
    Doctor reads the settings file it was given (`--env-file`), with the registry beside it.
  - The update's preflight (`Updater._legacy_token`, after `_from_a_commit`) refuses a PRODUCTION or VALIDATION
    compose box that holds it, before anything changes, and names the fix. Because the installed, older updater
    runs its own preflight, the new tree's `pre-start` has the same refusal as its first step: every updater since
    UPDATE-PRESTART runs that command from the new tree before the stack starts, and a failed step rolls the update
    back (review, High). The floor (`MIN_INSTALLED_SEQ`) stays 0: no box has a release yet.
  - `secrets rotate` of tokens is refused where `COMPOSE_FILE` lacks the secrets overlay: the services would get no
    token of their own. The fix there is `deploy/install.sh`, which puts the overlay in `COMPOSE_FILE`, then the
    rotation.
  - `deploy/install.sh` drops `TB_SERVICE_TOKEN` from `deploy/.env` unless the file held a real one before this
    install. Before this, a `deploy/.env` written ahead of the install (D-837: `TB_ENV`) made the box count as not
    fresh, and the settings wizard's own random token was kept and registered as `legacy`. Such a new box would
    then fail doctor and refuse updates. The first run's answers (`box-install.sh --firstrun`, `tools.box apply`)
    write no shared token either.
- **Why it does not take a box down:** every box from `install.sh` runs the secrets overlay
  (`deploy/docker-compose.secrets.yml`, also in `COMPOSE_FILE`, which the update reuses). There each TrialBox service
  has its own token file and `TB_SERVICE_TOKEN` cleared, and `service_token` reads the file first. So no service
  of such a box presents the shared token, even while the box still holds it for a migration. The host tools that
  call a service (`restore_drill`, `failure_drill_box`, `qualify`, `public_accuracy.onbox`) use `auth_headers`. A
  tool still run with the shared token in its environment is refused, and doctor names the cause.
- **Not proved here:** no Docker daemon and no box. The compose files were read, not started; `pre-start` was run
  as the command an updater runs, on a deploy folder, not inside an update of a running box. A box that runs
  PRODUCTION without the secrets overlay (installed before step 8, never installed again) is stopped by `pre-start`
  and told by doctor; it needs `deploy/install.sh` again, then `secrets rotate`.
- **Held by:** `tests/unit/test_legacy_token_refused.py` (both forms in every environment; each callee; one warning
  and no value; the overlay; the installer's lines run as they stand with the real `secrets init`; doctor; the
  preflight) and `tests/unit/test_legacy_token_review.py` (one test per finding of the review of 9g-13), with the
  changed assertions of `tests/unit/test_service_secrets.py`, `tests/unit/test_service_auth.py`,
  `tests/unit/test_service_token_everywhere.py`, `tests/unit/test_perimeter.py` (its token, not its assertions),
  `tests/unit/test_trialbox_doctor.py` and `tests/unit/test_update_minseq.py` (the new step's name).
