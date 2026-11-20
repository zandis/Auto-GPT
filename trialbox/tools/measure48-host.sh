#!/bin/bash
# The 48 GB measuring run on an existing host (lane H, card H-67): steps s05 to s14 of tools/measure48-vm.sh against
# a checkout, on ONE card chosen by its index, with no VM and nothing of the cloud.
#
#   tools/measure48-host.sh preflight --gpu-index N --run-dir DIR [--weights-dir DIR] [--pull]
#   tools/measure48-host.sh run       --gpu-index N --run-dir DIR [--weights-dir DIR] [--pull] [--no-o] [--run-id ID]
#
# preflight  changes nothing: it prints what the run needs and what the host has, and exits 2 on any problem.
# run        the same preflight, then the steps; the packed records in DIR/out (the VM form's allow-list and
#            redaction, tools/measure48_vm.py pack). Exit 0 complete, 1 a step ended the run, 3 the cap, 130 SIGINT,
#            143 SIGTERM, 2 refused before anything started, 4 something the run made could not be removed.
#
# The steps are the VM script's own functions (it is sourced with TB_M48_FUNCTIONS_ONLY=1 and stops before its VM part:
# the metadata, the bucket, the driver install, the reboot, the power-off and the cost cap's timer are not even
# defined here). What differs on a host is defined below: no apt, no prune of anything it did not make, no pull unless
# --pull, the screen's tools installed in the run folder.
#
# What it never does: install a driver or anything with apt, reboot, power off or shut down, call gcloud, a bucket or
# the cloud's metadata, `docker system prune`, `docker builder prune` or `docker image prune`, pull the engine image
# without --pull, touch a Docker object it did not make, read or use another card than --gpu-index. It writes in the
# run folder only, and makes Docker objects of the box's own names (compose project trialbox: its containers, networks
# trialbox-*, volumes trialbox_*) and the ballast's container tb-ballast-<run id>; it refuses to start when any of them
# exists already, and removes them at the end (on success, on failure, on SIGINT and SIGTERM, at the cap). The box's
# images it builds are listed in records/docker-objects.json and kept (the build cache too: Docker cannot tell this
# run's cache from another user's).
#
# The stop line and the cap are the VM form's (measure48_vm.py stop-line-min: 204 min with stage O; the cap 240 min),
# counted from the start of the steps and kept by this script itself: at the stop line the running tool gets SIGINT
# (as on the VM), at the cap a watchdog ends the steps and the end runs (down, release, the objects removed, the records
# packed). Nothing is powered off.
#
# Knobs for the rehearsal only (tests/unit/test_measure48_host_h67.py; never on a host): TB_M48_STANDIN (one program for
# every repository tool), TB_M48_POLL_S, TB_M48_TIME_SCALE, TB_M48_USED0_S, TB_M48_LINE_MIN, TB_M48_CAP_MIN,
# TB_M48_FREE_BYTES (the run folder's free bytes as the guard sees them), TB_M48_DOCKER_FREE_BYTES (Docker's root's).
# Nothing prints a key: no `set -x`.
set -u
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)   # the trialbox folder this script is in
HELPER="$HERE/tools/measure48_vm.py"
TB_M48_FUNCTIONS_ONLY=1
# shellcheck source=tools/measure48-vm.sh
. "$HERE/tools/measure48-vm.sh"
unset TB_M48_FUNCTIONS_ONLY

usage() {
  sed -n '4,6p' "${BASH_SOURCE[0]}" | sed 's/^# *//' >&2
  [ -z "${1:-}" ] || echo "measure48-host: $1" >&2
  exit 2
}
CMD=${1:-}; [ $# -gt 0 ] && shift
GPU_INDEX=""; RUN_DIR=""; WEIGHTS=""; CHECKOUT=$HERE; PULL=0; TAKE_O=1; RUN_ID=""
while [ $# -gt 0 ]; do
  case "$1" in
    --gpu-index) GPU_INDEX=${2:-}; shift 2 || usage "--gpu-index needs a number" ;;
    --run-dir) RUN_DIR=${2:-}; shift 2 || usage "--run-dir needs a folder" ;;
    --weights-dir) WEIGHTS=${2:-}; shift 2 || usage "--weights-dir needs a folder" ;;
    --checkout) CHECKOUT=${2:-}; shift 2 || usage "--checkout needs a folder" ;;
    --run-id) RUN_ID=${2:-}; shift 2 || usage "--run-id needs a name" ;;
    --pull) PULL=1; shift ;;
    --no-o) TAKE_O=0; shift ;;
    *) usage "unknown argument: $1" ;;
  esac
