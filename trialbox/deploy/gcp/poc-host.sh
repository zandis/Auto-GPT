#!/usr/bin/env bash
# TrialBox PoC host on Google Cloud (T-509, D-330; TB-POC-01 §3): one VM, two demo sites, a front door, kept data.
# Every paid step needs the owner's yes first (Q-03): without --yes a command only prints what it would run, as
# --dry-run does. Nothing here runs at import or by itself.
#
#   deploy/gcp/poc-host.sh cost                  the estimated hourly and monthly cost (prices from memory: check)
#   deploy/gcp/poc-host.sh image   [--yes] [--force]  build the demo image ONCE from tag poc-1 (a clean export of the
#                                                tag, here, never on the VM), push it, print its digest
#   deploy/gcp/poc-host.sh door    [--yes]       Cloudflare: tunnel, DNS names, Access apps for the testers' mail
#                                                addresses, one-time PIN sign-in; the tunnel token into Secret Manager
#   deploy/gcp/poc-host.sh create  [--yes]       network (SSH from IAP only), VM service account, data disk with a
#                                                daily snapshot schedule, the VM running the image by digest
#   deploy/gcp/poc-host.sh rebuild [--yes]       destroy and rebuild the VM from the tag's digest; the data disk
#                                                stays (a snapshot is taken first). One command.
#   deploy/gcp/poc-host.sh status                the VM, the image it runs, the data disk, the snapshots
#   deploy/gcp/poc-host.sh reset SITE [--yes]    empty one site's kept data; it seeds afresh (3 to 6 minutes)
#   deploy/gcp/poc-host.sh purge   [--yes] [--record FILE]   end of life: delete the VM, the data disk, every
#                                                snapshot, the schedule, the network, the image, the secrets, the
#                                                service account and the Cloudflare entries; then check that no VM,
#                                                disk or snapshot is left, and write a record
#   add --dry-run to any command: it prints every command (gcloud, docker, git, curl) and runs none
#
# Settings (environment only; nothing secret on a command line, nothing secret printed):
#   TB_POC_PROJECT     the GCP project (required)            TB_POC_REGION  asia-east1    TB_POC_ZONE  asia-east1-b
#   TB_POC_NAME        prefix of every resource (tb-poc)     TB_POC_MACHINE e2-standard-4 TB_POC_DATA_GB 20
#   TB_POC_TAG         the git tag to build (poc-1)          TB_POC_KEEP_DAYS 70 (snapshot retention)
#   TB_POC_DOMAIN      the hosts are SITE.<domain> (required for door and create)
#   TB_POC_SITES       "SITE:LANG:ZONE ..." ("jp:ja:Asia/Tokyo tw:zh-TW:Asia/Taipei")
#   TB_POC_IMAGE       optional: an image by digest to run instead of the tag's
#   gcloud credentials as for every script here: CLOUDSDK_CONFIG, TB_SA_KEY_FILE (deploy/gcp/gcloud-auth.sh)
#   door and purge:    CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_ZONE_ID, TB_POC_ACCESS_TEAM (the
#                      Zero Trust team name), TB_POC_DOOR_EMAILS (comma list; read by the script, never printed)
# Secrets the owner puts in Secret Manager before `create` (values never in the repository; demo/README.md):
#   <name>-accounts-<site> (the T-505b accounts file of each site), <name>-owner-password (optional).
#   `door` adds <name>-tunnel-token.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TB_ROOT="$(cd "$HERE/../.." && pwd)"        # trialbox/
STARTUP="$HERE/hosted-demo-startup.sh"
DRY=0; YES=0; FORCE=0; RECORD=""; CMD=""; ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --yes) YES=1 ;;
    --force) FORCE=1 ;;
    --record) RECORD="${2:?--record needs a file}"; shift ;;
    -h | --help) sed -n 2,37p "$0"; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) if [ -z "$CMD" ]; then CMD=$1; elif [ -z "$ARG" ]; then ARG=$1; else echo "too many arguments" >&2; exit 2; fi ;;
  esac
  shift
