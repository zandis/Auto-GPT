#!/usr/bin/env bash
# The box installer (T-729, D-466; plan v6.1 OD-11, OD-13): one installer for a GPU workstation or a DGX Spark, set up
# by its owner, with no shell knowledge and no question an IT department would be asked.
#
#   sudo deploy/box-install.sh trialbox-<version>.tar                # on a terminal: four questions, then no more (M1)
#   sudo deploy/box-install.sh trialbox-<version>.tar --yes          # no question: install, then the first-run page
#   sudo deploy/box-install.sh trialbox-<version>.tar --prepare      # Aimedics, before shipping: stop before the wizard
#   sudo deploy/box-install.sh trialbox-<version>.tar --rehearsal    # a rehearsal box: TEST, stand-ins (D-726)
#   deploy/box-install.sh --firstrun                                 # the prepared box's first boot (trialbox-firstrun.service)
#   sudo deploy/box-install.sh trialbox-<version>.tar --answers owner.json   # unattended (D-898): the hospital's install
#
# What it does, in order:
#   1. hardware: python3 -m tools.box detect (the GPU, memory, disks, TPM, the box's network); shown, not asked. On a
#                terminal the four questions (D-1280: language, time zone, first administrator, and the key passphrase
#                only without a TPM), then the install runs to its end with the rest at its defaults (--yes skips them)
#   2. plan:     python3 -m tools.box plan --provisional: the GPU profile from the card (deploy/gpu_profile.sh), memory
#                caps from the RAM (OD-10), TLS internal under the box's name, deploy/site/hardening.conf (KEK tpm, or a
#                passphrase the owner sets on a board without a TPM; the input firewall open to the box's own network)
#   3. install:  deploy/install.sh with the plan's answers and flags, TB_BOX=1 (the first-run folder for the console, no
#                printed administrator password) and, without a TPM, TB_BOX_DEFER_SEAL=1
#   4. --prepare stops here (deploy/site/box/prepared; trialbox-firstrun.service enabled for the site's first boot)
#   5. first run: a one-time code (tb_common.firstrun) in /run/trialbox-firstrun (tmpfs), shown with the address on
#      a terminal once, never on the output (H-97, show_code); it waits until the owner has finished the wizard. Five
#      wrong codes void a code: a new one is shown
#   6. apply:    the keys sealed under the owner's passphrase when deferred; python -m tools.box apply in the image (the
#                owner's answers into settings.yaml and deploy/.env, the install's passwords kept); the host's time zone;
#                the stack restarted on the new settings; the backup schedule; the host check with `trialbox doctor`
# Unattended (--answers, D-898): the owner's answers come from a JSON file (the first-run form's fields, flat or
# nested; `environment` PRODUCTION or VALIDATION) instead of the first-run wizard. No question, no code, no wait: the
# plan is made from those answers, the install makes the first administrator as the IT form does (TB_BOX=0: its
# password and enrolment code printed once), then the time zone, the backup schedule and the host check. The file
# never holds a password or a passphrase (refused); a board without a TPM takes the KEK passphrase (12 characters or
# more, one line) from a file only root can read, and the keys are sealed at the install. Set bundle to the signed
# bundle path; type the passphrase after sudo's own password prompt, then Enter (nothing is shown):
#   sudo bash -c 'umask 077; IFS= read -rs TB_KEK_PASSPHRASE; printf "%s\n" "$TB_KEK_PASSPHRASE" > /root/trialbox-kek.pass'
#   sudo deploy/box-install.sh "$bundle" --answers owner.json --kek-passphrase-file /root/trialbox-kek.pass
# or it is typed when asked (twice, not shown): ... --kek-passphrase-stdin. The file must be a regular file owned by
# root with mode 0600; it is removed once the keys are sealed (--keep-kek-passphrase-file keeps it). A passphrase in
# the environment (TB_KEK_PASSPHRASE) is refused: sudo logs the variables it keeps (RUNBOOK §23, H-96).
# Knobs for the tests and the rehearsal only: TB_BOX_HARDWARE (a hardware.json instead of detecting), TB_BOX_INSTALL
# (the install command), TB_BOX_PY (a python command instead of the image), TB_BOX_COMPOSE (the compose command),
# TB_BOX_HOST_CHECK (the host check command), TB_FIRSTRUN_HOST_DIR, TB_BOX_POLL_S, TB_BOX_NO_ROOT=1,
# TB_SYSTEMD=0 (as install.sh), TB_BOX_PREFLIGHT (the python command that runs the first-run page's preflight, even
# with TB_BOX_PY; 10K-3), TB_BOX_PREFLIGHT_S (its time limit, 90 s) and TB_BOX_DOCKER (the docker command that asks
# the console's image whether it can read the audit anchor folder; 10K-4), TB_BOX_SEED (the site seed's command; M1).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
BUNDLE=""; YES=0; PREPARE=0; FIRSTRUN=0; REHEARSAL=0; OWNER=""; ENVIRONMENT=""
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
# H-94: this run's command line (--rehearsal, --environment) is read once before the arguments are (the owner's
# answers file is not read for it: on a fresh box with no --environment it stays PRODUCTION, the stricter)
TB_STOP_WHO=box-install; TB_STOP_FILE=box-install.sh; TB_STOP_DEPLOY="$ROOT/deploy"; TB_STOP_ARG_ENV=""
TB_STOP_REHEARSAL=0
_clear=1
_p=""
for _a in "$@"; do
  [ "$_p" != --environment ] || TB_STOP_ARG_ENV="$_a"  # M1: as install.sh reads its own
  [ "$_a" != --rehearsal ] || TB_STOP_REHEARSAL=1
  [ "$_a" != --firstrun ] || _clear=0
  _p="$_a"
