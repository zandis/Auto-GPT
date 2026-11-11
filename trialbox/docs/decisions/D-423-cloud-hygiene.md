# D-423 Cloud hygiene remainder: the door key through Secret Manager and pinned TLS, no port 80, the bucket path and the serving record rehearsed

- **Task:** T-119 (`docs/plan/28-master-plan-v6.md` §6.2.4, wave 1; as TB-ASSESS-01 §3.2)
- **PR:** this branch (`agent/T-119-cloud-hygiene`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** CR-048 (the cloud run's door key over plain HTTP); D-150 "Not done": the transport part of M-06, M-07
  (the bucket path not rehearsed), the serving-record capture not rehearsed. Real weight pins on the VM stay open
  (see Open)
- **Builds on:** D-141 (the fail-safe run), D-150 (the rehearsal as the gate), T-509 / D-330 (the PoC host already
  reads its secrets from Secret Manager and runs an image by digest)

## Context

The hosted demo goes to two external PoC testers. The cloud run's driver gave the GPU VM its API key as instance
metadata (`tb-key`): anyone with read access to the project, and every process on the VM, could read it, and it
stayed there after the run. The driver then used that key over plain HTTP on port 80 for the code upload, the
progress and the results. The older one-boot GPU scripts published the two model servers on port 80 too, and the demo
VM took its password from metadata, with `set -x` around it.

## Decision

1. **The door's secrets go through Secret Manager.** For each VM and run the driver makes a random key, a TLS key and
   a self-signed certificate (`deploy/gcp/door-tls.sh`, `door_make`; P-256, three days, name `tb-door`). The key and
   the TLS key go into Secret Manager as a new version of the secret `tb-gpu-door`; the metadata holds only the
   secret's name, the version number and the certificate. The VM reads the version with its own service account.
   Once the results are collected the driver destroys the version. A `tb-key` an older driver left is removed.
   `setup-gcp.sh` makes the secret once: the deployer may add and destroy its versions only, the VMs' service account
   may read it.
2. **The door is HTTPS on 443 only.** nginx on the VM listens on 443 with that certificate; nothing listens on 80.
   The driver's curl trusts only that certificate, pins its public key, allows only `https`, and bypasses any proxy
   (a re-signing proxy would fail the pin). Plain HTTP, another certificate or another key is refused (tests in
   `tests/unit/test_cloud_door.py`).
3. **The driver checks the VM before anything costs money.** It reads the VM (service account, scopes, network,
   tags) and the firewall rules, and refuses when a rule opens tcp:80 to the VM from outside the VPC or none opens
   tcp:443, with the command that fixes it. Internal and IAP-only rules do not count. When the VM's scope is not
   `cloud-platform` the driver sets it while the VM is stopped (same service account).
4. **No port 80 for the GPU VM anywhere.** The older scripts (`gpu-sim-startup.sh`, `gpu-fit-test.sh`,
   `gpu-pro6000-run.sh`, `gpu-swap-run.sh`) publish nginx on `127.0.0.1:80` only and make their key on the VM
   (`/root/tb-key`); they are reached over an ssh tunnel. `capture-serving-config.sh fetch` reads the record over ssh.
5. **The demo VM and the hosted demo.** `demo-vm-startup.sh` has no `set -x`, reads its password from Secret Manager
   and refuses one in the metadata. The PoC host's start-up script refuses metadata keys that look like secrets
   (password, token, accounts, `tb-key`), in a separate block so the PoC-mode change merges cleanly.
6. **The rehearsal.** A `bucket` case (code and results through a `gcloud storage` stand-in), Secret Manager and the
   firewall in the driver's gcloud stand-in, a gcloud stand-in on the "VM", and the serving record captured in
   `run-a`, `run-b` and `bucket` (`docker inspect` and `nvidia-smi` stand-ins, a synthetic file per weight folder).
   `check.py` checks no `tb-key` in the metadata, the door on 443, the version destroyed, the record's names and
   hashes. `make rehearse CASES=run-a,bucket` takes commas.

## Consequences

- Before the next paid run the owner runs `setup-gcp.sh` once, opens tcp:443 to the VM and closes tcp:80; the driver
  says so and starts nothing until it is done.
- The driver needs `openssl` (any Linux or Cloud Shell has it).
- Calls to the older scripts' model servers need an ssh tunnel.

## Open

- `make rehearse CASES=run-a,bucket` was not run in this pull request (it needs docker and about an hour); it is the
  gate before the next paid launch, as before.
- Checked only on the real cloud: `instances describe` shows no `tb-key` after a run (T-004's next run); the VM's
  gcloud reads the secret; the driver reaches 443 directly from where it runs.
- Real weight pins on the VM (M-09): the report still says "synthetic weight pins". The VM would have to place the
  real weights under `deploy/models` and pin them against the registry's expected manifests; that touches the run
  logic (`tools/complete_run.py`, `tools/scenarios.py`), which this card may not touch.
- The demo VM still serves plain HTTP on port 80 (its own section says to put HTTPS in front); the testers use the
  PoC host.
- Per-IP lockout and a run cap for the hosted demo (TB-ASSESS-01's goal) are left to Cloudflare Access in front of
  the PoC host (T-509); nothing more here.