done
[ -n "$CMD" ] || { sed -n 2,37p "$0"; exit 2; }

PROJECT=${TB_POC_PROJECT:-}
REGION=${TB_POC_REGION:-asia-east1}
ZONE=${TB_POC_ZONE:-asia-east1-b}
N=${TB_POC_NAME:-tb-poc}
MACHINE=${TB_POC_MACHINE:-e2-standard-4}
DATA_GB=${TB_POC_DATA_GB:-20}
BOOT_GB=30
TAG=${TB_POC_TAG:-poc-1}
KEEP_DAYS=${TB_POC_KEEP_DAYS:-70}
DOMAIN=${TB_POC_DOMAIN:-}
SITES=${TB_POC_SITES:-"jp:ja:Asia/Tokyo tw:zh-TW:Asia/Taipei"}
IAP_RANGE=35.235.240.0/20   # Google's IAP TCP forwarding range: SSH only, and only through IAP
derive() {  # names that hold the project
  SA="$N-vm@${PROJECT:-PROJECT}.iam.gserviceaccount.com"
  IMAGE_NAME="$REGION-docker.pkg.dev/${PROJECT:-PROJECT}/$N/demo"
}
derive
CF_API=https://api.cloudflare.com/client/v4

[[ "$N" =~ ^[a-z][a-z0-9-]{1,20}$ ]] || { echo "TB_POC_NAME must be a short lower-case name" >&2; exit 2; }
SITE_NAMES=(); SECRETS=(tunnel-token owner-password)  # the secret names after "$N-"
for spec in $SITES; do SITE_NAMES+=("${spec%%:*}"); SECRETS+=("accounts-${spec%%:*}"); done

say() { echo "== $*"; }
die() { echo "poc-host: $*" >&2; exit 3; }

# a paid or destructive command without --yes is shown, never run
case "$CMD" in
  image | door | create | rebuild | reset | purge)
    if [ "$DRY" = 0 ] && [ "$YES" = 0 ]; then
      echo "poc-host: '$CMD' changes the cloud and may cost money; this is what it would run. Add --yes to run it."
      DRY=1
    fi ;;
esac

export GC_DRY="$DRY"
# shellcheck source=SCRIPTDIR/gcloud-auth.sh
. "$HERE/gcloud-auth.sh"
run() {  # a non-gcloud command, or its quoted text in a dry run
  if [ "$DRY" = 1 ]; then printf '+'; printf ' %q' "$@"; printf '\n'; else "$@"; fi
}
gq() {  # a read-only gcloud query; in a dry run it prints the call and answers $GQ_DRY (default empty)
  if [ "$DRY" = 1 ]; then echo "+ gcloud $*" >&2; printf '%s' "${GQ_DRY-}"; return 0; fi
  gcloud "$@" 2>/dev/null
}
exists() {  # exists <gcloud describe args>: in a dry run the answer is $EXISTS_DRY (0 = no, 1 = yes)
  if [ "$DRY" = 1 ]; then [ "${EXISTS_DRY:-0}" = 1 ]; return; fi
  gcloud "$@" --format='value(name)' >/dev/null 2>&1
}
need() {  # need VAR...: settings the command cannot run without (a dry run shows a placeholder)
  local v
  for v in "$@"; do
    if [ -z "${!v:-}" ]; then
      [ "$DRY" = 1 ] || die "$v is not set"
      printf -v "$v" '%s' "<$v>"
    fi
  done
  derive
}

