#!/usr/bin/env bash
# The bench CI runner on the bench host (card H-105): install, give the token, verify, remove.
# The page: docs/runbook/13-bench-ci-runner.md (RUNBOOK §13 part). Run as root (sudo), from a checkout of master:
#
#   sudo tools/bench_ci/install.sh install          after /etc/tb-bench-ci/settings.env is filled in (the example:
#                                                   tools/bench_ci/settings.example.env)
#   sudo tools/bench_ci/install.sh token            the minting token, typed or pasted on standard input (not shown,
#                                                   never an argument, never in the environment or the journal)
#   sudo tools/bench_ci/install.sh verify PATH...   PATH: each folder a job must never see (typed here, never committed)
#   sudo tools/bench_ci/install.sh remove           everything this script made, and the token
#
# The harms (the page names them): a public repository's self-hosted runner runs strangers' code if a fork-reachable
# trigger reaches it (the workflow's part, tested); a job that escapes its container reaches the owner's data and keys
# (so: the tb-bench user with no group, a rootless engine, one scratch folder); a leaked token lets another machine
# join as a runner (so: a root-only file, handed to the units as a systemd credential).
set -euo pipefail
umask 022

ETC=/etc/tb-bench-ci
SETTINGS="$ETC/settings.env"
TOKEN="$ETC/token"
OPT=/opt/tb-bench-ci
UNITS=/etc/systemd/system
USER_NAME=tb-bench
HOME_DIR=/var/lib/tb-bench
ID_RANGE=262144
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FILES=(__init__.py launcher.py gpu_check.py)
IMAGE_FILES=(runner.Dockerfile entrypoint.sh job_started.sh probe.sh gpu_check.py egress_proxy.py)

die() { echo "bench CI install: $*" >&2; exit 1; }
say() { echo "bench CI install: $*"; }
need_root() { [ "$(id -u)" = 0 ] || die "run as root (sudo)"; }
launcher() { (cd "$SRC/../.." && python3 -s -E -m tools.bench_ci.launcher "$@"); }  # from the checkout
get() { launcher get --settings "$SETTINGS" "$1"; }
uid_of() { id -u "$USER_NAME"; }
as_tb() {  # run a command as tb-bench, in its home, with its own runtime folder (the rootless engine's)
  (cd "$HOME_DIR" && runuser -u "$USER_NAME" -- env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME="$HOME_DIR" \
    XDG_RUNTIME_DIR="/run/user/$(uid_of)" "$@")
}
as_tb_launcher() {  # the installed launcher, as tb-bench
  (cd "$OPT" && runuser -u "$USER_NAME" -- env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME="$HOME_DIR" \
    XDG_RUNTIME_DIR="/run/user/$(uid_of)" python3 -s -E -m tools.bench_ci.launcher "$@")
}
slots() {  # every slot unit the settings ask for
  local n
  for kind in cpu engine gpu; do
    n="$(get "BENCH_${kind^^}_SLOTS")"
    for ((i = 1; i <= n; i++)); do echo "tb-bench-runner@$kind-$i.service"; done
  done
}

prerequisites() {
  local missing=() cmd
  for cmd in systemctl loginctl runuser python3 curl sha256sum useradd usermod userdel newuidmap newgidmap tar; do
    command -v "$cmd" >/dev/null || missing+=("$cmd")
  done
  [ "${#missing[@]}" = 0 ] || die "missing on this host: ${missing[*]}"
  python3 -I -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "python3 is older than 3.10"
  [ "$(systemctl --version | awk 'NR==1{print $2}')" -ge 248 ] || die "systemd is older than 248 (credentials)"
  [ -f "$SETTINGS" ] || die "no $SETTINGS: copy tools/bench_ci/settings.example.env there and fill it in"
  chown root:root "$SETTINGS" && chmod 0600 "$SETTINGS"
  get BENCH_REPO >/dev/null || die "the settings are not complete (the line above says what)"
  local engine
  engine="$(get BENCH_ENGINE)"
  [ -x "$engine" ] || die "the container engine $engine is not installed"
  local ver
  ver="$("$engine" --version | grep -oE '[0-9]+\.[0-9]+' | head -n 1)"
  python3 -I -c 'import sys; a, b = map(int, sys.argv[1].split(".")); sys.exit((a, b) < (4, 4))' "$ver" ||
    die "the container engine is $ver: 4.4 or newer is needed (keep-id with a user)"
  if [ "$(get BENCH_GPU_SLOTS)" -gt 0 ]; then
    [ -x "$(get BENCH_GPU_QUERY)" ] || die "the card query tool $(get BENCH_GPU_QUERY) is not there"
  fi
  say "prerequisites: present"
}

