#!/bin/bash
# TrialBox PoC host: the startup script of the PoC VM (T-509, D-330; TB-POC-01 §3). Made and given to the VM by
# deploy/gcp/poc-host.sh; it runs at every boot. It never builds and never clones: it runs the demo image by digest.
#
#   the image   metadata tb-image, REGISTRY/PATH@sha256:<64 hex> (built once from tag poc-1 by `poc-host.sh image`);
#               anything without a digest is refused. Caddy and cloudflared are pinned by digest too.
#   the sites   metadata tb-sites, "SITE:LANG:ZONE SITE:LANG:ZONE" (default "jp:ja:Asia/Tokyo tw:zh-TW:Asia/Taipei");
#               one container per site, on 127.0.0.1:8081, 8082, ... and the host name SITE.<tb-domain>
#   the data    the persistent disk tb-data-disk (default tb-poc-data) on /srv/trialbox; each site keeps its demo
#               folder there (TB_DEMO_KEEP=1, T-505b), so a restart or a rebuild of the VM keeps the testers' work.
#               The disk is formatted only when it has no file system. A daily snapshot schedule sits on the disk.
#   the door    Cloudflare Access in front of a Cloudflare Tunnel (cloudflared, outbound only): the VM takes no
#               inbound web traffic at all (its network allows only SSH from Google's IAP range). cloudflared checks
#               the Access token before it forwards; Caddy then refuses any request without it, so nothing reaches
#               /login without a front-door session.
#   TLS         the browser gets the public certificate of the real host name at the Cloudflare edge; the tunnel
#               reaches Caddy over TLS (Caddy's own CA, `tls internal`, checked by cloudflared). Secure cookies on.
#   secrets     from Secret Manager with the VM's own service account, into root-only files: <prefix>-tunnel-token,
#               <prefix>-accounts-<site> (the T-505b accounts file), <prefix>-owner-password (optional). Never put
#               in metadata, never on a command line, never printed.
#
#   hosted-demo-startup.sh                     (the boot run, as root)
#   hosted-demo-startup.sh --reset-site SITE   (empty one site's folder and start it again: it seeds afresh)
#   hosted-demo-startup.sh --dry-run           (print what it would do; metadata from TB_MD_<KEY>, e.g. TB_MD_TB_IMAGE)
#   hosted-demo-startup.sh --print-caddyfile   (print the Caddyfile only; CI validates it with caddy)
#
# It replaces the build-on-boot click-through layout (sslip.io, a git clone and `docker build` on the VM, Caddy by a
# moving tag; OPS-008). The public-data site (tools.public_e2e) is not on the PoC host (D-330).
set -euo pipefail

usage() { sed -n 2,26p "$0"; }
DRY=0; PRINT_CADDY=0; RESET_SITE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --print-caddyfile) PRINT_CADDY=1; DRY=1 ;;
    --reset-site) RESET_SITE="${2:?--reset-site needs a site name}"; shift ;;
    -h | --help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
[ "${TB_HOST_DRY_RUN:-0}" = 1 ] && DRY=1

# pinned by digest (OPS-008); a metadata value may replace them, but only with another digest
CADDY_IMAGE_PIN="caddy:2.11.9@sha256:0c2243efcf437ab7f7a978f1027fcf0d4f9be8a75df27b1b3fbc5dbe0ffa8cf0"
CLOUDFLARED_IMAGE_PIN="cloudflare/cloudflared:2026.10.7@sha256:4955524aeaa379e154023d5a027c250f7b35041a2e7e950cf13f144bc9b9c5ba"
DATA=/srv/trialbox          # the persistent disk
ETC=/etc/trialbox-poc       # root-only: env files, the accounts files, the tunnel token
SELF=/opt/trialbox-poc/host.sh
APP_UID=1000                # the demo image's user `tb`
MD=http://metadata.google.internal/computeMetadata/v1

say() { echo "=== $(date -u +%H:%M:%S) $*"; }
die() { echo "poc-host startup: $*" >&2; exit 3; }
run() {  # a command, or its quoted text in a dry run
  if [ "$DRY" = 1 ]; then printf '+'; printf ' %q' "$@"; printf '\n'; else "$@"; fi
}
md() {  # md KEY [DEFAULT]: an instance metadata value; in a dry run the environment variable TB_MD_<KEY>
  local key=$1 def=${2-} var
  if [ "$DRY" = 1 ]; then
    var="TB_MD_$(printf '%s' "$key" | tr 'a-z-' 'A-Z_')"
    printf '%s' "${!var:-$def}"
    return 0
  fi
  curl -sf -H Metadata-Flavor:Google "$MD/instance/attributes/$key" || printf '%s' "$def"
}
gone() {  # gone NAME: remove a container if there is one (quiet)
  if [ "$DRY" = 1 ]; then echo "+ docker rm -f $1"; else docker rm -f "$1" >/dev/null 2>&1 || true; fi
}
pinned() {  # pinned REF: true when REF names a sha256 digest
  [[ "$1" =~ @sha256:[0-9a-f]{64}$ ]]
}

