#!/usr/bin/env bash
# Vendor side: build the one-file offline release bundle that deploy/install.sh (new site) and tools/apply_update.sh
# (existing site) accept. Images are exported with `docker save`; models, rulesets and the installer ride along; the
# manifest is Ed25519-signed with the vendor key (tools/sign_bundle.py, D-77). Nothing in it is site-specific.
#
#   tools/make_bundle.sh --key keys/vendor_ed25519.key --id 2026.11-1 --release-seq 3 --out dist/trialbox-2026.11-1.tar \
#       --gates build/supply-chain/gates.json [--sbom-dir dist/sbom] [--models deploy/models] [--rulesets dist/rulesets] \
#       [--refdata dist/trialbox-refdata-<date>.tar ...] [--image trialbox-py:1.0.0 --image trialbox-jvm:1.0.0 ...]
#       [--job-image trialbox-backup:1.0.0]   (an image the box runs as a one-off job: release.json `runs: job`, D-968)
#       [--allow-dirty "<reason>"]   (a rehearsal or a test only: builds from a working tree, D-631)
#       [--rehearsal]                (a bundle for a rehearsal box: release.json says so; a site box refuses it, D-726)
#       [--platform linux/arm64]     (the box's architecture, default linux/amd64: every image is pulled and checked
#                                    for it, release.json records it, and the update path refuses the bundle on a
#                                    host of another architecture)
#       [--model-pack-out DIR/trialbox-models-<id>.pack [--model-id ID] [--model-release-seq N]]
#       [--model-pack DIR/trialbox-models-<id>.pack]   (H-95: see below)
#
# H-95, two packs: --model-pack-out FILE splits the release. The model pack (FILE, named trialbox-models-*.pack so the
# installer finds it beside the software pack and the launcher never takes it for a release) carries the engine image
# (every image whose repository images.lock pins with a gpu entry) and the weights (--models); it is signed on its
# own (--model-id, default <id>-models; --model-release-seq, default --release-seq). The software pack (--out) carries
# everything else and names the model pack by its signed identity (its bundle id and the sha256 of its signed
# manifest). --model-pack FILE builds a software pack alone for an existing model pack (an update): no engine image
# and no --models in it. Without either: one whole bundle, as before.
# An image the stack pins by digest (images.lock third_party) given by its tag alone is refused before anything is
# saved: such a bundle would carry no image-pins.json (the integrator's 7097604232).
#
# The release gates are not optional (T-110b, D-340; CR-046): --gates names the passing record of `make release-gates`
# (D-186), and the bundle is refused unless every image it carries is a passing image of that record (Trivy, SBOM and
# licence gates of these exact images, at most 7 days old, no finding left in report mode). `make release-bundle` runs
# the gates first. tools/release.py then writes release.json (version, commit, every image by digest with its SBOM,
# every file with its sha256) and the release's images.lock; the SBOMs, NOTICE and CHANGELOG.md ride inside the signed
# bundle, and `tools/release.py check` re-reads the signed bundle before it is handed over.
# Default images: every image the box's compose file runs (profiles stub and gpu): ours (trialbox-py, trialbox-jvm,
# trialbox-postgres) and the third-party ones (so the site needs no registry access), and the nightly backup's image
# (trialbox-backup, D-968), a job image: release.json marks each image `runs: service` or `runs: job`. Never the test mail servers of
# docker-compose.test.yml (OPS-017). --no-third-party keeps ours only, for a site that mirrors the others itself.
# --refdata adds a reference data pack (tools/refdata_fetch.py build; payload kind refdata, D-140), which install.sh
# loads once the box runs.
# The host tree rides in every bundle (T-631, D-367; OPS-010): the compose files, the host tools (tools/, libs/,
# schemas/) and the release's configuration as one payload of kind host (trialbox-host.tar with its HOST-SHA256SUMS,
# tools/host_tree.py pack: what git holds, never the site's own files). install.sh and the update path unpack it to
# /opt/trialbox/releases/<id> and switch /opt/trialbox/current to it; a rollback switches back.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY=""; ID=""; OUT=""; MODELS=""; RULESETS=""; THIRD=1; GATES=""; SEQ=""; SBOM_DIR=""; DIRTY=0; DIRTY_WHY=""; REHEARSAL=()
IMAGES=(); REFDATA=(); JOBS=(); MODEL_OUT=""; MODEL_HAVE=""; MODEL_ID=""; MODEL_SEQ=""; PLATFORM="linux/amd64"
while [ $# -gt 0 ]; do
  case "$1" in
    --key) KEY="$2"; shift ;;
    --id) ID="$2"; shift ;;
    --out) OUT="$2"; shift ;;
    --models) MODELS="$2"; shift ;;
    --rulesets) RULESETS="$2"; shift ;;
    --refdata) REFDATA+=("$2"); shift ;;
    --image) IMAGES+=("$2"); shift ;;
    --job-image) IMAGES+=("$2"); JOBS+=(--job "$2"); shift ;;  # D-968: an image the box runs as a one-off job
    --no-third-party) THIRD=0 ;;
    --gates) GATES="$2"; shift ;;
    --sbom-dir) SBOM_DIR="$2"; shift ;;
    --release-seq) SEQ="$2"; shift ;;
    --allow-dirty)
      case "${2:-}" in ""|--*) echo "make_bundle: --allow-dirty needs a reason (--allow-dirty \"a rehearsal\")" >&2; exit 2 ;; esac
      DIRTY=1; DIRTY_WHY="$2"; shift ;;
    --rehearsal) REHEARSAL=(--rehearsal) ;;
    --model-pack-out) MODEL_OUT="$2"; shift ;;
    --model-pack) MODEL_HAVE="$2"; shift ;;
    --model-id) MODEL_ID="$2"; shift ;;
    --model-release-seq) MODEL_SEQ="$2"; shift ;;
    --platform) PLATFORM="$2"; shift ;;
    -h|--help) sed -n 2,41p "$0"; exit 0 ;;
    *) echo "make_bundle: unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
