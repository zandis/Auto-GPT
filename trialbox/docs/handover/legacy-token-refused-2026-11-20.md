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

## The review of 9g-13 (#1267, head 5a421d64), fixed in 9g-13b

Each finding has a test in `tests/unit/test_legacy_token_review.py` that failed on 5a421d64 and passes after the fix
(commit 5e905001b8706330eb9acf3cb4800dcf68c48468, unless the row says otherwise).

| Finding | Test | Fix |
| --- | --- | --- |
| High: an old installed updater skips the new preflight | `test_the_new_trees_pre_start_refuses_...`, `test_the_pre_start_step_refuses_after_the_making_steps_only_...` | The new tree's `pre-start` refuses in its last step, before the stack starts. Every updater since UPDATE-PRESTART runs that command before the stack starts. |
| High: a named match beats the legacy hash | `test_a_hash_marked_legacy_is_legacy_even_when_...` | `Registry.identify` decides the legacy mark first. |
| High: the shell sets the gateway's `TB_ENV` | `test_no_service_of_an_installed_box_takes_tb_env_from_the_shell` | The gateway takes `TB_ENV` from `deploy/.env` only. |
| Medium: `/v1/serving/release` answers 200 to the old token | `test_the_legacy_token_cannot_release_the_card_with_200` | The gateway's own route gate, a separate commit in `services/gateway/app.py`, asked on #639. |
| Medium: `secrets rotate` without the secrets overlay | `test_rotation_is_refused_where_...` | Rotation of tokens is refused there. Doctor, the preflight and `pre-start` name the overlay. |
| Medium: `--firstrun` adds a shared token back | `test_the_first_runs_answers_add_no_shared_token` | `tools.box apply` drops the wizard's token. |
| Medium: a file-backed shared token is missed | `test_a_file_backed_shared_token_is_held_too` | `legacy_held` counts `TB_SERVICE_TOKEN_FILE` where no registry reaches the services. |
| Medium: doctor `--env-file` reads the sibling `.env` | `test_doctor_reads_the_env_file_it_was_given` | Doctor reads the file it was given. |
| Medium: a quoted `TB_ENV` blocks a TEST update | `test_a_quoted_tb_env_is_read_as_compose_reads_it` | Quotes are read as compose reads them. |
| Low: the registry mount is not checked | `test_every_service_of_an_installed_box_can_read_the_registry_it_needs` | The test, which fails when the adapter's registry mount is removed. |

The orchestrator is no longer passed the old token by name. `make_app` hands the token layer's refusal to the
orchestrator's route gate, which audits it as before (`test_a_route_gate_can_only_replace_a_legacy_refusal_with_its_own`).