[ "$DRY" = 1 ] || exec > >(tee -a /var/log/trialbox-poc.log /dev/ttyS0) 2>&1

IMAGE=$(md tb-image "")
SITES=$(md tb-sites "jp:ja:Asia/Tokyo tw:zh-TW:Asia/Taipei")
DOMAIN=$(md tb-domain "")
PREFIX=$(md tb-secret-prefix tb-poc)
DISK=$(md tb-data-disk tb-poc-data)
CADDY_IMAGE=$(md tb-caddy-image "$CADDY_IMAGE_PIN")
CLOUDFLARED_IMAGE=$(md tb-cloudflared-image "$CLOUDFLARED_IMAGE_PIN")
if [ "$DRY" = 1 ]; then PROJECT=${TB_MD_PROJECT_ID:-"<project>"}; else
  PROJECT=$(curl -sf -H Metadata-Flavor:Google "$MD/project/project-id")
fi

[ -n "$DOMAIN" ] || die "metadata tb-domain is empty (the host names are SITE.<tb-domain>)"
[[ "$DOMAIN" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]] || die "metadata tb-domain is not a host name: $DOMAIN"
[[ "$PREFIX" =~ ^[a-z][a-z0-9-]*$ ]] || die "metadata tb-secret-prefix is not a plain name: $PREFIX"

# the sites, in order: name, language, zone, local port
SITE_NAMES=(); SITE_LANGS=(); SITE_ZONES=(); SITE_PORTS=()
port=8081
for spec in $SITES; do
  IFS=: read -r s l z <<<"$spec"
  [[ "$s" =~ ^[a-z][a-z0-9-]{0,15}$ ]] || die "site name '$s' in tb-sites is not a plain name"
  case "$l" in ja | zh-TW | en) ;; *) die "site $s: language '$l' is not ja, zh-TW or en" ;; esac
  [[ "$z" =~ ^[A-Za-z_]+/[A-Za-z_]+$ ]] || die "site $s: zone '$z' is not an Area/City zone"
  SITE_NAMES+=("$s"); SITE_LANGS+=("$l"); SITE_ZONES+=("$z"); SITE_PORTS+=("$port")
  port=$((port + 1))
done
[ "${#SITE_NAMES[@]}" -gt 0 ] || die "metadata tb-sites names no site"

caddyfile() {  # the Caddyfile: every site refuses a request that has no front-door token, before the console
  printf '{\n\tadmin off\n\tauto_https disable_redirects\n\tskip_install_trust\n}\n'
  local i
  for i in "${!SITE_NAMES[@]}"; do
    cat <<CF

${SITE_NAMES[$i]}.$DOMAIN {
	bind 127.0.0.1
	tls internal
	# defence in depth behind the tunnel: no Cloudflare Access token, no console (OPS-003)
	@nodoor header !Cf-Access-Jwt-Assertion
	respond @nodoor "TrialBox PoC: sign in through the front door first." 403
	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options nosniff
		Referrer-Policy same-origin
		-Server
	}
	reverse_proxy 127.0.0.1:${SITE_PORTS[$i]}
}
CF
  done
}

if [ "$PRINT_CADDY" = 1 ]; then caddyfile; exit 0; fi

write_file() {  # write_file PATH MODE OWNER < content (non-secret content only: a dry run prints it)
  local path=$1 mode=$2 owner=$3
  if [ "$DRY" = 1 ]; then echo "+ write $path (mode $mode, owner $owner):"; sed 's/^/    | /'; return 0; fi
  local tmp="$path.tmp.$$"
  (umask 077; cat >"$tmp")
  chown "$owner" "$tmp"; chmod "$mode" "$tmp"; mv -f "$tmp" "$path"
}

secret_to_file() {  # secret_to_file SECRET PATH OWNER [ENVNAME]: a Secret Manager value into a 0400 file, never shown
  local name=$1 path=$2 owner=$3 envname=${4-}
  if [ "$DRY" = 1 ]; then
    echo "+ gcloud secrets versions access latest --secret=$name --project=$PROJECT > $path${envname:+ (as $envname=...)} (mode 0400, owner $owner; the value is never printed)"
    return 0
  fi
  local tmp="$path.tmp.$$"
  (
    umask 077
    { [ -z "$envname" ] || printf '%s=' "$envname"; gcloud secrets versions access latest --secret="$name" --project="$PROJECT"; } >"$tmp"
  ) || { rm -f "$tmp"; die "secret $name could not be read (does it exist, and may the VM's service account read it?)"; }
  chown "$owner" "$tmp"; chmod 0400 "$tmp"; mv -f "$tmp" "$path"
}

