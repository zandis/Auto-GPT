#!/bin/bash
# run.sh: the e2e-box gate (TRIAGE-1 G1). A fresh VM, the bundle installed by its one command with the questions
# answered at a terminal and the site's size declared, a synthetic hospital of that size, then every journey as a
# script (one row per step, metrics every 20 s), and the verdict (verdict.py). See README.md.
#   BUNDLE=/path/trialbox-<id>.tar [SIZE=50000] tests/e2e-box/run.sh
# Beside the bundle: trialbox-bootstrap.sh, its .sig and vendor_ed25519.pub (or VENDOR_PUB). Optional: NEXT_IMG (the
# next bundle's media, for the update journey), E2E_MODELS_ENV with E2E_JUDGE_PORT/E2E_VERIFIER_PORT (the host's
# served pair), E2E_REDCAP_URL with E2E_REDCAP_TOKEN_FILE (the REDCap bench), BASELINE (the last run's journeys.csv),
# KNOWN (default known.tsv), KEEP=1 (leave the VM running). Exit 0 only on a GREEN verdict.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
BUNDLE=${BUNDLE:?the bundle tar}
BDIR=$(cd "$(dirname "$BUNDLE")" && pwd)
VENDOR_PUB=${VENDOR_PUB:-$BDIR/vendor_ed25519.pub}
SIZE=${SIZE:-50000}
NAME=${NAME:-vm-e2e}
PORTBASE=${PORTBASE:-29700}
E2E_HOME=${E2E_HOME:-$HOME/e2e-box}
E2E_VMS=${E2E_VMS:-/dev/shm/e2e-box}
export E2E_HOME E2E_VMS E2E_CPUSET=${E2E_CPUSET:-112-175}
ID=$(basename "$BUNDLE" .tar)
ID=${ID#trialbox-}
[[ $ID =~ ^[A-Za-z0-9._-]+$ && $SIZE =~ ^[0-9]+$ && $NAME =~ ^[a-z0-9][a-z0-9-]*$ && $PORTBASE =~ ^[0-9]+$ ]] || {
  echo "bad input: bundle id, SIZE, NAME or PORTBASE" >&2
  exit 2
}
OUT=${OUT:-$E2E_HOME/runs/$(date -u +%Y%m%dT%H%M)-$ID}
PY=${PY:-$REPO/.venv/bin/python}
mkdir -p "$E2E_VMS"
mkdir -p "$OUT" && chmod 0700 "$OUT"
exec 9> "$E2E_VMS/$NAME.lock"
flock -n 9 || { echo "another run holds $NAME" >&2; exit 2; }
[ ! -e "$E2E_VMS/$NAME" ] || { echo "$E2E_VMS/$NAME exists: another VM of that name; nothing was changed" >&2; exit 2; }
if [ -n "${E2E_MODELS_ENV:-}" ] && ! [[ ${E2E_JUDGE_PORT:-} =~ ^[0-9]+$ && ${E2E_VERIFIER_PORT:-} =~ ^[0-9]+$ && -s $E2E_MODELS_ENV ]]; then
  echo "E2E_MODELS_ENV needs a readable key file and E2E_JUDGE_PORT, E2E_VERIFIER_PORT" >&2
  exit 2
fi
# shellcheck source=lib.sh
source "$HERE/lib.sh"
# shellcheck source=journeys.sh
source "$HERE/journeys.sh"
exec > >(tee -a "$OUT/run.log") 2>&1
SINCE=$(date -u +%FT%TZ)
echo "e2e-box $ID size=$SIZE vm=$NAME cores=$E2E_CPUSET out=$OUT since=$SINCE"

make_media() { # the install media: a read-only ext4 image holding what goes on the USB stick
  local st=$E2E_VMS/$NAME-stage f size
  rm -rf "$st"
  mkdir -p "$st"
  for f in "$BUNDLE" "$BDIR/trialbox-bootstrap.sh" "$BDIR/trialbox-bootstrap.sh.sig" "$VENDOR_PUB"; do
    ln -f "$f" "$st/" 2> /dev/null || cp "$f" "$st/" || return 1
  done
  size=$(($(du -sb "$st" | cut -f1) / 1073741824 + 4))
  rm -f "$MEDIA"
  mke2fs -q -t ext4 -m 0 -d "$st" "$MEDIA" "${size}G"
  local rc=$?
  rm -rf "$st"
  return $rc
}
make_feed() { # the synthetic hospital at the declared size (tools/make_fixtures.py), cached per size
  local d=$E2E_HOME/feed-$SIZE
  [ -s "$d/site-a/patient.csv" ] || "$PY" "$REPO/tools/make_fixtures.py" --out "$d" --sites a --patients "$SIZE" > "$EV/feed-gen.txt" 2>&1 || return 1
  (cd "$d/site-a" && tar -czf "$E2E_VMS/$NAME-feed.tgz" ./*.csv) && "$CTL" put "$NAME" "$E2E_VMS/$NAME-feed.tgz" /tmp/feed.tgz
  local rc=$?
  rm -f "$E2E_VMS/$NAME-feed.tgz"
  [ $rc = 0 ] && vm "sudo rm -rf $FEED && sudo mkdir -p $FEED && sudo tar -xzf /tmp/feed.tgz -C $FEED && rm -f /tmp/feed.tgz && ls $FEED | wc -l"
}
feed_picks() { # MRN for CASE, MRN for the opt-out, and the doctor with the most patients under the 20,000 death-check cap
  python3 - "$E2E_HOME/feed-$SIZE/site-a" << 'PY'
import csv, sys
from collections import defaultdict
d = sys.argv[1]
mrns = [r['mrn'] for _, r in zip(range(5), csv.DictReader(open(f'{d}/patient.csv', encoding='utf-8')))]
per = defaultdict(set)
for r in csv.DictReader(open(f'{d}/encounter.csv', encoding='utf-8')):
    per[r['staff_id']].add(r['mrn'])
fit = sorted((len(v), k) for k, v in per.items() if len(v) < 20000) or [(0, '')]
print(mrns[2], mrns[4], fit[-1][1])
PY
}
vm_up() { "$CTL" new "$NAME" "$PORTBASE" "$MEDIA" "${VCPU:-24}" "${VMEM:-96G}" && "$CTL" start "$NAME"; }
prepare() { # as hospital IT leaves the machine: the zone, swap off, the vendor key, the stick at /media/usb, the GPU stand-in
  vm "sudo bash -s $SITE_TZ" << 'SH'
set -e
timedatectl set-timezone "$1"; echo "$1" > /etc/timezone; swapoff -a; sed -i '/ swap /d' /etc/fstab
mkdir -p /media/usb; cp /tmp/vendor_ed25519.pub /root/vendor_ed25519.pub
install -m 0755 /tmp/nvidia-smi /usr/local/bin/nvidia-smi
(umask 077; head -c 24 /dev/urandom | base64 > /root/e2e-kek.pass)
mount --bind /mnt/media /media/usb 2> /dev/null || mount -o ro --bind /mnt/media /media/usb
ls /media/usb | tr '\n' ' '
SH
}
take_secrets() { # the first administrator's password and code: the VM's root-only file to the run's creds, checked, then
  # removed on the VM (only once the copy is whole)
  rm -f "$CREDS/admin.json"
  (umask 077 && vm 'sudo cat /root/e2e-first-admin.json' > "$CREDS/admin.json") || return 1
  python3 -c 'import json, sys; d = json.load(open(sys.argv[1])); assert set(d) == {"password", "enrol"} and all(d.values()), sorted(d); print("kept: password, enrolment code")' "$CREDS/admin.json" || return 1
  vm 'sudo rm -f /root/e2e-first-admin.json'
}
secret_values() { python3 -c 'import json, sys; print("\n".join(json.load(open(sys.argv[1])).values()))' "$CREDS/admin.json"; }
transcript_clean() { # G6 / RULINGS Q3: neither one-time value anywhere the install or this run wrote text; files root-only
  local onbox here rc
  vm 'for f in /var/tmp/install.log /var/tmp/prompts.txt; do [ "$(sudo stat -c %a $f)" = 600 ] || { echo "$f is not 0600"; exit 1; }; done' || return 1
  onbox=$(secret_values | vm 'sudo grep -rlF -f - /var/tmp/install.log /var/tmp/prompts.txt $(sudo find /opt/trialbox/deploy/site/box -type f 2> /dev/null); [ $? -le 1 ]') || { echo "the scan on the box failed"; return 1; }
  here=$(secret_values | grep -rlF -f - "$OUT" --exclude-dir=creds)
  rc=$?
  [ $rc -le 1 ] || { echo "the scan of the run folder failed"; return 1; }
  echo "files holding a one-time value: on the box [${onbox}], in this run's folder [${here}]"
  [ -z "$onbox" ] && [ -z "$here" ]
}
snapshot() { # settings of the box: env:KEY and file:PATH with a hash of the value, never the value
  vm 'sudo bash -s' << 'SH'
cd /opt/trialbox/deploy
awk -F= '/^[A-Za-z_][A-Za-z0-9_]*=/ {k=$1; sub(/^[^=]*=/, ""); v[k]=$0} END {for (k in v) print k "=" v[k]}' .env | sort | while IFS= read -r l; do
  printf 'env:%s %s\n' "${l%%=*}" "$(printf '%s' "${l#*=}" | sha256sum | cut -c1-16)"; done
{ find site -type f \( -name '*.yaml' -o -name '*.yml' -o -name '*.py' \); ls secrets/model/vllm.env secrets/backup.pub 2> /dev/null; } | sort |
  while read -r f; do printf 'file:%s %s\n' "$f" "$(sha256sum < "$f" | cut -c1-16)"; done
SH
}
sampler() { # container CPU, memory, I/O and the box's disks every 20 s
  local ts
  echo 'ts,container,cpu_pct,mem_used,mem_limit,mem_pct,net_io,block_io,pids' > "$M/containers.csv"
  echo 'ts,mount,size,used,avail,use_pct' > "$M/disk.csv"
  while :; do
    ts=$(date -u +%FT%TZ)
    vm 'sudo docker stats --no-stream --format "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.NetIO}}|{{.BlockIO}}|{{.PIDs}}"' 2> /dev/null |
      awk -F'|' -v ts="$ts" '{split($3, m, " / "); gsub(/%/, "", $2); gsub(/%/, "", $4); print ts "," $1 "," $2 "," m[1] "," m[2] "," $4 "," $5 "," $6 "," $7}' >> "$M/containers.csv"
    vm 'df -P -h / /var/lib/docker | tail -n +2' 2> /dev/null | awk -v ts="$ts" '{print ts "," $6 "," $2 "," $3 "," $4 "," $5}' >> "$M/disk.csv"
    sleep 20
  done
}
collect() { # per container WARN+ lines, audit events, model calls and tokens, per-component peaks, storage
  vm "for c in \$(sudo docker ps -a --format '{{.Names}}' | grep ^trialbox- | sort); do
    l=\$(sudo docker logs --since $SINCE \$c 2>&1); n=\$(printf '%s\n' \"\$l\" | grep -cE '\"level\": \"(WARNING|ERROR|CRITICAL)\"|\\b(WARN|ERROR|FATAL)\\b')
    e=\$(printf '%s\n' \"\$l\" | grep -cE '\"level\": \"(ERROR|CRITICAL)\"|\\b(ERROR|FATAL)\\b'); echo \"\$c,\$n,\$e\"; done" > "$M/logs_warn.tmp" 2>&1
  { echo "container,warn_plus_lines,error_lines"; cat "$M/logs_warn.tmp"; } > "$M/logs_warn.csv"
  rm -f "$M/logs_warn.tmp"
  { echo "event,count,first,last"; psql_wf "select event||','||count(*)||','||min(at)||','||max(at) from audit.journal where at >= '$SINCE' group by event order by count(*) desc"; } > "$M/audit_events.csv"
  { echo "model,prompt_id,prompt_version,calls"; psql_wf "select model||','||prompt_id||','||prompt_version||','||count(*) from provenance.model_calls where at >= '$SINCE' group by 1, prompt_id, prompt_version order by count(*) desc"; } > "$M/model_calls.csv"
  { echo "field,lines,sum"; vm "sudo docker logs --since $SINCE trialbox-gateway-1 2>&1 | grep -oE '\"(prompt_tokens|completion_tokens|input_tokens|output_tokens)\": *[0-9]+' | awk -F': *' '{gsub(/\"/, \"\", \$1); s[\$1] += \$2; n[\$1]++} END {for (k in s) print k \",\" n[k] \",\" s[k]}'"; } > "$M/model_tokens.csv"
  python3 - "$M/containers.csv" > "$M/components.csv" << 'PY'
import csv, sys
def mib(s):
    s = s.strip()
    for u, f in (('GiB', 1024), ('MiB', 1), ('KiB', 1 / 1024), ('B', 1 / 1048576)):
        if s.endswith(u):
            return float(s[:-len(u)]) * f
    return 0.0
agg = {}
for r in csv.DictReader(open(sys.argv[1])):
    a = agg.setdefault(r['container'], {'cpu': [], 'mem': [], 'lim': r['mem_limit']})
    try:
        a['cpu'].append(float(r['cpu_pct'])); a['mem'].append(mib(r['mem_used']))
    except ValueError:
        pass
print('container,samples,cpu_mean,cpu_peak,mem_mean_mib,mem_peak_mib,mem_limit,peak_pct_of_limit')
for c, a in sorted(agg.items()):
    n = max(1, len(a['cpu'])); pk = max(a['mem'] or [0])
    print(f"{c},{len(a['cpu'])},{sum(a['cpu']) / n:.1f},{max(a['cpu'] or [0]):.1f},{sum(a['mem']) / n:.0f},{pk:.0f},{a['lim']},{100 * pk / (mib(a['lim']) or 1):.0f}")
PY
  vm "sudo docker system df --format '{{.Type}},{{.TotalCount}},{{.Size}},{{.Reclaimable}}'" > "$M/storage.csv" 2>&1
}

MEDIA=$E2E_VMS/$NAME-media.img
SAMPLER=
MADE=
cleanup() { # only what this run made: its media and the VM it created (the lock is held until exit)
  [ -z "$SAMPLER" ] || kill "$SAMPLER" 2> /dev/null
  [ "${KEEP:-0}" = 1 ] && return
  if [ "$MADE" = vm ]; then
    "$CTL" stop "$NAME" > /dev/null 2>&1 || "$CTL" stop "$NAME" --kill > /dev/null 2>&1
    "$CTL" remove "$NAME" > /dev/null 2>&1
  fi
  [ -z "$MADE" ] || rm -f "$MEDIA"
}
trap cleanup EXIT
J=INSTALL
step $J "install media made from the bundle (read-only image)" make_media || exit 2
MADE=media
step $J "vm created and started (cores $E2E_CPUSET)" vm_up || { [ -e "$E2E_VMS/$NAME" ] && MADE=vm; exit 2; }
MADE=vm
step $J "vm ready: ssh, cloud-init done, docker active" waitfor 120 vm 'test -f /var/lib/tbvm-ready && systemctl is-active docker' || exit 2
"$CTL" put "$NAME" "$HERE/ptyinstall.py" /tmp/ptyinstall.py
"$CTL" put "$NAME" "$REPO/tools/rehearse_box/shims/nvidia-smi" /tmp/nvidia-smi
"$CTL" put "$NAME" "$VENDOR_PUB" /tmp/vendor_ed25519.pub
step $J "zone, swap off, vendor key, the stick at /media/usb (as IT leaves it)" prepare
step $J "bootstrap signature verifies (runbook first command)" vm 'cd /media/usb && openssl pkeyutl -verify -pubin -inkey /root/vendor_ed25519.pub -rawin -in trialbox-bootstrap.sh -sigfile trialbox-bootstrap.sh.sig'
step $J "one-command install, the questions answered at a terminal ($SIZE patients declared)" vm "sudo python3 /tmp/ptyinstall.py trialbox-$ID.tar /root/e2e-kek.pass $SIZE > /dev/null 2>&1; rc=\$?; echo rc=\$rc prompts=\$(sudo grep -c '^PROMPT:' /var/tmp/prompts.txt); exit \$rc"
rec $J "run conditions (as the VM matrix installs): TB_HOST_PROFILE=poc, rehearsal stand-ins, --tier large, --rehearsal, GPU stand-in, $SIZE patients declared" PASS 0 "bundle $ID"
(
  umask 077
  vm 'sudo cat /var/tmp/prompts.txt' > "$EV/install-prompts.txt" 2>&1
  vm 'sudo cat /var/tmp/install.log' > "$EV/install.log" 2>&1
)
step $J "the first password and enrolment code reach the harness only (creds, 0600)" take_secrets
step $J "the kept transcript holds no one-time value and is root-only (G6)" transcript_clean
step $J "all box containers healthy" waitfor 60 healthy
step $J "host check: no FAIL line" vm 'cd /opt/trialbox && sudo deploy/check_host.sh > /var/tmp/check_host.txt 2>&1; echo "rc=$? fail_lines=$(grep -c FAIL /var/tmp/check_host.txt)"; [ "$(grep -c FAIL /var/tmp/check_host.txt)" = 0 ]'
step $J "installed tree = release host list" vm 'cd /opt/trialbox && sudo python3 -m tools.host_tree status --base /opt/trialbox'
snapshot > "$M/config-installed.txt" 2> /dev/null
step $J "synthetic hospital of $SIZE patients on the box (tools/make_fixtures.py)" make_feed
sampler > /dev/null 2>&1 &
SAMPLER=$!

if grep -q ",INSTALL,one-command install.*,PASS," "$STEPS"; then
  read -r MRN OPTMRN DOCTOR <<< "$(feed_picks)"
  j_accounts
  j_nights
  j_data_extra
  j_ops
  python3 "$HERE/actions.py" journey screen "$(today)" "$MRN" "$DOCTOR" > "$EV/screen-actions.json"
  VARS="{\"optmrn\":\"$OPTMRN\"}" jrun "$EV/screen-actions.json" screen
  python3 "$HERE/actions.py" journey people "$(today)" > "$EV/people-actions.json"
  VARS=$(python3 -c 'import json, sys; d = json.load(open(sys.argv[1])) if open(sys.argv[1]).read().strip() else {}; d["optmrn"] = sys.argv[2]; print(json.dumps(d))' "$EV/screen.vars.json" "$OPTMRN") \
    jrun "$EV/people-actions.json" people
  j_walk
  j_edc
  python3 "$HERE/actions.py" journey perf "$(today)" > "$EV/perf-actions.json"
  jrun "$EV/perf-actions.json" perf
  j_backup
  snapshot > "$M/config-checked.txt" 2> /dev/null # before the update, which may write settings of its own
  j_update
  j_hard_days
  collect
fi
python3 "$HERE/verdict.py" "$OUT" "${BASELINE:-}" "${KNOWN:-$HERE/known.tsv}"
exit $?
