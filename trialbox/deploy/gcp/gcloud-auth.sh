# shellcheck shell=bash
# Fresh auth for every gcloud call of the complete run (D-141, G1 bug A2). Source it; then call `gc <gcloud args>`
# instead of `gcloud <gcloud args>`.
#
#   export CLOUDSDK_CONFIG=<a private folder>          # never the default ~/.config/gcloud
#   export TB_SA_KEY_FILE=<the service account key file, in place>   # its PATH goes to gcloud; nothing here reads it
#   . deploy/gcp/gcloud-auth.sh
#   gc_start                                            # at the start of every command: activate, then probe
#   gc compute instances describe tb-gpu-sim --zone asia-east1-a --format='value(status)'
#
# gc_start activates the service account from TB_SA_KEY_FILE and probes the token, so a command never starts on a
# token that lapsed since the last one (G1: an activation stored in the private config lapsed during the run; the next
# launch failed and a collect hung for 10 minutes). Every call has a timeout, so a call without a working token fails
# instead of waiting: GC_TIMEOUT_S for a read or an auth call, GC_OP_TIMEOUT_S for a call that waits on a Compute
# Engine operation or copies results, GC_IMAGE_TIMEOUT_S for a machine image. A call that fails with an
# authentication error or times out re-activates the account and is retried once; if it fails again and the token
# probe fails too, it says "credentials expired: re-activate" with the command to run. Any other error is returned as
# it is. The key file's path is printed at most; its content never is (gcloud reads it itself, and stderr of the
# activation is dropped). GC_DRY=1 prints the commands instead of running them.
#
# The timeouts (OD-10: settings with a reason, not measured limits). They bound how long the driver waits on gcloud,
# never the run itself; each can be overridden in the environment:
#   GC_TIMEOUT_S 30         a read, a metadata or secret call or a token answers in seconds (gcloud's start-up and
#                           one API round trip); 30 s is about ten times that, and a token that does not come in 30 s
#                           is not coming
#   GC_OP_TIMEOUT_S 900     start, stop, create, delete, set-scheduling or a storage copy waits on the operation
#                           itself; a GPU VM's stop or start takes minutes, a 15-minute wait means the call is stuck
#   GC_IMAGE_TIMEOUT_S 3600 a machine image copies the whole disk (--provision, once)
GC_TIMEOUT_S="${GC_TIMEOUT_S:-30}"
GC_OP_TIMEOUT_S="${GC_OP_TIMEOUT_S:-900}"
GC_IMAGE_TIMEOUT_S="${GC_IMAGE_TIMEOUT_S:-3600}"

gc_auth_error() {  # $1: a file with the failed call's stderr
  grep -qiE 'reauthentication|invalid authentication credentials|UNAUTHENTICATED|invalid_grant|401|'\
'Request had invalid authentication|There was a problem refreshing your current auth tokens|'\
'You do not currently have an active account' "$1"
}

gc_timeout() {  # the timeout of one call, from its gcloud arguments
  case "$1 $2 ${3:-}" in
    "compute machine-images "*) echo "$GC_IMAGE_TIMEOUT_S" ;;
    "compute instances describe"|"compute instances list") echo "$GC_TIMEOUT_S" ;;
    "compute instances "*|"storage "*) echo "$GC_OP_TIMEOUT_S" ;;
    *) echo "$GC_TIMEOUT_S" ;;
  esac
}

gc_expired() {  # $1: what failed
  echo "gc: credentials expired: re-activate: gcloud auth activate-service-account --key-file \"\$TB_SA_KEY_FILE\"" \
       "(CLOUDSDK_CONFIG=${CLOUDSDK_CONFIG:-the default config}); $1" >&2
}

gc_activate() {
  [ -n "${TB_SA_KEY_FILE:-}" ] && [ -r "$TB_SA_KEY_FILE" ] || { echo "gc: no readable TB_SA_KEY_FILE to activate" >&2; return 1; }
  timeout -k 5 "$GC_TIMEOUT_S" gcloud auth activate-service-account --key-file "$TB_SA_KEY_FILE" --quiet >/dev/null 2>&1
}

gc_token_ok() { timeout -k 5 "$GC_TIMEOUT_S" gcloud auth print-access-token >/dev/null 2>&1; }

gc_stuck() { [ "$1" = 124 ] || [ "$1" = 137 ]; }  # timeout's exit codes (TERM, then KILL)

gc() {
  if [ "${GC_DRY:-0}" = 1 ]; then echo "+ gcloud $*"; return 0; fi
  local err rc t
  err="$(mktemp)"
  t="$(gc_timeout "$@")"
  timeout -k 5 "$t" gcloud "$@" 2>"$err"
  rc=$?
  if [ "$rc" != 0 ] && { gc_stuck "$rc" || gc_auth_error "$err"; }; then
    echo "gc: gcloud $1 $2 ${3:-} failed (rc $rc); re-activating the service account and trying once more" >&2
    if gc_activate; then
      timeout -k 5 "$t" gcloud "$@" 2>"$err"
      rc=$?
    fi
    if [ "$rc" != 0 ] && { gc_stuck "$rc" || gc_auth_error "$err"; } && ! gc_token_ok; then
      gc_expired "gcloud $1 $2 ${3:-} failed"
    elif gc_stuck "$rc"; then
      echo "gc: gcloud $1 $2 ${3:-} timed out after $t s (twice; the token works)" >&2
    fi
  fi
  [ "$rc" = 0 ] || sed 's/^/gcloud: /' "$err" >&2
  rm -f "$err"
  return "$rc"
}

gc_probe() {  # a dead or skewed credential fails here, before anything starts
  [ "${GC_DRY:-0}" = 1 ] && { echo "+ gcloud auth print-access-token (probe)"; return 0; }
  gc_token_ok || { gc_expired "no access token in $GC_TIMEOUT_S s"; return 5; }
}

gc_start() {  # the start of every driver command (launch, collect, stop, shard): activate from the key file, probe
  [ "${GC_DRY:-0}" = 1 ] && return 0
  if [ -n "${TB_SA_KEY_FILE:-}" ]; then
    gc_activate || { gc_expired "the service account could not be activated from TB_SA_KEY_FILE"; return 5; }
  else
    echo "gc: TB_SA_KEY_FILE is not set: the driver cannot re-activate the service account by itself" >&2
  fi
  gc_probe
}
