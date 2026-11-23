# H93: the Kerberos libraries in the PostgreSQL image

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** H-93 (ruled by the integrator, comment 7090444805): the `rehearse` jobs fail at step 3 `media`
- **Date:** 2026-11-23
- **Decision:** none given. The card stopped at a `question:`, as the ruling asks when the package is needed; option 1
  below is built on the branch for the integrator's go (the lead's ask), not posted without it.
- **Findings:** [`h93-postgres-image-kerberos-libraries-2026-11-23/findings.json`](h93-postgres-image-kerberos-libraries-2026-11-23/findings.json)
  (H93-01 to H93-04)
- **Files:** this page and its findings; option 1: `deploy/docker/db.Dockerfile`, `deploy/images.lock`,
  `tests/unit/test_db_krb5_held_h93.py`, `tests/integration/test_db_image.py` (the lock's package set). No scan is changed.

## Which image

The job log (job 137454834125) shows only the last 25 lines of the step's log (`tools/rehearse_box/rehearse.sh`,
`step`), so the image line above the 15 `FAIL` lines is cut. The gate prints each image's line, then its failing
findings (`tools/supply_chain/release.py`, `render`). The rehearsal passes its images in this order:
`trialbox-py`, `trialbox-backup`, `trialbox-jvm`, `trialbox-postgres`, then the third-party images sorted, and the
first of those, `caddy`, is the `PASS` line right after the 15 `FAIL` lines. So the shown findings belong to
**`trialbox-postgres:16-1`** (`deploy/docker/db.Dockerfile`). That is read from the order, not from an image line:
whether the cut lines also hold findings for the other three images is not shown.

## Why the version is old

The gate fails a CRITICAL or HIGH finding only when it has a fixed version (`tools/supply_chain/vulns.py`,
`trivy_fails`). In the distribution's metadata of 2026-11-23, Debian 13 main has `krb5` at `1.21.3-5+deb13u1` and
trixie-security (index dated 2026-11-22 19:58 UTC) has `1.21.3-5+deb13u2` for `libkrb5-3`, `libkrb5support0`,
`libk5crypto3` and `libgssapi-krb5-2`. The card's premise holds for `python.Dockerfile`, which runs
`apt-get upgrade`, but `db.Dockerfile` installs exact versions and does not upgrade, so it keeps the base's
`deb13u1`. The distribution's security tracker (read over HTTPS on 2026-11-23) lists each of the 14 CVE ids in the
log (CVE-2026-71200 appears on both packages, so 15 lines) as fixed in trixie (security) `1.21.3-5+deb13u2`, with
DSA-6650-1; the security suite has the four packages at that version for amd64 and arm64.

## The chain

From the PostgreSQL apt repository's and Debian 13's package lists (read here; no Docker, and this container is
Ubuntu 24.04, so its own `apt-cache` was not used):

- `postgresql-16` (16.14-1.pgdg13+1, the base's server) Depends `libgssapi-krb5-2` and `libpq5`
- `libpq5` Depends `libgssapi-krb5-2`; `pgbackrest` (installed by `db.Dockerfile`) Depends `libpq5`
- `libgssapi-krb5-2` Depends `libkrb5-3`, `libk5crypto3`, `libkrb5support0` (each `=` the same version)

A shared-library dependency of the server package means the server binary links the library, so removing the
packages leaves a server that does not start. The box configures no GSSAPI authentication (no `gss` or `krb` in
`deploy/`, `libs/`, `services/`, `tools/`), so Kerberos is linked but not used. The ruling says not to remove it.

## question: (for the integrator)

1. Install the four `krb5` packages at `1.21.3-5+deb13u2` from trixie-security in `db.Dockerfile`, held and checked
   like `zlib1g` (D-993), with the version in `deploy/images.lock`. No package added, no scan changed. Recommended;
   built on the branch: `ARG KRB5_VERSION`, the four in the install and the hold, a `dpkg-query` check for each, the
   lock's `db.packages` (its `digest` stays `null`, so no digest is needed), and
   `tests/unit/test_db_krb5_held_h93.py`. `tests/integration/test_db_image.py` asserts the lock's package set, so it
   gains the four: a change to what a test asserts, which needs the integrator's ruling.
2. `apt-get upgrade` in `db.Dockerfile` as `python.Dockerfile` does (no pin; the image changes with the archive).
3. A server built without GSSAPI (our own build of PostgreSQL 16 and the extensions): large, and drops the
   distribution's security updates for the server.
4. Another base: PGroonga 4.1.x is built for Debian 13 (D-204), so this is the largest.

`db.Dockerfile` has no lane named in the tree (no CODEOWNERS entry, no owner in the plan); the change under 1 or 2
is outside this card until the go.

## What was not run or not verified

- No image was built and no scan was run here (no Docker). CI's `rehearse` on a head with option 1 must show
  `PASS  trialbox-postgres:16-1` and step 3 `media` passed; that is the proof the pin installs and clears the gate.
- The image line of the 15 findings is inferred from the order, as above.
