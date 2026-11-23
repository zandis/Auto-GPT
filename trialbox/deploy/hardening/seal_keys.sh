#!/bin/sh
# The site keys sealed at install (T-634, D-408, D-347; OPS-043). install.sh runs it right after the keys are made
# and before the stack starts; safe to run again.
#
#   deploy/hardening/seal_keys.sh --secrets DIR [--conf deploy/site/hardening.conf] [--dry-run]
#       [--kek-passphrase-file FILE [--keep-kek-passphrase-file] | --kek-passphrase-stdin]
#
# A box with a KEK already (kek.json in the secrets folder): any key still plain is wrapped (tools.keys wrap), which
# needs the KEK unsealed. A box without one: a KEK is made by KEK_BACKEND and every key is wrapped (tools.keys init):
#   tpm         a random KEK, sealed with `systemd-creds encrypt --with-key=host+tpm2` to
#               /etc/credstore.encrypted/trialbox-kek and opened at every boot by trialbox-unseal.service; the plain
#               copy only ever sits in /run (tmpfs) and is removed here;
#   shamir      shares to KEK_SHARES_OUT (removable media), then unsealed now from the first shares there;
#   passphrase  from --kek-passphrase-file FILE (one line; a regular file owned by root, mode 0600; removed once the
#               keys are sealed unless --keep-kek-passphrase-file) or --kek-passphrase-stdin (one line), unsealed now.
#               A passphrase in the environment (TB_KEK_PASSPHRASE) is refused (H-96, the KEK-INPUT block below).
# TB_KEK_BACKEND in the environment chooses the back end without a hardening.conf (D-836: a file written only for the
# KEK also ran hardening/apply.sh all, the firewall and SSH); it wins over the file's KEK_BACKEND.
# tpm: the KEK is sealed before any key is wrapped under it, so a seal that fails changes nothing (D-836).
# Afterwards /run/trialbox/kek holds the KEK for the services and `tools.keys check` must pass. The keys commands run
# on the host's python3 when it has `cryptography`, else in the trialbox-py image (TB_IMAGE).
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
. "$HERE/lib.sh"
KP_WHO="seal_keys.sh"
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
kp_refuse_env  # H-96: before anything is read or made
CONF="$ROOT/deploy/site/hardening.conf"; SECRETS=""; PP_FILE=""; PP_STDIN=0; PP_KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --secrets) SECRETS="$2"; shift ;;
    --conf) CONF="$2"; shift ;;
    --dry-run) DRY=1 ;;
    --kek-passphrase-file) [ -n "${2:-}" ] || hb_die "--kek-passphrase-file needs a file"; PP_FILE="$2"; shift ;;
    --keep-kek-passphrase-file) PP_KEEP=1 ;;
    --kek-passphrase-stdin) PP_STDIN=1 ;;
    *) echo "seal_keys.sh: unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
[ -n "$SECRETS" ] && [ -d "$SECRETS" ] || hb_die "--secrets DIR: the secrets folder is not here (${SECRETS:-none})"
KEK_BACKEND=tpm; KEK_SHARES_OUT=""
[ -f "$CONF" ] && hb_load_conf "$CONF"
[ -n "${TB_KEK_BACKEND:-}" ] && KEK_BACKEND="$TB_KEK_BACKEND"
# H-96: the passphrase from the operator's root-only file or from stdin, never from the environment. Read before
# anything is made or sealed; a line break or another control character is refused (review 2 of #1305, L-2: the image
# and the host must seal under the same value). The value is never printed
[ -z "$PP_FILE" ] || [ "$PP_STDIN" = 0 ] || hb_die "--kek-passphrase-file and --kek-passphrase-stdin: give one"
[ "$PP_KEEP" = 0 ] || [ -n "$PP_FILE" ] || hb_die "--keep-kek-passphrase-file goes with --kek-passphrase-file"
if [ -n "$PP_FILE" ]; then kp_read_file "$PP_FILE"; elif [ "$PP_STDIN" = 1 ]; then kp_read_stdin; fi
# what a host that cannot seal with its TPM does instead (a fresh box has no hardening.conf)
NO_TPM_FIX="on a host without a usable TPM 2.0 run the installer with TB_KEK_BACKEND=passphrase and --kek-passphrase-file FILE (one line of 12 characters or more, a file only root can read; no hardening.conf needed)"
RUN_DIR="$HR/run/trialbox"
KEK_FILE="${TB_KEK_FILE:-$RUN_DIR/kek}"
TB_KEK_FILE="$KEK_FILE"; export TB_KEK_FILE
CRED="$HR/etc/credstore.encrypted/trialbox-kek"

