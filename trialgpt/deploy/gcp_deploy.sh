#!/usr/bin/env bash
# Deploy TrialGPT on Google Cloud (Compute Engine, 1x NVIDIA L4) from Google Cloud Shell:
#
#   curl -fsSL https://raw.githubusercontent.com/zandis/Auto-GPT/claude/trialgpt-local-lcvm9p/trialgpt/deploy/gcp_deploy.sh -o gcp_deploy.sh
#   bash gcp_deploy.sh                                   # uses the project selected in Cloud Shell
#   REGION=asia-east1 ALLOW=203.0.113.0/24 bash gcp_deploy.sh
#
# Creates: a static IP, a firewall rule (80/443 from ALLOW), a g2-standard-8 VM (8 vCPU, 32 GB, L4 24 GB) running
# Ubuntu 24.04 whose startup script installs the NVIDIA driver, Docker and the NVIDIA toolkit, then starts
# deploy/docker-compose.yml. The site is https://<ip>.sslip.io (or DOMAIN=...) behind a login.
# The password is generated here and printed once; only its bcrypt hash goes to the VM.
# Re-running is safe: existing resources are reused, the VM restarts and gets a NEW password.
# Remove everything with: bash gcp_deploy.sh --delete
set -euo pipefail

PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-asia-east1}"                  # Taiwan
NAME="${NAME:-trialgpt}"
MACHINE="${MACHINE:-g2-standard-8}"
GPU="${GPU:-nvidia-l4}"
DISK_GB="${DISK_GB:-100}"
MODEL="${MODEL:-gemma4:26b}"                    # fits the L4's 24 GB with a 16k context
USER_NAME="${USER_NAME:-pi}"
ALLOW="${ALLOW:-0.0.0.0/0}"                     # better: your hospital's public IP range
BRANCH="${BRANCH:-claude/trialgpt-local-lcvm9p}"
[ -n "$PROJECT" ] || { echo "No project: gcloud config set project YOUR_PROJECT"; exit 1; }
g() { gcloud --project "$PROJECT" --quiet "$@"; }

if [ "${1:-}" = "--delete" ]; then
  ZONE=$(g compute instances list --filter="name=$NAME" --format="value(zone.basename())" | head -1)
  [ -n "$ZONE" ] && g compute instances delete "$NAME" --zone "$ZONE"
  g compute firewall-rules delete "$NAME-web" 2>/dev/null || true
  g compute firewall-rules delete "$NAME-http" 2>/dev/null || true
  g compute addresses delete "$NAME-ip" --region "$REGION" 2>/dev/null || true
  echo "Deleted."; exit 0
fi

echo "Project $PROJECT, region $REGION"
g services enable compute.googleapis.com

# 1. A zone in the region that offers the GPU
ZONE="${ZONE:-$(g compute accelerator-types list --filter="name=$GPU AND zone~^$REGION-" --format="value(zone)" | sort | head -1)}"
[ -n "$ZONE" ] || { echo "No $GPU in $REGION: try REGION=us-central1 (or another region)"; exit 1; }
echo "Zone $ZONE"

# 2. GPU quota (new projects often have 0)
quota=$(g compute regions describe "$REGION" --format=json | python3 -c "
import sys, json
q = {x['metric']: x['limit'] for x in json.load(sys.stdin)['quotas']}
print(int(q.get('NVIDIA_L4_GPUS', 0)))")
if [ "$quota" -lt 1 ] && [ "${SKIP_QUOTA_CHECK:-}" != 1 ]; then
  echo "GPU quota NVIDIA_L4_GPUS in $REGION is 0. Request 1 at:"
  echo "  https://console.cloud.google.com/iam-admin/quotas?project=$PROJECT  (filter: NVIDIA_L4_GPUS, region $REGION;"
  echo "  also GPUS_ALL_REGIONS >= 1), then run this script again (SKIP_QUOTA_CHECK=1 if you know it is granted)."
  exit 1
fi

# 3. Static IP, domain, firewall
g compute addresses describe "$NAME-ip" --region "$REGION" >/dev/null 2>&1 || g compute addresses create "$NAME-ip" --region "$REGION"
IP=$(g compute addresses describe "$NAME-ip" --region "$REGION" --format="value(address)")
DOMAIN="${DOMAIN:-${IP//./-}.sslip.io}"
# port 80 only redirects to HTTPS but must stay open for the Let's Encrypt check; the site (443) is limited to ALLOW
g compute firewall-rules describe "$NAME-http" >/dev/null 2>&1 || \
  g compute firewall-rules create "$NAME-http" --allow tcp:80 --target-tags "$NAME" --source-ranges 0.0.0.0/0
g compute firewall-rules describe "$NAME-web" >/dev/null 2>&1 || \
  g compute firewall-rules create "$NAME-web" --allow tcp:443 --target-tags "$NAME" --source-ranges "$ALLOW"

# 4. Login: random password, bcrypt hash only goes to the VM
PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(15))')"
if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  HASH=$(docker run --rm caddy:2.10 caddy hash-password --plaintext "$PASSWORD")
else
  python3 -c "import bcrypt" 2>/dev/null || pip3 install --quiet --user bcrypt
  HASH=$(python3 -c "import bcrypt,sys; print(bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt(14)).decode())" "$PASSWORD")