done
# the list is this install's (review L-3 of #1396): emptied when a box install starts, kept by --firstrun (it finishes
# the same install) and by install.sh run from here (--keep-poc-list). rm takes a link away, never what it names
[ "$_clear" = 0 ] || rm -f -- "$TB_STOP_DEPLOY/site/poc-stops.jsonl" 2>/dev/null || true
PP_FILE=""; PP_KEEP=0; PP_STDIN=0  # H-96: the KEK passphrase's two ways in (the KEK-INPUT block)
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) YES=1 ;;
    --prepare) PREPARE=1 ;;
    --firstrun) FIRSTRUN=1 ;;
    --rehearsal) REHEARSAL=1 ;;
    --environment)  # M1: as install.sh's (D-837); a PRODUCTION box unless it says otherwise
      ENVIRONMENT="$(printf '%s' "${2:-}" | tr '[:lower:]' '[:upper:]')"; [ $# -lt 2 ] || shift
      case "$ENVIRONMENT" in VALIDATION|PRODUCTION) ;; *) echo "box-install: --environment is VALIDATION or PRODUCTION" >&2; exit 2 ;; esac ;;  # H-94 not a stop: a usage error
    --answers) if [ -n "${2:-}" ] && [ "${2#-}" = "$2" ]; then OWNER="$2"; shift
      else stop_or_warn --rc 2 answers-value "--answers (ignored)" "--answers needs the owner's answers file (JSON)"; fi ;;
    --kek-passphrase-file) PP_FILE="${2:-}"; shift ;;
    --keep-kek-passphrase-file) PP_KEEP=1 ;;
    --kek-passphrase-stdin) PP_STDIN=1 ;;
    -h|--help) sed -n '2,/^set -euo pipefail/{ /^set -euo pipefail/!p; }' "$0"; exit 0 ;;
    -*) echo "box-install: unknown option $1" >&2; exit 2 ;;  # H-94 not a stop: a usage error, refused by name on every box (review L-5 of #1430): an option not understood is never acted on, nor its value taken for the bundle
    *) BUNDLE="$1" ;;
  esac
  shift
done
# H-94 (3): a rehearsal box (a PoC box) never becomes a prepared box for a site, nor the site's unattended install
if [ "$REHEARSAL" = 1 ] && [ "$PREPARE" = 1 ]; then echo "box-install: --rehearsal with --prepare: a prepared box goes to a site" >&2; exit 2; fi  # H-94 (3)
if [ -n "$OWNER" ] && [ "$PREPARE$REHEARSAL$FIRSTRUN" != 000 ]; then
  echo "box-install: --answers is the site's unattended install: not with --prepare, --rehearsal or --firstrun" >&2; exit 2  # H-94 (3)
