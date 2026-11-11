#!/bin/sh
# Disk unlock that fails outside the hospital (T-634, D-408; OPS-043). Run as root by hospital IT, once, after the OS
# is installed on LUKS2 and before the box holds data. It needs the LUKS passphrase (clevis asks for it).
#
#   deploy/hardening/disk-unlock.sh bind  --device /dev/<luks-partition> [--conf deploy/site/hardening.conf] [--dry-run]
#   deploy/hardening/disk-unlock.sh check --device /dev/<luks-partition>
#
# bind: one clevis binding sss t=2 of {tang (TANG_URLS, any one of them), tpm2 (PCR 7, Secure Boot state)}: the
#   volume opens at boot only on this board AND with a hospital Tang server answering. Then every TPM-only way in is
#   removed (systemd-cryptenroll --wipe-slot=tpm2), the initramfs gets the network and clevis, and `check` runs.
#   A moved disk, or the box off the hospital network, stops at the passphrase prompt; the passphrase stays in the
#   hospital's sealed envelope. clevis, clevis-luks, clevis-tpm2 and clevis-initramfs come from the offline media.
# check: deploy/hardening/luks_policy.py on the device (deploy/check_host.sh runs it for every volume under Docker's
#   data root): FAIL on any way in that needs neither the network nor a person.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
. "$HERE/lib.sh"
CONF="$ROOT/deploy/site/hardening.conf"; DEV=""; CMD="${1:-}"
[ $# -gt 0 ] && shift
while [ $# -gt 0 ]; do
  case "$1" in
    --device) DEV="$2"; shift ;;
    --conf) CONF="$2"; shift ;;
    --dry-run) DRY=1 ;;
    *) echo "disk-unlock.sh: unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
[ -n "$DEV" ] || { sed -n 5,6p "$0" >&2; exit 2; }
case "$CMD" in
  check) exec python3 "$HERE/luks_policy.py" "$DEV" ;;
  bind) ;;
  *) sed -n 5,6p "$0" >&2; exit 2 ;;
esac
TANG_URLS=""
hb_load_conf "$CONF"
[ -n "$TANG_URLS" ] || hb_die "TANG_URLS is empty in $CONF: without a Tang server the disk would open anywhere"
# the clevis policy: any one Tang server (t=1 among them) and the TPM, both required (t=2)
TANG_JSON=""
for u in $TANG_URLS; do
  case "$u" in http://*|https://*) ;; *) hb_die "TANG_URLS: '$u' is not an http(s) URL" ;; esac
  TANG_JSON="$TANG_JSON${TANG_JSON:+,}{\"url\":\"$u\"}"
done
POLICY="{\"t\":2,\"pins\":{\"sss\":{\"t\":1,\"pins\":{\"tang\":[$TANG_JSON]}},\"tpm2\":{\"pcr_bank\":\"sha256\",\"pcr_ids\":\"7\"}}}"
hb_say "binding $DEV: sss t=2 of (one of: $TANG_URLS) and the TPM (PCR 7)"
hb_run clevis luks bind -d "$DEV" sss "$POLICY"
hb_say "removing every TPM-only way in (systemd-cryptenroll tokens)"
hb_run systemd-cryptenroll --wipe-slot=tpm2 "$DEV"
# /etc/crypttab: no tpm2-device= option left (clevis-initramfs opens the volume); the network in the initramfs
if [ -f "$HR/etc/crypttab" ] && grep -q 'tpm2-device=' "$HR/etc/crypttab"; then
  if [ "$DRY" = 1 ]; then
    hb_say "would remove tpm2-device= from $HR/etc/crypttab"
  else
    sed -i 's/,\{0,1\}tpm2-device=[^, ]*//; s/\(\s\)none,/\1none /' "$HR/etc/crypttab"
  fi
fi
hb_run update-initramfs -u -k all
[ "$DRY" = 1 ] || python3 "$HERE/luks_policy.py" "$DEV"
hb_say "test it in the hospital: reboot with the network cable out; the box must stop at the passphrase prompt"
