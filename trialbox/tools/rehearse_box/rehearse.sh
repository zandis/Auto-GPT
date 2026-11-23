#!/usr/bin/env bash
# Box-install rehearsal (D-176, D-177): the gate before any site's installation qualification (IQ). `make rehearse-box`
# calls it on any Docker host (no GPU, no network after the images are built, about 15 minutes).
#
# It makes offline media the way the vendor does (signed bundle with the images, placeholder model weights and the
# reference data pack; the release tree; the vendor key; SHA256SUMS), removes the box images from the Docker host so
# only the media can bring them back, then runs the REAL deploy/install.sh --tier large inside a clean Ubuntu 24.04
# container, with the strict vLLM stand-ins (tools/vllm_standin.py) where the GPU would be. It proves:
#
#   wsl2            the WSL2 preflight passes on a WSL2-like host and fails on plain Linux (Windows itself cannot run)
#   bootstrap       RUNBOOK §1's first command as written: openssl checks the bootstrap's signature, the bootstrap
#                   verifies the bundle and unpacks its host tree into an empty folder (D-996)
#   media-negative  missing media, a forged bundle, a software pack without its model pack (H-95) and a missing vendor
#                   key each stop the installer, nothing written
#   install         install.sh exits 0: bundle verified and loaded, settings, key, pins, stack healthy, serving check
#   doctor          trialbox doctor --live passes (with the site's TLS proxy assumed: TB_CONSOLE_SECURE_COOKIE=1)
#   served          the pinned served names are exactly what the stand-ins serve
#   offline         every running container's image is one the bundle loaded (third-party ones too: postgres, hapi),
#                   no image was pulled, the CQL jars = the vendor's and they translate, the reference data pack of
#                   the media is loaded, ClinicalTrials.gov offline, no route out of the box
#   egress-override no route out, with the REHEARSAL's internal egress-net (standins.yml); the shipped egress-net and
#                   deploy/network.sh are not rehearsed (no NET_ADMIN): the site's IQ checks them
#   guard           on model-net only model-guard answers to the model servers' names: /invocations,
#                   /collective_rpc, /metrics ... 404 with or without the key, /v1 and /tokenize need the key (D-177,
#                   D-739)
#   console         the console answers /healthz and its sign-in page; it resolves no outside name and reaches nothing
#                   outside (console-net, D-176)
#   screen          SCREEN GZQO on synthetic hospital A ends done, through the gateway to both pinned builds
#   restart         every box process killed (a power loss), then the host container restarted: the box comes back
#                   healthy with its data, the doctor passes, the console answers, a second SCREEN runs
#   wrong-name      a served name that is not the pinned one: the doctor (the installer's check) FAILs naming both,
#                   the gateway refuses the call
#   missing-key     the gateway without the key: the doctor FAILs "refused the key (HTTP 401)", calls are refused
#   no-registry-pull  the Docker daemon's image events from the clearing of the images to the end: loads, no pull
#   swapped-stream  H-95 on this real engine (tools/rehearse_box/h95_probe.py): an image archive swapped on the stick
#                   after the pin read is refused, and 30 s later no image, no tag, the pinned name unmoved
#
# Writes $TB_REHEARSE_DIR/report.md and report.json; exit 0 only when every step passes.
#
# The rehearsal box is VALIDATION (D-887, the integrator's (i)), run as a validation run on a plain VM: no TPM and the
# passphrase KEK (TB_KEK_BACKEND=passphrase, a throwaway synthetic passphrase), TB_HOST_PROFILE=poc.
# TB_REHEARSE_VARIANT=validation adds a root-owned deploy/site and a second install of the same bundle.
# Knobs: TB_REHEARSE_DIR (default a fresh mktemp dir; the same path is mounted in the box container, docker-outside-of-
# docker), TB_REHEARSE_SKIP_BUILD=1 (use the trialbox-py and trialbox-jvm images already built), TB_REHEARSE_KEEP=1
# (leave the box running and the work dir for inspection), TB_EXTRA_CA (a PEM for apt and pip behind a TLS proxy).
# TB_REHEARSE_MIN_FREE_GB (default 30: free space wanted for the work dir and Docker's root), TRIVY_CACHE (default
# .cache/trivy: the gates' database, `make trivy-db` at most 7 days before; D-883).
# H-54: TB_REHEARSE_HOST_CACHE (a folder: the host image is loaded from host-<sha256 of host.Dockerfile>.tar there when
# it exists, and saved there after a build; CI keeps it in the Actions cache), TB_REHEARSE_HOST_IMAGE_CAP_S (the cap of
# one host-image build attempt, HOST_IMAGE_CAP_S below).
# Needs: Docker with compose, no other TrialBox stack running on it, port 8090 free, python3 with the repo's venv.
# Either Docker image store: the containerd store keeps digests, the classic overlay2 store does not (tools/
# image_pins.py); DOCKER_HOST=unix:///path/docker.sock rehearses on another daemon (its socket goes into the box).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || exit 2
PY="${PY:-$ROOT/.venv/bin/python}"
VARIANT="${TB_REHEARSE_VARIANT:-test}"
case "$VARIANT" in test|validation) ;; *) echo "rehearse: TB_REHEARSE_VARIANT must be test or validation" >&2; exit 2 ;; esac
# The work dir holds box.sh, which runs with the Docker socket: a fresh private dir by default; a given one must be
# absolute, at least three levels deep, not a system folder, and new or the caller's own earlier rehearsal dir.
if [ -z "${TB_REHEARSE_DIR:-}" ]; then
  W="$(mktemp -d "${TMPDIR:-/tmp}/tb-rehearse-box.XXXXXX")" || exit 2
  touch "$W/.tb-rehearse-box"
