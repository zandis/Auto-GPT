#!/bin/sh
# The site keys sealed at install (T-634, D-408, D-347; OPS-043). install.sh runs it right after the keys are made
# and before the stack starts; safe to run again.
#
#   deploy/hardening/seal_keys.sh --secrets DIR [--conf deploy/site/hardening.conf] [--record FILE] [--dry-run]
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
# ---- KEK-INPUT functions (H-96, F-45, H-94 (5); the integrator's ruling 7094934985). The same lines are in deploy/install.sh,
# deploy/box-install.sh and deploy/hardening/seal_keys.sh; a test holds the three together. The passphrase comes from
#   --kek-passphrase-file FILE  one line of a regular file (not a link) owned by root (the user that runs this), mode
#                               0600; removed once the keys are sealed, unless --keep-kek-passphrase-file
#   --kek-passphrase-stdin      one line on stdin; on a terminal it is asked twice, not shown
# and never from the environment: TB_KEK_PASSPHRASE or TB_KEK_NEW_PASSPHRASE there is refused, with or without sudo
# (sudo writes a variable it keeps, with its value, to the system journal). The value lives in KP_VALUE, never
# exported, and goes on by a pipe: never an argument, never a sudo environment, never a file. Nothing prints it.
set +a  # H-09 (seventh review): bash -a (allexport) would export every assignment below
unset KP_VALUE KP_FILE kp_again  # H-09: a caller's export of these is dropped here (an assignment keeps an export)
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
    # H-110 (i): a hang-up, ^C or kill during the prompt gives the terminal its echo back (each caller asks before it
    # sets a trap of its own, so the traps are reset to the default after)
    # the echo back, then the signal again with its own default: the same end as before
    trap 'stty echo 2>/dev/null; trap - HUP; kill -s HUP $$' HUP
    trap 'stty echo 2>/dev/null; trap - INT; kill -s INT $$' INT
    trap 'stty echo 2>/dev/null; trap - TERM; kill -s TERM $$' TERM
    stty -echo 2>/dev/null; printf 'KEK passphrase (12 characters or more, not shown): ' >&2; IFS= read -r KP_VALUE || :
    printf '\nthe same again: ' >&2; kp_again=""; IFS= read -r kp_again || :; stty echo 2>/dev/null; printf '\n' >&2
    trap - HUP INT TERM
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
kp_refuse_env  # H-96: before anything is read or made
CONF="$ROOT/deploy/site/hardening.conf"; SECRETS=""; PP_FILE=""; PP_STDIN=0; PP_KEEP=0; REC=""
while [ $# -gt 0 ]; do
  case "$1" in
    --secrets) SECRETS="$2"; shift ;;
    --conf) CONF="$2"; shift ;;
    --record) REC="$2"; shift ;;
    --dry-run) DRY=1 ;;
    --kek-passphrase-file) [ -n "${2:-}" ] || hb_die "--kek-passphrase-file needs a file"; PP_FILE="$2"; shift ;;  # H-94 (5)
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
[ -z "$PP_FILE" ] || [ "$PP_STDIN" = 0 ] || hb_die "--kek-passphrase-file and --kek-passphrase-stdin: give one"  # H-94 (5)
[ "$PP_KEEP" = 0 ] || [ -n "$PP_FILE" ] || hb_die "--keep-kek-passphrase-file goes with --kek-passphrase-file"  # H-94 (5)
if [ -n "$PP_FILE" ]; then kp_read_file "$PP_FILE"; elif [ "$PP_STDIN" = 1 ]; then kp_read_stdin; fi
# what a host that cannot seal with its TPM does instead (a fresh box has no hardening.conf)
NO_TPM_FIX="on a host without a usable TPM 2.0 run the installer with TB_KEK_BACKEND=passphrase and --kek-passphrase-file FILE (one line of 12 characters or more, a file only root can read; no hardening.conf needed)"
RUN_DIR="$HR/run/trialbox"
# H-118 (the integrator's ruling 7125021924): the unsealed KEK goes to the box's own place, the one the boot unseal
# unit writes and the services read (/run/trialbox/kek, a tmpfs); a caller's TB_KEK_FILE never moves it
[ -z "${TB_KEK_FILE:-}" ] || [ "$TB_KEK_FILE" = "$RUN_DIR/kek" ] \
  || hb_say "TB_KEK_FILE in the environment ($TB_KEK_FILE) is not used: the unsealed KEK goes to $RUN_DIR/kek"
