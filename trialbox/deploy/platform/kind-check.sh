#!/usr/bin/env bash
# The platform deployment on a kind cluster without a GPU (T-113 acceptance 2 and 3, D-211; T-113b, D-409): what the
# CI job runs.
#
#   make images                 # trialbox-py:1.0.0, trialbox-jvm:1.0.0 and trialbox-postgres:16-1 in the local docker
#   deploy/platform/kind-check.sh                  # needs kind, kubectl, kustomize; about 15 minutes
#   SLICES=1 deploy/platform/kind-check.sh         # one MIG instance: the doctor must fail mig_instances, saying why
#
# Creates the cluster `tb-platform`, loads the release's images, makes throw-away Secrets (`trialbox secrets init` in
# a temporary folder and a random model key; nothing is a real credential), a ResourceQuota for the minimum and a
# test overlay on top of overlays/shared-quota (namespace trialbox, ReadWriteOnce claims for kind's local-path
# storage, TB_ENV=TEST, the doctor's egress to the API server rendered by `platform-egress`).
#
# The GPU is a stand-in (D-409): the kind node advertises SLICES (default 2) `nvidia.com/gpu` devices by hand and
# carries the labels the NVIDIA device plugin and GPU feature discovery put on a B200 node with MIG on (strategy
# single, product NVIDIA-B200-MIG-3g.90gb, sharing none); the judge and the verifier run the vLLM stand-in of
# tests/rehearsal (the OpenAI surface with --api-key, answers from the deterministic stub) behind model-guard, on
# those devices; TB_PLATFORM_GPU_STANDIN=1 (refused in VALIDATION and PRODUCTION) makes serving_record and canary
# `skipped: stand-in device`, while gpu_serving, mig_instances and model_key run for real; components/node-read
# lets the doctor read the node. With SLICES=2 the doctor must PASS gpu_serving, mig_instances and model_key; with
# SLICES=1 the verifier cannot be scheduled and the doctor must FAIL mig_instances with that reason. Then the
# isolation probe from a second namespace; the cluster is deleted (KEEP=1 keeps it).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
NAME="${KIND_CLUSTER:-tb-platform}"
NS=trialbox
SLICES="${SLICES:-2}"
case "$SLICES" in 1|2) ;; *) echo "kind-check: SLICES must be 1 or 2" >&2; exit 2 ;; esac
MIG=3g.90gb
PY="${PYTHON:-$ROOT/.venv/bin/python}"
WORK="$(mktemp -d)"
cleanup() {
  rm -rf "$WORK"
  [ "${KEEP:-0}" = 1 ] || kind delete cluster --name "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

kind create cluster --name "$NAME" --wait 180s
kubectl config use-context "kind-$NAME" >/dev/null
# the stand-in GPU: SLICES MIG instances advertised on the node, labelled as GPU feature discovery labels a B200
NODE="$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')"
kubectl label node "$NODE" --overwrite nvidia.com/mig.strategy=single "nvidia.com/gpu.product=NVIDIA-B200-MIG-$MIG" \
  nvidia.com/gpu.sharing-strategy=none >/dev/null
kubectl patch node "$NODE" --subresource=status --type=json \
  -p "[{\"op\": \"add\", \"path\": \"/status/capacity/nvidia.com~1gpu\", \"value\": \"$SLICES\"}]" >/dev/null
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
kubectl -n "$NS" create secret generic trialbox-model-key \
  --from-literal=TB_LLM_API_KEY="$(head -c 32 /dev/urandom | base64 | tr -dc A-Za-z0-9)"
kubectl -n "$NS" create configmap vllm-standin --from-file=vllm_standin.py="$ROOT/tests/rehearsal/vllm_standin.py"
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
REL() { "$PY" -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$1" "$O"; }
BASE="$(REL "$ROOT/deploy/platform/overlays/shared-quota")"
NODEREAD="$(REL "$ROOT/deploy/platform/components/node-read")"
standin() {  # the vLLM stand-in on the advertised device, behind model-guard, with the key from the Secret
  cat <<EOP
  - target: {kind: Deployment, name: $1}
    patch: |-
      - {op: replace, path: /spec/template/spec/containers/0/image, value: "trialbox-py:1.0.0"}
      - {op: add, path: /spec/template/spec/containers/0/command, value: [python, /standin/vllm_standin.py]}
      - op: replace
        path: /spec/template/spec/containers/0/args
        value: ["--host=0.0.0.0", "--served=\$($2)", "--key-file=/run/secrets/model-key/TB_LLM_API_KEY",
                "--load-seconds=5", "--repo=/app", "--name=$1"]
      - op: replace
        path: /spec/template/spec/containers/0/resources
        value: {requests: {cpu: 100m, memory: 512Mi, nvidia.com/gpu: 1}, limits: {memory: 1Gi, nvidia.com/gpu: 1}}
      - {op: add, path: /spec/template/spec/volumes/-, value: {name: standin, configMap: {name: vllm-standin}}}
      - {op: add, path: /spec/template/spec/volumes/-, value: {name: model-key, secret: {secretName: trialbox-model-key}}}
      - {op: add, path: /spec/template/spec/containers/0/volumeMounts/-, value: {name: standin, mountPath: /standin}}
      - {op: add, path: /spec/template/spec/containers/0/volumeMounts/-, value: {name: model-key, mountPath: /run/secrets/model-key}}
EOP
}
cat > "$O/kustomization.yaml" <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: $NS
resources: ["$BASE", egress.yaml]
components: ["$NODEREAD"]
configMapGenerator:
  - {name: trialbox-env, behavior: merge, literals: [TB_ENV=TEST, TB_CONSOLE_SECURE_COOKIE=0]}
  - name: trialbox-platform
    behavior: merge
    literals: [TB_PLATFORM_GPU_STANDIN=1, "TB_MIG_PROFILE=$MIG", TB_PLATFORM_GPU_SHARING=mig,
               "TB_PLATFORM_GPU_EVIDENCE=kind stand-in node labels", "TB_PLATFORM_API_SERVER=$API"]
patches:
  - target: {kind: PersistentVolumeClaim}
    patch: '[{"op": "replace", "path": "/spec/accessModes", "value": ["ReadWriteOnce"]}]'
  # no weights on kind: the pin job would only fail (the pin is tested in tests/unit/test_platform_mig_and_key.py)
  - patch: '{"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": "trialbox-pin"}, "\$patch": "delete"}'
$(standin llm-service JUDGE_MODEL)
$(standin llm-verifier VERIFIER_MODEL)
EOF
kustomize build "$O" > "$WORK/rendered.yaml"
(cd "$ROOT" && TB_ENV=TEST "$PY" -m tools.trialbox doctor --platform --no-gpu --manifests "$WORK/rendered.yaml" \
  | tail -16) || true   # before the apply: the quota minimum and the image refusals
kubectl apply -f "$WORK/rendered.yaml"

PAIR="llm-service"; [ "$SLICES" = 2 ] && PAIR="llm-service llm-verifier"   # one slice: the verifier stays Pending
for d in db fhir-store lake embed-service doc-parser criteria-compiler adapter orchestrator mail-gateway gateway console \
         model-guard $PAIR; do
  kind_of=deployment; [ "$d" = db ] && kind_of=statefulset
  kubectl -n "$NS" rollout status "$kind_of/$d" --timeout=900s
done
if [ "$SLICES" = 1 ]; then  # the scheduler's reason, which the doctor reads from the pod
  kubectl -n "$NS" wait pod -l app.kubernetes.io/component=llm-verifier --for=condition=PodScheduled=false --timeout=120s
fi
kubectl -n "$NS" delete job trialbox-doctor --ignore-not-found   # run the doctor now that the pair is placed
kubectl apply -f "$WORK/rendered.yaml" >/dev/null
kubectl -n "$NS" wait --for=condition=complete --for=condition=failed job/trialbox-doctor --timeout=600s || true
kubectl -n "$NS" logs job/trialbox-doctor | tee "$WORK/doctor.txt"
for check in topology image_digests quota storage_encryption network_policy kek_custody ntp directory mail_relay \
             backup_target gpu_serving mig_instances model_key; do
  grep -Eq "^(PASS|WARN|FAIL|SKIP) +$check " "$WORK/doctor.txt" || { echo "kind-check: no $check line"; exit 1; }
done
for check in serving_record canary; do
  grep -Eq "^SKIP +$check +skipped: stand-in device" "$WORK/doctor.txt" || { echo "kind-check: $check not skipped"; exit 1; }
done
grep -Eq "^PASS +model_key .*refuses without the key" "$WORK/doctor.txt" || { echo "kind-check: model_key"; exit 1; }
if [ "$SLICES" = 2 ]; then
  for check in gpu_serving mig_instances; do
    grep -Eq "^PASS +$check " "$WORK/doctor.txt" || { echo "kind-check: $check did not pass on two slices"; exit 1; }
  done
else
  grep -Eq "^FAIL +mig_instances .*cannot be scheduled.*ask for two" "$WORK/doctor.txt" \
    || { echo "kind-check: one slice did not fail mig_instances with its reason"; exit 1; }
fi

(cd "$ROOT" && TB_INTEGRATION=1 TB_PLATFORM_NAMESPACE="$NS" "$PY" -m pytest -q -m integration tests/platform)
echo "KIND-CHECK PASSED (SLICES=$SLICES)"