cost() {
  # Prices from memory (USD, on demand, asia-east1, November 2026), to be checked at order (TB-PLAN-06 Q-03).
  python3 - "$MACHINE" "$DATA_GB" "$BOOT_GB" <<'PY'
import sys
machine, data_gb, boot_gb = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
vm_hour = {"e2-standard-2": 0.0764, "e2-standard-4": 0.1528, "e2-standard-8": 0.3056}.get(machine, 0.1528)
H = 730  # hours in a month
rows = [
    (f"VM {machine} (always on)", vm_hour * H),
    (f"boot disk {boot_gb:.0f} GB pd-balanced", boot_gb * 0.11),
    (f"data disk {data_gb:.0f} GB pd-balanced", data_gb * 0.11),
    ("daily snapshots (incremental; about 5 GB kept)", 5 * 0.029),
    ("external IPv4 address (in use)", 0.005 * H),
    ("image in Artifact Registry (about 0.5 GB)", 0.05),
    ("egress (two testers, a few GB)", 1.0),
    ("Secret Manager, Cloudflare Tunnel and Access (free tier, under 50 users)", 0.0),
]
month = sum(v for _, v in rows)
print("Estimated cost of the PoC host (USD; prices from memory, check at order):")
for name, v in rows:
    print(f"  {name:<72} {v:7.2f} a month")
print(f"  {'total':<72} {month:7.2f} a month, about {month / H:.3f} an hour")
print(f"  two months: about {2 * month:.0f}; a domain name about 10 a year; e2-standard-2 (8 GB) halves the VM line")
print("  a stopped VM costs only its disks and snapshots (about 5 a month)")
PY
}

resolve_image() {  # the image to run: TB_POC_IMAGE, else the digest the tag was pushed with
  local ref digest
  if [ -n "${TB_POC_IMAGE:-}" ]; then ref=$TB_POC_IMAGE; else
    digest=$(GQ_DRY="sha256:<digest of $TAG>" gq artifacts docker images describe "$IMAGE_NAME:$TAG" \
      --project "$PROJECT" --format='value(image_summary.digest)')
    [ -n "$digest" ] || die "no image $IMAGE_NAME:$TAG in the registry: run 'poc-host.sh image --yes' first"
    ref="$IMAGE_NAME@$digest"
  fi
  [ "$DRY" = 1 ] || [[ "$ref" =~ @sha256:[0-9a-f]{64}$ ]] || die "the image must be pinned by digest: $ref"
  printf '%s' "$ref"
}

make_vm() {  # create the VM on the kept data disk, running the image by digest
  local image=$1
  # one metadata value holds spaces and colons: '|' separates the entries (gcloud topic escaping)
  gc compute instances create "$N" --project "$PROJECT" --zone "$ZONE" --machine-type "$MACHINE" \
    --subnet "$N-subnet" --network-tier PREMIUM --tags "$N" --labels "tb-poc=$N" \
    --service-account "$SA" --scopes cloud-platform \
    --image-family debian-12 --image-project debian-cloud --boot-disk-size "${BOOT_GB}GB" --boot-disk-type pd-balanced \
    --disk "name=$N-data,device-name=$N-data,mode=rw,boot=no,auto-delete=no" \
    --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring \
    --metadata-from-file "startup-script=$STARTUP" \
    --metadata "^|^tb-image=$image|tb-sites=$SITES|tb-domain=$DOMAIN|tb-secret-prefix=$N|tb-data-disk=$N-data|enable-oslogin=TRUE|block-project-ssh-keys=TRUE"
}

cmd_image() {
  need PROJECT
  local repo sha
  repo="$(git -C "$TB_ROOT" rev-parse --show-toplevel)"
  if ! sha=$(git -C "$repo" rev-parse -q --verify "refs/tags/$TAG^{commit}"); then
    [ "$DRY" = 1 ] || die "no tag $TAG here (git fetch --tags first)"
    sha="<commit of $TAG>"; echo "(dry run: tag $TAG is not here yet)"
  fi
  if [ "$FORCE" = 0 ] && exists artifacts docker images describe "$IMAGE_NAME:$TAG" --project "$PROJECT"; then
    die "$IMAGE_NAME:$TAG exists: the image is built once (--force builds and pushes a new digest)"
  fi
  say "build $TAG ($sha) from a clean export of the tag, here; the VM never builds"
  exists artifacts repositories describe "$N" --location "$REGION" --project "$PROJECT" || \
    gc artifacts repositories create "$N" --project "$PROJECT" --location "$REGION" --repository-format docker \
      --labels "tb-poc=$N" --description "TrialBox PoC demo image (T-509)"
  if [ "$DRY" = 1 ]; then BUILD_DIR="<a new temporary folder>"; else BUILD_DIR="$(mktemp -d)"; trap 'rm -rf "$BUILD_DIR"' EXIT; fi
  if [ "$DRY" = 1 ]; then echo "+ git -C $repo archive $TAG trialbox | tar -x -C $BUILD_DIR"; else
    git -C "$repo" archive "$TAG" trialbox | tar -x -C "$BUILD_DIR"
  fi
  run docker build -f "$BUILD_DIR/trialbox/demo/Dockerfile" --label "org.opencontainers.image.revision=$sha" \
    --label "org.opencontainers.image.version=$TAG" -t "$IMAGE_NAME:$TAG" "$BUILD_DIR/trialbox"
  gc auth configure-docker "$REGION-docker.pkg.dev" --quiet
  run docker push "$IMAGE_NAME:$TAG"
  say "pushed; the VM runs it by digest: $(resolve_image)"
}

