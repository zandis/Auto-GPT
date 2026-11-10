#!/bin/sh
# The extensions of the box's database image (D-204, deploy/docker/db.Dockerfile): pgvector (`vector`) and PGroonga
# (`pgroonga`) in database `trialbox_wf`, schema `public`, created by the superuser because neither is a trusted
# extension. Runs once, on an empty volume, after 10-trialbox-wf.sh. Strict on purpose: on an image without them
# (a stock `postgres` image put in POSTGRES_IMAGE) the first start fails here instead of a box running without them.
# No store creates an extension (the test suite's local cluster has neither); tools/backup_drill.py and
# tests/integration/test_db_image.py check that both exist.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname trialbox_wf <<SQL
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS pgroonga WITH SCHEMA public;
SQL
