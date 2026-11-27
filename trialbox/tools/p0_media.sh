#!/usr/bin/env bash
# The P-0 media, built for a GitHub release (NEW-WIN-13, D-616; owner rulings D-510 and D-504: no build by the owner).
#
#   tools/p0_media.sh a OUT [--skip-bitlocker] [--inputs DIR]     Stage A: a stand-in bundle; no Docker
#   tools/p0_media.sh b OUT [--skip-bitlocker] [--inputs DIR]     Stage B: a signed rehearsal bundle; needs Docker
#
# Run from trialbox/. OUT/release then holds what the release carries: the media as tar parts (each under GitHub's
# 2 GiB asset limit) and their manifest (tools/windows_media.py parts), get-p0-media.ps1, Get-TrialBox-P0.cmd (the
# one file the owner downloads; with TB_RELEASE_BASE set, the release's address is written into it) and NOTES.md
# (what the media redistributes, with each licence). The inputs others publish are fetched into OUT/in unless they
# are already there (--inputs names a folder that holds them): Canonical's Ubuntu 24.04 WSL image, checked against
# Canonical's own list, and Microsoft's WSL package. Stage B's bundle is signed with a key made for this run only;
# its private half is removed when the script ends, the public half goes on the media (a rehearsal bundle: a site
# box refuses it, D-726).
set -euo pipefail

STAGE="${1:-}"; OUT="${2:-}"
[ "$STAGE" = a ] || [ "$STAGE" = b ] || { echo "usage: tools/p0_media.sh a|b OUT [--skip-bitlocker] [--inputs DIR]" >&2; exit 2; }
[ -n "$OUT" ] || { echo "p0_media: name an output folder" >&2; exit 2; }
shift 2
SKIP=(); IN="$OUT/in"
while [ $# -gt 0 ]; do
  case "$1" in
    --skip-bitlocker) SKIP=(--skip-bitlocker) ;;
    --inputs) IN="${2:?--inputs needs a folder}"; shift ;;
    *) echo "p0_media: unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
die() { echo "p0_media: $*" >&2; exit 1; }
[ -f deploy/windows/box-install.ps1 ] || die "run it from trialbox/"
export PYTHONPATH="libs:."
PY="${TB_P0_PYTHON:-python3}"
# Microsoft's WSL package, pinned: the version P-0's sheet was written against (wsl.2.6.1.0.x64.msi, 2026-11-13)
WSL_VERSION="${TB_P0_WSL_VERSION:-2.6.1.0}"
ROOTFS_URL="https://cloud-images.ubuntu.com/wsl/releases/24.04/current"
ROOTFS="ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz"
MSI="wsl.$WSL_VERSION.x64.msi"

mkdir -p "$IN" "$OUT"
fetch() { [ -f "$IN/$2" ] || curl -fsSL --retry 3 -o "$IN/$2" "$1/$2"; }
if [ -z "${TB_P0_NO_FETCH:-}" ]; then
  fetch "$ROOTFS_URL" "$ROOTFS"
  fetch "$ROOTFS_URL" SHA256SUMS
  (cd "$IN" && sha256sum -c --ignore-missing SHA256SUMS) || die "the Ubuntu image does not match Canonical's list"
  fetch "https://github.com/microsoft/WSL/releases/download/$WSL_VERSION" "$MSI"
  [ -d "$IN/debs" ] || "$PY" -m tools.windows_media_debs --rootfs "$IN/$ROOTFS" --out "$IN/debs"
fi
for f in "$ROOTFS" "$MSI"; do [ -f "$IN/$f" ] || die "no $IN/$f"; done
[ -d "$IN/debs" ] || die "no $IN/debs"

