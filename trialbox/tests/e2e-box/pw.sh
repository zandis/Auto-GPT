#!/bin/bash
# pw.sh SCRIPT.js ARGS... : run a browser driver of pw/ in the Playwright container (the host lacks the browser's
# libraries). E2E_NODE_MODULES holds the playwright package (read-only); the run folder $OUT is the only writable mount.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
NM=${E2E_NODE_MODULES:?a node_modules folder with the playwright package}
PB=$(cat "${E2E_VMS:-/dev/shm/e2e-box}/$NAME/portbase")
# the console answers only to its TLS name (Caddy's site block): the site answers' tls_hostname
TBH=${TB_HOSTNAME:-$NAME.local}
export TB_URL=${TB_URL:-https://$TBH:$((PB + 1))} E2E_OUT=$OUT
exec docker run --rm -i --network host --add-host "$TBH:127.0.0.1" --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e TB_URL -e VARS_FILE -e E2E_OUT -e NODE_PATH="$NM" -v "$OUT:$OUT" -v "$NM:$NM:ro" -v "$HERE/pw:$HERE/pw:ro" -w "$HERE/pw" \
  mcr.microsoft.com/playwright:v1.65.1-noble node "$@"