[ -n "$KEY" ] && [ -n "$ID" ] && [ -n "$OUT" ] && [ -n "$SEQ" ] || {
  echo "make_bundle: --key, --id, --release-seq and --out are required" >&2; exit 2; }
# no bundle without its checks (T-110b, CR-046): there is no way to build one past the release gates
[ -n "$GATES" ] || { echo "make_bundle: --gates is required: a bundle is built only from images that passed the release gates (make release-bundle)" >&2; exit 2; }
[ -f "$GATES" ] || { echo "make_bundle: no such gate record $GATES" >&2; exit 2; }
GATES="$(cd "$(dirname "$GATES")" && pwd)/$(basename "$GATES")"
SBOM_DIR="${SBOM_DIR:-$ROOT/dist/sbom}"
[ -d "$SBOM_DIR" ] || { echo "make_bundle: no SBOM folder $SBOM_DIR (make release-gates writes it)" >&2; exit 2; }
[ -f "$KEY" ] || { echo "make_bundle: no such key $KEY" >&2; exit 2; }
case "$PLATFORM" in linux/amd64|linux/arm64) ;; *)
  echo "make_bundle: --platform is linux/amd64 or linux/arm64, not $PLATFORM" >&2; exit 2 ;; esac
# H-95: the two packs' options
if [ -n "$MODEL_OUT" ] && [ -n "$MODEL_HAVE" ]; then
  echo "make_bundle: --model-pack-out builds a model pack, --model-pack names an existing one: one of the two" >&2; exit 2
fi
if [ -n "$MODEL_OUT" ]; then
  case "$(basename "$MODEL_OUT")" in trialbox-models-*.pack) ;; *)
    echo "make_bundle: --model-pack-out must be named trialbox-models-<id>.pack (the installer finds it beside the software pack)" >&2; exit 2 ;; esac
  [ -n "$MODELS" ] || { echo "make_bundle: --model-pack-out needs --models (the weights ride in the model pack)" >&2; exit 2; }
fi
if [ -n "$MODEL_HAVE" ]; then
  [ -f "$MODEL_HAVE" ] || { echo "make_bundle: no such model pack $MODEL_HAVE" >&2; exit 2; }
  [ -z "$MODELS" ] || { echo "make_bundle: --models goes into the model pack, not a software pack for an existing one (--model-pack)" >&2; exit 2; }
