# D-1323 The container hardening baseline and its exceptions (10G-1)

- **Task:** lane H, plan 10 row 10G-1 (review 16, item 16-17; plan 9 rev 2, 9l-18): `cap_drop: [ALL]`,
  `no-new-privileges`, `read_only` with tmpfs and a fixed user on all 15 services. · **Date:** 2026-11-19
- **Decision:**
  - The 15 services of `deploy/docker-compose.yml` (db, fhir-store, lake, embed-service, doc-parser,
    criteria-compiler, adapter, audit-writer, orchestrator, mail-gateway, gateway, console, llm-stub, llm-service,
    model-guard) each carry four controls, or a written exception: `cap_drop: [ALL]`,
    `security_opt: ["no-new-privileges:true"]`, `read_only: true` with a tmpfs for what the service writes outside its
    volumes, and a fixed numeric non-root `user`. No capability is added back.
  - The TrialBox Python images (the `x-py` anchor: eleven services) run as `10001:10001`, `tb` of
    `deploy/docker/python.Dockerfile` (the JVM and embed images build on it), the user they already ran as: the named
    volumes the image seeds stay theirs, and `install.sh` already gives `settings.yaml` to group 10001. Their one
    write outside a volume is `/tmp` (tempfile, the audit-writer heartbeat, `MPLCONFIGDIR`, `HF_HOME`, the extra CA
    bundle, the JVM's hsperfdata): a tmpfs, charged to the service's `mem_limit`.
  - db runs as `999:999`, postgres of the Debian PostgreSQL image (Docker adds its `ssl-cert` group from
    `/etc/group`): the entrypoint no longer starts as root, so it skips its chown and the setpriv shim (D-993); db-pg
    and the pgBackRest repository were written by postgres already. tmpfs `/tmp` (pgBackRest's lock, the update's
    restore file) and `/var/run/postgresql` (the socket, owned 999); pgBackRest writes no log file
    (`log-level-file=off`).
  - fhir-store runs as `65532:65532`, the upstream distroless image's nonroot user, named so it is fixed; tmpfs
    `/tmp` for embedded Tomcat. HAPI's data is in PostgreSQL.
  - model-guard keeps what it had (D-177).
- **Exceptions** (in `EXCEPTIONS` of the test and beside each service in the compose file):

  | Service | Control | Why |
  | --- | --- | --- |
  | adapter | read_only | The HL7 validator (`adapter.validate.validator`) writes `.index.json` files into, and renames packages in, its package cache `/opt/hl7/home`, an image path. Run as uid 10001 against a cache it cannot write, it stops with "Unable to rename directory ... for atomic delete" (tried 2026-11-19 with the validator and packages of `make jvm-deps`); against a writable copy it passes. The cache is 399 MB, too much for a tmpfs under the 6g cap. The fix is in the adapter's validator (a writable package home), outside deploy/. |
  | orchestrator | read_only | Runs the same validator for the TWPAS scenario (`scenarios/twpas.py`). |
  | llm-service | read_only, user | The upstream vLLM image runs as root and writes its compile and kernel caches under `/root/.cache` and `/tmp`: gigabytes a memory tmpfs would take from the model. To be proved on a GPU box with the caches on a volume. cap_drop and no-new-privileges hold. |

- **Not in the 15:** the overlay services (llm-verifier, the rtx5090 model-swap helpers, caddy, authelia, prometheus,
  the platform doctor, the developer mail servers, the acceptance directory) are listed in `OUTSIDE_THE_15` with a
  reason each; a new service anywhere fails the test until it is placed.
- **Not proved here:** no Docker daemon in the container where this was made. Before 10G-1 is trusted, on a compose
  box: every stack up (stub, gpu, test, identity, box, monitoring, acceptance, platform) and healthy; `trialbox
  doctor`; `make walk-new-study walk-life-cycle walk-life-cycle-390 walk-modules`; a backup and a restore; an update
  (its db restore runs `exec db` as postgres now); the box rehearsal's SC-1b check (db PID 1 as 999 with postgres's
  own groups).
- **Held by:** `tests/unit/test_container_hardening.py` (the YAML of every stack, and `docker compose config` where
  the plugin is).