fi

# 5. VM (startup script runs on every boot and is idempotent)
STARTUP=$(mktemp)
cat > "$STARTUP" <<'EOS'
#!/bin/bash
exec >>/var/log/trialgpt-setup.log 2>&1
set -euxo pipefail
md() { curl -fsS -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"; }
if ! command -v nvidia-smi >/dev/null || ! nvidia-smi >/dev/null 2>&1; then
  apt-get update && apt-get install -y ubuntu-drivers-common && ubuntu-drivers install && reboot; exit 0
fi
if ! command -v docker >/dev/null; then curl -fsSL https://get.docker.com | sh; fi
if ! command -v nvidia-ctk >/dev/null; then
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update && apt-get install -y nvidia-container-toolkit git
  nvidia-ctk runtime configure --runtime=docker && systemctl restart docker
fi
BRANCH=$(md tg-branch)
if [ -d /opt/trialgpt-src/.git ]; then git -C /opt/trialgpt-src pull --ff-only
else git clone --branch "$BRANCH" --depth 1 https://github.com/zandis/Auto-GPT.git /opt/trialgpt-src; fi
cd /opt/trialgpt-src/trialgpt/deploy
umask 077
{
  echo "TG_DOMAIN=$(md tg-domain)"
  echo "TG_USER=$(md tg-user)"
  echo "TG_PASSWORD_HASH=$(md tg-password-hash | sed 's/\$/$$/g')"
  echo "TG_LLM_MODEL=$(md tg-model)"
} > .env
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
echo "TrialGPT started $(date -Is)"
EOS
ACCEL=()   # g2 (L4) / a2 / a3 machine types come with their GPUs; n1 needs them attached
case "$MACHINE" in n1-*) ACCEL=(--accelerator "type=$GPU,count=1") ;; esac
if ! g compute instances describe "$NAME" --zone "$ZONE" >/dev/null 2>&1; then
  g compute instances create "$NAME" --zone "$ZONE" --machine-type "$MACHINE" \
    "${ACCEL[@]}" --maintenance-policy TERMINATE \
    --image-family ubuntu-2404-lts-amd64 --image-project ubuntu-os-cloud \
    --boot-disk-size "${DISK_GB}GB" --boot-disk-type pd-balanced \
    --address "$IP" --tags "$NAME" --no-shielded-secure-boot \
    --metadata-from-file startup-script="$STARTUP" \
    --metadata "tg-domain=$DOMAIN,tg-user=$USER_NAME,tg-model=$MODEL,tg-branch=$BRANCH,tg-password-hash=$HASH"
else
  g compute instances add-metadata "$NAME" --zone "$ZONE" --metadata-from-file startup-script="$STARTUP" \
    --metadata "tg-domain=$DOMAIN,tg-user=$USER_NAME,tg-model=$MODEL,tg-branch=$BRANCH,tg-password-hash=$HASH"
  g compute instances reset "$NAME" --zone "$ZONE"
fi
rm -f "$STARTUP"

cat <<EOF

If the HTTPS certificate fails (shared sslip.io limits), rerun with your own name: DOMAIN=trialgpt.example.org
(DNS A record -> $IP first).

Deploying. First boot installs the NVIDIA driver and reboots, then builds and pulls $MODEL: allow 20-30 minutes.
  URL:      https://$DOMAIN
  user:     $USER_NAME
  password: $PASSWORD        (shown once: save it now)

Progress:  gcloud compute ssh $NAME --zone $ZONE --project $PROJECT -- sudo tail -f /var/log/trialgpt-setup.log
Stop billing for the GPU when idle:  gcloud compute instances stop $NAME --zone $ZONE --project $PROJECT
Remove everything:                   bash gcp_deploy.sh --delete
EOF
