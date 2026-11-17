#!/usr/bin/env bash
# TrialBox small demo VM (the owner's demo of 2026-11-17): one CPU VM, the demo image (stub model, synthetic hospital),
# Caddy with TLS in front, reachable on tcp:443 only (from the given addresses, or from any address with
# TB_DEMO_ALLOW=any), a hard stop.
# docs/runbook/11-cloud-runs.md ("The small demo VM"). It costs money while it runs: the owner's yes first.
#
#   deploy/gcp/demo-vm.sh --estimate       machine, US$ per hour, day and week, disk; the prices' source and date
#   deploy/gcp/demo-vm.sh --dry-run [CMD]  every gcloud command CMD (default up) would run; runs none
#   deploy/gcp/demo-vm.sh up [--yes]       network, subnet, the tcp:443 rule, the VM (or start the stopped one);
#                                          without --yes it only prints, as --dry-run
#   deploy/gcp/demo-vm.sh status [--boot-id ID]  the VM, its address, the rule's ranges, the hard stop, the boot
#                                          log's end; DEMO-VM-READY only from this boot (D-1120: its id, or stamped
#                                          after the VM's last start; ID, the one `links` printed, decides alone)
#   deploy/gcp/demo-vm.sh links            the people's one-time links (D-776; written by the VM after the seed):
#                                          prints them once and deletes the object; give each person their own line
#   deploy/gcp/demo-vm.sh down             stop the VM and check that it shows TERMINATED (the disk stays)
#   deploy/gcp/demo-vm.sh delete [--yes]   delete the VM (and its disk), the rule, the subnet and the network
#
# Settings (environment; deploy/gcp/demo_vm.py has each one's reason, tb_common.config.DECLARED their rows):
#   TB_DEMO_ALLOW         required for up: the source ranges of tcp:443, e.g. 1.2.3.4/32,5.6.7.8/32; or the word
#                         any: tcp:443 from 0.0.0.0/0, open to any address, the sign-in password the only gate (the
#                         owner's ruling of 2026-11-15: a PoC with synthetic data only). Empty or missing is refused.
#   TB_DEMO_VM_NETWORK    default: the project's `default` network (no networkAdmin needed); the VM gets an allow
#                         tcp:443 rule and a deny-all rule on its tag, which beats the network's SSH/RDP rules.
#                         own: a network of its own (needs roles/compute.networkAdmin)
#   TB_DEMO_VM_MODE       demo (default), or steps (D-1062): demo mode stays off and a person may be admin or
#                         steward too, so a study can be walked from its first step (synthetic or public text only)
#   TB_DEMO_VM_PEOPLE     owner:investigator,guest:coordinator: one account per person, opened with a one-time code;
#                         each chooses the password on /enrol (no password from anyone, no Secret Manager)
#   TB_DEMO_VM_HANDOFF    the private gs:// place for the codes' object (default $TB_BUCKET/demo-vm)
#   TB_DEMO_VM_ENROL_HOURS 24  an unused code expires after this
#   TB_DEMO_VM_IMAGE      required for up: REGISTRY/PATH@sha256:<digest>, or gs://BUCKET/trialbox-demo.tar.gz with
#                         TB_DEMO_VM_IMAGE_SHA256
#   TB_DEMO_VM_NAME tb-demo-vm  TB_DEMO_VM_ZONE asia-east1-a  TB_DEMO_VM_MACHINE e2-standard-4  TB_DEMO_VM_DISK_GB 30
#   TB_DEMO_VM_HOURS 12 (the hard stop of each up)  TB_DEMO_LANG ja
#   TB_DEMO_SITE_LANG (unset: both campuses)  TB_DEMO_VM_PRICE_* (the estimate)  TB_DEMO_VM_STOP_WAIT_S 300
#   gcloud: a private CLOUDSDK_CONFIG (the default ~/.config/gcloud is refused) and TB_SA_KEY_FILE, the key file's
#   PATH (gcloud reads it; nothing here does), as deploy/gcp/complete-run.sh; the project is the gcloud config's.
# Never: a GPU, a real model (TB_LLM_MODE other than stub is refused), port 80, SSH, a password in the metadata.
# The passwords: each person chooses their own on the demo's /enrol page; nothing here reads or makes one.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BOOT="$HERE/demo-vm-boot.sh"
PY="${PY:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY=python3
DRY=0; YES=0; ESTIMATE=0; CMD=""; BOOT_ID=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --yes) YES=1 ;;
    --estimate) ESTIMATE=1 ;;
    --boot-id)  # status only: this boot's id, as `links` printed it (D-1120)
      [ $# -ge 2 ] && [[ "$2" =~ ^[0-9a-f]{16}$ ]] || { echo "--boot-id takes the 16 hex digits \`links\` printed" >&2; exit 2; }
      BOOT_ID=$2; shift ;;
    -h | --help) sed -n 2,40p "$0"; exit 0 ;;
    up | status | down | delete | links) [ -z "$CMD" ] || { echo "one command only" >&2; exit 2; }; CMD=$1 ;;
    *) echo "unknown argument: $1" >&2; sed -n 2,40p "$0" >&2; exit 2 ;;
  esac
  shift
