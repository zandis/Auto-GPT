**D-211 The `shared-quota` profile, `doctor --platform` and the platform manifests.**

Task: T-113 (WS-14.8 start, WS-11.8 code, WS-13.9 tests part). PR: this branch
(`agent/T-113-shared-quota-platform`). Date: 2026-11-10. Status: proposed (agent-to-agent review; the CGMH platform
team reads RUNBOOK §17 when a contact exists).
Source: `docs/reviews/2026-11-09-assessment-and-tasks.md` card T-113; MR-213; plan WS-14.8, WS-11.8, WS-13.9,
URS-ADM-20, RSK-36, RSK-37, RSK-43; IT pack §A.3, §A.6.

*One image set, three forms.* The appliance (`install.sh` and compose), the platform (Kubernetes:
`deploy/platform/base` with the overlays `shared-quota` and `interim-cloud`; or the compose platform form
`deploy/platform/docker-compose.platform.yml`), and the two-device form later, all run the same images. The platform
forms have no `install.sh` host steps: what the host steps did is either a Kubernetes object (NetworkPolicy, a job,
claims on the platform's storage class) or a declaration the platform team evidences (`trialbox-platform`
ConfigMap: storage encryption and its evidence reference, the backup target, NTP, the directory).

*Images from the release.* The base names each image by a logical name (`trialbox-py`, `trialbox-jvm`,
`trialbox-postgres`, `hapi`, `vllm`); the kustomize Component `components/release-images` is generated from `release.json` (`python -m
tools.trialbox platform-images`; `--check` and a unit test keep the two equal) and pins each image by digest. T-110's
`release.json` has not landed: `deploy/platform/release.json` is a **provisional** file
(`tb-release-images/0-provisional`: `images.<name> = {image: repository:tag, digest}`); only that map is read. An
image the release has not yet built (the two TrialBox images, the database image and vLLM today) has `digest: null`: the manifests then
carry its tag only, and `doctor --platform` fails `image_digests` in VALIDATION and PRODUCTION (a warning in DEV and
TEST). A `latest` tag or an image with neither tag nor digest is refused by the release loader, the manifest lint
and the doctor; an image that is not the release's, or a running container whose image id differs, fails.

*The database is D-204's image* (review fix, 2026-11-10). The platform forms run `trialbox-postgres:16-1` (Debian
postgres 16 with pgvector and PGroonga, `deploy/docker/db.Dockerfile`), never stock postgres: the release entry
`trialbox-postgres` carries `deploy/images.lock`'s image and digest (null until a release pins it), the db-init
ConfigMap carries byte-identical copies of every appliance db-init script (`20-extensions.sh` included), the
StatefulSet runs as the Debian image's postgres user (uid and gid 999) and its readiness probe is the image's
`tb-db-check`; the compose platform form's `POSTGRES_IMAGE` comes from the same entry.

