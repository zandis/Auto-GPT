#!/usr/bin/env bash
# The PostgreSQL server binaries for a CI job, at the box's one major (D-371). The major is `postgres_major` of the db
# image in deploy/images.lock, the same one the db image (deploy/docker/db.Dockerfile) and the demo image
# (demo/Dockerfile) build; tests/unit/test_pg_major.py holds the three equal.
# Installs postgresql-<major> when the runner lacks it: from the distribution when it carries that major (Ubuntu
# 24.04 carries 16), else from PGDG with the key Debian and Ubuntu's postgresql-common ship. Then prints
# `pg_config --version`, fails on another major, and puts that major's bin directory first on the job's PATH, so
# tools/pglocal.py, pg_dump and pg_restore all use it.
#   tools/ci_postgres.sh            (from trialbox/; needs sudo unless run as root)
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
major="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["images"]["db"]["postgres_major"])' \
  "$root/deploy/images.lock")"
case "$major" in '' | *[!0-9]*) echo "ci_postgres: bad postgres_major '$major' in deploy/images.lock" >&2; exit 1 ;; esac
bin="/usr/lib/postgresql/$major/bin"
sudo=""
if [ "$(id -u)" != 0 ]; then sudo="sudo"; fi
if [ ! -x "$bin/initdb" ] || [ ! -x "$bin/pg_config" ]; then
  $sudo apt-get update
  if [ -z "$(apt-cache policy "postgresql-$major" 2>/dev/null | sed -n 's/^ *Candidate: //p' | grep -v '(none)')" ]; then
    $sudo apt-get install -y --no-install-recommends postgresql-common
    $sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
  fi
  $sudo apt-get install -y --no-install-recommends "postgresql-$major"
fi
version="$("$bin/pg_config" --version)"
echo "pg_config --version: $version (expected major $major, deploy/images.lock)"
case "$version" in
  "PostgreSQL $major."*) ;;
  *) echo "ci_postgres: $bin/pg_config says '$version', not PostgreSQL $major (D-371)" >&2; exit 1 ;;
esac
if [ -n "${GITHUB_PATH:-}" ]; then echo "$bin" >> "$GITHUB_PATH"; fi
