#!/bin/sh
# The extensions of the box's database image (D-204, deploy/docker/db.Dockerfile): pgvector (`vector`) and PGroonga
# (`pgroonga`) in database `trialbox_wf`, schema `public`. Created as the role `trialbox` (the database owner; the image
# marks both extensions trusted), so `trialbox` owns them: a restore as `trialbox` with `pg_restore --clean
# --if-exists` (tools/trialbox/backup.py, tools/trialbox/update.py) drops and re-creates them like any other object.
# Runs once, on an empty volume, after 10-trialbox-wf.sh. Strict on purpose: on an image without them (a stock
# `postgres` image put in POSTGRES_IMAGE) the first start fails here; `tb-db-check` (the image's readiness check)
# stays failing if a later start skips this script. No store creates an extension (the test suite's local cluster has
# neither).
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname trialbox_wf <<SQL
SET ROLE trialbox;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS pgroonga WITH SCHEMA public;
RESET ROLE;
DO \$\$
BEGIN
  IF (SELECT count(*) FROM pg_extension e JOIN pg_roles r ON r.oid = e.extowner
      WHERE e.extname IN ('vector', 'pgroonga') AND r.rolname = 'trialbox') <> 2 THEN
    RAISE EXCEPTION 'vector and pgroonga must exist in trialbox_wf, owned by trialbox (D-204)';
  END IF;
END
\$\$;
SQL