*`shared-quota` is measured, never assumed.* In Kubernetes a GPU device (a whole card or one MIG instance) is given
to exactly one container, so the pair needs two devices: the judge and the verifier each request one
`nvidia.com/gpu` (the device plugin's `single` MIG strategy; `mixed` names `nvidia.com/mig-<profile>`, which the
quota check also accepts). The namespace's quota is therefore **two MIG instances** plus CPU and memory; the plan's
"a dedicated MIG partition" should read so (plan change requested). The serving values (context, sequences, memory
fraction per instance) have no default anywhere: the overlays' `serving.env` reads `unmeasured` (vLLM refuses to
start) and `deploy/docker-compose.shared-quota.yml` uses `${VAR:?...}` (compose refuses to start), until the
shared-quota serving record exists (T-114 on the cloud B200, then CGMH's own partition at IQ). `deploy/gpu_profile.sh`
names a MIG-enabled card `shared-quota`, which `install.sh` refuses: a shared host is not installed with it.

*`trialbox doctor --platform`.* The base checks plus twelve platform checks (`tools/trialbox/platform.py`):
`image_digests`, `quota` (the namespace's ResourceQuotas cover the workloads: `requests.*` against the sum of the
requests, `limits.*` against the sum of the limits, the lowest figure where several quotas bound one resource, and a
bounded limit every container sets; GPU devices included; no quota is a failure, the platform's fixed quota being
the contract), `storage_encryption` (evidenced, not tested: PR-19; `TB_PLATFORM_STORAGE_CLASS` is required in
VALIDATION and PRODUCTION and every claim must use it), `network_policy` (the default deny denies everything, the
model isolation is the shipped one, no rule of any policy is open: no ingress rule without `from`, no egress rule
without `to`, no `0.0.0.0/0` or `::/0`; the egress policies name exactly the allowlist's hosts and carry exactly the
ipBlocks rendered for them now; the doctor's policy, when present, is exactly the rendered one), `kek_custody` (no Secret holds the KEK, `pid_map.key` or `site_hmac.key`:
WS-13.11; T-210 adds the unseal), `ntp` (an SNTP query), `directory`, `mail_relay` (TCP probes from the namespace),
`backup_target` (D-187's off-box rule, or the platform's declaration), `serving_record` (the record exists,
validates and names the namespace's MIG profile; absent today, and the check says so), `gpu_serving` (exactly one
judge and one verifier workload by `trialbox.io/role`, each with exactly one GPU device, no other GPU workload, a GPU
quota of at least two; ready pods in a cluster) and `canary`. `--no-gpu` (or `TB_PLATFORM_NO_GPU`) makes the last
three `skipped: no device` (a new status, SKIP, which is not a failure) in DEV and TEST only: VALIDATION and
PRODUCTION refuse it (the command exits 1 before any check, and the checks fail if given it), so the evidence can
never read `passed` without the GPU checks. Any FAIL exits 1;
`--evidence` writes `iq-evidence.json` (`tb-iq-evidence/1`: the release id and sha256, the profile, every check)
for the IQ protocol (TST-IQ-03). It reads the cluster (the job's read-only service account; Secrets are read for
their names and data keys only, the values are dropped on receipt), rendered manifests (`--manifests`, before an
apply) or a compose configuration (`--compose-config`). The job's Role lists Secrets (`kek_custody` must see every
Secret, under any name) and never gets one by name. Its egress is not in the base: `platform-egress` renders
`trialbox-egress-doctor` from the site's declarations, the same way as the allowlist (one rule per declared host,
its addresses as ipBlocks): the API server (`TB_PLATFORM_API_SERVER`), NTP (`TB_NTP_SERVER`, UDP 123), the directory
(`TB_DIRECTORY_URL`), the mail relay (`SMTP_HOST:SMTP_PORT`) and the backup share (`TB_PLATFORM_BACKUP_HOST`). A host
not declared gets no rule (fail closed: the probe then fails). It mounts no patient data.

*One allowlist, two renderings.* `deploy/egress.py` gains `render_networkpolicy`: the same `allowlist()` that the
nftables table renders, as one `trialbox-egress-<service>` NetworkPolicy per service, the host kept in an annotation
(a NetworkPolicy cannot name a host; the addresses are resolved when it is rendered, as the nftables table is when
applied). A unit test renders both from one allowlist and asserts the same (service, host, port) and the same
addresses; the doctor compares the policies in the namespace with the allowlist.

*Isolation, tested.* `tests/platform/test_isolation_probe.py` (marker `integration`): from a throw-away second
namespace every Service port of the TrialBox namespace is refused and no TrialBox claim can be mounted or its volume
re-bound; a control probe inside the namespace shows the probe can see an open port.

*Evidence.* `tests/unit/test_platform_manifests.py`; `kustomize build deploy/platform/overlays/shared-quota |
kubeconform -strict` (kustomize v5.4.3, kubeconform v0.6.7, Kubernetes 1.31 schemas) valid.
*Not done here.* The kind job in CI (CI workflow files are owned elsewhere): `deploy/platform/kind-check.sh` is what
it is to run; it could not run where this was built (kind's node fails to start any container there: runc
"can't get final child's PID from pipe", a sandbox without nested containers), so acceptance (2) and (3) are open; the
KEK unseal (T-210); the serving record (T-114); `release.json` itself (T-110); the update path on the platform
(WS-14.8's update drill); `P-SHARED-QUOTA` and `P-INTERIM-CLOUD` in `models/routing.yaml`'s profile list (no route
restricts by profile today, so the gateway routes the same; the doctor's perimeter check iterates the listed ones).