KEK_FILE="$RUN_DIR/kek"
TB_KEK_FILE="$KEK_FILE"; export TB_KEK_FILE
CRED="$HR/etc/credstore.encrypted/trialbox-kek"

tool() {  # tool MODULE ARGS...: the host's python3 when it can, else the image's own copy of the module; stdin goes on
  mod="$1"; shift
  # review of #1482 (1482-1): the image is given the plain KEK's own folder too, once arm made it (never made by the
  # engine: a missing folder given to -v is made root's 0755, which the next arm refuses)
  seal_v=""; [ ! -d "$SEAL_DIR" ] || seal_v="$SEAL_DIR:$SEAL_DIR"
  if python3 -c "import cryptography" 2>/dev/null; then
    (cd "$ROOT" && PYTHONPATH="$ROOT/libs:$ROOT" python3 -m "$mod" "$@")
  else
    # the folders keep their host paths inside the container. The passphrase goes through the container's stdin (a
    # pipe), never -e: Docker keeps a container's environment in its config on disk
    docker run --rm -i --network none --user 0:0 -e TB_KEK_FILE -e TB_ENV \
      -v "$SECRETS:$SECRETS" -v "$RUN_DIR:$RUN_DIR" ${seal_v:+-v "$seal_v"} \
      ${KEK_SHARES_OUT:+-v "$KEK_SHARES_OUT:$KEK_SHARES_OUT"} \
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
  [ -n "$KP_FILE" ] || return 0  # the real path the file was read from; rm, never written through the name
  if [ "$PP_KEEP" = 1 ]; then hb_say "the passphrase file $KP_FILE is kept (--keep-kek-passphrase-file): remove it yourself"
  else kp_remove_file "$KP_FILE"; hb_say "the passphrase file $KP_FILE is removed"; fi
}
# NEW-STD-2 (D-562): the audit signing key, made once beside the site keys and wrapped under the same KEK; a key that
# is there is kept. Not a stop: `trialbox doctor` (audit_heads) names a missing key
audit_key() {
  tool tools.trialbox.audit_heads --init-key --secrets "$SECRETS" </dev/null \
    || hb_say "the audit signing key was not made (above): trialbox doctor names it; run this script again"
}