done

if [ "$ESTIMATE" = 1 ]; then exec "$PY" "$HERE/demo_vm.py" estimate; fi
if [ -z "$CMD" ]; then
  [ "$DRY" = 1 ] || { sed -n 2,40p "$0" >&2; exit 2; }
  CMD=up
fi
[ -z "$BOOT_ID" ] || [ "$CMD" = status ] || { echo "--boot-id is for status only" >&2; exit 2; }
case "$CMD" in
  up | delete)
    if [ "$DRY" = 0 ] && [ "$YES" = 0 ]; then
      echo "demo-vm: '$CMD' changes the cloud and may cost money; this is what it would run. Add --yes to run it."
      DRY=1
    fi ;;
esac

# the checked settings (a refused one stops here, before any gcloud call)
FOR=$CMD; [ "$CMD" = up ] && [ "$DRY" = 1 ] && FOR=dry
SETTINGS="$("$PY" "$HERE/demo_vm.py" shell "$FOR")" || exit 2
N=""; NETWORK=""; ALLOW_PRIORITY=""; DENY_PRIORITY=""; ZONE=""; REGION=""; MACHINE=""; DISK_GB=""; HOURS=""; ALLOW=""; IMAGE=""; IMAGE_SHA256=""; PEOPLE=""; ENROL_HOURS=""; HANDOFF=""
DEMO_LANG=""; SITE_LANG=""; STOP_WAIT_S=""; OPEN_ANY=0; GATE=""; MODE=""; MODE_TEXT=""; SHARED_PASSWORD=0
eval "$SETTINGS"   # shlex-quoted assignments of the names above, from demo_vm.py only
[ -n "$IMAGE" ] || IMAGE="<TB_DEMO_VM_IMAGE>"
[ -n "$ALLOW" ] || ALLOW="<TB_DEMO_ALLOW>"
OPEN_TEXT="open to any address; the sign-in password is the only gate"
if [ "$OPEN_ANY" = 1 ]; then
  REACH="tcp:443 from $ALLOW: $GATE (TB_DEMO_ALLOW=any; the owner's ruling of 2026-11-15, PoC, synthetic data)"
  RULE_WHY="TrialBox demo VM: https from any address (owner's ruling 2026-11-15; PoC, synthetic data; password only)"
else
  REACH="tcp:443 from $ALLOW only"
  RULE_WHY="TrialBox demo VM: https from the allowed ranges only"
fi
if [ "$NETWORK" = own ]; then NET="$N-net"; else NET=default; fi
SUBNET="$N-subnet"; RULE="$N-https"; DENY="$N-deny"; TAG="$N"
SUBNET_RANGE=10.42.0.0/24   # private addresses of the demo's own network (one VM); not a limit

