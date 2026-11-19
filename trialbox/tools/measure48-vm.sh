#!/bin/bash
# The 48 GB measuring run ON its GPU VM, unattended (lane H, card H-53: H-47's sheet, steps 2 to 10, with no SSH).
# The start-up script of a VM that deploy/gcp/measure48-run.sh creates for this run and deletes after it; nobody runs
# this by hand. GCE runs it at every boot, so the driver's reboot (step 2) and a pre-emption resume here: a step that
# finished is never run again (state/<step>), one cut by a restart runs again.
#
# What it does, in H-47's order (docs/plan/measurements/48gb-measuring-run-2026-11-19.md, sections 3 and "Unattended,
# through the driver (H-53)"), each step timed in steps.json and its log in logs/<step>.log:
#   s01-host     the driver (D-966: nvidia-driver-580-server-open, the open modules Blackwell needs; one reboot), then Docker and the container toolkit with the
#                commands of deploy/gcp/gpu-sim-startup.sh (a test holds them equal)
#   s02-card     o0-card.csv (the card, CPUs, memory: O-0), the card inside a container
#   s03-source   the commit's archive from the bucket (tb-src), its sha256 (tb-src-sha256) and its HEAD (tb-commit)
#   s04-weights  tools/fetch_weights.py --profile rtxpro6000 from the public hub, NO token (none is ever asked for: a
#                gated or refused file fails the step with the tool's own words)
#   s05-stub     deploy/poc.sh once with TB_POC_SKIP_INGEST=1 (it builds the box's images and, since #1130, the
#                database image itself), status, down; its output (the administrator's password) goes to raw/, never
#                up; then the build cache and the stub's volumes are freed
#   s06-engine   the pinned engine image (tools/engine_probe.py pinned_ref)
#   s07-ballast  tools.ballast hold --target-mib 49140 until "ready" (a "refused" ends the run), ballast48 plan
#   s08-ladder   ballast48 measure --keep: pair-32k, else pair-16k, else judge-alone; the first that starts is kept
#   s09-tools    the screen's tools as deploy/gcp/complete-run-vm.sh sets them up (apt, uv, the venv, node, Chromium,
#                fonts, the hospital's data); uv's and apt's caches freed after
#   s10-screen   1,000 patients, ja, 16 in flight, against the kept pair (ballast48 during); a pair only
#   s11-o        OPTIONAL (tb-o=1): verifier-flag, the 54-case canary, canary-diff; pair-32k kept only, and only when
#                its high (0.25 h) ends before the stop line; a refused flag (exit 1) is the result, recorded
#   s12-down     the kept servers stopped (ballast48 down)
#   s13-host53   pair-32k-host53 (no --keep) when pair-32k was kept and its high (0.80 h) ends before the stop line:
#                the first stage dropped (it comes last)
#   s14-release  the ballast released (SIGTERM, then tools.ballast release when it did not say "released")
# Every decision a person would have made is made from the clock and the exit codes and written to decisions.json.
# Each stage starts only when its high estimate ends before the stop line (tb-stop-line-minutes, the VM's seconds up
# over every boot); at the line the running command gets SIGINT (lane J's measure writes what it has, then stops its
# servers), and the end runs: down, release, the records up, power off. The cost cap (tb-cap-minutes, 240) powers off
# whatever runs; the cloud's --max-run-duration 4h is the hard one.
#
# Records go up AFTER EVERY STEP (and every minute while a long step runs) to tb-bucket m48runs/<run id>/: only the
# files tools/measure48_vm.py ALLOW names, none DENY names (raw/, deploy/.env, deploy/secrets/, down.json,
# verifier-flag.yml, the stub's output), each text redacted line by line and with the model servers' key masked.
# Nothing prints a key: no `set -x`. Knobs for the rehearsal only (tests/unit/test_measure48_vm_h53.py; never on the
# VM): TB_M48_ROOT, TB_M48_SBIN, TB_M48_SERIAL, TB_M48_MD_DIR (metadata as files), TB_M48_POLL_S, TB_M48_TIME_SCALE
# (a second counts as that many), TB_M48_USED0_S (seconds already used), TB_M48_STANDIN (one program for every
# repository tool: ballast48, ballast, fetch_weights, poc, complete_run, fetch_run_data, pinned_ref, canary, setup),
# TB_M48_REBOOT, TB_M48_POWEROFF, TB_M48_NO_TIMER, TB_M48_FREE_BYTES (the disk the guard sees), TB_M48_ETC (/etc).
W=${TB_M48_ROOT:-/var/lib/tb-m48}
SBIN=${TB_M48_SBIN:-/usr/local/sbin}
SERIAL=${TB_M48_SERIAL:-/dev/ttyS0}
POLL=${TB_M48_POLL_S:-10}   # seconds between looks; every wait below is counted in looks (6 a minute on the VM)
SCALE=${TB_M48_TIME_SCALE:-1}
SI=${TB_M48_STANDIN:-}
ETC=${TB_M48_ETC:-/etc}
mkdir -p "$W" "$SBIN"
exec > >(tee -a "$W/console.log" "$SERIAL" 2>/dev/null) 2>&1
set -u
export PATH="$PATH:/snap/bin"
export DEBIAN_FRONTEND=noninteractive
unset HF_TOKEN   # never a token: a gated file fails its step (the tool says so), nothing waits for input