done
case "$CMD" in preflight|run) ;; *) usage "preflight or run first" ;; esac
[[ "$GPU_INDEX" =~ ^[0-9]+$ ]] || usage "--gpu-index N is required (the card's nvidia-smi index)"
[ -n "$RUN_DIR" ] || usage "--run-dir DIR is required (the one folder the run writes in)"
case "$RUN_DIR" in /*) ;; *) RUN_DIR="$PWD/$RUN_DIR" ;; esac
CHECKOUT=$(cd "$CHECKOUT" 2> /dev/null && pwd) || usage "--checkout: no such folder"
WEIGHTS=${WEIGHTS:-$CHECKOUT/deploy/models}
case "$WEIGHTS" in /*) ;; *) WEIGHTS="$PWD/$WEIGHTS" ;; esac
RUN_ID=$(printf '%s' "${RUN_ID:-m48h-$(date -u +%Y%m%dT%H%M%SZ)}" | tr -c 'A-Za-z0-9._-' '_')

SI=${TB_M48_STANDIN:-}
POLL=${TB_M48_POLL_S:-10}
SCALE=${TB_M48_TIME_SCALE:-1}
ETC=""   # never /etc: nothing is installed with apt here (step_tools writes apt's lock timeout only when ETC is set)
OWN_ONLY=1   # the stop line's SIGINT and the release reach this run's own processes only
W=$RUN_DIR; RUN="$W/run"; CK=$CHECKOUT   # CK is the checkout for the preflight, the run's own copy after it
BALLAST_NAME="tb-ballast-$RUN_ID"
export TB_BALLAST_CONTAINER=$BALLAST_NAME   # tools/ballast.py: the holder's container carries the run id
export PYTHONDONTWRITEBYTECODE=1   # the preflight runs tools from the checkout: no __pycache__ written there
h() { python3 "$HELPER" "$@"; }
tick() { :; }
say() { echo "TB-M48 $(stamp) $*" | if [ -d "$RUN" ]; then tee -a "$RUN/host.log"; else cat; fi; }

# ------------------------------------------------------------------ the preflight: reads only, changes nothing
PRE=""; PROBLEMS=0; GPU_UUID=""; DOCKER_ROOT=""
pf() {  # pf ok|NO|note <text>
  local line="preflight: $1: $2"
  PRE="$PRE$line"$'\n'; echo "$line"
  [ "$1" != NO ] || PROBLEMS=$((PROBLEMS + 1))
}
nearest_dir() { local d=$1; while [ ! -d "$d" ]; do d=$(dirname "$d"); done; printf '%s' "$d"; }
screen_missing() {  # what the screen's steps (s09, s10) need of the host and do not install here
  local miss="" langs
  command -v pg_config > /dev/null || compgen -G '/usr/lib/postgresql/*/bin/initdb' > /dev/null || miss="$miss PostgreSQL's server binaries,"
  langs=$(tesseract --list-langs 2> /dev/null)
  for l in jpn chi_tra eng; do grep -qx "$l" <<< "$langs" || miss="$miss tesseract $l,"; done
  for t in curl xz git; do command -v "$t" > /dev/null || miss="$miss $t,"; done
  printf '%s' "${miss%,}"
}
preflight() {
  local docker_gb run_gb out ref n mib drv rt ver rented what
  pf note "card H-67's host form; nothing below changes anything on this host"
  if python3 -c 'import sys, yaml; sys.exit(sys.version_info < (3, 10))' 2> /dev/null; then pf ok "python3 3.10 or newer with PyYAML"
  else pf NO "python3 3.10 or newer with PyYAML (python3-yaml) is needed: the ballast's tools import it"; fi
  # the checkout: the run is of its HEAD (a copy of it in the run folder; uncommitted changes are not in it)
  if out=$(git -C "$CHECKOUT" rev-parse HEAD 2> /dev/null) && [ -f "$CHECKOUT/tools/ballast48.py" ]; then
    pf ok "the checkout: commit $out"
    [ -z "$(git -C "$CHECKOUT" status --porcelain --untracked-files=no 2> /dev/null)" ] \
      || pf NO "the checkout has uncommitted changes to tracked files: the run is of one commit (commit or drop them)"
  else pf NO "--checkout is not a git checkout of trialbox/ (no HEAD, or no tools/ballast48.py)"; fi
  # the card: index N only (-i); its UUID is read here and checked by every later read of the run
  if out=$(nvidia-smi -i "$GPU_INDEX" --query-gpu=uuid,name,memory.total,driver_version --format=csv,noheader,nounits 2>&1) \
     && [ -n "$out" ]; then
    GPU_UUID=$(printf '%s' "$out" | head -n 1 | cut -d, -f1 | tr -d ' ')
    drv=$(printf '%s' "$out" | head -n 1 | awk -F', *' '{print $NF}')
    pf ok "card $GPU_INDEX: $(printf '%s' "$out" | head -n 1 | cut -d, -f2,3 | sed 's/^ *//') MiB in all; driver $drv"
    rented=$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import measure48_vm as m; print(m.RENTED_DRIVER_BRANCH)' "$HERE/tools")
    [ "${drv%%.*}" = "$rented" ] \
      || pf note "driver $drv is not the rented run's branch ($rented): recorded; the run goes on (no minimum is set)"
  else pf NO "nvidia-smi has no card $GPU_INDEX: $(printf '%s' "$out" | head -n 1)"; fi
  # other processes on THAT card (a shared machine: how many and how much, never whose); other cards are not read
  if out=$(nvidia-smi -i "$GPU_INDEX" --query-compute-apps=pid,used_memory --format=csv,noheader,nounits 2> /dev/null); then
    n=$(printf '%s\n' "$out" | grep -c '[0-9]'); mib=$(printf '%s\n' "$out" | awk -F', *' '$2 ~ /^[0-9]+$/ {s += $2} END {print s + 0}')
    if [ "$n" = 0 ]; then pf ok "card $GPU_INDEX: no other process on it"
    else pf NO "card $GPU_INDEX: $n other process(es) on it, $mib MiB: the card must be free for the run"; fi
  fi
  # the ballast's own checks and numbers on that card (allocates nothing): too small, held memory, the target
  if [ -n "$GPU_UUID" ]; then
    if out=$(tool ballast plan --gpu-index "$GPU_INDEX" --gpu-uuid "$GPU_UUID" --target-mib 49140 2>&1); then
      pf ok "the ballast's plan: $(printf '%s\n' "$out" | grep -m1 '^target:' || echo 'its checks passed')"
    else pf NO "the ballast refuses this card: $(printf '%s\n' "$out" | grep -m1 'refused' || printf '%s' "$out" | tail -n 1)"; fi
  fi
  # Docker, the NVIDIA runtime registered with it (docker info's Runtimes: what nvidia-ctk runtime configure adds),
  # compose with !override (2.24.4 or newer: the servers' card pin replaces the overlay's count: 1)
  if rt=$(docker info --format '{{json .Runtimes}}' 2> /dev/null); then
    pf ok "Docker answers"
    if grep -q '"nvidia"' <<< "$rt"; then pf ok "the NVIDIA runtime is registered with Docker (docker info: Runtimes)"
    else pf NO "the NVIDIA runtime is not registered with Docker (docker info: Runtimes has no nvidia): the owner registers it (nvidia-ctk runtime configure --runtime=docker, then a Docker restart); this script never does"; fi
    DOCKER_ROOT=$(docker info --format '{{.DockerRootDir}}' 2> /dev/null)
    ver=$(docker compose version --short 2> /dev/null); ver=${ver#v}
    if [ -n "$ver" ] && [ "$(printf '%s\n2.24.4\n' "$ver" | sort -V | head -n 1)" = 2.24.4 ]; then pf ok "docker compose $ver"
    else pf NO "docker compose ${ver:-missing}: 2.24.4 or newer is needed (the servers' card pin uses !override)"; fi
    out=$(objs); n=$(printf '%s' "$out" | grep -c .)
    if [ "$n" = 0 ]; then pf ok "no TrialBox objects on this host (compose project trialbox, trialbox-* networks, trialbox_* volumes, $BALLAST_NAME)"
    else pf NO "this host has $n Docker object(s) of the box's names already ($(cut -f1 <<< "$out" | sort | uniq -c | awk '{printf "%s%s %s", (NR > 1 ? ", " : ""), $1, $2}')): the run makes and removes objects of those names and shares none"; fi
    ref=$(tool pinned_ref 2> /dev/null)
    if [ -z "$ref" ]; then pf NO "no pinned engine image (tools/engine_probe.py pinned_ref)"
    elif docker image inspect --format '{{.Id}}' "$ref" > /dev/null 2>&1; then pf ok "the engine image is here by digest: $ref"
    elif [ "$PULL" = 1 ]; then pf note "the engine image is not here: s06 pulls it (--pull; 9.2 GB compressed, 23.4 GB unpacked)"
    else pf NO "the engine image is not here by digest ($ref): load it, or give --pull"; fi
  else
    pf NO "Docker does not answer (is it running, and may this user use it?)"
  fi
  # the weights: the pinned list (models/registry.yaml and its measured record), checked, never fetched
  if out=$(tool fetch_weights --profile rtxpro6000 --models-dir "$WEIGHTS" --verify-only 2>&1); then
    pf ok "the weights in --weights-dir are the pinned builds (tools/fetch_weights.py --verify-only)"
  else pf NO "the weights in --weights-dir are not the pinned builds: $(printf '%s\n' "$out" | grep -m1 'NOT OK' || printf '%s' "$out" | tail -n 1)"; fi
  # the disk, from the run sheet's figures (measure48_vm.py NEED_GB, host_need)
  local pull=(); [ "$PULL" = 0 ] || pull=(--pull)
  read -r docker_gb run_gb <<< "$(h host-need "${pull[@]}")"
  if [ -n "$DOCKER_ROOT" ]; then
    if out=$(h disk --path "$(nearest_dir "$DOCKER_ROOT")" --need-gb "$docker_gb" ${TB_M48_DOCKER_FREE_BYTES:+--free-bytes "$TB_M48_DOCKER_FREE_BYTES"}); then
      pf ok "Docker's data root: ${out%% on *}, $docker_gb GB needed"
    else
      what="the stub's images"; [ "$PULL" = 0 ] || what="$what and the engine image"
      pf NO "Docker's data root: ${out%% on *}, $docker_gb GB needed ($what)"
    fi
  fi
  if out=$(h disk --path "$(nearest_dir "$RUN_DIR")" --need-gb "$run_gb" ${TB_M48_FREE_BYTES:+--free-bytes "$TB_M48_FREE_BYTES"}); then
    pf ok "the run folder: ${out%% on *}, $run_gb GB needed"
  else pf NO "the run folder: ${out%% on *}, $run_gb GB needed (the screen's tools, the screen, the records)"; fi
  if [ -e "$RUN_DIR" ] && [ -n "$(ls -A "$RUN_DIR" 2> /dev/null)" ]; then pf NO "--run-dir is not empty: one run, one new folder"
  elif ! [ -w "$(nearest_dir "$RUN_DIR")" ]; then pf NO "--run-dir cannot be made here (not writable)"
  else pf ok "--run-dir is new or empty"; fi
  out=$(screen_missing)
  [ -z "$out" ] || pf note "the screen (s09, s10) needs, and this host lacks:$out (installed by nobody here: the screen's steps will fail and the rest goes on)"
  if [ "$PROBLEMS" = 0 ]; then pf ok "passed: nothing was changed"; return 0; fi
  pf NO "$PROBLEMS problem(s): nothing was changed"; return 2
}

# ------------------------------------------------------------------ the run's Docker objects (the box's names only)
objs() {  # kind<TAB>name, one a line: what exists now of the names this run makes
  docker ps -a --filter "label=com.docker.compose.project=trialbox" --format $'container\t{{.Names}}' 2> /dev/null
  docker ps -a --filter "name=^${BALLAST_NAME}\$" --format $'container\t{{.Names}}' 2> /dev/null
  docker network ls --filter "name=^trialbox-" --format $'network\t{{.Name}}' 2> /dev/null
  docker volume ls --filter "name=^trialbox_" --format $'volume\t{{.Name}}' 2> /dev/null
}
images() { docker image ls --format '{{.Repository}}:{{.Tag}}' 2> /dev/null | sort -u; }
remove_objects() {  # every object of the run's names, removed; records/docker-objects.json says what and how it went
  local kind name left=0 list="$RUN/kv/objects"
  objs | sort -u > "$list"
  : > "$list.done"
  while IFS=$'\t' read -r kind name; do
    [ -n "$name" ] || continue
    case "$kind" in
      container) timeout -k 10 120 docker rm -f "$name" > /dev/null 2>&1 ;;
      network) timeout -k 10 120 docker network rm "$name" > /dev/null 2>&1 ;;
      volume) timeout -k 10 120 docker volume rm "$name" > /dev/null 2>&1 ;;
    esac
    printf '%s\t%s\t%s\n' "$kind" "$name" "$?" >> "$list.done"
  done < <(sort -t$'\t' -k1,1 "$list")   # containers before the networks and volumes they use
  objs | sort -u > "$list.after"
  [ ! -s "$list.after" ] || left=1
  images | comm -13 "$RUN/kv/images-before" - > "$RUN/kv/images-made" 2> /dev/null
  python3 - "$RUN" "$RUN_ID" "$BALLAST_NAME" <<'PY'
