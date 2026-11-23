#!/usr/bin/env bash
# The box installer (T-729, D-466; plan v6.1 OD-11, OD-13): one installer for a GPU workstation or a DGX Spark, set up
# by its owner, with no shell knowledge and no question an IT department would be asked.
#
#   sudo deploy/box-install.sh trialbox-<version>.tar [--yes]       # hardware the site bought: install, then the wizard
#   sudo deploy/box-install.sh trialbox-<version>.tar --prepare      # Aimedics, before shipping: stop before the wizard
#   sudo deploy/box-install.sh trialbox-<version>.tar --rehearsal    # a rehearsal box: TEST, stand-ins (D-726)
#   deploy/box-install.sh --firstrun                                 # the prepared box's first boot (trialbox-firstrun.service)
#   sudo deploy/box-install.sh trialbox-<version>.tar --answers owner.json   # unattended (D-898): the hospital's install
#
# What it does, in order:
#   1. hardware: python3 -m tools.box detect (the GPU, memory, disks, TPM, the box's network); shown, and the one
#      question on the terminal: is this the machine? (--yes skips it)
#   2. plan:     python3 -m tools.box plan --provisional: the GPU profile from the card (deploy/gpu_profile.sh), memory
#                caps from the RAM (OD-10), TLS internal under the box's name, deploy/site/hardening.conf (KEK tpm, or a
#                passphrase the owner sets on a board without a TPM; the input firewall open to the box's own network)
#   3. install:  deploy/install.sh with the plan's answers and flags, TB_BOX=1 (the first-run folder for the console, no
#                printed administrator password) and, without a TPM, TB_BOX_DEFER_SEAL=1
#   4. --prepare stops here (deploy/site/box/prepared; trialbox-firstrun.service enabled for the site's first boot)
#   5. first run: a one-time code (tb_common.firstrun) in /run/trialbox-firstrun (tmpfs), printed with the address and
#      written to /etc/issue.d (the box's own screen); it waits until the owner has finished the wizard. Five wrong
#      codes void a code: a new one is shown
#   6. apply:    the keys sealed under the owner's passphrase when deferred; python -m tools.box apply in the image (the
#                owner's answers into settings.yaml and deploy/.env, the install's passwords kept); the host's time zone;
#                the stack restarted on the new settings; the backup schedule; the host check with `trialbox doctor`
# Unattended (--answers, D-898): the owner's answers come from a JSON file (the first-run form's fields, flat or
# nested; `environment` PRODUCTION or VALIDATION) instead of the first-run wizard. No question, no code, no wait: the
# plan is made from those answers, the install makes the first administrator as the IT form does (TB_BOX=0: its
# password and enrolment code printed once), then the time zone, the backup schedule and the host check. The file
# never holds a password or a passphrase (refused); a board without a TPM takes TB_KEK_PASSPHRASE from the
# environment and the keys are sealed at the install. In your own Bash shell, set bundle to the signed bundle path:
#   IFS= read -rs TB_KEK_PASSPHRASE; export TB_KEK_PASSPHRASE
#   sudo --preserve-env=TB_KEK_PASSPHRASE deploy/box-install.sh "$bundle" --answers owner.json
#   unset TB_KEK_PASSPHRASE
# sudo VAR=value command shows the value in the process list.
# Knobs for the tests and the rehearsal only: TB_BOX_HARDWARE (a hardware.json instead of detecting), TB_BOX_INSTALL
# (the install command), TB_BOX_PY (a python command instead of the image), TB_BOX_COMPOSE (the compose command),
# TB_BOX_HOST_CHECK (the host check command), TB_ISSUE_DIR, TB_FIRSTRUN_HOST_DIR, TB_BOX_POLL_S, TB_BOX_NO_ROOT=1,
# TB_SYSTEMD=0 (as install.sh), TB_BOX_PREFLIGHT (the python command that runs the first-run page's preflight, even
# with TB_BOX_PY; 10K-3), TB_BOX_PREFLIGHT_S (its time limit, 90 s) and TB_BOX_DOCKER (the docker command that asks
# the console's image whether it can read the audit anchor folder; 10K-4).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
BUNDLE=""; YES=0; PREPARE=0; FIRSTRUN=0; REHEARSAL=0; OWNER=""
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
  if [ ! -L "$_f" ] && { [ -z "$_o" ] || [ "$_o" = 0 ] || [ "$_o" = "$(id -u)" ]; } && mkdir -p "${_f%/*}" 2>/dev/null \
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
  printf '%s: warning (PoC box, H-94): %s%s\n' "$TB_STOP_WHO" "$*" "${_skipped:+; skipped: $_skipped}" >&2
  tb_stop_list "$_key" "$_skipped" "$*"
  return 0
}
# ---- end of STOP-OR-WARN
# H-94: this run's command line (--rehearsal) is read once before the arguments are; box-install.sh has no
# --environment (the owner's answers file is not read for it: on a fresh box it stays PRODUCTION, the stricter)
TB_STOP_WHO=box-install; TB_STOP_FILE=box-install.sh; TB_STOP_DEPLOY="$ROOT/deploy"; TB_STOP_ARG_ENV=""
TB_STOP_REHEARSAL=0
_clear=1
for _a in "$@"; do
  [ "$_a" != --rehearsal ] || TB_STOP_REHEARSAL=1
  [ "$_a" != --firstrun ] || _clear=0
