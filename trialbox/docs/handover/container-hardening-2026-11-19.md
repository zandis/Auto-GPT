# Container hardening: the four controls on the 15 services (2026-11-19)

**Reader:** the people who build TrialBox: lane H, the integrator, and the owners of the adapter, the orchestrator
and the GPU serving profiles. Findings for builders, so in one language.

Plan 10 row 10G-1 (review 16-17 and 9l-18), decision D-1323. Findings in the register's `--add-from` form:
`container-hardening-2026-11-19/findings.json`.

## What changed

`deploy/docker-compose.yml` has 15 services. Each carries `cap_drop: [ALL]`, `no-new-privileges:true`,
`read_only: true` with a `/tmp` tmpfs, and a fixed numeric non-root user, or a written exception:

| Service | cap_drop ALL | no-new-privileges | read_only (tmpfs) | user |
| --- | --- | --- | --- | --- |
| db | yes | yes | yes (`/tmp`, `/var/run/postgresql`) | 999:999, group_add ssl-cert |
| fhir-store | yes | yes | yes (`/tmp`) | 65532:65532 |
| lake, embed-service, doc-parser, criteria-compiler, audit-writer, mail-gateway, gateway, console, llm-stub | yes | yes | yes (`/tmp`) | 10001:10001 |
| adapter | yes | yes | **exception** (H10G1-01) | 10001:10001 |
| orchestrator | yes | yes | **exception** (H10G1-01) | 10001:10001 |
| llm-service | yes | yes | **exception** (H10G1-02) | **exception** (H10G1-02) |
| model-guard | yes | yes | yes (as before) | 10001:10001 |

`tests/unit/test_container_hardening.py` merges every stack of `tests/unit/test_compose_limits.py` (the YAML level)
and renders each with `docker compose config` (where the plugin is), and fails on a missing control without an
exception, an exception whose control is applied, an unexplained `cap_add`, or a service outside the 15 that is not
listed with a reason.

## What was and was not run

No Docker daemon in the container where this was made: nothing was brought up. Shown here: the YAML and the rendered
configuration of every stack; the HL7 validator against an unwritable and a writable copy of its package cache (as
uid 10001). Not shown: that each service starts and works under the controls. To be run on a compose box before the
row is trusted: every stack up and healthy, `trialbox doctor`, the four walks, backup and restore, an update, and the
box rehearsal's later steps.

The box rehearsal ran in CI on #1142 (run 44449244254, both legs): the hardened stack came up ("doctor passed", 17
containers running and healthy), then the SC-1b / D-993 identity check failed. db PID 1 had uid and gid 999 but groups
`999` only, where `id -G postgres` is `999 101`: started as numeric `999:999`, it no longer goes through the setpriv
shim's `--init-groups` and lost postgres's `ssl-cert` group (the TLS key). The fix gives db `group_add: [ssl-cert]` (by
name, resolved in the image's `/etc/group`; user `999:999`, cap_drop, no-new-privileges and read_only unchanged), and
the YAML test pins it. No Docker daemon here, so only the rendered configuration shows it; the rehearsal on the pushed
head is the proof. The rehearsal's later steps (terminology, screen, power-cycle, restore) have NOT yet run under the
hardening: the check aborted before them.

## Findings

- **H10G1-01** (Medium): the adapter and the orchestrator cannot run read-only. The HL7 validator writes `.index.json`
  files into its package cache and renames packages there "for atomic delete"; the cache is `/opt/hl7/home`, an image
  path (`services/adapter/validate/validator.py` passes it as `-Duser.home`). The fix is in the validator: run it
  on a writable copy or a writable home seeded per image revision. Then drop the two exceptions.
- **H10G1-02** (Medium): llm-service (vLLM) still runs as root with a writable root filesystem; its compile and kernel
  caches go under `/root/.cache` and `/tmp`. To be proved on a GPU box with the caches on a volume and a fixed user.
- **H10G1-03** (Low): the overlay services outside the 15 are not hardened: llm-verifier (gb10, rtx5090, rtxpro6000,
  platform), the rtx5090 model-swap helpers, caddy, authelia, prometheus, the platform doctor. Each is listed with its
  reason in `OUTSIDE_THE_15`.
