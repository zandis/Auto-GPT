#!/bin/sh
# Every start of the box mounts the site's settings, never the example (D-888, found on lane G's box). Each service
# mounts ${TB_SETTINGS_FILE:-./settings.example.yaml} (deploy/docker-compose.yml); compose takes TB_SETTINGS_FILE
# from the environment, else from deploy/.env, which install.sh writes. Run before every start that is not
# install.sh: the systemd unit (ExecStartPre) and tools/apply_update.sh.
#
#   deploy/settings_guard.sh DEPLOY_DIR
#
# 10K-4: before that, the audit anchor folder the console is given is checked again (exit 1 when it may not be).
# Exit 0 when the box has no site settings yet (a first install loads its bundle first) or when compose would mount
# them; exit 1, saying what to add, when a site settings.yaml exists and the example would be mounted instead.
set -eu
DEPLOY="${1:?usage: settings_guard.sh DEPLOY_DIR}"
# ---- STOP-OR-WARN (H-94, the owner's ruling 7092087958, D-1091; the same bytes in every script that has it): on a PoC box
# the install, start and update paths stop for five things only (D-1091), each named where it stops as "H-94 (N)":
# (1) the bundle's or update's signature or hashes do not hold; (2) the machine physically cannot run it (disk,
# memory, card); (3) a PoC box would load real patient data or become PRODUCTION; (4) the step needs root and does
# not have it; (5) a secret would be read from, or written to, a place others can read. Every other stop calls
# stop_or_warn: on a PoC box a warning, a line of the one list (deploy/site/poc-stops.jsonl, which trialbox doctor
# shows) and the step goes on; on any other box the same stop as before, the same words and exit code. "H-94
# depends (N)" marks a stop kept because it protects stop N on the input that reaches it (D-1091, H94-03).
# A PoC box (tools/trialbox/stops.py poc_box, the same rule): every source that speaks says DEV, TEST or VALIDATION.
# The sources are TB_ENV in deploy/.env read as compose reads it (an "export", blanks, a comment; the last line wins.
# A file that cannot be read, or a value none of the four: PRODUCTION), an installed box with none (PRODUCTION,
# D-127), the rehearsal mark on a box that records none yet (VALIDATION), and this run's command line, upper-cased
# only, as ENV-EARLY reads it (TB_STOP_ARG_ENV, TB_STOP_REHEARSAL: set by the script itself, never read from a
# caller's environment). Nothing speaking (a fresh box, no environment given) is PRODUCTION.
tb_env_raw() {  # FILE: TB_ENV's value as compose reads it (an "export", blanks around the name and the value, a comment
  # after an unquoted value; the last line wins), quotes kept; nothing when the file names none or cannot be read
  { sed -n -E 's/^[[:space:]]*(export[[:space:]]+)?TB_ENV[[:space:]]*=//p' "$1" 2>/dev/null || true; } | tail -1 \
    | sed -E -e "/^[[:space:]]*[\"']/!s/[[:space:]]+#.*\$//" -e 's/^[[:space:]]+//' -e 's/[[:space:]]+$//'
}
tb_env_of() { tb_env_raw "$1" | tr -d "\"' \r\t" | tr '[:lower:]' '[:upper:]'; }  # FILE: no quotes, no blanks, upper case
tb_poc_box() {
  _d="$TB_STOP_DEPLOY"; _rec=""
  if [ -e "$_d/.env" ] || [ -L "$_d/.env" ]; then
    [ -f "$_d/.env" ] && [ -r "$_d/.env" ] || return 1
    _rec="$(tb_env_of "$_d/.env")"
  fi
  if [ -z "$_rec" ] && { [ -e "$_d/settings.yaml" ] || [ -e "$_d/updates/installed.json" ]; }; then _rec=PRODUCTION; fi
  if [ -z "$_rec" ] && [ -f "$_d/site/rehearsal.json" ]; then _rec=VALIDATION; fi
  _arg="$(printf '%s' "$TB_STOP_ARG_ENV" | tr '[:lower:]' '[:upper:]')"
  [ -n "$_arg" ] || [ "$TB_STOP_REHEARSAL" != 1 ] || _arg=VALIDATION
  for _e in "$_rec" "$_arg"; do case "$_e" in ""|DEV|TEST|VALIDATION) ;; *) return 1 ;; esac; done
  [ -n "$_rec$_arg" ]
}
tb_stop_json() {  # one line, no secret's value, no path under uploads/, escaped for a JSON string
  printf '%s' "$1" | tr -d '\000-\037' | sed -e 's#[^ ]*/uploads/[^ ]*#<a path under uploads/>#g' \
    -e 's/\([a-z0-9_]*\(password\|passphrase\|token\|secret\|_key\)\)=[^ ]*/\1=<hidden>/gI' -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}