secret_exists() {
  [ "$DRY" = 1 ] && return 0
  gcloud secrets describe "$1" --project="$PROJECT" >/dev/null 2>&1
}

mount_data() {
  local dev="/dev/disk/by-id/google-$DISK"
  if [ "$DRY" = 1 ]; then
    echo "+ mount $dev on $DATA (ext4, formatted only when blkid finds no file system on it; fstab entry with nofail)"
    return 0
  fi
  [ -b "$dev" ] || die "the data disk $dev is not attached"
  blkid "$dev" >/dev/null 2>&1 || mkfs.ext4 -q -m 0 -L tb-poc-data "$dev"  # a new, empty disk only
  mkdir -p "$DATA"
  mountpoint -q "$DATA" || mount -o discard,defaults "$dev" "$DATA"
  grep -q " $DATA " /etc/fstab || echo "$dev $DATA ext4 discard,defaults,nofail 0 2" >>/etc/fstab
}

site_index() {  # site_index NAME: its index in SITE_NAMES, or fail
  local i
  for i in "${!SITE_NAMES[@]}"; do [ "${SITE_NAMES[$i]}" = "$1" ] && { echo "$i"; return 0; }; done
  return 1
}

start_site() {  # start_site INDEX: (re)create the site's container on its kept folder; never wipes it
  local i=$1 s=${SITE_NAMES[$1]} owner_env="" extra
  run install -d -m 0750 -o "$APP_UID" -g "$APP_UID" "$DATA/$s"
  secret_to_file "$PREFIX-accounts-$s" "$ETC/accounts-$s.json" "$APP_UID"
  extra=$(md "tb-site-env-$s" "")
  while IFS= read -r line; do  # non-secret extra settings for one site (e.g. its scenario), KEY=VALUE per line
    [ -z "$line" ] && continue
    [[ "$line" =~ ^TB_[A-Z0-9_]+=[^[:space:]]*$ ]] || die "metadata tb-site-env-$s: '$line' is not a TB_ KEY=VALUE line"
  done <<<"$extra"
  write_file "$ETC/$s.env" 0400 root <<ENV
TB_DEMO_TOOL=demo
TB_DEMO_KEEP=1
TB_DEMO_DIR=/data/demo
TB_DEMO_ACCOUNTS=/run/demo-accounts.json
TB_DEMO_LANG=${SITE_LANGS[$i]}
TB_TZ=${SITE_ZONES[$i]}
TB_CONSOLE_SECURE_COOKIE=1
TB_CONSOLE_PUBLIC_URL=https://$s.$DOMAIN
$extra
ENV
  if secret_exists "$PREFIX-owner-password"; then
    owner_env="$ETC/$s.owner.env"
    secret_to_file "$PREFIX-owner-password" "$owner_env" root TB_DEMO_OWNER_PASSWORD
  fi
  gone "tb-poc-$s"
  run docker run -d --name "tb-poc-$s" --restart unless-stopped --memory 6g \
    -p "127.0.0.1:${SITE_PORTS[$i]}:8080" \
    -v "$DATA/$s:/data" -v "$ETC/accounts-$s.json:/run/demo-accounts.json:ro" \
    --env-file "$ETC/$s.env" ${owner_env:+--env-file "$owner_env"} "$IMAGE"
}

wait_site() {  # wait_site INDEX: the first start seeds (3 to 6 minutes per site; demo/README.md)
  local p=${SITE_PORTS[$1]} n
  if [ "$DRY" = 1 ]; then echo "+ wait up to 15 minutes for http://127.0.0.1:$p/login"; return 0; fi
  for n in $(seq 1 180); do
    curl -sf -o /dev/null "http://127.0.0.1:$p/login" && { say "site ${SITE_NAMES[$1]} answers (after about $((n * 5)) s)"; return 0; }
    sleep 5
  done
  say "site ${SITE_NAMES[$1]} did not answer within 15 minutes: docker logs tb-poc-${SITE_NAMES[$1]}"
}

pinned "$IMAGE" || die "metadata tb-image must be an image by digest (…@sha256:<64 hex>), not '$IMAGE'; the VM never builds"
pinned "$CADDY_IMAGE" || die "tb-caddy-image must be pinned by digest"
pinned "$CLOUDFLARED_IMAGE" || die "tb-cloudflared-image must be pinned by digest"

