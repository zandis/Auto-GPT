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
# TB_BOX_HOST_CHECK (the host check command), TB_ISSUE_DIR, TB_FIRSTRUN_HOST_DIR, TB_BOX_POLL_S, TB_BOX_NO_ROOT=1,
# TB_SYSTEMD=0 (as install.sh), TB_BOX_PREFLIGHT (the python command that runs the first-run page's preflight, even
# with TB_BOX_PY; 10K-3), TB_BOX_PREFLIGHT_S (its time limit, 90 s) and TB_BOX_DOCKER (the docker command that asks
# the console's image whether it can read the audit anchor folder; 10K-4).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
BUNDLE=""; YES=0; PREPARE=0; FIRSTRUN=0; REHEARSAL=0; OWNER=""
PP_FILE=""; PP_KEEP=0; PP_STDIN=0  # H-96: the KEK passphrase's two ways in (the KEK-INPUT block)
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) YES=1 ;;
    --prepare) PREPARE=1 ;;
    --firstrun) FIRSTRUN=1 ;;
    --rehearsal) REHEARSAL=1 ;;
    --answers) [ -n "${2:-}" ] && [ "${2#-}" = "$2" ] || { echo "box-install: --answers needs the owner's answers file (JSON)" >&2; exit 2; }
      OWNER="$2"; shift ;;
    --kek-passphrase-file) PP_FILE="${2:-}"; shift ;;
    --keep-kek-passphrase-file) PP_KEEP=1 ;;
    --kek-passphrase-stdin) PP_STDIN=1 ;;
    -h|--help) sed -n '2,/^set -euo pipefail/{ /^set -euo pipefail/!p; }' "$0"; exit 0 ;;
    -*) echo "box-install: unknown option $1" >&2; exit 2 ;;
    *) BUNDLE="$1" ;;
  esac
  shift
done
if [ "$REHEARSAL" = 1 ] && [ "$PREPARE" = 1 ]; then echo "box-install: --rehearsal with --prepare: a prepared box goes to a site" >&2; exit 2; fi
if [ -n "$OWNER" ] && [ "$PREPARE$REHEARSAL$FIRSTRUN" != 000 ]; then
  echo "box-install: --answers is the site's unattended install: not with --prepare, --rehearsal or --firstrun" >&2; exit 2
