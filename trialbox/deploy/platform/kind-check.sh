#!/usr/bin/env bash
# The platform deployment on a kind cluster without a GPU (T-113 acceptance 2 and 3, D-211): what the CI job runs.
#
#   make images                 # trialbox-py:1.0.0, trialbox-jvm:1.0.0 and trialbox-postgres:16-1 in the local docker
#   deploy/platform/kind-check.sh                  # needs kind, kubectl, kustomize; about 15 minutes
#
# Creates the cluster `tb-platform`, loads the release's images, makes throw-away Secrets (`trialbox secrets init` in
# a temporary folder; nothing is a real credential), a ResourceQuota for the non-GPU minimum and a test overlay on
# top of overlays/shared-quota (namespace trialbox, ReadWriteOnce claims for kind's local-path storage, TB_ENV=TEST,
# TB_PLATFORM_NO_GPU=1, which VALIDATION and PRODUCTION refuse; the doctor's egress to the API server rendered by
# `platform-egress`); applies it; waits for every non-GPU workload; reads the doctor job's report (every check
# present, the GPU checks `skipped: no device`); runs the isolation probe from a second namespace; deletes the
# cluster (KEEP=1 keeps it). The judge and the verifier stay Pending: kind has no GPU.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
NAME="${KIND_CLUSTER:-tb-platform}"
NS=trialbox
PY="${PYTHON:-$ROOT/.venv/bin/python}"
WORK="$(mktemp -d)"
cleanup() {
  rm -rf "$WORK"
  [ "${KEEP:-0}" = 1 ] || kind delete cluster --name "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

kind create cluster --name "$NAME" --wait 180s
kubectl config use-context "kind-$NAME" >/dev/null
for ref in $(cd "$ROOT" && "$PY" -m tools.trialbox platform-images --env | cut -d= -f2-); do
  case "$ref" in vllm/*) continue ;; esac   # no GPU here: the model servers are never started
  docker image inspect "$ref" >/dev/null 2>&1 || docker pull "$ref"
  kind load docker-image --name "$NAME" "$ref"
done

kubectl create namespace "$NS"
mkdir -p "$WORK/deploy"
(cd "$ROOT" && "$PY" -m tools.trialbox secrets init --deploy "$WORK/deploy" >/dev/null)
S="$WORK/deploy/secrets/services"
for svc in lake embed-service doc-parser criteria-compiler adapter orchestrator mail-gateway gateway console; do
  kubectl -n "$NS" create secret generic "trialbox-token-$svc" --from-file=token="$S/$svc.token"
done
kubectl -n "$NS" create configmap trialbox-service-tokens --from-file=tokens.json="$S/public/tokens.json"
kubectl -n "$NS" create secret generic trialbox-actor --from-file=keys="$S/actor/keys"
PW="$(head -c 18 /dev/urandom | base64 | tr -dc A-Za-z0-9)"
kubectl -n "$NS" create secret generic trialbox-db --from-literal=POSTGRES_PASSWORD="$PW" \
  --from-literal=POSTGRES_WF_PASSWORD="$PW" --from-literal=TB_DB_URL="postgresql://trialbox:$PW@db:5432/trialbox_wf"
kubectl -n "$NS" create quota trialbox --hard=requests.cpu=16,requests.memory=96Gi,requests.nvidia.com/gpu=2

O="$WORK/overlay"
mkdir -p "$O"
# the doctor job's egress: only the API server here (no NTP, directory, relay or share on kind), rendered from the
# declaration like a site's (`platform-egress`); without it the job reaches nothing (fail closed)
API="$(kubectl -n default get endpoints kubernetes -o jsonpath='{.subsets[0].addresses[0].ip}:{.subsets[0].ports[0].port}')"
printf 'TB_ENV=TEST\nTB_PLATFORM_API_SERVER=%s\n' "$API" > "$WORK/site.env"
(cd "$ROOT" && "$PY" -m tools.trialbox platform-egress --env-file "$WORK/site.env") > "$O/egress.yaml"
BASE="$("$PY" -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$ROOT/deploy/platform/overlays/shared-quota" "$O")"
cat > "$O/kustomization.yaml" <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: $NS
resources: ["$BASE", egress.yaml]
configMapGenerator:
  - {name: trialbox-env, behavior: merge, literals: [TB_ENV=TEST, TB_CONSOLE_SECURE_COOKIE=0]}
  - {name: trialbox-platform, behavior: merge, literals: [TB_PLATFORM_NO_GPU=1, "TB_PLATFORM_API_SERVER=$API"]}
patches:
  - target: {kind: PersistentVolumeClaim}
    patch: '[{"op": "replace", "path": "/spec/accessModes", "value": ["ReadWriteOnce"]}]'
EOF
kustomize build "$O" > "$WORK/rendered.yaml"
(cd "$ROOT" && TB_ENV=TEST "$PY" -m tools.trialbox doctor --platform --no-gpu --manifests "$WORK/rendered.yaml" \
  | tail -16) || true   # before the apply: the quota minimum and the image refusals
kubectl apply -f "$WORK/rendered.yaml"

for d in db fhir-store lake embed-service doc-parser criteria-compiler adapter orchestrator mail-gateway gateway console; do
  kind_of=deployment; [ "$d" = db ] && kind_of=statefulset
  kubectl -n "$NS" rollout status "$kind_of/$d" --timeout=900s
done
kubectl -n "$NS" wait --for=condition=complete --for=condition=failed job/trialbox-doctor --timeout=600s || true
kubectl -n "$NS" logs job/trialbox-doctor | tee "$WORK/doctor.txt"
for check in topology image_digests quota storage_encryption network_policy kek_custody ntp directory mail_relay \
             backup_target; do
  grep -Eq "^(PASS|WARN|FAIL|SKIP) +$check " "$WORK/doctor.txt" || { echo "kind-check: no $check line"; exit 1; }
done
for check in serving_record gpu_serving canary; do
  grep -Eq "^SKIP +$check +skipped: no device" "$WORK/doctor.txt" || { echo "kind-check: $check not skipped"; exit 1; }
done

(cd "$ROOT" && TB_INTEGRATION=1 TB_PLATFORM_NAMESPACE="$NS" "$PY" -m pytest -q -m integration tests/platform)
echo "KIND-CHECK PASSED"