import json, sys
from pathlib import Path
run, rid, ballast = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
def rows(name):
    p = run / "kv" / name
    return [x.split("\t") for x in p.read_text().splitlines() if x.strip()] if p.is_file() else []
after = {(r[0], r[1]) for r in rows("objects.after")}
seen = sorted({(r[0], r[1]) for r in rows("objects-seen") + rows("objects.done") if len(r) >= 2})
objs = [{"kind": k, "name": n, "removed": (k, n) not in after} for k, n in seen]
doc = {"schema": "tb-measure48-host-objects/1", "run_id": rid, "ballast_container": ballast,
       "objects": objs, "left": sorted(f"{k} {n}" for k, n in after),
       "images_made_and_kept": [r[0] for r in rows("images-made")],
       "build_cache": "kept: Docker's build cache cannot be told apart by run (a prune would take other users' too)",
       "never": "docker system prune, builder prune, image prune; an object not of the run's names"}
(run / "records" / "docker-objects.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
PY
  return "$left"
}

# ------------------------------------------------------------------ what differs from the VM's steps
stub_free() {  # s05's end: the stub's volumes only (the run's: the preflight found none); nothing pruned
  objs >> "$RUN/kv/objects-seen"   # listed in records/docker-objects.json, though gone before the end
  docker volume ls -q --filter "name=^trialbox_" 2> /dev/null | xargs -r docker volume rm >> "$STEP_LOG" 2>&1
  return 0
}
engine_room() { [ "$PULL" = 1 ] || return 0; room engine; }
engine_get() {
  docker image inspect --format '{{.Id}}' "$1" > /dev/null 2>&1 && return 0
  [ "$PULL" = 1 ] || { NOTE="the engine image is not on this host by digest ($1) and --pull was not given"; return 1; }
  watched docker pull "$1" || { NOTE="the engine image did not pull"; return 1; }
}
# the screen's tools: nothing with apt; uv, the venv, node, Playwright and Chromium in the run folder (no --with-deps)
screen_setup_apt() { local miss; miss=$(screen_missing); [ -z "$miss" ] || { echo "this host lacks:$miss"; return 1; }; }
screen_setup_py() {
  command -v uv > /dev/null || [ -x "$W/uv/bin/uv" ] || { python3 -m venv "$W/uv" && "$W/uv/bin/pip" install -q uv; } || return 1
  local uv; uv=$(command -v uv || echo "$W/uv/bin/uv")
  (cd "$CK" && "$uv" venv --python 3.12 .venv && "$uv" pip install --python .venv/bin/python -e ".[dev]")
}
screen_setup_node() {  # the VM's pinned LTS and Playwright 1.63.0, in the run folder; Chromium launched once
  local v=v22.23.4
  [ -x "$W/node-$v-linux-x64/bin/npm" ] || { curl -fsSL "https://nodejs.org/dist/$v/node-$v-linux-x64.tar.xz" | tar -xJ -C "$W"; } || return 1
  mkdir -p "$W/bin" "$NODE_TOOLS" && ln -sf "$W/node-$v-linux-x64/bin/node" "$W/node-$v-linux-x64/bin/npm" "$W/node-$v-linux-x64/bin/npx" "$W/bin/"
  (cd "$NODE_TOOLS" && npm i -s playwright@1.63.0 && npx playwright install chromium \
    && node -e "require('playwright').chromium.launch().then(b => b.close())")
}
screen_setup_fonts() { (cd "$CK" && .venv/bin/python tools/fetch_fonts.py); }
screen_setup_clean() { if command -v uv > /dev/null; then uv cache clean; else "$W/uv/bin/uv" cache clean; fi; }
end_run() {  # inside the steps: down, release, why it ended; the objects and the records are the end's (below)
  trap - EXIT
  local why=$1
  [ -n "$(kv kept)" ] && [ ! -f "$RUN/state/s12-down" ] && run_step s12-down step_down
  [ -f "$RUN/kv/ballast-on" ] && [ ! -f "$RUN/state/s14-release" ] && run_step s14-release step_release
  printf '%s' "$why" > "$RUN/ended"
  exit 0
}
pack() {  # the records, as the VM packs them (its allow-list and redaction), into the run folder: never uploaded
  objs >> "$RUN/kv/objects-seen"   # every object of the run's names seen at a step's end or a minute's look
  h records --run "$RUN" --used-s "$(used)" > /dev/null 2>&1
  h pack --run "$RUN" --out "$W/out" --mask-file "$CK/deploy/.env" --mask-dir "$CK/deploy/secrets" > /dev/null 2>> "$RUN/host.log" || true
}

