#!/bin/sh
# Stand-in for deploy/install.sh UNDER the real deploy/box-install.sh (its knob TB_BOX_INSTALL). install.sh needs
# Docker, the bundle's images and a GPU; the paid run runs the real one. It writes the .env the install would (the
# passwords the wizard's apply keeps, the feed folder) and ends as the real one does with a FAIL list on a box with
# no backup yet: "TrialBox is running", exit 1.
echo "install-inner $*" >> "$BR_S/calls.log"
echo install >> "$BR_S/calls.log"
mkdir -p "$BR_S/feed"
printf 'POSTGRES_PASSWORD=made-by-install\nTB_SOURCE_DIR=%s\nTB_SOURCE_MOUNT=/data/source/site-a\nTB_ENV=PRODUCTION\n' "$BR_S/feed" > "$BR_S/box-root/deploy/.env"
# install.sh pins the pair from deploy/models (pin_model --install ... --out deploy/site/registry.site.yaml)
mkdir -p "$BR_S/box-root/deploy/site" && echo "builds: {}  # stand-in pins" > "$BR_S/box-root/deploy/site/registry.site.yaml"
# the installer's record of the release (Updater._record, D-994): its commit beside dirty, read from the bundle's
# release.json as the real one reads it (H-19, D-1105: the driver names the qualification record's code by it)
mkdir -p "$BR_S/box-root/deploy/updates" && python3 - "$1" "$BR_S/box-root/deploy/updates/installed.json" <<'PY'
import json, re, sys, tarfile
with tarfile.open(sys.argv[1]) as t:
    src = json.load(t.extractfile("release.json")).get("source") or {}
c = src.get("commit")
ok = isinstance(c, str) and re.fullmatch(r"[0-9a-f]{40}", c)
rec = {"commit": c if ok else None, "dirty": src.get("dirty") is True}
json.dump(rec, open(sys.argv[2], "w"))
PY
echo '  TrialBox is running.'
echo 'install: FAIL: no backup yet' >&2
exit 1
