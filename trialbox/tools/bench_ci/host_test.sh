#!/usr/bin/env bash
# The bench CI runner's real-host test (card H-105b; docs/runbook/13-bench-ci-runner.md): install, check, verify,
# remove, on the bench host itself, as one command whose report can be posted on the pull request as it is:
#
#   sudo tools/bench_ci/host_test.sh FOLDER...     FOLDER: each folder a job must never see (typed here, never committed)
#
# It uses no token: it refuses to start when one is installed, and no runner is registered. When the install step
# fails, nothing after it runs, remove least of all (OCR 1466-2): the report says what to read. remove takes away only
# what install recorded that it made; the operator's settings stay. The report names no folder, path, user, address or
# host: each FOLDER is "<folder N>", the settings' paths "<scratch>", "<weights>" and "<card tool>", the checkout
# "<checkout>", the operator "<user>" and "<home>", the host "<host>", an address "<address>". Each step's whole output
# stays in a root-only log folder on the host; the report holds the last lines of a failed step.
set -euo pipefail
umask 077

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROXY_WAIT=90   # seconds the proxy may take to start (the first start makes its network)
PROXY_HOLD=30   # seconds it must then stay up with no restart
passes=0
fails=0
skipped=0
LOG=""
LAST_LOG=""  # the log of the last step
NOW="starting"  # the step that runs, for the interrupt's line
REDACT=()  # pairs: a literal and the word that stands for it in the report

result() {  # result PASS|FAIL|NOT-RUN TEXT
  case "$1" in PASS) passes=$((passes + 1)) ;; FAIL) fails=$((fails + 1)) ;; *) skipped=$((skipped + 1)) ;; esac
  echo "$1 $2" | redact
}

redact() {  # each literal in REDACT, longest first, then every address, becomes its stand-in (standard in to out)
  python3 -I -c '
import re, sys
pairs = sorted(zip(sys.argv[1::2], sys.argv[2::2]), key=lambda p: -len(p[0]))
addr = re.compile(r"(?<![\w.:])(\d{1,3}(\.\d{1,3}){3}|[0-9A-Fa-f]{0,4}(:[0-9A-Fa-f]{0,4}){2,7})(/\d{1,3})?(?![\w.:])")


def address(m):  # an IPv6 form has "::" or at least four colons (a time of day such as 11:12:28 has two)
    s = m.group(1)
    return "<address>" if "." in s or "::" in s or s.count(":") >= 4 else m.group(0)


for line in sys.stdin:
    for real, word in pairs:
        if real:
            line = line.replace(real, word)
    sys.stdout.write(addr.sub(address, line))
' "${REDACT[@]}"
}

tail_of() {  # the last lines of a log, redacted, indented
  tail -n 25 "$1" | redact | sed 's/^/    | /'
}

step() {  # step NAME COMMAND...: the command's output goes to its log; PASS when it succeeds
  local name="$1" log
  shift
  NOW="$name"
  log="$LOG/step-$((passes + fails + skipped + 1)).log"  # numbered: a step's name may hold a "/" (OCR 1466-1)
  LAST_LOG="$log"
  if "$@" >"$log" 2>&1; then
    result PASS "$name"
  else
    result FAIL "$name (exit $?); its last lines:"
    tail_of "$log"
  fi
}

interrupted() {  # INT, TERM or HUP: nothing more runs; the report says where it stopped and what is still there
  trap - INT TERM HUP
  echo "host test: interrupted during: $NOW. Nothing more is run. If the install step passed, the runner is still" | redact
  echo "host test: installed: run 'sudo trialbox/tools/bench_ci/install.sh remove' (it takes only what install made)"
  echo "host test: $passes passed, $fails failed, $skipped not run (interrupted)"
  exit 130
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
  local unit
  for unit in "$UNITS/tb-bench-proxy.service" "$UNITS/tb-bench-runner@.service"; do
    [ -f "$unit" ] || { echo "$unit is not there"; return 1; }  # OCR 1466-6 (1): no unit is no pass
    ! grep -q XDG_RUNTIME_DIR "$unit" || { echo "$unit names a runtime folder"; return 1; }
  done
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

nothing_left() {  # NAMES_FILE OLD_UID: after remove, nothing install recorded is there, and no process of the user's id
  local list="$1" old_uid="$2" kind name left=0
  [ -s "$list" ] || { echo "no record of what install made"; return 1; }
  while IFS=$'\t' read -r kind name; do
    case "$kind" in
      dir | file) [ ! -e "$name" ] || { echo "left: $name"; left=1; } ;;
      units) [ ! -e "$name/tb-bench-proxy.service" ] && [ ! -e "$name/tb-bench-runner@.service" ] ||
          { echo "left: a unit in $name"; left=1; } ;;
      user) ! id "$name" >/dev/null 2>&1 || { echo "left: the user $name"; left=1; } ;;
      subid) ! grep -q "^$name:" /etc/subuid /etc/subgid 2>/dev/null || { echo "left: $name's id range"; left=1; } ;;
      linger) [ ! -e "/var/lib/systemd/linger/$name" ] || { echo "left: $name's linger"; left=1; } ;;
    esac
  done <"$list"
  if [ "$old_uid" != none ] && pgrep -U "$old_uid" >/dev/null; then echo "left: a process of the user's id"; left=1; fi
  [ "$left" = 0 ]
}

