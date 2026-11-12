# 11. Cloud runs (owner's OK first)

Qualifying a model pair on a card (G1b runs through it): [the qualify section](11-qualify.md) (D-313).

GCP project `trialbox-demo`. Always use a private `CLOUDSDK_CONFIG` (and unset `CLOUDSDK_AUTH_ACCESS_TOKEN`), stop
every VM after use and check that it shows `TERMINATED`.

**The demo VM** (`trialbox-demo`, e2-standard-4, asia-east1-b, about US$0.15 an hour). `make demo-bundle` writes
`dist/trialbox-demo.tar.gz`; copy it to a bucket, add `deploy/gcp/demo-vm-startup.sh` and the image as metadata, start
the VM, and the console answers on port 80 (plain http, `TB_CONSOLE_SECURE_COOKIE=0`: put https in front before
sharing widely; the PoC testers use the PoC host instead, `deploy/gcp/poc-host.sh` and `demo/README.md`). Its
password comes from Secret Manager (`tb-demo-password`, asked once by `deploy/gcp/setup-gcp.sh`; T-119): a password
put in the metadata is refused and the VM does not start the demo. A restart resets the demo. The update path on it: `deploy/gcp/demo-vm-update.sh build <bucket>`,
then `run <bucket>` (a good bundle applied and checked with `e2e_simple`, a broken one rolled back; about one hour,
US$0.15).

**The GPU VM** (`tb-gpu-sim`, g4-standard-48 spot, one RTX PRO 6000, asia-east1-a, about US$2.74 an hour; the disk
with the weights is kept, so boot to serving is about 10–15 minutes). No script opens port 80 on it to the internet
(T-119): the older one-boot scripts below serve on `127.0.0.1:80` only, with a key made on the VM (`/root/tb-key`,
never in the metadata); reach them with `gcloud compute ssh tb-gpu-sim --zone asia-east1-a -- -N -L
8080:127.0.0.1:80` and read the key over the same ssh. `capture-serving-config.sh fetch` reads the record over ssh.

