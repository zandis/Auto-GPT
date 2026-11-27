#!/bin/bash
# nightly.sh: the e2e-box gate on the newest head of BRANCH (default master) of REMOTE (default origin), in its own
# checkout under E2E_HOME. Builds the head's bundle and a second bundle of the same tree one release later (the update
# journey's), makes the second one's media, runs the head's own run.sh with the last run's journeys.csv as BASELINE,
# then removes the bundles it made. Inputs of bundle.sh and run.sh come from the environment (README.md).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
E2E_HOME=${E2E_HOME:-$HOME/e2e-box}
D=${E2E_VMS:-/dev/shm/e2e-box}
CO=$E2E_HOME/tree
[ -d "$CO/.git" ] || git clone -q "$(git -C "$HERE" remote get-url "${REMOTE:-origin}")" "$CO" || exit 2
git -C "$CO" fetch -q "${REMOTE:-origin}" "${BRANCH:-master}" && git -C "$CO" checkout -q --detach FETCH_HEAD || exit 2
SHA=$(git -C "$CO" rev-parse --short=8 HEAD)
SEQ=${SEQ:-$(date -u +%Y%m%d)}
export TREE=$CO/trialbox
bash "$HERE/bundle.sh" "int-$SHA-p" "$SEQ" "$D/dist" || exit 3
if bash "$HERE/bundle.sh" "int-$SHA-plus1-p" "$((SEQ + 1))" "$D/next"; then
  size=$(($(du -sb "$D/next" | cut -f1) / 1073741824 + 4))
  mke2fs -q -t ext4 -m 0 -d "$D/next" "$D/next-media.img" "${size}G" && echo "int-$SHA-plus1-p" > "$D/next-media.img.ready"
  rm -rf "$D/next"
fi
BASELINE=$(grep -l '^E2E .* GREEN ' "$E2E_HOME"/runs/*/verdict 2> /dev/null | sort | tail -1)
BASELINE=${BASELINE:+$(dirname "$BASELINE")/metrics/journeys.csv}
BUNDLE=$D/dist/trialbox-int-$SHA-p.tar NEXT_IMG=$D/next-media.img BASELINE=$BASELINE bash "$TREE/tests/e2e-box/run.sh"
rc=$?
rm -rf "${D:?}/dist" "${D:?}/next-media.img" "${D:?}/next-media.img.ready"
exit $rc
