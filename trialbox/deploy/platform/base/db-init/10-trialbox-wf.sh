#!/bin/sh
# One PostgreSQL server, two databases (TB-PLAN-03 step 6, D-121): `hapi` (the FHIR store, created by the image from
# POSTGRES_DB) and `trialbox_wf` (durable steps, outbox, recall ledger; spec v4 §11.0). Runs once, on an empty volume.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE trialbox LOGIN CREATEDB PASSWORD '${POSTGRES_WF_PASSWORD:-$POSTGRES_PASSWORD}';
CREATE DATABASE trialbox_wf OWNER trialbox;
SQL