fi
if [ "$REHEARSAL" = 1 ] && [ "$FIRSTRUN" = 1 ]; then echo "box-install: --rehearsal with --firstrun: the first run finishes the box as it was installed" >&2; exit 2; fi
say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf 'box-install: %s\n' "$*" >&2; exit 1; }
# KEK-INPUT (H-96, F-45; the integrator's ruling 7094934985): never from the environment (refused, before
# anything); only with --answers (the wizard's box takes it on the set-up page). A file goes on to install.sh by its
# name (its seal step removes it); a passphrase read from stdin by a pipe at fd 8. KP_VALUE is never exported
KP_WHO=box-install
# ---- KEK-INPUT functions (H-96, F-45; the integrator's ruling 7094934985). The same lines are in deploy/install.sh,
# deploy/box-install.sh and deploy/hardening/seal_keys.sh; a test holds the three together. The passphrase comes from
#   --kek-passphrase-file FILE  one line of a regular file (not a link) owned by root (the user that runs this), mode
#                               0600; removed once the keys are sealed, unless --keep-kek-passphrase-file
#   --kek-passphrase-stdin      one line on stdin; on a terminal it is asked twice, not shown
# and never from the environment: TB_KEK_PASSPHRASE or TB_KEK_NEW_PASSPHRASE there is refused, with or without sudo
# (sudo writes a variable it keeps, with its value, to the system journal). The value lives in KP_VALUE, never
# exported, and goes on by a pipe: never an argument, never a sudo environment, never a file. Nothing prints it.
KP_VALUE=""
kp_die() { printf '%s: %s\n' "$KP_WHO" "$*" >&2; exit 1; }
kp_refuse_env() {  # an empty variable is dropped
  for kp_var in TB_KEK_PASSPHRASE TB_KEK_NEW_PASSPHRASE; do
    eval "kp_set=\${$kp_var:+yes}"
    [ "$kp_set" != yes ] || { printf '%s: %s is set in the environment: refused, nothing was changed. A passphrase given by the environment can be in the system journal (sudo logs the variables it keeps, with their values): treat that passphrase as exposed and rotate it (RUNBOOK §23, rotate the KEK passphrase). Give it in a file only root can read: --kek-passphrase-file FILE (a regular file, owned by root, mode 0600), or on stdin: --kek-passphrase-stdin. Then unset %s.\n' "$KP_WHO" "$kp_var" "$kp_var" >&2; exit 2; }
  done
  unset TB_KEK_PASSPHRASE TB_KEK_NEW_PASSPHRASE kp_set kp_var
}
kp_check_value() {  # one line, not empty, no control character (the image and the host read it alike)
  [ -n "$KP_VALUE" ] || kp_die "the KEK passphrase from $1 is empty: nothing was changed"
  case "$KP_VALUE" in *[[:cntrl:]]*) KP_VALUE=""; kp_die "the KEK passphrase from $1 holds a line break or another control character: write it again on one line; nothing was sealed" ;; esac
}
kp_read_file() {  # refused unless a regular file, not a link, owned by the user that runs this (root), mode 0600, one line
  kp_fix="write the passphrase on one line of a regular file owned by root with mode 0600 (sudo install -m 0600 -o root -g root /dev/null FILE, then write it there); nothing was changed"
  [ ! -L "$1" ] || kp_die "--kek-passphrase-file $1 is a link: refused; $kp_fix"
  [ -f "$1" ] || kp_die "--kek-passphrase-file $1 is not a regular file: refused; $kp_fix"
  [ "$(stat -c %u "$1")" = "$(id -u)" ] || kp_die "--kek-passphrase-file $1 is owned by uid $(stat -c %u "$1"), not root (the user that runs this): refused; $kp_fix"
  [ "$(stat -c %a "$1")" = 600 ] || kp_die "--kek-passphrase-file $1 has mode $(stat -c %a "$1"), not 0600: refused; $kp_fix"
  [ "$(tail -c 1 "$1" | wc -l)" = "$(wc -l < "$1")" ] \
    || kp_die "--kek-passphrase-file $1 holds a line break or another control character: write it again on one line; nothing was sealed"
  KP_VALUE=""; IFS= read -r KP_VALUE < "$1" || [ -n "$KP_VALUE" ] || :
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
kp_remove_file() { shred -u -- "$1" 2>/dev/null || rm -f -- "$1"; [ ! -e "$1" ] || kp_die "the passphrase file $1 could not be removed: remove it yourself"; }
# ---- end of KEK-INPUT functions
kp_refuse_env
if [ -n "$PP_FILE" ] || [ "$PP_KEEP" = 1 ] || [ "$PP_STDIN" = 1 ]; then
  [ -n "$OWNER" ] || die "--kek-passphrase-file and --kek-passphrase-stdin go with --answers (the unattended install); otherwise the owner sets the passphrase on the set-up page. Nothing was changed"
  [ -z "$PP_FILE" ] || [ "$PP_STDIN" = 0 ] || die "--kek-passphrase-file and --kek-passphrase-stdin: give one; nothing was changed"
  [ "$PP_KEEP" = 0 ] || [ -n "$PP_FILE" ] || die "--keep-kek-passphrase-file goes with --kek-passphrase-file"
  case "$PP_FILE" in ""|/*) ;; *) die "--kek-passphrase-file: give the file's full path (/root/...): nothing was changed" ;; esac
  if [ -n "$PP_FILE" ]; then kp_read_file "$PP_FILE"; else kp_read_stdin; fi
fi
PP_INSTALL=()  # what install.sh is given: the file's name, or the pipe at fd 8
if [ -n "$PP_FILE" ]; then
  PP_INSTALL=(--kek-passphrase-file "$PP_FILE"); [ "$PP_KEEP" = 0 ] || PP_INSTALL+=(--keep-kek-passphrase-file)
elif [ -n "$KP_VALUE" ]; then PP_INSTALL=(--kek-passphrase-fd 8); fi
# ---- end of KEK-INPUT
IMAGE_PY="${TB_IMAGE:-trialbox-py:1.0.0}"
FR="${TB_FIRSTRUN_HOST_DIR:-/run/trialbox-firstrun}"
BOX="$ROOT/deploy/site/box"
ISSUE="${TB_ISSUE_DIR:-/etc/issue.d}/trialbox-firstrun.issue"
# BOX-WSL2 (D-571): under WSL2 (the Windows form, plan v7.2 section 2.3) no screen shows /etc/issue.d, and Windows
# keeps the clock and the time zone. The kernel's release says so; TB_BOX_WSL2=0|1 sets it for a test.
WSL2=0; case "$(uname -r)" in *[Mm]icrosoft*) WSL2=1 ;; esac
case "${TB_BOX_WSL2:-}" in "") ;; 0|1) WSL2="$TB_BOX_WSL2" ;; *) die "TB_BOX_WSL2 is 0 or 1, not '$TB_BOX_WSL2'" ;; esac
export PYTHONPATH="$ROOT/libs:$ROOT"
[ "${TB_BOX_NO_ROOT:-0}" = 1 ] || [ "$(id -u)" = 0 ] || die "run it as root (sudo deploy/box-install.sh ...)"
command -v python3 >/dev/null || die "python3 is missing on this machine (Ubuntu 24.04 has it)"
# a bare Ubuntu box gets Docker, the NVIDIA toolkit and the host's libraries from the media first (OPS-006, D-966)
[ -n "${TB_BOX_PY:-}" ] || command -v docker >/dev/null \
  || die "Docker is missing on this machine: prepare it from the media first (sudo <media>/linux/box-prepare.sh <media> --pub <the vendor key given to you>; RUNBOOK §16)"
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
  [ -n "$BUNDLE" ] || die "usage: deploy/box-install.sh trialbox-<version>.tar [--prepare | --rehearsal] [--yes]"
  [ -f "$BUNDLE" ] || die "no such bundle: $BUNDLE"
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
    [ -f "$OWNER" ] || die "no such answers file: $OWNER (nothing was changed)"
    python3 - "$OWNER" <<'EOP' || die "the owner's answers file is refused (above): nothing was changed"
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
    if [ "$(json_get "$BOX/hardware.json" tpm)" != True ] && [ "${#KP_VALUE}" -lt 12 ]; then
      die "no usable TPM: the KEK passphrase (--kek-passphrase-file or --kek-passphrase-stdin) must contain at least 12 characters; follow the example in box-install.sh --help (nothing was changed)"
    fi
    YES=1
  fi
  if [ "$YES" != 1 ] && [ -t 0 ]; then
    printf 'Is this the machine to install TrialBox on? [Y/n] '; read -r ans
    case "$ans" in n|N) die "stopped: nothing was changed" ;; esac
  fi
  # ---------------------------------------------------------------------------------------------- 2. plan
  say "plan from the hardware"
  rm -f "$BOX/applied"  # D-576: a new install: the answers are provisional again and the wizard is due
  if [ -n "$OWNER" ]; then
    ARGS_LINE="$(python3 -m tools.box plan --hardware "$BOX/hardware.json" --owner "$OWNER" --deploy "$ROOT/deploy" --out "$BOX/answers.json" | tail -1)" \
      || die "the owner's answers do not parse (above): nothing was changed"
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
  TB_BOX="$INBOX" TB_BOX_DEFER_SEAL="$DEFER" ${TB_BOX_INSTALL:-bash "$ROOT/deploy/install.sh"} "$BUNDLE" \
    --answers "$BOX/answers.json" "${INSTALL_ARGS[@]}" ${PP_INSTALL[@]+"${PP_INSTALL[@]}"} --yes \
    8< <(printf '%s\n' "$KP_VALUE") 2>&1 | tee "$BOX/install.log"
  rc="${PIPESTATUS[0]}"
  KP_VALUE=""
  set -e
  # a FAIL list at the end (backups not yet placed, say) leaves the stack running; a stop half-way does not
  if [ "$rc" != 0 ] && ! grep -q "TrialBox is running" "$BOX/install.log"; then
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
  # deferred at install (no TPM): the keys are sealed now, under the passphrase the owner set on the set-up page (in
  # the tmpfs first-run folder; never written to disk). H-96: it goes to the seal step by a pipe, never exported
  KP_VALUE="$(json_get "$FR/answers.json" kek_passphrase)"
  [ -n "$KP_VALUE" ] || die "no passphrase in the owner's answers: the keys stay unsealed (run the wizard again)"
  SEC_DIR="${TB_SECRETS_HOST_DIR:-$(docker volume inspect -f '{{.Mountpoint}}' "${COMPOSE_PROJECT_NAME:-trialbox}_tb-secrets")}"
  printf '%s\n' "$KP_VALUE" | TB_IMAGE="$IMAGE_PY" sh deploy/hardening/seal_keys.sh --secrets "$SEC_DIR" \
    --conf "$ROOT/deploy/site/hardening.conf" --kek-passphrase-stdin \
    || die "the site keys could not be sealed (above)"
  KP_VALUE=""
fi
TZ_NEW="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tz"])' "$FR/answers.json")"
if [ -n "${TB_BOX_PY:-}" ]; then APPLY=(--firstrun "$FR" --hardware "$BOX/hardware.json" --deploy "$ROOT/deploy")
else APPLY=(--firstrun /fr --hardware /d/site/box/hardware.json --deploy /d); fi  # the image's mounts (box_py)
box_py apply "${APPLY[@]}" || die "the owner's answers could not be applied (above)"
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
if [ -z "$OWNER" ]; then
  rc=0; ANCHORS="$(python3 -m tools.trialbox finish-check --deploy "$ROOT/deploy" --print-anchors)" || rc=$?
  [ "$rc" = 0 ] || [ "$rc" = 1 ] || die "the finish check did not run (exit $rc, above): the set-up is not finished; nothing was restarted"
  [ "$rc" = 0 ] || die "the set-up is not finished (above). Mount the disk or the share at the folder the owner named; or, when a folder was typed wrongly or is mounted elsewhere, change the setting each line names in $ROOT/deploy/.env (the first-run page does not open again: the answers are applied). Then: sudo deploy/box-install.sh --firstrun"
  if [ -z "${TB_BOX_PY:-}" ] || [ -n "${TB_BOX_DOCKER:-}" ]; then  # the tests' stand-in for the image: TB_BOX_DOCKER
    while IFS= read -r anchor; do
      [ -n "$anchor" ] || continue
      # shellcheck disable=SC2086 # a command line on purpose (tests)
      ${TB_BOX_DOCKER:-docker} run --rm --network none -v "$anchor:/anchor:ro" "$IMAGE_PY" sh -c \
        'test -r /anchor && test -x /anchor && for d in heads keys; do [ ! -e "/anchor/$d" ] || { test -r "/anchor/$d" && test -x "/anchor/$d"; } || exit 1; done' </dev/null \
        || die "the console's user cannot read $anchor (or its heads/ or keys/): the audit page would find no signed head. Make the folder readable (chmod a+rx), then: sudo deploy/box-install.sh --firstrun"
    done <<< "$ANCHORS"
  fi
  python3 -m tools.trialbox finish-check --deploy "$ROOT/deploy" --mount-anchors >/dev/null \
    || die "the audit anchor folder is not mounted into the console (above); then: sudo deploy/box-install.sh --firstrun"
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
${TB_BOX_COMPOSE:-docker compose --project-directory deploy} up -d --wait || die "the stack did not restart on the new settings"
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
exit "$rc"
