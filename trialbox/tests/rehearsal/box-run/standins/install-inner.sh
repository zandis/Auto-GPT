#!/bin/sh
# Stand-in for deploy/install.sh UNDER the real deploy/box-install.sh (its knob TB_BOX_INSTALL). install.sh needs
# Docker, the bundle's images and a GPU; the paid run runs the real one. It writes the .env the install would (the
# passwords the wizard's apply keeps, the feed folder) and ends as the real one does with a FAIL list on a box with
# no backup yet: "TrialBox is running", exit 1.
d="$(cd "$(dirname "$0")" && pwd)"
echo "install-inner $*" >> "$BR_S/calls.log"
echo install >> "$BR_S/calls.log"
mkdir -p "$BR_S/feed"
printf 'POSTGRES_PASSWORD=made-by-install\nTB_SOURCE_DIR=%s\nTB_SOURCE_MOUNT=/data/source/site-a\nTB_ENV=PRODUCTION\n' "$BR_S/feed" > "$BR_S/box-root/deploy/.env"
echo '  TrialBox is running.'
echo 'install: FAIL: no backup yet' >&2
exit 1