journal_of_proxy() {  # on a failed proxy step: its last journal lines, redacted
  journalctl -u tb-bench-proxy.service -n 30 --no-pager >"$LOG/proxy-journal.log" 2>&1 || true
  tail_of "$LOG/proxy-journal.log"
}

add_redactions() {  # FOLDER...: every name the report must not carry
  local n=0 f
  for f in "$@"; do n=$((n + 1)); REDACT+=("$f" "<folder $n>"); done
  REDACT+=("$(cd "$SRC/../../.." && pwd)" "<checkout>")
  if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ]; then
    REDACT+=("$(getent passwd "$SUDO_USER" | cut -d: -f6)" "<home>" "$SUDO_USER" "<user>")
  fi
  REDACT+=("$(hostname -f 2>/dev/null || true)" "<host>" "$(hostname)" "<host>")
  if [ -f "$SETTINGS" ]; then
    local key word
    for key in BENCH_SCRATCH:scratch BENCH_WEIGHTS:weights BENCH_GPU_QUERY:"card tool"; do
      word="${key#*:}"
      REDACT+=("$(get "${key%%:*}" 2>/dev/null || true)" "<$word>")
    done
  fi
}

main() {
  [ "$(id -u)" = 0 ] || { echo "host test: run as root (sudo)" >&2; exit 1; }
  [ "$#" -gt 0 ] || { echo "host test: name at least one folder a job must never see" >&2; exit 2; }
  # shellcheck source=tools/bench_ci/install.sh
  source "$SRC/install.sh"  # the steps' own functions (as_tb, get) and paths; it runs nothing when read
  umask 077  # install.sh sets its own
  if [ -e "$TOKEN" ]; then
    echo "host test: a token is installed; this test ends by removing what install made, the token too. Run it" >&2
    echo "host test: before the token step, or run 'sudo $SRC/install.sh remove' first" >&2
    exit 2
  fi
  LOG="$(mktemp -d /var/tmp/tb-bench-host-test.XXXXXX)"
  add_redactions "$@"
  trap interrupted INT TERM HUP
  echo "host test: the bench CI runner, on this host, $(date -u +%Y-%m-%dT%H:%MZ); commit $(git -C "$SRC" rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "host test: $(. /etc/os-release && echo "$ID $VERSION_ID"); service manager $(systemctl --version | awk 'NR==1{print $2}')"
  local before=$fails
  step "install" "$SRC/install.sh" install
  if [ "$fails" != "$before" ]; then
    # OCR 1466-2: never remove after a failed install; never verify a half-made one
    result NOT-RUN "the checks, verify and remove: the install failed (its lines above). Read them before anything goes"
    echo "host test: $passes passed, $fails failed, $skipped not run; whole logs (root's, on this host): $LOG" | redact
    return 1
  fi
  if grep -q "unbound variable" "$LAST_LOG"; then
    result FAIL "install ended with an unbound variable"
  else
    result PASS "install ended with no unbound variable"
  fi
  ENGINE="$(get BENCH_ENGINE 2>/dev/null || echo /usr/bin/podman)"
  echo "host test: engine $("$ENGINE" --version 2>/dev/null | head -n 1)"
  step "no unit names a runtime folder (a system unit's %U is 0)" units_name_no_runtime_folder
  step "the folder /var/lib/cni is there (without it the engine hides /var/lib from a user's network)" test -d /var/lib/cni
  NOW="the egress proxy"
  if proxy_holds >"$LOG/proxy.log" 2>&1; then
    result PASS "the egress proxy starts and runs ${PROXY_HOLD}s with no restart"
  else
    result FAIL "the egress proxy starts and runs ${PROXY_HOLD}s with no restart; its journal:"
    journal_of_proxy
  fi
  step "the proxy's engine reads the tb-bench user's own runtime folder" proxy_runtime_is_its_users
  step "as tb-bench: the egress network exists and the proxy container runs" proxy_container_runs
  NOW="verify"
  echo "host test: verify (its own lines, then its result):"
  local verified=0 not_run
  "$SRC/install.sh" verify "$@" >"$LOG/verify.log" 2>&1 || verified=$?
  redact <"$LOG/verify.log" | sed 's/^/    /'
  not_run="$(grep -c '^NOT RUN' "$LOG/verify.log" || true)"
  skipped=$((skipped + not_run))  # OCR 1466-6 (3): verify's own NOT RUN lines count as not run, never as passed
  if [ "$verified" = 0 ]; then result PASS "verify (its $not_run NOT RUN line(s) counted as not run)"; else result FAIL "verify"; fi
  result NOT-RUN "a job on a registered runner (no token is used by this test)"
  local old_uid
  old_uid="$(id -u tb-bench 2>/dev/null || echo none)"
  cp -- "$MADE" "$LOG/made.list" 2>/dev/null || : >"$LOG/made.list"
  step "remove" "$SRC/install.sh" remove
  step "nothing install made is left after remove, and no process of its user" nothing_left "$LOG/made.list" "$old_uid"
  step "the operator's settings are kept" test -f "$SETTINGS"
  trap - INT TERM HUP
  echo "host test: $passes passed, $fails failed, $skipped not run; whole logs (root's, on this host): $LOG" | redact
  [ "$fails" = 0 ]
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then main "$@"; fi
