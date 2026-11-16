#!/usr/bin/env bash
# The PostgreSQL server binaries for a CI job, at the box's one major (D-371). The major is `postgres_major` of the db
# image in deploy/images.lock, the same one the db image (deploy/docker/db.Dockerfile) and the demo image
# (demo/Dockerfile) build; tests/unit/test_pg_major.py holds the three equal.
# Installs postgresql-<major> when the runner lacks it: from the distribution when it carries that major (Ubuntu
# 24.04 carries 16, so a GitHub-hosted job installs nothing), else from PGDG with the key Debian and Ubuntu's
# postgresql-common ship. A self-hosted Ubuntu does not have the package. That install needs passwordless sudo
# (`sudo -n`): a password prompt would hang the job, so a missing sudo fails at once and names the package. The
# package would start a default cluster on TCP 5432. These jobs use throwaway unix-socket clusters
# (tools/pglocal.py), and the self-hosted host is shared, so the install turns that cluster off for the duration
# (`create_main_cluster = false`), restores the file afterwards, and drops a `main` cluster if one was created
# anyway. A major that was already installed is left as the host had it. Then prints `pg_config --version`, fails
# on another major, and puts that major's bin directory first on the job's PATH, so tools/pglocal.py, pg_dump and
# pg_restore all use it.
#   tools/ci_postgres.sh            (from trialbox/; sudo only when the binaries are missing and the user is not root)
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
major="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["images"]["db"]["postgres_major"])' \
  "$root/deploy/images.lock")"
case "$major" in '' | *[!0-9]*) echo "ci_postgres: bad postgres_major '$major' in deploy/images.lock" >&2; exit 1 ;; esac
bin="/usr/lib/postgresql/$major/bin"
if [ ! -x "$bin/initdb" ] || [ ! -x "$bin/pg_config" ]; then
  sudo=""
  if [ "$(id -u)" != 0 ]; then
    if ! sudo -n true 2>/dev/null; then
      echo "ci_postgres: $bin/initdb is not installed, and passwordless sudo is not available." >&2
      echo "ci_postgres: install postgresql-$major (so $bin/initdb exists), or grant the runner user NOPASSWD for apt-get." >&2
      exit 1
    fi
    sudo="sudo -n"
  fi
  conf=/etc/postgresql-common/createcluster.conf
  saved=""
  restore_cluster_conf() {
    if [ -n "$saved" ] && [ -f "$saved" ] && [ -f "$conf" ]; then
      $sudo cp "$saved" "$conf"
      rm -f "$saved"
      saved=""
    fi
  }
  $sudo apt-get update
  if [ -z "$(apt-cache policy "postgresql-$major" 2>/dev/null | sed -n 's/^ *Candidate: //p' | grep -v '(none)')" ]; then
    $sudo apt-get install -y --no-install-recommends postgresql-common
    $sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
  fi
  if [ ! -f "$conf" ]; then
    $sudo apt-get install -y --no-install-recommends postgresql-common
  fi
  # the server package reads this before it creates a cluster. Put it back before the script exits, including on
  # failure, so a later install on this host still gets the cluster its package would have created.
  if [ -f "$conf" ]; then
    saved="$(mktemp)"
    $sudo cp "$conf" "$saved"
    $sudo sed -i 's/^[# ]*create_main_cluster.*/create_main_cluster = false/' "$conf"
    $sudo grep -q '^create_main_cluster = false' "$conf" || echo 'create_main_cluster = false' | $sudo tee -a "$conf" >/dev/null
    trap restore_cluster_conf EXIT
  fi
  $sudo apt-get install -y --no-install-recommends "postgresql-$major"
  restore_cluster_conf
  # a cluster this install created anyway (TCP 5432). Not one the host already had: this branch runs only when the
  # binaries were missing
  if $sudo pg_lsclusters --no-header 2>/dev/null | awk -v m="$major" '$1 == m && $2 == "main" { found = 1 } END { exit !found }'; then
    $sudo pg_dropcluster --stop "$major" main
  fi
fi
version="$("$bin/pg_config" --version)"
echo "pg_config --version: $version (expected major $major, deploy/images.lock)"
case "$version" in
  "PostgreSQL $major."*) ;;
  *) echo "ci_postgres: $bin/pg_config says '$version', not PostgreSQL $major (D-371)" >&2; exit 1 ;;
esac
if [ -n "${GITHUB_PATH:-}" ]; then echo "$bin" >> "$GITHUB_PATH"; fi
