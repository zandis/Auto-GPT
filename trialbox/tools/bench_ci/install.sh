#!/usr/bin/env bash
# The bench CI runner on the bench host (card H-105): install, give the token, verify, remove.
# The page: docs/runbook/13-bench-ci-runner.md (RUNBOOK §13 part). Run as root (sudo), from a checkout of master:
#
#   sudo tools/bench_ci/install.sh install          after /etc/tb-bench-ci/settings.env is filled in (the example:
#                                                   tools/bench_ci/settings.example.env)
#   sudo tools/bench_ci/install.sh token            the minting token, typed or pasted on standard input (not shown,
#                                                   never an argument, never in the environment or the journal)
#   sudo tools/bench_ci/install.sh verify PATH...   PATH: each folder a job must never see (typed here, never committed)
#   sudo tools/bench_ci/install.sh remove           only what install recorded that it made (the token too); never
#                                                   the settings, nor anything that was there before
#
# The harms (the page names them): a public repository's self-hosted runner runs strangers' code if a fork-reachable
# trigger reaches it (the workflow's part, tested); a job that escapes its container reaches the owner's data and keys
# (so: the tb-bench user with no group, a rootless engine, one scratch folder); a leaked token lets another machine
# join as a runner, and more (so: a root-only file that only the units' root steps read; the jobs' user never can).
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
# The engine (4.9, rootless) mounts an empty folder over the nearest existing folder of /var/lib/cni while it sets up a
# user's own network: without /var/lib/cni that is /var/lib, which hides the user's home and its network files ("network
# not found"; the walk's red, reproduced on the distribution's 4.9.3 with netavark 1.4). An empty root folder there
# keeps /var/lib in sight.
CNI_DIR=/var/lib/cni
HELPER_DIRS=(/usr/lib/podman /usr/libexec/podman)  # where the distributions put the engine's network helpers
# What install made, one "KIND<tab>NAME" line each, recorded before it is made (a cut install leaves a line for a thing
# that is not there, never a thing with no line): remove takes away only these (OCR 1466-2: never a folder or file that
# was there before, such as a scratch folder install refused). Root's, 0600, always written whole (copy, sync, rename).
MADE="$ETC/made"
SUBID_FILES=(/etc/subuid /etc/subgid)
LINGER_DIR=/var/lib/systemd/linger
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FILES=(__init__.py launcher.py gpu_check.py)
IMAGE_FILES=(runner.Dockerfile entrypoint.sh job_started.sh probe.sh gpu_check.py egress_proxy.py gate.py unpack_jit.py)

