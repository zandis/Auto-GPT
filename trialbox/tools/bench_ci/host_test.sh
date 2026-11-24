#!/usr/bin/env bash
# The bench CI runner's real-host test (card H-105b; docs/runbook/13-bench-ci-runner.md): install, check, verify,
# remove, on the bench host itself, as one command whose report can be posted on the pull request as it is:
#
#   sudo tools/bench_ci/host_test.sh FOLDER...     FOLDER: each folder a job must never see (typed here, never committed)
#
# It uses no token: it refuses to start when one is installed (its last step removes everything, the token too), and
# no runner is registered. The report names no folder, path or host: each FOLDER is "<folder N>", the settings'
# paths are "<scratch>", "<weights>" and "<card tool>", and the host's name is "<host>". Each step's whole output stays
# in a root-only log folder on the host (its path is printed); the report holds the last lines of a failed step.
set -euo pipefail
umask 077

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROXY_WAIT=90   # seconds the proxy may take to start (the first start makes its network)
PROXY_HOLD=30   # seconds it must then stay up with no restart
passes=0
fails=0
skipped=0
LOG=""
REDACT=()  # pairs: a literal and the word that stands for it in the report

result() {  # result PASS|FAIL|NOT-RUN TEXT
  case "$1" in PASS) passes=$((passes + 1)) ;; FAIL) fails=$((fails + 1)) ;; *) skipped=$((skipped + 1)) ;; esac
  echo "$1 $2" | redact
}

redact() {  # each literal in REDACT, longest first, becomes its stand-in; standard input to standard output
  python3 -I -c '
import sys
pairs = sorted(zip(sys.argv[1::2], sys.argv[2::2]), key=lambda p: -len(p[0]))
for line in sys.stdin:
    for real, word in pairs:
        if real:
            line = line.replace(real, word)
    sys.stdout.write(line)
' "${REDACT[@]}"
}

tail_of() {  # the last lines of a step's log, redacted, indented
  tail -n 25 "$LOG/$1.log" | redact | sed 's/^/    | /'
}

step() {  # step NAME COMMAND...: the command's output goes to its log; PASS when it succeeds
  local name="$1"
  shift
  if "$@" >"$LOG/$name.log" 2>&1; then
    result PASS "$name"
  else
    result FAIL "$name (exit $?); its last lines:"
    tail_of "$name"
  fi
}

proxy_holds() {  # the proxy starts within PROXY_WAIT and then runs PROXY_HOLD seconds with no restart
  local waited=0
  until systemctl is-active --quiet tb-bench-proxy.service; do
    [ "$waited" -lt "$PROXY_WAIT" ] || return 1
    sleep 5
    waited=$((waited + 5))
  done
  local before
  before="$(systemctl show -p NRestarts --value tb-bench-proxy.service)"
  sleep "$PROXY_HOLD"
  systemctl is-active --quiet tb-bench-proxy.service &&
    [ "$(systemctl show -p NRestarts --value tb-bench-proxy.service)" = "$before" ]
}

units_name_no_runtime_folder() {  # the walk's red: a system unit's %U is 0, so no unit sets the runtime folder
  ! grep -q XDG_RUNTIME_DIR /etc/systemd/system/tb-bench-proxy.service /etc/systemd/system/tb-bench-runner@.service
}

proxy_runtime_is_its_users() {  # the running proxy's engine reads the tb-bench user's own runtime folder
  local pid uid
  pid="$(systemctl show -p MainPID --value tb-bench-proxy.service)"
  uid="$(id -u tb-bench)"
  [ "$pid" != 0 ] && tr '\0' '\n' <"/proc/$pid/environ" | grep -qx "XDG_RUNTIME_DIR=/run/user/$uid"
}

proxy_container_runs() {  # as the tb-bench user, in its own store: the network and the running proxy container
  as_tb "$ENGINE" network exists tb-bench-egress &&
    [ "$(as_tb "$ENGINE" container inspect --format '{{.State.Running}}' tb-bench-proxy)" = true ]
}

