#!/bin/sh
# The restore job's database tools (T-633, D-416), in the database image beside the Python container, which has no
# PostgreSQL client (D-23). `trialbox platform-day2 pg <tool> ...` writes a request into the spool folder: <id>.args
# (the tool, then one argument a line; a connection string is the name of its variable, @TB_DB_URL or
# @TB_HAPI_DB_URL, never its value), <id>.in (standard input, pg_restore only) and last <id>.req. This loop runs the
# tool and writes <id>.out, <id>.err and <id>.rc. Only psql, pg_dump and pg_restore run. It stops at the file STOP.
set -u
SPOOL="${1:-/spool/pg}"
umask 077
mkdir -p "$SPOOL"
while :; do
  for r in "$SPOOL"/*.req; do
    [ -e "$r" ] || continue
    id="${r%.req}"
    mv "$r" "$id.run" 2>/dev/null || continue
    set --
    tool=""
    while IFS= read -r a; do
      case "$a" in
        @TB_DB_URL) a="${TB_DB_URL:-}" ;;
        @TB_HAPI_DB_URL) a="${TB_HAPI_DB_URL:-}" ;;
        @*) a="" ;;
      esac
      if [ -z "$tool" ]; then tool="$a"; else set -- "$@" "$a"; fi
    done < "$id.args"
    case "$tool" in
      psql|pg_dump|pg_restore)
        if [ -e "$id.in" ]; then
          "$tool" "$@" < "$id.in" > "$id.out" 2> "$id.err"
        else
          "$tool" "$@" < /dev/null > "$id.out" 2> "$id.err"
        fi
        rc=$?
        ;;
      *) echo "pg-spool: $tool refused" > "$id.err"; : > "$id.out"; rc=126 ;;
    esac
    echo "$rc" > "$id.rc.part"
    mv "$id.rc.part" "$id.rc"
    rm -f "$id.run"
  done
  [ -e "$SPOOL/STOP" ] && exit 0
  sleep 1
done
