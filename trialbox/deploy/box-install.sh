#!/usr/bin/env bash
# The box installer (T-729, D-466; plan v6.1 OD-11, OD-13): one installer for a GPU workstation or a DGX Spark, set up
# by its owner, with no shell knowledge and no question an IT department would be asked.
#
#   sudo deploy/box-install.sh trialbox-<version>.tar [--yes]       # hardware the site bought: install, then the wizard
#   sudo deploy/box-install.sh trialbox-<version>.tar --prepare      # Aimedics, before shipping: stop before the wizard
#   sudo deploy/box-install.sh trialbox-<version>.tar --rehearsal    # a rehearsal box: TEST, stand-ins (D-726)
#   deploy/box-install.sh --firstrun                                 # the prepared box's first boot (trialbox-firstrun.service)
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
# Knobs for the tests and the rehearsal only: TB_BOX_HARDWARE (a hardware.json instead of detecting), TB_BOX_INSTALL
# (the install command), TB_BOX_PY (a python command instead of the image), TB_BOX_COMPOSE (the compose command),
# TB_BOX_HOST_CHECK (the host check command), TB_ISSUE_DIR, TB_FIRSTRUN_HOST_DIR, TB_BOX_POLL_S, TB_BOX_NO_ROOT=1,
# TB_SYSTEMD=0 (as install.sh).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
BUNDLE=""; YES=0; PREPARE=0; FIRSTRUN=0; REHEARSAL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) YES=1 ;;
    --prepare) PREPARE=1 ;;
    --firstrun) FIRSTRUN=1 ;;
    --rehearsal) REHEARSAL=1 ;;
    -h|--help) sed -n 2,29p "$0"; exit 0 ;;
    -*) echo "box-install: unknown option $1" >&2; exit 2 ;;
    *) BUNDLE="$1" ;;
  esac
  shift
done
say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf 'box-install: %s\n' "$*" >&2; exit 1; }
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
  [ -n "$BUNDLE" ] || die "usage: deploy/box-install.sh trialbox-<version>.tar [--prepare] [--yes]"
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
  if [ "$YES" != 1 ] && [ -t 0 ]; then
    printf 'Is this the machine to install TrialBox on? [Y/n] '; read -r ans
    case "$ans" in n|N) die "stopped: nothing was changed" ;; esac
  fi
  # ---------------------------------------------------------------------------------------------- 2. plan
  say "plan from the hardware"
  rm -f "$BOX/applied"  # D-576: a new install: the answers are provisional again and the wizard is due
  ARGS_LINE="$(python3 -m tools.box plan --hardware "$BOX/hardware.json" --provisional --deploy "$ROOT/deploy" --out "$BOX/answers.json" | tail -1)"
  read -r -a INSTALL_ARGS <<< "${ARGS_LINE#install-args: }"
  [ "$REHEARSAL" = 1 ] && INSTALL_ARGS+=(--rehearsal)  # D-726: a rehearsal box, handed on to install.sh
  DEFER=0; [ "$(json_get "$BOX/hardware.json" tpm)" = True ] || DEFER=1
  echo "    install: ${INSTALL_ARGS[*]}"
  [ "$DEFER" = 0 ] || echo "    no TPM: the site keys are sealed after the wizard, under the owner's passphrase"
  # ---------------------------------------------------------------------------------------------- 3. install
  set +e
  # shellcheck disable=SC2086 # TB_BOX_INSTALL is a command line on purpose (tests)
  TB_BOX=1 TB_BOX_DEFER_SEAL="$DEFER" ${TB_BOX_INSTALL:-bash "$ROOT/deploy/install.sh"} "$BUNDLE" \
    --answers "$BOX/answers.json" "${INSTALL_ARGS[@]}" --yes 2>&1 | tee "$BOX/install.log"
  rc="${PIPESTATUS[0]}"
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
if [ -f "$BOX/applied" ]; then
  say "the owner's answers were applied on $(cat "$BOX/applied"): finishing the set-up (no new code)"
else
cp "$BOX/hardware.json" "$FR/hardware.json" && chmod 600 "$FR/hardware.json" && chown 10001:10001 "$FR/hardware.json" 2>/dev/null || true
HOST="$(json_get "$BOX/answers.json" tls_hostname)"
show_code() {
  CODE="$(python3 -m tools.box code --firstrun "$FR")"
  chown 10001:10001 "$FR/code.json" 2>/dev/null || true
  local text
  text="$(printf '\n  TrialBox set-up:  https://%s/login/first-run\n  One-time code:    %s\n' "$HOST" "$CODE")"
  if [ "$WSL2" = 0 ]; then  # the box's own screen; under WSL2 the Windows installer's window shows this output
    mkdir -p "$(dirname "$ISSUE")"
    printf '%s\n\n' "$text" > "$ISSUE"
  fi
  say "open https://$HOST/login/first-run on a computer of the team (or this box) and type the code"
  printf '%s\n\n' "$text"
}
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
  [ -n "$TB_KEK_PASSPHRASE" ] || die "no passphrase in the owner's answers: the keys stay unsealed (run the wizard again)"
  export TB_KEK_PASSPHRASE
  SEC_DIR="${TB_SECRETS_HOST_DIR:-$(docker volume inspect -f '{{.Mountpoint}}' "${COMPOSE_PROJECT_NAME:-trialbox}_tb-secrets")}"
  TB_IMAGE="$IMAGE_PY" sh deploy/hardening/seal_keys.sh --secrets "$SEC_DIR" --conf "$ROOT/deploy/site/hardening.conf" \
    || die "the site keys could not be sealed (above)"
  unset TB_KEK_PASSPHRASE
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
HOST="$(json_get "$BOX/answers.json" tls_hostname)"  # the box's name the owner chose
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
printf '\n  TrialBox is ready: https://%s  (sign in with the account you made in the set-up)\n' "$HOST"
exit "$rc"
