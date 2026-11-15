#!/bin/sh
# The site keys sealed at install (T-634, D-408, D-347; OPS-043). install.sh runs it right after the keys are made
# and before the stack starts; safe to run again.
#
#   deploy/hardening/seal_keys.sh --secrets DIR [--conf deploy/site/hardening.conf] [--dry-run]
#
# A box with a KEK already (kek.json in the secrets folder): any key still plain is wrapped (tools.keys wrap), which
# needs the KEK unsealed. A box without one: a KEK is made by KEK_BACKEND and every key is wrapped (tools.keys init):
#   tpm         a random KEK, sealed with `systemd-creds encrypt --with-key=host+tpm2` to
#               /etc/credstore.encrypted/trialbox-kek and opened at every boot by trialbox-unseal.service; the plain
#               copy only ever sits in /run (tmpfs) and is removed here;
#   shamir      shares to KEK_SHARES_OUT (removable media), then unsealed now from the first shares there;
#   passphrase  TB_KEK_PASSPHRASE (never written anywhere), unsealed now.
# TB_KEK_BACKEND in the environment chooses the back end without a hardening.conf (D-836: a file written only for the
# KEK also ran hardening/apply.sh all, the firewall and SSH); it wins over the file's KEK_BACKEND.
# tpm: the KEK is sealed before any key is wrapped under it, so a seal that fails changes nothing (D-836).
# Afterwards /run/trialbox/kek holds the KEK for the services and `tools.keys check` must pass. The keys commands run
# on the host's python3 when it has `cryptography`, else in the trialbox-py image (TB_IMAGE).
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
. "$HERE/lib.sh"
CONF="$ROOT/deploy/site/hardening.conf"; SECRETS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --secrets) SECRETS="$2"; shift ;;
    --conf) CONF="$2"; shift ;;
    --dry-run) DRY=1 ;;
    *) echo "seal_keys.sh: unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
[ -n "$SECRETS" ] && [ -d "$SECRETS" ] || hb_die "--secrets DIR: the secrets folder is not here (${SECRETS:-none})"
KEK_BACKEND=tpm; KEK_SHARES_OUT=""
[ -f "$CONF" ] && hb_load_conf "$CONF"
[ -n "${TB_KEK_BACKEND:-}" ] && KEK_BACKEND="$TB_KEK_BACKEND"
# what a host that cannot seal with its TPM does instead (a fresh box has no hardening.conf)
NO_TPM_FIX="on a host without a usable TPM 2.0 run the installer with TB_KEK_BACKEND=passphrase and TB_KEK_PASSPHRASE set (12 characters or more; no hardening.conf needed)"
RUN_DIR="$HR/run/trialbox"
KEK_FILE="${TB_KEK_FILE:-$RUN_DIR/kek}"
TB_KEK_FILE="$KEK_FILE"; export TB_KEK_FILE
CRED="$HR/etc/credstore.encrypted/trialbox-kek"

tool() {  # tool MODULE ARGS...: the host's python3 when it can, else the image's own copy of the module
  mod="$1"; shift
  if python3 -c "import cryptography" 2>/dev/null; then
    (cd "$ROOT" && PYTHONPATH="$ROOT/libs:$ROOT" python3 -m "$mod" "$@")
  else
    # the folders keep their host paths inside the container
    docker run --rm --network none --user 0:0 -e TB_KEK_PASSPHRASE -e TB_KEK_FILE -e TB_ENV -v "$SECRETS:$SECRETS" -v "$RUN_DIR:$RUN_DIR" \
      ${KEK_SHARES_OUT:+-v "$KEK_SHARES_OUT:$KEK_SHARES_OUT"} "${TB_IMAGE:-trialbox-py:1.0.0}" python -m "$mod" "$@"
  fi
}
keys() { tool tools.keys "$@"; }
# NEW-STD-2 (D-562): the audit signing key, made once beside the site keys and wrapped under the same KEK; a key that
# is there is kept. Not a stop: `trialbox doctor` (audit_heads) names a missing key
audit_key() {
  tool tools.trialbox.audit_heads --init-key --secrets "$SECRETS" \
    || hb_say "the audit signing key was not made (above): trialbox doctor names it; run this script again"
}

if [ -f "$SECRETS/kek.json" ]; then
  hb_say "the KEK exists ($SECRETS/kek.json): wrapping any key still plain"
  [ "$DRY" = 1 ] && { hb_say "would run: tools.keys wrap"; exit 0; }
  keys wrap --secrets "$SECRETS"
  audit_key
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
    [ -n "${TB_KEK_PASSPHRASE:-}" ] || hb_die "KEK_BACKEND=passphrase needs TB_KEK_PASSPHRASE in the environment"
    [ "$DRY" = 1 ] && { hb_say "would run: tools.keys init --backend passphrase; unseal"; exit 0; }
    keys init --backend passphrase --secrets "$SECRETS"
    keys unseal --secrets "$SECRETS" --out "$KEK_FILE"
    ;;
  *) hb_die "KEK_BACKEND must be tpm, shamir or passphrase, not '$KEK_BACKEND'" ;;
esac
keys check --secrets "$SECRETS"
audit_key