md() {
  if [ -n "${TB_M48_MD_DIR:-}" ]; then [ -f "$TB_M48_MD_DIR/$1" ] && cat "$TB_M48_MD_DIR/$1"; return; fi
  curl -sf -H Metadata-Flavor:Google "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"
}
RUN_ID=$(md tb-run-id | tr -c 'A-Za-z0-9._-' '_'); RUN_ID=${RUN_ID:-m48}
BUCKET=$(md tb-bucket || true)
LINE_MIN=$(md tb-stop-line-minutes || echo 204)
CAP_MIN=$(md tb-cap-minutes || echo 240)
TAKE_O=$(md tb-o || echo 1)
COMMIT=$(md tb-commit || true)
SRC=$(md tb-src || true); SRC_SHA=$(md tb-src-sha256 || true)
RUN="$W/run"; CK="$W/src/trialbox"; HELPER="$SBIN/tb-m48.py"
mkdir -p "$RUN/state" "$RUN/logs" "$RUN/records" "$RUN/raw" "$RUN/kv"
chmod 700 "$RUN/raw"
md tb-m48-helper > "$HELPER.tmp" 2>/dev/null && [ -s "$HELPER.tmp" ] && mv -f "$HELPER.tmp" "$HELPER"
rm -f "$HELPER.tmp"
h() { python3 "$HELPER" "$@"; }

# ------------------------------------------------------------------ the clock: seconds up, over every boot
BOOT_T0=$(date +%s)
USED0=$(cat "$RUN/used-s" 2>/dev/null || echo "${TB_M48_USED0_S:-0}")
used() { echo $(( USED0 + ($(date +%s) - BOOT_T0) * SCALE )); }
LINE_S=$((LINE_MIN * 60)); CAP_S=$((CAP_MIN * 60))
tick() { used > "$RUN/used-s.tmp.$BASHPID" && mv -f "$RUN/used-s.tmp.$BASHPID" "$RUN/used-s"; }
stamp() { date -u +%FT%TZ; }
say() { echo "TB-M48 $(stamp) $*" | tee -a "$RUN/vm.log"; }
echo "$(stamp) boot (used $(used) s of the run)" >> "$RUN/clock.txt"
tick
# the clock is saved every minute whatever runs (a hard stop loses at most a minute of it); it ends with this script
TICK_S=$(awk -v p="$POLL" 'BEGIN { print p * 6 }')
( while sleep "$TICK_S" && kill -0 $$ 2>/dev/null; do tick; done ) > /dev/null 2>&1 &
TICKER=$!

# ------------------------------------------------------------------ the records up, as it goes
pack() {
  tick
  h records --run "$RUN" --used-s "$(used)" > /dev/null 2>&1
  h pack --run "$RUN" --out "$W/up" --mask-file "$CK/deploy/.env" --mask-dir "$CK/deploy/secrets" > "$W/up.list" 2>> "$RUN/vm.log" \
    || return 0
  [ -n "$BUCKET" ] || return 0
  # bounded: a hung upload must not keep a finished VM billing; a timed-out one is said, the power-off still comes
  timeout -k 10 300 gcloud storage rsync --recursive "$W/up" "$BUCKET/m48runs/$RUN_ID" > /dev/null 2>&1 \
    || say "TB-UPLOAD-FAILED (or timed out after 300 s): the records to $BUCKET/m48runs/$RUN_ID"
}
poweroff_vm() { if [ -n "${TB_M48_POWEROFF:-}" ]; then "$TB_M48_POWEROFF"; else systemctl poweroff; fi; }
off() { say "power off: $1"; pack; kill "$TICKER" 2>/dev/null; poweroff_vm; exit 0; }
# the cost cap: whatever runs, at CAP_S of the run the records go up and the VM powers itself off
cat > "$SBIN/tb-m48-off" <<EOS
#!/bin/sh
echo "TB-M48 cap of $CAP_MIN minutes reached: powering off" >> "$RUN/vm.log"
echo "$CAP_S" > "$RUN/used-s"
timeout 120 "$SBIN/tb-m48-pack" || true
${TB_M48_POWEROFF:-systemctl poweroff}
EOS
cat > "$SBIN/tb-m48-pack" <<EOS
#!/bin/bash
python3 "$HELPER" records --run "$RUN" --used-s "\$(cat "$RUN/used-s")" --ended "the cost cap" >/dev/null 2>&1
python3 "$HELPER" pack --run "$RUN" --out "$W/up" --mask-file "$CK/deploy/.env" --mask-dir "$CK/deploy/secrets" >/dev/null 2>&1
[ -z "$BUCKET" ] || timeout -k 10 100 gcloud storage rsync --recursive "$W/up" "$BUCKET/m48runs/$RUN_ID" >/dev/null 2>&1
EOS
chmod 0755 "$SBIN/tb-m48-off" "$SBIN/tb-m48-pack"
[ "$(used)" -lt "$CAP_S" ] || off "the cap of $CAP_MIN minutes is used"
if [ -z "${TB_M48_NO_TIMER:-}" ]; then
  systemd-run --unit tb-m48-cap --on-active="$(( (CAP_S - $(used)) / SCALE ))s" --description "TrialBox 48 GB run: cost cap" \
    "$SBIN/tb-m48-off" > /dev/null 2>&1 || say "no systemd-run: the cloud's --max-run-duration is the cap"