# ------------------------------------------------------------------ preflight only
if [ "$CMD" = preflight ]; then preflight; exit $?; fi

# ------------------------------------------------------------------ run
preflight || exit 2
mkdir -p "$RUN/state" "$RUN/logs" "$RUN/records" "$RUN/raw" "$RUN/kv" "$W/src/trialbox" "$W/tmp" "$W/cache" || exit 2
chmod 700 "$RUN/raw" "$RUN/kv"
printf '%s' "$PRE" > "$RUN/preflight.txt"
kv gpu-uuid "$GPU_UUID"   # kv/ is never packed: the UUID stays on the host
images > "$RUN/kv/images-before"
git -C "$CHECKOUT" archive --format=tar HEAD . | tar -x -C "$W/src/trialbox" || { say "the checkout could not be copied"; exit 2; }
python3 -c 'import json, sys; print(json.dumps({"head": sys.argv[1], "form": "an existing host (H-67)", "run_id": sys.argv[2]}))' \
  "$(git -C "$CHECKOUT" rev-parse HEAD)" "$RUN_ID" > "$RUN/records/head.json"
CK="$W/src/trialbox"
GPU=(--gpu-index "$GPU_INDEX" --gpu-uuid "$GPU_UUID")
DISK_PATH=$W; DOCKER_DISK_PATH=$(nearest_dir "${DOCKER_ROOT:-/}")
NODE_TOOLS="$W/node-tools"
export TB_MODELS_DIR=$WEIGHTS TMPDIR="$W/tmp" TB_SCRATCH="$W/tmp" XDG_CACHE_HOME="$W/cache" UV_CACHE_DIR="$W/cache/uv" \
  UV_PYTHON_INSTALL_DIR="$W/uv-python" PIP_CACHE_DIR="$W/cache/pip" npm_config_cache="$W/cache/npm" \
  PLAYWRIGHT_BROWSERS_PATH="$W/ms-playwright" PATH="$W/bin:$PATH"