tb_stop_list() {  # KEY SKIPPED WHAT: one line of the list, written by root or the installer only; never a stop
  _f="$TB_STOP_DEPLOY/site/poc-stops.jsonl"; _o=""
  [ ! -e "$_f" ] || _o="$(stat -c %u "$_f" 2>/dev/null || echo unknown)"
  # a link is never followed, nor a second name of another file (review L-2 of #1430: one name, its own)
  if [ ! -L "$_f" ] && { [ ! -e "$_f" ] || [ "$(stat -c %h "$_f" 2>/dev/null)" = 1 ]; } \
      && { [ -z "$_o" ] || [ "$_o" = 0 ] || [ "$_o" = "$(id -u)" ]; } && mkdir -p "${_f%/*}" 2>/dev/null \
      && (umask 027; printf '{"key": "%s", "what": "%s", "skipped": "%s", "at": "%s", "by": "%s"}\n' "$(tb_stop_json "$TB_STOP_FILE/$1")" \
        "$(tb_stop_json "$3")" "$(tb_stop_json "$2")" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$TB_STOP_FILE" >> "$_f") 2>/dev/null; then
    chmod 0640 "$_f" 2>/dev/null || true
  else
    printf '%s: warning: the PoC list %s cannot be written; the step goes on\n' "$TB_STOP_WHO" "$_f" >&2
  fi
}
stop_or_warn() {  # [--rc N] [--silent] KEY SKIPPED WHAT...: PoC box: a warning, a line of the list, 0; else the stop
  _rc=1; _silent=0
  while :; do case "$1" in --rc) _rc="$2"; shift 2 ;; --silent) _silent=1; shift ;; *) break ;; esac; done
  _key="$1"; _skipped="$2"; shift 2
  if ! tb_poc_box; then
    if command -v alive_stop >/dev/null 2>&1; then alive_stop; fi
    [ "$_silent" = 1 ] || printf '%s: %s\n' "$TB_STOP_WHO" "$*" >&2
    exit "$_rc"
  fi
  # a warning never says REFUSED (review L-3 of #1430): "update REFUSED" warns as "update"
  printf '%s: warning (PoC box, H-94): %s%s\n' "${TB_STOP_WHO%% REFUSED*}" "$*" "${_skipped:+; skipped: $_skipped}" >&2
  tb_stop_list "$_key" "$_skipped" "$*"
  return 0
}
tb_kept_fails() {  # stdin: a host check's output; stdout: its FAIL lines of a kept refusal, which stop on every box
  # (5) a secret's mode (deploy/.env, a key, a token); (2) what the machine cannot run (memory class, card, driver,
  # toolkit, disk space); (3) the poc profile on a PRODUCTION box (review H-1 of #1430). Every other FAIL line warns
  _in="$(cat)"
  { printf '%s\n' "$_in" | grep -E '^FAIL .*[Mm]ode' | grep -Ei '\.env|secret|key|token|passphrase|password'
    printf '%s\n' "$_in" | grep -E '^FAIL .*(under 96 GiB|GB10 profile on|NVIDIA driver|nvidia-container-toolkit not configured|but no nvidia-smi|free space on|TB_HOST_PROFILE=poc on a PRODUCTION box)'
  } | sort -u || true
}
# ---- end of STOP-OR-WARN
# H-94: its PoC box is the record (deploy/.env, the mark) alone: it has no command line of its own
TB_STOP_WHO="TrialBox REFUSED to start"; TB_STOP_FILE=settings_guard.sh; TB_STOP_DEPLOY="$DEPLOY"; TB_STOP_ARG_ENV=""
TB_STOP_REHEARSAL=0
# 10K-4 (D-1390): the audit anchor folder is bind-mounted into the console, and docker resolves its path again at
# every start: when the box mounts one (deploy/site/compose.anchors.yml), the rule for a folder the console may be
# given is checked again here (no link in its path, parents only root may write, no system folder; finish-check
# --anchor-only), and the stack does not start when it no longer holds
if [ -f "$DEPLOY/site/compose.anchors.yml" ]; then
  if ! (cd "$DEPLOY/.." && python3 -m tools.trialbox finish-check --deploy "$DEPLOY" --anchor-only) >&2; then
    # the integrator's ruling 7102087475 (H94-09): the audit anchor is not one of the five: on a PoC box it warns
    stop_or_warn anchor-rule "the nightly signed head into the anchor folder (taken out of the retention cron)" "the audit anchor folder it would give the console no longer passes the rule (above), or the check could not run. Correct TB_AUDIT_ANCHOR_TARGETS in $DEPLOY/.env and run deploy/install.sh again (RUNBOOK §5)"
    # on a PoC box (the helper returned): root's nightly signer writes into each anchor folder, so its line leaves the
    # retention cron, as install.sh and box-install.sh do for a warned anchor (review M-2 of #1430)
    if [ -f "${TB_CRON_DIR:-/etc/cron.d}/trialbox-retention" ]; then
      sed -i 's/; python3 -m tools.trialbox audit-sign//' "${TB_CRON_DIR:-/etc/cron.d}/trialbox-retention"
    fi
  fi
