#!/bin/sh
# PERF-010 (D-968): check each pinned module bump against the restic release's own go.mod, before `go get` applies it.
#   restic_bumps.sh GO_MOD MODULE@VERSION ...
# A bump must name a module the release requires (directly or // indirect), and must be newer than the version the
# release carries. One the release already carries (or a newer one) is refused: drop it from RESTIC_MODULE_BUMPS.
set -eu
gomod="$1"; shift
[ -f "$gomod" ] || { echo "restic_bumps: no $gomod" >&2; exit 2; }
fail=0
for bump in "$@"; do
  mod="${bump%@*}"; want="${bump#*@}"
  case "$bump" in *@v[0-9]*) ;; *) echo "restic_bumps: $bump is not MODULE@vX.Y.Z" >&2; fail=1; continue ;; esac
  # a require line: "<mod> <version>" inside "require ( ... )" or "require <mod> <version>"
  cur="$(sed -n -E "s#^[[:space:]]*(require[[:space:]]+)?$(printf '%s' "$mod" | sed 's/[.]/[.]/g')[[:space:]]+(v[^[:space:]]+).*#\2#p" "$gomod" | head -1)"
  if [ -z "$cur" ]; then
    echo "restic_bumps: $mod is not in the release's go.mod: a bump raises only restic's own modules" >&2; fail=1
  elif [ "$cur" = "$want" ]; then
    echo "restic_bumps: the release already carries $mod $cur: drop the bump" >&2; fail=1
  elif [ "$(printf '%s\n%s\n' "${cur#v}" "${want#v}" | sort -V | head -1)" != "${cur#v}" ]; then
    echo "restic_bumps: $mod $want is older than the release's $cur: drop the bump" >&2; fail=1
  else
    echo "restic_bumps: $mod $cur -> $want"
  fi
done
exit "$fail"