cf() {  # cf METHOD PATH [JSON]: one Cloudflare API call; the token goes in a header read from a pipe, never argv
  local m=$1 p=$2 body=${3-}
  if [ "$DRY" = 1 ]; then
    echo "+ curl -X $m $CF_API$p${body:+ --data '$body'} (Authorization from CLOUDFLARE_API_TOKEN)" >&2
    printf '{"success": true, "result": %s}' "${CF_DRY:-[]}"
    return 0
  fi
  local args=(-sS --fail-with-body -X "$m" -H @- -H 'Content-Type: application/json')
  [ -z "$body" ] || args+=(--data "$body")
  printf 'Authorization: Bearer %s\n' "$CLOUDFLARE_API_TOKEN" | curl "${args[@]}" "$CF_API$p"
}
jget() {  # jget PYTHON-EXPRESSION < JSON: a value from a Cloudflare answer (r = the parsed answer)
  python3 -c 'import json, sys
r = json.load(sys.stdin)
if not r.get("success", False):
    sys.exit("cloudflare: " + json.dumps(r.get("errors")))
v = eval(sys.argv[1], {"r": r})
sys.stdout.write("" if v is None else str(v))' "$1"
}
emails_json() {  # the Access rule list from TB_POC_DOOR_EMAILS, built in Python from the environment (never argv)
  python3 -c 'import json, os
es = [e.strip() for e in os.environ.get("TB_POC_DOOR_EMAILS", "").split(",") if e.strip()]
if not es: raise SystemExit("TB_POC_DOOR_EMAILS is empty")
print(json.dumps([{"email": {"email": e}} for e in es]))'
}