fi
if [ "$REHEARSAL" = 1 ] && [ "$FIRSTRUN" = 1 ]; then echo "box-install: --rehearsal with --firstrun: the first run finishes the box as it was installed" >&2; exit 2; fi  # H-94 (3): a first-run box is a site's box (review F7)
say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf 'box-install: %s\n' "$*" >&2; exit 1; }
# KEK-INPUT (H-96, F-45, H-94 (5); the integrator's ruling 7094934985): never from the environment (refused, before
# anything); only with --answers (the wizard's box takes it on the set-up page). A file goes on to install.sh by its
# name (its seal step removes it); a passphrase read from stdin by a pipe at fd 8. KP_VALUE is never exported
KP_WHO=box-install
# ---- KEK-INPUT functions (H-96, F-45, H-94 (5); the integrator's ruling 7094934985). The same lines are in deploy/install.sh,
# deploy/box-install.sh and deploy/hardening/seal_keys.sh; a test holds the three together. The passphrase comes from
#   --kek-passphrase-file FILE  one line of a regular file (not a link) owned by root (the user that runs this), mode
#                               0600; removed once the keys are sealed, unless --keep-kek-passphrase-file
#   --kek-passphrase-stdin      one line on stdin; on a terminal it is asked twice, not shown
# and never from the environment: TB_KEK_PASSPHRASE or TB_KEK_NEW_PASSPHRASE there is refused, with or without sudo
# (sudo writes a variable it keeps, with its value, to the system journal). The value lives in KP_VALUE, never
# exported, and goes on by a pipe: never an argument, never a sudo environment, never a file. Nothing prints it.
KP_VALUE=""; KP_FILE=""
kp_die() { printf '%s: %s\n' "$KP_WHO" "$*" >&2; exit 1; }
kp_refuse_env() {  # an empty variable is dropped
  for kp_var in TB_KEK_PASSPHRASE TB_KEK_NEW_PASSPHRASE; do
    kp_set=""
    eval "kp_set=\${$kp_var:+yes}"
    [ "$kp_set" != yes ] || { printf '%s: %s is set in the environment: refused, nothing was changed. A passphrase given by the environment can be in the system journal (sudo logs the variables it keeps, with their values): treat that passphrase as exposed and rotate it (RUNBOOK §23, rotate the KEK passphrase). Give it in a file only root can read: --kek-passphrase-file FILE (a regular file, owned by root, mode 0600), or on stdin: --kek-passphrase-stdin. Then unset %s.\n' "$KP_WHO" "$kp_var" "$kp_var" >&2; exit 2; }  # H-94 (5)
  done
  unset TB_KEK_PASSPHRASE TB_KEK_NEW_PASSPHRASE kp_set kp_var
}
kp_check_value() {  # one line, not empty, no control character (the image and the host read it alike)
  [ -n "$KP_VALUE" ] || kp_die "the KEK passphrase from $1 is empty: nothing was changed"
  case "$KP_VALUE" in *[[:cntrl:]]*) KP_VALUE=""; kp_die "the KEK passphrase from $1 holds a line break or another control character: write it again on one line; nothing was sealed" ;; esac
}
kp_read_file() {  # H-94 (5): refused unless its folders are safe and the opened file is regular, root's, 0600, one name
  kp_fix="write the passphrase on one line of a regular file owned by root with mode 0600, in a folder only root can write (sudo install -m 0600 -o root -g root /dev/null /root/trialbox-kek.pass, then write it there); nothing was changed"
  # (M-1 of the review of #1398) the folders as their real paths: the file's own folder and every one above it owned
  # by root (the user that runs this), and writable by no one else; above the file's own folder a shared folder with
  # the sticky bit (/tmp) is allowed, as no one else can rename what is root's there
  kp_dir="$(cd -P -- "$(dirname -- "$1")" 2>/dev/null && pwd -P)" \
    || kp_die "--kek-passphrase-file $1: its folder cannot be reached: refused; $kp_fix"  # H-94 (5)
  kp_name="${kp_dir%/}/${1##*/}"; kp_d="$kp_dir"; kp_own=1
  while :; do
    kp_st="$(stat -c '%u %a' -- "$kp_d" 2>/dev/null)" || kp_die "--kek-passphrase-file $1: the folder $kp_d cannot be read: refused; $kp_fix"  # H-94 (5)
    kp_m="${kp_st#* }"
    case "${kp_st%% *}" in 0|"$(id -u)") ;; *) kp_die "--kek-passphrase-file $1: the folder $kp_d is owned by uid ${kp_st%% *}, not root: refused; $kp_fix" ;; esac  # H-94 (5)
    case "${kp_m#"${kp_m%??}"}" in
      [0145][0145]) ;;
      *) case "$kp_own:${#kp_m}:$kp_m" in 0:4:[1357]*) ;; *) kp_die "--kek-passphrase-file $1: the folder $kp_d can be written by others (mode $kp_m): refused; $kp_fix" ;; esac ;;  # H-94 (5)
    esac
    [ "$kp_d" != / ] || break
    kp_d="$(dirname -- "$kp_d")"; kp_own=0
  done
  # opened once on fd 7 and read from it; what was opened is checked through /dev/fd/7 (the same open file, never the
  # name again), and the name must still be that very file, not a link (the shell cannot open without following one)
  [ ! -L "$kp_name" ] || kp_die "--kek-passphrase-file $1 is a link: refused; $kp_fix"  # H-94 (5)
  [ -f "$kp_name" ] || kp_die "--kek-passphrase-file $1 is not a regular file: refused; $kp_fix"  # H-94 (5): never a fifo opened
  exec 7< "$kp_name"
  kp_fd="$(stat -L -c '%F|%u|%a|%h|%d:%i' /dev/fd/7 2>/dev/null)" || kp_fd=""
  kp_nm="$(stat -c '%F|%d:%i' -- "$kp_name" 2>/dev/null)" || kp_nm=""
  kp_t="${kp_fd%%|*}"; kp_r="${kp_fd#*|}"; kp_u="${kp_r%%|*}"; kp_r="${kp_r#*|}"; kp_a="${kp_r%%|*}"; kp_r="${kp_r#*|}"
  kp_h="${kp_r%%|*}"; kp_i="${kp_r#*|}"
  kp_bad=""
  case "$kp_nm" in "symbolic link|"*) kp_bad="is a link" ;; esac
  [ -n "$kp_bad" ] || case "$kp_t" in "regular file"|"regular empty file") ;; *) kp_bad="is not a regular file" ;; esac
  [ -n "$kp_bad" ] || [ "$kp_nm" = "$kp_t|$kp_i" ] || kp_bad="changed while it was opened"
  [ -n "$kp_bad" ] || [ "$kp_u" = "$(id -u)" ] || kp_bad="is owned by uid $kp_u, not root (the user that runs this)"
  [ -n "$kp_bad" ] || [ "$kp_a" = 600 ] || kp_bad="has mode $kp_a, not 0600"
  [ -n "$kp_bad" ] || [ "$kp_h" = 1 ] || kp_bad="has $kp_h names (hard links), not one"
  if [ -n "$kp_bad" ]; then exec 7<&-; kp_die "--kek-passphrase-file $1 $kp_bad: refused; $kp_fix"; fi  # H-94 (5)
  KP_VALUE=""; IFS= read -r KP_VALUE <&7 || [ -n "$KP_VALUE" ] || :
  kp_rest="$(wc -c <&7)"; exec 7<&-
  if [ "$kp_rest" != 0 ]; then KP_VALUE=""; kp_die "--kek-passphrase-file $1 holds a line break or another control character: write it again on one line; nothing was sealed"; fi  # H-94 (5)
  KP_FILE="$kp_name"
  kp_check_value "--kek-passphrase-file $1"
}
kp_read_stdin() {
  KP_VALUE=""
  if [ -t 0 ]; then
    stty -echo 2>/dev/null; printf 'KEK passphrase (12 characters or more, not shown): ' >&2; IFS= read -r KP_VALUE || :
    printf '\nthe same again: ' >&2; kp_again=""; IFS= read -r kp_again || :; stty echo 2>/dev/null; printf '\n' >&2
    [ "$KP_VALUE" = "$kp_again" ] || { KP_VALUE=""; kp_again=""; kp_die "the two passphrases differ: nothing was changed"; }
    kp_again=""
  else
    IFS= read -r KP_VALUE || [ -n "$KP_VALUE" ] || kp_die "--kek-passphrase-stdin: nothing on stdin; nothing was changed"
  fi
  kp_check_value "stdin"
}
kp_remove_file() {  # unlinked, never written through its name (a link is taken away, never what it names)
  rm -f -- "$1"; [ ! -e "$1" ] && [ ! -L "$1" ] || kp_die "the passphrase file $1 could not be removed: remove it yourself"  # H-94 (5)
}
# ---- end of KEK-INPUT functions
kp_refuse_env
if [ -n "$PP_FILE" ] || [ "$PP_KEEP" = 1 ] || [ "$PP_STDIN" = 1 ]; then
  [ -n "$OWNER" ] || die "--kek-passphrase-file and --kek-passphrase-stdin go with --answers (the unattended install); otherwise the owner sets the passphrase on the set-up page. Nothing was changed"  # H-94 (5)
  [ -z "$PP_FILE" ] || [ "$PP_STDIN" = 0 ] || die "--kek-passphrase-file and --kek-passphrase-stdin: give one; nothing was changed"  # H-94 (5)
  [ "$PP_KEEP" = 0 ] || [ -n "$PP_FILE" ] || die "--keep-kek-passphrase-file goes with --kek-passphrase-file"  # H-94 (5)
  case "$PP_FILE" in ""|/*) ;; *) die "--kek-passphrase-file: give the file's full path (/root/...): nothing was changed" ;; esac  # H-94 (5)
  if [ -n "$PP_FILE" ]; then kp_read_file "$PP_FILE"; else kp_read_stdin; fi
fi
PP_INSTALL=()  # what install.sh is given: the file's name (checked again there), or a passphrase from stdin at fd 8
KP_LEN="${#KP_VALUE}"  # for the no-TPM check below; the file form keeps no copy of the value (review L-1 of #1398)
if [ -n "$PP_FILE" ]; then
  PP_INSTALL=(--kek-passphrase-file "$KP_FILE"); [ "$PP_KEEP" = 0 ] || PP_INSTALL+=(--keep-kek-passphrase-file)
  KP_VALUE=""
elif [ -n "$KP_VALUE" ]; then PP_INSTALL=(--kek-passphrase-fd 8); fi
# ---- end of KEK-INPUT
IMAGE_PY="${TB_IMAGE:-trialbox-py:1.0.0}"
FR="${TB_FIRSTRUN_HOST_DIR:-/run/trialbox-firstrun}"
BOX="$ROOT/deploy/site/box"
# BOX-WSL2 (D-571): under WSL2 (the Windows form, plan v7.2 section 2.3) Windows keeps the clock and the time zone.
# The kernel's release says so; TB_BOX_WSL2=0|1 sets it for a test.
WSL2=0; case "$(uname -r)" in *[Mm]icrosoft*) WSL2=1 ;; esac
case "${TB_BOX_WSL2:-}" in "") ;; 0|1) WSL2="$TB_BOX_WSL2" ;; *) stop_or_warn wsl2-value "TB_BOX_WSL2 (the kernel's word: $WSL2)" "TB_BOX_WSL2 is 0 or 1, not '$TB_BOX_WSL2'" ;; esac
export PYTHONPATH="$ROOT/libs:$ROOT"
[ "${TB_BOX_NO_ROOT:-0}" = 1 ] || [ "$(id -u)" = 0 ] || die "run it as root (sudo deploy/box-install.sh ...)"  # H-94 (4)
command -v python3 >/dev/null || die "python3 is missing on this machine (Ubuntu 24.04 has it)"  # H-94 (2): every next step runs it, as bootstrap.sh's own check (review L-1, L-4 of #1430)
# a bare Ubuntu box gets Docker, the NVIDIA toolkit and the host's libraries from the media first (OPS-006, D-966)
[ -n "${TB_BOX_PY:-}" ] || command -v docker >/dev/null \
  || stop_or_warn docker-missing "every step that runs Docker (the install's load then stops: kept refusal 1)" "Docker is missing on this machine: prepare it from the media first (sudo <media>/linux/box-prepare.sh <media> --pub <the vendor key given to you>; RUNBOOK §16)"
box_py() {  # tools.box with the image's libraries (the settings wizard needs them)
  if [ -n "${TB_BOX_PY:-}" ]; then
    # shellcheck disable=SC2086 # a command line on purpose (tests)
    $TB_BOX_PY -m tools.box "$@"
  else
    docker run --rm --user 0 --network none -v "$ROOT/deploy:/d" -v "$FR:/fr" "$IMAGE_PY" python -m tools.box "$@"
  fi
}
json_get() { python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get(sys.argv[2], ""))' "$1" "$2"; }

mkdir -p "$FR" "$BOX"
chmod 700 "$FR"
chown 10001:10001 "$FR" 2>/dev/null || true   # the console's user (tb) writes the owner's answers there

if [ "$FIRSTRUN" = 0 ]; then
  # H-94 (1): no bundle, no signature that holds
  [ -n "$BUNDLE" ] || die "usage: deploy/box-install.sh trialbox-<version>.tar [--prepare | --rehearsal] [--yes]"  # H-94 (1)
  [ -f "$BUNDLE" ] || die "no such bundle: $BUNDLE"  # H-94 (1)
  # ---------------------------------------------------------------------------------------------- 1. hardware
  say "this machine"
  if [ -n "${TB_BOX_HARDWARE:-}" ]; then cp "$TB_BOX_HARDWARE" "$BOX/hardware.json"
  else python3 -m tools.box detect --deploy "$ROOT/deploy" > "$BOX/hardware.json"; fi
  python3 - "$BOX/hardware.json" <<'EOP'
import json, sys
h = json.load(open(sys.argv[1]))
print(f"    GPU:     {h.get('gpu_name') or 'none'}" + (f" ({h['gpu_mem_gib']} GiB)" if h.get("gpu_mem_gib") else ""))
print(f"    memory:  {h['ram_gib']} GiB, {h['cpu_count']} processors, {h['disk_free_gib']} GiB free")
print(f"    disks for backups: {', '.join(d['path'] for d in h.get('disks') or []) or 'none'}")
print(f"    security chip (TPM): {'yes' if h.get('tpm') else 'no'};  network: {h.get('lan') or '-'};  name: {h['hostname']}")
EOP
  if [ -n "$OWNER" ]; then  # D-898: checked before anything is written; a bad file changes nothing
    # H-94 (3): the unattended install is the site's (never on a PoC box's arguments); (5): a password or passphrase
    # in the answers file is a secret in a file others may read
    [ -f "$OWNER" ] || die "no such answers file: $OWNER (nothing was changed)"  # H-94 (3)
    python3 - "$OWNER" <<'EOP' || die "the owner's answers file is refused (above): nothing was changed"  # H-94 (5)
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError, ValueError) as e:
    sys.exit(f"box-install: {sys.argv[1]} is not a JSON file ({type(e).__name__})")
secret = sorted(k for k in d if k in ("password", "password2", "totp", "kek", "kek2", "kek_passphrase"))
if secret:
    sys.exit(f"box-install: {', '.join(secret)} in the answers file: a password or passphrase never goes in a file "
             "(the administrator's password is made and printed by the install; the KEK passphrase comes from "
             "--kek-passphrase-file or --kek-passphrase-stdin)")
EOP
    if [ "$(json_get "$BOX/hardware.json" tpm)" != True ] && [ "$KP_LEN" -lt 12 ]; then
      # H-94 (5): the passphrase that seals the site keys (H-96's refusal)
      die "no usable TPM: the KEK passphrase (--kek-passphrase-file or --kek-passphrase-stdin) must contain at least 12 characters; follow the example in box-install.sh --help (nothing was changed)"
    fi
    YES=1
  fi
  # FOUR (M1, D-1280): on a terminal the four questions are asked here, before anything is changed; from there the
  # install is the unattended one (no first-run code, no wait, no question). A re-run keeps the answers it has. A site
  # seed beside the bundle, signed by the vendor (10K-2), answers all but the person and the passphrase
  SEED="$(dirname "$BUNDLE")/site-seed.json"; SEED_ARGS=()
  if [ -f "$SEED" ]; then
    python3 -m tools.site_seed verify "$SEED" --pub "$ROOT/deploy/keys/vendor_ed25519.pub" \
      || die "the site seed beside the bundle is not signed by the vendor's key (above): nothing was changed"  # H-94 (1)
    SEED_ARGS=(--seed "$SEED")
  fi
  if [ -z "$OWNER" ] && [ "$YES$PREPARE$REHEARSAL" = 000 ] && [ -t 0 ]; then
    OWNER="$BOX/owner.json"
    if [ -f "$OWNER" ]; then echo "    the answers of the earlier run are kept ($OWNER)"
    else
      python3 -m tools.box ask --hardware "$BOX/hardware.json" --out "$OWNER" ${ENVIRONMENT:+--environment "$ENVIRONMENT"} \
        ${SEED_ARGS[@]+"${SEED_ARGS[@]}"} || die "the questions were not answered (above): nothing was changed"  # H-94 (3): the site's install
    fi
    if [ "$(json_get "$BOX/hardware.json" tpm)" != True ] && [ "$KP_LEN" = 0 ]; then
      kp_read_stdin  # the fourth: not shown, twice
      KP_LEN="${#KP_VALUE}"
      [ "$KP_LEN" -ge 12 ] || die "the KEK passphrase must contain at least 12 characters (nothing was changed)"  # H-94 (5)
      PP_INSTALL=(--kek-passphrase-fd 8)
    fi
    YES=1
  fi
  # ---- end of FOUR
  # ---------------------------------------------------------------------------------------------- 2. plan
  say "plan from the hardware"
  rm -f "$BOX/applied"  # D-576: a new install: the answers are provisional again and the wizard is due
  if [ -n "$OWNER" ]; then
    ARGS_LINE="$(python3 -m tools.box plan --hardware "$BOX/hardware.json" --owner "$OWNER" --deploy "$ROOT/deploy" --out "$BOX/answers.json" | tail -1)" \
      || die "the owner's answers do not parse (above): nothing was changed"  # H-94 (3): the site's unattended install
  else
    ARGS_LINE="$(python3 -m tools.box plan --hardware "$BOX/hardware.json" --provisional --deploy "$ROOT/deploy" --out "$BOX/answers.json" | tail -1)"
  fi
  read -r -a INSTALL_ARGS <<< "${ARGS_LINE#install-args: }"
  [ -z "$ENVIRONMENT" ] || INSTALL_ARGS+=(--environment "$ENVIRONMENT")
  [ "$REHEARSAL" = 1 ] && INSTALL_ARGS+=(--rehearsal)  # D-726: a rehearsal box, handed on to install.sh
  DEFER=0; [ "$(json_get "$BOX/hardware.json" tpm)" = True ] || [ -n "$OWNER" ] || DEFER=1
  INBOX=1; [ -z "$OWNER" ] || INBOX=0  # D-898: unattended, the install makes the first administrator (the IT form)
  echo "    install: ${INSTALL_ARGS[*]}"
  [ "$DEFER" = 0 ] || echo "    no TPM: the site keys are sealed after the wizard, under the owner's passphrase"
  # ---------------------------------------------------------------------------------------------- 3. install
  set +e
  run_install() {
    # shellcheck disable=SC2086 # TB_BOX_INSTALL is a command line on purpose (tests)
    TB_BOX="$INBOX" TB_BOX_DEFER_SEAL="$DEFER" ${TB_BOX_INSTALL:-bash "$ROOT/deploy/install.sh"} "$BUNDLE" \
      --answers "$BOX/answers.json" "${INSTALL_ARGS[@]}" ${PP_INSTALL[@]+"${PP_INSTALL[@]}"} --yes --keep-poc-list
  }
  # fd 8 is opened only for a passphrase from stdin, the one form install.sh reads there (review L-1 of #1398)
  if [ "${PP_INSTALL[0]:-}" = --kek-passphrase-fd ]; then
    run_install 8< <(printf '%s\n' "$KP_VALUE") 2>&1 | tee "$BOX/install.log"; rc="${PIPESTATUS[0]}"
  else
    run_install 2>&1 | tee "$BOX/install.log"; rc="${PIPESTATUS[0]}"
  fi
  KP_VALUE=""
  set -e
  # a FAIL list at the end (backups not yet placed, say) leaves the stack running; a stop half-way does not
  if [ "$rc" != 0 ] && ! grep -q "TrialBox is running" "$BOX/install.log"; then
    # H-94 depends (1): on a PoC box install.sh stops only for one of the five (D-1091); a box with none is not served
    die "the install stopped (above; $BOX/install.log): nothing for the wizard to serve"
  fi
  if [ "$PREPARE" = 1 ]; then
    # ------------------------------------------------------------------------------------------- 4. prepared image
    date -u +%FT%TZ > "$BOX/prepared"
    if [ "${TB_SYSTEMD:-1}" != 0 ] && command -v systemctl >/dev/null && [ -d /run/systemd/system ]; then
      sed "s#@TB_ROOT@#$ROOT#g" deploy/systemd/trialbox-firstrun.service > "${TB_SYSTEMD_DIR:-/etc/systemd/system}/trialbox-firstrun.service"
      systemctl daemon-reload && systemctl enable trialbox-firstrun.service >/dev/null
    fi
    say "prepared: the box shows its first-run code at the site's first boot (trialbox-firstrun.service)"
    exit 0
  fi
fi

# ------------------------------------------------------------------------------------------------ 5. first run
# H-94 depends (3): the first run serves only a box this installer planned; another box's settings (a site's) are
# never taken over by a first-run wizard
[ -f "$BOX/answers.json" ] && [ -f "$BOX/hardware.json" ] || die "this box was not installed by box-install.sh"
# BOX-APPLIED (D-576): the owner's answers were applied by an earlier start that did not reach its last line (the
# window closed, the session dropped). The console's set-up is finished: a new code would never be accepted and the
# wait would never end. Nothing is asked again; what follows the apply is done again.
# H-96 (7097514776): where the install put the administrator's first password and enrolment code (never their values):
# on the terminal, or with no terminal in the root-only file its output names
once_where() {  # from the install's own line (never a value): the file it names, not kept, or the terminal
  local f
  f="$(sed -n 's/.*no terminal to show it on: it is in \(.*\) (root only, 0600).*/\1/p' "$BOX/install.log" 2>/dev/null | tail -1)"
  if [ -n "$f" ]; then echo "not printed above: in $f, root only: read it once, then remove it"
  elif grep -q "enrolment code were not kept" "$BOX/install.log" 2>/dev/null; then
    echo "not printed above and not kept: the install's FAIL lines say why"
  else echo "printed above, on the install's terminal only"; fi
}
if [ -n "$OWNER" ]; then  # D-898: the answers were the install's own; no wizard, no code
  say "unattended: the owner's answers came from $OWNER (no first-run code; the administrator's password and enrolment code are $(once_where))"
