# 17. On a hospital platform

For a hospital that runs TrialBox on its own shared GPU platform (CGMH's B200) or, in the interim, on its private
cloud with GPU (D-211). The same images as the appliance; no `install.sh`. The platform team applies the manifests in
TrialBox's own namespace; Aimedics runs the install checks there; the hospital witnesses (IT pack §A.6).

**What the platform team gives TrialBox** (before the first apply; survey questions 49 to 53):

| Item | What | Checked by |
| --- | --- | --- |
| Namespace | TrialBox's own; nothing else runs in it | the isolation probe |
| Quota | a ResourceQuota with two GPU devices: **two MIG instances** on the shared card, the judge and the verifier each holding one (for example a 45 GB class instance for the judge and a 23 GB class one for the verifier; `nvidia.com/gpu` with the `single` MIG strategy or `nvidia.com/mig-<profile>` with `mixed`); never a time-slice or an MPS share (no memory isolation); CPU and memory at least the minimum `doctor --platform` prints | `quota`, `gpu_serving`, `mig_instances` |
| GPU evidence | the MIG configuration dump (`nvidia-smi mig -lgi`) as `TB_PLATFORM_GPU_SHARING=mig` with `TB_PLATFORM_GPU_EVIDENCE=<reference>`, and the layout as `TB_MIG_PROFILE` (one profile, or `judge=<profile>,verifier=<profile>`); optionally read access to Nodes (`components/node-read`) so the job reads the node's GPU labels itself | `mig_instances` |
| Storage | an encrypted storage class with ReadWriteMany; its specification and encryption setting as evidence; for the database's claim an encrypted block storage class (ReadWriteOnce, `TB_PLATFORM_DB_STORAGE_CLASS`, OPS-069) | `storage_encryption` (evidence reference), `db_storage` |
| Day 2 | the backup share as the claim `backup-share`, the backup public key as the ConfigMap `trialbox-backup-pub`, the site's zone on the CronJobs ([§26](26-platform-day-2.md)) | `backup_job`, `log_job` |
| Network | a CNI that enforces NetworkPolicy; the console's TLS proxy or ingress controller in a namespace labelled `trialbox.io/console-ingress=true` | `network_policy`, the isolation probe |
| Services | NTP, the directory (LDAP or OIDC), the SMTP relay, the backup share | `ntp`, `directory`, `mail_relay`, `backup_target` |
| Secrets | `trialbox-db` (`POSTGRES_PASSWORD`, `POSTGRES_WF_PASSWORD`, `TB_DB_URL`, `TB_HAPI_DB_URL` for the backup), `trialbox-mail` (optional), `trialbox-cloud` (optional), `trialbox-actor`, `trialbox-token-<service>` (key `token`) and the ConfigMap `trialbox-service-tokens`, made with `python3 -m tools.trialbox secrets init` on an admin workstation and created with `kubectl create secret`; **never** the key-encryption key, the `pid_map.key` or the `site_hmac.key` (WS-13.11: a hospital KMS or the steward's unseal; T-210) | `kek_custody` |
| Model key | the Secret `trialbox-model-key` (key `TB_LLM_API_KEY`, a random value of at least 32 characters, e.g. `kubectl create secret generic trialbox-model-key --from-literal=TB_LLM_API_KEY="$(openssl rand -hex 32)"`): the two model servers (`VLLM_API_KEY`), model-guard and the gateway read it, nothing else (D-177, D-409) | `model_key` |
| Weights | the model folders in the `models-data` claim (read-only to the servers); the pin job writes the site's pins to the `model-pins` claim | `gpu_serving`, `canary` |

**Apply.** A site overlay sits on top of `deploy/platform/overlays/shared-quota` (or `interim-cloud`): it sets the
namespace and the storage class, replaces `trialbox-settings` with the site's `settings.yaml`, merges the site's
values into `trialbox-env` (as `deploy/.env` on a box: `SMTP_HOST`, `TB_SITE_ID` ...) and `trialbox-platform`
(the platform's declarations: `TB_PLATFORM_STORAGE_CLASS` (required in VALIDATION and PRODUCTION),
`TB_PLATFORM_STORAGE_ENCRYPTED=yes`, `TB_PLATFORM_STORAGE_EVIDENCE`, `TB_BACKUP_TARGETS`,
`TB_PLATFORM_BACKUP_EVIDENCE`, `TB_PLATFORM_BACKUP_HOST`, `TB_NTP_SERVER`, `TB_DIRECTORY_URL`,
`TB_PLATFORM_API_SERVER` (the API server's endpoint addresses, `kubectl -n default get endpoints kubernetes`),
`TB_MIG_PROFILE`), and adds the egress policies:

1. `python -m tools.trialbox platform-egress --env-file <site.env> > egress.yaml` renders the egress allowlist of
   `deploy/egress.py` as NetworkPolicies (the same hosts as the appliance's nftables table; resolved now, so re-run
   it when an address changes) and the install-check job's own policy `trialbox-egress-doctor` (only the declared
   API server, NTP, directory, mail relay and backup hosts; an undeclared one gets no rule). Add `egress.yaml` to
   the site overlay's resources.
2. `kustomize build <site overlay> | kubeconform -strict -summary` (pinned: kustomize v5.4.3, kubeconform v0.6.7),
   then `python -m tools.trialbox doctor --platform --manifests <build output>` before anything is applied: it
   prints the quota minimum and refuses a `latest` tag.
3. `kustomize build <site overlay> | kubectl apply -f -`. The judge and the verifier do not start while
   `serving.env` reads `unmeasured`: that is on purpose (below).
4. **Pins.** The job `trialbox-pin` (`overlays/shared-quota/pin.yaml`) pins the pair from the `models-data` claim
   (`tools/pin_model.py --install shared-quota`: the builds `gemma-4-26b-a4b-it-sharedquota` and
   `qwen3.5-9b-sharedquota`, as `candidate`; a folder that is not the release's expected weights is refused) into
   the `model-pins` claim. The gateway reads its pins at start: `kubectl -n <ns> wait --for=condition=complete
   job/trialbox-pin`, then `kubectl -n <ns> rollout restart deployment/gateway`. After new weights: delete the job,
   apply again, restart the gateway. `champion` comes only from `trialbox eval qualify` and `pin_model --promote`.

**The model key and model-guard** (D-177, D-409). As on the appliance, the gateway never calls vLLM directly: the
Services `llm-service` and `llm-verifier` (the names `models/routing.yaml` calls) are model-guard, which wants the
key on every call and passes only `/v1/models`, `/v1/chat/completions`, `/v1/completions` and `/health`; vLLM is
behind `llm-service-vllm` and `llm-verifier-vllm`, which only model-guard reaches (NetworkPolicies
`trialbox-model-isolation` and `trialbox-model-guard`). `doctor --platform` (check `model_key`) checks the
manifests and, in the cluster, that model-guard refuses a call without the key and with another key (401) and an
unkeyed vLLM route (404). The doctor holds no key; a call with the key is the canary's, through the gateway.

**The `shared-quota` serving record.** The pair's context, sequences and memory fraction on its two MIG instances
are measured, never assumed: from the B200 qualification (T-114, WS-02.7), then on CGMH's own instances at IQ with
`tools/serving_config.py`. The record goes into the ConfigMap `trialbox-serving-record` (key `serving_config.json`),
its values into the overlay's `serving.env`. `python -m tools.serving_config measured shared-quota <record>` says
whether it counts (D-409): each server on its own MIG instance (`gpu_devices` a `MIG-` UUID, the two different:
one device for both is a time-slice), each naming its `mig_profile`, and each server's context at least the rule
for that profile (`MIG_MIN_LEN`: 8k on a 23 GB class instance, 16k on a 45 GB class one, 32k on 90 GB and larger);
the profiles must be the namespace's `TB_MIG_PROFILE`. A change of the instances is a CC6 change: measure again,
re-run the checks and the canary. The Docker form of the same profile is
`deploy/docker-compose.shared-quota.yml` (the MIG instance UUIDs and every serving value required, none defaulted).

**The install checks (IQ).** `kubectl -n <ns> delete job trialbox-doctor trialbox-canary --ignore-not-found`, apply
again, then `kubectl -n <ns> logs job/trialbox-doctor`. The doctor job writes `iq-evidence.json` to the
`iq-evidence` claim; the IQ protocol attaches it (TST-IQ-03). Every check is PASS, WARN, FAIL or SKIP; the job fails
on any FAIL. Re-run both jobs after every platform change (host OS, runtime, GPU driver, quota: RSK-37). Then the
isolation probe from a second namespace: `TB_INTEGRATION=1 TB_PLATFORM_NAMESPACE=<ns> pytest -m integration
tests/platform` (every TrialBox port refused, no volume mountable; `TB_PROBE_IMAGE` names an image the platform holds).

**The compose platform form** (a Docker host the platform team runs): `python -m tools.trialbox platform-images
--env >> deploy/.env`, then the appliance files with `deploy/docker-compose.shared-quota.yml` and
`deploy/platform/docker-compose.platform.yml` last; `docker compose ... config --format json >
deploy/site/compose.json`; `docker compose ... --profile doctor run --rm doctor` writes
`deploy/site/iq-evidence.json`. There the egress rule is the platform's firewall (`TB_PLATFORM_NETWORK_POLICY_EVIDENCE`
names it) and the quota its declaration (`TB_PLATFORM_QUOTA`, e.g. `gpu=2,cpu=16,memory=96Gi`).

**A release.** `release.json` names every image and its digest; `python -m tools.trialbox platform-images` writes the
component that pins them (`--check` in review). Until T-110's `release.json` lands, `deploy/platform/release.json` is
the provisional one, with no digest for the images not yet released: the doctor then fails `image_digests` in
VALIDATION and PRODUCTION.

**On a test cluster (no GPU).** `make images`, then `deploy/platform/kind-check.sh`: a kind cluster, the release's
images loaded, throw-away Secrets (and a random model key) and a ResourceQuota, a stand-in GPU (the node advertises
`SLICES` devices, default 2, with the labels of a B200 node with MIG on), the overlay applied with `TB_ENV=TEST`,
`TB_PLATFORM_GPU_STANDIN=1` (refused in VALIDATION and PRODUCTION), `components/node-read` and the doctor's egress
to the API server, the judge and the verifier as the vLLM stand-in of `tests/rehearsal` behind model-guard, every
workload rolled out, the doctor job's report read (`gpu_serving`, `mig_instances` and `model_key` pass,
`serving_record` and `canary` `skipped: stand-in device`), the isolation probe, the cluster deleted.
`SLICES=1 deploy/platform/kind-check.sh` is the one-instance case: the verifier cannot be scheduled and the doctor
fails `mig_instances` with that reason. It is what the CI job is to run; the job itself is not wired yet (the
workflow file is owned elsewhere).