else
  W="${TB_REHEARSE_DIR%/}"
  case "$W" in /*) ;; *) echo "rehearse: TB_REHEARSE_DIR must be absolute" >&2; exit 2 ;; esac
  case "$W" in *..*|*//*) echo "rehearse: TB_REHEARSE_DIR must be a plain path" >&2; exit 2 ;; esac
  depth="$(printf '%s' "$W" | tr -cd / | wc -c)"
  case "$W" in /bin*|/boot*|/dev*|/etc*|/lib*|/proc*|/root|/run*|/sbin*|/sys*|/usr*|/var/lib*|/home/*/.*) depth=0 ;; esac
  [ "$depth" -ge 3 ] || { echo "rehearse: TB_REHEARSE_DIR $W is too shallow or a system folder (e.g. /tmp/<you>/tb-rehearse-box)" >&2; exit 2; }
  if [ -e "$W" ]; then
    [ -d "$W" ] && [ ! -L "$W" ] && [ "$(stat -c %u "$W")" = "$(id -u)" ] && [ -e "$W/.tb-rehearse-box" ] \
      || { echo "rehearse: $W exists and is not this user's earlier rehearsal dir (no .tb-rehearse-box): refusing to delete it" >&2; exit 2; }
  fi
fi
ID="rehearsal-$(date -u +%Y%m%d)"
MEDIA="$W/media/TRIALBOX-$ID"
BUNDLE_NAME="trialbox-$ID.tar"
MODEL_PACK_NAME="trialbox-models-$ID.pack"  # H-95: the model pack, beside the software pack on the media
BOX="$W/box"
HOST_IMG="trialbox-rehearsal-host:24.04"
HOST_CT="tb-rehearse-host"
# H-54: a cache miss builds the host image from the Ubuntu archive (an outside mirror). One attempt may take
# HOST_IMAGE_CAP_S seconds, then it is stopped and tried once more: the slowest of the 11 successful CI builds read
# on 2026-11-19 took 222 s (most 14-51 s); one leg's mirror trickled for 2758 s (46 min) and another's refused for 500 s
HOST_IMAGE_CAP_S="${TB_REHEARSE_HOST_IMAGE_CAP_S:-600}"
HOST_IMAGE_ATTEMPTS=2
HOST_IMAGE_LABEL="org.trialbox.rehearsal.host-dockerfile-sha256"
HOST_CACHE="${TB_REHEARSE_HOST_CACHE:-}"
LOGS="$W/logs"
SOCK=/var/run/docker.sock
case "${DOCKER_HOST:-}" in unix://*) SOCK="${DOCKER_HOST#unix://}" ;; "") ;; *) echo "rehearse: DOCKER_HOST must be a unix socket" >&2; exit 2 ;; esac
EVENTS_PID=""
export PYTHONPATH="$ROOT/libs:$ROOT/services:$ROOT"