elif [ -f "$BOX/applied" ]; then
  say "the owner's answers were applied on $(cat "$BOX/applied"): finishing the set-up (no new code)"
else
cp "$BOX/hardware.json" "$FR/hardware.json" && chmod 600 "$FR/hardware.json" && chown 10001:10001 "$FR/hardware.json" 2>/dev/null || true
HOST="$(json_get "$BOX/answers.json" tls_hostname)"
box_address() {  # OPS-005: the box's first address on its network, for a computer that cannot resolve .local
  { hostname -I 2>/dev/null || true; } | awk '{print $1}'
}
# H-97 (the integrator's ruling 7101844662, H96-09; H-94 (5): a secret read from or written to a place others can
# read): the one-time code is never on stdout, which trialbox-firstrun.service sends to the system journal, and never
# in a file others can read (it was in /etc/issue.d). On stdout only when stdout is a terminal; else on the
# controlling terminal (the Windows installer's window under WSL2, a terminal whose output is piped to a log); with
# no terminal at all (the service at boot), on the box's screen, written to the virtual console directly (/dev/tty0,
# never a serial console a hypervisor may log), and in a root-only file in the home the passwd entry names (0600,
# made new; a link or anything but a regular file at its name refused, never followed). No variable of the caller
# names where the code goes. The file is removed once the owner's answers are in, and replaced by a new code
CODE_FILE=""
code_file() {  # the root-only file's name: the home of the user that runs this, by its passwd entry (never HOME)
  local home
  home="$(getent passwd "$(id -u)" | cut -d: -f6)"
  [ -n "$home" ] && [ -d "$home" ] || return 1
  printf '%s/trialbox-firstrun-code\n' "${home%/}"
}
drop_code_file() {  # rm takes a link away, never what it names
  local f
  f="$(code_file)" || return 0
  rm -f -- "$f" 2>/dev/null || true
}
drop_written_code_file() {  # on a stop: only the file this run wrote (CODE_FILE), never a link planted at the name
  [ -z "$CODE_FILE" ] || rm -f -- "$CODE_FILE" 2>/dev/null || true
}
show_code() {
  local code text addr shown=""
  code="$(python3 -m tools.box code --firstrun "$FR")"
  chown 10001:10001 "$FR/code.json" 2>/dev/null || true
  text="$(printf '\n  TrialBox set-up:  https://%s/login/first-run\n  One-time code:    %s\n' "$HOST" "$code")"
  code=""
  addr="$(box_address)"
  [ -z "$addr" ] || text="$text$(printf '\n  If the name does not open: https://%s/login/first-run (the browser warns about the certificate: it names %s)\n' "$addr" "$HOST")"
  say "open https://$HOST/login/first-run on a computer of the team (or this box) and type the code"
  if [ -t 1 ]; then printf '%s\n\n' "$text"; text=""; return 0; fi
  # the write itself is checked: a terminal that is gone (a hung-up SSH session) falls through to the screen and file
  if { printf '%s\n\n' "$text" >> /dev/tty; } 2>/dev/null; then
    text=""
    echo "    the one-time code is shown on this terminal only: never in this output, which a log or the journal keeps"
    return 0
  fi
  if [ -c /dev/tty0 ] && { : >> /dev/tty0; } 2>/dev/null; then
    printf '%s\n\n' "$text" >> /dev/tty0 2>/dev/null && shown="on this box's screen and "
  fi
  CODE_FILE="$(code_file)" || CODE_FILE=""
  if [ -z "$CODE_FILE" ] || [ -L "$CODE_FILE" ] || { [ -e "$CODE_FILE" ] && [ ! -f "$CODE_FILE" ]; }; then
    # H-94 (5): never followed, never written through
    echo "box-install: ${CODE_FILE:-the home of uid $(id -u)} is a link or not a regular file (or there is no home): the one-time code is not kept there (H-94 (5)); remove it, then: sudo deploy/box-install.sh --firstrun" >&2
    CODE_FILE=""
  else
    rm -f -- "$CODE_FILE"
    if ! (umask 077; set -C; printf '%s\n\n' "$text" > "$CODE_FILE") 2>/dev/null; then
      echo "box-install: $CODE_FILE could not be made new: the one-time code is not kept there (H-94 (5))" >&2
      CODE_FILE=""
    fi
  fi
  text=""
  [ -n "$CODE_FILE" ] || [ -n "$shown" ] \
    || die "no terminal, no screen and no root-only file for the one-time code (above): nothing was shown (H-94 (5)); run it on a terminal: sudo deploy/box-install.sh --firstrun"
  if [ -n "$CODE_FILE" ]; then
    echo "    the one-time code is not in this output (a log or the system journal keeps it): it is ${shown}in $CODE_FILE (root only, 0600). On this box or over SSH: sudo cat $CODE_FILE"
  else
    echo "    the one-time code is not in this output (a log or the system journal keeps it): it is on this box's screen only"
  fi
}
box_preflight() {  # 10K-3 (D-1361): the live preflight the first-run page shows (tb_common.preflight); never stops the set-up
  # an earlier run's lines never stay: a run that fails or is stopped leaves no file, and the page says "not run yet"
  rm -f "$FR/preflight.json"
  local py="${TB_BOX_PREFLIGHT:-}"
  if [ -z "$py" ] && [ -n "${TB_BOX_PY:-}" ]; then
    return 0  # the tests' stand-in for the image (TB_BOX_PY): no checks of this host unless TB_BOX_PREFLIGHT says
  fi
  if [ -z "$py" ] && ! python3 -c 'import yaml' 2>/dev/null; then
    echo "    the preflight is not shown on the set-up page (no python3-yaml on this host): run 'python3 -m tools.trialbox doctor --preflight --env-file deploy/.env' after the set-up"
    return 0
  fi
  local settings=()
  [ ! -f "$ROOT/deploy/settings.yaml" ] || settings=(--settings "$ROOT/deploy/settings.yaml")
  # one check is bounded in the tool (a hung share, a resolver); the whole run here, killed 5 s after its limit
  # shellcheck disable=SC2086 # a command line on purpose (tests)
  PYTHONPATH="$ROOT/libs:$ROOT/services:$ROOT" timeout -k 5 "${TB_BOX_PREFLIGHT_S:-90}" ${py:-python3} -m tools.trialbox \
    doctor --preflight --env-file "$ROOT/deploy/.env" ${settings[@]+"${settings[@]}"} --out "$FR/preflight.json" \
    >/dev/null 2>&1 || true
  [ -f "$FR/preflight.json" ] || echo "    the preflight did not finish in ${TB_BOX_PREFLIGHT_S:-90} s: the set-up page says it has not run"
  chown 10001:10001 "$FR/preflight.json" 2>/dev/null || true
}
box_preflight
rm -f /etc/issue.d/trialbox-firstrun.issue 2>/dev/null || true  # H-97: an earlier version's copy, readable by all
# a run stopped while it waits (the service stopped, a time-out, a reboot, a closed terminal) leaves no code file
trap 'drop_written_code_file' EXIT
trap 'drop_written_code_file; exit 129' HUP  # H-94 not a stop: the signal's own exit, the code file removed
trap 'drop_written_code_file; exit 130' INT  # H-94 not a stop: the signal's own exit, the code file removed
trap 'drop_written_code_file; exit 143' TERM  # H-94 not a stop: the signal's own exit, the code file removed
show_code
while [ ! -f "$FR/answers.json" ]; do
  [ -f "$FR/code.json" ] || { echo "    the code was voided (five wrong codes): a new one"; show_code; }
  sleep "${TB_BOX_POLL_S:-5}"
