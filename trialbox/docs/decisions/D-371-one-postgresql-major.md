# D-371 One PostgreSQL major: 16 on Debian 13, pgBackRest from PGDG

- **Task:** T-104b, database base and major, dependency batch 2, data plane (`docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-104b-db-major`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** DEP-013 (base and major, pins), DEP-014 (one major everywhere), DEP-027 (pgBackRest pinned)
- **Builds on:** D-204 (the db image and `deploy/images.lock`), D-348 (the lock's third-party part), D-187 (pgBackRest)

## Context

The deep review of 2026-11-10 (`docs/reviews/2026-11-10-deep-review/08-dependency-currency.md`) found:

- DEP-013: the db image should be Debian 13 with pinned pgvector, PGroonga and pgBackRest, at a major chosen by the
  owner (question Q1), before any site data.
- DEP-014: the major differs by place. The db image runs 16. The demo image installs Debian's `postgresql`, which
  is 17 on its trixie base. CI uses what `ubuntu-latest` has (16 on 24.04, 18 on 26.04).
- DEP-027: pgBackRest comes from `apk add pgbackrest` with no version.

T-104 (D-204) already moved the db image to `postgres:16-trixie` with pgvector and PGroonga pinned.

## Decision

1. **The major is 16.** The owner's question is dropped under D-311 (below). The rule given to the card was: the
   major already used most on master, or else the newest one that pgvector, PGroonga and pgBackRest all support
   for Debian 13. 16 is the one used most on master: the db image and its tag `trialbox-postgres:16-1`, the lock,
   compose, the platform manifests, the release records, the update and rehearsal tools, the SOUP list, about 20
   tests and the CI runners (Ubuntu 24.04 has 16). The demo image was the only place on another major (17). All
   three dependencies are built for 16 on Debian 13: pgvector `0.8.7-1.pgdg13+1` and pgBackRest
   `2.60.0-1.pgdg13+1` from PGDG `trixie-pgdg` (amd64 and arm64), PGroonga `4.1.0-1` from the Groonga repository.
   PostgreSQL 16 is supported until 2028-11-09.
2. **One declared major.** `deploy/images.lock` gets `images.db.postgres_major` (`"16"`). Every place reads it or
   is checked against it:
   - db image: base `postgres:16-trixie` by digest; `ARG PG_MAJOR_EXPECTED=16`; the build stops when the base's
     `PG_MAJOR` or `pg_config --version` is another major.
   - demo image: `ARG PG_MAJOR=16`; `postgresql-16` from PGDG (the key comes with Debian's `postgresql-common`,
     nothing is fetched on first use); the build stops when `pg_config --version` is another major.
   - CI: `tools/ci_postgres.sh` reads the lock and installs `postgresql-<major>` if the runner lacks it (from the
     distribution when it has that major, else from PGDG). It prints `pg_config --version`, fails on another
     major and puts that major's `bin` first on the job's `PATH`. Every workflow step that set up PostgreSQL now
     calls it.
   - `tests/unit/test_pg_major.py` (no server, no docker) checks the four places name the same major. It also
     checks that no workflow installs `postgresql` itself or runs a `postgres` service container.
3. **pgBackRest in the db image.** `pgbackrest=2.60.0-1.pgdg13+1` from PGDG is installed and held. Its version is
   checked at build. `/var/lib/pgbackrest`, `/var/spool/pgbackrest` and `/var/log/pgbackrest` are owned by
   `postgres`. The lock lists the package. A box that turns on point-in-time restore no longer needs a second
   image.
4. **The tag stays `trialbox-postgres:16-1`.** The major did not change, and the lock's `digest` is still null
   until a release pins it (D-204, T-110).

## Consequences

- If the major is set in one place only, `make test` fails. If an image or a CI runner gets another major, its
  build or job fails and prints `pg_config --version`.
- To move to 17 or 18 later, change the lock's `postgres_major`, the db base and digest, both `PG_MAJOR` args and
  the image tag. Do it before any site data. After site data it needs `pg_upgrade` or dump and restore on each box.
- The demo now runs the same major as the box, so `pglocal` and the update path's dumps behave the same in both.
- `deploy/pgbackrest/Dockerfile` (Alpine) is now redundant. Retiring it, and its lines in compose and RUNBOOK §5,
  is left to a later card.

## Dropped (D-311)

- **Owner question Q1, "PostgreSQL 17 or 18".** This was a development gate, so D-311 dropped it. The card's rule
  chose the major (decision 1). No owner sign-off is needed.
