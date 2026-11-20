# H-70: two install-test gaps, buildx and SSH=off over SSH

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** H-70. Lane J reported F-5 and F-6 of an install test on a real server on PR #639 (2026-11-20).
- **Date:** 2026-11-20
- **Findings:** [`install-test-runbook-gaps-2026-11-20/findings.json`](install-test-runbook-gaps-2026-11-20/findings.json)
  (H70-01, H70-02)
- **Tests:** `tests/unit/test_install_test_gaps_h70.py`; `tests/unit/test_host_baseline.py` unchanged and passing

## 1. H70-01: `make images` without buildx (F-5)

Every Dockerfile under `deploy/docker` that installs packages uses `RUN --mount` (python, backup, embed, db), which
needs BuildKit. `make images` calls `docker build`; without the buildx plugin Docker falls back to its legacy builder,
which stops with "the --mount option requires BuildKit". `images-multiarch` calls `docker buildx build` directly.

Fixed: a `buildx-check` target runs first for both (`images: buildx-check jvm-deps $(FONTS)`). When
`docker buildx version` fails it stops before any fetch with

    images: Docker's buildx plugin is missing (docker buildx version failed); install docker-buildx-plugin (Docker's packages) or docker-buildx (Ubuntu's), then run make again

Runbook 01 step 2 names buildx, the check and both failures. `deploy/check_host.sh` checks the box, not a build host,
and no build-host check exists, so none was added.

## 2. H70-02: `SSH=off` locks out an install over SSH (F-6)

`install.sh` runs `deploy/hardening/apply.sh all` when `deploy/site/hardening.conf` exists, and the example's default
is `SSH=off`: sshd is stopped and disabled and the input firewall drops port 22. Run over SSH, the session is cut.

Fixed: before it changes anything, `apply.sh` asks whether it runs inside an SSH session (`SSH_CONNECTION` or
`SSH_TTY`, or an `sshd` or `sshd-session` process in its parent chain, read from `/proc`: sudo drops the variables).
With `SSH=off` and `all`, `firewall` or `ssh` it then refuses, exit 1, nothing written or run:

    hardening: SSH=off would stop sshd and close port 22 under this SSH session, locking it out; nothing was changed. Run it from the box's console, or add --ssh-off-over-ssh (install.sh: TB_SSH_OFF_OVER_SSH=yes) to do it anyway

`--ssh-off-over-ssh` or `TB_SSH_OFF_OVER_SSH=yes` (only that word) keeps the behaviour of before. Off SSH, with
`SSH=it`, or for `render`, nothing changes. The default stays `SSH=off`. The process tree is read under
`TB_HOST_ROOT`, so the tests stand one in. Runbook 01 step 1 and Security §1 say so.

## 3. Not done, not verified

- The `make trivy-db` figure of the same test (1 min 38 s, 3.2 GB) was not placed: no runbook page tells the operator
  to run `make trivy-db`, so there was no line to carry it.
- Not run on a real host: no Docker daemon and no SSH session here; both checks were run with stand-ins only.
- Whether `TB_SSH_OFF_OVER_SSH` reaches `install.sh` through `sudo` and the bootstrap depends on sudo's settings;
  not verified. `--ssh-off-over-ssh` on `apply.sh` itself does not depend on it.
- `SSH=it` with an `IT_RANGES` that leaves out the installer's own address also cuts the session; not checked.