nothing_left() {  # after remove: no user, no units, no files, and no process of the user's old id
  ! id tb-bench >/dev/null 2>&1 && [ ! -e /etc/tb-bench-ci ] && [ ! -e /opt/tb-bench-ci ] &&
    [ ! -e /var/lib/tb-bench ] && [ ! -e /etc/systemd/system/tb-bench-proxy.service ] &&
    [ ! -e /etc/systemd/system/tb-bench-runner@.service ] && ! pgrep -U "$OLD_UID" >/dev/null
}

journal_of_proxy() {  # on a failed proxy step: its last journal lines, redacted
  journalctl -u tb-bench-proxy.service -n 30 --no-pager >"$LOG/proxy-journal.log" 2>&1 || true
  tail_of proxy-journal
}

main() {
  [ "$(id -u)" = 0 ] || { echo "host test: run as root (sudo)" >&2; exit 1; }
  [ "$#" -gt 0 ] || { echo "host test: name at least one folder a job must never see" >&2; exit 2; }
  # shellcheck source=tools/bench_ci/install.sh
  source "$SRC/install.sh"  # the steps' own functions (as_tb, get) and paths; it runs nothing when read
  umask 077  # install.sh sets its own
  if [ -e "$TOKEN" ]; then
    echo "host test: a token is installed; this test ends by removing everything, the token too. Run it before the" >&2
    echo "host test: token step, or run 'sudo $SRC/install.sh remove' first" >&2
    exit 2
  fi
  LOG="$(mktemp -d /var/tmp/tb-bench-host-test.XXXXXX)"
  local n=0 f
  for f in "$@"; do n=$((n + 1)); REDACT+=("$f" "<folder $n>"); done
  REDACT+=("$(hostname -f 2>/dev/null || true)" "<host>" "$(hostname)" "<host>")
  if [ -f "$SETTINGS" ]; then
    local key word
    for key in BENCH_SCRATCH:scratch BENCH_WEIGHTS:weights BENCH_GPU_QUERY:"card tool"; do
      word="${key#*:}"
      REDACT+=("$(get "${key%%:*}" 2>/dev/null || true)" "<$word>")
    done
  fi
  echo "host test: the bench CI runner, on this host, $(date -u +%Y-%m-%dT%H:%MZ); commit $(git -C "$SRC" rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "host test: $(. /etc/os-release && echo "$ID $VERSION_ID"); service manager $(systemctl --version | awk 'NR==1{print $2}')"
  step "install" "$SRC/install.sh" install
  if grep -q "unbound variable" "$LOG/install.log"; then
    result FAIL "install ended with an unbound variable"
  else
    result PASS "install ended with no unbound variable"
  fi
  ENGINE="$(get BENCH_ENGINE 2>/dev/null || echo /usr/bin/podman)"
  echo "host test: engine $("$ENGINE" --version 2>/dev/null | head -n 1)"
  step "no unit names a runtime folder (a system unit's %U is 0)" units_name_no_runtime_folder
  if proxy_holds >"$LOG/proxy.log" 2>&1; then
    result PASS "the egress proxy starts and runs ${PROXY_HOLD}s with no restart"
  else
    result FAIL "the egress proxy starts and runs ${PROXY_HOLD}s with no restart; its journal:"
    journal_of_proxy
  fi
  step "the proxy's engine reads the tb-bench user's own runtime folder" proxy_runtime_is_its_users
  step "as tb-bench: the egress network exists and the proxy container runs" proxy_container_runs
  echo "host test: verify (its own lines, then its result):"
  if "$SRC/install.sh" verify "$@" >"$LOG/verify.log" 2>&1; then
    redact <"$LOG/verify.log" | sed 's/^/    /'
    result PASS "verify"
  else
    redact <"$LOG/verify.log" | sed 's/^/    /'
    result FAIL "verify"
  fi
  result NOT-RUN "a job on a registered runner (no token is used by this test)"
  OLD_UID="$(id -u tb-bench 2>/dev/null || echo none)"
  step "remove" "$SRC/install.sh" remove
  if [ "$OLD_UID" = none ]; then
    result FAIL "nothing of the runner is left after remove (the user was never made)"
  else
    step "nothing of the runner is left after remove" nothing_left
  fi
  echo "host test: $passes passed, $fails failed, $skipped not run; whole logs (root's, on this host): $LOG" | redact
  [ "$fails" = 0 ]
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then main "$@"; fi