unset HF_TOKEN   # never a token
NO_O=(); [ "$TAKE_O" = 1 ] || NO_O=(--no-o)
LINE_MIN=${TB_M48_LINE_MIN:-$(h stop-line-min "${NO_O[@]}")}
CAP_MIN=${TB_M48_CAP_MIN:-240}   # the VM form's cap (measure48_vm.py CAP_HOURS; its tb-cap-minutes)
LINE_S=$((LINE_MIN * 60)); CAP_S=$((CAP_MIN * 60))
T0=$(date +%s); USED0=${TB_M48_USED0_S:-0}
used() { echo $(( USED0 + ($(date +%s) - T0) * SCALE )); }
say "run $RUN_ID on card $GPU_INDEX: stop line $LINE_MIN min, cap $CAP_MIN min, optional stage O: $([ "$TAKE_O" = 1 ] && echo taken if time allows || echo not taken)"

# the cap's watchdog: the script's own (nothing is powered off): at the cap it ends the steps; the end below runs
( trap - TERM INT
  left=$(( (CAP_S - $(used)) / SCALE )); [ "$left" -le 0 ] || sleep "$left"
  : > "$RUN/kv/cap"; kill -TERM $$ 2> /dev/null ) > /dev/null 2>&1 &
WATCHDOG=$!

