# shellcheck shell=bash
# Fresh auth for every gcloud call of the complete run (D-141). Source it; then call `gc <gcloud args>` instead of
# `gcloud <gcloud args>`.
#
#   export CLOUDSDK_CONFIG=<a private folder>          # never the default ~/.config/gcloud
#   export TB_SA_KEY_FILE=<the service account key file, in place>   # read by gcloud only, never printed
#   . deploy/gcp/gcloud-auth.sh
#   gc_probe                                            # fails fast when no credential works (before anything starts)
#   gc compute instances describe tb-gpu-sim --zone asia-east1-a --format='value(status)'
#
# A call that fails with an authentication error (an expired or revoked token, "Reauthentication required",
# UNAUTHENTICATED, 401) re-activates the service account from TB_SA_KEY_FILE and is retried once; any other error is
# returned as it is. The key file's path is printed at most; its content never is (gcloud reads it itself, and
# stderr of the re-activation is dropped). GC_DRY=1 prints the commands instead of running them.

gc_auth_error() {  # $1: a file with the failed call's stderr
  grep -qiE 'reauthentication|invalid authentication credentials|UNAUTHENTICATED|invalid_grant|401|'\
'Request had invalid authentication|There was a problem refreshing your current auth tokens|'\
'You do not currently have an active account' "$1"
}

gc_activate() {
  [ -n "${TB_SA_KEY_FILE:-}" ] && [ -r "$TB_SA_KEY_FILE" ] || { echo "gc: no readable TB_SA_KEY_FILE to re-activate" >&2; return 1; }
  gcloud auth activate-service-account --key-file "$TB_SA_KEY_FILE" --quiet >/dev/null 2>&1
}

gc() {
  if [ "${GC_DRY:-0}" = 1 ]; then echo "+ gcloud $*"; return 0; fi
  local err rc
  err="$(mktemp)"
  gcloud "$@" 2>"$err"
  rc=$?
  if [ "$rc" != 0 ] && gc_auth_error "$err"; then
    echo "gc: authentication failed; re-activating the service account and trying once more" >&2
    if gc_activate; then
      gcloud "$@" 2>"$err"
      rc=$?
    fi
  fi
  [ "$rc" = 0 ] || sed 's/^/gcloud: /' "$err" >&2
  rm -f "$err"
  return "$rc"
}

gc_probe() {  # a dead or skewed credential fails here, before the paid VM starts
  [ "${GC_DRY:-0}" = 1 ] && { echo "+ gcloud auth print-access-token (probe)"; return 0; }
  gc auth print-access-token >/dev/null || { echo "gc: no usable credential in ${CLOUDSDK_CONFIG:-the default config}" >&2; return 5; }
}
