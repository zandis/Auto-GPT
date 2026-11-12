# D-575 A build's extra CA is readable by apt wherever apt reads it

- **Task:** DEMO-CA (given to lane D by the integrator on 2026-11-12: the demo image does not build behind a
  TLS-inspecting proxy)
- **PR:** this branch (`agent/DEMO-CA-secret-mode`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** the build secret `extra_ca` (a PEM trusted during the build only, for a TLS-inspecting proxy);
  `deploy/docker/db.Dockerfile`, which already mounts it with `mode=0444` for the same reason

## Context

A build secret is mounted readable by root only. `apt` fetches as the user `_apt`. Where a Dockerfile points
`Acquire::https::CAInfo` at the secret, `_apt` cannot read it and `apt-get update` fails behind such a proxy.
`demo/Dockerfile` did that; the database image had the fix, the demo image did not.

## Decision

1. `demo/Dockerfile` mounts `extra_ca` with `mode=0444` in the step where apt reads it.
2. A test holds the rule for every Dockerfile of the repository: a step that gives the mounted secret to apt
   (`Acquire::https::CAInfo "/run/secrets/extra_ca"`) mounts it with `mode=0444`. A step that copies the secret to
   a file of its own first, or gives it to pip (which runs as root), needs nothing.

## Consequences

- The demo image builds behind a TLS-inspecting proxy. The secret is a public certificate: world-readable inside
  one build step is no disclosure.
- No setting, no limit, no new store.
