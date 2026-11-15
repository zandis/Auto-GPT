#!/bin/bash
# TrialBox small demo VM: its startup script (made and given to the VM by deploy/gcp/demo-vm.sh; runs at every boot).
# It never builds and never clones: it runs the demo image (demo/Dockerfile, the same image CI's demo-boot job starts)
# with the stub model on the synthetic hospital, behind Caddy on tcp:443. docs/runbook/11-cloud-runs.md.
#
#   the image   metadata tb-demo-image: REGISTRY/PATH@sha256:<64 hex> (pulled), or gs://BUCKET/...tar.gz (`make
#               demo-bundle`) whose sha256 must equal metadata tb-demo-image-sha256 (copied, checked, loaded)
#   the login   the demo's own sign-in (tools/demo.py: admin, crc, pi, subpi, cra, viewer; one password). The password
#               is read here from Secret Manager (metadata tb-demo-password-secret names the secret, default
#               tb-demo-password; the VM's own service account reads it) into a root-only env file. It is never in
#               the metadata (a secret-looking metadata key stops this script), never on a command line, never in
#               this log: TB_DEMO_PASSWORD is set, so the demo does not print it either.
#   demo mode   TB_DEMO_MODE=on seeds the audited flag demo.mode on the first start (banner, uploads refused)
#   the model   TB_LLM_MODE=stub, TB_DEMO_TOOL=demo: fixed here; no metadata key changes them (tb-llm-* stops it)
#   TLS         Caddy (pinned by digest, as deploy/gcp/hosted-demo-startup.sh) with `tls internal` for the VM's own
#               external address: the browser warns once. Only :443 is bound (no :80 listener, no redirect). The
#               firewall (demo-vm.sh) lets tcp:443 in from the allowed ranges only, and nothing else.
#   hard stop   metadata tb-demo-hours (whole hours): `shutdown -P` is armed at every boot, so the VM powers itself
#               off that long after it started (Compute Engine's max-run-duration stops it at the same time).
#
#   demo-vm-boot.sh                    the boot run, as root
#   demo-vm-boot.sh --dry-run          print what it would do; metadata from TB_MD_<KEY> (e.g. TB_MD_TB_DEMO_IMAGE)
#   demo-vm-boot.sh --print-caddyfile  the Caddyfile only (TB_MD_EXTERNAL_IP for the address)
# No `set -x` (review A-12): nothing secret reaches the serial log.
set -euo pipefail

DRY=0; PRINT_CADDY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --print-caddyfile) PRINT_CADDY=1; DRY=1 ;;
    -h | --help) sed -n 2,24p "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

# the same pin as deploy/gcp/hosted-demo-startup.sh (tests/unit/test_g1_demo_vm.py keeps them equal)
CADDY_IMAGE_PIN="caddy:2.11.9@sha256:0c2243efcf437ab7f7a978f1027fcf0d4f9be8a75df27b1b3fbc5dbe0ffa8cf0"
ETC=/etc/tb-demo-vm          # root-only: the env files, the Caddyfile
DATA=/var/lib/tb-demo-vm     # Caddy's data (its local CA)
MD=http://metadata.google.internal/computeMetadata/v1
# the first answer on /login: CI's demo-boot budget is 600 s (demo/README.md, measured 166 to 339 s); twice that
SEED_WAIT_S=1200