die() { echo "bench CI install: $*" >&2; exit 1; }
say() { echo "bench CI install: $*"; }
need_root() { [ "$(id -u)" = 0 ] || die "run as root (sudo)"; }
id_ranges_whole() {  # the user has an id range in both files, or in neither
  local f n=0
  for f in "${SUBID_FILES[@]}"; do ! grep -q "^$USER_NAME:" "$f" 2>/dev/null || n=$((n + 1)); done
  [ "$n" != 1 ]
}
unrecorded_pieces() {  # each piece of an install that is here and not in the record, one per line
  # OCR 1466-11 (lane LR's LR-46): an install from before the record, or what a by-hand removal of it left, is not
  # taken by remove, which takes only what the record names; install and the host test refuse to go on over it
  local p
  ! id "$USER_NAME" >/dev/null 2>&1 || was_made user "$USER_NAME" || echo "the user $USER_NAME"
  for p in "$OPT" "$HOME_DIR"; do [ ! -e "$p" ] || was_made dir "$p" || echo "$p"; done
  for p in "$UNITS/tb-bench-proxy.service" "$UNITS/tb-bench-runner@.service"; do
    [ ! -e "$p" ] || was_made units "$UNITS" || echo "$p"
  done
  [ ! -e "$LINGER_DIR/$USER_NAME" ] || was_made linger "$USER_NAME" || echo "$USER_NAME's linger"
  ! grep -qs "^$USER_NAME:" "${SUBID_FILES[@]}" || was_made subid "$USER_NAME" || echo "$USER_NAME's id range"
}
refuse_unrecorded() {  # WHO: stop when unrecorded_pieces names anything
  local pieces
  pieces="$(unrecorded_pieces | paste -sd ';' -)"
  [ -z "$pieces" ] || die "$1: an install with no record is here ($pieces): remove it first (runbook 13, 'Removing a runner installed before H-105b'); remove would leave it"
}
was_made() { [ -f "$MADE" ] && grep -qxF -- "$1"$'\t'"$2" "$MADE"; }
record_made() {  # record_made KIND NAME: before the thing is made
  ! was_made "$1" "$2" || return 0
  local tmp
  tmp="$(mktemp "$ETC/.made.XXXXXX")" || die "the record of what install made cannot be written in $ETC"
  { { [ ! -f "$MADE" ] || cat -- "$MADE"; } && printf '%s\t%s\n' "$1" "$2"; } >"$tmp" &&
    chown root:root "$tmp" && chmod 0600 "$tmp" && sync -- "$tmp" && mv -f -- "$tmp" "$MADE" && sync -- "$ETC" ||
    { rm -f -- "$tmp"; die "the record of what install made could not be written: nothing more is made"; }
}
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
  # newuidmap and newgidmap come with the distribution's uidmap package, which a fresh host lacks (the walk's red)
  # a rootless user's own networks need the engine's network helper for its namespace (either one)
  command -v slirp4netns >/dev/null || command -v pasta >/dev/null || missing+=("slirp4netns or pasta")
  local helper dir found
  for helper in netavark aardvark-dns; do
    found=""
    for dir in "${HELPER_DIRS[@]}"; do [ ! -x "$dir/$helper" ] || found=1; done
    [ -n "$found" ] || command -v "$helper" >/dev/null || missing+=("$helper")
  done
  [ "${#missing[@]}" = 0 ] || die "missing on this host: ${missing[*]} (install them from the distribution first)"
  # OCR 1466-12: an id range in only one of the two files is someone's by-hand line: install would add a second one,
  # and remove would take both; stop before any change and let it be set right by hand
  id_ranges_whole || die "$USER_NAME has an id range in only one of ${SUBID_FILES[*]}: set it right by hand first"
  # L-1448-18: the service manager must be the running init, before anything is changed (users, linger, units)
  [ -d /run/systemd/system ] || die "the service manager is not the running init here: the units cannot run"
  python3 -I -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "python3 is older than 3.10"
  [ "$(systemctl --version | awk 'NR==1{print $2}')" -ge 248 ] || die "the service manager is older than 248"
  [ -f "$SETTINGS" ] || die "no $SETTINGS: copy tools/bench_ci/settings.example.env there and fill it in"
  chown root:root "$SETTINGS" && chmod 0600 "$SETTINGS"
  get BENCH_REPO >/dev/null || die "the settings are not complete (the line above says what)"
  local engine
  engine="$(get BENCH_ENGINE)"
  [ -x "$engine" ] || die "the container engine $engine is not installed (install it from the distribution first)"
  local ver
  ver="$("$engine" --version | grep -oE '[0-9]+\.[0-9]+' | head -n 1)"
  python3 -I -c 'import sys; a, b = map(int, sys.argv[1].split(".")); sys.exit((a, b) < (4, 4))' "$ver" ||
    die "the container engine is $ver: 4.4 or newer is needed (keep-id with a user)"
  if [ "$(get BENCH_GPU_SLOTS)" -gt 0 ]; then
    [ -x "$(get BENCH_GPU_QUERY)" ] || die "the card query tool $(get BENCH_GPU_QUERY) is not there"
    [ -d "$(get BENCH_WEIGHTS)" ] || die "the weights folder $(get BENCH_WEIGHTS) is not there"
  fi
  say "prerequisites: present"
}

