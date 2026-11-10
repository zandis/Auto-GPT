# The db image with pgBackRest, for a box that turns on point-in-time restore (WS-08.6, D-187; RUNBOOK §5).
# The same pinned PostgreSQL image as deploy/docker-compose.yml, plus the distribution's pgBackRest package.
#   docker build -t trialbox-db-pitr:16 deploy/pgbackrest
#   echo POSTGRES_IMAGE=trialbox-db-pitr:16 >> deploy/.env
# WS-03.1's Debian db image (pgvector, PGroonga) will carry pgBackRest itself and replace this file.
ARG POSTGRES_IMAGE=postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea
FROM ${POSTGRES_IMAGE}
RUN apk add --no-cache pgbackrest \
    && install -d -o postgres -g postgres -m 0750 /var/lib/pgbackrest /var/spool/pgbackrest \
    && pgbackrest version