| Run | Script | About |
| --- | --- | --- |
| PRO 6000 profile, serving record, `public_e2e`, canary (done 2026-11-08) | `deploy/gcp/gpu-pro6000-run.sh` as startup script | 0.6 h, US$1.50 |
| 32 GB-capped pair (the 5090 stand-in) | `deploy/gcp/gpu-sim-startup.sh` (the usual startup script) | per run |
| serving record with hashes | `deploy/gcp/capture-serving-config.sh prepare`, start, `fetch`, stop | 0.5 h |
| N-12 on the deployed files (done 2026-11-08) | `tools/trec_ct_eval.py` against the VM | 0.85 h, US$2.30 |
| the complete-platform run with the scenario matrix (step 9) | `deploy/gcp/complete-run.sh` | `--estimate` (each hospital part from G1's measured 17,960 s at 50,000 patients, scaled with `--patients`); D-141 |
| the same on four VMs, with the embedding and profile benches | `deploy/gcp/complete-run.sh --vms 4 --parts g1,embed,profile` | about 5.5 h (a hospital part is 5.0 h, measured in G1), US$46; D-148 |

**The complete run is fail-safe** (D-141, after the 2026-11-09 incident: a killed driver left the VM on for an hour;
D-150, after the independent review of the four failed runs of that day). The workload runs on the VM; the VM stops
itself; the driver only uploads, polls and collects.

**Gate before any paid launch: the rehearsal** (D-150). `make rehearse` runs the real driver and the real VM script,
on the exact commit to be launched (it uploads `git archive` of HEAD, as the paid run does), in an Ubuntu 24.04
container that stands in for `tb-gpu-sim`: real apt, PyPI, Node.js, Playwright, the data downloads and nginx; strict
vLLM stand-ins (the API key is checked, any but the served name is a 404); fakes only for gcloud, the metadata
server, systemd, docker and the GPU (`tests/rehearsal/rehearse.sh` says what each is). About an hour, US$0. It must
end with `REHEARSAL PASSED`; no paid launch without it, and none from a commit it did not pass on. Its cases:

| Case | What it shows |
| --- | --- |
| `run-a` | a fresh disk, a bounded run at 500 patients (hospital-ja, public-ja, the gateway probe, emr-fhir, it-dump, MedTxt, TREC), driven with `--no-wait` and repeated `--collect`: setup, the data, both model servers' check, every part reported, no 404 or 401 at the servers, the report's HEAD = the commit, power-off once collected |
| `run-b` | the same disk, a new run: nothing kept from `run-a`, a fresh log |
| `served` | the judge serves a wrong name: `TB-SERVING-FAILED` before any part, the servers' logs in `results.tgz` |
| `no-upload` | nobody uploads: `TB-NO-CODE`, power-off after the grace |
| `hang` | a stuck, silent part and no driver: the idle watchdog powers off; `--collect` then gets the results from the stopped VM |
| `busy` | a part silent for 5 minutes but working (idle limit 2): it is never powered off as idle; it finishes; `--collect` gets it |
| `bucket` | `TB_BUCKET` set: the code and the results go through the bucket (a `gcloud storage` stand-in), not the door |

In every case the door is TLS on 443 with the driver's pinned certificate, the key and the TLS key come from the
Secret Manager stand-in (never the metadata) and their version is destroyed once collected, and `run-a`, `run-b`
and `bucket` capture the serving record on the "VM" (`docker inspect` of the two stand-ins, the weight hashes;
T-119). Some cases only: `make rehearse CASES=run-a,bucket`.

It needs docker (it starts a private `dockerd` when none answers and stops it afterwards), about 4 GB of disk and
the ports 443 and 8080 free; the evidence of each case stays in `$TB_REHEARSAL_DIR/evidence/<case>/`. Model quality
is not rehearsed (the stand-ins answer with the deterministic stub, so the canary may fail there): plumbing, names,
keys, setup, state and timing are, the layer every failure of 2026-11-09 was in.

1. `deploy/gcp/complete-run.sh --estimate --patients 50000` prints the hours and US$ per scenario (`--only TAG,TAG`
   for a bounded run). `--dry-run` prints every command and starts nothing.
2. The run: `export CLOUDSDK_CONFIG=<private folder> TB_SA_KEY_FILE=<key file, in place>`, then
   `deploy/gcp/complete-run.sh --patients 50000 --no-wait` (or `--detach`). Every command of the driver (the launch,
   each `--collect`, `--stop`, each VM's child, `--provision`, `--teardown`) first activates the service account from
   `TB_SA_KEY_FILE` (gcloud gets the file's path; the driver never reads it) and probes the token: a dead credential
   stops it at once with `credentials expired: re-activate` (G1 bug A2). It:
   * probes the credential (`gc_probe`), reads the GPU and CPU quota (read-only) and refuses when the VMs cannot run,
     and refuses unless every VM is `TERMINATED`;
   * sets the **cloud-side hard cap**: `gcloud compute instances set-scheduling tb-gpu-sim --zone asia-east1-a
     --max-run-duration=<estimate x 1.3, rounded up>h --instance-termination-action=STOP` (`--hours N` to change);
   * checks the VM's door (T-119): the VM has a service account (its scope is set to `cloud-platform` while it is
     stopped), and no firewall rule opens tcp:80 to it from outside while one opens tcp:443; else it refuses, with
     the command that fixes it; a `tb-key` an older driver left in the metadata is removed;
   * makes a fresh door: a random key, a TLS key and its self-signed certificate (0600 files, never printed), puts
     the key and the TLS key in Secret Manager as a new version of `tb-gpu-door`, and gives the VM only the secret's
     name and version and the certificate (`tb-door-secret`, `tb-door-version`, `tb-door-cert`);
   * puts `deploy/gcp/complete-run-vm.sh` on the VM as its startup script with the sha256 of the code, starts it,
     and uploads the code through the door: HTTPS on 443, the certificate it made as the only trust root and its
     public key pinned (`--pinnedpubkey`), no proxy; plain HTTP or any other certificate is refused (`git archive`
     of HEAD with `TB_HEAD.json`: local changes are not in the run; the VM refuses an archive with another sha256).
     Once the results are here the driver destroys the secret version.
3. On the VM: a systemd hard cap and a watchdog start first; then a pre-flight (docker with the NVIDIA runtime, the
   weights in `/models`, 50 GB free: else `TB-PREFLIGHT-FAILED`); then both model servers, which must be healthy,
   list exactly their served names, answer one chat call and refuse a call without the key, else
   `TB-SERVING-FAILED` and their logs in the results; only then `PRO6000-RUN-READY`. Setup installs git, the venv,
   Node.js, Playwright (Chromium must launch) and fetches the data git does not carry (`tools/fetch_run_data.py`: the
   CQL translator's `quick-5.4.0.jar`, MedTxt, TREC CT; a dataset it cannot fetch is named `TB-DATA-MISSING`, and
   its parts fail at once as "data missing" without using the card). The watchdog limits each phase (serving and
   setup 45 minutes, the code 35) and, in the run, powers off when no part has worked for 20 minutes (the run's own
   heartbeat follows the part's CPU, so a long silent SCREEN stays alive and a stuck one does not), and 30 minutes
   after the done marker (at once when the driver has collected). The model parts run in the run's own directory
   (`/var/lib/tb/runs/<run id>`) with `--resume --ocr tesseract`, through the gateway built as an installed box builds
   it; `results.tgz` is re-packed after every part.
4. Collect: `deploy/gcp/complete-run.sh --collect <run id>`, as often as wanted (each call is short: one look, the
   results so far, the report so far, "still running"; `--follow` polls to the end). The driver need not live through
   the run: the operator's shell may be capped at two hours, the run is not. When the VM has stopped with its
   results not yet collected, `--collect` starts it once in a **results-only** mode (no models, no run, a 20-minute
   cloud cap; it powers off as soon as the results are here; about US$0.20). Once every VM is done, it runs the walk,
   backup, update and scale on the stub here (at the run's `--patients`, OCR tesseract) and writes the report, whose
   head, host and run id are the VM's. A restart of the same run (`TB_RUN_ID=<run id> --shard i`) keeps the parts
   passed in that run at that HEAD; a new run never keeps anything.
5. Every gcloud call goes through `gc` (`deploy/gcp/gcloud-auth.sh`) and has a timeout (`GC_TIMEOUT_S`, 30 s, for
   reads, secrets and the token; `GC_OP_TIMEOUT_S`, 900 s, for start, stop, metadata and storage copies;
   `GC_IMAGE_TIMEOUT_S`, 3600 s, for a machine image; the reasons are in the script). An authentication error or a
   timeout re-activates the service account from `TB_SA_KEY_FILE` and retries once; when that fails too and no token
   comes, the call fails with `credentials expired: re-activate` instead of waiting (a G1 collect hung 10 minutes).
6. Afterwards: `gcloud compute instances describe tb-gpu-sim --zone asia-east1-a --format='value(status)'` must say
   `TERMINATED`, and `--format='value(metadata.items)'` must show no `tb-key`;
   `gcloud secrets versions list tb-gpu-door --filter=state:enabled` must list nothing once collected; `deploy/gcp/complete-run.sh --stop` stops it by hand and puts the usual startup script back (a VM
   started by hand after that runs both model servers with no watchdog: only its cloud cap stops it). Read
   `report.md`: its verdict is PASSED, FAILED (a part that ran failed a check) or INCOMPLETE (parts without a
   result: `pending` while their VM runs, `not run (VM stopped)` after; they count no check, G1 bug A5). A part that
   "crashed or never ran" is named in the headline, and a `profile` row whose path says
   "direct (the gateway refused...)" is a failed check, whatever else passed.

**The first launch after a failed one is bounded**: `deploy/gcp/complete-run.sh --patients 5000 --only
install,hospital-ja,scenario-gateway,scenario-emr-fhir --no-wait`, then `--collect <run id>`; read `report.md`, and only
then the full plan.

**Several VMs at once** (D-148). `--vms N` splits the run into N shards of whole parts (no part is split, so the
merged report is the single-VM report); VM 1 is `tb-gpu-sim` in the first zone, VM i is `tb-gpu-sim-i` in zone i of
`--zones` (one zone per region where the GPU quota is 1 per region). Each VM gets its own cap (its estimate × 1.3),
key, watchdog and results; the driver waits for all, merges, runs the stub parts and writes one report. `--parts`
adds the benches: `embed` (`tools/bench_embed.py`) and `profile` (`tools/bench_profile.py`).

The project had one GPU in all (`GPUS_ALL_REGIONS = 1`, `PREEMPTIBLE_CPUS = 0`: Spot VMs then draw on the regular
quota) when D-150 was written, so `--vms N > 1` is refused until the owner has the quota raised; the driver checks
it before any start or `--provision` and makes nothing it could not run.

1. The owner checks the zones and the quota (read-only; `--dry-run` prints these commands for the chosen zones):
   `gcloud compute accelerator-types list --filter='name~rtx'`, `gcloud compute regions describe <region>
   --flatten=quotas --filter='quotas.metric~RTX|CPUS'` and `gcloud compute project-info describe --flatten=quotas
   --filter='quotas.metric~GPUS_ALL_REGIONS'`.
2. `deploy/gcp/complete-run.sh --estimate --patients 50000 --vms 4 --parts g1,embed,profile` prints hours and US$
   per VM and in all; `--dry-run` with the same flags and `--zones` prints the plan and every command.
3. Once: `--provision --vms 4 --zones <z1,z2,z3,z4>` makes a machine image of `tb-gpu-sim` and the clones from it (a
   clone boots, powers itself off at once, and has a 30-minute cap in case it does not; its disk is kept and costs
   until `--teardown`).
4. The run: the same flags without `--dry-run`. `--collect <run id>` collects every VM; a VM that was preempted is
   started again with `TB_RUN_ID=<run id> deploy/gcp/complete-run.sh --shard <i>`; `--stop --collect <run id>` stops
   them all.

**Once, before the first run with the TLS door** (T-119): `deploy/gcp/setup-gcp.sh` (Cloud Shell) makes the secrets
`tb-gpu-door` (the deployer may add and destroy its versions only; the VMs' service account may read it) and
`tb-demo-password`; a firewall rule opens tcp:443 to `tb-gpu-sim` (best from the driver's address only: `gcloud
compute firewall-rules create tb-gpu-door --network <network> --allow tcp:443 --source-ranges <address>/32
--target-tags tb-gpu-door` and `gcloud compute instances add-tags tb-gpu-sim --zone asia-east1-a --tags
tb-gpu-door`), and any rule that opens tcp:80 to it is deleted (or its tag removed). The driver says which, before
anything starts.

Optional `TB_BUCKET=gs://<bucket>` moves code and results through a bucket (the VM's service account needs storage
access; the `bucket` case of the rehearsal); without it they go through the TLS door. A billing budget with a kill switch
is the last net; it needs billing permissions this project's service account does not have: the owner sets it.