make_user() {
  if ! id "$USER_NAME" >/dev/null 2>&1; then
    useradd --system --user-group --create-home --home-dir "$HOME_DIR" --shell /usr/sbin/nologin "$USER_NAME"
  fi
  [ "$(id -nG "$USER_NAME")" = "$USER_NAME" ] || die "$USER_NAME is in another group ($(id -nG "$USER_NAME")): it must not be"
  chmod 0700 "$HOME_DIR"
  if ! grep -q "^$USER_NAME:" /etc/subuid || ! grep -q "^$USER_NAME:" /etc/subgid; then
    local start
    start="$(awk -F: 'BEGIN { m = 1000000 } { e = $2 + $3; if (e > m) m = e } END { print m }' /etc/subuid /etc/subgid)"
    usermod --add-subuids "$start-$((start + ID_RANGE - 1))" --add-subgids "$start-$((start + ID_RANGE - 1))" "$USER_NAME"
  fi
  loginctl enable-linger "$USER_NAME"
  for _ in $(seq 30); do [ -d "/run/user/$(uid_of)" ] && break; sleep 1; done
  [ -d "/run/user/$(uid_of)" ] || die "no runtime folder for $USER_NAME after enabling linger"
  say "user $USER_NAME: no login, no other group, its own id range, lingering"
}