# the steps in a child shell, so that a signal to this script is taken at once (wait returns), not after a step
( trap 'trap - EXIT; exit 143' TERM
  trap 'end_run "the steps ended unexpectedly"' EXIT
  steps_s05_on
  end_run "complete: every stage ran or was decided (decisions.json)" ) &
STEPS=$!
STOPPED=""
stop_steps() {  # TERM to the steps and everything they started; KILL to what is left after 60 s
  local all i=0
  all="$STEPS $(descendants "$STEPS")"
  # shellcheck disable=SC2086  # a list of pids
  kill -TERM $all 2> /dev/null
  while kill -0 "$STEPS" 2> /dev/null && [ "$i" -lt 60 ]; do sleep 1; i=$((i + 1)); done
  all="$STEPS $(descendants "$STEPS")"
  # shellcheck disable=SC2086
  kill -KILL $all 2> /dev/null
}
on_signal() { [ -n "$STOPPED" ] || { STOPPED=$1; say "$1: ending the steps (nothing is powered off)"; stop_steps; }; }
trap 'on_signal SIGTERM' TERM
trap 'on_signal SIGINT' INT
trap 'on_signal SIGHUP' HUP
while kill -0 "$STEPS" 2> /dev/null; do wait "$STEPS"; done
wait "$STEPS" 2> /dev/null
trap '' TERM INT HUP   # the end is not cut short
# shellcheck disable=SC2046  # a list of pids
kill "$WATCHDOG" $(descendants "$WATCHDOG") 2> /dev/null
[ ! -f "$RUN/kv/cap" ] || STOPPED="the cap of $CAP_MIN minutes"

