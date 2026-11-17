#!/usr/bin/env bash
# Day 2 of the platform deployment on a kind cluster (T-633 acceptance, D-416; RUNBOOK §26). Builds on the cluster
# and the overlay deploy/platform/kind-check.sh leaves behind:
#
#   make images
#   KEEP=1 KIND_WORK=/tmp/tb-kind deploy/platform/kind-check.sh     # the cluster, the namespace, the overlay
#   KIND_WORK=/tmp/tb-kind deploy/platform/kind-day2.sh             # about 20 minutes
#   kind delete cluster --name tb-platform && rm -rf /tmp/tb-kind
#
# Checks, in order (each failure stops the script with what failed):
#   1. `doctor --platform` fails when no backup job exists: on the rendered manifests, and in the cluster after
#      `kubectl delete cronjob trialbox-backup`; with the job back, backup_job does not fail;
#   2. a backup file appears on the share claim: the CronJob trialbox-backup run once, the file and its .sha256 on
#      the claim backup-share, whole (`trialbox backup-check` in a pod that mounts the claim);
#   3. a wipe and restore pass: a marker row and a marker file, the services scaled to 0, the database's StatefulSet
#      and every data claim deleted and made again empty, the restore job from the share with the restore key
#      Secret, the Secret deleted; the row and the file are back and every service rolls out;
#   4. a digest update and its rollback pass: trialbox-py rebuilt with one label (a new digest), pinned by
#      `platform-day2 update-overlay`, the pre-update backup, the update applied (the pods run the new digest,
#      image_digests does not fail), then `previous` applied (the pods run the old digest again);
#   5. the log job runs: yesterday's pod logs and the audit archive on the logs-data claim.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
NAME="${KIND_CLUSTER:-tb-platform}"
NS=trialbox
WORK="${KIND_WORK:?run KEEP=1 KIND_WORK=<dir> deploy/platform/kind-check.sh first and give the same KIND_WORK}"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
D="$WORK/day2"
mkdir -p "$D"
[ -f "$WORK/overlay/kustomization.yaml" ] || { echo "kind-day2: no $WORK/overlay (KEEP=1 kind-check.sh)" >&2; exit 2; }
kubectl config use-context "kind-$NAME" >/dev/null
k() { kubectl -n "$NS" "$@"; }
fail() { echo "kind-day2: FAILED: $*" >&2; exit 1; }
SITE_TZ="$(grep '^TB_TZ=' "$ROOT/deploy/platform/base/site.env" | cut -d= -f2-)"
REL() { "$PY" -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$1" "$2"; }

job() {  # job <name> <from cronjob> [timeout]: run a job from a CronJob, wait, print its log; exit 1 if it failed
  k delete job "$1" --ignore-not-found >/dev/null
  k create job --from="cronjob/$2" "$1" >/dev/null
  if ! k wait --for=condition=complete "job/$1" --timeout="${3:-1200s}" >/dev/null 2>&1; then
    k logs "job/$1" --all-containers --prefix || true
    return 1
  fi
  k logs "job/$1" --all-containers --prefix || true
}
doctor() {  # run the install-check job again; its report in $D/doctor-$1.txt
  k delete job trialbox-doctor --ignore-not-found >/dev/null
  kubectl apply -f "$D/rendered.yaml" >/dev/null
  k wait --for=condition=complete --for=condition=failed job/trialbox-doctor --timeout=600s >/dev/null || true
  k logs job/trialbox-doctor > "$D/doctor-$1.txt" || true
}
rollout() {
  for dpl in $(k get deployment -o name); do k rollout status "$dpl" --timeout=900s; done
  k rollout status statefulset/db --timeout=900s
}
images_of() { k get pods -l "app.kubernetes.io/component=$1" -o jsonpath='{.items[*].spec.containers[*].image}'; }

# the backup key pair (throw-away) and the public key ConfigMap; the day-2 overlay sets the site's zone on the jobs
(cd "$ROOT" && "$PY" -m tools.trialbox backup-keygen --private "$D/backup.key" --public "$D/backup.pub" >/dev/null)
k create configmap trialbox-backup-pub --from-file=backup.pub="$D/backup.pub" --dry-run=client -o yaml | k apply -f -
mkdir -p "$D/overlay"
cat > "$D/overlay/kustomization.yaml" <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources: ["$(REL "$WORK/overlay" "$D/overlay")"]
patches:
  - target: {kind: CronJob}
    patch: '[{"op": "add", "path": "/spec/timeZone", "value": "$SITE_TZ"}]'
EOF
kustomize build "$D/overlay" > "$D/rendered.yaml"

# 1. doctor --platform fails when no backup job exists
"$PY" - "$D/rendered.yaml" "$D/no-backup.yaml" <<'PYEOF'
import sys, yaml
docs = [d for d in yaml.safe_load_all(open(sys.argv[1], encoding="utf-8")) if d]
keep = [d for d in docs if not (d.get("kind") == "CronJob" and d["metadata"]["name"] == "trialbox-backup")]
assert len(keep) == len(docs) - 1, "the rendered manifests have no CronJob trialbox-backup"
open(sys.argv[2], "w", encoding="utf-8").write(yaml.safe_dump_all(keep))
PYEOF
if (cd "$ROOT" && TB_ENV=TEST "$PY" -m tools.trialbox doctor --platform --no-gpu --manifests "$D/no-backup.yaml" \
      > "$D/doctor-manifests.txt" 2>&1); then
  fail "doctor --platform passed on manifests without a backup job"
fi
grep -Eq "^FAIL +backup_job .*no backup job" "$D/doctor-manifests.txt" || fail "no FAIL backup_job on the manifests"
kubectl apply -f "$D/rendered.yaml" >/dev/null
k delete cronjob trialbox-backup --ignore-not-found
k delete job trialbox-doctor --ignore-not-found >/dev/null
kubectl apply -f "$D/no-backup.yaml" >/dev/null
k wait --for=condition=complete --for=condition=failed job/trialbox-doctor --timeout=600s >/dev/null || true
k logs job/trialbox-doctor > "$D/doctor-no-backup.txt" || true
grep -Eq "^FAIL +backup_job .*no backup job" "$D/doctor-no-backup.txt" || fail "no FAIL backup_job in the cluster"
doctor with-backup
grep -Eq "^(PASS|WARN) +backup_job " "$D/doctor-with-backup.txt" || fail "backup_job fails with the job in place"
echo "kind-day2: 1. doctor --platform fails without a backup job: ok"

# 2. a backup file appears on the share claim
rollout
k exec statefulset/db -- psql -v ON_ERROR_STOP=1 -U trialbox -d trialbox_wf -qc \
  "CREATE TABLE IF NOT EXISTS public.day2_marker (id int PRIMARY KEY, note text);
   INSERT INTO public.day2_marker VALUES (1, 'kind day 2') ON CONFLICT (id) DO NOTHING"
k exec deployment/lake -- sh -c 'echo "kind day 2" > /data/lake/day2-marker.txt'
job tb-day2-backup trialbox-backup || fail "the backup job"
PYIMG="$("$PY" -c 'import sys, yaml
for d in yaml.safe_load_all(open(sys.argv[1], encoding="utf-8")):
    if d and d.get("kind") == "CronJob" and d["metadata"]["name"] == "trialbox-backup":
        print(d["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["image"])' "$D/rendered.yaml")"
cat > "$D/share-check.yaml" <<EOF
apiVersion: batch/v1
kind: Job
metadata: {name: tb-day2-share-check, namespace: $NS}
spec:
  backoffLimit: 0
  template:
    metadata: {labels: {app.kubernetes.io/component: share-check}}
    spec:
      restartPolicy: Never
      automountServiceAccountToken: false
      securityContext: {runAsNonRoot: true, runAsUser: 10001, runAsGroup: 10001, seccompProfile: {type: RuntimeDefault}}
      containers:
        - name: check
          image: $PYIMG
          command: ["python", "-c", "import json, subprocess, sys; r = json.load(open('/backup/trialbox/backup-last.json')); print(json.dumps(r)); sys.exit(subprocess.call(['python', '-m', 'tools.trialbox', 'backup-check', '/backup/trialbox/' + r['file']['name']]))"]
          securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}}
          volumeMounts: [{name: share, mountPath: /backup, readOnly: true}]
      volumes: [{name: share, persistentVolumeClaim: {claimName: backup-share, readOnly: true}}]
EOF
k delete job tb-day2-share-check --ignore-not-found >/dev/null
kubectl apply -f "$D/share-check.yaml" >/dev/null
k wait --for=condition=complete job/tb-day2-share-check --timeout=300s >/dev/null || { k logs job/tb-day2-share-check; fail "the backup file on the share"; }
k logs job/tb-day2-share-check | tee "$D/share-check.txt"
grep -q '"ok": true' "$D/share-check.txt" || fail "backup-last.json does not record a good backup"
echo "kind-day2: 2. a backup file on the share claim: ok"

# 3. wipe and restore
k scale deployment --all --replicas=0
k wait --for=delete pod -l trialbox.io/tier=app --timeout=300s || true
k delete statefulset db --wait=true
k delete pvc db-pg-db-0 lake-data objects-data audit-data rulesets-data orch-data mail-data tb-secrets console-data tb-terminology \
  --wait=true
kubectl apply -f "$D/rendered.yaml" >/dev/null   # the claims and the database again, empty
k scale deployment --all --replicas=0             # nothing writes while the restore runs
k rollout status statefulset/db --timeout=600s
[ -z "$(k exec statefulset/db -- psql -U trialbox -d trialbox_wf -tAc "SELECT to_regclass('public.day2_marker')")" ] \
  || fail "the wipe left the marker table"
k create secret generic trialbox-backup-restore-key --from-file=backup.key="$D/backup.key"
job tb-day2-restore trialbox-restore 1800s || { k delete secret trialbox-backup-restore-key; fail "the restore job"; }
k delete secret trialbox-backup-restore-key
[ "$(k exec statefulset/db -- psql -U trialbox -d trialbox_wf -tAc 'SELECT note FROM public.day2_marker WHERE id = 1')" \
  = "kind day 2" ] || fail "the marker row is not back"
kubectl apply -f "$D/rendered.yaml" >/dev/null   # the services back to their replicas
rollout
[ "$(k exec deployment/lake -- cat /data/lake/day2-marker.txt)" = "kind day 2" ] || fail "the marker file is not back"
echo "kind-day2: 3. wipe and restore: ok"

# 4. a digest update and its rollback
NODE="$NAME-control-plane"
digest_of() {
  docker exec "$NODE" crictl inspecti "$1" | "$PY" -c 'import json, sys
d = json.load(sys.stdin)["status"]
print(next(r.split("@", 1)[1] for r in d.get("repoDigests") or []))'
}
D1="$(digest_of "docker.io/library/$PYIMG")" || fail "no repo digest for $PYIMG on the node (crictl inspecti)"
printf 'FROM %s\nLABEL org.trialbox.day2=update\n' "$PYIMG" | docker build -q -t trialbox-py:day2-update - >/dev/null
kind load docker-image --name "$NAME" trialbox-py:day2-update
D2="$(digest_of docker.io/library/trialbox-py:day2-update)" || fail "no repo digest for the rebuilt image"
[ "$D1" != "$D2" ] || fail "the rebuilt image has the same digest"
rel() {  # rel <trialbox-py digest> <out>: deploy/platform/release.json with trialbox-py pinned
  "$PY" - "$ROOT/deploy/platform/release.json" "$1" "$2" <<'PYEOF'
import json, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
r["images"]["trialbox-py"]["digest"] = sys.argv[2]
r["release_id"] = "kind-day2-" + sys.argv[2][7:19]
json.dump(r, open(sys.argv[3], "w", encoding="utf-8"), indent=1)
PYEOF
}
rel "$D1" "$D/r1.json"
rel "$D2" "$D/r2.json"
rm -rf "$D/u1" "$D/u2"
(cd "$ROOT" && "$PY" -m tools.trialbox platform-day2 update-overlay --site "$D/overlay" --release "$D/r1.json" \
  --out "$D/u1" >/dev/null)
kustomize build "$D/u1/next" > "$D/rendered.yaml"   # the baseline: the same build, pinned by its digest
kubectl apply -f "$D/rendered.yaml" >/dev/null
rollout
(cd "$ROOT" && "$PY" -m tools.trialbox platform-day2 update-overlay --site "$D/overlay" --current "$D/u1/next" \
  --current-release "$D/r1.json" --release "$D/r2.json" --out "$D/u2" | tee "$D/plan.json")
job tb-day2-pre-update trialbox-backup || fail "the pre-update backup"
kustomize build "$D/u2/next" > "$D/rendered.yaml"
kubectl apply -f "$D/rendered.yaml" >/dev/null
rollout
images_of lake | grep -q "$D2" || fail "lake does not run the new digest"
doctor update
grep -Eq "^(PASS|WARN) +image_digests " "$D/doctor-update.txt" || fail "image_digests fails after the update"
kustomize build "$D/u2/previous" > "$D/rendered.yaml"   # the rollback
kubectl apply -f "$D/rendered.yaml" >/dev/null
rollout
images_of lake | grep -q "$D1" || fail "lake does not run the old digest after the rollback"
images_of lake | grep -q "$D2" && fail "lake still runs the new digest after the rollback"
doctor rollback
grep -Eq "^(PASS|WARN) +image_digests " "$D/doctor-rollback.txt" || fail "image_digests fails after the rollback"
echo "kind-day2: 4. digest update and rollback: ok"

# 5. the log job
job tb-day2-logs trialbox-logs || fail "the log job"
echo "kind-day2: 5. the log job: ok"
echo "KIND-DAY2 PASSED"