cmd_door() {
  need CLOUDFLARE_ACCOUNT_ID CLOUDFLARE_ZONE_ID TB_POC_ACCESS_TEAM DOMAIN PROJECT
  [ "$DRY" = 1 ] || [ -n "${CLOUDFLARE_API_TOKEN:-}" ] || die "CLOUDFLARE_API_TOKEN is not set"
  local acc="/accounts/$CLOUDFLARE_ACCOUNT_ID" tid apps app aud pol ingress="" s host rec include n_emails
  if [ "$DRY" = 1 ]; then
    n_emails=$(TB_POC_DOOR_EMAILS=${TB_POC_DOOR_EMAILS:-} python3 -c 'import os; print(len([e for e in os.environ["TB_POC_DOOR_EMAILS"].split(",") if e.strip()]))')
    include="[<$n_emails addresses from TB_POC_DOOR_EMAILS>]"
  else include=$(emails_json); fi

  say "sign-in by one-time PIN to the testers' mail addresses (no account needed)"
  if [ -z "$(cf GET "$acc/access/identity_providers" | jget '",".join(x["id"] for x in r["result"] if x["type"] == "onetimepin")')" ]; then
    CF_DRY='{"id": "<idp id>"}' cf POST "$acc/access/identity_providers" '{"name": "One-time PIN", "type": "onetimepin", "config": {}}' | jget 'r["result"]["id"]' >/dev/null
  fi

  say "tunnel $N (outbound from the VM; no inbound port)"
  tid=$(cf GET "$acc/cfd_tunnel?name=$N&is_deleted=false" | jget 'r["result"][0]["id"] if r["result"] else ""')
  [ -n "$tid" ] || tid=$(CF_DRY='{"id": "<tunnel id>"}' cf POST "$acc/cfd_tunnel" "{\"name\": \"$N\", \"config_src\": \"cloudflare\"}" | jget 'r["result"]["id"]')

  apps=$(cf GET "$acc/access/apps")
  for s in "${SITE_NAMES[@]}"; do
    host="$s.$DOMAIN"
    say "front door for $host: Cloudflare Access, the listed addresses only, 24-hour session"
    app=$(printf '%s' "$apps" | jget "next((x['id'] for x in r['result'] if x.get('domain') == '$host'), '')")
    if [ -z "$app" ]; then
      app=$(CF_DRY='{"id": "<app id>", "aud": "<aud>"}' cf POST "$acc/access/apps" "{\"name\": \"TrialBox PoC $s\", \"domain\": \"$host\", \"type\": \"self_hosted\", \"session_duration\": \"24h\", \"app_launcher_visible\": false}" | jget 'r["result"]["id"]')
    fi
    aud=$(CF_DRY='{"aud": "<aud>"}' cf GET "$acc/access/apps/$app" | jget 'r["result"]["aud"]')
    pol=$(cf GET "$acc/access/apps/$app/policies" | jget "next((x['id'] for x in r['result'] if x.get('name') == 'testers'), '')")
    local body="{\"name\": \"testers\", \"decision\": \"allow\", \"precedence\": 1, \"include\": $include}"
    if [ -n "$pol" ]; then cf PUT "$acc/access/apps/$app/policies/$pol" "$body" >/dev/null
    else cf POST "$acc/access/apps/$app/policies" "$body" >/dev/null; fi
    # cloudflared refuses a request without a valid Access token for this app before it reaches Caddy
    ingress+="{\"hostname\": \"$host\", \"service\": \"https://127.0.0.1:443\", \"originRequest\": {\"originServerName\": \"$host\", \"caPool\": \"/etc/trialbox/caddy-root.crt\", \"access\": {\"required\": true, \"teamName\": \"$TB_POC_ACCESS_TEAM\", \"audTag\": [\"$aud\"]}}}, "
    rec=$(cf GET "/zones/$CLOUDFLARE_ZONE_ID/dns_records?type=CNAME&name=$host" | jget 'r["result"][0]["id"] if r["result"] else ""')
    local dns="{\"type\": \"CNAME\", \"name\": \"$host\", \"content\": \"$tid.cfargotunnel.com\", \"proxied\": true}"
    if [ -n "$rec" ]; then cf PUT "/zones/$CLOUDFLARE_ZONE_ID/dns_records/$rec" "$dns" >/dev/null
    else cf POST "/zones/$CLOUDFLARE_ZONE_ID/dns_records" "$dns" >/dev/null; fi
  done
  say "tunnel routes: each host to Caddy on the VM; anything else 404"
  cf PUT "$acc/cfd_tunnel/$tid/configurations" "{\"config\": {\"ingress\": [${ingress}{\"service\": \"http_status:404\"}]}}" >/dev/null

  say "the tunnel token into Secret Manager ($N-tunnel-token), straight from the API, never shown"
  exists secrets describe "$N-tunnel-token" --project "$PROJECT" || \
    gc secrets create "$N-tunnel-token" --project "$PROJECT" --replication-policy user-managed --locations "$REGION" --labels "tb-poc=$N"
  if [ "$DRY" = 1 ]; then
    echo "+ curl -X GET $CF_API$acc/cfd_tunnel/$tid/token | gcloud secrets versions add $N-tunnel-token --data-file=- (value never printed)"
  else
    cf GET "$acc/cfd_tunnel/$tid/token" | jget 'r["result"]' | gcloud secrets versions add "$N-tunnel-token" --project "$PROJECT" --data-file=- >/dev/null
  fi
}

