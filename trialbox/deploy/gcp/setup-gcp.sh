#!/usr/bin/env bash
# TrialBox hosted demo: one-time GCP setup. Run in Google Cloud Shell
# (the >_ icon at the top right of console.cloud.google.com).
#
# What it does (nothing here starts a VM or costs money by itself):
#   1. uses PROJECT_ID (creates it if missing) and links your billing account
#   2. enables the Compute Engine API
#   3. creates service account trialbox-deployer with only the roles needed
#      to create and manage a VM + its firewall rule
#   4. Secret Manager (T-119, CR-048; a secret with no version costs nothing):
#        tb-gpu-door       the GPU run's door (complete-run.sh adds one version per VM and run and destroys it
#                          once collected); the deployer may add and destroy versions of it only, the VMs' service
#                          account may read it
#        tb-demo-password  the demo VM's password (demo-vm-startup.sh reads it; never metadata): asked here once,
#                          without echo, when it has no version yet (Enter skips)
#   5. creates ONE JSON key and prints a one-line base64 copy of it
#      for the GCP_SA_KEY environment variable
#
# Usage:  bash setup-gcp.sh [PROJECT_ID]
#         VM_SA=<email> bash setup-gcp.sh ...   the VMs' service account (default: the Compute Engine default one)
set -euo pipefail

PROJECT_ID="${1:-trialbox-demo-$(date +%y%m%d)}"
REGION="asia-east1"            # Taiwan
ZONE="asia-east1-b"
SA_NAME="trialbox-deployer"
SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
KEY="$HOME/trialbox-gcp-key.json"

echo "== Project: $PROJECT_ID"
if ! gcloud projects describe "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud projects create "$PROJECT_ID" --name="TrialBox demo"
fi
gcloud config set project "$PROJECT_ID" >/dev/null

echo "== Billing"
if [ "$(gcloud billing projects describe "$PROJECT_ID" --format='value(billingEnabled)')" != "True" ]; then
  gcloud billing accounts list
  ACCT="$(gcloud billing accounts list --filter=open=true --format='value(name)' | head -1)"
  [ -n "$ACCT" ] || { echo "No open billing account. Create one in Billing, then rerun."; exit 1; }
  read -r -p "Link billing account $ACCT to $PROJECT_ID? [y/N] " ok
  [ "$ok" = "y" ] || { echo "Stopped before linking billing."; exit 1; }
  gcloud billing projects link "$PROJECT_ID" --billing-account="${ACCT##*/}"
fi

echo "== Enable Compute Engine API (takes ~1 min)"
gcloud services enable compute.googleapis.com
gcloud config set compute/region "$REGION" >/dev/null
gcloud config set compute/zone "$ZONE" >/dev/null

echo "== Service account $SA"
gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$SA_NAME" --display-name="TrialBox deployer"
for ROLE in roles/compute.instanceAdmin.v1 roles/compute.securityAdmin roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA" --role="$ROLE" --condition=None >/dev/null
  echo "   granted $ROLE"
done

echo "== Secret Manager (secrets, never metadata)"
gcloud services enable secretmanager.googleapis.com
VM_SA="${VM_SA:-$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')-compute@developer.gserviceaccount.com}"
for SECRET in tb-gpu-door tb-demo-password; do
  gcloud secrets describe "$SECRET" >/dev/null 2>&1 || \
    gcloud secrets create "$SECRET" --replication-policy=automatic --labels=trialbox=t-119 >/dev/null
  gcloud secrets add-iam-policy-binding "$SECRET" --member="serviceAccount:$VM_SA" \
    --role=roles/secretmanager.secretAccessor --condition=None >/dev/null
  echo "   $SECRET: readable by $VM_SA"
done
gcloud secrets add-iam-policy-binding tb-gpu-door --member="serviceAccount:$SA" \
  --role=roles/secretmanager.secretVersionManager --condition=None >/dev/null
echo "   tb-gpu-door: $SA adds and destroys its versions"
if [ -z "$(gcloud secrets versions list tb-demo-password --filter=state:enabled --format='value(name)' 2>/dev/null)" ]; then
  read -r -s -p "Demo VM password (not shown; Enter to skip): " DEMO_PW; echo
  if [ -n "$DEMO_PW" ]; then
    printf '%s' "$DEMO_PW" | gcloud secrets versions add tb-demo-password --data-file=- >/dev/null
    echo "   tb-demo-password: stored"
  fi
  unset DEMO_PW
fi

echo "== Key"
if [ -f "$KEY" ]; then
  echo "   $KEY already exists; reusing it (delete it to make a new key)."
elif ! gcloud iam service-accounts keys create "$KEY" --iam-account="$SA"; then
  echo "Key creation was refused. Your organisation probably enforces"
  echo "iam.disableServiceAccountKeyCreation. Tell Claude in the thread; do not paste anything."
  exit 1
fi

echo
echo "== DONE. Copy the single line between the markers into the GCP_SA_KEY variable"
echo "   (Claude project settings > Cloud environment > gear > environment variables)."
echo "   Never paste it into chat."
echo "-----8<-----"
base64 -w0 "$KEY"; echo
echo "-----8<-----"
echo "Also add:  GCP_PROJECT=$PROJECT_ID   GCP_ZONE=$ZONE"
echo "After saving, delete the local copy:  shred -u $KEY"
