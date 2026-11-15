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
#   deploy/gcp/demo-vm.sh status           the VM, its address, the rule's ranges, the hard stop, the boot log's end
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
#   TB_DEMO_VM_IMAGE      required for up: REGISTRY/PATH@sha256:<digest>, or gs://BUCKET/trialbox-demo.tar.gz with
#                         TB_DEMO_VM_IMAGE_SHA256
#   TB_DEMO_VM_NAME tb-demo-vm  TB_DEMO_VM_ZONE asia-east1-a  TB_DEMO_VM_MACHINE e2-standard-4  TB_DEMO_VM_DISK_GB 30
#   TB_DEMO_VM_HOURS 12 (the hard stop of each up)  TB_DEMO_VM_SM_NAME tb-demo-password  TB_DEMO_LANG ja
#   TB_DEMO_SITE_LANG (unset: both campuses)  TB_DEMO_VM_PRICE_* (the estimate)  TB_DEMO_VM_STOP_WAIT_S 300
#   gcloud: a private CLOUDSDK_CONFIG (the default ~/.config/gcloud is refused) and TB_SA_KEY_FILE, the key file's
#   PATH (gcloud reads it; nothing here does), as deploy/gcp/complete-run.sh; the project is the gcloud config's.
# Never: a GPU, a real model (TB_LLM_MODE other than stub is refused), port 80, SSH, a password in the metadata.
# The password: the demo's own sign-in, from Secret Manager (TB_DEMO_VM_SM_NAME); the VM reads it, nothing here does.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BOOT="$HERE/demo-vm-boot.sh"
PY="${PY:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY=python3
DRY=0; YES=0; ESTIMATE=0; CMD=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --yes) YES=1 ;;
    --estimate) ESTIMATE=1 ;;
    -h | --help) sed -n 2,30p "$0"; exit 0 ;;
    up | status | down | delete) [ -z "$CMD" ] || { echo "one command only" >&2; exit 2; }; CMD=$1 ;;
    *) echo "unknown argument: $1" >&2; sed -n 2,30p "$0" >&2; exit 2 ;;
  esac
  shift
done

if [ "$ESTIMATE" = 1 ]; then exec "$PY" "$HERE/demo_vm.py" estimate; fi
if [ -z "$CMD" ]; then
  [ "$DRY" = 1 ] || { sed -n 2,30p "$0" >&2; exit 2; }
  CMD=up
fi
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
N=""; NETWORK=""; ALLOW_PRIORITY=""; DENY_PRIORITY=""; ZONE=""; REGION=""; MACHINE=""; DISK_GB=""; HOURS=""; ALLOW=""; IMAGE=""; IMAGE_SHA256=""; SECRET=""
DEMO_LANG=""; SITE_LANG=""; STOP_WAIT_S=""; OPEN_ANY=0; GATE=""
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
METADATA="block-project-ssh-keys=TRUE,tb-demo-image=$IMAGE,tb-demo-hours=$HOURS,tb-demo-password-secret=$SECRET,tb-demo-lang=$DEMO_LANG"
[ -z "$IMAGE_SHA256" ] || METADATA="$METADATA,tb-demo-image-sha256=$IMAGE_SHA256"
[ -z "$SITE_LANG" ] || METADATA="$METADATA,tb-demo-site-lang=$SITE_LANG"

password_check() {  # the secret has an enabled version; its value is never read here (only version names)
  local out
  if [ "$DRY" = 1 ]; then
    echo "+ gcloud secrets versions list $SECRET --project $PROJECT --filter=state:enabled --format=value(name)   # a version exists (names only)"
    return 0
  fi
  if ! out="$(gc secrets versions list "$SECRET" --project "$PROJECT" --filter=state:enabled --format='value(name)' 2>/dev/null)"; then
    echo "demo-vm: cannot list the versions of $SECRET here (the deployer needs roles/secretmanager.viewer on it);" \
         "the VM refuses to start the demo if it has none" >&2
    return 0
  fi
  [ -n "$out" ] || die "secret $SECRET has no version: the owner sets the password in his own shell (runbook 11, 'The small demo VM')"
}

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
  password_check
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
  say "https://$(vm_ip)/ answers after the seed (3 to 6 minutes; \`demo-vm.sh status\` shows DEMO-VM-READY)"
  say "the browser warns once (Caddy's own certificate); the password: runbook 11, never here"
  if [ "$OPEN_ANY" = 1 ]; then say "$OPEN_TEXT"; fi
  say "it powers itself off $HOURS h after its start; stop it earlier with: deploy/gcp/demo-vm.sh down"
}

status() {
  local st
  st="$(vm_status)"
  echo "VM $N ($ZONE): $st"
  [ "$st" = NONE ] && return 0
  if [ "$DRY" = 1 ]; then
    echo "+ gcloud compute firewall-rules describe $RULE --format=yaml(sourceRanges,allowed,disabled)   # 0.0.0.0/0: $OPEN_TEXT"
    echo "+ gcloud compute instances get-serial-port-output $N --zone $ZONE   # the TB-DEMO-VM lines only"
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
    gc compute instances get-serial-port-output "$N" --zone "$ZONE" 2>/dev/null \
      | grep -E '^(TB-DEMO-VM|DEMO-VM-)' | tail -8 || true
  fi
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
    echo "deleted: VM $N and its disk, rule $RULE, subnet $SUBNET, network $NET (the secret $SECRET stays)"
  else
    echo "deleted: VM $N and its disk, rules $RULE and $DENY (the network $NET is the project's and stays; the secret $SECRET stays)"
  fi
}

"$CMD"