# ------------------------------------------------------------------------------------------------ bookkeeping
NAMES=(); STATES=(); NOTES=(); N=0
record() { NAMES+=("$1"); STATES+=("$2"); NOTES+=("$3"); }
step() {  # step <name> <fatal 0|1> <command...>
  local name="$1" fatal="$2"; shift 2
  N=$((N + 1)); local log; log="$LOGS/$(printf %02d "$N")-$name.log"
  if [ -n "${BLOCKED:-}" ]; then record "$name" SKIP "not run: $BLOCKED failed"; return 1; fi
  echo "==> [$N] $name"
  local t0=$SECONDS
  if "$@" >"$log" 2>&1; then
    record "$name" PASS "$((SECONDS - t0)) s"; grep -h '^ok: ' "$log" | sed 's/^/    /'; return 0
  fi
  record "$name" FAIL "$((SECONDS - t0)) s; $log"
  tail -n 25 "$log" | sed 's/^/    /'
  [ "$fatal" = 1 ] && BLOCKED="$name"
  return 1
}
# Keep one synthetic KEK passphrase in this rehearsal process for the install and reinstall.
rehearsal_passphrase="$(openssl rand -hex 24)" || exit 1
in_box() {
  local -a pass_env=()
  case "$1" in
    install|reinstall) local -x TB_KEK_PASSPHRASE="$rehearsal_passphrase"; pass_env=(-e TB_KEK_PASSPHRASE) ;;
  esac
  docker exec "${pass_env[@]}" -e TB_RH_VARIANT="$VARIANT" -e TB_RH_DIR="$W" -e TB_RH_MEDIA="$MEDIA" -e TB_RH_BUNDLE="$BUNDLE_NAME" -e TB_RH_BOX="$BOX" \
  "$HOST_CT" bash "$W/run/box.sh" "$@"; }
box_containers() { docker ps -q --filter label=com.docker.compose.project=trialbox; }

# ------------------------------------------------------------------------------------------------ vendor side
preconditions() {
  docker info >/dev/null || { echo "docker is not running"; return 1; }
  docker compose version || return 1
  [ -z "$(docker ps -aq --filter label=com.docker.compose.project=trialbox)" ] \
    || { echo "a TrialBox compose project already exists on this Docker host (make down / poc-down first)"; return 1; }
  [ -x "$PY" ] || { echo "no venv at $PY (make venv)"; return 1; }
  # D-883: the gates' Trivy database and the disk, before the build rather than half an hour into it
  "$PY" -m tools.rehearse_box.preflight --work "$W" --trivy-cache "${TRIVY_CACHE:-.cache/trivy}" \
    --docker-root "$(docker info --format '{{.DockerRootDir}}')" --min-free-gb "${TB_REHEARSE_MIN_FREE_GB:-30}" \
    || return 1
  mkdir -p "$W/vendor" "$W/run" "$MEDIA/linux" "$MEDIA/measured" "$MEDIA/windows" || return 1
  cp tools/rehearse_box/box.sh "$W/run/box.sh" && cp -r tools/rehearse_box/shims "$W/run/shims"
  echo "ok: docker $(docker version --format '{{.Server.Version}}'), work dir $W"
}

images() {
  if [ "${TB_REHEARSE_SKIP_BUILD:-0}" = 1 ]; then
    docker image inspect trialbox-py:1.0.0 trialbox-backup:1.0.0 trialbox-jvm:1.0.0 trialbox-postgres:16-1 >/dev/null || return 1
    echo "ok: TB_REHEARSE_SKIP_BUILD=1: using the built trialbox-py, trialbox-backup, trialbox-jvm and trialbox-postgres"
  else
    make images PY="$PY" || return 1
    echo "ok: trialbox-py, trialbox-backup, trialbox-jvm and trialbox-postgres built from this checkout"
  fi
}