done
drop_code_file
trap - EXIT HUP INT TERM

# ------------------------------------------------------------------------------------------------ 6. apply
say "applying the owner's answers"
if [ -f "$ROOT/deploy/site/hardening.conf" ] && grep -q '^KEK_BACKEND=passphrase' "$ROOT/deploy/site/hardening.conf" \
   && [ "$(id -u)" = 0 ] && [ -z "${TB_BOX_PY:-}" ]; then
  # deferred at install (no TPM): the keys are sealed now, under the passphrase the owner set on the set-up page (in
  # the tmpfs first-run folder; never written to disk). H-96: it goes to the seal step by a pipe, never exported
  KP_VALUE="$(json_get "$FR/answers.json" kek_passphrase)"
  # H-94 (5): the site keys stay plain without it (H-96's refusal)
  [ -n "$KP_VALUE" ] || die "no passphrase in the owner's answers: the keys stay unsealed (run the wizard again)"
  SEC_DIR="${TB_SECRETS_HOST_DIR:-$(docker volume inspect -f '{{.Mountpoint}}' "${COMPOSE_PROJECT_NAME:-trialbox}_tb-secrets")}"
  printf '%s\n' "$KP_VALUE" | TB_IMAGE="$IMAGE_PY" sh deploy/hardening/seal_keys.sh --secrets "$SEC_DIR" \
    --conf "$ROOT/deploy/site/hardening.conf" --kek-passphrase-stdin --record deploy/site/kek-backend \
    || die "the site keys could not be sealed (above)"  # H-94 (5): H-96's refusal
  KP_VALUE=""
  # H-77 (F-22): the back end is the one seal_keys.sh recorded (deploy/site/kek-backend, kept when the wizard rewrites
  # deploy/.env), copied as it is (never worked out here) to deploy/.env, where the host check reads it. Without a
  # record: deploy/.env is left as it is. The same block is in install.sh and in
  # box-install.sh's deferred seal; a test keeps the two identical
  KEK_USED=""; [ -f deploy/site/kek-backend ] && KEK_USED="$(tr -d ' \r\t\n' < deploy/site/kek-backend)"
  case "$KEK_USED" in
    tpm|shamir|passphrase)
      { [ -f deploy/.env ] && [ ! -L deploy/.env ]; } \
        || die "deploy/.env is missing or a link: TB_KEK_BACKEND=$KEK_USED was not written (put the file back, then run this again)"  # H-94 (5): the file that holds the box's secrets
      [ -z "$(tail -c 1 deploy/.env)" ] || echo >> deploy/.env  # a last line without its newline is not joined
      { sed -i '/^[[:space:]]*\(export[[:space:]]\+\)\?TB_KEK_BACKEND=/d' deploy/.env \
          && echo "TB_KEK_BACKEND=$KEK_USED" >> deploy/.env; } || die "deploy/.env: TB_KEK_BACKEND=$KEK_USED could not be written"  # H-94 (5): the file that holds the box's secrets
      echo "    the KEK back end that sealed the keys: $KEK_USED (recorded by seal_keys.sh; deploy/.env TB_KEK_BACKEND)" ;;
    *) echo "    note: no record of the KEK back end in deploy/site/kek-backend (above): deploy/.env not changed" >&2 ;;
  esac
