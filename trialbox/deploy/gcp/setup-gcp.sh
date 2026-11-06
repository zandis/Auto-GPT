#!/usr/bin/env bash
# TrialBox hosted demo: one-time GCP setup. Run in Google Cloud Shell
# (the >_ icon at the top right of console.cloud.google.com).
#
# What it does (nothing here starts a VM or costs money by itself):
#   1. uses PROJECT_ID (creates it if missing) and links your billing account
#   2. enables the Compute Engine API
#   3. creates service account trialbox-deployer with only the roles needed
#      to create and manage a VM + its firewall rule
#   4. creates ONE JSON key and prints a one-line base64 copy of it
#      for the GCP_SA_KEY environment variable
#
# Usage:  bash setup-gcp.sh [PROJECT_ID]
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