fi
[ -s "$HELPER" ] || { say "no tb-m48-helper in the metadata"; poweroff_vm; exit 1; }

# A simple command a non-interactive bash starts with & has SIGINT ignored, and Python keeps an ignored SIGINT: the stop
# line's SIGINT would never become lane J's KeyboardInterrupt. Every tool starts with SIGINT's default restored.
if env --default-signal=INT true 2> /dev/null; then sigint() { env --default-signal=INT "$@"; }
else sigint() { python3 -c 'import os, signal, sys; signal.signal(signal.SIGINT, signal.SIG_DFL); os.execvp(sys.argv[1], sys.argv[1:])' "$@"; }
fi
# ------------------------------------------------------------------ steps, decisions, the stop line
kv() { if [ $# -eq 2 ]; then printf '%s' "$2" > "$RUN/kv/$1"; else cat "$RUN/kv/$1" 2>/dev/null; fi; }
decide() {  # decide <what> <choice> <why>: one line of decisions.json (a later boot does not repeat one)
  grep -qF "$(printf '\t%s\t%s\t' "$1" "$2")" "$RUN/decisions.tsv" 2>/dev/null && return 0
  printf '%s\t%s\t%s\t%s\t%s\n' "$(stamp)" "$(used)" "$1" "$2" "$3" >> "$RUN/decisions.tsv"; say "DECISION $1: $2 ($3)"
}
STEP=""; STEP_LOG=/dev/null; NOTE=""; STOPLINE=0
disk_note() {
  printf '{"step": "%s", "t": "%s", "free_bytes": %s, "used_bytes": %s}\n' "$1" "$(stamp)" \
    "$(df -B1 --output=avail / | tail -n 1 | tr -d ' ')" "$(df -B1 --output=used / | tail -n 1 | tr -d ' ')" >> "$RUN/disk.jsonl"
  docker system df 2>/dev/null | sed "s/^/$1 docker: /" >> "$RUN/logs/disk.log"
}
room() {  # room <what>: the disk guard (measure48_vm.py NEED_GB); a short disk fails the step with its record
  local why rc
  why=$(h disk --path / --for "$1" ${TB_M48_FREE_BYTES:+--free-bytes "$TB_M48_FREE_BYTES"}); rc=$?
  echo "disk: $why" >> "$STEP_LOG"
  [ "$rc" = 0 ] || NOTE="$why"
  return "$rc"
}
gate() {  # gate <stage> [--also <stage>]: 0 = may start; the reason in GATE_WHY
  GATE_WHY=$(h gate --stage "$@" --used-s "$(used)" --line-s "$LINE_S")
}
descendants() { local c; for c in $(pgrep -P "$1"); do echo "$c"; descendants "$c"; done; }
watched() {  # watched <command...>: its output to the step's log; at the stop line SIGINT (then TERM after 3 minutes)
  # a simple command started with & gets SIGINT ignored (bash 5.2, measured); a function (tool) does not, and tool
  # restores it anyway: either way the stop line's SIGINT reaches the command
  if declare -F "$1" > /dev/null; then "$@" >> "$STEP_LOG" 2>&1 < /dev/null &
  else sigint "$@" >> "$STEP_LOG" 2>&1 < /dev/null &
  fi
  local pid=$! t=0 p=0 target
  while kill -0 "$pid" 2>/dev/null; do
    sleep "$POLL"; tick
    if [ "$STOPLINE" = 0 ] && [ "$(used)" -ge "$LINE_S" ]; then
      # SIGINT to the tool itself (STOP_TARGET: lane J's measure, the screen), not to the shells around it (a
      # background shell ignores it) nor to the docker commands it runs (its own cleanup needs them)
      STOPLINE=1
      if [ -n "${STOP_TARGET:-}" ]; then target=$(pgrep -f -- "$STOP_TARGET"); else target="$pid $(descendants "$pid")"; fi
      say "the stop line ($LINE_MIN min): SIGINT to the step's command ($STEP)"
      # shellcheck disable=SC2086  # a list of pids
      kill -INT ${target:-$pid} 2>/dev/null
    fi
    if [ "$STOPLINE" = 1 ]; then
      t=$((t + 1))
      # shellcheck disable=SC2046  # a list of pids
      [ "$t" -lt 18 ] || kill -TERM "$pid" $(descendants "$pid") 2>/dev/null   # 3 minutes after the SIGINT
    fi
    p=$((p + 1)); [ "$p" -lt 6 ] || { p=0; pack; }   # the records up every minute while a step runs
  done
  wait "$pid"
}
run_step() {  # run_step <name> <function>: once (state/<name> = its exit code), timed, logged, the records up
  local name=$1 fn=$2 rc t0
  if [ -f "$RUN/state/$name" ]; then
    NOTE=$(cat "$RUN/state/$name.note" 2>/dev/null); say "$name kept (finished before, exit $(cat "$RUN/state/$name"))"
    return "$(cat "$RUN/state/$name")"
  fi
  STEP=$name; STEP_LOG="$RUN/logs/$name.log"; NOTE=""
  t0=$(stamp); say "$name start"; echo "$t0 $name start" >> "$RUN/clock.txt"; disk_note "$name"
  "$fn"; rc=$?
  printf '%s\t%s\t%s\t%s\t%s\n' "$name" "$t0" "$(stamp)" "$rc" "$(printf '%s' "$NOTE" | tr '\t\n' '  ')" >> "$RUN/steps.tsv"
  echo "$(stamp) $name end rc=$rc" >> "$RUN/clock.txt"
  echo "$rc" > "$RUN/state/$name"; printf '%s' "$NOTE" > "$RUN/state/$name.note"
  say "$name end (exit $rc)${NOTE:+: $NOTE}"; pack
  return "$rc"
}
end_run() {  # the end, on every way out: down, release, the records up, power off (H-47 step 10)
  trap - EXIT
  local why=$1
  [ -n "$(kv kept)" ] && [ ! -f "$RUN/state/s12-down" ] && run_step s12-down step_down
  [ -f "$RUN/kv/ballast-on" ] && [ ! -f "$RUN/state/s14-release" ] && run_step s14-release step_release
  h records --run "$RUN" --used-s "$(used)" --ended "$why" > /dev/null 2>&1
  printf '%s' "$why" > "$RUN/ended"
  off "$why"
}
# A signal (a Spot pre-emption, an ACPI stop: systemd sends SIGTERM) saves the clock and the records but does NOT end
# the run, so the next boot (--resume) goes on; bash would otherwise run the EXIT trap below on SIGTERM.
trap 'trap - EXIT; say "signal: the VM is stopping; the run goes on at the next boot"; tick; pack; kill "$TICKER" 2>/dev/null; exit 143' TERM HUP
trap 'end_run "the script ended unexpectedly"' EXIT
# a boot after the end (a restart by hand) changes nothing: the EXIT trap is dropped first, or off's exit would run
# end_run and overwrite ended (why the run ended) with "the script ended unexpectedly"
[ ! -f "$RUN/ended" ] || { trap - EXIT; off "ended before: $(cat "$RUN/ended")"; }

# ------------------------------------------------------------------ the repository's tools (one stand-in in rehearsal)
tool() {  # tool <name> <args...>: run from the checkout, SIGINT at its default
  if [ -n "$SI" ]; then sigint "$SI" "$@"; return; fi
  local t=$1; shift
  case "$t" in
    ballast48) (cd "$CK" && sigint python3 tools/ballast48.py "$@") ;;
    ballast) (cd "$CK" && sigint python3 -m tools.ballast "$@") ;;
    fetch_weights) (cd "$CK" && sigint python3 -m tools.fetch_weights "$@") ;;
    poc) (cd "$CK" && sigint deploy/poc.sh "$@") ;;
    pinned_ref) (cd "$CK" && python3 -c 'import tools.engine_probe as p; print(p.pinned_ref())') ;;
    complete_run) (cd "$CK" && NODE_PATH=/opt/node-tools/node_modules TB_ENV=DEV PYTHONPATH=libs:services:. \
                   sigint .venv/bin/python -m tools.complete_run "$@") ;;
    fetch_run_data) (cd "$CK" && sigint .venv/bin/python -m tools.fetch_run_data "$@") ;;
    canary) docker run --rm --network trialbox-model-backend -e TB_GPU_KEY -v "$CK/tools/canary.py:/app/tools/canary.py:ro" \
              trialbox-py:1.0.0 python -m tools.canary "$@" ;;
    setup) "screen_setup_$1" ;;
  esac
}

