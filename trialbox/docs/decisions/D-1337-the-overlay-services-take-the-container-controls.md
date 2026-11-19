# D-1337 The overlay services take the four container controls, or a written exception (H-58)

- **Task:** lane H, card H-58 (finding H10G1-03 of 10G-1, D-1323). · **Date:** 2026-11-19
- **Decision:**
  - D-1323's four controls (`cap_drop: [ALL]`, `security_opt: ["no-new-privileges:true"]`, `read_only: true` with a
    `/tmp` tmpfs, a fixed numeric non-root `user`) now hold for the 15 services the overlay files add
    (`OUTSIDE_THE_15` of `tests/unit/test_container_hardening.py`), in every stack that runs them, the two-device
    form's included. A control a service cannot take is a written exception in the same `EXCEPTIONS` list as the
    15's, and beside the service in its overlay file. No capability is added back; no service is privileged.
  - Each numeric user is the image's own: tb `10001:10001` (python.Dockerfile) for the platform doctor, the test
    bench and the two-device link; nobody `65534:65534` for Prometheus (its image's `USER`, owner of
    `/prometheus`) and Mailpit (its image names no user: it ran as root; its one binary is 0755); greenmail
    `999:999` for both GreenMail servers (the image's `/etc/passwd`); lldap `1000:1000` for the acceptance
    directory and its seed (the rootless image's UID and GID; `tools/acceptance_env.py` chowns their files to 1000).
    Read from each pinned image's configuration and layers in the public registry, not from a running container.
  - What each one writes outside its volumes goes to a `/tmp` tmpfs: the JVM's hsperfdata (GreenMail), the seed's
    `mktemp -d`, the doctor's tempfile; Prometheus, Caddy (XDG folders `/data`, `/config`) and LLDAP (`/data`)
    keep their state on volumes.
- **Exceptions:**

  | Service | Control | Why |
  | --- | --- | --- |
  | llm-verifier | read_only, user, cap_drop | The second vLLM server of the GPU overlays: the same image as llm-service and the same three exceptions (D-1323, H10G1-02). Its capabilities are not changed: rc1 runs the GPU profiles with them. It gains `no-new-privileges`, as llm-service has. |
  | judge-sleep-init, judge-wake-init, model-swap-init | user | The rtx5090 swap helpers run the vLLM image's python, which that image runs as root; not shown here to start as another uid, and no rehearsal leg runs the profile. They write nothing: cap_drop, no-new-privileges, read-only root. |
  | caddy | user, cap_drop | Runs as root and binds 443: without NET_BIND_SERVICE the bind rests on Docker's per-container port sysctl; without DAC_OVERRIDE root cannot read a hospital key (`TB_TLS_KEY_FILE`) of another owner at 0600/0640, a host file whose owner and mode the installer does not set; caddy-data's files are root's. It takes no-new-privileges and a read-only root. |
  | authelia | user, cap_drop, read_only | The image starts as root (`PUID=0`, `PGID=0`) and its entrypoint sets the owner of `/config` and the user it runs as at start; it writes `/app/.healthcheck.env`, an image path its own health check reads. It takes no-new-privileges. |
  | mailpit | read_only | With no `MP_DATABASE` its message database is a file in `/tmp`: on a read-only root a memory tmpfs under its 256m cap, filled by every test mail. Test profile only. |

- **Not proved here:** no Docker daemon where this was made: nothing was started. Shown: the YAML of every stack
  and `docker compose config` of every stack (the two-device ones with documentation addresses). The CI box
  rehearsal (`trialbox-rehearse-box`) boots the base file, the secrets file, the rtxpro6000 file with its model
  servers replaced by stand-ins, and the identity file without the `oidc` profile: of these services it starts
  Caddy (and llm-verifier as the stand-in, not vLLM). The e2e workflow's compose job (nightly) starts the test
  file's GreenMail and Mailpit. Nothing in CI starts the GPU overlays' vLLM servers or swap helpers, Authelia,
  Prometheus, the platform doctor, the acceptance services, the test bench or the two-device link.
- **Held by:** `tests/unit/test_container_hardening.py` (every service of every compose file is checked in a stack
  that runs it; each control or its exception; the numeric users; the negative cases).