say() { echo "TB-DEMO-VM $(date -u +%H:%M:%S) $*"; }
die() { echo "TB-DEMO-VM refused: $*" >&2; exit 3; }
run() { if [ "$DRY" = 1 ]; then printf '+'; printf ' %q' "$@"; printf '\n'; else "$@"; fi; }
gone() { if [ "$DRY" = 1 ]; then echo "+ docker rm -f $1"; else docker rm -f "$1" >/dev/null 2>&1 || true; fi; }
md() {  # md PATH [DEFAULT]: an instance metadata value; in a dry run the environment variable TB_MD_<KEY>
  local key=$1 def=${2-} var
  if [ "$DRY" = 1 ]; then
    var="TB_MD_$(printf '%s' "${key##*/}" | tr 'a-z-' 'A-Z_')"
    printf '%s' "${!var:-$def}"
    return 0
  fi
  curl -sf -H Metadata-Flavor:Google "$MD/$key" || printf '%s' "$def"
}

# the serial console (demo-vm.sh status reads it); tests/rehearsal/demo-vm-local.sh points it at a file
[ "$DRY" = 1 ] || exec > >(tee -a /var/log/tb-demo-vm.log "${DEMO_VM_SERIAL:-/dev/ttyS0}") 2>&1

IP=$(md instance/network-interfaces/0/access-configs/0/external-ip "")
[[ "$IP" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || die "no external IPv4 address on this VM ('$IP')"

caddyfile() {  # tls internal for the VM's own address; a client without SNI (an IP in the address bar) gets it too
  cat <<CF
{
	admin off
	auto_https disable_redirects
	skip_install_trust
	default_sni $IP
}

https://$IP:443 {
	tls internal
	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options nosniff
		Referrer-Policy same-origin
		-Server
	}
	reverse_proxy 127.0.0.1:8080
}
CF
}
if [ "$PRINT_CADDY" = 1 ]; then caddyfile; exit 0; fi

# T-119: secrets come from Secret Manager only. A secret-looking metadata key stops the boot before anything starts
# (its value is never read); so does any key that would change the model.
metadata_keys() {
  if [ "$DRY" = 1 ]; then env | sed -n 's/^TB_MD_\([A-Z0-9_]*\)=.*/\1/p' | tr 'A-Z_' 'a-z-'; return 0; fi
  curl -sf -H Metadata-Flavor:Google "$MD/instance/attributes/" || true
}
for k in $(metadata_keys); do
  [[ "$k" =~ (password$|passwd|token|accounts|private-key|^tb-key$) ]] \
    && die "metadata $k looks like a secret: put it in Secret Manager and remove it from the metadata"
  [[ "$k" =~ ^tb-llm|^tb-demo-tool ]] && die "metadata $k: the demo VM runs the stub model and the demo tool only"
done

IMAGE=$(md instance/attributes/tb-demo-image "")
IMAGE_SHA=$(md instance/attributes/tb-demo-image-sha256 "")
SECRET=$(md instance/attributes/tb-demo-password-secret tb-demo-password)
HOURS=$(md instance/attributes/tb-demo-hours "")
LANG_UI=$(md instance/attributes/tb-demo-lang ja)
SITE_LANG=$(md instance/attributes/tb-demo-site-lang "")
if [ "$DRY" = 1 ]; then PROJECT=${TB_MD_PROJECT_ID:-"<project>"}; else PROJECT=$(md project/project-id ""); fi

[[ "$HOURS" =~ ^[1-9][0-9]*$ ]] || die "metadata tb-demo-hours must be a whole number of hours (got '$HOURS')"
[[ "$SECRET" =~ ^[A-Za-z0-9_-]{1,255}$ ]] || die "metadata tb-demo-password-secret is not a secret name"
case "$LANG_UI" in ja | zh-TW | en) ;; *) die "metadata tb-demo-lang must be ja, zh-TW or en" ;; esac
case "$SITE_LANG" in "" | ja | zh-TW) ;; *) die "metadata tb-demo-site-lang must be ja or zh-TW" ;; esac
if [[ "$IMAGE" =~ @sha256:[0-9a-f]{64}$ ]]; then KIND=digest
elif [[ "$IMAGE" =~ ^gs://[a-z0-9._-]+/.+\.tar\.gz$ ]]; then
  KIND=tarball
  [[ "$IMAGE_SHA" =~ ^[0-9a-f]{64}$ ]] || die "metadata tb-demo-image-sha256 must be the tarball's sha256"
else die "metadata tb-demo-image must be an image by digest or a gs:// .tar.gz (got '$IMAGE')"; fi

# the hard stop first, before anything that could hang: a forgotten demo cannot bill for a week
say "hard stop: this VM powers off $HOURS h after this boot"
run shutdown -P "+$((HOURS * 60))" "TrialBox demo VM: the hard stop (tb-demo-hours=$HOURS)"

if [ "$DRY" = 1 ] || ! command -v docker >/dev/null; then
  run apt-get update -qq
  run apt-get install -y -qq docker.io  # Debian's package; never a script piped from the network (OPS-008)
  run systemctl enable --now docker
fi
run install -d -m 0700 "$ETC"
run install -d -m 0700 "$DATA"

say "the password from Secret Manager ($SECRET; never printed)"
if [ "$DRY" = 1 ]; then
  echo "+ gcloud secrets versions access latest --secret=$SECRET --project=$PROJECT > $ETC/secret.env (as TB_DEMO_PASSWORD=..., mode 0400; the value is never printed)"
else
  tmp="$ETC/secret.env.tmp.$$"
  ( umask 077
    { printf 'TB_DEMO_PASSWORD='; gcloud secrets versions access latest --secret="$SECRET" --project="$PROJECT"; echo; } >"$tmp"
  ) 2>/dev/null || { rm -f "$tmp"; die "secret $SECRET has no readable version (deploy/gcp/setup-gcp.sh; the VM's service account must read it)"; }
  [ "$(wc -c <"$tmp")" -gt 18 ] || { rm -f "$tmp"; die "secret $SECRET is empty"; }  # more than 'TB_DEMO_PASSWORD=\n'
  chmod 0400 "$tmp"; mv -f "$tmp" "$ETC/secret.env"
fi
DEMO_ENV="TB_DEMO_TOOL=demo
TB_LLM_MODE=stub
TB_DEMO_MODE=on
TB_DEMO_LANG=$LANG_UI
TB_CONSOLE_SECURE_COOKIE=1
TB_CONSOLE_PUBLIC_URL=https://$IP${SITE_LANG:+
TB_DEMO_SITE_LANG=$SITE_LANG}"
if [ "$DRY" = 1 ]; then echo "+ write $ETC/demo.env (mode 0400):"; printf '%s\n' "$DEMO_ENV" | sed 's/^/    | /'
else (umask 077; printf '%s\n' "$DEMO_ENV" >"$ETC/demo.env"); fi

say "the demo image ($KIND)"
if [ "$KIND" = digest ]; then
  case "${IMAGE%%/*}" in *-docker.pkg.dev) run gcloud auth configure-docker "${IMAGE%%/*}" --quiet ;; esac
  run docker pull -q "$IMAGE"
  REF=$IMAGE
