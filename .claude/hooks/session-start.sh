#!/bin/bash
# Cloud sessions only: make CI's fast tier runnable before the first push (tools/prepush.py). Installs only what is
# missing; the venv is rebuilt only when uv.lock, pyproject.toml or this script changed. A step that cannot install
# (no network) is reported and skipped; the session starts either way. Prints no secret, changes no git state.
set -uo pipefail
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then exit 0; fi
cd "${CLAUDE_PROJECT_DIR:-.}/trialbox" || exit 0
missing=()

# uv at the version CI pins (tools/supply_chain/lock.py UV_VERSION): an older uv fails lock-check here, not in CI
want="$(sed -n 's/^UV_VERSION = "\(.*\)"$/\1/p' tools/supply_chain/lock.py)"
if [ "$(uv --version 2>/dev/null | cut -d' ' -f2)" != "$want" ]; then
  python3 -m pip install -q --user --break-system-packages "uv==$want" >/dev/null 2>&1 \
    || python3 -m pip install -q --user "uv==$want" >/dev/null 2>&1 || missing+=("uv $want")
fi

# the venv, exactly as uv.lock
hashes=.venv/.session-start.sha256
if ! sha256sum --check --status "$hashes" 2>/dev/null; then
  rm -f "$hashes"
  if make venv >/dev/null 2>&1; then
    sha256sum ../.claude/hooks/session-start.sh uv.lock pyproject.toml > "$hashes"
  else
    missing+=("the venv (run: make venv)")
  fi
fi

# PostgreSQL at the box's major (deploy/images.lock): cross-card and most unit tests start a local cluster
major="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["images"]["db"]["postgres_major"])' \
  deploy/images.lock)"
if tools/ci_postgres.sh >/dev/null 2>&1; then
  if [ -n "${CLAUDE_ENV_FILE:-}" ]; then echo "export PATH=\"/usr/lib/postgresql/$major/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"; fi
else
  missing+=("PostgreSQL $major")
fi

# the shell linter: CI's checks job gates on it
if ! command -v shellcheck >/dev/null; then
  { apt-get update -qq && apt-get install -y -qq shellcheck; } >/dev/null 2>&1 || missing+=("shellcheck")
fi

case "$(git branch --show-current)" in
  master | "") echo "session-start: you are on master or a detached HEAD: cut your own branch before you commit" ;;
esac
if [ ${#missing[@]} -gt 0 ]; then
  echo "session-start: not installed: ${missing[*]}; prepush will show their steps as skipped or failed"
else
  echo "session-start: venv, uv $want, PostgreSQL $major and shellcheck ready; before a push: .venv/bin/python -m tools.prepush"
fi
exit 0