fi
TZ_NEW="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tz"])' "$FR/answers.json")"
if [ -n "${TB_BOX_PY:-}" ]; then APPLY=(--firstrun "$FR" --hardware "$BOX/hardware.json" --deploy "$ROOT/deploy")
else APPLY=(--firstrun /fr --hardware /d/site/box/hardware.json --deploy /d); fi  # the image's mounts (box_py)
box_py apply "${APPLY[@]}" || stop_or_warn apply "the owner's answers (the install's provisional settings stay)" "the owner's answers could not be applied (above)"  # D-1091
date -u +%FT%TZ > "$BOX/applied"  # D-576: from here a new start does not ask again
if [ "$WSL2" = 1 ]; then
  echo "    the host's time zone is not set here: Windows keeps the clock and the time zone (the site's zone $TZ_NEW is in the settings)"
elif [ "$(id -u)" = 0 ] && [ -z "${TB_BOX_PY:-}" ] && command -v timedatectl >/dev/null; then
  timedatectl set-timezone "$TZ_NEW" || echo "box-install: warning: the host's time zone is not $TZ_NEW" >&2
fi
fi  # the answers were not applied before
if [ -n "$OWNER" ]; then  # D-898: the host's zone from the answers file, then the mark (a later --firstrun asks nothing)
  ZONE="$(json_get "$BOX/answers.json" tz)"
  if [ "$WSL2" = 0 ] && [ -n "$ZONE" ] && [ "$(id -u)" = 0 ] && [ -z "${TB_BOX_PY:-}" ] && command -v timedatectl >/dev/null; then
    timedatectl set-timezone "$ZONE" || echo "box-install: warning: the host's time zone is not $ZONE" >&2
  fi
  date -u +%FT%TZ > "$BOX/applied"