KEYS=""
cleanup() { [ -z "$KEYS" ] || rm -f "$KEYS"/*.key; }
trap cleanup EXIT
CHOICES=(--p0 "${SKIP[@]}")
if [ "$STAGE" = a ]; then
  VERSION=p0a
  printf 'P-0 stage A: not a bundle\n' > "$IN/trialbox-p0a.tar"
  printf 'P-0 stage A: not a key\n' > "$IN/vendor_ed25519.pub"
  BUNDLE="$IN/trialbox-p0a.tar"; PUB="$IN/vendor_ed25519.pub"
else
  VERSION=p0b
  K="$OUT/p0b"; KEYS="$K/keys"
  mkdir -p "$K/models"
  make venv
  make images
  .venv/bin/python tools/sign_bundle.py keygen --out "$KEYS"
  .venv/bin/python tools/refdata_fetch.py sample --out "$K/refdata"
  for d in gemma-4-26b-a4b-it-4bit qwen3.5-9b-4bit; do
    mkdir -p "$K/models/$d"
    printf '{"architectures": ["TrialBoxRehearsalPlaceholder"], "name": "%s"}\n' "$d" > "$K/models/$d/config.json"
    printf 'placeholder for %s: not a model\n' "$d" > "$K/models/$d/model.safetensors"
  done
  printf 'TB_TZ=Asia/Taipei\n' > "$K/.env"
  mapfile -t third < <(docker compose --project-directory "$K" -f deploy/docker-compose.yml config --images | sort -u | grep -v '^trialbox-')
  # every image a rehearsal box runs: ours (the embed service has no profile and always runs, review 2), the
  # third-party ones of the default services; the model servers are the stand-ins (trialbox-py, D-726)
  IMGS=(trialbox-py:1.0.0 trialbox-jvm:1.0.0 trialbox-postgres:16-1 trialbox-embed:1.0.0 "${third[@]}")
  for i in "${IMGS[@]}"; do docker image inspect "$i" >/dev/null 2>&1 || docker pull -q "$i"; done
  # HYG2-R2: make_bundle.sh publishes bundle-p0b inside this run's own folder; that replaces the last bundle-p0b only
  # once the bundle is built (bundle-p0b.old holds the last one only between the two renames; a failed rename puts it back)
  NEXT="$(mktemp -d "$OUT/bundle-p0b.next.XXXXXX")"
  args=(--rehearsal --key "$KEYS/vendor_ed25519.key" --id p0b --release-seq 1 --out "$NEXT/bundle-p0b/trialbox-p0b.tar" --models "$K/models")
  args+=(--refdata "$(ls "$K"/refdata/trialbox-refdata-*.tar)")
  for i in "${IMGS[@]}"; do args+=(--image "$i"); done
  make release-bundle SC_LOCAL_IMAGES=1 SC_IMAGES="${IMGS[*]}" BUNDLE_ARGS="${args[*]}" || { rm -rf "$NEXT"; exit 1; }
  P0B="$OUT/bundle-p0b"
  [ -e "$P0B" ] || [ ! -d "$P0B.old" ] || mv -T "$P0B.old" "$P0B"
  rm -rf "$P0B.old"; [ ! -e "$P0B" ] || mv -T "$P0B" "$P0B.old"
  mv -T "$NEXT/bundle-p0b" "$P0B" || { [ -e "$P0B" ] || [ ! -d "$P0B.old" ] || mv -T "$P0B.old" "$P0B"; rm -rf "$NEXT"; exit 1; }
  rm -rf "$P0B.old" "$NEXT"
  BUNDLE="$OUT/bundle-p0b/trialbox-p0b.tar"; PUB="$KEYS/vendor_ed25519.pub"
  # the images are in the bundle now: their room is given back before the media is laid out (review 6)
  docker system prune -af >/dev/null
  CHOICES+=(--rehearsal)
fi

rm -rf "${OUT:?}/media" "${OUT:?}/release"
"$PY" -m tools.windows_media build --out "$OUT/media" --version "$VERSION" --bundle "$BUNDLE" --wsl-msi "$IN/$MSI" \
  --rootfs "$IN/$ROOTFS" --debs "$IN/debs" --vendor-pub "$PUB" "${CHOICES[@]}"
[ "$STAGE" = a ] || rm -f "$BUNDLE"   # on the media now
"$PY" -m tools.windows_media parts "$OUT/media/TRIALBOX-$VERSION" --out "$OUT/release"
rm -rf "${OUT:?}/media"   # in the parts now
cp deploy/windows/get-p0-media.ps1 "$OUT/release/"
sha="$(sha256sum "$OUT/release/get-p0-media.ps1" | cut -d' ' -f1)"
msha="$(sha256sum "$OUT/release/TRIALBOX-$VERSION.manifest.json" | cut -d' ' -f1)"
sed -e "s|@RELEASE_BASE@|${TB_RELEASE_BASE:-@RELEASE_BASE@}|" -e "s|@MANIFEST_SHA256@|$msha|" \
  -e "s|@MANIFEST@|TRIALBOX-$VERSION.manifest.json|" -e "s|@SCRIPT_SHA256@|$sha|" \
  deploy/windows/Get-TrialBox-P0.cmd > "$OUT/release/Get-TrialBox-P0.cmd"
if [ "$STAGE" = b ]; then
  # the images' licence records and SBOMs (the release gates' own), beside the notes on the release page
  [ ! -f build/supply-chain/gates.json ] || cp build/supply-chain/gates.json "$OUT/release/IMAGES-gates.json"
  [ ! -f dist/sbom/index.json ] || cp dist/sbom/index.json "$OUT/release/IMAGES-sbom-index.json"
fi

# what the release redistributes, and under which licence (cited in the release's notes)
{
  echo "# TrialBox P-0 media, stage $STAGE (TRIALBOX-$VERSION)"
  echo
  echo "Download **Get-TrialBox-P0.cmd** only and double-click it with an empty USB disk (exFAT or NTFS) plugged in: it"
  echo "fetches the parts below, checks each, and puts the media on the disk. Then double-click"
  echo "Install-TrialBox-P0.cmd on the disk. Synthetic data only; no patient data. Built from commit $(git rev-parse HEAD)."
  echo
  echo "## What the media redistributes"
  echo
  echo "- Microsoft's Windows Subsystem for Linux package ($MSI), MIT licence: https://github.com/microsoft/WSL/blob/master/LICENSE"
  echo "- Canonical's Ubuntu 24.04 WSL image ($ROOTFS), from $ROOTFS_URL: Ubuntu's packages, each under its own"
  echo "  licence (many GPL or LGPL); Canonical's terms for the image and the Ubuntu name:"
  echo "  https://ubuntu.com/legal/intellectual-property-policy. Sources: https://launchpad.net/ubuntu/noble (each package's"
  echo "  source at the version in the image)."
  echo "- These packages, each under the licence in its own copyright file (/usr/share/doc/<package>/copyright):"
  for d in "$IN"/debs/*.deb; do
    n="$(basename "$d")"
    case "$n" in
      docker-*|containerd.io_*) echo "  - $n: from download.docker.com (Docker Engine, Apache-2.0; source: https://github.com/moby/moby, https://github.com/docker/cli, https://github.com/containerd/containerd)" ;;
      nvidia-*|libnvidia-*) echo "  - $n: from nvidia.github.io (NVIDIA Container Toolkit, Apache-2.0; source: https://github.com/NVIDIA/nvidia-container-toolkit)" ;;
      *) echo "  - $n: from Ubuntu's archive (source: https://launchpad.net/ubuntu/noble)" ;;
    esac
  done
  if [ "$STAGE" = b ]; then
    echo "- The container images of the bundle:"
    for i in "${IMGS[@]}"; do echo "  - $i"; done
    echo "  Each image's licences and SBOM: IMAGES-gates.json and IMAGES-sbom-index.json beside these notes (the release"
    echo "  gates' records). The two model folders are placeholders, not models."
  fi
  echo "- TrialBox's own installer and host tree, from this repository at the commit named above."
  echo
  echo "Source code for the GPL and LGPL programs in the image and the packages is at the source locations above, at the"
  echo "versions named in each file's name."
} > "$OUT/release/NOTES.md"

# the release's own check: the parts join back to a tar of the media
cat "$OUT"/release/TRIALBOX-"$VERSION".tar.part-* | sha256sum | grep -q "$("$PY" -c "import json,sys; print(json.load(open(sys.argv[1]))['sha256'])" "$OUT/release/TRIALBOX-$VERSION.manifest.json")" \
  || die "the parts do not join back to the manifest's sha256"
echo "release: $OUT/release ($(ls "$OUT/release" | wc -l) files)"