# ------------------------------------------------------------------ the end, on every way out
if [ -n "$STOPPED" ]; then
  STEP_LOG="$RUN/logs/end.log"
  [ -n "$(kv kept)" ] && [ ! -f "$RUN/state/s12-down" ] && run_step s12-down step_down
  [ -f "$RUN/kv/ballast-on" ] && [ ! -f "$RUN/state/s14-release" ] && run_step s14-release step_release
  printf '%s' "stopped: $STOPPED" > "$RUN/ended"
fi
WHY=$(cat "$RUN/ended" 2> /dev/null || echo "the steps ended without a reason")
remove_objects; LEFT=$?
[ "$LEFT" = 0 ] || say "LEFT BEHIND: $(tr '\t\n' ' ;' < "$RUN/kv/objects.after") (records/docker-objects.json)"
h records --run "$RUN" --used-s "$(used)" --ended "$WHY" > /dev/null 2>&1
pack
say "the run ended: $WHY; the records are in the run folder's out/"
case "$STOPPED" in
  "") case "$WHY" in complete*) RC=0 ;; *) RC=1 ;; esac ;;
  SIGINT) RC=130 ;;
  SIGTERM|SIGHUP) RC=143 ;;
  *) RC=3 ;;
esac
[ "$LEFT" = 0 ] || RC=4
exit "$RC"