elif [ "$DRY" = 1 ]; then
  echo "+ gcloud storage cp $IMAGE /root/trialbox-demo.tar.gz; sha256sum must be $IMAGE_SHA; docker load"
  REF="<the image docker load names>"
else
  gcloud storage cp "$IMAGE" /root/trialbox-demo.tar.gz
  echo "$IMAGE_SHA  /root/trialbox-demo.tar.gz" | sha256sum -c --quiet - || die "the tarball's sha256 is not $IMAGE_SHA"
  REF=$(gunzip -c /root/trialbox-demo.tar.gz | docker load | sed -n 's/^Loaded image: //p' | tail -1)
  [ -n "$REF" ] || die "docker load named no image"
fi
run docker pull -q "$CADDY_IMAGE_PIN"

say "the demo (stub model, synthetic hospital; seeds for 3 to 6 minutes)"
gone tb-demo
run docker run -d --name tb-demo --restart unless-stopped --memory 6g -p 127.0.0.1:8080:8080 \
  --env-file "$ETC/demo.env" --env-file "$ETC/secret.env" "$REF"

say "caddy on :443 (tls internal for $IP)"
if [ "$DRY" = 1 ]; then echo "+ write $ETC/Caddyfile:"; caddyfile | sed 's/^/    | /'
else (umask 022; caddyfile >"$ETC/Caddyfile"); fi
gone tb-demo-caddy
run docker run -d --name tb-demo-caddy --restart unless-stopped --network host \
  -v "$ETC/Caddyfile:/etc/caddy/Caddyfile:ro" -v "$DATA:/data" "$CADDY_IMAGE_PIN"

if [ "$DRY" = 1 ]; then
  echo "+ wait up to $SEED_WAIT_S s for https://$IP/login (through Caddy, from the VM itself)"
  echo DEMO-VM-DRY-RUN-DONE
  exit 0
fi
ok=0
for _ in $(seq 1 $((SEED_WAIT_S / 5))); do
  if curl -sf -o /dev/null --cacert "$DATA/caddy/pki/authorities/local/root.crt" --resolve "$IP:443:127.0.0.1" \
       "https://$IP/login" 2>/dev/null; then ok=1; break; fi
  sleep 5
done
ROOT_FP=$(openssl x509 -noout -fingerprint -sha256 -in "$DATA/caddy/pki/authorities/local/root.crt" 2>/dev/null \
  | sed 's/^.*=//' || true)
if [ "$ok" = 1 ]; then
  say "ready https://$IP/ (sign in: admin, crc, pi, subpi, cra or viewer; the password is in Secret Manager $SECRET)"
  say "certificate: Caddy's local CA, root SHA-256 ${ROOT_FP:-unknown} (the browser warns once; compare this)"
  echo DEMO-VM-READY
else
  say "no answer on https://$IP/login within $SEED_WAIT_S s: docker logs tb-demo (on the VM)"
  docker ps --format '{{.Names}} {{.Status}}' | sed 's/^/TB-DEMO-VM /'
  echo DEMO-VM-NOT-READY
fi
