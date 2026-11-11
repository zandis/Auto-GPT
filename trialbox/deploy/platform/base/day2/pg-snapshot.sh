#!/bin/sh
# The backup job's database snapshot (T-633, D-416), in the database image (its psql and pg_dump). The job's first
# init container (`trialbox platform-day2 snapshot-prepare`) wrote one psql script per database and the list
# `sources` ("<database> <variable>"); each script exports a REPEATABLE READ snapshot, runs pg_dump on it and, in the
# same session, counts and hashes every table (backup_schedule.snapshot_script, D-187). The connection strings stay
# in the environment: the scripts name the variable, never its value.
set -eu
SPOOL="${1:-/spool}"
umask 077
while read -r db var; do
  [ -n "$db" ] || continue
  case "$db" in trialbox_wf|hapi) ;; *) echo "pg-snapshot: database $db refused" >&2; exit 2 ;; esac
  case "$var" in
    TB_DB_URL) url="${TB_DB_URL:?TB_DB_URL is not set}" ;;
    TB_HAPI_DB_URL) url="${TB_HAPI_DB_URL:?TB_HAPI_DB_URL is not set}" ;;
    *) echo "pg-snapshot: variable $var refused" >&2; exit 2 ;;
  esac
  psql -X -q -v ON_ERROR_STOP=1 --dbname "$url" -f "$SPOOL/$db.sql" > /dev/null
  rc="$(cat "$SPOOL/$db.dump.rc" 2>/dev/null || echo missing)"
  if [ "$rc" != 0 ]; then
    echo "pg-snapshot: pg_dump of $db failed (exit $rc)" >&2
    exit 1
  fi
  echo "pg-snapshot: $db dumped in its snapshot"
done < "$SPOOL/sources"
