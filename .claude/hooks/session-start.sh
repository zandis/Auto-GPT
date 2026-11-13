#!/bin/bash
# Cloud sessions only: make CI's fast tier runnable before the first push (tools/prepush.py). Installs only what is
# missing; the venv is rebuilt only when uv.lock, pyproject.toml or this script changed. Prints no secret.
set -euo pipefail
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then exit 0; fi
cd "${CLAUDE_PROJECT_DIR:-.}/trialbox"

# shellcheck: CI's `checks` job gates on it
if ! command -v shellcheck >/dev/null; then
  apt-get update -qq && apt-get install -y -qq shellcheck >/dev/null
fi
# PostgreSQL at the box's major (deploy/images.lock): the cross-card job and most unit tests start a local cluster
tools/ci_postgres.sh >/dev/null
major="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["images"]["db"]["postgres_major"])' \
  deploy/images.lock)"
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then echo "export PATH=\"/usr/lib/postgresql/$major/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"; fi

# the venv, exactly as uv.lock
hashes=.venv/.session-start.sha256
if ! sha256sum --check --status "$hashes" 2>/dev/null; then
  rm -f "$hashes"
  make venv >/dev/null
  sha256sum ../.claude/hooks/session-start.sh uv.lock pyproject.toml > "$hashes"
fi

branch="$(git branch --show-current)"
case "$branch" in
  master | "") echo "session-start: you are on '${branch:-a detached HEAD}': cut your own branch before you commit" ;;
esac
echo "session-start: venv, PostgreSQL $major and shellcheck ready; before a push: .venv/bin/python -m tools.prepush"
