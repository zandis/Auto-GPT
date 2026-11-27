#!/bin/bash
# bundle.sh ID SEQ OUTDIR : the signed rehearsal bundle of a checkout's trialbox/ folder (TREE, default this one), as the
# integration builds make it:
# the images built fresh, the release gates on them, make_bundle with the vendor key. Writes OUTDIR/trialbox-ID.tar,
# the signed bootstrap beside it and vendor_ed25519.pub. Needs VENDOR_KEY (the signing key, never printed), MODELS_DIR
# and REFDATA (a refdata tar); JAVA_HOME, mvn and docker on PATH. The images go to docker's own disk (about 25 GB at
# the peak), the tar (about 60 GB) to OUTDIR.
set -u
ID=${1:?bundle id, e.g. int-685faed0-p}
SEQ=${2:?release seq}
OUTDIR=${3:?output folder}
T=$(cd "${TREE:-$(dirname "$0")/../..}" && pwd)
cd "$T" || exit 2
: "${VENDOR_KEY:?}" "${MODELS_DIR:?}" "${REFDATA:?}"
mkdir -p "$OUTDIR"
L=$OUTDIR/build-$ID.log
: > "$L"
s=$(date +%s)
fail() { echo "bundle: FAILED at $1 after $(($(date +%s) - s)) s (see $L)" | tee -a "$L"; exit 1; }
{ make venv && make images BUILD_ARGS="--no-cache" && make trivy-db; } >> "$L" 2>&1 || fail images
cfg=$(mktemp -d)
ans() { sed -n "s/^$1: *['\"]\{0,1\}\([A-Za-z0-9_+\/.-]*\).*/\1/p" tools/rehearse_box/site_answers.yaml | head -1; }
printf 'TB_TZ=%s\nTB_TLS_HOSTNAME=%s\n' "$(ans tz)" "$(ans tls_hostname)" > "$cfg/.env"
imgs=(trialbox-py:1.0.0 trialbox-backup:1.0.0 trialbox-jvm:1.0.0 trialbox-embed:1.0.0 trialbox-postgres:16-1)
while IFS= read -r i; do
  case "$i" in trialbox-*) ;; *) imgs+=("$i") ;; esac
done < <(docker compose --profile gpu --project-directory "$cfg" -f deploy/docker-compose.yml -f deploy/docker-compose.secrets.yml \
  -f deploy/docker-compose.rtxpro6000.yml -f deploy/docker-compose.identity.yml config --images | sort -u)
rm -rf "$cfg"
ia=()
for i in "${imgs[@]}"; do
  docker image inspect "$i" > /dev/null 2>&1 || docker pull -q "$i" >> "$L" 2>&1 || fail "pull $i"
  case "$i" in trialbox-backup:*) ia+=(--job-image "$i") ;; *) ia+=(--image "$i") ;; esac
done
make release-bundle SC_LOCAL_IMAGES=1 SC_IMAGES="${imgs[*]}" BUNDLE_ARGS="--rehearsal --key $VENDOR_KEY --id $ID --release-seq $SEQ --out $OUTDIR/trialbox-$ID.tar --models $MODELS_DIR --refdata $REFDATA ${ia[*]}" >> "$L" 2>&1 || fail release-bundle
openssl pkey -in "$VENDOR_KEY" -pubout -out "$OUTDIR/vendor_ed25519.pub" 2>> "$L" || fail "public key"
echo "bundle: $OUTDIR/trialbox-$ID.tar $(stat -c %s "$OUTDIR/trialbox-$ID.tar") bytes in $(($(date +%s) - s)) s" | tee -a "$L"
