#!/bin/sh
# tb-db-check (D-204): the box's database is ready only when the server answers, `trialbox_wf` exists and both
# extensions of the image (vector, pgroonga) are installed in it. Run inside the db container (compose healthcheck,
# doctor). A first start whose db-init failed half way, or an old volume that never ran db-init/20-extensions.sh,
# stays unhealthy here instead of serving without the extensions.
set -eu
U="${POSTGRES_USER:-postgres}"
pg_isready -q -U "$U" -d "${POSTGRES_DB:-$U}"
n="$(psql -X -q -U "$U" -d trialbox_wf -tAc "SELECT count(*) FROM pg_extension WHERE extname IN ('vector', 'pgroonga')")"
test "$n" = 2
