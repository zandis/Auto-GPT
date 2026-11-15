#!/bin/sh
# Stand-in for deploy/install.sh in validation mode (TB_BOXRUN_INSTALL): `install.sh BUNDLE --answers F --gpu P
# --mode gpu --yes`. The paid run runs the real one (Docker, the bundle's images, the GPU). It writes the .env the
# settings wizard would from the answers (TB_ENV from env_extra, as tools/settings_wizard.py env_extra does; the
# feed folder), the settings.yaml the limits step edits, prints the first administrator's password and enrolment
# code once as the real installer does (the VM script must redact them), and ends with a FAIL list: exit 1.
set -eu
echo "install-validation $*" >> "$BR_S/calls.log"
echo install >> "$BR_S/calls.log"
ans=""; while [ $# -gt 0 ]; do [ "$1" = --answers ] && ans=$2; shift; done
envname=$(sed -n 's/^ *TB_ENV: *//p' "$ans" | tr -d "\"' ")
mkdir -p "$BR_S/feed" "$BR_S/box-root/deploy"
printf 'POSTGRES_PASSWORD=made-by-install\nTB_SOURCE_DIR=%s\nTB_SOURCE_MOUNT=/data/source/site-a\nTB_TZ=Asia/Taipei\n' "$BR_S/feed" > "$BR_S/box-root/deploy/.env"
[ -z "$envname" ] || echo "TB_ENV=$envname" >> "$BR_S/box-root/deploy/.env"
# the other declared settings of env_extra (the run's limits, D-775), and the MTA's id (mta_authserv_id, D-825)
sed -n 's/^  \(TB_[A-Z_]*\): *"\{0,1\}\([^"]*\)"\{0,1\}$/\1=\2/p' "$ans" | grep -v '^TB_ENV=' >> "$BR_S/box-root/deploy/.env"
auth=$(sed -n 's/^mta_authserv_id: *//p' "$ans" | tr -d "\"' ")
[ -z "$auth" ] || echo "TB_MAIL_AUTHSERV_ID=$auth" >> "$BR_S/box-root/deploy/.env"
grep -q '^TB_ENV=' "$BR_S/box-root/deploy/.env" || echo "TB_ENV=PRODUCTION" >> "$BR_S/box-root/deploy/.env"
printf 'site: {id: ACC-VALIDATION}\nrate_limit_per_sender_per_day: 20\n' > "$BR_S/box-root/deploy/settings.yaml"
python3 "$BR_HERE/standins/box.py" wizard-done
echo "    admin password: standin-admin-pw-0001"
echo "    enrolment code: ENROL-424242-STANDIN"
# install.sh pins the pair from deploy/models (pin_model --install ... --out deploy/site/registry.site.yaml)
mkdir -p "$BR_S/box-root/deploy/site" && echo "builds: {}  # stand-in pins" > "$BR_S/box-root/deploy/site/registry.site.yaml"
echo '  TrialBox is running.'
echo 'install: FAIL: no backup yet' >&2
exit 1
