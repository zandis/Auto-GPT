#!/usr/bin/env bash
# TB-PLAN-04 step 8 done-check on the demo VM (D-138): `apply_update` on the demo image, then `e2e_simple` passes;
# and a broken update rolls back. Needs the owner's OK: the VM costs about US$0.15 an hour while it runs.
#
#   deploy/gcp/demo-vm-update.sh build  BUCKET          # here (Docker): image A, bundles B (good) and C (broken)
#   deploy/gcp/demo-vm-update.sh run    BUCKET [VM] [ZONE]   # the VM must be RUNNING: A, apply B, apply C
#
# build: A = `make demo-bundle` (this commit); B = the same image with a release label (a new image id), signed
# with a throwaway vendor key into a bundle; C = an image that never answers (CMD exits), signed the same way.
# Everything goes to gs://BUCKET/step8/ with the trialbox tree (tools, deploy) the VM runs apply_update.sh from.
# run: on the VM, over ssh: the startup script's container from A, then
#   tools/apply_update.sh B --target demo   -> backup, rollback point, load, recreate, e2e_simple in the container
#   tools/apply_update.sh C --target demo   -> the container never answers: rolled back to B and checked again
# and prints the history. This script never creates, starts or stops a VM.
set -euo pipefail
CMD="${1:-}"; BUCKET="${2:?usage: demo-vm-update.sh build|run BUCKET [VM] [ZONE]}"
VM="${3:-trialbox-demo}"; ZONE="${4:-asia-east1-b}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIST="$ROOT/dist/step8"
case "$CMD" in
  build)
    mkdir -p "$DIST"
    (cd "$ROOT" && make demo-bundle)                                        # A: dist/trialbox-demo.tar.gz
    "${PY:-$ROOT/.venv/bin/python}" "$ROOT/tools/sign_bundle.py" keygen "$DIST/keys"
    # HYG2-R2: make_bundle.sh publishes B and C into bundles/ inside this build's own folder; that replaces the last
    # bundles/ as ONE folder, only once both are built: a failed build, a failed rename or a cut leaves the last pair
    # as it was, never a new B beside an old C (bundles.old holds the last pair only between the two renames below)
    NEXT="$(mktemp -d "$DIST/bundles.next.XXXXXX")"
    trap 'rm -rf "$NEXT"' EXIT
    docker build -f "$ROOT/demo/Dockerfile" --label trialbox.release=step8-b -t trialbox-demo:step5 "$ROOT"
    # no bundle without its checks (T-110b, D-340): each image goes through the release gates before its bundle
    (cd "$ROOT" && make release-gates SC_LOCAL_IMAGES=1 SC_DIR="$DIST/gates-b" SC_IMAGES=trialbox-demo:step5)
    "$ROOT/tools/make_bundle.sh" --key "$DIST/keys/vendor_ed25519.key" --id 2026.11-step8-demo-b --release-seq 1 \
      --gates "$DIST/gates-b/gates.json" --sbom-dir "$ROOT/dist/sbom" \
      --image trialbox-demo:step5 --no-third-party --pub "$DIST/keys/vendor_ed25519.pub" --out "$NEXT/bundles/b/trialbox-step8-b.tar"
    printf 'FROM trialbox-demo:step5\nCMD ["false"]\n' | docker build -t trialbox-demo:step5-broken -
    docker tag trialbox-demo:step5-broken trialbox-demo:step5
    (cd "$ROOT" && make release-gates SC_LOCAL_IMAGES=1 SC_DIR="$DIST/gates-c" SC_IMAGES=trialbox-demo:step5)
    "$ROOT/tools/make_bundle.sh" --key "$DIST/keys/vendor_ed25519.key" --id 2026.11-step8-demo-c --release-seq 2 \
      --gates "$DIST/gates-c/gates.json" --sbom-dir "$ROOT/dist/sbom" \
      --image trialbox-demo:step5 --no-third-party --pub "$DIST/keys/vendor_ed25519.pub" --out "$NEXT/bundles/c/trialbox-step8-c.tar"
    L="$DIST/bundles"
    [ -e "$L" ] || [ ! -d "$L.old" ] || mv -T "$L.old" "$L"
    rm -rf "$L.old"; [ ! -e "$L" ] || mv -T "$L" "$L.old"
    mv -T "$NEXT/bundles" "$L" || { [ -e "$L" ] || [ ! -d "$L.old" ] || mv -T "$L.old" "$L"; exit 1; }
    rm -rf "$L.old"
    tar -C "$ROOT" -czf "$DIST/trialbox-tree.tar.gz" tools libs deploy/gcp deploy/keys 2>/dev/null \
      || tar -C "$ROOT" -czf "$DIST/trialbox-tree.tar.gz" tools libs deploy/gcp
    gcloud storage cp "$ROOT/dist/trialbox-demo.tar.gz" "$L/b/trialbox-step8-b.tar" "$L/c/trialbox-step8-c.tar" \
      "$DIST/trialbox-tree.tar.gz" "$DIST/keys/vendor_ed25519.pub" "gs://$BUCKET/step8/"
    echo "uploaded to gs://$BUCKET/step8/ (the vendor key is a throwaway for this drill)" ;;
  run)
    STATUS="$(gcloud compute instances describe "$VM" --zone "$ZONE" --format='value(status)')"
    [ "$STATUS" = RUNNING ] || { echo "VM $VM is $STATUS, not RUNNING. This script does not start VMs." >&2; exit 2; }
    gcloud compute ssh "$VM" --zone "$ZONE" --command "sudo bash -s" <<EOS
set -euo pipefail
mkdir -p /opt/trialbox && cd /opt/trialbox
gcloud storage cp "gs://$BUCKET/step8/*" .
tar -xzf trialbox-tree.tar.gz
mkdir -p deploy/keys && cp vendor_ed25519.pub deploy/keys/vendor_ed25519.pub
gunzip -c trialbox-demo.tar.gz | docker load
docker rm -f trialbox-demo >/dev/null 2>&1 || true
sh /etc/trialbox-demo/run.sh trialbox-demo:step5
for i in \$(seq 1 120); do curl -sf -o /dev/null http://127.0.0.1/login && break; sleep 5; done
export TB_PY_IMAGE=trialbox-demo:step5 TB_VERIFY_IN_DOCKER=1
echo "== B: a good update"
tools/apply_update.sh trialbox-step8-b.tar --target demo
echo "== C: a broken update (must roll back)"
TB_DEMO_WAIT_S=240 tools/apply_update.sh trialbox-step8-c.tar --target demo && { echo "C did not fail"; exit 1; } || true
docker exec trialbox-demo python -m tools.e2e_simple --dir /tmp/tb-e2e-after-rollback | tail -3
cat deploy/updates/history.jsonl
EOS
    echo "done; stop the VM when finished: gcloud compute instances stop $VM --zone $ZONE" ;;
  *) sed -n 2,16p "$0"; exit 2 ;;
esac