done
# the list is this install's (review L-3 of #1396): emptied when a box install starts, kept by --firstrun (it finishes
# the same install) and by install.sh run from here (TB_STOP_KEEP_LIST=1). rm takes a link away, never what it names
[ "$_clear" = 0 ] || rm -f -- "$TB_STOP_DEPLOY/site/poc-stops.jsonl" 2>/dev/null || true
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) YES=1 ;;
    --prepare) PREPARE=1 ;;
    --firstrun) FIRSTRUN=1 ;;
    --rehearsal) REHEARSAL=1 ;;
    --answers) if [ -n "${2:-}" ] && [ "${2#-}" = "$2" ]; then OWNER="$2"; shift
      else stop_or_warn --rc 2 answers-value "--answers (ignored)" "--answers needs the owner's answers file (JSON)"; fi ;;
    -h|--help) sed -n '2,/^set -euo pipefail/{ /^set -euo pipefail/!p; }' "$0"; exit 0 ;;
    -*) stop_or_warn --rc 2 unknown-option "the option $1 (ignored)" "unknown option $1" ;;
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
IMAGE_PY="${TB_IMAGE:-trialbox-py:1.0.0}"
FR="${TB_FIRSTRUN_HOST_DIR:-/run/trialbox-firstrun}"
BOX="$ROOT/deploy/site/box"
ISSUE="${TB_ISSUE_DIR:-/etc/issue.d}/trialbox-firstrun.issue"
# BOX-WSL2 (D-571): under WSL2 (the Windows form, plan v7.2 section 2.3) no screen shows /etc/issue.d, and Windows
# keeps the clock and the time zone. The kernel's release says so; TB_BOX_WSL2=0|1 sets it for a test.
WSL2=0; case "$(uname -r)" in *[Mm]icrosoft*) WSL2=1 ;; esac
case "${TB_BOX_WSL2:-}" in "") ;; 0|1) WSL2="$TB_BOX_WSL2" ;; *) stop_or_warn wsl2-value "TB_BOX_WSL2 (the kernel's word: $WSL2)" "TB_BOX_WSL2 is 0 or 1, not '$TB_BOX_WSL2'" ;; esac
export PYTHONPATH="$ROOT/libs:$ROOT"
[ "${TB_BOX_NO_ROOT:-0}" = 1 ] || [ "$(id -u)" = 0 ] || die "run it as root (sudo deploy/box-install.sh ...)"  # H-94 (4)
command -v python3 >/dev/null || stop_or_warn python3-missing "every step that runs python3 (each fails where it runs)" "python3 is missing on this machine (Ubuntu 24.04 has it)"  # D-1091
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
             "(the administrator's password is made and printed by the install; TB_KEK_PASSPHRASE comes from the "
             "environment)")
EOP
    if [ "$(json_get "$BOX/hardware.json" tpm)" != True ] && { [ -z "${TB_KEK_PASSPHRASE:-}" ] || [ "${#TB_KEK_PASSPHRASE}" -lt 12 ]; }; then
      # H-94 (5): the passphrase that seals the site keys (H-96's part; unchanged here)
      die "no usable TPM: TB_KEK_PASSPHRASE must contain at least 12 characters; follow the Bash example in box-install.sh --help (nothing was changed)"
    fi
    YES=1
  fi
  if [ "$YES" != 1 ] && [ -t 0 ]; then
    printf 'Is this the machine to install TrialBox on? [Y/n] '; read -r ans
    case "$ans" in n|N) die "stopped: nothing was changed" ;; esac  # H-94 not a stop: the operator's own answer
  fi
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
  [ "$REHEARSAL" = 1 ] && INSTALL_ARGS+=(--rehearsal)  # D-726: a rehearsal box, handed on to install.sh
  DEFER=0; [ "$(json_get "$BOX/hardware.json" tpm)" = True ] || [ -n "$OWNER" ] || DEFER=1
  INBOX=1; [ -z "$OWNER" ] || INBOX=0  # D-898: unattended, the install makes the first administrator (the IT form)
  echo "    install: ${INSTALL_ARGS[*]}"
  [ "$DEFER" = 0 ] || echo "    no TPM: the site keys are sealed after the wizard, under the owner's passphrase"
  # ---------------------------------------------------------------------------------------------- 3. install
  set +e
  # shellcheck disable=SC2086 # TB_BOX_INSTALL is a command line on purpose (tests)
  TB_STOP_KEEP_LIST=1 TB_BOX="$INBOX" TB_BOX_DEFER_SEAL="$DEFER" ${TB_BOX_INSTALL:-bash "$ROOT/deploy/install.sh"} "$BUNDLE" \
    --answers "$BOX/answers.json" "${INSTALL_ARGS[@]}" --yes 2>&1 | tee "$BOX/install.log"
  rc="${PIPESTATUS[0]}"
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
if [ -n "$OWNER" ]; then  # D-898: the answers were the install's own; no wizard, no code
  say "unattended: the owner's answers came from $OWNER (no first-run code; the administrator's password and enrolment code are printed above)"