tool() {  # tool MODULE ARGS...: the host's python3 when it can, else the image's own copy of the module; stdin goes on
  mod="$1"; shift
  if python3 -c "import cryptography" 2>/dev/null; then
    (cd "$ROOT" && PYTHONPATH="$ROOT/libs:$ROOT" python3 -m "$mod" "$@")
  else
    # the folders keep their host paths inside the container. The passphrase goes through the container's stdin (a
    # pipe), never -e: Docker keeps a container's environment in its config on disk
    docker run --rm -i --network none --user 0:0 -e TB_KEK_FILE -e TB_ENV \
      -v "$SECRETS:$SECRETS" -v "$RUN_DIR:$RUN_DIR" ${KEK_SHARES_OUT:+-v "$KEK_SHARES_OUT:$KEK_SHARES_OUT"} \
      "${TB_IMAGE:-trialbox-py:1.0.0}" python -m "$mod" "$@"
  fi
}
keys() { tool tools.keys "$@" </dev/null; }
# H-96: the passphrase by a pipe (printf is the shell's builtin: no process of its own, no argument) to the keys
# command's stdin, as one line, on the host and in the image alike; never in an environment
keys_pp() { printf '%s\n' "$KP_VALUE" | tool tools.keys "$@" --passphrase-stdin; }
# the operator's file, once the keys are sealed (kept with --keep-kek-passphrase-file)
pp_done() {
  KP_VALUE=""
  [ -n "$PP_FILE" ] || return 0
  if [ "$PP_KEEP" = 1 ]; then hb_say "the passphrase file $PP_FILE is kept (--keep-kek-passphrase-file): remove it yourself"
  else kp_remove_file "$PP_FILE"; hb_say "the passphrase file $PP_FILE is removed"; fi
}
# NEW-STD-2 (D-562): the audit signing key, made once beside the site keys and wrapped under the same KEK; a key that
# is there is kept. Not a stop: `trialbox doctor` (audit_heads) names a missing key
audit_key() {
  tool tools.trialbox.audit_heads --init-key --secrets "$SECRETS" </dev/null \
    || hb_say "the audit signing key was not made (above): trialbox doctor names it; run this script again"
}

if [ -f "$SECRETS/kek.json" ]; then
  hb_say "the KEK exists ($SECRETS/kek.json): wrapping any key still plain"
  [ "$DRY" = 1 ] && { hb_say "would run: tools.keys wrap"; exit 0; }
  # H-96: a passphrase box whose KEK is not unsealed here (a restart since): opened from the passphrase given
  if [ -n "$KP_VALUE" ] && [ ! -f "$KEK_FILE" ] && grep -q '"backend": *"passphrase"' "$SECRETS/kek.json"; then
    keys_pp unseal --secrets "$SECRETS" --out "$KEK_FILE"
  fi
  keys wrap --secrets "$SECRETS"
  audit_key
  pp_done
  exit 0
fi