fi
[ -n "$MODEL_OUT$MODEL_HAVE" ] || [ -z "$MODEL_ID$MODEL_SEQ" ] || { echo "make_bundle: --model-id and --model-release-seq go with --model-pack-out" >&2; exit 2; }
MODEL_ID="${MODEL_ID:-$ID-models}"; MODEL_SEQ="${MODEL_SEQ:-$SEQ}"
PY="${PY:-$ROOT/.venv/bin/python}"; [ -x "$PY" ] || PY=python3
# 7097604232: an image the stack pins by digest (deploy/images.lock third_party), given here by its tag alone, would
# make a bundle without image-pins.json, and the box could not find it offline: refused before anything is exported
PINNED_BY_TAG='import json, sys
lock = json.load(open(sys.argv[1]))
pinned = {}
for e in (lock.get("third_party") or {}).values():
    ref, dig = str(e.get("image") or ""), str(e.get("digest") or "")
    if ref and dig.startswith("sha256:"):
        pinned[ref.rsplit(":", 1)[0] if ":" in ref.rsplit("/", 1)[-1] else ref] = f"{ref}@{dig}"
bad = []
for img in sys.argv[2:]:
    if "@sha256:" in img:
        continue
    repo = img.rsplit(":", 1)[0] if ":" in img.rsplit("/", 1)[-1] else img
    if repo in pinned:
        bad.append(f"{img} (the stack pins {pinned[repo]})")
if bad:
    print("make_bundle: an image the stack pins by digest is given without its digest: " + "; ".join(bad)
          + ". Give it as REF@sha256:DIGEST: a bundle without its image pins is never made (7097604232)", file=sys.stderr)
    sys.exit(2)'
