# Hardening follow-ups: the overlay services and a pack that does not load (2026-11-19)

**Reader:** the people who build TrialBox: lane H and the integrator. For builders, so in one language.

Card H-58: the two findings 10G-1 left open (`container-hardening-2026-11-19.md`), decision D-1337. New findings in
the register's `--add-from` form: `hardening-follow-ups-2026-11-19/findings.json`.

## H10G1-03: the overlay services

Fixed in commit 2e3febfb6abea4eb67949f64b09a3711b04aafeb. The services the overlay files add take D-1323's four
controls, or a written exception in `EXCEPTIONS` of `tests/unit/test_container_hardening.py` and beside the service
in its file. Each numeric user is the image's own, read from the pinned image's configuration and layers in the
public registry (no image was run):

| Service (file) | cap_drop ALL | no-new-privileges | read_only (tmpfs) | user |
| --- | --- | --- | --- | --- |
| greenmail (test) | added | added | added (`/tmp`) | added 999:999, the image's greenmail |
| mailpit (test) | added | added | **exception**: its message database is a file in /tmp, a memory tmpfs under 256m | added 65534:65534 (the image names none: root before) |
| testbench (testbench) | had | had | had | added 10001:10001, the image's tb |
| llm-verifier (gb10, rtx5090, rtxpro6000, dgpu48, shared-quota, platform) | **exception**, as llm-service (rc1 keeps its capabilities) | added, as llm-service | **exception**, as llm-service | **exception**, as llm-service |
| judge-sleep-init, judge-wake-init, model-swap-init (rtx5090) | added | added | added (`/tmp`) | **exception**: the vLLM image's python runs as root there; not shown as another uid |
| caddy (identity) | **exception**: root on 443, and the hospital's key file of an owner and mode the installer does not set | added | added (`/tmp`; state in the /data and /config volumes) | **exception**: root; caddy-data's files are root's |
| authelia (identity, oidc profile) | **exception**: the entrypoint changes owners and user at start | added | **exception**: writes /app/.healthcheck.env at start | **exception**: starts as root (PUID=0) and changes user |
| prometheus (monitoring) | added | added | added (`/tmp`) | added 65534:65534, the image's nobody |
| doctor (platform) | added | added | added (`/tmp`) | added 10001:10001, as the platform's own doctor Job |
| acceptance-directory, acceptance-directory-seed (acceptance) | had | had | added (`/tmp`) | added 1000:1000, the rootless image's lldap |
| acceptance-mail (acceptance) | had | had | added (`/tmp`) | added 999:999, the image's greenmail |
| link (two-device spark and workstation) | had | had | had | had 10001:10001 |

llm-service and the GPU model servers' capabilities are unchanged; adapter, orchestrator and llm-service keep their
exceptions.

The test now checks every service of every compose file under deploy/, the two-device form's included (two stacks
added to its list), in a stack that runs it; a file that sets no control key on a service it does not run there
(gb10's llm-stub) changes nothing checked. Per overlay service, each control is applied or excepted, never both. The
numeric users are pinned. Negative cases: an overlay service that loses a control, and an exception whose control
is then applied, are named. The same checks run on `docker compose config` of every stack (the compose plugin is
here; the two-device stacks with documentation addresses). One assertion of 10G-1's base test was widened: the
services named in EXCEPTIONS are now the 15 and the overlay services, since the overlay exceptions share the list.

## H10G1-04: a reference data pack that does not load

Fixed in commit 6fdb1319fb4d41baadd0c8c0635c333ce3d8b8df. The 10G-1 page recorded no reason for the warning to stay
("left open, as it changes what install reports"). The installer's loop now adds a FAIL line: the pack's file name,
"was not loaded", that the loader's error is above, that the pack stays in the pending folder, and how to retry
(re-run `deploy/install.sh`, or `tools/apply_update.sh` with a bundle that carries the pack). The install ends with
exit 1 and leaves the stack running, as for every FAIL line; box-install.sh reads that as a running stack.
`tests/unit/test_install_refdata_load_fails.py` runs the installer's own loop with a `docker` shim: a failed load
gave exit 0 and a warning before the change (the test failed), and gives the FAIL line and exit 1 after it.

## What was and was not run

No Docker daemon here: no container was started. Shown: the YAML of every stack, `docker compose config` of every
stack, the installer's loop with a shim. Not shown: that any service starts and works under its new controls.

What CI will start: the box rehearsal (`trialbox-rehearse-box`) boots the base file, the secrets file, the
rtxpro6000 file with its model servers replaced by stand-ins (llm-verifier runs the stand-in in the TrialBox image,
not vLLM) and the identity file without the oidc profile. Of the services changed here it starts Caddy (read-only
root, no-new-privileges) and the llm-verifier stand-in (no-new-privileges); its install step now also fails if the
pack does not load. The nightly e2e workflow's compose job starts GreenMail and Mailpit of the test file. Nothing
in CI starts the vLLM servers or the swap helpers of a GPU file, Authelia, Prometheus, the platform doctor, the
acceptance services, the test bench or the two-device link: for those the proof is the static checks above.

## Findings

- **H58-01** (Low): the overlay exceptions stay open: llm-verifier's three (with H10G1-02), the rtx5090 swap
  helpers' user, Caddy's user and cap_drop, Authelia's user, cap_drop and read_only, Mailpit's read_only.
- **H58-02** (Low): the overlay services that no CI job starts are hardened on the static proof only: Authelia,
  Prometheus, the platform doctor, the acceptance services, the test bench, the two-device link and the swap helpers.
  To be brought up on a compose box with each overlay before the controls are trusted there.
- **H58-03** (Low): `tests/unit/test_compose_limits.py` lints no two-device file: its list of compose files reads
  deploy/ only, not deploy/two-device (it adds the platform file by name), so the link's limits, log cap, health check
  and watchdog rule are not checked by it.