# tpm (H-111): at every instant either the plain keys are there or the KEK that opens the wrapped keys is sealed in
# $CRED, its final place: the credential is sealed and placed before any key is wrapped, and nothing here removes it.
# Only the plain copy in /run ($NEW) and an unplaced $CRED.new are removed, at any exit; a signal exits.
# H-118 (#1457's review, 1457-9): $NEW lives in a folder of its own, root's (0700) and never handed over: $RUN_DIR is
# handed to the services' user (D-887), and a name there could be swapped for a link
SEAL_DIR="$HR/run/trialbox-seal"
NEW="$SEAL_DIR/kek.new"
# review of #1457 (1457-5): once the clean-up starts a further signal neither cuts it short nor kills its shred
# review of #1457 (1457-9): /run/trialbox is handed to the services' user, so a name there is never followed: a link is
# removed, not shredded through
new_gone() {
  trap '' HUP INT TERM
  if [ -L "$NEW" ]; then rm -f "$NEW"; else shred -u "$NEW" 2>/dev/null || rm -f "$NEW"; fi
  rm -f "$CRED.new"
}
arm() {
  ( umask 077; mkdir -p "$RUN_DIR" "$(dirname "$CRED")" )
  # review of #1457 (1457-1, the rest): kek.new and the credential are the host's, not one secrets folder's: one TPM
  # seal at a time on this host, whichever folder it is for. The credential's folder is root's (0700); the lock is
  # taken before the trap is set, so a refused run removes nothing of the other run's
  exec 5<"$(dirname "$CRED")"
  flock -n 5 || hb_die "another run of seal_keys.sh on this host holds $(dirname "$CRED"): let it finish, then run this script again; nothing was changed"
  # H-118: the plain KEK's folder, made by this run under the host lock: a real folder, this user's, mode 0700, or
  # nothing is done
  ( umask 077; mkdir -p "$SEAL_DIR" )
  # (the owner compared with this shell's own, /proc/$$: never `id`, which a test may stand in for)
  if [ -L "$SEAL_DIR" ] || [ ! -d "$SEAL_DIR" ] \
    || [ "$(stat -c %u:%a "$SEAL_DIR")" != "$(stat -c %u /proc/$$):700" ]; then
    hb_die "$SEAL_DIR is not a folder only this user can open (a link, another owner, or not mode 0700): remove it, then run this script again; nothing was changed"
  fi
  # review of #1457 (1457-9): with the host lock held no other seal runs, so a name at kek.new is a stopped run's (its KEK
  # is in the placed credential, or no key was wrapped under it) or a link: removed before the new KEK is written
  rm -f -- "$NEW"
  trap new_gone EXIT; trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM
}
# the KEK of the sealed credential, to $NEW (a run that stopped after the credential was placed)
cred_open() {
  arm
  # review of #1457 (1457-4): owner only, as the new KEK is made, and never written through a name already there
  ( umask 077; rm -f -- "$NEW" && systemd-creds decrypt --name=trialbox-kek "$CRED" "$NEW" ) \
    || hb_die "the TPM could not open $CRED (above): nothing was changed; run this script again on the host that sealed it"
}
# the boot unit: the same unseal from the sealed credential
boot_unit() {
  [ "${TB_SYSTEMD:-1}" != 0 ] || return 0
  sed -e "s#@TB_ROOT@#$ROOT#g" -e "s#@TB_SECRETS@#$SECRETS#g" "$HERE/trialbox-unseal.service" \
    | hb_write "${TB_SYSTEMD_DIR:-$HR/etc/systemd/system}/trialbox-unseal.service" 644
  if command -v systemctl >/dev/null 2>&1 && [ -d "$HR/run/systemd/system" ]; then
    systemctl daemon-reload && systemctl enable trialbox-unseal.service >/dev/null
  fi
}
any_wrapped() { for w in "$SECRETS"/*.wrapped; do [ -e "$w" ] && return 0; done; return 1; }
# D-887 (found by the box rehearsal): the keys commands run as root and leave kek.json, the wrapped keys and the
# runtime KEK root's; the services (the secrets folder's owner, uid 10001) must open them. Owner only: modes stay 0600.
# Review of #1457 (1457-2): on each way out that says done, a re-run's (the kek.json branch) too
hand_over() {
  OWNER="$(stat -c %u:%g "$SECRETS")"
  if [ "${OWNER%%:*}" != 0 ] && [ "$(id -u)" = 0 ]; then
    # review of #1457 (1457-7): -h, never through a link: the secrets folder is the services' user's, and a name there
    # can be swapped for a link between the sweep and the chown
    find "$SECRETS" -maxdepth 1 -type f -user 0 -exec chown -h "$OWNER" {} +
    if [ -f "$KEK_FILE" ]; then chown -h "$OWNER" "$KEK_FILE" "$(dirname "$KEK_FILE")"; fi
  fi
}

# review of #1457 (1457-1): one run at a time on this secrets folder. Two runs at once shared kek.new: one wrapped the
# keys under the other's KEK and placed its own credential. An exclusive lock on the folder itself (no file is added,
# the lock tools.keys rotate-kek takes), held until this run and its children end
if [ "$DRY" != 1 ]; then
  command -v flock >/dev/null 2>&1 \
    || hb_die "flock (util-linux) is missing, so a second run could not be kept out: install util-linux, then run this script again; nothing was changed"
  exec 6<"$SECRETS"
  flock -n 6 || hb_die "another run of seal_keys.sh or a key command holds $SECRETS: let it finish, then run this script again; nothing was changed"
fi

# H-77 (F-22): record WORD: --record FILE gets the back end the seal in place uses, the name only and owner only, whole
# (a temp file, then renamed). install.sh copies it to deploy/.env (TB_KEK_BACKEND), where the host check reads it
record() {
  [ -n "$REC" ] || return 0
  mkdir -p "$(dirname "$REC")"
  ( umask 077; printf '%s\n' "$1" > "$REC.tmp" )
  mv -f "$REC.tmp" "$REC"
  hb_say "the KEK back end is recorded: $1 ($REC)"
}

if [ -f "$SECRETS/kek.json" ]; then
  hb_say "the KEK exists ($SECRETS/kek.json): wrapping any key still plain"
  [ "$DRY" = 1 ] && { hb_say "would run: tools.keys wrap"; exit 0; }
  # H-96: a passphrase box whose KEK is not unsealed here (a restart since): opened from the passphrase given
  if [ -n "$KP_VALUE" ] && [ ! -f "$KEK_FILE" ] && grep -q '"backend": *"passphrase"' "$SECRETS/kek.json"; then
    keys_pp unseal --secrets "$SECRETS" --out "$KEK_FILE"
  fi
  TPM_BOX=0
  if [ -f "$CRED" ] && grep -q '"backend": *"file"' "$SECRETS/kek.json"; then TPM_BOX=1; fi
  # H-111: a TPM box stopped after kek.json was written and before its KEK was unsealed here: from the credential
  if [ "$TPM_BOX" = 1 ] && [ ! -f "$KEK_FILE" ]; then
    cred_open
    keys unseal --secrets "$SECRETS" --from "$NEW" --out "$KEK_FILE"
  fi
  keys wrap --secrets "$SECRETS"
  [ "$TPM_BOX" = 0 ] || boot_unit
  audit_key
  pp_done
  hand_over
  # H-77: the record follows the seal in place as kek.json names it (after a rotate-kek, or a seal whose closing check
  # failed once); kek.json's file back end is tpm's KEK (tools.keys init --backend file --kek-in, above)
  WAS="$(sed -n 's/^ "backend": "\([a-z]*\)",\{0,1\}$/\1/p' "$SECRETS/kek.json")"
  [ "$WAS" = file ] && WAS=tpm
  case "$WAS" in
    ""|*[!a-z]*) hb_say "kek.json names no back end: nothing recorded" ;;
    *) record "$WAS" ;;
  esac
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
    # H-111: a credential with no kek.json and no wrapped key is a run's that stopped before any key was wrapped
    if [ -f "$CRED" ] && any_wrapped; then
      hb_die "$CRED exists but $SECRETS has no kek.json: put kek.json back from the backup, or remove the credential"
    fi
    if [ "$DRY" = 1 ]; then
      hb_say "would make a KEK in $SEAL_DIR/kek.new"
      hb_say "would run: systemd-creds encrypt --with-key=host+tpm2 --name=trialbox-kek $SEAL_DIR/kek.new $CRED.new; mv $CRED.new $CRED"
      hb_say "would run: tools.keys init --backend file --kek-in $SEAL_DIR/kek.new"
      hb_say "would run: tools.keys unseal --from $SEAL_DIR/kek.new --out $KEK_FILE; shred $SEAL_DIR/kek.new"
      exit 0
    fi
    if [ -f "$CRED" ]; then
      hb_say "$CRED is from a run that stopped before any key was wrapped: its KEK is used"
      cred_open
    else
      arm
      # review of #1457 (1457-11): the credential was looked for before the host lock was held; a run that finished in
      # between placed its own, and a second seal would move a new one over it (the other folder's keys then open
      # under no credential). Looked for again under the lock
      [ ! -e "$CRED" ] || hb_die "$CRED was placed by another run while this one started: run this script again; nothing was changed"
      # D-836: make the KEK, seal it, and only then wrap the keys under it: a failed seal leaves every key as it was
      ( umask 077; head -c 32 /dev/urandom > "$NEW" )
      systemd-creds encrypt --with-key=host+tpm2 --name=trialbox-kek "$NEW" "$CRED.new" \
        || hb_die "the TPM could not seal the KEK (above): nothing was changed; $NO_TPM_FIX"
      # H-111: placed, and on disk, before any key is wrapped under it
      chmod 600 "$CRED.new"
      mv -f "$CRED.new" "$CRED"
      sync -- "$CRED" "$(dirname "$CRED")" 2>/dev/null || sync
    fi
    keys init --backend file --secrets "$SECRETS" --kek-in "$NEW" \
      || hb_die "the site keys could not be wrapped (above): the KEK is sealed in $CRED; run this script again"
    keys unseal --secrets "$SECRETS" --from "$NEW" --out "$KEK_FILE"
    boot_unit
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
hand_over
# H-77 (F-22): the back end this run sealed with, recorded only now that every step above passed (a dry run and a failed
# seal never get here: an earlier record stays as it was)
record "$KEK_BACKEND"
