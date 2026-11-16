# D-963 the dead deploy files go, and no page says to swap the db image

- **Task:** LEFTOVERS, lane D backlog (#639, 2026-11-16; the owner's ruling to complete everything as soon as possible)
- **PR:** this branch (`agent/LEFTOVERS-the-dead-deploy-files-go`)
- **Date:** 2026-11-16
- **Status:** accepted

## Decision

Plan v7 §3.1 (OPS-013).

1. `deploy/topology_a/podman-compose.yml` (no box uses it) and `deploy/pgbackrest/Dockerfile` (Alpine) are removed;
   `deploy/pgbackrest/pgbackrest.conf` stays (the db service mounts it).
2. RUNBOOK §5's point-in-time restore step 1 set `POSTGRES_IMAGE` to an image built from that Dockerfile. That swaps
   the box's Debian db image, which carries pgBackRest 2.60 (D-371), for one without pgvector and PGroonga and with
   another C library. Step 1 now sets only `TB_PGBACKREST_REPO` and says never to change `POSTGRES_IMAGE`; the
   compose comment says the same. Step numbers are kept.

## Test

`tests/unit/test_dead_deploy_files.py`: the files are gone, `pgbackrest.conf` stays, no runbook page or compose file
says to build or swap the old image, the db image installs pgBackRest.
