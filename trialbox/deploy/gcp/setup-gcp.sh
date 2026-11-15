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
#      the deployer may also read tb-gpu-door's metadata and policy (roles/secretmanager.viewer on the secret): the
#      driver's `secrets describe` and its pre-flight need it (the 2026-11-12 run failed without it, A7)
#   4b. only with TB_BUCKET=gs://<bucket> (the GPU run's code and results through a bucket, not the door; a machine
#      behind an HTTPS proxy needs it, A6): the bucket (in REGION, uniform access) and roles/storage.objectAdmin on it
#      for the deployer and the VMs' service account. An empty bucket costs nothing; the run's objects cost cents.
#   5. creates ONE JSON key and prints a one-line base64 copy of it
#      for the GCP_SA_KEY environment variable
#
# Usage:  bash setup-gcp.sh [PROJECT_ID]
#         VM_SA=<email> bash setup-gcp.sh ...   the VMs' service account (default: the Compute Engine default one)
#         TB_BUCKET=gs://<bucket> bash setup-gcp.sh ...   also the GPU run's bucket (step 4b)
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
gcloud secrets add-iam-policy-binding tb-gpu-door --member="serviceAccount:$SA" \
  --role=roles/secretmanager.viewer --condition=None >/dev/null
echo "   tb-gpu-door: $SA reads its metadata, versions and policy (the driver's describe and pre-flight)"
if [ -z "$(gcloud secrets versions list tb-demo-password --filter=state:enabled --format='value(name)' 2>/dev/null)" ]; then
  read -r -s -p "Demo VM password (not shown; Enter to skip): " DEMO_PW; echo
  if [ -n "$DEMO_PW" ]; then
    printf '%s' "$DEMO_PW" | gcloud secrets versions add tb-demo-password --data-file=- >/dev/null
    echo "   tb-demo-password: stored"
  fi
  unset DEMO_PW
fi

if [ -n "${TB_BUCKET:-}" ]; then
  echo "== Bucket $TB_BUCKET (the GPU run's code and results)"
  case "$TB_BUCKET" in gs://?*) ;; *) echo "TB_BUCKET must be gs://<bucket>"; exit 1 ;; esac
  gcloud storage buckets describe "$TB_BUCKET" >/dev/null 2>&1 || \
    gcloud storage buckets create "$TB_BUCKET" --location="$REGION" --uniform-bucket-level-access >/dev/null
  for M in "serviceAccount:$SA" "serviceAccount:$VM_SA"; do
    gcloud storage buckets add-iam-policy-binding "$TB_BUCKET" --member="$M" --role=roles/storage.objectAdmin >/dev/null
    echo "   $TB_BUCKET: objectAdmin for ${M#serviceAccount:}"
  done
  # the driver's pre-flight reads the bucket's policy (both accounts must be on it): only this bucket's
  gcloud storage buckets add-iam-policy-binding "$TB_BUCKET" --member="serviceAccount:$SA" \
    --role=roles/storage.legacyBucketOwner >/dev/null
  echo "   $TB_BUCKET: $SA reads its policy (the driver's pre-flight)"
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