cmd_create() {
  need PROJECT DOMAIN
  cost
  local image s
  image=$(resolve_image)
  say "APIs"
  gc services enable compute.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com iap.googleapis.com --project "$PROJECT"
  say "the secrets the VM reads (their values are put there by the owner, never by this script)"
  for s in "${SITE_NAMES[@]}"; do
    exists secrets describe "$N-accounts-$s" --project "$PROJECT" || [ "$DRY" = 1 ] || \
      die "secret $N-accounts-$s is missing: gcloud secrets create $N-accounts-$s --data-file=<the accounts file of $s> (demo/README.md)"
  done
  exists secrets describe "$N-tunnel-token" --project "$PROJECT" || [ "$DRY" = 1 ] || die "secret $N-tunnel-token is missing: run 'poc-host.sh door --yes' first"
  say "network $N-net: no inbound web port; SSH only from Google's IAP range (port 80 and 443 closed)"
  exists compute networks describe "$N-net" --project "$PROJECT" || \
    gc compute networks create "$N-net" --project "$PROJECT" --subnet-mode custom
  exists compute networks subnets describe "$N-subnet" --region "$REGION" --project "$PROJECT" || \
    gc compute networks subnets create "$N-subnet" --project "$PROJECT" --network "$N-net" --region "$REGION" --range 10.90.0.0/24
  exists compute firewall-rules describe "$N-allow-iap-ssh" --project "$PROJECT" || \
    gc compute firewall-rules create "$N-allow-iap-ssh" --project "$PROJECT" --network "$N-net" --direction INGRESS \
      --action allow --rules tcp:22 --source-ranges "$IAP_RANGE" --target-tags "$N"
  say "service account $SA: reads its own secrets and the image, nothing else"
  exists iam service-accounts describe "$SA" --project "$PROJECT" || \
    gc iam service-accounts create "$N-vm" --project "$PROJECT" --display-name "TrialBox PoC VM (T-509)"
  for s in "${SECRETS[@]}"; do
    exists secrets describe "$N-$s" --project "$PROJECT" || [ "$DRY" = 1 ] || continue  # owner-password is optional
    gc secrets add-iam-policy-binding "$N-$s" --project "$PROJECT" --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor
  done
  gc artifacts repositories add-iam-policy-binding "$N" --project "$PROJECT" --location "$REGION" \
    --member "serviceAccount:$SA" --role roles/artifactregistry.reader
  say "data disk $N-data with a daily snapshot (17:00 UTC = 01:00 Taipei, 02:00 Tokyo), kept $KEEP_DAYS days"
  exists compute resource-policies describe "$N-daily" --region "$REGION" --project "$PROJECT" || \
    gc compute resource-policies create snapshot-schedule "$N-daily" --project "$PROJECT" --region "$REGION" \
      --daily-schedule --start-time 17:00 --max-retention-days "$KEEP_DAYS" \
      --on-source-disk-delete keep-auto-snapshots --storage-location "$REGION" --snapshot-labels "tb-poc=$N"
  exists compute disks describe "$N-data" --zone "$ZONE" --project "$PROJECT" || \
    gc compute disks create "$N-data" --project "$PROJECT" --zone "$ZONE" --size "${DATA_GB}GB" --type pd-balanced \
      --labels "tb-poc=$N" --resource-policies "$N-daily"
  say "VM $N ($MACHINE) running $image"
  exists compute instances describe "$N" --zone "$ZONE" --project "$PROJECT" && die "VM $N exists: use rebuild"
  make_vm "$image"
  say "the first start seeds each site (3 to 6 minutes); then https://<site>.$DOMAIN behind the front door"
}

cmd_rebuild() {
  need PROJECT DOMAIN
  local image stamp
  image=$(resolve_image)
  stamp=$(date -u +%Y%m%d-%H%M%S)
  say "destroy and rebuild $N from $image; the data disk $N-data stays"
  gc compute disks snapshot "$N-data" --project "$PROJECT" --zone "$ZONE" --snapshot-names "$N-pre-rebuild-$stamp" \
    --labels "tb-poc=$N" --storage-location "$REGION"
  if EXISTS_DRY=1 exists compute instances describe "$N" --zone "$ZONE" --project "$PROJECT"; then
    gc compute instances delete "$N" --project "$PROJECT" --zone "$ZONE" --keep-disks data --quiet
  fi
  make_vm "$image"
  say "rebuilt; the sites reopen their kept data (no reseed)"
}