media() (  # a subshell: set -e stops the step, not the run
  set -e
  "$PY" tools/sign_bundle.py keygen --out "$W/vendor/keys" >/dev/null
  # the reference data pack: the committed samples (CT.gov, TFDA, NHI, ICD-10-CM, MHLW), no network
  "$PY" tools/refdata_fetch.py sample --out "$W/vendor/refdata" >/dev/null
  pack="$(ls "$W/vendor/refdata"/trialbox-refdata-*.tar)"
  basename "$pack" .tar > "$W/vendor/refdata-pack-id.txt"
  # placeholder weights for the large tier's pair (pinned at install like real ones; never a model)
  for d in gemma-4-26b-a4b-it-4bit qwen3.5-9b-4bit; do
    mkdir -p "$W/vendor/models/$d"
    printf '{"architectures": ["TrialBoxRehearsalPlaceholder"], "name": "%s"}\n' "$d" > "$W/vendor/models/$d/config.json"
    printf 'box-install rehearsal placeholder for %s: not a model\n' "$d" > "$W/vendor/models/$d/model.safetensors"
  done
  # the images a box runs without a GPU: the TrialBox images (the database is built here since D-204; the nightly
  # backup's since D-968) and the third-party ones of the base compose file
  local imgs=(trialbox-py:1.0.0 trialbox-backup:1.0.0 trialbox-jvm:1.0.0 trialbox-postgres:16-1) args=() i
  # compose renders nothing without an env file, and since D-315 nothing without TB_TZ: the rehearsal site's zone
  mkdir -p "$W/vendor/cfg"
  printf 'TB_TZ=%s\n' "$(sed -n "s/^tz: *['\"]\{0,1\}\([A-Za-z0-9_+\/-]*\).*/\1/p" tools/rehearse_box/site_answers.yaml | head -1)" > "$W/vendor/cfg/.env"
  grep -q '^TB_TZ=.' "$W/vendor/cfg/.env" || { echo "site_answers.yaml names no tz"; return 1; }
  # OPS-004b (D-574): the bundle carries what the box's own stack runs: the file set install.sh uses for these
  # answers (the large tier, TLS on), with the stand-ins' override, which replaces the model servers
  printf 'TB_TLS_HOSTNAME=%s\n' "$(sed -n "s/^tls_hostname: *['\"]\{0,1\}\([A-Za-z0-9._-]*\).*/\1/p" tools/rehearse_box/site_answers.yaml | head -1)" >> "$W/vendor/cfg/.env"
  grep -q '^TB_TLS_HOSTNAME=.' "$W/vendor/cfg/.env" || { echo "site_answers.yaml names no tls_hostname"; return 1; }
  while IFS= read -r i; do case "$i" in trialbox-*) ;; *) imgs+=("$i") ;; esac; done \
    < <(docker compose --project-directory "$W/vendor/cfg" -f deploy/docker-compose.yml -f deploy/docker-compose.secrets.yml \
          -f deploy/docker-compose.rtxpro6000.yml -f deploy/docker-compose.identity.yml \
          -f tools/rehearse_box/standins.yml config --images | sort -u)
  [ ${#imgs[@]} -ge 5 ] || { echo "compose listed no third-party image"; return 1; }
  : > "$W/vendor/bundle-images.txt"
  for i in "${imgs[@]}"; do
    # `set -e` does not act here (the step runs inside an `if`): a failed pull must stop the step by name
    docker image inspect "$i" >/dev/null 2>&1 || docker pull -q "$i" >/dev/null \
      || { echo "cannot pull $i (the registry refused or is not reachable): pull it once, then run again"; return 1; }
    echo "$i $(docker image inspect --format '{{.Id}}' "$i")" >> "$W/vendor/bundle-images.txt"
    # D-968: the nightly backup's image runs as a one-off job, as make_bundle's own default says (release.json)
    case "$i" in trialbox-backup:*) args+=(--job-image "$i") ;; *) args+=(--image "$i") ;; esac
  done
  # no bundle without its checks (T-110b, D-340): the release gates over exactly these images, then the bundle
  make release-gates SC_LOCAL_IMAGES=1 SC_DIR="$W/vendor/gates" SC_IMAGES="${imgs[*]}" || { echo "the release gates did not pass"; return 1; }
  # D-631: a rehearsal builds from the working tree and says so; a release for a site never passes --allow-dirty
  # D-726, D-887: a rehearsal bundle (release.json says so): a site box refuses it; a rehearsal box pins its placeholders
  tools/make_bundle.sh --allow-dirty "a rehearsal of the working tree" --rehearsal \
    --key "$W/vendor/keys/vendor_ed25519.key" --id "$ID" --release-seq 1 \
    --out "$W/vendor/dist/$BUNDLE_NAME" --gates "$W/vendor/gates/gates.json" --sbom-dir dist/sbom \
    --model-pack-out "$W/vendor/dist/$MODEL_PACK_NAME" \
    --models "$W/vendor/models" --refdata "$pack" "${args[@]}" \
    || { echo "the bundle was not built"; return 1; }
  # H-95: a release in two packs; the model pack (engine image, placeholder weights) beside the software pack
  mv "$W/vendor/dist/$MODEL_PACK_NAME" "$W/vendor/dist/$MODEL_PACK_NAME.sha256" "$MEDIA/linux/" \
    || { echo "the model pack and its .sha256 are not in the vendor's folder"; return 1; }
  # H-22 (D-996): the vendor builds in its own folder and hands the files over; that folder is gone before the site
  # installs, so a sidecar or a check that names the vendor's path fails here as it fails on a site's stick
  # HS-1: with the stick's launcher (install, the key's fingerprint pinned in it) and the vendor's public key
  mv "$W/vendor/dist/$BUNDLE_NAME" "$W/vendor/dist/$BUNDLE_NAME.sha256" "$W/vendor/dist/trialbox-bootstrap.sh" \
    "$W/vendor/dist/trialbox-bootstrap.sh.sig" "$W/vendor/dist/install" "$W/vendor/dist/vendor_ed25519.pub" \
    "$MEDIA/linux/" && rmdir "$W/vendor/dist" \
    || { echo "the bundle's files are not all in the vendor's folder (bundle, .sha256, bootstrap, .sig, install, key)"; return 1; }
  [ -s "$MEDIA/linux/$BUNDLE_NAME" ] || { echo "no bundle at $MEDIA/linux/$BUNDLE_NAME"; return 1; }
  cp "$W/vendor/keys/vendor_ed25519.pub" "$MEDIA/linux/"
  cp deploy/measured/serving_config.*.json "$MEDIA/measured/"
  cp deploy/windows/preflight.ps1 "$MEDIA/windows/"
  # the release tree the site copies to /opt/trialbox: the tracked files and the new ones of this checkout
  git ls-files -co --exclude-standard -z | tar --null -cf "$MEDIA/trialbox-release.tar" -T -
  (cd .cache/jvm/cql-translator/lib && sha256sum ./*.jar | sed 's# \./# #' | sort -k2) > "$W/vendor/cql-jars.sha256"
  printf 'TrialBox %s (box-install rehearsal media, synthetic; not for a site)\nbuilt %s from %s\n' "$ID" \
    "$(date -u +%FT%TZ)" "$(git rev-parse --short HEAD)" > "$MEDIA/README.txt"
  (cd "$MEDIA" && find . -type f ! -name SHA256SUMS | sort | xargs sha256sum > SHA256SUMS)
  echo "ok: media $MEDIA: $(du -sh "$MEDIA" | cut -f1), ${#imgs[@]} images, 2 placeholder models, refdata $(cat "$W/vendor/refdata-pack-id.txt")"
)

host_image() {
  local key tar="" args=() a rc=1 t0 out what
  key="$(sha256sum tools/rehearse_box/host.Dockerfile | cut -c1-64)" || return 1
  [ -n "$HOST_CACHE" ] && tar="$HOST_CACHE/host-$key.tar"
  # H-54: the image built from this very Dockerfile (the file name and the label both carry its hash): no fetch at all
  if [ -n "$tar" ] && [ -s "$tar" ]; then
    if docker load -i "$tar" >/dev/null \
      && [ "$(docker image inspect --format "{{index .Config.Labels \"$HOST_IMAGE_LABEL\"}}" "$HOST_IMG" 2>/dev/null)" = "$key" ]; then
      echo "ok: host image $HOST_IMG from the cache $tar (host.Dockerfile sha256 $key): nothing fetched"; return 0
    fi
    echo "the cached $tar did not load as $HOST_IMG with host.Dockerfile's hash $key: building"
  fi
  [ -n "${HTTPS_PROXY:-}" ] && args+=(--network host --build-arg "https_proxy=$HTTPS_PROXY")
  [ -n "${TB_EXTRA_CA:-}" ] && args+=(--secret "id=extra_ca,src=$TB_EXTRA_CA")
  for a in $(seq 1 "$HOST_IMAGE_ATTEMPTS"); do
    out="$LOGS/host-image-build-$a.log"; t0=$SECONDS
    BUILDKIT_PROGRESS=plain timeout --kill-after=30 "$HOST_IMAGE_CAP_S" docker build "${args[@]}" \
      --label "$HOST_IMAGE_LABEL=$key" -f tools/rehearse_box/host.Dockerfile -t "$HOST_IMG" tools/rehearse_box/shims \
      >"$out" 2>&1
    rc=$?; cat "$out"
    [ "$rc" = 0 ] && break
    # what the build was fetching when it stopped: the last apt or registry line of its log
    what="$(grep -E 'Get:[0-9]|Err:[0-9]|Failed to fetch|Unable to connect|Could not resolve|Temporary failure|Unable to locate|load metadata for|failed to resolve|failed to do request' "$out" | tail -n 1 | cut -c1-300)"
    case "$rc" in
      124|137) echo "host-image: attempt $a of $HOST_IMAGE_ATTEMPTS stopped at its cap of $HOST_IMAGE_CAP_S s (HOST_IMAGE_CAP_S) while fetching: ${what:-nothing logged}" ;;
      *) echo "host-image: attempt $a of $HOST_IMAGE_ATTEMPTS failed after $((SECONDS - t0)) s (docker build exit $rc); last fetch: ${what:-nothing logged}" ;;
    esac
    [ "$a" -lt "$HOST_IMAGE_ATTEMPTS" ] && sleep $((a * 15))
  done
  [ "$rc" = 0 ] || { echo "host-image: no host image after $HOST_IMAGE_ATTEMPTS attempts: the Ubuntu archive or the base image's registry did not serve the build (see above)"; return 1; }
  echo "ok: clean Ubuntu 24.04 host image $HOST_IMG (docker CLI + compose, python3, nftables, cron), built in $((SECONDS - t0)) s"
  # saved for the next run; never an image built with a site's CA (TB_EXTRA_CA): the cache holds only public layers
  if [ -n "$tar" ] && [ -z "${TB_EXTRA_CA:-}" ]; then
    mkdir -p "$HOST_CACHE" && rm -f "$HOST_CACHE"/host-*.tar \
      && docker save -o "$tar.part" "$HOST_IMG" && mv "$tar.part" "$tar" \
      && echo "ok: host image saved to $tar for the next run" \
      || { rm -f "$tar.part"; echo "note: the host image was not saved to $HOST_CACHE (the next run builds it again)"; }
  fi
  return 0
}

clear_images() {  # only the media may bring them back: by id, so every tag and digest of the image goes
  local ref id
  while read -r ref id; do
    docker image rm -f "$id" >/dev/null 2>&1 || docker image rm -f "$ref" >/dev/null 2>&1 || true
    docker image inspect "$ref" >/dev/null 2>&1 && { echo "could not remove $ref"; return 1; }
    docker image inspect "$id" >/dev/null 2>&1 && { echo "could not remove $ref ($id)"; return 1; }
  done < "$W/vendor/bundle-images.txt"
  # from now on every image event of the daemon is kept: the offline and no-registry-pull steps read it
  docker events --filter type=image --format '{{.Action}} {{.Actor.ID}} {{index .Actor.Attributes "name"}}' \
    > "$LOGS/image-events.log" 2>&1 &
  EVENTS_PID=$!
  echo "ok: $(wc -l < "$W/vendor/bundle-images.txt") box images removed from the Docker host ($(docker info --format '{{.Driver}}') store); only the media has them"
}

swapped_stream() {  # H-95 (the re-review of #1409, F1): the update path's streamed load on the real engine
  PYTHONPATH="$ROOT/libs:$ROOT" "$PY" -m tools.rehearse_box.h95_probe "$W/h95-probe"; local rc=$?
  rm -rf "$W/h95-probe"
  return "$rc"
}

no_registry_pull() {
  [ -n "$EVENTS_PID" ] || { echo "no image event log"; return 1; }
  sleep 1; kill "$EVENTS_PID" 2>/dev/null; wait "$EVENTS_PID" 2>/dev/null; EVENTS_PID=""
  cat "$LOGS/image-events.log"
  if grep -q '^pull ' "$LOGS/image-events.log"; then echo "an image was pulled from a registry:"; grep '^pull ' "$LOGS/image-events.log"; return 1; fi
  local loads; loads="$(grep -c '^load ' "$LOGS/image-events.log")"
  [ "$loads" -ge "$(wc -l < "$W/vendor/bundle-images.txt")" ] || { echo "only $loads image loads (the bundle has $(wc -l < "$W/vendor/bundle-images.txt"))"; return 1; }
  echo "ok: $loads image loads from the media and no pull from the clearing of the images to the end of the run"
}

host_up() {
  docker rm -f "$HOST_CT" >/dev/null 2>&1
  # --network host: the console's published 127.0.0.1 port is the host's; no NET_ADMIN, so the installer's nftables
  # step (deploy/network.sh apply) cannot touch the Docker host's firewall and reports that it was not applied
  # D-887: the box host sees the secrets volume by its host path, as a site's host does (the host check hands it to the
  # doctor); the seal also writes the KEK where the services mount it, /run/trialbox
  local droot; droot="$(docker info --format '{{.DockerRootDir}}')" || return 1
  local site=(-v "$droot/volumes:$droot/volumes" -v "/run/trialbox:/run/trialbox")
  docker run -d --name "$HOST_CT" --hostname trialbox-rehearsal --network host --restart no \
    -v "$SOCK:/var/run/docker.sock" -v "$W:$W" ${site[@]+"${site[@]}"} "$HOST_IMG" sleep infinity || return 1
  docker exec "$HOST_CT" sh -c '. /etc/os-release; echo "ok: box host $PRETTY_NAME, $(docker compose version)"'
}

power_cycle() {
  local pids
  pids="$(box_containers | xargs docker inspect --format '{{.State.Pid}}' | tr '\n' ' ')"
  echo "box containers: $(box_containers | wc -l); killing their processes: $pids"
  # SIGKILL from the host's PID namespace (works on Docker Desktop too): the box's processes die as in a power loss;
  # Docker restarts them under their restart policy (unless-stopped), as at boot
  docker run --rm --pid host --privileged "$HOST_IMG" kill -9 $pids || return 1
  docker restart "$HOST_CT" >/dev/null || return 1
  sleep 10
  docker ps -a --filter label=com.docker.compose.project=trialbox --format '{{.Names}} restarts={{.Status}}' | head -20
  echo "ok: power loss simulated: every box process killed, the box host restarted"
}

collect() {
  [ -d "$BOX/deploy" ] || return 0
  docker exec "$HOST_CT" sh -c "cd '$BOX' && docker compose --project-directory deploy ps -a && \
    docker compose --project-directory deploy logs --no-color --timestamps" >"$LOGS/compose.log" 2>&1 || true
}

restore_images() {  # a run that stopped before the install loaded them must not leave the Docker host without them
  local ref id b="$MEDIA/linux/$BUNDLE_NAME" m src
  [ -f "$W/vendor/bundle-images.txt" ] && [ -f "$b" ] || return 0
  while read -r ref id; do
    docker image inspect "$ref" >/dev/null 2>&1 && continue
    m="files/$(printf '%s' "$ref" | tr '/:' '__').tar"
    echo "restoring $ref from the media" >>"$LOGS/teardown.log"
    src="$b"  # H-95: the engine image is in the model pack
    tar -tf "$b" "$m" >/dev/null 2>&1 || src="$MEDIA/linux/$MODEL_PACK_NAME"
    tar -xOf "$src" "$m" | docker load >>"$LOGS/teardown.log" 2>&1 || echo "could not restore $ref" >&2
  done < "$W/vendor/bundle-images.txt"
}

teardown() {
  [ -z "$EVENTS_PID" ] || kill "$EVENTS_PID" 2>/dev/null
  if [ "${TB_REHEARSE_KEEP:-0}" = 1 ]; then echo "TB_REHEARSE_KEEP=1: box left running, work dir $W"; return 0; fi
  docker exec "$HOST_CT" sh -c "cd '$BOX' && docker compose --project-directory deploy down -v --remove-orphans" \
    >>"$LOGS/teardown.log" 2>&1 || true
  docker rm -f "$HOST_CT" >/dev/null 2>&1 || true
  docker image rm "$HOST_IMG" >/dev/null 2>&1 || true
  # D-887: the rehearsal's KEK and its throwaway passphrase do not outlive it
  docker run --rm -v /run/trialbox:/k ubuntu:24.04 rm -f /k/kek >/dev/null 2>&1 || true
  restore_images
  # keep the report and logs; drop the media and the box (gigabytes)
  docker run --rm --user 0:0 -v "$W:$W" "$(docker image inspect trialbox-py:1.0.0 >/dev/null 2>&1 && echo trialbox-py:1.0.0 || echo ubuntu:24.04)" \
    sh -c "rm -rf '$W/media' '$W/box' '$W/vendor/models'" >/dev/null 2>&1 || rm -rf "${W:?}/media" "${W:?}/box" "${W:?}/vendor/models"
}

# ------------------------------------------------------------------------------------------------ run
find "$W" -mindepth 1 -delete 2>/dev/null; rm -rf "$W"; (umask 077 && mkdir -p "$W") && touch "$W/.tb-rehearse-box" && mkdir -p "$LOGS" || exit 2
echo "TrialBox box-install rehearsal $ID ($VARIANT), work dir $W"
BLOCKED=""
step preconditions 1 preconditions
step images 1 images
step media 1 media
step host-image 1 host_image
step clear-images 1 clear_images
step host-up 1 host_up
step wsl2 0 in_box wsl2
step bootstrap 1 in_box bootstrap
step media-negative 0 in_box media-negative
step install 1 in_box install
[ "$VARIANT" = validation ] && step reinstall 1 in_box reinstall
step doctor 0 in_box doctor
step terminology 0 in_box terminology
step served 0 in_box served
step offline 0 in_box offline
step egress-override 0 in_box egress-override
step guard 0 in_box guard
step console 0 in_box console
step screen 0 in_box screen first
step power-cycle 1 power_cycle
step after-restart 1 in_box after-restart
step doctor-after-restart 0 in_box doctor
step console-after-restart 0 in_box console
step screen-after-restart 0 in_box screen second
step restic-restore 0 in_box restic-restore
step wrong-name 0 in_box wrong-name
step missing-key 0 in_box missing-key
step no-registry-pull 0 no_registry_pull
step swapped-stream 0 swapped_stream
collect
teardown

VERDICT=PASS
for s in "${STATES[@]}"; do [ "$s" = PASS ] || VERDICT=FAIL; done
{
  echo "# TrialBox box-install rehearsal ($VARIANT): $VERDICT"
  echo
  echo "Media $ID from $(git rev-parse --short HEAD), $(date -u +%FT%TZ), docker $(docker version --format '{{.Server.Version}}' 2>/dev/null) ($(docker info --format '{{.Driver}}' 2>/dev/null) image store)," \
    "real deploy/install.sh --tier large in Ubuntu 24.04 with the strict vLLM stand-ins (D-176, D-177)."
  echo
  echo "| # | step | result | detail |"
  echo "| --- | --- | --- | --- |"
  for i in "${!NAMES[@]}"; do echo "| $((i + 1)) | ${NAMES[$i]} | ${STATES[$i]} | ${NOTES[$i]} |"; done
  echo
  echo "Logs: $LOGS (compose.log: every box service)."
} | tee "$W/report.md"
"$PY" - "$W/report.json" "$VERDICT" "$ID" "$VARIANT" "${NAMES[@]}" -- "${STATES[@]}" <<'EOF' || true
import json, sys
out, verdict, media, variant, *rest = sys.argv[1:]
cut = rest.index("--")
json.dump({"verdict": verdict, "media": media, "variant": variant, "steps": dict(zip(rest[:cut], rest[cut + 1 :], strict=True))},
          open(out, "w"), indent=1)
EOF
[ "$VERDICT" = PASS ]
