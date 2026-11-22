#!/bin/sh
# Every start of the box mounts the site's settings, never the example (D-888, found on lane G's box). Each service
# mounts ${TB_SETTINGS_FILE:-./settings.example.yaml} (deploy/docker-compose.yml); compose takes TB_SETTINGS_FILE
# from the environment, else from deploy/.env, which install.sh writes. Run before every start that is not
# install.sh: the systemd unit (ExecStartPre) and tools/apply_update.sh.
#
#   deploy/settings_guard.sh DEPLOY_DIR
#
# 10K-4: before that, the audit anchor folder the console is given is checked again (exit 1 when it may not be).
# Exit 0 when the box has no site settings yet (a first install loads its bundle first) or when compose would mount
# them; exit 1, saying what to add, when a site settings.yaml exists and the example would be mounted instead.
set -eu
DEPLOY="${1:?usage: settings_guard.sh DEPLOY_DIR}"
# 10K-4 (D-1390): the audit anchor folder is bind-mounted into the console, and docker resolves its path again at
# every start: when the box mounts one (deploy/site/compose.anchors.yml), the rule for a folder the console may be
# given is checked again here (no link in its path, parents only root may write, no system folder; finish-check
# --anchor-only), and the stack does not start when it no longer holds
if [ -f "$DEPLOY/site/compose.anchors.yml" ]; then
  if ! (cd "$DEPLOY/.." && python3 -m tools.trialbox finish-check --deploy "$DEPLOY" --anchor-only) >&2; then
    echo "TrialBox REFUSED to start: the audit anchor folder it would give the console no longer passes the rule (above), or the check could not run. Correct TB_AUDIT_ANCHOR_TARGETS in $DEPLOY/.env and run deploy/install.sh again (RUNBOOK §5)" >&2
    exit 1
  fi
fi
# H-89: a box that carries a rehearsal sign starts only as a whole rehearsal box, never as PRODUCTION (a hand edit of
# TB_ENV before a reboot): tools/rehearsal_real.py start. A box without a sign is not asked
if [ -f "$DEPLOY/site/rehearsal.json" ] || [ -f "$DEPLOY/site/rehearsal-real-servers.json" ] || [ -f "$DEPLOY/site/rehearsal-real-servers.yml" ] \
  || grep -qE '^[[:space:]]*(export[[:space:]]+)?TB_REHEARSAL(_REAL_SERVERS)?=|rehearsal-real-servers' "$DEPLOY/.env" 2>/dev/null; then
  if ! (cd "$DEPLOY/.." && python3 -m tools.rehearsal_real start --deploy "$DEPLOY") >&2; then
    echo "TrialBox REFUSED to start: this box carries a rehearsal sign and is not a whole rehearsal box (above), or the check could not run. A rehearsal box never becomes a site's box: install the site's box afresh on an empty box (RUNBOOK §16)" >&2
    exit 1
  fi
fi
[ -f "$DEPLOY/settings.yaml" ] || exit 0
got="${TB_SETTINGS_FILE:-$(sed -n 's/^TB_SETTINGS_FILE=//p' "$DEPLOY/.env" 2>/dev/null | tail -1)}"
case "$got" in
  ./settings.yaml|settings.yaml|"$DEPLOY/settings.yaml") exit 0 ;;
esac
echo "TrialBox REFUSED to start on the example settings: $DEPLOY/settings.yaml is this site's, but compose would mount ${got:-./settings.example.yaml} (TB_SETTINGS_FILE). Add TB_SETTINGS_FILE=./settings.yaml to $DEPLOY/.env (or run deploy/install.sh again, which writes it), then start again" >&2
exit 1