if [ "$DRY" = 0 ]; then
  : "${CLOUDSDK_CONFIG:?set a private CLOUDSDK_CONFIG and TB_SA_KEY_FILE (the path of the key file); never the default config}"
  case "$CLOUDSDK_CONFIG" in "$HOME/.config/gcloud"* | */.config/gcloud | */.config/gcloud/*)
    echo "demo-vm: CLOUDSDK_CONFIG must be private, not the default gcloud config" >&2; exit 2 ;;
  esac
fi
unset CLOUDSDK_AUTH_ACCESS_TOKEN
export GC_DRY="$DRY"
# shellcheck source=deploy/gcp/gcloud-auth.sh
. "$HERE/gcloud-auth.sh"
gc_start || exit 5

say() { echo "== $*"; }
die() { echo "demo-vm: $*" >&2; exit 3; }
exists() {  # exists <gcloud describe args>: in a dry run nothing exists yet (the whole plan is printed)
  if [ "$DRY" = 1 ]; then echo "+ gcloud $* --format=value(name)   # exists?"; return 1; fi
  gc "$@" --format='value(name)' >/dev/null 2>&1
}
DRY_ST=RUNNING; [ "$CMD" = up ] && DRY_ST=NONE   # a dry run of up plans a new VM; of the others, a running one
vm_status() {  # RUNNING, TERMINATED, ... NONE (gcloud says not found) or UNKNOWN (any other failure)
  if [ "$DRY" = 1 ]; then echo "+ gcloud compute instances describe $N --zone $ZONE --format=value(status)" >&2; echo "$DRY_ST"; return 0; fi
  local out err rc=0
  err="$(mktemp)"
  out="$(gc compute instances describe "$N" --zone "$ZONE" --format='value(status)' 2>"$err")" || rc=$?
  if [ "$rc" = 0 ] && [ -n "$out" ]; then echo "$out"
  elif grep -qiE 'not found|notFound|NOT_FOUND' "$err"; then echo NONE
  else echo UNKNOWN; fi
  rm -f "$err"
}
vm_ip() {
  [ "$DRY" = 1 ] && { echo "<the VM's address>"; return 0; }
  gc compute instances describe "$N" --zone "$ZONE" --format='value(networkInterfaces[0].accessConfigs[0].natIP)'
}

if [ "$DRY" = 1 ]; then
  echo "+ gcloud auth activate-service-account --key-file \"\$TB_SA_KEY_FILE\" --quiet   # the path only; gcloud reads it"
  echo "+ gcloud auth print-access-token   # the probe (its output is dropped)"
  echo "+ gcloud config get-value project"
  PROJECT="<project from the gcloud config>"
else
  PROJECT="$(gc config get-value project 2>/dev/null || true)"
  [ -n "$PROJECT" ] && [ "$PROJECT" != "(unset)" ] || die "no project in the gcloud config (gcloud config set project <id>)"
fi
METADATA="block-project-ssh-keys=TRUE,tb-demo-image=$IMAGE,tb-demo-hours=$HOURS,tb-demo-lang=$DEMO_LANG"
# gcloud splits --metadata on commas: the people go as name:role;name:role
METADATA="$METADATA,tb-demo-people=${PEOPLE//,/;},tb-demo-enrol-hours=$ENROL_HOURS,tb-demo-handoff=$HANDOFF"
[ -z "$IMAGE_SHA256" ] || METADATA="$METADATA,tb-demo-image-sha256=$IMAGE_SHA256"
[ -z "$SITE_LANG" ] || METADATA="$METADATA,tb-demo-site-lang=$SITE_LANG"
[ "$MODE" != steps ] || METADATA="$METADATA,tb-demo-mode=steps"
[ "$SHARED_PASSWORD" != 1 ] || METADATA="$METADATA,tb-demo-shared-login=1"

rules_check() {  # nothing but the VM's own rules reaches it (no SSH or port 80 added by hand, no default rule first)
  local bad
  if [ "$DRY" = 1 ]; then
    echo "+ gcloud compute firewall-rules list --filter=network~/$NET\$ --format=json   # nothing but $RULE may reach the VM"
    return 0
  fi
  bad="$(gc compute firewall-rules list --filter="network~/$NET\$" --format=json \
    | "$PY" "$HERE/demo_vm.py" rules-check "$NET" "$NETWORK" "$RULE" "$DENY" "$TAG")" \
    || die "network $NET has other firewall rules that reach the VM ($bad): delete them or give them a priority above $DENY_PRIORITY; the demo VM opens tcp:443 only"
}

up() {
  say "demo VM $N ($MACHINE, $ZONE, project $PROJECT): $REACH; hard stop $HOURS h"
  local st
  st="$(vm_status)"
  case "$st" in
    RUNNING) say "$N is already RUNNING (the rule's ranges are updated; the hard stop counts from its start)" ;;
    TERMINATED | NONE) ;;
    *) die "$N is $st; wait until it is RUNNING or TERMINATED" ;;
  esac
  local net_args
  if [ "$NETWORK" = own ]; then
    exists compute networks describe "$NET" \
      || gc compute networks create "$NET" --subnet-mode=custom --description="TrialBox demo VM: its own network (no default rules)"
    exists compute networks subnets describe "$SUBNET" --region "$REGION" \
      || gc compute networks subnets create "$SUBNET" --network "$NET" --region "$REGION" --range "$SUBNET_RANGE"
    net_args=(--subnet "$SUBNET")
  else
    # the project's own network (no networkAdmin needed); its rules (default-allow-ssh, -rdp, -icmp, -internal) target
    # every instance, so a deny-all on the VM's tag comes first: only the tcp:443 rule, of higher precedence, gets in
    if [ "$DRY" = 1 ]; then echo "+ gcloud compute networks describe $NET --format=value(name)   # the project's network must exist"
    else
      gc compute networks describe "$NET" --format='value(name)' >/dev/null 2>&1 \
        || die "the project has no network named $NET: set TB_DEMO_VM_NETWORK=own (needs roles/compute.networkAdmin)"
    fi
    exists compute firewall-rules describe "$DENY" \
      || gc compute firewall-rules create "$DENY" --network "$NET" --direction INGRESS --action DENY --rules=all \
        --source-ranges=0.0.0.0/0 --target-tags "$TAG" --priority "$DENY_PRIORITY" \
        --description="TrialBox demo VM: nothing but its tcp:443 rule reaches it (not the network's SSH or RDP rules)"
    net_args=(--network "$NET")
  fi
  # the only allow rule: tcp:443 from the given ranges (0.0.0.0/0 with TB_DEMO_ALLOW=any); no port 80, no SSH
  if exists compute firewall-rules describe "$RULE"; then
    gc compute firewall-rules update "$RULE" --rules=tcp:443 --source-ranges="$ALLOW" --priority "$ALLOW_PRIORITY"
  else
    gc compute firewall-rules create "$RULE" --network "$NET" --direction INGRESS --action ALLOW --rules=tcp:443 \
      --source-ranges="$ALLOW" --target-tags "$TAG" --priority "$ALLOW_PRIORITY" --description="$RULE_WHY"
  fi
  rules_check
  if [ "$st" = NONE ]; then
    gc compute instances create "$N" --zone "$ZONE" --machine-type "$MACHINE" \
      "${net_args[@]}" --tags "$TAG" --image-family debian-12 --image-project debian-cloud \
      --boot-disk-size "${DISK_GB}GB" --boot-disk-type pd-balanced --shielded-secure-boot \
      --provisioning-model STANDARD --max-run-duration "${HOURS}h" --instance-termination-action STOP \
      --scopes cloud-platform --labels trialbox=demo-vm \
      --metadata-from-file "startup-script=$BOOT" --metadata "$METADATA"
  elif [ "$st" = TERMINATED ]; then
    gc compute instances add-metadata "$N" --zone "$ZONE" --metadata-from-file "startup-script=$BOOT" --metadata "$METADATA"
    gc compute instances set-scheduling "$N" --zone "$ZONE" --max-run-duration "${HOURS}h" --instance-termination-action STOP
    gc compute instances start "$N" --zone "$ZONE"
  fi
  say "https://$(vm_ip)/ answers after the seed (about 10 minutes; \`demo-vm.sh status\` shows DEMO-VM-READY)"
  say "the browser warns once (Caddy's own certificate)"
  say "after DEMO-VM-READY: deploy/gcp/demo-vm.sh links prints each person's one-time link once (then deletes it);"
  say "  each person opens their link (https://<address>/enrol#u=...&c=...: the page fills the two fields) and chooses a password"
  if [ "$OPEN_ANY" = 1 ]; then say "$OPEN_TEXT"; fi
  [ -z "$MODE_TEXT" ] || say "$MODE_TEXT"
  say "it powers itself off $HOURS h after its start; stop it earlier with: deploy/gcp/demo-vm.sh down"
}

status() {
  local st
  st="$(vm_status)"
  echo "VM $N ($ZONE): $st"
  [ "$st" = NONE ] && return 0
  if [ "$DRY" = 1 ]; then
    echo "+ gcloud compute firewall-rules describe $RULE --format=yaml(sourceRanges,allowed,disabled)   # 0.0.0.0/0: $OPEN_TEXT"
    echo "+ gcloud compute instances describe $N --zone $ZONE --format=value(lastStartTimestamp)   # this boot's start"
    echo "+ gcloud compute instances get-serial-port-output $N --zone $ZONE --port 1 --start 0 --format=json   # then from each page's next, to the end"
    echo "  # the boot's lines; DEMO-VM-READY only from this boot (D-1120)"
    return 0
  fi
  local rule
  echo "rule $RULE:"
  if rule="$(gc compute firewall-rules describe "$RULE" --format='yaml(sourceRanges,allowed,disabled)' 2>/dev/null)"; then
    printf '%s\n' "$rule" | sed 's/^/  /'
    if printf '%s\n' "$rule" | grep -q '0\.0\.0\.0/0'; then echo "reach: $OPEN_TEXT"; else echo "reach: the ranges above only"; fi
  else
    echo "  none"
  fi
  echo "hard stop: $(gc compute instances describe "$N" --zone "$ZONE" \
    --format='value(scheduling.maxRunDuration.seconds,scheduling.instanceTerminationAction)' 2>/dev/null) (seconds, action)"
  if [ "$st" = RUNNING ]; then
    echo "address: https://$(vm_ip)/"
    # D-1120: the serial buffer outlives a stop and a start, so a marker counts only when it is this boot's: its id
    # (--boot-id, or the id of the boot whose first line is stamped after lastStartTimestamp), else its own stamp
    local last_start pages
    last_start="$(gc compute instances describe "$N" --zone "$ZONE" --format='value(lastStartTimestamp)' 2>/dev/null || true)"
    pages="$(mktemp -d)"
    serial_pages "$pages"
    # the boot's own lines and its marker, wherever the script runner's prefix puts them (demo_vm.py boot-state)
    echo "boot log (serial console):"
    local args=(--last-start "${last_start:-none}")
    [ -z "$BOOT_ID" ] || args+=(--boot-id "$BOOT_ID")
    local files=("$pages"/page-*)   # in order: page-001, page-002, ...
    [ -e "${files[0]}" ] || files=()
    "$PY" "$HERE/demo_vm.py" boot-state "${args[@]}" "${files[@]}"
    rm -rf "$pages"
  else
    echo "boot: the VM is $st: no ready line is read (a marker in the serial buffer is an earlier boot's)"
  fi
}

# the whole serial buffer of port 1 (where the boot's tee and the script runner write), page by page: each call
# starts at the previous page's next byte, so a buffer longer than one answer is read to its end and a line cut at a
# page's edge is joined again. Ends when a page is empty or next does not move; 64 pages is far past the 1 MB the
# console keeps (a guard against a VM that never stops writing, not a cut of a boot's output).
serial_pages() {
  local dir=$1 pos=0 i nxt f
  for i in $(seq 1 64); do
    f="$dir/page-$(printf '%03d' "$i")"
    gc compute instances get-serial-port-output "$N" --zone "$ZONE" --port 1 --start "$pos" --format=json \
      >"$f" 2>/dev/null || { rm -f "$f"; break; }
    nxt="$("$PY" "$HERE/demo_vm.py" serial-next <"$f")" || break
    [ "$nxt" -gt "$pos" ] || break
    pos=$nxt
  done
}

down() {
  local st i
  st="$(vm_status)"
  case "$st" in
    NONE) echo "VM $N: none"; return 0 ;;
    TERMINATED) echo "VM $N: TERMINATED"; return 0 ;;
    UNKNOWN) die "the status of VM $N cannot be read here; stop it in the console and check TERMINATED there" ;;
  esac
  gc compute instances stop "$N" --zone "$ZONE"
  [ "$DRY" = 1 ] && { echo "+ wait up to $STOP_WAIT_S s for TERMINATED"; return 0; }
  for i in $(seq 0 10 "$STOP_WAIT_S"); do
    st="$(vm_status)"
    [ "$st" = TERMINATED ] && { echo "VM $N: TERMINATED (the disk stays: \`delete\` ends its cost)"; return 0; }
    [ "$i" -lt "$STOP_WAIT_S" ] && sleep 10
  done
  die "VM $N is $st, not TERMINATED, $STOP_WAIT_S s after the stop: check it in the console and stop it there"
}

delete() {
  local st
  st="$(vm_status)"
  [ "$st" = NONE ] || gc compute instances delete "$N" --zone "$ZONE" --quiet
  if [ "$DRY" = 1 ] || exists compute firewall-rules describe "$RULE"; then gc compute firewall-rules delete "$RULE" --quiet; fi
  if [ "$NETWORK" = own ]; then
    if [ "$DRY" = 1 ] || exists compute networks subnets describe "$SUBNET" --region "$REGION"; then
      gc compute networks subnets delete "$SUBNET" --region "$REGION" --quiet
    fi
    if [ "$DRY" = 1 ] || exists compute networks describe "$NET"; then gc compute networks delete "$NET" --quiet; fi
  elif [ "$DRY" = 1 ] || exists compute firewall-rules describe "$DENY"; then
    gc compute firewall-rules delete "$DENY" --quiet  # the project's network itself stays
  fi
  [ "$DRY" = 1 ] && return 0
  st="$(vm_status)"
  [ "$st" = NONE ] || die "VM $N still exists ($st)"
  if [ "$NETWORK" = own ]; then
    echo "deleted: VM $N and its disk, rule $RULE, subnet $SUBNET, network $NET"
  else
    echo "deleted: VM $N and its disk, rules $RULE and $DENY (the network $NET is the project's and stays)"
  fi
}

links() {  # the links' object(s) the VM wrote: the newest printed once, then every one deleted
  local objs newest o
  if [ "$DRY" = 1 ]; then
    echo "+ gcloud storage ls $HANDOFF/enrol-*.txt"
    echo "+ gcloud storage cat <the newest>   # the one-time links, printed once"
    echo "+ gcloud storage rm <each enrol-*.txt there>"
    return 0
  fi
  objs="$(gc storage ls "$HANDOFF/enrol-*.txt" 2>/dev/null | sort || true)"
  [ -n "$objs" ] || die "no codes under $HANDOFF: the VM writes them after the seed (status shows DEMO-VM-READY), or they were read already (a new set needs down and up: a new seed)"
  newest="$(printf '%s\n' "$objs" | tail -1)"
  local text id
  text="$(gc storage cat "$newest")"
  printf '%s\n' "$text"
  # D-1120: the boot's id (random, not a secret): `status --boot-id` then reads that boot's lines only
  id="$(printf '%s\n' "$text" | sed -n 's/.*boot id \([0-9a-f]\{16\}\).*/\1/p' | head -1)"
  if [ -n "$id" ]; then echo "== boot id: $id (deploy/gcp/demo-vm.sh status --boot-id $id reads this boot only)"
  else echo "== boot id: none in the object (an image before D-1120)"; fi
  for o in $objs; do
    gc storage rm "$o" >/dev/null 2>&1 || echo "demo-vm: could not delete $o: delete it by hand" >&2
  done
  echo "== deleted from the bucket. Give each person their own line, privately; nobody else needs it."
}

"$CMD"