# T-119 (CR-048): secrets come from Secret Manager only. A key, password, token or accounts file put in the instance
# metadata (readable by anyone on the VM and in the project's metadata) is refused before anything starts; its value
# is never read. In a dry run the metadata is the TB_MD_<KEY> environment.
metadata_keys() {
  if [ "$DRY" = 1 ]; then env | sed -n 's/^TB_MD_\([A-Z0-9_]*\)=.*/\1/p' | tr 'A-Z_' 'a-z-'; return 0; fi
  curl -sf -H Metadata-Flavor:Google "$MD/instance/attributes/" || true
}
for k in $(metadata_keys); do
  [[ "$k" =~ (password|passwd|token|accounts|^tb-key$|private-key) ]] \
    && die "metadata $k looks like a secret: put it in Secret Manager ($PREFIX-...) and remove it from the metadata"
done

if [ -n "$RESET_SITE" ]; then
  idx=$(site_index "$RESET_SITE") || die "no site '$RESET_SITE' in tb-sites ($SITES)"
  say "reset site $RESET_SITE: its kept folder is emptied; the next start seeds afresh (3 to 6 minutes)"
  mountpoint -q "$DATA" 2>/dev/null || [ "$DRY" = 1 ] || die "$DATA is not mounted"
  gone "tb-poc-$RESET_SITE"
  run rm -rf --one-file-system "$DATA/$RESET_SITE/demo"
  start_site "$idx"
  wait_site "$idx"
  echo POC-RESET-DONE
  exit 0
fi

say "PoC host: image $IMAGE; sites ${SITE_NAMES[*]} on $DOMAIN"
if [ "$DRY" = 1 ]; then echo "+ cp $0 $SELF (for --reset-site)"; else install -D -m 0700 "$0" "$SELF"; fi
if [ "$DRY" = 1 ] || ! command -v docker >/dev/null; then
  run apt-get update -qq
  run apt-get install -y -qq docker.io  # Debian's package; never a script piped from the network (OPS-008)
  run systemctl enable --now docker
fi
mount_data
run install -d -m 0700 "$ETC"
run install -d -m 0700 "$DATA/caddy-data"

say "images by digest"
REGISTRY_HOST=${IMAGE%%/*}
case "$REGISTRY_HOST" in *-docker.pkg.dev) run gcloud auth configure-docker "$REGISTRY_HOST" --quiet ;; esac
for ref in "$IMAGE" "$CADDY_IMAGE" "$CLOUDFLARED_IMAGE"; do run docker pull -q "$ref"; done

say "caddy"
caddyfile | write_file "$ETC/Caddyfile" 0444 root
gone tb-poc-caddy
run docker run -d --name tb-poc-caddy --restart unless-stopped --network host \
  -v "$ETC/Caddyfile:/etc/caddy/Caddyfile:ro" -v "$DATA/caddy-data:/data" "$CADDY_IMAGE"
ROOT_CRT="$DATA/caddy-data/caddy/pki/authorities/local/root.crt"
if [ "$DRY" = 1 ]; then echo "+ wait for $ROOT_CRT, copy it to $ETC/caddy-root.crt (0444) for cloudflared"; else
  for _ in $(seq 1 60); do [ -s "$ROOT_CRT" ] && break; sleep 2; done
  [ -s "$ROOT_CRT" ] || die "caddy made no local CA root ($ROOT_CRT): docker logs tb-poc-caddy"
  install -m 0444 "$ROOT_CRT" "$ETC/caddy-root.crt"
fi

say "tunnel (outbound only; Cloudflare Access checks every request)"
secret_to_file "$PREFIX-tunnel-token" "$ETC/tunnel.env" root TUNNEL_TOKEN
gone tb-poc-tunnel
run docker run -d --name tb-poc-tunnel --restart unless-stopped --network host \
  --env-file "$ETC/tunnel.env" -v "$ETC/caddy-root.crt:/etc/trialbox/caddy-root.crt:ro" \
  "$CLOUDFLARED_IMAGE" tunnel --no-autoupdate run

say "sites (kept data, no reseed at restart)"
for i in "${!SITE_NAMES[@]}"; do start_site "$i"; done
for i in "${!SITE_NAMES[@]}"; do wait_site "$i"; done
if [ "$DRY" = 1 ]; then echo "+ docker ps"; else docker ps --format '{{.Names}} {{.Status}}'; fi
for s in "${SITE_NAMES[@]}"; do say "ready https://$s.$DOMAIN (behind the front door)"; done
echo POC-STARTUP-DONE
