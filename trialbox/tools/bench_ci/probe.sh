#!/usr/bin/env bash
# The install's verify step (card H-105): run in a job container with one profile's arguments exactly
# (launcher.py probe --profile P, for each profile that has slots). Each line says PASS or FAIL; any FAIL exits 1.
set -uo pipefail
fails=0
check() {  # check NAME COMMAND...: PASS when the command succeeds
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then echo "PASS $name"; else echo "FAIL $name"; fails=$((fails + 1)); fi
}
not() { ! "$@"; }
profile="${BENCH_PROFILE:-cpu}"
echo "probe: the $profile profile"
check "runs as a user that is not root" not test "$(id -u)" = 0
for sock in /var/run/docker.sock /run/docker.sock /run/podman/podman.sock /run/containerd/containerd.sock; do
  check "no engine socket at $sock" not test -e "$sock"
done
check "no engine socket anywhere under /run" not sh -c 'find /run /var/run -type s 2>/dev/null | grep -q .'
# every mount is the container's own, except this job's scratch folder (and, for a GPU job, the weights, read-only)
own='^(/|/proc(/.*)?|/sys(/.*)?|/dev(/.*)?|/tmp|/var/tmp|/run|/scratch|/weights|/etc/(hosts|hostname|resolv\.conf)|/run/\.containerenv|/run/secrets)$'
check "no host folder but /scratch (and /weights for a GPU job)" not sh -c "awk '{print \$2}' /proc/self/mounts | grep -Ev '$own' | grep -q ."
check "the root is read-only" not touch /probe-write
if [ "$profile" = gpu ]; then check "the weights are read-only" not touch /weights/probe-write; fi
check "no fuse or tun device" not sh -c 'test -e /dev/fuse || test -e /dev/net/tun'
caps="$(awk '/^CapEff:/ {print $2}' /proc/self/status)"
case "$profile" in
  cpu) check "no capability at all" test "$caps" = 0000000000000000 ;;
  *) check "only the set-id pair (the nested engine's id mapping)" test "$caps" = 00000000000000c0 ;;
esac
check "no name service (every name goes through the proxy)" not getent hosts github.com
check "no direct way out (the proxy is the only one)" not curl --noproxy '*' -sS -m 8 -o /dev/null https://github.com
check "the code host through the proxy" curl -sS -m 20 -o /dev/null https://github.com
check "the package registry through the proxy" curl -sS -m 20 -o /dev/null https://pypi.org/simple/
check "a host off the allow-list is refused" not curl -sS -m 20 -o /dev/null https://example.com
check "the code host's upload host is refused" not curl -sS -m 20 -o /dev/null https://uploads.github.com
check "an address written as a number is refused" not curl -sS -m 20 -o /dev/null https://192.0.2.1
echo "probe: $fails failure(s)"
[ "$fails" = 0 ]