make_user() {
  if ! id "$USER_NAME" >/dev/null 2>&1; then
    record_made user "$USER_NAME"
    [ -e "$HOME_DIR" ] || record_made dir "$HOME_DIR"
    useradd --system --user-group --create-home --home-dir "$HOME_DIR" --shell /usr/sbin/nologin "$USER_NAME"
  fi
  [ "$(id -nG "$USER_NAME")" = "$USER_NAME" ] || die "$USER_NAME is in another group ($(id -nG "$USER_NAME")): it must not be"
  chmod 0700 "$HOME_DIR"
  if ! grep -q "^$USER_NAME:" /etc/subuid || ! grep -q "^$USER_NAME:" /etc/subgid; then
    local start
    record_made subid "$USER_NAME"
    start="$(awk -F: 'BEGIN { m = 1000000 } { e = $2 + $3; if (e > m) m = e } END { print m }' /etc/subuid /etc/subgid)"
    usermod --add-subuids "$start-$((start + ID_RANGE - 1))" --add-subgids "$start-$((start + ID_RANGE - 1))" "$USER_NAME"
  fi
  [ -e "$LINGER_DIR/$USER_NAME" ] || record_made linger "$USER_NAME"
  loginctl enable-linger "$USER_NAME"
  for _ in $(seq 30); do [ -d "/run/user/$(uid_of)" ] && break; sleep 1; done
  [ -d "/run/user/$(uid_of)" ] || die "no runtime folder for $USER_NAME after enabling linger"
  say "user $USER_NAME: no login, no other group, its own id range, lingering"
}