# ------------------------------------------------------------------ s01: the host (driver, reboot, Docker, toolkit)
docker_toolkit() {  # deploy/gpu-sim-startup.sh's Docker and container toolkit lines (test: the same commands)
  if ! command -v docker >/dev/null; then
    curl -fsSL https://get.docker.com | sh
  fi
  if ! docker info 2>/dev/null | grep -qi nvidia; then
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
      sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' > /etc/apt/sources.list.d/nvidia-container-toolkit.list
    apt-get update && apt-get install -y nvidia-container-toolkit
    nvidia-ctk runtime configure --runtime=docker && systemctl restart docker
  fi
}
step_host() {
  echo 'DPkg::Lock::Timeout "600";' > "$ETC/apt/apt.conf.d/99tb-lock-timeout" 2>/dev/null
  if ! nvidia-smi > /dev/null 2>&1; then
    if [ -f "$RUN/kv/rebooted" ]; then NOTE="no working nvidia-smi after the driver's reboot (logs/s01-host.log)"; return 1; fi
    watched sh -c 'apt-get update -q && apt-get install -y -q git make curl python3-yaml python3-venv \
      && apt-get install -y -q nvidia-driver-580-server-open nvidia-utils-580-server' \
      || { NOTE="the driver did not install (D-966's nvidia-driver-580-server-open, logs/s01-host.log)"; return 1; }
    touch "$RUN/kv/rebooted"; decide reboot yes "the driver was installed: one reboot, then this step again"
    pack; trap - EXIT; kill "$TICKER" 2>/dev/null
    if [ -n "${TB_M48_REBOOT:-}" ]; then "$TB_M48_REBOOT"; else systemctl reboot; fi
    exit 0
  fi
  watched sh -c 'apt-get install -y -q git make curl python3-yaml python3-venv' || true
  watched docker_toolkit || { NOTE="Docker or the container toolkit did not install"; return 1; }
  NOTE="driver $(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n 1)"
}
step_card() {
  nvidia-smi --query-gpu=name,memory.total,compute_cap,driver_version,ecc.mode.current --format=csv > "$RUN/records/o0-card.csv" \
    || { NOTE="nvidia-smi gave no card"; return 1; }
  { nproc; free -g; } >> "$RUN/records/o0-card.csv"
  watched docker run --rm --gpus all ubuntu:24.04 nvidia-smi || { NOTE="the card is not seen inside a container"; return 1; }
}
step_source() {
  [ -n "$SRC" ] && [ -n "$SRC_SHA" ] && [ -n "$COMMIT" ] || { NOTE="no tb-src / tb-src-sha256 / tb-commit"; return 1; }
  rm -rf "$W/src" && mkdir -p "$W/src"
  case "$SRC" in gs://*) timeout -k 10 600 gcloud storage cp "$SRC" "$W/src.tgz" >> "$STEP_LOG" 2>&1 ;; *) cp "$SRC" "$W/src.tgz" ;; esac \
    || { NOTE="the archive did not come from $SRC"; return 1; }
  [ "$(sha256sum "$W/src.tgz" | cut -d' ' -f1)" = "$SRC_SHA" ] || { NOTE="the archive's sha256 is not tb-src-sha256"; return 1; }
  tar -xzf "$W/src.tgz" -C "$W/src" && rm -f "$W/src.tgz"
  local head; head=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["head"])' "$W/src/TB_HEAD.json" 2>/dev/null)
  [ "$head" = "$COMMIT" ] || { NOTE="the archive's HEAD ($head) is not tb-commit ($COMMIT)"; return 1; }
  cp "$W/src/TB_HEAD.json" "$RUN/records/head.json"; NOTE="commit $COMMIT"
}
step_weights() {
  room weights || return 1
  watched tool fetch_weights --profile rtxpro6000 \
    || { NOTE="tools/fetch_weights.py failed (no token is sent: a gated file or a hub refusal is in logs/s04-weights.log)"; return 1; }
}
step_stub() {
  room stub || return 1
  TB_POC_SKIP_INGEST=1 tool poc > "$RUN/raw/poc-up.txt" 2>&1 < /dev/null; local rc=$?
  # its output holds the administrator's password: it stays in raw/ on the VM; its last lines go to the step's log
  # only redacted and with every value of deploy/.env and deploy/secrets/ masked
  tail -n 15 "$RUN/raw/poc-up.txt" | h redact --mask-file "$CK/deploy/.env" --mask-dir "$CK/deploy/secrets" >> "$STEP_LOG"
  [ "$rc" = 0 ] || { NOTE="deploy/poc.sh did not start the stub (exit $rc; its last lines, redacted, in logs/s05-stub.log)"; return 1; }
  watched tool poc status; watched tool poc down || { NOTE="deploy/poc.sh down failed"; return 1; }
  [ -s "$CK/deploy/.env" ] || [ -n "$SI" ] || { NOTE="the stub start left no deploy/.env"; return 1; }
  # freed: the build cache (4.0 GB on 2026-11-15), dangling layers, the stub's volumes (made again by compose if used)
  watched docker builder prune -af; watched docker image prune -f
  docker volume ls -q 2>/dev/null | grep '^trialbox_' | xargs -r docker volume rm >> "$STEP_LOG" 2>&1
  disk_note "s05-stub-freed"
}
step_engine() {
  room engine || return 1
  local ref; ref=$(tool pinned_ref) || { NOTE="no pinned engine (tools/engine_probe.py)"; return 1; }
  watched docker pull "$ref" || { NOTE="the engine image did not pull"; return 1; }
  NOTE="$ref"
}
step_ballast() {
  : > "$RUN/records/ballast.log"
  if [ -n "$SI" ]; then setsid "$SI" ballast hold --target-mib 49140 >> "$RUN/records/ballast.log" 2>&1 < /dev/null &
  else (cd "$CK" && exec setsid python3 -m tools.ballast hold --target-mib 49140) >> "$RUN/records/ballast.log" 2>&1 < /dev/null &
  fi
  echo $! > "$RUN/kv/ballast-pid"; touch "$RUN/kv/ballast-on"
  local i=0
  until grep -q -e '^ready' -e '^refused' "$RUN/records/ballast.log"; do
    sleep "$POLL"; i=$((i + 1)); [ "$i" -lt 90 ] || { NOTE="the ballast said neither ready nor refused in 15 minutes"; return 1; }
  done
  grep -q '^ready' "$RUN/records/ballast.log" || { NOTE="the ballast refused: $(grep '^refused' "$RUN/records/ballast.log" | head -n 1)"; return 1; }
  tool ballast48 plan > "$RUN/records/plan.txt" 2>> "$STEP_LOG" || { NOTE="ballast48 plan refused (records/plan.txt)"; return 1; }
}

