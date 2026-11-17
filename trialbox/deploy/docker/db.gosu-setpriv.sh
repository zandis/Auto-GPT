#!/bin/sh
# SC-1b (D-993): gosu's interface on setpriv. The upstream postgres image drops root with gosu, a Go binary whose old
# Go runtime carried most of the image's scanner findings; this shim takes its place at /usr/local/bin/gosu, so the
# upstream entrypoint (`exec gosu postgres "$BASH_SOURCE" "$@"`) is unchanged. setpriv is util-linux, already in the
# base. The result is gosu's: the user's uid, its primary group (or the one named) and only its own supplementary
# groups (initgroups), with nothing kept from root.
#   gosu USER[:GROUP] COMMAND [ARG...]      USER and GROUP by name or number
set -eu
[ $# -ge 2 ] || { echo "usage: gosu USER[:GROUP] COMMAND [ARG...]" >&2; exit 2; }
spec="$1"; shift
user="${spec%%:*}"
case "$spec" in *:*) group="${spec#*:}" ;; *) group="" ;; esac
uid="$(id -u "$user" 2>/dev/null)" || { echo "gosu: no user $user" >&2; exit 1; }
if [ -n "$group" ]; then
  case "$group" in
    *[!0-9]*) gid="$(getent group "$group" | cut -d: -f3)" ;;
    *) gid="$group" ;;
  esac
  [ -n "$gid" ] || { echo "gosu: no group $group" >&2; exit 1; }
else
  gid="$(id -g "$user")"
fi
exec setpriv --reuid="$uid" --regid="$gid" --init-groups -- "$@"
