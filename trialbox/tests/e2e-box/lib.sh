# shellcheck shell=bash
# e2e-box library, sourced by run.sh and every journey. One CSV row per journey step in $OUT/metrics/steps.csv, the
# step's output in $OUT/evidence/. Needs NAME (the VM) and OUT (this run's folder).
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CTL=$HERE/vmctl.sh
EV=$OUT/evidence
M=$OUT/metrics
CREDS=$OUT/creds
mkdir -p "$EV" "$M"
mkdir -p "$CREDS" && chmod 0700 "$CREDS"
STEPS=$M/steps.csv
[ -s "$STEPS" ] || echo 'ts,attempt,journey,step,result,seconds,detail' > "$STEPS"
A=${A:-1}
DC='cd /opt/trialbox && sudo docker compose --project-directory deploy'
RS=GOUT-301
export NAME OUT DC RS

vm() { "$CTL" ssh "$NAME" "set -o pipefail; $*"; } # a pipe's failure is the command's (no `| tail` hides an exit code)
csvq() { printf '%s' "$1" | tr '\n\r,"' '  ;'"'" | cut -c1-300; }
rec() { # journey step result seconds detail
  echo "$(date -u +%FT%TZ),$A,$1,$(csvq "$2"),$3,$4,$(csvq "$5")" >> "$STEPS"
  echo "[$1] $2 -> $3 (${4}s) $(csvq "$5" | cut -c1-160)"
}
step() { # journey step cmd... : PASS on rc 0; the output goes to evidence/
  local j=$1 s=$2 t0 out rc f cs
  shift 2
  t0=$(date +%s%N)
  f=$EV/$(echo "$j-$s" | tr -c 'A-Za-z0-9._-' '_' | cut -c1-90).txt
  out=$("$@" 2>&1)
  rc=$?
  printf '%s\n' "$out" > "$f"
  cs=$((($(date +%s%N) - t0) / 10000000))
  if [ $rc = 0 ]; then
    rec "$j" "$s" PASS "$((cs / 100)).$(printf '%02d' $((cs % 100)))" "$(printf '%s' "$out" | tail -c 180)"
  else
    rec "$j" "$s" FAIL "$((cs / 100)).$(printf '%02d' $((cs % 100)))" "rc=$rc $(printf '%s' "$out" | tail -c 170)"
  fi
  return $rc
}
deviate() { # id why cmd... : a change to the box as installed, recorded as a DEVIATION row (G5), then made
  local id=$1 why=$2 r=APPLIED
  shift 2
  rec DEVIATION "$id: $why" STARTED 0 "" # a run cut here leaves a deviation that never applied: inconclusive
  "$@" > "$EV/deviation-$id.txt" 2>&1 || r=FAILED
  rec DEVIATION "$id: $why" "$r" 0 "$(tail -c 160 "$EV/deviation-$id.txt")"
}
skip() { rec "$1" "$2" SKIP 0 "$3"; } # journey step reason : a step not run, and why
waitfor() {
  local n=$1 i
  shift
  for i in $(seq 1 "$n"); do
    "$@" > /dev/null 2>&1 && return 0
    [ "$i" = "$n" ] || sleep 10
  done
  return 1
}
healthy() {
  vm 'n=$(sudo docker ps --format "{{.Names}} {{.Status}}" | grep "^trialbox-" | grep -c "(healthy)")
      u=$(sudo docker ps -a --format "{{.Names}} {{.Status}}" | grep "^trialbox-" | grep -vc "(healthy)")
      echo "healthy=$n other=$u"; [ "$n" -ge 12 ] && [ "$u" = 0 ]'
}
unseal() { # runbook 22 step 2 after a boot; a box with no key to unseal says so and the step is a no-op
  waitfor 6 vm 'cd /opt/trialbox && sudo env PYTHONPATH=/opt/trialbox/libs:/opt/trialbox/services:/opt/trialbox python3 -m tools.keys unseal --passphrase-file /root/e2e-kek.pass --keep-passphrase-files'
}
psql_wf() { vm "sudo docker exec trialbox-db-1 psql -U hapi -d trialbox_wf -Atc \"$1\""; }
envset() { # KEY VALUE : set one line of the box's deploy/.env (site configuration; the caller records the deviation)
  vm "sudo sed -i -e '\$a $1=$2' -e '/^$1=/d' /opt/trialbox/deploy/.env && sudo grep -qxF '$1=$2' /opt/trialbox/deploy/.env"
}
answer() { sed -n "s/^$1: *['\"]\{0,1\}\([A-Za-z0-9_+\/.-]*\).*/\1/p" "$HERE/../../tools/rehearse_box/site_answers.yaml" | head -1; }
SITE_TZ=$(answer tz)
TB_HOSTNAME=${TB_HOSTNAME:-$(answer tls_hostname)} # the console answers only to its TLS name (pw.sh)
export SITE_TZ TB_HOSTNAME
today() { vm 'date +%F'; }
day() { vm "date -d '$1 days' +%F"; } # day -4 : four days before the box's today
pw() { "$HERE/pw.sh" "$@"; }         # a browser driver under pw/ (Playwright in its container)
jrun() { "$HERE/jrun.sh" "$@"; }     # a journey's actions through the browser runner, one row per action