# ------------------------------------------------------------------ s08: the ladder
measure_dir() { echo "$RUN/records/tb-dgpu48-$1"; }
MEASURE_RE='ballast48(\.py)? measure --option'   # the tool's own process: SIGINT makes lane J's measure write and stop
step_ladder() {
  local tried="" opt why rc line
  [ -s "$RUN/kv/tried" ] && tried=$(cat "$RUN/kv/tried")
  while :; do
    # shellcheck disable=SC2086  # tried is a list of option:rc words
    line=$(h ladder-next --tried $tried); opt=${line%%$'\t'*}; why=${line#*$'\t'}
    [ -n "$opt" ] || { tried=${tried# }; decide ladder "${tried:-none}" "$why"; break; }
    if ! gate 6; then decide "ladder $opt" "not started" "$GATE_WHY"; break; fi
    decide "ladder $opt" try "$why; $GATE_WHY"
    local tb0; tb0=$(grep -c '^Traceback' "$STEP_LOG" 2>/dev/null)
    STOP_TARGET="$MEASURE_RE" TB_UNMEASURED_DGPU48_MEASURING_RUN=1 \
      watched tool ballast48 measure --option "$opt" --keep --out-dir "$(measure_dir "$opt")"
    rc=$?
    [ "$STOPLINE" = 0 ] || rc=130
    # exit 1 is "did not start" only with lane J's record and no new traceback; else the tool broke (3): the
    # ladder ends, since the next option would run the same broken code
    if [ "$rc" = 1 ] && { [ ! -s "$(measure_dir "$opt")/measure.$opt.json" ] \
         || [ "$(grep -c '^Traceback' "$STEP_LOG" 2>/dev/null)" -gt "${tb0:-0}" ]; }; then
      rc=3; decide "ladder $opt result" "the tool broke (exit 1 with a traceback or no record)" "logs/s08-ladder.log"
    elif [ "$rc" = 1 ]; then
      decide "ladder $opt result" "did not start" "$(measure_dir "$opt" | sed "s#^$RUN/##")/measure.$opt.json"
    fi
    tried="$tried $opt:$rc"; printf '%s' "$tried" > "$RUN/kv/tried"
    if [ "$rc" = 0 ]; then kv kept "$opt"; decide kept "$opt" "the first of the ladder that started"; break; fi
  done
  [ -n "$(kv kept)" ] || { NOTE="no option was kept (${tried# })"; return 1; }
  NOTE="kept $(kv kept) (tried${tried})"
}

# ------------------------------------------------------------------ s09, s10: the screen's tools and the small screen
screen_setup_apt() {
  apt-get -o DPkg::Lock::Timeout=600 install -y -qq postgresql tesseract-ocr tesseract-ocr-jpn tesseract-ocr-chi-tra \
    tesseract-ocr-eng python3-venv python3-pip curl xz-utils git
}
screen_setup_py() {
  command -v uv > /dev/null || { python3 -m venv /opt/uv && /opt/uv/bin/pip install -q uv && ln -sf /opt/uv/bin/uv /usr/local/bin/uv; }
  (cd "$CK" && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]")
}
screen_setup_node() {  # as deploy/gcp/complete-run-vm.sh: the pinned LTS, Playwright 1.63.0, Chromium launched once
  local v=v22.23.4
  [ -x "/opt/node-$v-linux-x64/bin/npm" ] || { curl -fsSL "https://nodejs.org/dist/$v/node-$v-linux-x64.tar.xz" | tar -xJ -C /opt; }
  ln -sf "/opt/node-$v-linux-x64/bin/node" "/opt/node-$v-linux-x64/bin/npm" "/opt/node-$v-linux-x64/bin/npx" /usr/local/bin/
  mkdir -p /opt/node-tools && (cd /opt/node-tools && npm i -s playwright@1.63.0 && npx playwright install --with-deps chromium \
    && node -e "require('playwright').chromium.launch().then(b => b.close())")
}
screen_setup_fonts() { (cd "$CK" && .venv/bin/python tools/fetch_fonts.py); }
screen_setup_clean() { uv cache clean; apt-get clean; }
step_tools() {
  room tools || return 1
  echo 'DPkg::Lock::Timeout "600";' > "$ETC/apt/apt.conf.d/99tb-lock-timeout" 2>/dev/null
  local s
  for s in apt py node fonts; do watched tool setup "$s" || { NOTE="the screen's tools: $s failed"; return 1; }; done
  watched tool fetch_run_data --cache "$W/cache" --only hospital-ja || { NOTE="the hospital's data did not come"; return 1; }
  watched tool setup clean; disk_note "s09-tools-freed"
}
pair_kept() { case "$(kv kept)" in pair-32k|pair-16k) return 0 ;; *) return 1 ;; esac; }
servers_up() { [ -n "$SI" ] || [ "$(docker inspect -f '{{.State.Running}}' trialbox-llm-service-1 2>/dev/null)" = true ]; }
key_env() {  # the servers' key into the environment, never printed (tools/dgpu48.py _vllm_key's file)
  TB_GPU_KEY="$(sed -n 's/^VLLM_API_KEY=//p' "$CK/deploy/secrets/model/vllm.env" 2>/dev/null | tail -n 1 | tr -d "\"'")"
  export TB_GPU_KEY="${TB_GPU_KEY:-measuring-run-no-key}"
}
bridge() {  # bridge connect|disconnect: the kept pair on Docker's local bridge (only this VM reaches it)
  docker network "$1" bridge trialbox-llm-service-1 >> "$STEP_LOG" 2>&1
  docker network "$1" bridge trialbox-llm-verifier-1 >> "$STEP_LOG" 2>&1
  return 0
}
step_screen() {
  room screen || return 1
  servers_up || { NOTE="the kept servers are not running (a restart since the ladder?)"; return 1; }
  bridge connect
  local j v
  j=$(docker inspect -f '{{.NetworkSettings.Networks.bridge.IPAddress}}' trialbox-llm-service-1 2>/dev/null)
  v=$(docker inspect -f '{{.NetworkSettings.Networks.bridge.IPAddress}}' trialbox-llm-verifier-1 2>/dev/null)
  key_env
  export NODE_PATH=/opt/node-tools/node_modules TB_ENV=DEV PYTHONPATH=libs:services:.
  # SIGINT to complete_run itself (its own command line starts with the venv's python), not to `during` around it,
  # so `during` writes its record with complete_run's exit code
  STOP_TARGET="^[^ ]*/\.venv/bin/python -m tools\.complete_run --dir $RUN/records/screen" watched tool ballast48 during --out "$RUN/records/screen-during.json" -- \
    "$CK/.venv/bin/python" -m tools.complete_run --dir "$RUN/records/screen" --model pair --patients 1000 --langs ja \
    --only prepare hospital-ja --llm-concurrency 16 --ocr tesseract --judge-url "http://$j:8000/v1" --verifier-url "http://$v:8000/v1"
  local rc=$?
  NOTE="the screen's exit $rc (records/screen-during.json, records/screen/parts/hospital-ja.json)"
  return 0   # a screen that fails is a record, not the run's end (H-47: a failed check does not void the wall time)
}