cmd_status() {
  need PROJECT
  gc compute instances describe "$N" --project "$PROJECT" --zone "$ZONE" \
    --format 'table(name,status,machineType.basename(),metadata.items.tb-image)' || true
  gc compute disks describe "$N-data" --project "$PROJECT" --zone "$ZONE" --format 'table(name,sizeGb,status,resourcePolicies.basename())' || true
  gc compute snapshots list --project "$PROJECT" --filter "labels.tb-poc=$N" --format 'table(name,creationTimestamp,storageBytes)' || true
}

cmd_reset() {
  need PROJECT
  [ -n "$ARG" ] || die "reset needs a site: one of ${SITE_NAMES[*]}"
  printf '%s\n' "${SITE_NAMES[@]}" | grep -qx -- "$ARG" || die "no site '$ARG' (sites: ${SITE_NAMES[*]})"
  say "reset site $ARG: its marks, notes and accounts are deleted; it seeds afresh"
  gc compute ssh "$N" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap \
    --command "sudo bash /opt/trialbox-poc/host.sh --reset-site $ARG"
}

cmd_purge() {
  need PROJECT
  local stamp line s snaps left=0 found
  stamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  if [ "$DRY" = 0 ]; then
    RECORD=${RECORD:-"$PWD/trialbox-poc-purge-$(date -u +%Y%m%d-%H%M%S).txt"}
    : >"$RECORD" || die "cannot write the record $RECORD"
  fi
  rec() {  # one line of the record (a dry run marks its lines: nothing was deleted)
    if [ "$DRY" = 1 ]; then echo "[dry run] $*"; else echo "$*"; echo "$*" >>"$RECORD"; fi
  }
  rec "TrialBox PoC host purge (T-509), project $PROJECT, prefix $N, started $stamp"
  echo "Export the feedback first (it is kept without names, TB-POC-01 §3); the purge cannot be undone."
  export EXISTS_DRY=1
  if exists compute instances describe "$N" --zone "$ZONE" --project "$PROJECT"; then
    gc compute instances delete "$N" --project "$PROJECT" --zone "$ZONE" --delete-disks all --quiet && rec "deleted VM $N and its boot disk"
  fi
  if exists compute disks describe "$N-data" --zone "$ZONE" --project "$PROJECT"; then
    gc compute disks delete "$N-data" --project "$PROJECT" --zone "$ZONE" --quiet && rec "deleted data disk $N-data"
  fi
  snaps=$(GQ_DRY="<snapshot-of-the-list>" gq compute snapshots list --project "$PROJECT" \
    --filter "labels.tb-poc=$N OR sourceDisk~/disks/$N-data\$" --format 'value(name)')
  for s in $snaps; do gc compute snapshots delete "$s" --project "$PROJECT" --quiet && rec "deleted snapshot $s"; done
  if exists compute resource-policies describe "$N-daily" --region "$REGION" --project "$PROJECT"; then
    gc compute resource-policies delete "$N-daily" --project "$PROJECT" --region "$REGION" --quiet && rec "deleted snapshot schedule $N-daily"
  fi
  if exists compute firewall-rules describe "$N-allow-iap-ssh" --project "$PROJECT"; then
    gc compute firewall-rules delete "$N-allow-iap-ssh" --project "$PROJECT" --quiet && rec "deleted firewall rule $N-allow-iap-ssh"
  fi
  if exists compute networks subnets describe "$N-subnet" --region "$REGION" --project "$PROJECT"; then
    gc compute networks subnets delete "$N-subnet" --project "$PROJECT" --region "$REGION" --quiet && rec "deleted subnet $N-subnet"
  fi
  if exists compute networks describe "$N-net" --project "$PROJECT"; then
    gc compute networks delete "$N-net" --project "$PROJECT" --quiet && rec "deleted network $N-net"
  fi
  if exists artifacts repositories describe "$N" --location "$REGION" --project "$PROJECT"; then
    gc artifacts repositories delete "$N" --project "$PROJECT" --location "$REGION" --quiet && rec "deleted image repository $N"
  fi
  for s in "${SECRETS[@]}"; do
    if exists secrets describe "$N-$s" --project "$PROJECT"; then
      gc secrets delete "$N-$s" --project "$PROJECT" --quiet && rec "deleted secret $N-$s"
    fi
  done
  if exists iam service-accounts describe "$SA" --project "$PROJECT"; then
    gc iam service-accounts delete "$SA" --project "$PROJECT" --quiet && rec "deleted service account $N-vm"
  fi
  if [ -n "${CLOUDFLARE_API_TOKEN:-}${CLOUDFLARE_ACCOUNT_ID:-}" ] || [ "$DRY" = 1 ]; then
    purge_cloudflare
  else
    rec "Cloudflare entries not touched (no CLOUDFLARE_* settings): delete tunnel $N, its DNS names and Access apps by hand"
  fi

  say "check: nothing of the PoC host is left"
  for line in "instances list --filter=labels.tb-poc=$N" "disks list --filter=labels.tb-poc=$N OR name~^$N-" \
    "snapshots list --filter=labels.tb-poc=$N OR sourceDisk~/disks/$N-data\$"; do
    read -r kind _ filter <<<"$line"
    found=$(gq compute "$kind" list --project "$PROJECT" "$filter" --format 'value(name)' | grep -c . || true)
    rec "left: $found ${kind}"
    [ "$found" = 0 ] || left=1
  done
  if [ "$left" = 0 ]; then rec "PURGED: no VM, no disk, no snapshot left ($(date -u +%Y-%m-%dT%H:%M:%SZ))"; else
    rec "NOT CLEAN: something is left (see above)"; exit 4; fi
  [ "$DRY" = 1 ] || echo "record: $RECORD (keep it with the PoC record; it holds no name and no secret)"
}

