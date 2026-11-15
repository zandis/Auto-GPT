# 26. Platform day 2

**Reader:** hospital IT (an other install form: the hospital's own platform).

For the platform form (§17: CGMH's shared B200, or an interim private cloud): what the appliance does with host cron
and `docker compose exec` (backup, restore, logs, the audit archive, updates; §2, §5), done as Kubernetes objects in
TrialBox's own namespace (T-633, D-416). Everything here is in `deploy/platform/base/day2.yaml` and
`tools/trialbox/platform_day2.py`; `doctor --platform` checks it (`backup_job`, `log_job`, `db_storage`,
`pod_limits`).

## What runs

| Object | When | What it does |
| --- | --- | --- |
| CronJob `trialbox-backup` | nightly, 04:45 in the site's zone | one encrypted `.tbbak` (the appliance's format) of both databases and every data claim to the claim `backup-share`; `backup-last.json` beside it |
| CronJob `trialbox-logs` | daily, 00:20 in the site's zone | yesterday's pod logs (the site's day) and `COVERAGE.json` into the claim `logs-data`, pruning after `retention.logs_days`, the audit chain archived (verified before and after) |
| CronJob `trialbox-restore` | never (suspended) | a restore, only as `kubectl create job --from=cronjob/trialbox-restore` |
| `platform-day2 update-overlay` | on an update | the update overlay and its rollback overlay (below) |

**What the platform team adds for day 2** (on top of §17's list; survey questions 51a to 51c):

| Item | What | Checked by |
| --- | --- | --- |
| Backup share | the claim `backup-share` bound to the hospital's backup share (a PersistentVolume for the NFS or SMB share, or the share's storage class), ReadWriteMany; the files on it are encrypted to the hospital's key, so the share needs no encryption of its own | `backup_job`, `backup_target` |
| Backup public key | the ConfigMap `trialbox-backup-pub` (key `backup.pub`), from `python3 -m tools.trialbox backup-keygen` with hospital IT (§5); the private key goes in the sealed envelope, never in the namespace | the backup job fails without it |
| The FHIR store's URL | `TB_HAPI_DB_URL` in the Secret `trialbox-db` (`postgresql://hapi:<POSTGRES_PASSWORD>@db:5432/hapi`): without it the FHIR store is not in the backup | `backup_job` |
| Block storage | a storage class that is block storage (ReadWriteOnce), encrypted, for the database's claim `db-pg`: `TB_PLATFORM_DB_STORAGE_CLASS`, its specification as `TB_PLATFORM_DB_STORAGE_EVIDENCE` | `db_storage`, `storage_encryption` |
| The zone | `spec.timeZone` of the two scheduled CronJobs = `site.tz` (`TB_TZ`), in the site overlay | `backup_job`, `log_job` |
| Log egress | the log job reads the pods and their logs through the API server: `platform-egress` renders `trialbox-egress-ops` (the declared `TB_PLATFORM_API_SERVER` only) with the doctor's policy | `network_policy` |

A site overlay sets them, for example:

```yaml
patches:
  - target: {kind: CronJob, name: "trialbox-(backup|logs)"}
    patch: '[{"op": "add", "path": "/spec/timeZone", "value": "<site.tz>"}]'
  - target: {kind: StatefulSet, name: db}
    patch: '[{"op": "add", "path": "/spec/volumeClaimTemplates/0/spec/storageClassName", "value": "<block class>"}]'
  - target: {kind: PersistentVolumeClaim, name: backup-share}
    patch: '[{"op": "add", "path": "/spec/volumeName", "value": "<the share PV>"}]'
```

The backup and restore jobs mount the claims `console-data`, `orch-data` and `mail-data`, which are ReadWriteOnce: on a
platform with several nodes, TrialBox's pods stay on one node (a `nodeSelector` in the site overlay) or those claims
are on a class that allows several readers, or the jobs wait for their volumes.

## Where patient data lives and who can read it

Synthetic data only on a shared host until T-210's unseal is built and the hospital's key custody is in place
(OPS-069; §17, WS-13.11). Then:

| Where | Holds | Patient data | Who can read it |
| --- | --- | --- | --- |
| claim `db-pg-db-0` (block class) | the trial database `trialbox_wf` and the FHIR store `hapi` | yes, identified | TrialBox's pods; the platform's administrators (root on the node, the storage) |
| claims `lake-data`, `objects-data`, `orch-data`, `mail-data`, `console-data` (encrypted class) | the lake, documents, job outputs, mail, console state | yes | the same |
| claim `source-data` | the hospital's export, read-only | yes | the same, and the hospital's export job |
| claim `audit-data`, and `logs-data/audit-archive` | the audit chain and its archive | pseudonymous references | the same |
| claim `tb-secrets` | the site keys (`pid_map.key`, `site_hmac.key`) as files until T-210's unseal | the key to the pseudonyms | the same: this is why the shared host holds synthetic data only until then |
| claim `logs-data/services` | the pod logs (no rows, no file content: the services log names, counts and hashes) | no | the same |
| claim `backup-share` | the encrypted backups, `backup-last.json` | yes, encrypted | anyone with the share; only the holder of the private key (hospital IT's envelope) can open a backup |
| Secrets `trialbox-db`, `trialbox-token-*`, `trialbox-model-key` | connection strings and tokens | no | the platform's administrators (Secrets are readable to them); never the key-encryption key (`kek_custody`) |
| Secret `trialbox-backup-restore-key` | the backup private key | the key to every backup | only during a restore; deleted after it (`backup_job` fails while it is there in VALIDATION and PRODUCTION) |
| pod memory, the GPU's MIG instances | what is being processed | yes, while it runs | the platform's administrators (root on the node) |

The platform's administrators are root: they can read the volumes, pod memory and the Secrets. The responsibility
sheet names them (survey question 51b) and whether their access to the volumes is logged.

## Backup

The job takes the database's dump in one snapshot with the database image's own `psql` and `pg_dump` (the Python image
has no PostgreSQL client, D-23), then `trialbox backup` packs the dump with the claims, encrypts it to the public key
and writes `trialbox-<site>-<time>.tbbak` and its `.sha256` to `backup-share/trialbox/`, keeping 14. A backup of
the platform restores on an appliance and the other way round: the interim cloud's move to the final host is a
backup and a restore (D-211). The database is one point in time; the claims' files are read while the services run
(each file read once, read again if it changed while it was read).

```sh
kubectl -n <ns> get cronjob trialbox-backup                          # LAST SCHEDULE, and doctor --platform's backup_job
kubectl -n <ns> create job --from=cronjob/trialbox-backup tb-backup-now   # a backup now (before an update: always)
kubectl -n <ns> logs job/tb-backup-now --all-containers
```

The age alert of the appliance (36 hours) is the check `backup_job`: it fails in VALIDATION and PRODUCTION when the
last success is older than `TB_BACKUP_MAX_AGE_HOURS`. The platform's own monitoring watches failed Jobs.

## Restore (and the drill)

A restore replaces both databases and every data claim with the backup's. The box as it was is kept first as one
more encrypted backup in `backup-share/pre-restore/` when it holds data.

1. Scale the services to 0, so nothing writes: `kubectl -n <ns> scale deployment --all --replicas=0`.
2. Hospital IT creates the restore key from the envelope:
   `kubectl -n <ns> create secret generic trialbox-backup-restore-key --from-file=backup.key=<file>`.
3. Pick the backup: `newest` by default, or
   `kubectl -n <ns> set env cronjob/trialbox-restore TB_RESTORE_FILE=<file name>`; `TB_RESTORE_OLDER_OK=1` for a
   backup older than 14 days, `TB_RESTORE_OTHER_SITE=1` for another site's (a move to new hardware).
4. `kubectl -n <ns> create job --from=cronjob/trialbox-restore tb-restore-<date>`, then
   `kubectl -n <ns> logs job/tb-restore-<date> -c restore`: the rows are checked against the backup's own count
   before any file is touched; a failure leaves the claims as they were.
5. `kubectl -n <ns> delete secret trialbox-backup-restore-key` (D-126: the box never keeps the key to its backups).
6. Apply the build again (the services come back), then the doctor job.

Exit code 3 means the vendor reference packs are not loaded again (a backup leaves their rows out, D-187): load them
as after an install (`python -m tb_common.refdata load <pack>` in a pod with the packs), then run the doctor.

**The drill** (quarterly, §22): a restore on a second namespace or the kind cluster, timed;
`deploy/platform/kind-day2.sh` is the whole drill on kind (a marker row and file, a wipe, the restore).

## Logs and the audit archive

The platform keeps pod logs only until its rotation; the log job keeps the site's day of every pod in
`logs-data/services/<day>/<component>.log.gz` (each line `<pod>/<container> <time> <text>`) with `COVERAGE.json`.
A **log gap** (the job exits 1) is a pod that ran before the day began whose oldest kept line is later: the platform
rotated the start of the day away; ask the platform team for a larger log size, or forward the namespace's logs to the
hospital's SIEM. Then the audit chain: every closed day file copied, compressed, to `logs-data/audit-archive/` with
`MANIFEST.sha256`, the chain verified before and the archive after; nothing in `audit-data` is ever changed.

## Updates and rollback

A digest update (a rebuilt image of the same release, a security fix of a base image) moves only image digests:

```sh
python -m tools.trialbox platform-day2 update-overlay --site <site overlay> --release <new release.json> --out <dir>
kubectl -n <ns> create job --from=cronjob/trialbox-backup tb-backup-pre-update   # the dump first; wait for it
kustomize build <dir>/next | kubectl apply -f -                                  # the update
kubectl -n <ns> rollout status deployment --timeout=900s; then the doctor job (image_digests)
kustomize build <dir>/previous | kubectl apply -f -                              # the rollback, if needed
```

`next` is the site overlay with an `images` entry per changed image and the new `release.json` as the ConfigMap
`trialbox-release` (what `image_digests` compares the running images with); `previous` is the overlay that was applied,
untouched. The shape is `deploy/platform/overlays/update`. For the next update, `--current <dir>/next
--current-release <that release.json>`. A rollback after the new images migrated the database also restores the
pre-update backup. A new image name or repository is refused: that is a new release, whose manifests are applied
after the same backup. The tool refuses an update that would unpin an image.

## Noisy neighbours

MIG separates the GPU's memory and compute, not the CPU, memory, storage or network of the host (OPS-070). Every
container states its CPU and memory requests and a memory limit (`pod_limits`), so the scheduler keeps TrialBox's
share and the quota stops it taking more. The night's duration with the other tenants running is measured by T-319
(p95 over five nights); the first-call contact at night for TrialBox's pods is in the responsibility sheet (survey
question 51b). An error from another tenant can reset the card: the canary and the doctor job run again after it.

## Moving the database to block storage

A claim never changes class. A database made on the shared file system class moves by backup and restore: a backup,
the services and the database scaled to 0, the claim `db-pg-db-0` deleted, the StatefulSet deleted and applied again
with the block class (it makes a new, empty claim), then the restore above. `db_storage` names the claim until then.

## On kind

`KEEP=1 KIND_WORK=<dir> deploy/platform/kind-check.sh`, then `KIND_WORK=<dir> deploy/platform/kind-day2.sh`: the doctor
fails without the backup job (on the manifests and in the cluster), a backup file appears on the share claim, a wipe
and restore bring a marker row and a marker file back, a digest update of `trialbox-py` and its rollback run the new
and then the old digest, the log job runs.