# ------------------------------------------------------------------ s11: optional stage O; s12 down; s13; s14
step_o() {
  servers_up || { NOTE="the kept servers are not running"; decide O skipped "the kept servers are not running"; return 0; }
  key_env
  watched tool ballast48 verifier-flag --out-dir "$(measure_dir pair-32k)"; local rc=$?
  kv o-flag-rc "$rc"
  if [ "$rc" != 0 ]; then
    decide "O result" "flag refused (exit $rc)" "the verifier did not start with disable_any_whitespace: a result in itself; the canary skipped"
    NOTE="verifier-flag exit $rc: refused"; return 0
  fi
  tool canary --judge-url http://llm-service-vllm:8000/v1 --verifier-url http://llm-verifier-vllm:8000/v1 \
    > "$RUN/records/canary-verifier-flag.json" 2>> "$STEP_LOG"
  NOTE="canary exit $?"
  watched tool ballast48 canary-diff "$(measure_dir pair-32k)/canary.pair-32k.json" "$RUN/records/canary-verifier-flag.json" \
    --json "$RUN/records/canary-verifier-flag-diff.json"
  decide "O result" "flag started" "records/canary-verifier-flag-diff.json"
}
step_down() {
  bridge disconnect
  watched tool ballast48 down --out-dir "$(measure_dir "$(kv kept)")" || { NOTE="ballast48 down failed"; return 1; }
}
step_host53() {
  STOP_TARGET="$MEASURE_RE" TB_UNMEASURED_DGPU48_MEASURING_RUN=1 \
    watched tool ballast48 measure --option pair-32k-host53 --out-dir "$(measure_dir pair-32k-host53)"
  NOTE="pair-32k-host53 exit $?"; return 0
}
step_release() {
  local pid; pid=$(cat "$RUN/kv/ballast-pid" 2>/dev/null)
  [ -z "$pid" ] || kill -TERM "$pid" 2>/dev/null
  pkill -TERM -f 'tools.ballast hold' 2>/dev/null
  local i=0
  until grep -q '^released' "$RUN/records/ballast.log" 2>/dev/null || [ "$i" -ge 6 ]; do sleep "$POLL"; i=$((i + 1)); done
  if ! grep -q '^released' "$RUN/records/ballast.log" 2>/dev/null; then
    watched tool ballast release || { NOTE="the ballast did not say released and release failed"; return 1; }
    NOTE="released by tools.ballast release"
  fi
  rm -f "$RUN/kv/ballast-on"
}