install_files() {
  [ -e "$OPT" ] || record_made dir "$OPT"
  [ -e "$UNITS/tb-bench-proxy.service" ] || [ -e "$UNITS/tb-bench-runner@.service" ] || record_made units "$UNITS"
  install -d -m 0755 -o root -g root "$OPT" "$OPT/tools" "$OPT/tools/bench_ci"
  install -m 0644 -o root -g root /dev/null "$OPT/tools/__init__.py"
  for f in "${FILES[@]}"; do install -m 0644 -o root -g root "$SRC/$f" "$OPT/tools/bench_ci/$f"; done
  install -m 0644 -o root -g root "$SRC/tb-bench-proxy.service" "$UNITS/tb-bench-proxy.service"
  install -m 0644 -o root -g root "$SRC/tb-bench-runner@.service" "$UNITS/tb-bench-runner@.service"
  install -d -m 0750 -o root -g "$USER_NAME" "$ETC"
  chown root:"$USER_NAME" "$SETTINGS" && chmod 0640 "$SETTINGS"
  local scratch
  scratch="$(get BENCH_SCRATCH)"
  # OCR 1466-14 (lane LR's LR-49): never a folder install made for itself (the code folder, the CNI folder): "install
  # made it" below skips the owner check, and the folder would be handed to the jobs' user
  case "$scratch" in /|/home|/home/*|/root|/root/*|/etc|/etc/*|"$HOME_DIR"|"$HOME_DIR"/*|"$OPT"|"$OPT"/*|"$CNI_DIR"|"$CNI_DIR"/*) die "scratch $scratch is not a folder of its own" ;; esac
  # OCR 1466-9: a folder that is already there is taken only if install made it, or it is tb-bench's and empty (an
  # earlier install's); never another owner's, even empty: install would hand it to the jobs' user
  if [ -e "$scratch" ] && ! was_made dir "$scratch"; then
    { [ "$(stat -c %U "$scratch")" = "$USER_NAME" ] && [ -z "$(ls -A "$scratch")" ]; } ||
      die "scratch $scratch is in use by another owner: name a folder that is not there yet (install makes it)"
  fi
  # 1448-22: root makes and removes the slots' folders in here: no folder above it may be a link, not root's, or
  # writable by anyone but root, or a link put there sends root elsewhere
  local up="$scratch"
  while [ "$up" != / ]; do
    up="$(dirname "$up")"
    { [ ! -L "$up" ] && [ "$(stat -c %u "$up")" = 0 ] && [ $((0$(stat -c %a "$up") & 022)) = 0 ]; } ||
      die "scratch $scratch: $up must be root's, not a link, and writable by root only"
  done
  [ -e "$scratch" ] || record_made dir "$scratch"
  install -d -m 0700 -o "$USER_NAME" -g "$USER_NAME" "$scratch"
  say "files in $OPT, units in $UNITS, settings $SETTINGS (root:$USER_NAME 0640), scratch $scratch (0700)"
}

build_image() {
  local ver sha ctx engine
  ver="$(get BENCH_RUNNER_VERSION)"
  sha="$(get BENCH_RUNNER_SHA256)"
  engine="$(get BENCH_ENGINE)"
  ctx="$(mktemp -d)"
  # the trap clears itself: a RETURN trap left set fires again when the caller returns, with ctx gone (the walk's
  # "ctx: unbound variable" after "installed")
  trap 'rm -rf -- "$ctx"; trap - RETURN' RETURN
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
  if [ ! -d "$CNI_DIR" ]; then
    record_made dir "$CNI_DIR"  # remove takes it away again if it is still empty
    install -d -m 0755 -o root -g root "$CNI_DIR"
  fi
  as_tb "$engine" network exists tb-bench-egress || as_tb "$engine" network create tb-bench-egress >/dev/null
  say "networks: tb-bench-egress (the proxy's way out); each job gets its own internal network at its start"
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
  refuse_unrecorded install  # before any change
  prerequisites
  [ -e "$TOKEN" ] || record_made file "$TOKEN"  # the token step writes it; remove shreds it
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
  # the temporary copy goes whatever happens (L-1448-11); global, so the trap still sees it after the function ends.
  # A signal ends the step (1448-20): it never goes on to say the token is kept or restart the slots, and every file
  # of the step is made under umask 077, so no copy of the token is ever readable by others
  umask 077
  tmp=""
  trap '[ -z "$tmp" ] || rm -f -- "$tmp"' EXIT
  # 1448-26: a copy gone after it was made means it was moved into place: the token is kept, the restarts were cut
  trap 'if [ -n "$tmp" ] && [ ! -e "$tmp" ]; then echo "bench CI install: interrupted: the new token is kept, but the slots were not all restarted (restart them, or run the token step again)" >&2; else [ -z "$tmp" ] || rm -f -- "$tmp"; echo "bench CI install: interrupted: no token was kept" >&2; fi; trap - EXIT; exit 130' INT TERM HUP
  tmp="$(mktemp "$ETC/.token.XXXXXX")"
  printf '%s\n' "$tok" > "$tmp"
  tok=""
  { chown root:root "$tmp" && chmod 0600 "$tmp" && mv -f "$tmp" "$TOKEN"; } || die "the token could not be kept"
  say "token kept in a root-only file (0600); it is never printed"
  start_units
  local unit
  while read -r unit; do systemctl restart "$unit"; done < <(slots)
}

cmd_verify() {
  need_root
  local fails=0 skipped=0 p unit
  check() {  # check NAME COMMAND...: PASS when the command succeeds
    local name="$1"
    shift
    if "$@" >/dev/null 2>&1; then echo "PASS $name"; else echo "FAIL $name"; fails=$((fails + 1)); fi
  }
  not() { ! "$@"; }
  token_mode() { [ "$(stat -c '%U %a' "$TOKEN")" = "root 600" ]; }
  no_group() { [ "$(id -nG "$USER_NAME")" = "$USER_NAME" ]; }
  sees() { as_tb test -r "$1" || as_tb test -w "$1"; }
  check "$USER_NAME is in no other group" no_group
  # before the token step (the host test's run) there is no token and no runner: said, never passed or failed
  if [ -e "$TOKEN" ]; then
    check "the token file is root's, mode 0600" token_mode
    check "$USER_NAME cannot read the token file" not as_tb test -r "$TOKEN"
  else
    echo "NOT RUN the token file's owner and mode, and that $USER_NAME cannot read it (no token given yet)"
    skipped=$((skipped + 1))
  fi
  check "at least one folder a job must never see was named" test "$#" -gt 0
  for p in "$@"; do check "$USER_NAME cannot read or write $p" not sees "$p"; done
  check "the egress proxy runs" systemctl is-active --quiet tb-bench-proxy.service
  if [ -s "$TOKEN" ]; then
    while read -r unit; do check "$unit runs" systemctl is-active --quiet "$unit"; done < <(slots)
  else
    echo "NOT RUN the runner slots run (no token given yet: none is started)"
    skipped=$((skipped + 1))
  fi
  if [ "$(get BENCH_GPU_SLOTS)" -gt 0 ]; then
    check "the CI cards are free" as_tb_launcher check --settings "$SETTINGS"
    check "$USER_NAME cannot write the weights folder" not as_tb test -w "$(get BENCH_WEIGHTS)"
  fi
  check "no unit holds a copy of the token (no credential of the service manager)" not grep -q LoadCredential "$UNITS/tb-bench-runner@.service"
  local profile
  for profile in cpu engine gpu; do
    [ "$(get "BENCH_${profile^^}_SLOTS")" -gt 0 ] || continue
    echo "the job container probe, $profile profile (each line PASS or FAIL):"
    if as_tb_launcher probe --settings "$SETTINGS" --profile "$profile"; then echo "PASS the $profile probe"; else echo "FAIL the $profile probe"; fails=$((fails + 1)); fi
  done
  echo "verify: $fails failure(s), $skipped not run"
  [ "$fails" = 0 ]
}

cmd_remove() {
  need_root
  # OCR 1466-2: only what install recorded that it made goes; what was there before stays (the operator's settings,
  # a folder of another owner named as scratch by a slip, a user or folder of the same name)
  local engine="" scratch="" unit kind name
  if [ ! -f "$MADE" ]; then
    say "no record of what install made ($MADE): the units are stopped; only the token and its copies go"
  fi
  if [ -f "$SETTINGS" ]; then engine="$(get BENCH_ENGINE || true)"; scratch="$(get BENCH_SCRATCH || true)"; fi
  # OCR 1466-18 (lane LR's LR-66): today's settings may name the CNI folder by a slip made after install; it is
  # never a scratch folder (install refuses it), so it goes only by its own rule below: when it is empty
  if [ -n "$scratch" ] && [ "$scratch" = "$CNI_DIR" ]; then say "scratch $scratch is the CNI folder: not taken as scratch"; scratch=""; fi
  while read -r unit; do
    if [ -n "$unit" ]; then systemctl disable --now "$unit" || true; fi
  done < <(systemctl list-units --all --plain --no-legend 'tb-bench-runner@*' | awk '{print $1}')
  systemctl disable --now tb-bench-proxy.service 2>/dev/null || true
  if was_made units "$UNITS"; then rm -f "$UNITS/tb-bench-runner@.service" "$UNITS/tb-bench-proxy.service"; fi
  systemctl daemon-reload
  systemctl reset-failed 2>/dev/null || true
  if was_made user "$USER_NAME" && id "$USER_NAME" >/dev/null 2>&1 && [ -n "$engine" ] && [ -x "$engine" ]; then
    as_tb "$engine" rm --all --force >/dev/null 2>&1 || true
    if [ -n "$scratch" ] && was_made dir "$scratch" && [ -d "$scratch" ]; then
      as_tb "$engine" unshare rm -rf --one-file-system "$scratch" || true
    fi
    as_tb "$engine" network ls --quiet --filter name=tb-bench | while read -r net; do
      as_tb "$engine" network rm --force "$net" >/dev/null 2>&1 || true
    done
    as_tb "$engine" system reset --force >/dev/null 2>&1 || true
  fi
  if [ -n "$scratch" ] && [ -d "$scratch" ]; then
    if was_made dir "$scratch"; then rm -rf --one-file-system "$scratch"; else say "scratch $scratch is kept: install did not make it"; fi
  fi
  # OCR 1466-15 (lane LR's LR-47): the token and any copy a cut token step left are the token step's own files, never
  # the operator's: shredded whenever they are there, recorded or not (a token given before the first install)
  if [ -f "$TOKEN" ]; then shred -u "$TOKEN" 2>/dev/null || rm -f "$TOKEN"; fi
  local tok
  for tok in "$ETC"/.token.*; do
    if [ -f "$tok" ]; then shred -u "$tok" 2>/dev/null || rm -f "$tok"; fi
  done
  if was_made dir "$CNI_DIR" && [ -d "$CNI_DIR" ]; then
    rmdir "$CNI_DIR" 2>/dev/null || say "$CNI_DIR is left: something else has put files in it"
  fi
  if was_made dir "$OPT"; then rm -rf "$OPT"; fi
  if was_made user "$USER_NAME" && id "$USER_NAME" >/dev/null 2>&1; then
    if was_made linger "$USER_NAME"; then loginctl disable-linger "$USER_NAME" || true; fi
    loginctl terminate-user "$USER_NAME" 2>/dev/null || true
    if was_made dir "$HOME_DIR"; then userdel --remove "$USER_NAME" 2>/dev/null || userdel "$USER_NAME"; else userdel "$USER_NAME"; fi
  fi
  if was_made subid "$USER_NAME"; then sed -i "/^$USER_NAME:/d" /etc/subuid /etc/subgid; fi
  if was_made dir "$HOME_DIR"; then rm -rf "$HOME_DIR"; fi
  if ! id "$USER_NAME" >/dev/null 2>&1 && [ -d "$ETC" ]; then  # the settings go back to root's own (no group left)
    chown root:root "$ETC" && chmod 0750 "$ETC"
    if [ -f "$SETTINGS" ]; then chown root:root "$SETTINGS" && chmod 0600 "$SETTINGS"; fi
  fi
  local left=0
  if [ ! -f "$MADE" ]; then
    say "nothing was deleted (no record) but the token and its copies (shredded): stopped only. The owner decides what of an earlier install goes"
    return 1
  else
    while IFS=$'\t' read -r kind name; do
      case "$kind" in
        dir | file) [ ! -e "$name" ] || [ "$name" = "$CNI_DIR" ] || { echo "LEFT $name"; left=1; } ;;
        units) for unit in tb-bench-runner@.service tb-bench-proxy.service; do
            [ ! -e "$name/$unit" ] || { echo "LEFT $name/$unit"; left=1; }
          done ;;
        user) ! id "$name" >/dev/null 2>&1 || { echo "LEFT the user $name"; left=1; } ;;
        subid) ! grep -q "^$name:" /etc/subuid /etc/subgid 2>/dev/null || { echo "LEFT $name's id range"; left=1; } ;;
        linger) [ ! -e "/var/lib/systemd/linger/$name" ] || { echo "LEFT $name's linger"; left=1; } ;;
      esac
    done <"$MADE"
    if [ "$left" = 0 ]; then rm -f "$MADE"; fi  # kept while anything is left, so remove can be run again
  fi
  say "kept: $SETTINGS (the operator's), and anything install did not make"
  say "removed from this host. Still to do by the owner, on the code host: Settings, Actions, Runners: remove any"
  say "runner named tb-bench-*; and revoke the minting token where it was made."
  [ "$left" = 0 ]
}

# run as a command; read with "source" (the tests, the host test), it only defines the steps
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  case "${1:-}" in
    install) cmd_install ;;
    token) cmd_token ;;
    verify) shift; cmd_verify "$@" ;;
    remove) cmd_remove ;;
    *) echo "usage: sudo $0 install | token | verify FOLDER... | remove" >&2; exit 2 ;;
  esac
fi