if [ ${#IMAGES[@]} -gt 0 ]; then
  "$PY" -c "$PINNED_BY_TAG" "$ROOT/deploy/images.lock" "${IMAGES[@]}" || exit 2
fi
# D-631: a release is built from a commit. The host tree is packed from the files on disk (untracked ones too), so a
# checkout that differs from its commit is refused before anything is exported, and looked at again once the host
# tree is packed; --allow-dirty "<reason>" is for a rehearsal or a test, and release.json then says dirty
tree_changes() {
  # every changed, staged or untracked (not ignored) file of the project folder, and every file git was told not to
  # look at (assume-unchanged, skip-worktree: `git status` is silent on those, the pack reads them from disk);
  # tools/release.py tree_changes asks the same
  local st hid
  st="$(git -C "$ROOT" -c core.quotePath=false status --porcelain --untracked-files=all -- . 2>&1)" \
    || { printf 'not a git checkout: a release is built from a commit (%s)\n' "$(printf '%s' "$st" | head -c 300)"; return 0; }
  hid="$(git -C "$ROOT" -c core.quotePath=false ls-files -v -- . 2>/dev/null | grep -E '^([a-z]|S) ' || true)"
  [ -z "$st" ] || printf '%s\n' "$st"
  [ -z "$hid" ] || printf '%s\n' "$hid" | sed 's/$/   (hidden from git: assume-unchanged or skip-worktree)/'
}
show_changes() {  # the first 20 of $1, and how many more; sed reads all of its input (no SIGPIPE under pipefail)
  local n
  printf '%s\n' "$1" | sed -n '1,20s/^/    /p'
  n="$(printf '%s\n' "$1" | wc -l)"
  [ "$n" -le 20 ] || echo "    ... and $((n - 20)) more"
}
CHANGES="$(tree_changes)"
if [ -n "$CHANGES" ]; then
  if [ "$DIRTY" = 1 ]; then
    { echo "make_bundle: NOT a release: built from a working tree ($DIRTY_WHY); release.json says dirty. Differs from the commit:"
      show_changes "$CHANGES"; } >&2
  else
    { echo "make_bundle: this checkout differs from its commit; a release is built from a commit (commit or remove these, or --allow-dirty \"<reason>\" for a rehearsal):"
      show_changes "$CHANGES"; } >&2
    exit 2
  fi
fi
command -v docker >/dev/null || { echo "make_bundle: docker is needed to export images" >&2; exit 2; }

STAGE="$(mktemp -d "${TMPDIR:-/tmp}/tb-bundle.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT INT TERM
if [ ${#IMAGES[@]} -eq 0 ]; then
  # every image the box's compose file runs, ours included, from the rendered config (profiles stub and gpu; not the
  # test file: no test mail server in a hospital bundle, OPS-017). An empty .env of its own: on a vendor machine
  # without deploy/.env compose renders nothing, and the bundle silently had no third-party image (D-176)
  # The identity overlay too (Caddy, Authelia): install.sh adds it on every PRODUCTION box (T-632, D-382).
  # D-828: every variable the files require (${VAR:?...}: TB_TLS_HOSTNAME, TB_TZ, ...) gets a placeholder, only the
  # images are read; a failed render shows compose's own error
  mkdir -p "$STAGE/cfg"
  grep -ohE '\$\{[A-Za-z0-9_]+:?\?' "$ROOT/deploy/docker-compose.yml" "$ROOT/deploy/docker-compose.identity.yml" \
    | sed -E 's/^\$\{//; s/:?\?$//' | sort -u | while IFS= read -r var; do
        case "$var" in TB_TZ) echo "TB_TZ=UTC" ;; *) echo "$var=bundle.invalid" ;; esac
      done > "$STAGE/cfg/.env"
  while IFS= read -r img; do
    case "$img" in trialbox-*) IMAGES+=("$img") ;; *) [ "$THIRD" = 1 ] && IMAGES+=("$img") ;; esac
  done < <(docker compose --project-directory "$STAGE/cfg" -f "$ROOT/deploy/docker-compose.yml" \
             -f "$ROOT/deploy/docker-compose.identity.yml" \
             --profile stub --profile gpu --profile oidc config --images 2>"$STAGE/compose.err" | sort -u)
  case " ${IMAGES[*]-} " in *" trialbox-py:"*) ;; *)
    echo "make_bundle: compose listed no trialbox-py image (docker compose config):" >&2
    cat "$STAGE/compose.err" >&2; exit 2 ;; esac
  # PERF-010 (D-968): the nightly backup's image is no compose service (the nightly runs it), so it is named here
  # (release.json marks it a job: no box container runs it between nights)
  case " ${IMAGES[*]} " in *" trialbox-backup:1.0.0 "*) ;; *) IMAGES+=("trialbox-backup:1.0.0"); JOBS+=(--job "trialbox-backup:1.0.0") ;; esac
  if [ "$THIRD" = 1 ]; then
    n3=0; for img in "${IMAGES[@]}"; do case "$img" in trialbox-*) ;; *) n3=$((n3 + 1)) ;; esac; done
    [ "$n3" -gt 0 ] || { echo "make_bundle: compose listed no third-party image (docker compose config)" >&2; exit 2; }
  fi
fi
# H-95: the engine image(s): every image whose repository images.lock pins with a gpu entry. They ride in the model
# pack (--model-pack-out); a software pack for an existing model pack (--model-pack) carries none
ENGINE_OF='import json, sys
lock = json.load(open(sys.argv[1]))
def repo(r):
    r = r.split("@", 1)[0]
    return r.rsplit(":", 1)[0] if ":" in r.rsplit("/", 1)[-1] else r
gpu = {repo(str(e.get("image") or "")) for e in (lock.get("third_party") or {}).values() if e.get("gpu")}
for img in sys.argv[2:]:
    if repo(img) in gpu:
        print(img)'
ENGINE=()
if [ -n "$MODEL_OUT$MODEL_HAVE" ]; then
  while IFS= read -r img; do ENGINE+=("$img"); done < <("$PY" -c "$ENGINE_OF" "$ROOT/deploy/images.lock" "${IMAGES[@]}")