# ------------------------------------------------------------------ the run
say "run $RUN_ID: stop line $LINE_MIN min, cap $CAP_MIN min, optional stage O: $([ "$TAKE_O" = 1 ] && echo taken if time allows || echo not taken)"
stage() {  # stage <H-47 stage> <step> <function> [--also <stage>]: gated, then run; a failure ends the run
  local st=$1 name=$2 fn=$3; shift 3
  if [ ! -f "$RUN/state/$name" ] && ! gate "$st" "$@"; then
    decide "$name" "not started" "$GATE_WHY"; end_run "the stop line: $GATE_WHY"
  fi
  run_step "$name" "$fn" || end_run "$name failed: $NOTE"
}
stage 2 s01-host step_host
run_step s02-card step_card || end_run "s02-card failed: $NOTE"
stage 3 s03-source step_source
run_step s04-weights step_weights || end_run "s04-weights failed: $NOTE"
stage 4 s05-stub step_stub
stage 5 s06-engine step_engine
if [ -f "$RUN/kv/ballast-on" ] && ! pgrep -f 'tools.ballast hold' > /dev/null && [ -z "$SI" ]; then
  rm -f "$RUN/state/s07-ballast"; decide ballast "held again" "a restart dropped it (a pre-emption): the later steps need it"
fi
run_step s07-ballast step_ballast || end_run "s07-ballast failed: $NOTE"
run_step s08-ladder step_ladder || end_run "s08-ladder: $NOTE"
if ! pair_kept; then
  decide screen skipped "$(kv kept) serves no verifier: the screen runs the pair"
