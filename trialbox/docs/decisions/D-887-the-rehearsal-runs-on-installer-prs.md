# D-887 the box rehearsal runs in CI, by hand and on installer pull requests, in two variants

- **Task:** I-8 (the integrator's answer on #639, 2026-11-15: no schedule, D-511 stands)
- **PR:** this branch (`agent/I-8b-the-rehearsal-runs-on-installer-prs`)
- **Date:** 2026-11-15
- **Status:** accepted

## Decision

1. `.github/workflows/trialbox-rehearse-box.yml` runs `make rehearse-box` on `workflow_dispatch` and on a pull request
   that touches the installer path; never on a schedule. Two legs: `test` (the rehearsal as it is) and `validation`.
2. `TB_REHEARSE_VARIANT=validation`: the passphrase KEK with no TPM, `TB_HOST_PROFILE=poc`, a root-owned `deploy/site`,
   and a second install of the same bundle (`reinstall`: continues, keeps `kek.json`). The box stays TEST, where the
   model stand-ins are honoured (D-726); the environment name VALIDATION itself is not rehearsed.
3. install.sh seals the site keys on any box whose installer environment names `TB_KEK_BACKEND` (before: a DEV or
   TEST box only with a hardening.conf, which also sets the firewall and SSH).

4. Found by its first run: since D-835 a failed pin stops the install, and the rehearsal media's placeholder weights
   are never the release's (models/registry.yaml names the real ones), so every rehearsal stopped at the pin. On a
   rehearsal box only (TB_ENV TEST, TB_REHEARSAL=1) the refused pin is said and the install goes on: the model
   stand-ins answer. Every other box still stops. The teardown's cleanup container runs as root.

5. Its second run reached the install's host check (never run on a box before, first-contact handover) and found:
   the doctor in the image read no site key and no compose file outside deploy/ (check_host.sh now mounts the
   secrets volume at /run/secrets/trialbox and each such file, read-only); a rehearsal box cannot load the egress
   table without NET_ADMIN (WARN there only); and the runner's swap and UTC zone, which a site's host has not (the
   workflow turns swap off, the rehearsal host takes the site's zone).
6. Its third run reached the second install of a sealed box and found that the seal left kek.json, the wrapped keys
   and the runtime KEK (and its folder) root's: the services run as uid 10001 and could open none of them, so keys-init
   failed on the re-run and every service reading a key would fail on a sealed box. seal_keys.sh and the boot unseal
   unit now hand them to the secrets folder's owner; modes stay 0600 (the folder 0700). The host check gives the
   doctor a missing secrets folder when it cannot see the volume (WARN, not a false FAIL). On a sealed box the KEK
   (/run/trialbox/kek, mode 0600, its folder 0700), kek.json and the wrapped keys belong to uid and gid 10001, the
   user `tb` every TrialBox service runs as (deploy/docker/python.Dockerfile) and the owner of the secrets volume:
   the services open them and nobody else can (`ls -ln /run/trialbox` and the volume's folder show 10001 10001).
7. Its fourth run passed install and the second install and showed where the rehearsal had fallen behind the box:
   a rehearsal box's host has no encrypted disk (LUKS: WARN there only, as the egress table); the rehearsal's own
   doctor call now mounts the release tree, the secrets volume and the KEK as the host check does; with no pins on a
   rehearsal box the served step checks the stand-ins serve exactly the names the gateway calls; the synthetic
   ingest takes today's snapshot date, not 2026-10-04 (older than the box's 3-day limit, D-383).
8. The rehearsal pins the media's placeholder weights (the integrator's (a), the owner's standing yes for advised
   choices, D-504). **This exists so that the rehearsal proves the path a box judges by: installer, pins, gateway,
   model servers, SCREEN. It proves nothing about a model.** `pin_model --install` pins them only when all three hold:
   a rehearsal box (TB_ENV TEST, TB_REHEARSAL=1), a rehearsal bundle (`installed.json` says `rehearsal: true`, from
   release.json; the rehearsal builds its bundle with `make_bundle.sh --rehearsal`), and every weight folder of the
   pair is the media's placeholder (`config.json` architectures `TrialBoxRehearsalPlaceholder`); a real folder beside
   a placeholder refuses the whole pin. The pin is a candidate with `weights.trust: rehearsal_placeholder`; the
   registry routes it on a TEST box only (services/registry, one condition); `--promote` and qualify refuse it by
   name; the doctor's serving and registry_pins lines and the served step say "rehearsal placeholder". The install's
   earlier "a rehearsal box goes on unpinned" is gone: a refused pin stops every box.
9. **The rehearsal box is VALIDATION** (the integrator's (i), 2026-11-15; it amends D-726's "a rehearsal box is
   TEST", every refusal of D-726 for a box without the mark standing). Its fifth run showed why: SCREEN's note checks
   are D3, a TEST box has no step confirmer and its class ceiling is D0, so the gateway refused all twelve
   (`step_unconfirmed`, then `class_not_allowed_in_env`) and no SCREEN could reach the pinned builds there.
   - The mark: `deploy/install.sh --rehearsal` writes `deploy/site/rehearsal.json` before the bundle loads (the
     load records it in installed.json as `rehearsal_box: true`) and then `TB_ENV=VALIDATION`, `TB_REHEARSAL=1` in
     deploy/.env. A variable alone makes no rehearsal box: a VALIDATION box counts as one only with both marks.
   - The pin's three conditions stand: a rehearsal box (TEST or VALIDATION, `TB_REHEARSAL=1`, installed.json's
     recorded mark), a rehearsal bundle, every folder a placeholder; PRODUCTION never. The registry routes a
     placeholder candidate on TEST or VALIDATION, never PRODUCTION.
   - Never taken for a validation box: the doctor's standing line "REHEARSAL BOX: placeholder models, synthetic data
     only" (no setting turns it off), the console's banner and footer say `VALIDATION REHEARSAL`, and qualify,
     `pin_model --promote` and `--promote-shipped` refuse on a rehearsal box by name (the mark beside the pins).
   - A VALIDATION box without the mark refuses a rehearsal bundle, a placeholder pin and `--rehearsal` exactly as
     before; a PRODUCTION box refuses the bundle whatever marks it carries.
   - Every rehearsal now runs as a validation run on a plain VM does (VALIDATION seals the site keys and FAILs what
     only a site's host has): the passphrase KEK with no TPM and `TB_HOST_PROFILE=poc`; the validation variant adds
     the root-owned `deploy/site` and the second install. The doctor's registry_pins line no longer says a VALIDATION
     box with candidates "routes nothing" (D-823: it runs its candidate pair).
   - **What the rehearsal reaches now:** VALIDATION's gates, D3 on the box, both pinned builds through the gateway
     (SCREEN on synthetic hospital A), the seal and the second install. **What it still cannot reach:** a real model,
     a GPU, the shipped egress rules (no NET_ADMIN in its container), a TPM, the host's time sync, the systemd timers
     and an off-box audit anchor share. The doctor step names these last three (`clock`, `ops_runner`,
     `audit_heads`) as not reached by a rehearsal and fails on any other FAIL.
   - Its sixth run (the first on VALIDATION) found two things every poc VALIDATION box would meet, the PoC VM
     included: the install's host check FAILed `ops_runner` (a poc box installs no systemd units) and `audit_heads`
     (no hospital share for the anchor folder), and `secure_cookie` (a box behind https left the cookie off outside
     PRODUCTION). The first two are host facilities under the poc profile now, as the anchor mount was (a stale or
     broken head where a folder is set stays a FAIL); install.sh sets `TB_CONSOLE_SECURE_COOKIE=1` on a box with
     `TB_TLS_HOSTNAME`, keeping a value the site wrote.
   - Its seventh run installed and reinstalled on VALIDATION; SCREEN found no approved study (a VALIDATION box seeds
     no example, D-640). The rehearsal installs GZQO by the operator's synthetic-run command of RUNBOOK §1 step 2
     before SCREEN, and its own doctor call reads the box's deploy/.env as the host check's does.

## Test

`tests/unit/test_rehearsal_workflow.py`: before, 6 failed; after, 6 passed. `tests/unit/test_install_pin_step.py`: the
rehearsal-box case failed before, passes after; the four other boxes still stop. The workflow itself proves the run.