fi
is_engine() { local e; for e in ${ENGINE[@]+"${ENGINE[@]}"}; do [ "$e" = "$1" ] && return 0; done; return 1; }
if [ -n "$MODEL_HAVE" ] && [ ${#ENGINE[@]} -gt 0 ]; then
  KEEP=(); for img in "${IMAGES[@]}"; do is_engine "$img" || KEEP+=("$img"); done
  echo "==> a software pack for the model pack $(basename "$MODEL_HAVE"): the engine image stays in it (${ENGINE[*]})"
  IMAGES=("${KEEP[@]}")
fi

# the box's architecture, not this machine's: an image here for another one is pulled again for --platform (one of
# ours is built for it: make images PLATFORM=...); tools/release.py build refuses an archive of another platform
have_platform() {
  [ "$(docker image inspect "$1" 2>/dev/null | "$PY" -c 'import json, sys
d = json.load(sys.stdin)[0]
print(str(d.get("Os")) + "/" + str(d.get("Architecture")))' 2>/dev/null)" = "$PLATFORM" ]
}
pull_platform() {
  have_platform "$1" && return 0
  echo "    pulling $1 ($PLATFORM)"
  DOCKER_DEFAULT_PLATFORM="$PLATFORM" docker pull -q "$1" >/dev/null && have_platform "$1" \
    || { echo "make_bundle: $1 is not here for $PLATFORM and cannot be pulled for it (one of ours: make images PLATFORM=$PLATFORM)" >&2; exit 2; }
}
for img in "${IMAGES[@]}"; do
  pull_platform "$img"
done
echo "==> release gates ($GATES)"
(cd "$ROOT" && PYTHONPATH="$ROOT/libs:$ROOT/services:$ROOT" "$PY" -m tools.supply_chain bundle-check --gates "$GATES" \
  "${IMAGES[@]}") || { echo "make_bundle: images are not covered by a passing gate record" >&2; exit 1; }
# card 22-4 (root review 22): no row of a must-not-ship vocabulary (licence class c in docs/licences/register.csv) in
# what this bundle stages beside the images: the rule-set zips, the reference data packs, the models folder. The tree
# inside the images is `make vocab-bundle-check` (release-bundle and demo-bundle need it). Before the first save.
VB_ARGS=()
if [ -n "$RULESETS" ]; then
  while IFS= read -r f; do VB_ARGS+=("$f"); done < <(find "$RULESETS" -type f -name '*.zip' | sort)
fi
for f in ${REFDATA[@]+"${REFDATA[@]}"}; do VB_ARGS+=("$f"); done
[ -z "$MODELS" ] || VB_ARGS+=(--models "$MODELS")
# H-90: a rehearsal bundle's placeholder model folders are read as such; in any other bundle the check refuses them
[ ${#VB_ARGS[@]} -eq 0 ] || VB_ARGS+=(${REHEARSAL[@]+"${REHEARSAL[@]}"})
if [ ${#VB_ARGS[@]} -gt 0 ]; then
  echo "==> vocabulary bundle check (card 22-4)"
  (cd "$ROOT" && PYTHONPATH="$ROOT/libs:$ROOT/services:$ROOT" "$PY" -m tools.vocab_bundle_check "${VB_ARGS[@]}") \
    || { echo "make_bundle: a must-not-ship vocabulary, or a file that cannot be checked, is staged (tools.vocab_bundle_check)" >&2; exit 1; }
else
  echo "==> vocabulary bundle check: no rule sets, reference data or models staged beside the images"
fi
# D-830: the space the saves and the bundle need, said before the first image is saved (TMPDIR moves the staging)
mkdir -p "$(dirname "$OUT")"
(cd "$ROOT" && PYTHONPATH="$ROOT" "$PY" -m tools.bundle_space --stage "$STAGE" --out "$OUT" ${MODELS:+--models "$MODELS"} \
  "${IMAGES[@]}") || exit 2

ITEMS=(); PINS=(); SAVED=(); M_ITEMS=(); M_SAVED=()
echo "==> images"
for img in "${IMAGES[@]}"; do
  pull_platform "$img"
  f="$STAGE/$(printf '%s' "$img" | tr '/:' '__').tar"
  ref="$img"
  case "$img" in *@sha256:*)
    # a digest-pinned image saved by its digest loads back with no name, so compose cannot find it offline and tries
    # to pull (found by the box rehearsal, D-176): save it under its tag. Neither image store of the container
    # engine is sure to resolve the digest reference after a load (the classic store keeps no digests; the newer
    # store gives the image another id, H-149), so the bundle also carries the pin read out of the saved archive: its
    # config digest, tag, layer diff ids and config (tools/image_pins.py proves the loaded image by them)
    ref="${img%@*}"; case "${ref##*/}" in *:*) ;; *) ref="$ref:pinned" ;; esac
    docker tag "$img" "$ref" ;;
  esac
  echo "    $img"
  docker save "$ref" -o "$f"
  if [ -n "${MODEL_OUT:-}" ] && is_engine "$img"; then  # H-95: the engine image rides in the model pack
    M_ITEMS+=("image:$f=$(basename "$f")"); M_SAVED+=(--image "$img=$f")
  else
    ITEMS+=("image:$f=$(basename "$f")"); SAVED+=(--image "$img=$f")
  fi
  [ "$ref" = "$img" ] || PINS+=("$img=$ref=$f")
done
if [ ${#PINS[@]} -gt 0 ]; then
  (cd "$ROOT" && PYTHONPATH="$ROOT" "$PY" -m tools.image_pins bundle-pins "$STAGE/image-pins.json" "${PINS[@]}") || exit 1
  ITEMS+=("other:$STAGE/image-pins.json=image-pins.json")
fi
if [ -n "$MODELS" ]; then
  echo "==> models from $MODELS"
  while IFS= read -r f; do
    rel="${f#"$MODELS"/}"; echo "    $rel"
    if [ -n "${MODEL_OUT:-}" ]; then M_ITEMS+=("model:$f=$rel"); else ITEMS+=("model:$f=$rel"); fi
  done < <(find -L "$MODELS" -type f | sort)  # through links (H-43): a model cache's snapshot files link to its blobs
fi
if [ -n "$RULESETS" ]; then
  echo "==> rulesets from $RULESETS"
  while IFS= read -r f; do
    echo "    $(basename "$f")"; ITEMS+=("ruleset:$f=$(basename "$f")")
  done < <(find "$RULESETS" -type f -name '*.zip' | sort)
fi
for f in ${REFDATA[@]+"${REFDATA[@]}"}; do
  [ -f "$f" ] || { echo "make_bundle: no such reference data pack $f" >&2; exit 2; }
  echo "==> reference data $(basename "$f")"; ITEMS+=("refdata:$f=$(basename "$f")")
done
echo "==> host tree (compose files, host tools, configuration; tools/host_tree.py, D-367)"
(cd "$ROOT" && PYTHONPATH="$ROOT" "$PY" -m tools.host_tree pack --root "$ROOT" --out "$STAGE/trialbox-host.tar") \
  | sed 's/^/    /' || { echo "make_bundle: the host tree could not be packed" >&2; exit 1; }
[ -f "$STAGE/trialbox-host.tar" ] || { echo "make_bundle: no host tree" >&2; exit 1; }
if [ "$DIRTY" != 1 ]; then  # D-631: exporting the images took minutes; the tree that was packed is still the commit
  AFTER="$(tree_changes)"
  [ -z "$AFTER" ] || { { echo "make_bundle: the checkout changed while the bundle was built; nothing is signed:"
                         show_changes "$AFTER"; } >&2; exit 2; }
fi
ITEMS+=("host:$STAGE/trialbox-host.tar=trialbox-host.tar")
echo "==> installer, runbook, settings example, notices, changelog"
for f in deploy/install.sh deploy/check_host.sh deploy/settings.example.yaml .env.example NOTICE CHANGELOG.md; do
  ITEMS+=("other:$ROOT/$f=$(basename "$f")")
done
# the whole runbook as one RUNBOOK.md: once T-669 makes docs/RUNBOOK.md an index of section files, `doclint --whole
# RUNBOOK` joins them (its output is used only when it is a Markdown document: an older doclint ignores --whole and
# prints its summary); until then docs/RUNBOOK.md is itself the whole text
if (cd "$ROOT" && PYTHONPATH="$ROOT/libs:$ROOT/services:$ROOT" "$PY" -m tools.doclint --whole RUNBOOK) \
     > "$STAGE/RUNBOOK.md" 2>/dev/null && [ "$(head -c 2 "$STAGE/RUNBOOK.md")" = "# " ]; then
  ITEMS+=("other:$STAGE/RUNBOOK.md=RUNBOOK.md")
else
  ITEMS+=("other:$ROOT/docs/RUNBOOK.md=RUNBOOK.md")
fi
PACK=()
if [ -n "$MODEL_OUT" ]; then
  # H-95: the model pack first, signed on its own; the software pack then names it by its signed identity
  echo "==> model pack $MODEL_OUT (bundle id $MODEL_ID, release_seq $MODEL_SEQ): the engine image and the weights"
  M_META=()
  if [ ${#M_SAVED[@]} -gt 0 ]; then
    (cd "$ROOT" && PYTHONPATH="$ROOT/libs:$ROOT/services:$ROOT" "$PY" -m tools.release build --id "$MODEL_ID" \
      --release-seq "$MODEL_SEQ" --gates "$GATES" --sbom-dir "$SBOM_DIR" --out-dir "$STAGE/meta-model" --platform "$PLATFORM" \
      ${REHEARSAL[@]+"${REHEARSAL[@]}"} "${M_SAVED[@]}" "${M_ITEMS[@]}") \
      || { echo "make_bundle: no release record for the model pack: nothing is built" >&2; exit 1; }
    while IFS= read -r it; do [ -n "$it" ] && M_ITEMS+=("$it"); done < "$STAGE/meta-model/items.txt"
    M_META=(--release "$STAGE/meta-model/release.json" --images-lock "$STAGE/meta-model/images.lock")
  fi
  mkdir -p "$(dirname "$MODEL_OUT")"
  PYTHONPATH="$ROOT/libs:$ROOT" "$PY" "$ROOT/tools/sign_bundle.py" build --key "$KEY" --id "$MODEL_ID" --out "$MODEL_OUT" \
    --release-seq "$MODEL_SEQ" --pack model ${M_META[@]+"${M_META[@]}"} \
    --description "TrialBox model pack $MODEL_ID: the engine image and the weights" "${M_ITEMS[@]}"
  if [ ${#M_SAVED[@]} -gt 0 ]; then
    (cd "$ROOT" && PYTHONPATH="$ROOT/libs:$ROOT/services:$ROOT" "$PY" -m tools.release check "$MODEL_OUT") \
      || { rm -f "$MODEL_OUT"; echo "make_bundle: the signed model pack does not match its release record; removed" >&2; exit 1; }
  fi
  (cd "$(dirname "$MODEL_OUT")" && sha256sum "$(basename "$MODEL_OUT")") > "$MODEL_OUT.sha256"
  PACK=(--pack software --requires-model "$MODEL_OUT")
elif [ -n "$MODEL_HAVE" ]; then
  PACK=(--pack software --requires-model "$MODEL_HAVE")
fi
echo "==> release record (tools/release.py: gates by archive digest, SBOMs, release.json, images.lock)"
(cd "$ROOT" && PYTHONPATH="$ROOT/libs:$ROOT/services:$ROOT" "$PY" -m tools.release build --id "$ID" \
  --release-seq "$SEQ" --gates "$GATES" --sbom-dir "$SBOM_DIR" --out-dir "$STAGE/meta" --platform "$PLATFORM" ${REHEARSAL[@]+"${REHEARSAL[@]}"} ${JOBS[@]+"${JOBS[@]}"} "${SAVED[@]}" "${ITEMS[@]}") \
  || { echo "make_bundle: no release record: the bundle is not built" >&2; exit 1; }
while IFS= read -r it; do [ -n "$it" ] && ITEMS+=("$it"); done < "$STAGE/meta/items.txt"
mkdir -p "$(dirname "$OUT")"
echo "==> signing $OUT (bundle id $ID, release_seq $SEQ)"
PYTHONPATH="$ROOT/libs:$ROOT" "$PY" "$ROOT/tools/sign_bundle.py" build --key "$KEY" --id "$ID" --out "$OUT" \
  --release-seq "$SEQ" --release "$STAGE/meta/release.json" --images-lock "$STAGE/meta/images.lock" ${PACK[@]+"${PACK[@]}"} \
  --description "TrialBox release $ID: images, models, rulesets, installer" "${ITEMS[@]}"
(cd "$ROOT" && PYTHONPATH="$ROOT/libs:$ROOT/services:$ROOT" "$PY" -m tools.release check "$OUT") \
  || { rm -f "$OUT"; echo "make_bundle: the signed bundle does not match its release record; removed" >&2; exit 1; }
# H-22 (D-996): the install's first command, beside the bundle and signed by the same key; RUNBOOK §1 checks its .sig
# with openssl, then runs it: it verifies the bundle, unpacks the host tree to /opt/trialbox and runs the installer
BOOT="$(dirname "$OUT")/trialbox-bootstrap.sh"
cp "$ROOT/deploy/bootstrap.sh" "$BOOT"
PYTHONPATH="$ROOT/libs:$ROOT" "$PY" "$ROOT/tools/sign_bundle.py" sign-file --key "$KEY" "$BOOT" >/dev/null \
  || { echo "make_bundle: the bootstrap could not be signed" >&2; exit 1; }
# each file named bare, written from its own folder: the sidecar checks wherever the stick is mounted (H-22 finding 4)
(cd "$(dirname "$OUT")" && sha256sum "$(basename "$OUT")" "$(basename "$BOOT")" "$(basename "$BOOT").sig") | tee "$OUT.sha256"
# HS-1: the hospital's one command. The launcher goes to the stick's root as `install`, with the vendor key's
# fingerprint pinned inside it and the vendor's public key beside it. The delivery sheet carries two codes on
# paper: the key's fingerprint, which the launcher shows, and the first 24 hex digits of the launcher's own sha256,
# which the sheet's line prints with stock tools before the launcher runs (HS1-01, the integrator's ruling).
# The same line is in deploy/launcher.sh and deploy/bootstrap.sh; a test holds the three together.
fingerprint() { openssl pkey -pubin -in "$1" -outform DER 2>/dev/null | sha256sum | cut -c1-24 | sed 's/..../& /g; s/ $//'; }
STICK_PUB="$(dirname "$OUT")/vendor_ed25519.pub"
openssl pkey -in "$KEY" -pubout -out "$STICK_PUB" 2>/dev/null \
  || { echo "make_bundle: the vendor's public key could not be written" >&2; exit 1; }
LAUNCH="$(dirname "$OUT")/install"
sed "s/@VENDOR_KEY_FINGERPRINT@/$(fingerprint "$STICK_PUB")/" "$ROOT/deploy/launcher.sh" > "$LAUNCH" && chmod 0755 "$LAUNCH"
grep -q '^PIN="[0-9a-f ]\{29\}"$' "$LAUNCH" || { echo "make_bundle: the launcher's key pin was not written" >&2; exit 1; }
echo "done: hand over, on a USB stick labelled TRIALBOX (no space): install, vendor_ed25519.pub, $(basename "$OUT"), $(basename "$OUT").sha256, $(basename "$BOOT") and $(basename "$BOOT").sig"
[ -z "$MODEL_OUT" ] || echo "      and, beside them for a first install, the model pack $(basename "$MODEL_OUT") and $(basename "$MODEL_OUT").sha256 (an update needs the software pack alone)"
if [ -n "$MODEL_OUT$MODEL_HAVE" ]; then
  echo "      sizes: $(PYTHONPATH="$ROOT" "$PY" "$ROOT/tools/packs.py" sizes "$OUT" --model-pack "${MODEL_OUT:-$MODEL_HAVE}")"
fi
echo "      the delivery sheet carries the vendor key's fingerprint: $(fingerprint "$STICK_PUB")"
echo "      and the launcher's code: $(sha256sum "$LAUNCH" | cut -c1-24 | sed 's/..../& /g; s/ $//')"
# the sheet's line stops after the launcher's code is printed: nothing from the stick runs before it is compared
echo "      the sheet's line: sudo install -m 0700 /media/<user>/TRIALBOX/install /root/trialbox-install && sudo sha256sum /root/trialbox-install | cut -c1-24 | sed 's/..../& /g' && read -r -p 'Same as the sheet? Type yes: ' a && [ \"\$a\" = yes ] && sudo bash /root/trialbox-install /media/<user>/TRIALBOX"
echo "      (RUNBOOK section 1's longer command keeps working)"