install_files() {
  install -d -m 0755 -o root -g root "$OPT" "$OPT/tools" "$OPT/tools/bench_ci"
  install -m 0644 -o root -g root /dev/null "$OPT/tools/__init__.py"
  for f in "${FILES[@]}"; do install -m 0644 -o root -g root "$SRC/$f" "$OPT/tools/bench_ci/$f"; done
  install -m 0644 -o root -g root "$SRC/tb-bench-proxy.service" "$UNITS/tb-bench-proxy.service"
  install -m 0644 -o root -g root "$SRC/tb-bench-runner@.service" "$UNITS/tb-bench-runner@.service"
  install -d -m 0750 -o root -g "$USER_NAME" "$ETC"
  chown root:"$USER_NAME" "$SETTINGS" && chmod 0640 "$SETTINGS"
  local scratch
  scratch="$(get BENCH_SCRATCH)"
  case "$scratch" in /|/home|/home/*|/root|/root/*|/etc|/etc/*|/var/lib/tb-bench*) die "scratch $scratch is not a folder of its own" ;; esac
  if [ -e "$scratch" ]; then
    [ "$(stat -c %U "$scratch")" = "$USER_NAME" ] || [ -z "$(ls -A "$scratch")" ] || die "scratch $scratch is in use by another owner"
  fi
  install -d -m 0700 -o "$USER_NAME" -g "$USER_NAME" "$scratch"
  say "files in $OPT, units in $UNITS, settings $SETTINGS (root:$USER_NAME 0640), scratch $scratch (0700)"
}

build_image() {
  local ver sha ctx engine
  ver="$(get BENCH_RUNNER_VERSION)"
  sha="$(get BENCH_RUNNER_SHA256)"
  engine="$(get BENCH_ENGINE)"
  ctx="$(mktemp -d)"
  trap 'rm -rf "$ctx"' RETURN
  curl -fsSL --proto '=https' -o "$ctx/actions-runner.tar.gz" \
    "https://github.com/actions/runner/releases/download/v$ver/actions-runner-linux-x64-$ver.tar.gz"
  echo "$sha  $ctx/actions-runner.tar.gz" | sha256sum -c --quiet - || die "the runner archive's SHA-256 is not the settings'"
  for f in "${IMAGE_FILES[@]}"; do cp "$SRC/$f" "$ctx/$f"; done
  chown -R "$USER_NAME:$USER_NAME" "$ctx"
  as_tb "$engine" build --pull=always -f "$ctx/runner.Dockerfile" -t "$(get BENCH_IMAGE)" "$ctx"
  say "image $(get BENCH_IMAGE) built (runner $ver, SHA-256 checked)"
}

make_networks() {
  local engine
  engine="$(get BENCH_ENGINE)"
  as_tb "$engine" network exists tb-bench-jobs || as_tb "$engine" network create --internal tb-bench-jobs >/dev/null
  as_tb "$engine" network exists tb-bench-egress || as_tb "$engine" network create tb-bench-egress >/dev/null
  [ "$(as_tb "$engine" network inspect tb-bench-jobs --format '{{.Internal}}')" = true ] ||
    die "the network tb-bench-jobs exists and is not internal: remove it and run install again"
  say "networks: tb-bench-jobs (internal, no route out), tb-bench-egress (the proxy's only)"
}

start_units() {
  systemctl daemon-reload
  systemctl enable --now tb-bench-proxy.service
  if [ ! -s "$TOKEN" ]; then
    say "no token yet: run 'sudo $0 token', which starts the runners"
    return 0
  fi
  local unit
  while read -r unit; do systemctl enable --now "$unit"; done < <(slots)
  say "runners started: $(slots | tr '\n' ' ')"
}

cmd_install() {
  need_root
  prerequisites
  make_user
  install_files
  build_image
  make_networks
  start_units
  say "installed. Next: 'sudo $0 token' (if not given yet), then 'sudo $0 verify <each folder a job must not see>'"
}

cmd_token() {
  need_root
  [ -d "$ETC" ] || die "run '$0 install' first"
  local tok=""
  if [ -t 0 ]; then
    printf 'bench CI install: paste the minting token, then Enter (it is not shown): ' >&2
    IFS= read -rs tok
    echo >&2
  else
    IFS= read -r tok || true
  fi
  [ -n "$tok" ] || die "no token was given"
  local tmp
  tmp="$(umask 077 && mktemp "$ETC/.token.XXXXXX")"
  printf '%s\n' "$tok" > "$tmp"
  tok=""
  chown root:root "$tmp" && chmod 0600 "$tmp" && mv -f "$tmp" "$TOKEN"
  say "token kept in a root-only file (0600); it is never printed"
  start_units
  local unit
  while read -r unit; do systemctl restart "$unit"; done < <(slots)
}

cmd_verify() {
  need_root
  local fails=0 p unit
  check() {  # check NAME COMMAND...: PASS when the command succeeds
    local name="$1"
    shift
    if "$@" >/dev/null 2>&1; then echo "PASS $name"; else echo "FAIL $name"; fails=$((fails + 1)); fi
  }
  not() { ! "$@"; }
  token_mode() { [ "$(stat -c '%U %a' "$TOKEN")" = "root 600" ]; }
  no_group() { [ "$(id -nG "$USER_NAME")" = "$USER_NAME" ]; }
  sees() { as_tb test -r "$1" || as_tb test -w "$1"; }
  check "the token file is root's, mode 0600" token_mode
  check "$USER_NAME is in no other group" no_group
  check "$USER_NAME cannot read the token file" not as_tb test -r "$TOKEN"
  check "at least one folder a job must never see was named" test "$#" -gt 0
  for p in "$@"; do check "$USER_NAME cannot read or write $p" not sees "$p"; done
  check "the egress proxy runs" systemctl is-active --quiet tb-bench-proxy.service
  while read -r unit; do check "$unit runs" systemctl is-active --quiet "$unit"; done < <(slots)
  if [ "$(get BENCH_GPU_SLOTS)" -gt 0 ]; then
    check "the CI cards are free" as_tb_launcher check --settings "$SETTINGS"
  fi
  echo "the job container probe (each line PASS or FAIL):"
  if as_tb_launcher probe --settings "$SETTINGS"; then echo "PASS the probe"; else echo "FAIL the probe"; fails=$((fails + 1)); fi
  echo "verify: $fails failure(s)"
  [ "$fails" = 0 ]
}

cmd_remove() {
  need_root
  local engine="" scratch="" unit
  if [ -f "$SETTINGS" ]; then engine="$(get BENCH_ENGINE || true)"; scratch="$(get BENCH_SCRATCH || true)"; fi
  while read -r unit; do
    if [ -n "$unit" ]; then systemctl disable --now "$unit" || true; fi
  done < <(systemctl list-units --all --plain --no-legend 'tb-bench-runner@*' | awk '{print $1}')
  systemctl disable --now tb-bench-proxy.service 2>/dev/null || true
  rm -f "$UNITS/tb-bench-runner@.service" "$UNITS/tb-bench-proxy.service"
  systemctl daemon-reload
  systemctl reset-failed 2>/dev/null || true
  if id "$USER_NAME" >/dev/null 2>&1 && [ -n "$engine" ] && [ -x "$engine" ]; then
    as_tb "$engine" rm --all --force >/dev/null 2>&1 || true
    if [ -n "$scratch" ] && [ -d "$scratch" ]; then as_tb "$engine" unshare rm -rf --one-file-system "$scratch" || true; fi
    as_tb "$engine" network rm --force tb-bench-jobs tb-bench-egress >/dev/null 2>&1 || true
    as_tb "$engine" system reset --force >/dev/null 2>&1 || true
  fi
  if [ -n "$scratch" ] && [ -d "$scratch" ]; then rm -rf --one-file-system "$scratch"; fi
  if [ -f "$TOKEN" ]; then shred -u "$TOKEN" 2>/dev/null || rm -f "$TOKEN"; fi
  rm -rf "$ETC" "$OPT"
  if id "$USER_NAME" >/dev/null 2>&1; then
    loginctl disable-linger "$USER_NAME" || true
    loginctl terminate-user "$USER_NAME" 2>/dev/null || true
    userdel --remove "$USER_NAME" 2>/dev/null || userdel "$USER_NAME"
  fi
  sed -i "/^$USER_NAME:/d" /etc/subuid /etc/subgid
  rm -rf "$HOME_DIR"
  local left=0
  for p in "$ETC" "$OPT" "$HOME_DIR" "$UNITS/tb-bench-runner@.service" "$UNITS/tb-bench-proxy.service"; do
    [ ! -e "$p" ] || { echo "LEFT $p"; left=1; }
  done
  ! id "$USER_NAME" >/dev/null 2>&1 || { echo "LEFT the user $USER_NAME"; left=1; }
  ! grep -q "^$USER_NAME:" /etc/subuid /etc/subgid || { echo "LEFT $USER_NAME's id range"; left=1; }
  say "removed from this host. Still to do by the owner, on the code host: Settings, Actions, Runners: remove any"
  say "runner named tb-bench-*; and revoke the minting token where it was made."
  [ "$left" = 0 ]
}

case "${1:-}" in
  install) cmd_install ;;
  token) cmd_token ;;
  verify) shift; cmd_verify "$@" ;;
  remove) cmd_remove ;;
  *) echo "usage: sudo $0 install | token | verify FOLDER... | remove" >&2; exit 2 ;;
esac
