# shellcheck shell=sh
# Shared by the host baseline scripts of deploy/hardening/ (T-634, D-408). Sourced, never run.
#
# HR is the host root: empty on the box; the tests point TB_HOST_ROOT at a folder so that nothing on the machine that
# runs them is read or changed. DRY=1 prints each change instead of making it.
# shellcheck disable=SC2034  # used by the scripts that source this file
HR="${TB_HOST_ROOT:-}"
DRY="${DRY:-0}"

hb_say() { printf '    %s\n' "$*"; }
hb_die() { printf 'hardening: %s\n' "$*" >&2; exit 1; }

# run a command that changes the host; in a dry run print it only
hb_run() {
  if [ "$DRY" = 1 ]; then
    printf '    would run: %s\n' "$*"
  else
    "$@"
  fi
}

# write stdin to a host file (mode $2); in a dry run print where it would go
hb_write() {
  if [ "$DRY" = 1 ]; then
    printf '    would write: %s\n' "$1"
    cat >/dev/null
  else
    mkdir -p "$(dirname "$1")"
    cat >"$1.tmp" && chmod "${2:-644}" "$1.tmp" && mv -f "$1.tmp" "$1"
  fi
}

# the site's file: --conf, else deploy/site/hardening.conf; variables only (shell syntax)
hb_load_conf() {
  [ -n "${1:-}" ] || return 0
  [ -f "$1" ] || hb_die "no such file: $1 (copy deploy/hardening/hardening.example.conf to deploy/site/hardening.conf)"
  # shellcheck disable=SC1090
  . "$1"
}