elif [ -f "$BOX/applied" ]; then
  say "the owner's answers were applied on $(cat "$BOX/applied"): finishing the set-up (no new code)"
else
cp "$BOX/hardware.json" "$FR/hardware.json" && chmod 600 "$FR/hardware.json" && chown 10001:10001 "$FR/hardware.json" 2>/dev/null || true
HOST="$(json_get "$BOX/answers.json" tls_hostname)"
box_address() {  # OPS-005: the box's first address on its network, for a computer that cannot resolve .local
  { hostname -I 2>/dev/null || true; } | awk '{print $1}'
}
show_code() {
  CODE="$(python3 -m tools.box code --firstrun "$FR")"
  chown 10001:10001 "$FR/code.json" 2>/dev/null || true
  local text addr
  text="$(printf '\n  TrialBox set-up:  https://%s/login/first-run\n  One-time code:    %s\n' "$HOST" "$CODE")"
  addr="$(box_address)"
  [ -z "$addr" ] || text="$text$(printf '\n  If the name does not open: https://%s/login/first-run (the browser warns about the certificate: it names %s)\n' "$addr" "$HOST")"
  if [ "$WSL2" = 0 ]; then  # the box's own screen; under WSL2 the Windows installer's window shows this output
    mkdir -p "$(dirname "$ISSUE")"
    printf '%s\n\n' "$text" > "$ISSUE"
  fi
  say "open https://$HOST/login/first-run on a computer of the team (or this box) and type the code"
  printf '%s\n\n' "$text"
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
show_code
while [ ! -f "$FR/answers.json" ]; do
  [ -f "$FR/code.json" ] || { echo "    the code was voided (five wrong codes): a new one"; show_code; }
  sleep "${TB_BOX_POLL_S:-5}"
done
[ "$WSL2" = 1 ] || rm -f "$ISSUE"

# ------------------------------------------------------------------------------------------------ 6. apply
say "applying the owner's answers"
if [ -f "$ROOT/deploy/site/hardening.conf" ] && grep -q '^KEK_BACKEND=passphrase' "$ROOT/deploy/site/hardening.conf" \
   && [ "$(id -u)" = 0 ] && [ -z "${TB_BOX_PY:-}" ]; then
  # deferred at install (no TPM): the keys are sealed now, under the passphrase the owner set (never written to disk)
  TB_KEK_PASSPHRASE="$(json_get "$FR/answers.json" kek_passphrase)"
  # H-94 (5): the site keys stay plain without it (H-96's part; unchanged here)
  [ -n "$TB_KEK_PASSPHRASE" ] || die "no passphrase in the owner's answers: the keys stay unsealed (run the wizard again)"
  export TB_KEK_PASSPHRASE
  SEC_DIR="${TB_SECRETS_HOST_DIR:-$(docker volume inspect -f '{{.Mountpoint}}' "${COMPOSE_PROJECT_NAME:-trialbox}_tb-secrets")}"
  TB_IMAGE="$IMAGE_PY" sh deploy/hardening/seal_keys.sh --secrets "$SEC_DIR" --conf "$ROOT/deploy/site/hardening.conf" \
    || die "the site keys could not be sealed (above)"  # H-94 (5): H-96's part, unchanged
  unset TB_KEK_PASSPHRASE
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
say "host check"
set +e
# shellcheck disable=SC2086 # a command line on purpose (tests)
${TB_BOX_HOST_CHECK:-sh "$ROOT/deploy/check_host.sh"}
rc=$?
set -e
if [ -n "$OWNER" ]; then
  printf '\n  TrialBox is ready: https://%s  (sign in as admin with the password and enrolment code printed above)\n' "$HOST"
else
  printf '\n  TrialBox is ready: https://%s  (sign in with the account you made in the set-up)\n' "$HOST"
fi
# H-94: the host check's FAIL lines (above) end the run with its code; on a PoC box a warning and a line of the list
[ "$rc" = 0 ] || stop_or_warn --rc "$rc" --silent host-check "" "the host check reported FAIL lines (above)"
exit 0
