#!/bin/sh
# Every start of the box mounts the site's settings, never the example (D-888, found on lane G's box). Each service
# mounts ${TB_SETTINGS_FILE:-./settings.example.yaml} (deploy/docker-compose.yml); compose takes TB_SETTINGS_FILE
# from the environment, else from deploy/.env, which install.sh writes. Run before every start that is not
# install.sh: the systemd unit (ExecStartPre) and tools/apply_update.sh.
#
#   deploy/settings_guard.sh DEPLOY_DIR
#
# Exit 0 when the box has no site settings yet (a first install loads its bundle first) or when compose would mount
# them; exit 1, saying what to add, when a site settings.yaml exists and the example would be mounted instead.
set -eu
DEPLOY="${1:?usage: settings_guard.sh DEPLOY_DIR}"
[ -f "$DEPLOY/settings.yaml" ] || exit 0
got="${TB_SETTINGS_FILE:-$(sed -n 's/^TB_SETTINGS_FILE=//p' "$DEPLOY/.env" 2>/dev/null | tail -1)}"
case "$got" in
  ./settings.yaml|settings.yaml|"$DEPLOY/settings.yaml") exit 0 ;;
esac
echo "TrialBox REFUSED to start on the example settings: $DEPLOY/settings.yaml is this site's, but compose would mount ${got:-./settings.example.yaml} (TB_SETTINGS_FILE). Add TB_SETTINGS_FILE=./settings.yaml to $DEPLOY/.env (or run deploy/install.sh again, which writes it), then start again" >&2
exit 1