purge_cloudflare() {
  need CLOUDFLARE_ACCOUNT_ID CLOUDFLARE_ZONE_ID DOMAIN
  local acc="/accounts/$CLOUDFLARE_ACCOUNT_ID" s host id tid
  for s in "${SITE_NAMES[@]}"; do
    host="$s.$DOMAIN"
    id=$(CF_DRY='[{"id": "<dns record id>"}]' cf GET "/zones/$CLOUDFLARE_ZONE_ID/dns_records?type=CNAME&name=$host" | jget 'r["result"][0]["id"] if r["result"] else ""')
    [ -z "$id" ] || { cf DELETE "/zones/$CLOUDFLARE_ZONE_ID/dns_records/$id" >/dev/null && rec "deleted DNS name $host"; }
    id=$(CF_DRY="[{\"id\": \"<app id>\", \"domain\": \"$host\"}]" cf GET "$acc/access/apps" | jget "next((x['id'] for x in r['result'] if x.get('domain') == '$host'), '')")
    [ -z "$id" ] || { cf DELETE "$acc/access/apps/$id" >/dev/null && rec "deleted Access app for $host"; }
  done
  tid=$(CF_DRY='[{"id": "<tunnel id>"}]' cf GET "$acc/cfd_tunnel?name=$N&is_deleted=false" | jget 'r["result"][0]["id"] if r["result"] else ""')
  [ -z "$tid" ] || { cf DELETE "$acc/cfd_tunnel/$tid?cascade=true" >/dev/null && rec "deleted tunnel $N"; }
}

case "$CMD" in
  cost) cost ;;
  image) cmd_image ;;
  door) cmd_door ;;
  create) cmd_create ;;
  rebuild) cmd_rebuild ;;
  status) cmd_status ;;
  reset) cmd_reset ;;
  purge) cmd_purge ;;
  *) echo "unknown command: $CMD" >&2; sed -n 2,37p "$0" >&2; exit 2 ;;
esac