hb_say "sealing the site keys under a new KEK (back end $KEK_BACKEND)"
case "$KEK_BACKEND" in
  tpm)
    command -v systemd-creds >/dev/null 2>&1 || hb_die "KEK_BACKEND=tpm needs systemd-creds (systemd 250 or later); $NO_TPM_FIX"
    [ -e "$HR/dev/tpmrm0" ] || [ -e "$HR/dev/tpm0" ] || hb_die "KEK_BACKEND=tpm but this host has no TPM 2.0 device; $NO_TPM_FIX"
    # a device node is not enough: systemd-creds needs the TPM and its TSS2 libraries
    TPM2="$(systemd-creds has-tpm2 2>&1)" \
      || hb_die "KEK_BACKEND=tpm but the TPM 2.0 is not usable (systemd-creds has-tpm2: $(echo "$TPM2" | tr '\n' ' ')); $NO_TPM_FIX"
    [ -f "$CRED" ] && hb_die "$CRED exists but $SECRETS has no kek.json: put kek.json back from the backup, or remove the credential"
    if [ "$DRY" = 1 ]; then
      hb_say "would make a KEK in $RUN_DIR/kek.new"
      hb_say "would run: systemd-creds encrypt --with-key=host+tpm2 --name=trialbox-kek $RUN_DIR/kek.new $CRED.new"
      hb_say "would run: tools.keys init --backend file --kek-in $RUN_DIR/kek.new; mv $CRED.new $CRED"
      hb_say "would run: tools.keys unseal --from $RUN_DIR/kek.new --out $KEK_FILE; shred $RUN_DIR/kek.new"
      exit 0
    fi
    ( umask 077; mkdir -p "$RUN_DIR" "$(dirname "$CRED")" )
    NEW="$RUN_DIR/kek.new"
    trap 'shred -u "$NEW" 2>/dev/null || rm -f "$NEW"; rm -f "$CRED.new"' EXIT INT TERM HUP
    # D-836: make the KEK, seal it, and only then wrap the keys under it: a failed seal leaves every key as it was
    ( umask 077; head -c 32 /dev/urandom > "$NEW" )
    systemd-creds encrypt --with-key=host+tpm2 --name=trialbox-kek "$NEW" "$CRED.new" \
      || hb_die "the TPM could not seal the KEK (above): nothing was changed; $NO_TPM_FIX"
    keys init --backend file --secrets "$SECRETS" --kek-in "$NEW" \
      || hb_die "the site keys could not be wrapped (above): nothing was sealed; run this script again"
    mv -f "$CRED.new" "$CRED"
    chmod 600 "$CRED"
    keys unseal --secrets "$SECRETS" --from "$NEW" --out "$KEK_FILE"
    # the boot unit: the same unseal from the sealed credential
    if [ "${TB_SYSTEMD:-1}" != 0 ]; then
      sed -e "s#@TB_ROOT@#$ROOT#g" -e "s#@TB_SECRETS@#$SECRETS#g" "$HERE/trialbox-unseal.service" \
        | hb_write "${TB_SYSTEMD_DIR:-$HR/etc/systemd/system}/trialbox-unseal.service" 644
      if command -v systemctl >/dev/null 2>&1 && [ -d "$HR/run/systemd/system" ]; then
        systemctl daemon-reload && systemctl enable trialbox-unseal.service >/dev/null
      fi
    fi
    ;;
  shamir)
    [ -n "$KEK_SHARES_OUT" ] || hb_die "KEK_BACKEND=shamir needs KEK_SHARES_OUT (removable media)"
    [ "$DRY" = 1 ] && { hb_say "would run: tools.keys init --backend shamir --shares-out $KEK_SHARES_OUT; unseal"; exit 0; }
    keys init --backend shamir --secrets "$SECRETS" --shares-out "$KEK_SHARES_OUT"
    set --
    for f in "$KEK_SHARES_OUT"/share-*.txt; do [ -f "$f" ] && set -- "$@" --share "$f"; done
    keys unseal --secrets "$SECRETS" "$@" --out "$KEK_FILE"
    hb_say "give one share file to each steward now and remove them from $KEK_SHARES_OUT"
    ;;
  passphrase)
    [ -n "$KP_VALUE" ] || hb_die "KEK_BACKEND=passphrase needs the passphrase: --kek-passphrase-file FILE (a file only root can read) or --kek-passphrase-stdin; nothing was sealed"
    [ "$DRY" = 1 ] && { hb_say "would run: tools.keys init --backend passphrase; unseal"; exit 0; }
    keys_pp init --backend passphrase --secrets "$SECRETS"
    keys_pp unseal --secrets "$SECRETS" --out "$KEK_FILE"
    ;;
  *) hb_die "KEK_BACKEND must be tpm, shamir or passphrase, not '$KEK_BACKEND'" ;;
esac
keys check --secrets "$SECRETS"
audit_key
pp_done
# D-887 (found by the box rehearsal): the keys commands run as root and leave kek.json, the wrapped keys and the
# runtime KEK root's; the services (the secrets folder's owner, uid 10001) must open them. Owner only: modes stay 0600
OWNER="$(stat -c %u:%g "$SECRETS")"
if [ "${OWNER%%:*}" != 0 ] && [ "$(id -u)" = 0 ]; then
  find "$SECRETS" -maxdepth 1 -type f -user 0 -exec chown "$OWNER" {} +
  [ -f "$KEK_FILE" ] && chown "$OWNER" "$KEK_FILE" "$(dirname "$KEK_FILE")"
fi