fi
# H-89: a box that carries a rehearsal sign starts only as a whole rehearsal box, never as PRODUCTION (a hand edit of
# TB_ENV before a reboot): tools/rehearsal_real.py start. A box without a sign is not asked
# the signs are the start check's (rehearsal_real.start_refusal): the files, the names in deploy/.env, and any file
# COMPOSE_FILE names that carries the real servers' mark, wherever it lies
rehearsal_sign() {
  [ -f "$DEPLOY/site/rehearsal.json" ] || [ -f "$DEPLOY/site/rehearsal-real-servers.json" ] || [ -f "$DEPLOY/site/rehearsal-real-servers.yml" ] \
    || grep -qE '^[[:space:]]*(export[[:space:]]+)?TB_REHEARSAL(_REAL_SERVERS)?=|rehearsal-real-servers' "$DEPLOY/.env" 2>/dev/null \
    && return 0
  cf="$(sed -n 's/^[[:space:]]*\(export[[:space:]]\{1,\}\)\{0,1\}COMPOSE_FILE=//p' "$DEPLOY/.env" 2>/dev/null | tail -1)"
  # a line this reader cannot read as the start check does (a comment, a carriage return): refused below (fail closed)
  case "$cf" in *"#"*|*"$(printf '\r')"*) CF_UNREADABLE=1; return 0 ;; esac
  old_ifs="$IFS"; IFS=:
  for f in $cf; do
    case "$f" in /*) ;; *) f="$DEPLOY/$f" ;; esac
    if [ -f "$f" ] && tr -d '\r' < "$f" | grep -qx 'x-trialbox-rehearsal-real-servers: true'; then IFS="$old_ifs"; return 0; fi
  done
  IFS="$old_ifs"
  return 1
}
CF_UNREADABLE=0
if rehearsal_sign; then
  if [ "$CF_UNREADABLE" = 1 ]; then
    echo "TrialBox REFUSED to start: COMPOSE_FILE in $DEPLOY/.env has a comment or a carriage return, so the files it names cannot be checked for a rehearsal's real model servers. Write it as one plain line (deploy/install.sh writes it so), then start again" >&2
    exit 1  # H-94 (3): a rehearsal box never starts as PRODUCTION (it cannot be checked)
  fi
  if ! (cd "$DEPLOY/.." && python3 -m tools.rehearsal_real start --deploy "$DEPLOY") >&2; then
    echo "TrialBox REFUSED to start: this box carries a rehearsal sign and is not a whole rehearsal box (above), or the check could not run. A rehearsal box never becomes a site's box: install the site's box afresh on an empty box (RUNBOOK §16)" >&2
    exit 1  # H-94 (3)
  fi
fi
# H-116 (D-1357): a box that carries the bench mark starts only with the mark the install option wrote (the record is
# root's, with the install's trace) and only as a PRODUCTION box with no sending identity: tools/trialbox/benchbox.py
if [ -e "$DEPLOY/site/bench-box.env" ] || [ -L "$DEPLOY/site/bench-box.env" ] || grep -q '^TB_BENCH=' "$DEPLOY/.env" 2>/dev/null; then
  if ! (cd "$DEPLOY/.." && python3 -m tools.trialbox.benchbox check --deploy "$DEPLOY" >/dev/null) >&2; then
    echo "TrialBox REFUSED to start: this box's bench mark is refused (above), or the check could not run. The mark is written by deploy/install.sh --bench only; run it again, or empty the box (RUNBOOK part 30)" >&2
    exit 1  # H-94 (3): a mark the install option did not write never keeps a PRODUCTION box beside test boxes
  fi
fi
[ -f "$DEPLOY/settings.yaml" ] || exit 0
got="${TB_SETTINGS_FILE:-$(sed -n 's/^TB_SETTINGS_FILE=//p' "$DEPLOY/.env" 2>/dev/null | tail -1)}"
case "$got" in
  ./settings.yaml|settings.yaml|"$DEPLOY/settings.yaml") exit 0 ;;
esac
# the integrator's ruling 7102087475 (H94-09): the example settings are what a PoC box starts from: there it warns
TB_STOP_WHO="TrialBox REFUSED to start on the example settings"
stop_or_warn example-settings "the site's settings (the start mounts the example's)" "$DEPLOY/settings.yaml is this site's, but compose would mount ${got:-./settings.example.yaml} (TB_SETTINGS_FILE). Add TB_SETTINGS_FILE=./settings.yaml to $DEPLOY/.env (or run deploy/install.sh again, which writes it), then start again"
exit 0