elif [ -f "$RUN/state/s10-screen" ] || gate 7 --also 8; then
  [ -f "$RUN/state/s09-tools" ] || decide screen run "${GATE_WHY:-kept before}"
  run_step s09-tools step_tools && run_step s10-screen step_screen
else
  decide screen "not started" "$GATE_WHY"
fi
if [ "$(kv kept)" != pair-32k ]; then
  decide O skipped "the kept option is $(kv kept), not pair-32k"
elif [ "$TAKE_O" != 1 ]; then
  decide O skipped "not taken at the launch (tb-o=0)"
elif [ -f "$RUN/state/s11-o" ] || gate O; then
  [ -f "$RUN/state/s11-o" ] || decide O run "$GATE_WHY"
  run_step s11-o step_o
else
  decide O skipped "$GATE_WHY"
fi
run_step s12-down step_down
if [ "$(kv kept)" != pair-32k ]; then
  decide "step 9" skipped "the kept option is $(kv kept): the ladder ran, nothing more (H-47 step 9)"
elif [ -f "$RUN/state/s13-host53" ] || gate 9; then
  [ -f "$RUN/state/s13-host53" ] || decide "step 9" run "$GATE_WHY"
  run_step s13-host53 step_host53
else
  decide "step 9" dropped "$GATE_WHY"
fi
end_run "complete: every stage ran or was decided (decisions.json)"