fi
# FINISH-GATE (10K-4, D-1390): the owner's answers are applied. tools/trialbox/finish_check.py judges each folder they
# name by what it is (the mount table and /sys): a PRODUCTION box does not finish (no restart on them, no "ready")
# without a backup target shown to be off the box and the hospital's audit share as its anchor folder, and no box gives
# the console an anchor folder the rule refuses. Then that one folder is mounted into the console, read-only, as
# install.sh mounts it (D-638), once the console's own image has shown it can read it (as install.sh asks it).
# Unattended (--answers), install.sh ran the same check before it started the stack.
# D-1091 (H94-03): the finish check protects none of the five, so on a PoC box it warns; a warning sets ANCHOR_UNSAFE:
# the anchor folder is not mounted into the console and root's nightly cron signs no head into it
ANCHOR_UNSAFE=0
ANCHOR_SKIPS="the anchor folders: not mounted into the console, no nightly signed head (the cron writes the log retention only)"
if [ -z "$OWNER" ]; then
  rc=0; ANCHORS="$(python3 -m tools.trialbox finish-check --deploy "$ROOT/deploy" --print-anchors)" || rc=$?
  [ "$rc" = 0 ] || [ "$rc" = 1 ] || { stop_or_warn finish-did-not-run "$ANCHOR_SKIPS" "the finish check did not run (exit $rc, above): the set-up is not finished; nothing was restarted"; ANCHOR_UNSAFE=1; }
  [ "$rc" = 0 ] || [ "$ANCHOR_UNSAFE" = 1 ] || { stop_or_warn finish-gate "$ANCHOR_SKIPS" "the set-up is not finished (above). Mount the disk or the share at the folder the owner named; or, when a folder was typed wrongly or is mounted elsewhere, change the setting each line names in $ROOT/deploy/.env (the first-run page does not open again: the answers are applied). Then: sudo deploy/box-install.sh --firstrun"; ANCHOR_UNSAFE=1; }
  if [ "$ANCHOR_UNSAFE" = 0 ] && { [ -z "${TB_BOX_PY:-}" ] || [ -n "${TB_BOX_DOCKER:-}" ]; }; then  # the tests' stand-in for the image: TB_BOX_DOCKER
    while IFS= read -r anchor; do
      [ -n "$anchor" ] || continue
      # shellcheck disable=SC2086 # a command line on purpose (tests)
      # H-94 not a stop: the exit inside the probe container's script is the probe's own answer
      ${TB_BOX_DOCKER:-docker} run --rm --network none -v "$anchor:/anchor:ro" "$IMAGE_PY" sh -c \
        'test -r /anchor && test -x /anchor && for d in heads keys; do [ ! -e "/anchor/$d" ] || { test -r "/anchor/$d" && test -x "/anchor/$d"; } || exit 1; done' </dev/null \
        || { stop_or_warn anchor-read "the anchor folder's mount into the console" "the console's user cannot read $anchor (or its heads/ or keys/): the audit page would find no signed head. Make the folder readable (chmod a+rx), then: sudo deploy/box-install.sh --firstrun"; ANCHOR_READ=0; }
    done <<< "$ANCHORS"
  fi
  if [ "$ANCHOR_UNSAFE" = 0 ] && [ "${ANCHOR_READ:-1}" = 1 ]; then
    python3 -m tools.trialbox finish-check --deploy "$ROOT/deploy" --mount-anchors >/dev/null \
      || stop_or_warn anchor-mount "" "the audit anchor folder is not mounted into the console (above); then: sudo deploy/box-install.sh --firstrun"
  fi
  if [ "$ANCHOR_UNSAFE" = 1 ] && [ -f "${TB_CRON_DIR:-/etc/cron.d}/trialbox-retention" ]; then  # no head into a refused folder
    sed -i 's/; python3 -m tools.trialbox audit-sign//' "${TB_CRON_DIR:-/etc/cron.d}/trialbox-retention"
  fi
