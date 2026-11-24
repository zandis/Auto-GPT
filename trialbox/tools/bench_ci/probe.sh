#!/usr/bin/env bash
# The install's verify step (card H-105): run in a job container with the cpu profile's arguments exactly
# (launcher.py probe). Each line says PASS or FAIL; any FAIL exits 1.
set -uo pipefail
fails=0
check() {  # check NAME COMMAND...: PASS when the command succeeds
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then echo "PASS $name"; else echo "FAIL $name"; fails=$((fails + 1)); fi
}
not() { ! "$@"; }
check "runs as a user that is not root" not test "$(id -u)" = 0
for sock in /var/run/docker.sock /run/docker.sock /run/podman/podman.sock /run/containerd/containerd.sock; do
  check "no engine socket at $sock" not test -e "$sock"
done
check "no engine socket anywhere under /run" not sh -c 'find /run /var/run -type s 2>/dev/null | grep -q .'
# every mount is the container's own, except this job's scratch folder
own='^(/|/proc(/.*)?|/sys(/.*)?|/dev(/.*)?|/tmp|/scratch|/etc/(hosts|hostname|resolv\.conf)|/run/\.containerenv|/run/secrets)$'
check "no host folder but /scratch" not sh -c "awk '{print \$2}' /proc/self/mounts | grep -Ev '$own' | grep -q ."
check "the root is read-only" not touch /probe-write
check "no direct way out (the proxy is the only one)" not curl --noproxy '*' -sS -m 8 -o /dev/null https://github.com
check "the code host through the proxy" curl -sS -m 20 -o /dev/null https://api.github.com
check "the package registry through the proxy" curl -sS -m 20 -o /dev/null https://pypi.org/simple/
check "a host off the allow-list is refused" not curl -sS -m 20 -o /dev/null https://example.com
check "an address written as a number is refused" not curl -sS -m 20 -o /dev/null https://192.0.2.1
echo "probe: $fails failure(s)"
[ "$fails" = 0 ]