fi
HOST="$(json_get "$BOX/answers.json" tls_hostname)"  # the box's name the owner chose
# OPS-005: the name the box prints resolves on the clinic's network: the host takes the owner's name and the mDNS
# responder answers it (the firewall lets UDP 5353 in from the box's network when hardening.conf says MDNS=on)
if [ "$WSL2" = 0 ] && [ "$(id -u)" = 0 ] && [ -z "${TB_BOX_PY:-}" ] && [ "${HOST%.local}" != "$HOST" ]; then
  if command -v hostnamectl >/dev/null; then
    hostnamectl set-hostname "${HOST%.local}" || echo "box-install: warning: the host name is not ${HOST%.local}" >&2
  fi
  if command -v avahi-daemon >/dev/null && command -v systemctl >/dev/null; then
    systemctl enable --now avahi-daemon >/dev/null 2>&1 || echo "box-install: warning: avahi-daemon did not start" >&2
  else
    echo "box-install: warning: no mDNS responder (avahi-daemon): $HOST will not resolve on the clinic's computers; install avahi-daemon (the box's media) or use the address printed above" >&2
  fi
fi
chown "$(id -u):10001" deploy/settings.yaml 2>/dev/null && chmod 640 deploy/settings.yaml
# shellcheck disable=SC2086 # a command line on purpose (tests)
${TB_BOX_COMPOSE:-docker compose --project-directory deploy} up -d --wait || stop_or_warn stack-restart "" "the stack did not restart on the new settings"  # D-1091
if grep -q '^TB_BACKUP_TARGETS=.' deploy/.env && [ -z "${TB_BOX_PY:-}" ]; then
  python3 -m tools.trialbox backup-install --deploy deploy 2>&1 | sed 's/^/    /' \
    || echo "box-install: warning: the backup schedule is not installed yet (the health page says why; T-730)" >&2
fi
rm -f "$BOX/prepared"
# SEED (M1): the sample hospital and study on a box that is not in use, what the network and disks suggest for the page
# "Information still needed"; neither stops the install, and each can be run again
if [ -z "${TB_BOX_PY:-}" ] || [ -n "${TB_BOX_SEED:-}" ]; then
  say "site seed"
  # shellcheck disable=SC2086 # a command line on purpose (tests)
  ${TB_BOX_SEED:-python3 -m tools.site_seed run --deploy "$ROOT/deploy"} 2>&1 | sed 's/^/    /' \
    || echo "box-install: warning: the site seed did not finish (above): sudo python3 -m tools.site_seed run" >&2
  python3 -m tools.box propose --deploy "$ROOT/deploy" 2>/dev/null \
    || echo "box-install: warning: the network and disks could not be read for proposals" >&2
fi
# ---- end of SEED
say "host check"
set +e
# shellcheck disable=SC2086 # a command line on purpose (tests)
exec 8>&1
HC_OUT="$(${TB_BOX_HOST_CHECK:-sh "$ROOT/deploy/check_host.sh"} | tee -a /dev/fd/8)"  # -a: as install.sh (a file is not emptied)
rc=$?
exec 8>&-
set -e
# H-94 (5): its FAIL lines of a kept refusal (tb_kept_fails: a secret's mode, (2), (3)) end the run with its code on
# every box, as install.sh keeps them FAIL lines (review M-1 of #1396; review H-1 of #1430)
SECRET_FAIL="$(printf '%s\n' "$HC_OUT" | tb_kept_fails)"
if [ -n "$OWNER" ]; then
  printf '\n  TrialBox is ready: https://%s  (sign in as admin with the password and enrolment code %s)\n' "$HOST" "$(once_where)"
else
  printf '\n  TrialBox is ready: https://%s  (sign in with the account you made in the set-up)\n' "$HOST"
fi
# H-94: the host check's FAIL lines (above) end the run with its code; on a PoC box a warning and a line of the list
[ "$rc" = 0 ] || [ -z "$SECRET_FAIL" ] || exit "$rc"  # H-94 (5): a secret's file or key where others can read it
[ "$rc" = 0 ] || stop_or_warn --rc "$rc" --silent host-check "" "the host check reported FAIL lines (above)"
exit 0
