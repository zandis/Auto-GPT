# GPU VM hand-over (lane G to the integrator), 2026-11-16

**Reader:** the people who build TrialBox, and the integrator who runs the next pass on this VM.

Draft for `docs/handover/gpu-vm-handover-2026-11-16.md`. Lane G wrote it from the run log, the driver's code at
lane G's branch head `f49973efefffe7d7fbd190df59a470ac9b81de18`, and read-only `gcloud` calls made on 2026-11-16 at
about 02:30 UTC. It holds no secret, key, address, sign-in code or demo stop time.

Final at about 05:40 UTC, after the last launch. The GPU VM is TERMINATED with no launch in flight and its metadata reset (startup script only).

## 1. The machines

Project: `trialbox-demo`. Region `asia-east1` (Taiwan).

| | GPU VM | Demo VM |
|---|---|---|
| Name | `tb-gpu-sim` | `tb-demo-vm` |
| Zone | `asia-east1-a` | `asia-east1-a` |
| Machine type | `g4-standard-48` | `e2-standard-4` |
| GPU | 1 x NVIDIA RTX PRO 6000 (`nvidia-rtx-pro-6000`), 96 GB card | none |
| Provisioning | SPOT; on stop: STOP | STANDARD; on stop: STOP; 12-hour hard stop from each start (`--max-run-duration 12h`) |
| Boot disk | `tb-gpu-sim`, 400 GiB `hyperdisk-balanced`, 4,200 IOPS, 440 MB/s provisioned | `tb-demo-vm`, 30 GiB `pd-balanced` |
| Image | `common-cu129-ubuntu-2404-nvidia-580-v20261029` (Ubuntu 24.04, NVIDIA driver 580) | `debian-12-bookworm-v20261109` |
| Shielded VM | vTPM on, integrity monitoring on, secure boot off | vTPM on |
| Service account | the Compute Engine default service account | the Compute Engine default service account |
| Network tags | `tb-gpu`, `tb-gpu-door` | `tb-demo-vm` |
| State at writing | TERMINATED | TERMINATED |

A third VM exists: `trialbox-demo` in `asia-east1-b` (`e2-standard-4`, 60 GiB `pd-balanced`, Ubuntu 24.04). It is
the hosted demo of early November, created 2026-11-05 and last stopped 2026-11-08. Lane G does not use it. Its disk
bills while it is stopped (see e1-billing).

### What is installed on the GPU VM

Read by the probe launch (L4, 2026-11-15 08:50) and later launches:

- Docker 29.9.3 with the overlay2 driver and the **classic** image store (lane G switched it for the build, F6). The
  old containerd store's images were removed (F7, F8). Docker Compose v2.
- The NVIDIA driver 580 and Docker's GPU runtime. At idle the card shows 97.9 GB free.
- Python 3.12 with PyYAML 6.0.1 and cryptography 41; systemd 255 with `systemd-creds`; `/dev/tpmrm0`.
- Added by the driver when missing: Maven and OpenJDK 21 (for `make images`, F1), `tpm2-tools` (F9), `cron`.
- `nft` is present.
- `/models`: the model cache (about 48 GB): the judge's and the verifier's weight snapshots at the revisions the
  registry pins, the chat template, and the embedder's files (placed by `box_vm.py models-place`).
- `/srv/tb-build`: the build checkout of the last dev launch.
- `/opt/trialbox`: the installed box (the bundle's host tree, then `current -> releases/dev-<commit12>`),
  `deploy/.env` and `/opt/trialbox/deploy/settings.yaml` from the settings wizard, `/opt/trialbox/deploy/secrets`, `deploy/site` (the site pins).
- `/var/lib/tb`: the driver's state (run folders, accuracy sets, lane G's accuracy tools).

Before lane G's box runs, the VM's usual startup script was `deploy/gcp/gpu-sim-startup.sh`. It starts three private
containers (`judge`, `verifier`, `front`) with `--restart unless-stopped`. See trap T9.

### The demo VM

Made and run by `deploy/gcp/demo-vm.sh` (runbook 11, "The small demo VM"). It runs the demo image (stub model,
synthetic hospital) behind Caddy with TLS on tcp:443 only. The image is the bucket object
`gs://trialbox-demo-runs/trialbox-demo.tar.gz`, with its `.sha256` beside it. Part D4 of the owner's plan rebuilds
it from Monday's master (part D4, done by a separate worker; the object's `.sha256` beside it is the record). **The demo VM is not to be touched by anyone else through Tuesday's demo.**

## 2. Credentials and settings for every command below

Run from `trialbox/` of a lane G checkout (branch `claude/lane-g-box-accuracy`), with the repository's venv as
`.venv`.

    export CLOUDSDK_CONFIG=<a private gcloud config folder, never ~/.config/gcloud>
    export TB_SA_KEY_FILE=<the path of the service account's key file>   # the path only; gcloud reads the file
    export TB_BUCKET=gs://trialbox-demo-runs

The driver activates the account from `TB_SA_KEY_FILE` at the start of every command and re-activates it once when
a call fails on authentication (`deploy/gcp/gcloud-auth.sh`). See e3-access for the roles this needs.

## 3. Start, stop and check each VM

### GPU VM

Do not start the GPU VM with a bare `gcloud compute instances start`. A box run's startup script reads the VM's
metadata at boot. At the time of writing the metadata still holds the keys of the last launch
(`box-20261116T020018Z-29f69010a`, which has ended). A bare start would boot, see that the run has ended, upload its
results again and power off.

| What | Command | Cost |
|---|---|---|
| Is it off? | `gcloud compute instances describe tb-gpu-sim --zone asia-east1-a --format='value(status)'` | free |
| Start a run | `deploy/gcp/box-run.sh ...` (section 4). Refuses unless the VM is TERMINATED. | paid |
| Follow a run | `deploy/gcp/box-run.sh --collect <run id> --follow` (one look a minute) | free (the VM's hours run anyway) |
| Look once | `deploy/gcp/box-run.sh --collect <run id>` | free |
| The console lines | `gcloud compute instances get-serial-port-output tb-gpu-sim --zone asia-east1-a \| grep -E 'TB-(STEP\|STOP\|PROGRESS\|WATCHDOG\|STACK\|DISK)'` | free |
| Stop it | `deploy/gcp/box-run.sh --stop [<run id>]`: stops, waits up to 240 s for TERMINATED, then puts the VM back as it is kept (SPOT, `gpu-sim-startup.sh`, default service account, the `tb-*` keys removed) | free |

**How to tell it is healthy.**

- The run's `state.json` lists each step as `done`, and its last line in the serial log is `TB-STEP <step> done`.
- `records/stack.txt` (written at 02) lists every service `running healthy`. The 1157c9bf stack had 15 of 15.
- `parts/07-canary.json` says `"pass": true`.
- A boot after the first (a resume, or an `acc` launch) prints `TB-STACK up` before any step. `TB-STACK not healthy`
  means compose's wait timed out (900 s); the next step stops with its own log.
- During a long step, a `TB-PROGRESS` line every 60 s. It shows model calls, calls a minute, latency, refusals, the
  card's use and, in a set, the embed service's requests and memory.
- `TB-WATCHDOG ...: powering off` is the end of every boot. Read the reason on that line.

### Demo VM

The demo VM's commands are in `docs/handover/demo-2026-11-17.md` and the run sheet. In short:

    export TB_DEMO_ALLOW=any TB_BUCKET=gs://trialbox-demo-runs
    export TB_DEMO_VM_IMAGE=gs://trialbox-demo-runs/trialbox-demo.tar.gz
    export TB_DEMO_VM_IMAGE_SHA256=<the hex in the .sha256 object beside it>
    deploy/gcp/demo-vm.sh --estimate         # free
    deploy/gcp/demo-vm.sh --dry-run up       # free: prints every gcloud call
    deploy/gcp/demo-vm.sh up --yes           # PAID: starts the stopped VM (or creates it), 12-hour hard stop
    deploy/gcp/demo-vm.sh status             # repeat until the last line says "boot: DEMO-VM-READY" (about 10 min)
    deploy/gcp/demo-vm.sh links              # ONCE after READY: the two one-time lines; then the object is deleted
    deploy/gcp/demo-vm.sh down               # stop; checks TERMINATED

**Healthy:** `status` ends with `boot: DEMO-VM-READY`; the sign-in page answers 200 over TLS; a multipart post is
refused 403 (demo mode on). `boot: DEMO-VM-NOT-READY` or `boot: refused` gives the reason on the line above. The
links go to the people privately, never into a channel or a file.

## 4. The driver, step by step

Driver: `deploy/gcp/box-run.sh` (on this machine), `tools/box_run.py` (its helper), `deploy/gcp/box-install-run.sh`
(the VM's startup script: the work), `deploy/gcp/box_vm.py` (the VM's helper), `tools/public_accuracy/` (lane G's
accuracy tools, sent to the VM as a `git archive`; `onbox.py` is piped into the box's containers).

Every launch prints its estimate and cap first. The price constant is US$2.74 per VM hour, spot
(`tools/complete_run.py PRICE_PER_HOUR`; on demand is taken as 3 times that; neither was re-checked today). The VM
hours below are from the run log; US$ = hours x 2.74.

The step names in the table are the part files the VM writes (`parts/<step>.json`).

### 4.0 Before any paid launch (free)

    deploy/gcp/box-run.sh --estimate --mode validation --steps dev,acc --only jmed:300,tcga:500
    PYTHONPATH=libs:services:. .venv/bin/python -m tools.box_run validation-check   # exit 0 = can_run true
    PYTHONPATH=libs:services:. .venv/bin/python -m tools.box_run acc-ids --only tcga --rs-tag m2   # the ids, free
    deploy/gcp/box-run.sh --preflight <the launch's own options>   # every free check; exit 0 = the launch passes them

`--preflight` takes the paid launch's options unchanged (`--steps`, `--mode`, `--only`, `--commit`,
`--src-bundle`, `--acc-rs-tag`, `--acc-protocols`, `--acc-streams`, `--acc-deadline`, ...). It makes no gcloud call
and needs no `TB_BUCKET` or credentials, and it stops where the launch would first upload anything. It checks:

- **The protocol filter (D1).** Every id must be one of its set's ids under `--acc-rs-tag`. With tag `m2` the
  TCGA-BRCA protocol is `Gm2TCGA-BRCA`, so launch P1b's `G2TCGA-BRCA` is refused, and the refusal lists the ids
  that do exist. An empty filter is refused too.
- **The streams and budgets (D4, D7).** `--acc-streams` must name a set of the launch, with 1 to TB_WORKERS
  less one (3 by default). `--acc-deadline` and `--acc-min-start` must be seconds. The preflight prints how many
  protocols each set will have in flight: 3 for a compile-bound set, else 1.
- **The commit and the source bundle (D8).** A build or dev launch needs the full 40-character commit and
  `--src-bundle`. The bundle is cloned as the VM clones it, and the commit is checked out from it.
- **The metadata.** Every key the steps need is there, and no value looks like a key.
- **The validation-check.** This one runs only when the launch has `acc` in validation mode.

A launch runs the same checks first and refuses before anything is uploaded or started: exit 2 for the filter,
exit 6 for the preflight, exit 9 for a validation-check blocker.

### 4.1 Probe (the VM's facts, nothing built)

    deploy/gcp/box-run.sh --steps probe

- Writes `records/facts-vm.txt` (disk, image store, Python, TPM, GPU, model folders, a disk read rate).
- `--probe` on a `start` or `dev` launch reads the box's facts after 03 (`records/facts-box.txt`) and stops.
- L4 (2026-11-15 08:50): 00-facts 50 s; the launch 0.09 h, US$0.25.

### 4.2 The source bundle (by hand, before a build or dev launch)

The VM clones the commit from `gs://trialbox-demo-runs/r2/<release id>/src.bundle`. Since D8 (after launch P1b, whose
bundle came from a shallow checkout and could not be used) the bundle is made and proved here, and the driver
uploads it only once a clone of it checks the commit out:

    python -m tools.box_run src-bundle --commit <sha> --out /tmp/src.bundle   # refused in a shallow checkout
    deploy/gcp/box-run.sh --steps dev --commit <sha> --release-id dev-<commit12> --src-bundle /tmp/src.bundle ...

A bundle made by hand is proved the same way: `python -m tools.box_run src-bundle --commit <sha> --check FILE`.
The proof clones the bundle exactly as `b01-source` does (a plain `git clone`, then `git checkout --detach` of
the commit), so it fails for a bundle whose commit is not on a branch: a plain clone of such a bundle is empty. A
build or dev launch without `--src-bundle` is refused, because the bundle already in the bucket cannot be proved
from here.

### 4.3 Build: the commit's images, and (build route only) a signed bundle

Two routes. The evidence columns used **dev**: the images built on the VM from the commit, no bundle, no signature.

    # dev (images and tree only; sets the direct route by itself):
    deploy/gcp/box-run.sh --mode validation --steps dev,acc --release-id dev-<commit12> --commit <sha> [acc flags] --no-wait
    # build route (a bundle signed with a THROWAWAY key made on the VM; not a release):
    deploy/gcp/box-run.sh --mode validation --steps build --release-id val-<commit12> --release-seq 1 --commit <sha> --no-wait

| Step | What it does | Writes | Time (measured) |
|---|---|---|---|
| b01-source | clones `src.bundle`, checks out the commit | `/srv/tb-build/tb` | 15-17 s |
| b02-venv | `make venv scanners` (the run's `TB_SETTINGS_FILE` unset, F31) | the build venv | 21 s |
| b03-images | `make images` and the demo image | Docker images on the VM | 160 s (ac36aa21), 250 s (1157c9bf), 165 s (L8) |
| d04-tree (dev) | the checkout's host tree as `/opt/trialbox/releases/dev-<commit12>`, `current` points to it | the box tree | under 1 s |
| b04-gates (build) | `make trivy-db release-gates`, report mode for test-only mail images (F3) | `records/gates.json` | 340 s |
| b05-sign (build) | `tools/make_bundle.sh` with a throwaway key in tmpfs | the bundle | 521 s |
| b06-verify (build) | `verify_update.py`, the release record as a PRODUCTION box reads it | | 51 s |
| b07-upload (build) | bundle, `.sha256`, the key's public half to `r2/<id>/`; the local copy removed | `records/bundle.json` | 73 s |

The one complete build: `val-ac36aa21fdc1`, 29.6 GB, launch L5, 0.57 h, US$1.56. It is not a release: the gates
were in report mode and it is signed with a throwaway key.

### 4.4 Bring-up by the direct route (02 to 07)

The installer route (`install.sh --answers`) was tried twice and closed (F9, F10). The direct route brings the tree
up with the product's own commands in the installer's order. A `dev` launch uses it by itself. A `start` launch
uses it with `--direct`, or on a resume:

    deploy/gcp/box-run.sh --resume <run id> --direct

| Step | What it does | Writes | Time |
|---|---|---|---|
| 01-bundle (start only) | fetch, sha256, manifest check, host tree unpacked | `records/release.json` | 75 s |
| 02-install (direct) | host packages; weights placed and bound into `/opt/trialbox/deploy/models`; old private servers removed; `secrets init`; `pin_model --install` as root (F11) and the three pins checked; site keys made, not sealed; database and `db-up`; `compose up --wait` (900 s); the serving check | `deploy/site/registry.site.yaml`, `records/stack.txt` | 281 s (bundle tree), 145 s and 157 s (1157c9bf) |
| 03-wizard | the box says VALIDATION (`deploy/.env`) | | under 1 s |
| 04-pin | the site pins are there | | 5 s |
| 05-serving | the serving record of the running pair | `records/serving_config.json` | 25-30 s |

### 4.5 G-1 (06-g1)

Runs in every `start` or `dev` launch. It checks:

- the template the judge server was started with, against the registry;
- each model server's image digest against `deploy/images.lock`;
- the weights against their pins (`pin_model --verify-all`);
- the prompt versions served;
- the token half: the server's ids (model-guard's keyed `/tokenize`, asked from the gateway's container) against the
  weights folder's tokenizer, offline in the model server's image, on 20 prompts.

Writes `records/identity.json`, `identity-box.json`, `g1-tokens.json`, `chat_template.folder.jinja` and, from
13d158b2 on, `g1-token-span.json` (positions around the first difference, decoded). Time: 27 s.

### 4.6 The canary (07-canary), and the canary through the box's own gate

- 07-canary runs `python -m tools.trialbox selftest --deploy /opt/trialbox/deploy` with the **host's** Python. It
  is not the box's own canary gate. On 1157c9bf it passed (54 cases: 52 correct, 2 disagreed, 0 wrong) in 220-260 s.
- The owner's B2 asks for the canary through the box's own gate (`make canary`, `python -m tools.trialbox selftest`
  in the box, or the admin page's "Run now", `canary_gate.run_canary`). The gate's record decides whether
  note_block can exclude (part A1).
- **07g-gate** (from b1aed1e0) does it by the gate's own way in: it restarts the orchestrator once the model servers
  answer, and the orchestrator runs the full pair canary at start (`canary_gate.startup`). About 3 to 4 minutes.
  - The admin "Run now" (`POST /models/canary`) refuses lane G's tokens (HTTP 403: the route is the console's).
  - `GET /models` needs a token too (`protect_reads`), so 07g cannot read the gate itself and its record stays empty.
  - The proof is the next SCREEN's `judging` block in `work/screen/<ruleset>.json`: on master it read
    `may_block: true`, `note_block_code: "ok"` (run box-20261116T023816Z-b266f9b7f, 05:15).
  - Before that, the gate held a failed record from the stack's first start ("gateway refused judge: upstream_down",
    0 of 54 answered): the orchestrator's start-up canary met model servers that were still loading.

### 4.7 Qualify (08-qualify) and 09 to 12

    deploy/gcp/box-run.sh ... --qualify-timebox 300                      # a probe: ended after 300 s
    deploy/gcp/box-run.sh ... --qualify-args "--items 60 --repeat-items 40"
    deploy/gcp/box-run.sh ... --skip 08-qualify                          # left out, said, never a pass

- It runs `trialbox eval qualify --box` in the box's Python image on `trialbox-net`, with the operator's token, the
  host's Docker socket, `TB_HOST_PROFILE=poc`, `TB_CODE_IMAGE` (the image's id) and `TB_HOST_GPU` (read on the host).
  The same commit's `tests`, `docs`, `eval` and `images.lock` are mounted read-only (F13).
- It writes `records/qualification.json` (if it finishes) and `logs/08-qualify.checkpoints.jsonl`.
- L7: the full qualify ran 1 h 52 min with no visible progress and was stopped. L8 probe (300 s): pin, licence,
  schema, longest_prompt, log_marker and canary passed; serving_record failed.
- 09/10 promote only from a passing record (none so far: "not promoted"). 11-resolve 1 s. 12-doctor 0.3 s; it runs
  from the host, so its serving FAIL is not real (chain review B8).
- B8 (master, 30 minutes, `TB_HOST_PROFILE=poc`, `TB_CODE_IMAGE`, `TB_HOST_GPU`):
  - serving_record passed (D-881, D-889);
  - licence, schema, longest_prompt, log_marker and canary passed;
  - pin failed, by lane G's fault F36 (an earlier run's `eval/` mounted over the image's; fixed in 2063e371);
  - pair_gate had 1,468 of 2,986 items done at 1,500 s and did not finish inside the box;
  - the later gates were not reached.

### 4.8 The accuracy sets (50 to 79)

    deploy/gcp/box-run.sh --mode validation --steps dev,acc --release-id dev-<commit12> --commit <sha> \
      --only jmed:300,tcga:500 --acc-deadline "jmed:1350 tcga:2700" \
      --acc-protocols "tcga:G2TCGA-BRCA" --acc-rs-tag 2 --skip 08-qualify --no-wait

The flags:

- `--only set:size,...`: the sets in the order given (cheapest first).
- `--acc-deadline`: each set's time budget in seconds ("set:s ..." or one number).
- `--acc-protocols "set:RS1,RS2"`: only these protocols.
- `--acc-rs-tag`: new ruleset ids for a second run on one box (F29).
- `--site-env "TB_MEM_EMBED=16g"`: a `TB_MEM_*` limit in `deploy/.env`. The owner's plan leaves the embed service at
  master's own 6 GB for part B, so do not pass it there.
- `--acc-tripwire`: defaults to `TB_GATEWAY_PHI_TRIPWIRE=off` (D-506, D-511).

| Step | What it does | Time |
|---|---|---|
| 50-acc-tools | the tools from the bucket, unpacked on the VM (never into the box) | 10 s |
| 51-acc-settings | `TB_JOBS_PER_SENDER_PER_DAY=0`, `TB_MAIL_PER_RECIPIENT_PER_DAY=0`, the mail id, the tripwire setting; every service but the model servers recreated | 36-41 s |
| 52-acc-routes | would the box route the compile's and the screen's calls; which embedder; stops here if not | 2-28 s |
| 53-acc-data | `public_accuracy fetch` and `build --for-box` per set (a set whose source fails is left out, said) | 10 s (jmed), 661 s (all sets) |
| 54-acc-ingest | the sets' feeds merged, optional tables and the validation threshold (F17, F20), the box's ingest | 101 s (jmed), 776 s (all sets) |
| 6x-acc-<set> | per set, `box_vm.py acc-set`: FEAS by mail, the workbook, APPROVE by the box's reviewer, SCREEN; the pseudonym map; audit and raw traces | see below |
| 79-acc-result | the sets' counts | under 1 s |

Each set, measured on 1157c9bf (L9):

| Set | Time | Note |
|---|---|---|
| jmed, 2 protocols | 60-64 s | 594 patient-criterion rows; no model call (no note criterion) |
| tcga BRCA, 500 patients | 1,352 s | 1,014 model calls, embed service at 16g |
| tcga COAD, HNSC, KIRC, LIHC | 1,245, 1,275, 1,314 and 1,224 s | about 1,010 calls each |
| trec2023 | 5,256 s of a 5,400 s budget | 46 of 297 protocols started |
| sigir | 2,768 s of a 2,700 s budget | 34 of 104 started |
| chia (compile only) | its whole 3,600 s budget | |
| jrct | started, then stopped by lane G | |

A set writes, the moment it ends, `gs://.../boxruns/<run>/acc/<set>.tgz`. At every checkpoint it writes
`acc-partial/<set>.tgz`. On the VM: `/var/lib/tb/acc/<run>/<set>/{built,work}`.

`work/` holds `answers.json`, the per-protocol progress, `set-clock.json`, `pidmap.json`, `gateway-audit.json`,
`raw-traces.json`, `services.log`, `embed-mem.tsv` (each second) and each protocol's screen JSON (F32).

The gold stays in `built/gold`. It never goes into the box.

### 4.9 Collect

    deploy/gcp/box-run.sh --collect <run id> [--follow]

- It fetches `results.tgz` and every set's tgz, fetching a set again when its object changed (F24).
- It scores each set here, outside the box (`tools.box_run acc-score`).
- It writes `.cache/box-run/<run>/{results.tgz,report.md,summary.json,acc/<set>/score.json,acc-score.json}`.
- When the run has ended and the VM is TERMINATED, it puts the VM back (`reset_vm`).
- No VM cost of its own.

### 4.10 Resume and redo

    deploy/gcp/box-run.sh --resume <run id> [--only set:size,...] [--direct] [--qualify-args "..."]
    deploy/gcp/box-run.sh --resume <run id> --redo 60-acc-jmed [--acc-deadline ...] [--acc-protocols ...] [--site-env ...]

- A resume sends this tree's startup script and helper, the launch's own keys again (F2), and a new `tb-retry`.
- The VM clears the stopped step (its part kept as `logs/<step>.stop-<retry>.json`) and runs it again. Finished
  steps are kept. Lane G's tools are fetched again.
- `--redo` runs a finished step again. A set starts from no work: its earlier work is kept as
  `logs/<step>.work-<retry>`. It mails under new mail ids (F28). Its clock and any slowdown it measured are cleared.
- `--redo`, `--acc-deadline`, `--acc-protocols` and `--site-env` hold for that launch only (F24).
- The cloud cap is the launch's `cap-hours` again.
- Each resume costs a boot and the stack's start: about 2.5 min to `TB-STACK up` on L9 resume 3, plus model loads.

## 5. Where things are

### The bucket: `gs://trialbox-demo-runs` (STANDARD, regional `asia-east1`, soft delete 7 days)

Size on 2026-11-16 at 02:30: 30,760,471,165 bytes in all.

    boxruns/<run id>/
      results.tgz              the run so far (uploaded after every step and at every checkpoint)
      acc-tools.tgz            lane G's accuracy tools at the driver's commit
      acc/<set>.tgz            a finished set: built/gold, built/site-provenance, work
      acc-partial/<set>.tgz    a set in flight, at its last checkpoint
      POWER-CYCLE-REQUEST      G-9 only
    r2/<release id>/
      src.bundle               the commit's git bundle (about 54 MB each)
      trialbox-<id>.tar(.sha256), throwaway-signing-key.pub   (build route; val-ac36aa21fdc1: 29.6 GB)
    r2/models/e-embed-1.sha256  the embedder's file list (public names and sha256s)
    runs/                      the complete runs of 2026-11-12 to 14 (about 0.39 GB)
    trialbox-demo.tar.gz(.sha256)   the demo image
    demo-vm/                   the demo's one-time codes, deleted by `demo-vm.sh links`

`records/` and `logs/` are not separate bucket folders. They are inside `results.tgz`.

### A run folder

On the VM, `/var/lib/tb/boxruns/<run id>/`. The same content is in `results.tgz`:

    state.json          each step: started, done or stop; attempts; boots; seconds; the run's end; kv (set clocks,
                        sender, reviewer, measured slowdown, redo attempts)
    vm.log              the run's own log across boots
    parts/<step>.json   per step: status, started, ended, seconds, attempts, detail (the notes), pass, stop reason and
                        the last 20 lines of its log
    logs/<step>.log     the step's full output; <step>.notes; <step>.checkpoints.jsonl (every 60 s);
                        <step>.stop-<retry>.json and <step>.redo-<retry>.json (earlier attempts); <step>.work-<retry>/
    records/            disk.json, facts-*.txt, stack.txt, serving_config.json, identity*.json, g1-tokens.json,
                        chat_template.folder.jinja, g1-token-span.json, qualification.json, acc-settings-*.json,
                        acc-routes.json, production-resolves.txt, doctor.json, release.json, bundle.json
    acc/<set>/answers.json
    cap-used-s, retry-seen

On the VM, also:

- `/var/log/tb-boxrun.log` (the console; the previous boot's as `.prev`);
- `/var/log/tb-boxrun-run.log`;
- the serial port.

Locally, `.cache/box-run/<run id>/` holds:

- `md/` (the metadata, one file a key) and `metadata-keys`;
- `cap-hours` and `validation-check.json`;
- `acc-tools.tgz`;
- the collect's outputs.

## 6. The frozen commits

| Column | Commit | What it is | Driver commits used |
|---|---|---|---|
| Frozen | `1157c9bfa514e71cdd4f6e430250665c0c9481a2` | master at train 28 (`0d9ebeb3`) merged into lane G's run tooling; images built on the VM (dev) | f2288a50 to d44e3978 (L7 to L9) |
| Master at train 36 | `93b6c945baecbde97ffd1f68b1a867f0dc3a4374`, merged into lane G as `ea10bf2ccee0b849c8b34fe65b1e75685fe23c9d` | the launch of 02:00 (L10, driver `29f69010`) stopped at b03 (F31) | run `box-20261116T020018Z-29f69010a`, stopped at b03 (F31); no figure |
| Master, train 37 or later | master `2d35403676d1afe8c82724a28b53d0502ddd7a83` merged into lane G as `f49973efefffe7d7fbd190df59a470ac9b81de18` (head at writing) | part B's column | frozen at `b266f9b7f45194afb86b217619f0da78156f0eaf` (images built on the VM from it); run `box-20261116T023816Z-b266f9b7f` (5 boots); driver commits f49973ef to b1aed1e0 |

## 7. Workarounds still in force

| # | Workaround (where) | Why | The master fix that replaces it |
|---|---|---|---|
| W1 | Every compose call exports `TB_SETTINGS_FILE=./settings.yaml` (`dc()`) | F16: without it the services mounted `settings.example.yaml` | D-888, train 35 (the site settings file on every start path). Keep it until the master column shows each service on `settings.yaml` (B11 checks) |
| W2 | The build's `make` calls run with `TB_SETTINGS_FILE` unset | F31: master's `fetch_jvm_deps.sh` reads it as a build-tree path | none needed (lane G's own) |
| W3 | Qualify gets the same commit's `tests`, `docs`, `eval`, `images.lock` mounted read-only | F13: the image lacks them | D-838, train 30. The host GPU facts and the code identity are master's own settings (D-881, D-889, train 32) |
| W4 | The direct route instead of `install.sh`; `pin_model --install` as root | F10 (a half install cannot be re-run), F11 (pins cannot be written as uid 10001) | none yet (the installer hand-over is #717) |
| W5 | Site keys made by `adapter keys-init`, not sealed (`TB_BOX_DEFER_SEAL=1` on the installer route) | F9; the owner's ruling for a public-data PoC | none (a ruling, not a fault) |
| W6 | The weights' bind into `/opt/trialbox/deploy/models` made again at every boot, and the model servers and the embedder restarted | F15 | none yet (no systemd unit on the direct route) |
| W7 | `feed_completeness.optional_tables` from the feed; `validation_error_max_pct` 10 | F17, F20: a public-data site lacks tables and birth dates | none needed (site settings, as a hospital sets them) |
| W8 | `TB_GATEWAY_PHI_TRIPWIRE=off`, `TB_JOBS_PER_SENDER_PER_DAY=0`, `TB_MAIL_PER_RECIPIENT_PER_DAY=0` | public data; one sender mails hundreds of jobs | none needed (declared settings, D-506, D-511, D-775) |
| W9 | `TB_MEM_EMBED=16g` (`--site-env`) | F27: the embed service lost mid-SCREEN at 4g | D-900 and D-890, train 33 (the embed service and its 6 GB limit). D-902, train 34 (SCREEN waits out an embed outage). Do not pass it on master (owner's plan, part B) |
| W10 | Classic Docker image store on the build VM | F6: the bundle check compares config digests | none yet (lane D's red) |
| W11 | `TB_TZ=UTC` for `make_bundle.sh`'s image listing (build route) | F5 | none yet (lane D's red) |
| W12 | Release gates in report mode for the test-only mail images; the demo image built in b03/b04 | F3, F4 | none yet (lane D's red on the mail images' CVEs) |
| W13 | New mail ids on a redo; new ruleset ids (`--acc-rs-tag`) for a second run | F28, F29: the box keeps one job per mail id and an approved ruleset version | none needed (the product's design) |
| W14 | A program argument over 100 KB goes in the program text | F30 | none needed (the kernel's limit) |
| W15 | The old containerd store's images removed before b02/b05 and at 01 | F7, F8 | none needed (VM housekeeping) |
| W16 | G-1's token half reports the extra token as a result, not a stop | the extra token at position 22 | D-880, train 30 |

## 8. The watchdog, the checkpoints, the time budgets and the stop rules

**On the VM** (`box-install-run.sh`; each one a metadata setting with its reason):

- **Cost cap.** `tb-max-minutes` = the sum of the launch's group caps x 60 - 5. A systemd timer powers off at the cap.
  The used seconds are kept across boots (`cap-used-s`). A resume starts the count again.
- **Group caps** (`tools/box_run.py GROUP_CAP_HOURS`): build 2 h, start 4 h, dev 3 h, probe 1 h, g6 7 h, g9 2 h,
  g10 2 h. acc = the plan's high bound of the chosen sets x 1.3, whole hours, at most 24 h.
- **The cloud's own cap.** `--max-run-duration` = the same hours, with `--instance-termination-action=STOP`.
- **Watchdog.** No heartbeat for `tb-idle-minutes` (20) powers off. Each of these counts as a heartbeat: the step's
  log growing; disk I/O (`WATCH_IO`: the install and the stack's start); the card busy (`WATCH_GPU`: qualify and the
  sets); a set's job changing state.
- **After the end.** DONE and uploaded: off at once. DONE and not uploaded: off after `tb-done-grace` (30 min).
- **Checkpoints.** Every `tb-progress-seconds` (60 s) during a long step, written to:
  - a `TB-PROGRESS` line;
  - `logs/<step>.checkpoints.jsonl`;
  - `results.tgz` uploaded;
  - in a set, `acc-partial/<set>.tgz`.

  A stop of any kind leaves the last checkpoint and every finished protocol.
- **Healthy wait.** `tb-healthy-minutes` (20) for a model load.
- **Jobs.** `tb-acc-job-minutes` (60) is the longest single FEAS or SCREEN job.
- **Set budget.** Each set's budget is `--acc-deadline` if given. Otherwise it is 1.5 x the plan's high bound x the
  measured slowdown (4 before it is measured), and at least 600 s (`tb-acc-min-deadline`). A set cut by its budget
  keeps what it finished and says so.
- **The gate set (F22).** The first set must answer at least one patient (or, compile-only, compile one protocol).
  Otherwise the run stops. A later set that answers nothing is "not scored, because", and the run goes on.
- **A stop.** A failed box command is the step's STOP: no repair on the VM. The part keeps the reason and the last
  20 log lines, and the run ends. A test rule not met is `"pass": false`, and the run goes on.

**The owner's rules** (plan of 2026-11-16):

- US$210 in all (D-516). Before each launch, post the estimate, the worst case and the running total on #639.
- Stop any launch more than 50 % over its estimate.
- Part B stops at a running total of US$130.
- If money runs short, drop in this order: B12, B9, B5, B7, B10, B11, B8. Never drop B1 to B4 or B6.

## 9. Spend log

US$2.74 per VM hour (spot). Lane G's spend before step 1 was US$59.00. The disk and the bucket are not in these
figures (see e1-billing).

| Launch | Run id | What | VM hours | US$ | Running total |
|---|---|---|---|---|---|
| before | | lane G's earlier GPU runs | | 59.00 | 59.00 |
| L1 | box-20261115T060826Z-f6bcc176 | build f6bcc176: 1 attempt + 4 resumes, stopped F1 to F5 | 0.61 | 1.68 | 60.67 |
| L2 | box-20261115T073901Z-e7504de38 | build e7504de3, stopped F6 | 0.22 | 0.60 | 61.27 |
| L3 | box-20261115T080047Z-5618bd840 | build 5618bd84, stopped F7 (disk full) | 0.35 | 0.96 | 62.23 |
| L4 | box-20261115T085016Z-876ff6506 | probe | 0.09 | 0.25 | 62.48 |
| L5 | box-20261115T091037Z-ac36aa21f | build ac36aa21 + resume: complete, bundle 29.6 GB | 0.57 | 1.56 | 64.04 |
| L6 | box-20261115T094747Z-4c7c47017 | start: installer (F9, F10), then direct; G-1, canary; qualify shake-down | 1.52 | 4.20 | 68.24 |
| L7 | box-20261115T123832Z-1157c9bfa | dev 1157c9bf: images, stack, G-1, canary; full qualify stopped after 1 h 52 min | 2.10 | 5.75 | 73.99 |
| L8 | box-20261115T150421Z-f2288a501 | phase B probes: qualify 300 s, jmed (F16, F17, F18) | 0.55 | 1.52 | 75.51 |
| L9 | box-20261115T162830Z-04138db7c | phase C, acc only, 10 boots: jmed, tcga (5), trec2023, sigir, chia, jrct | 6.85 | 18.77 | 94.28 |
| L10 | box-20261116T020018Z-29f69010a | dev,acc on master train 36: stopped at b03 (F31) | 0.06 | 0.16 | 94.44 |
| M1 | box-20261116T023816Z-b266f9b7f | master train 37 (b266f9b7): images, G-1, canary, qualify 30 min, jmed, tcga BRCA twice; 5 boots (F33 to F38) | 2.32 | 6.35 | 100.79 |

Notes on the table:

- L10 is not in the run log. Its hours come from the VM's own start and stop times (02:00:47 to 02:04:18 UTC,
  211 s), read with `gcloud compute instances describe`.
- `box-20261116T015907Z-29f69010a` has only `acc-tools.tgz` in the bucket and no `results.tgz`. Lane G reads it as a
  launch that did not start the VM. This was not confirmed.
- L1 to L9 sum to 12.86 VM hours. Their US$ rows add to US$35.29; the log's running total gives US$35.28 (rounding
  of single entries). With L10: 12.92 h and US$35.44.

## 10. Known traps

| # | Trap | What to do |
|---|---|---|
| T1 | **The root file system grows only at boot.** The disk was grown online from 200 to 400 GiB (2026-11-15 09:21). The file system followed only at the next boot. b05 ran out of space before that (F8). | `grow_root` runs at every boot and writes `records/disk.json`. Grow the disk only while the VM is stopped, or expect the space at the next boot. Note: hyperdisk can grow but never shrink. |
| T2 | **The mail intake keeps one job per mail id (F28).** A redo that mails the same ids gets the old jobs back, with their failures. | `--redo` mails under new ids (`-r<retry>`). Never resend by hand under an old id. |
| T3 | **The box keeps an approved ruleset version (F29).** A second FEAS of an approved ruleset fails with "no structured criteria to count" and no workbook. | A second run on one box uses new ruleset ids: `--acc-rs-tag <letters or digits>`. |
| T4 | **The weights' mount is lost at reboot (F15).** The model servers and the embedder restart on an empty `/opt/trialbox/deploy/models` and stay unhealthy. | The driver binds `/models` again and restarts those three before any step (`TB-STACK`). A reboot by hand (B11) needs the same, unless master's start path does it (that is what B11 tests). |
| T5 | **The kernel's 128 KiB limit on one argument (F30).** A long protocol in base64 as an argument failed with "Argument list too long". | Any argument over 100 KB goes in the program text (d44e3978). Keep that rule for new calls. |
| T6 | **The shared accuracy folder (F21).** Every run used `/var/lib/tb/acc`, so a later run took an earlier run's progress as its own and said "done". | Per-run folders `/var/lib/tb/acc/<run id>/`. A run that built its data before this rule keeps the shared folder. Do not reuse an old run id for new work. |
| T7 | **A bare start replays the last launch.** The VM keeps the last launch's `tb-*` keys until a collect or `--stop` resets them. | Use the driver. To boot without a run, `--stop` first. |
| T8 | **`TB_SETTINGS_FILE` leaks into the build (F31).** | Fixed in 8d564b6f. Any new host-side `make` call must unset it. |
| T9 | **`--stop` sets the usual startup script back.** `gpu-sim-startup.sh` starts three private model containers that hold about 31 GB of the card and port 80 on loopback. | The box run removes them at 02 (`d_old_servers`). A boot outside the driver starts them. |
| T10 | **Collect and resume rewrite the metadata.** The collect at a run's end removes the launch's keys (F2). | `--resume` sends them again from `.cache/box-run/<run>/md/`. Lane G's copies of that folder, with `metadata-keys` and `cap-hours`, are in the bucket as `boxruns/<run id>/driver-md.tgz` for box-20261115T123832Z-1157c9bfa, box-20261115T162830Z-04138db7c and box-20261116T023816Z-b266f9b7f. Unpack one into `.cache/box-run/<run id>/` before a `--resume`. |
| T11 | **A set's slowdown measured on a set that answered nothing (F22).** Every later set got the 600 s minimum. | Fixed (e9c29464): only a whole answered set measures it. |
| T12 | **A step cut by the watchdog loses no work, but a silent step is cut.** The full qualify ran 1 h 52 min with no visible progress. | Use `--qualify-timebox` or `--qualify-args`; read the checkpoints. |
| T13 | **Spot.** The VM can be pre-empted. | It boots again only on `--resume`; finished steps are kept. |
| T14 | **The 400 GiB disk bills while stopped.** | See e1-billing. |
| T15 | **The doctor runs from the host.** Its serving FAIL is not real (chain review B8). | Read `doctor.json` knowing this. |
| T16 | **Network.** The project's `default-allow-ssh` rule reaches the GPU VM from any address. Its tag `tb-gpu-door` also opens tcp:443 to one source range (the earlier door). The box's Caddy listens on 443 while the stack runs. | Review both rules before a long run. The demo VM has its own deny rule; the GPU VM has none. |
| T18 | **A second run's ingest into the snapshot already current (F33).** The lake's CURRENT does not change, so the old wait never ends. | Fixed in 7b1b951f: the synchronous ingest is the publication when CURRENT already names the snapshot. |
| T19 | **A resume sends only the per-launch keys it is given (F34).** `--qualify-timebox`, `--redo`, `--acc-deadline`, `--acc-protocols`, `--site-env`, `--skip`, `--serving` hold for one launch only. | Give them again on every resume that needs them. |
| T20 | **Site settings stay in deploy/.env (F37).** `--site-env TB_MEM_EMBED=16g` from the frozen column stayed on master. | Set the value you want on every launch (`--site-env TB_MEM_EMBED=6g` is master's default). |
| T21 | **On master a FEAS of an approved version is "done" (D-901), not "failed" (F38).** | The redo path takes both (b1aed1e0). |
| T22 | **The box's gate canary at start meets model servers still loading.** Its failed record keeps note_block off until a full canary passes. | Run 07g (restart the orchestrator once the servers answer) before any SCREEN whose pair level matters. |
| T17 | **Disk at b05 and 01.** The bundle can sit on the disk up to four times. | b07 removes its copy; 01 needs 1.1 x the bundle free (chain review B1). |

## 11. What to run next, in order

These estimates are derived from the frozen column's measured times at US$2.74/h. Measured on master since:
- one 500-patient tcga SCREEN took 317 to 325 s, against 1,352 s on 1157c9bf (D-904: all 500 windows fit, no embedding);
- jmed's two SCREEN jobs took about 60 s each.
So rows 2, 6 and 10 below are about a quarter of what they say. The compile-bound sets (sigir, trec2023, chia, jrct, tfda) were not measured on master: their time is FEAS (the compile), not SCREEN.
Master's D-904 (train 36: S2b skipped when the window fits) and D-900 (the embed service) may change SCREEN times;
that is not known yet.

| # | What | How derived | VM hours | US$ |
|---|---|---|---|---|
| 1 | Relaunch the master column on the frozen master commit (with F31's fix), `--steps dev,acc`: build, stack, G-1, the canary through the box's gate, jmed (B1 to B3) | b01-b03 about 0.11 h, 02 and 03-07 about 0.15 h, boot 0.25 h, jmed about 0.02 h | about 0.55 | about 1.5 |
| 2 | B4, tcga BRCA, 500 patients | 1,352 s SCREEN plus about 0.1 h of resume overhead | about 0.5 | about 1.4 |
| 3 | B6, sigir in full, 104 protocols | 2,768 s for 34 started, so about 81 s a protocol | about 2.4 | about 6.6 |
| 4 | B6, trec2023 in full, 297 protocols and 500 pairs | 5,256 s for 46 started, so about 114 s a protocol | about 9.4 | about 25.8 |
| 5 | B8, qualify `--box`, time-boxed | the owner's 30 minutes | 0.5 | 1.4 |
| 6 | B5, tcga's other four | about 1,265 s each | about 1.4 | about 3.8 |
| 7 | B7, chia, jrct, tfda, compile only | chia used its whole 3,600 s; jrct and tfda not measured; the plan's budgets 2,700 s and 3,600 s | about 2.75 (at the budgets) | about 7.5 |
| 8 | B11, a restart | a boot (0.25 h) plus the stack and model loads | about 0.35 | about 1.0 |
| 9 | B10, the one-command route | not measured | unknown | the cap |
| 10 | B9, BRCA's SCREEN a second time | as row 2 | about 0.4 | about 1.1 |
| 11 | B12, disk and image sizes | reads only | about 0.1 | about 0.3 |

Rows 1 to 4 (never dropped) come to about 12.9 h and US$35.3. The running total at writing is US$94.44. Rows 1 to 4
would bring it to about US$129.7: just under part B's US$130 stop, with no margin.

Trec2023 in full is the one row that decides the fit. Before launching it, measure master's per-protocol time on
sigir. If master is not faster, ask the owner (the plan's rule: post what is left with its estimate). **(box
worker: the figures as run.)**

Part C (after lane A2's compiler fixes) is not costed here.

## 12. What bills while the machines are stopped (E1)


Draft for the hand-over (part E1 of the owner's plan).

**How this was found.** The resources were read with read-only `gcloud` calls on 2026-11-16 at about 02:30 UTC
(`instances list`, `disks list`, `addresses list`, `snapshots list`, `machine-images list`, `images list`,
`storage du`, `buckets describe`). Nothing was changed.

**Where the rates come from.** Google's public price pages, read on 2026-11-16 for region `asia-east1` (Taiwan). The
pages draw their regional tables from data embedded in the page. Lane G read the Taiwan rows from that data, keyed by
"Taiwan (asia-east1)":

- disks: https://cloud.google.com/compute/disks-image-pricing (read 2026-11-16);
- Cloud Storage: https://cloud.google.com/storage/pricing (read 2026-11-16), the regional table (46 locations);
- Secret Manager: https://cloud.google.com/secret-manager/pricing (read 2026-11-16).

The Cloud Billing catalog API, which would give the exact SKUs, is not enabled in the project. Lane G did not enable
it. The console's billing report was not read. **So the rates are the list prices from the pages, not the account's
invoice.** They do not include any discount or credit on the billing account.

A month is Google's 730 hours. A day is 24 / 730 of a month.

## The state of the machines

| VM | Zone | State | Bills while stopped? |
|---|---|---|---|
| `tb-gpu-sim` (g4-standard-48 + 1 RTX PRO 6000, spot) | asia-east1-a | TERMINATED | Its disk only. A stopped VM's vCPUs, memory and GPU are not billed. |
| `tb-demo-vm` (e2-standard-4) | asia-east1-a | TERMINATED | Its disk only while stopped. Part D4 (a separate worker) runs it for Tuesday's demo; its state at hand-over is given in the "done: hand-over" post. Nobody else touches it through Tuesday. |
| `trialbox-demo` (e2-standard-4) | asia-east1-b | TERMINATED since 2026-11-08 | Its disk only. The early-November hosted demo; lane G does not use it. |

## Everything that bills while stopped

| Item | Size | Rate (Taiwan, list price) | Per month | Per day |
|---|---|---|---|---|
| `tb-gpu-sim` disk, capacity | 400 GiB hyperdisk-balanced | US$0.093 per GiB-month | US$37.20 | US$1.223 |
| `tb-gpu-sim` disk, IOPS above the free 3,000 | 4,200 provisioned, so 1,200 billed | US$0.006 per IOPS-month | US$7.20 | US$0.237 |
| `tb-gpu-sim` disk, throughput above the free 140 MB/s | 440 provisioned, so 300 billed | US$0.046 per MB/s-month | US$13.80 | US$0.454 |
| **`tb-gpu-sim` disk, in all** | | | **US$58.20** | **US$1.913** |
| `tb-demo-vm` disk | 30 GiB pd-balanced | US$0.10 per GiB-month | US$3.00 | US$0.099 |
| `trialbox-demo` disk | 60 GiB pd-balanced | US$0.10 per GiB-month | US$6.00 | US$0.197 |
| Bucket `gs://trialbox-demo-runs` | 30,760,471,165 bytes = 28.65 GiB, STANDARD, regional asia-east1 | US$0.020 per GiB-month | US$0.57 | US$0.019 |
| **In all** | | | **US$67.77** | **US$2.228** |

The hourly rows on the disk page agree with these figures. For the GPU disk: US$0.000127397 per GiB-hour for
capacity, US$0.000008219 per IOPS-hour and US$0.000063014 per MB/s-hour. That is US$0.0797 an hour for the GPU
VM's disk.

The free baselines (3,000 IOPS and 140 MB/s) are as the disk page states them for Hyperdisk Balanced.

### What does not bill

Each of these was checked with a read-only `gcloud` call:

- **Reserved addresses: none.** `addresses list` is empty. The VMs' ephemeral addresses are released when they stop.
- **Snapshots, machine images, custom images: none.**
- **Firewall rules:** `tb-demo-vm-deny`, `tb-demo-vm-https`, `tb-gpu-door`, `trialbox-web` and the default rules.
  Firewall rules have no charge of their own.

### Items not verified

- **Secret Manager.** The project holds the secrets `tb-gpu-door`, `tb-demo-password`, `tb-vendor-signing-key` and
  `tb-r2-answers`. The deployer account may not list them, so the number of active versions is not known here.
  - The rate: US$0.06 per active version per month (US$0.000082192 an hour on the page).
  - The first 6 active versions per billing account are free.
  - Probably a few cents a month at most. Not verified.
- **The bucket's soft delete.** It keeps deleted objects 7 days (`retentionDurationSeconds` 604800). An object
  deleted now still bills for up to 7 days at the same storage rate.
- **Bucket operations** (list, get, put) are billed per operation. At this run's volume, cents.
- **Network egress.** Downloads of results to this session leave Google Cloud. The bucket is about 29 GB; lane G
  fetched only the small objects. Not computed.
- **The billing account's own invoice**, discounts and credits were not read.

## Should the 400 GiB disk be shrunk or kept?

### The facts

- A Hyperdisk volume **cannot be shrunk.** Google's page (https://cloud.google.com/compute/docs/disks/modify-hyperdisks,
  read 2026-11-16) says: "You can only increase the size of a Hyperdisk volume." To get a smaller disk, you make a
  new one and copy the data over.
- The disk holds what makes the next launch cheap:
  - the model cache (about 48 GB);
  - Docker's images of the last build;
  - the installed box tree and its database volumes;
  - the run folders.

  Rebuilding that on a new disk costs VM hours: the weights download, a full image build and a first stack start.
- Part B and part C still need the VM. So does the integrator, if it takes over the runs.
- The extra IOPS and throughput (US$21.00 a month together) can be lowered without a new disk. Google allows a
  change of IOPS or throughput once every 4 hours. Lowering throughput to the free 140 MB/s would slow the model
  loads and the image loads at each boot. With about 48 GB of weights, that is several more minutes a boot at
  US$2.74 an hour. Lane G has not measured it.

### Lane G's advice

1. **Keep the 400 GiB disk while parts B and C, and the integrator's runs, continue.** It costs US$1.91 a day. A
   rebuild on a new disk would cost more in VM time than several days of this disk, and it adds risk before
   Tuesday.
2. **If the VM will sit unused for more than about a week,** lower the provisioned IOPS to 3,000 and the throughput
   to 140 MB/s (`gcloud compute disks update tb-gpu-sim --zone asia-east1-a --provisioned-iops 3000
   --provisioned-throughput 140`, a paid-state change for the owner to approve). That saves US$21.00 a month, and it
   can be raised again before the next run (once every 4 hours).
3. **When PoC-1 ends for good:** decide between deleting the disk (and the VM) or keeping a snapshot.
   - A snapshot bills only for the data stored. The snapshot rate for Taiwan was not read in this draft.
   - Deleting ends the US$58.20 a month.
   - Either is the owner's call.
4. **The `trialbox-demo` VM's disk (US$6.00 a month)** belongs to the early-November demo. If nobody needs it, the
   owner can delete that VM. Lane G has not touched it.
5. **The bucket** (US$0.57 a month) is mostly the validation bundle `r2/val-ac36aa21fdc1` (29.6 GB). That bundle is
   not a release. Keep it while #717 (the installer hand-over) might want it. Otherwise it can go: about US$0.55 a
   month, plus 7 days of soft delete.


## 13. Access for the integrator's session (E3)


Draft for the hand-over (part E3 of the owner's plan). It names no key, token, key-file path or address.

## 1. What the driver actually calls

Read from `deploy/gcp/box-run.sh`, `deploy/gcp/gcloud-auth.sh`, `deploy/gcp/demo-vm.sh` and
`deploy/gcp/box-install-run.sh` at `f49973ef`.

**On the GPU VM `tb-gpu-sim`** (`box-run.sh`: launch, `--resume`, `--collect`, `--stop`):

- `gcloud compute instances`: `describe`, `start`, `stop`, `set-scheduling`, `add-metadata`, `remove-metadata`,
  `get-serial-port-output`;
- `set-service-account`, for a **production** build only (the vendor-key signer). PoC-1 runs in validation mode and
  does not need it.

**On the demo VM `tb-demo-vm`** (`demo-vm.sh up` on the existing VM, `status`, `down`, `links`):

- `instances describe`, `add-metadata`, `set-scheduling`, `start`, `stop`, `get-serial-port-output`;
- firewall rules `describe`, `list` and `update`. The rules `tb-demo-vm-https` and `tb-demo-vm-deny` already exist.
  `create` is needed only if one was deleted.
- `networks describe` (the `default` network).

`demo-vm.sh delete` would also need `instances delete` and firewall `delete`. `up` on a deleted VM would need
`instances create`, which is a project-level right. Neither is needed for Tuesday.

**On the bucket `gs://trialbox-demo-runs`:** `gcloud storage cp`, `ls`, `cat`, `rm`, and `objects describe` (to
read the generation).

**Local only:** `gcloud config get-value project` and `gcloud auth activate-service-account --key-file <path>`.

**What runs on the VM is not the integrator's.** The VM runs as the **Compute Engine default service account**. That
account writes the bucket (`roles/storage.objectAdmin` on the bucket, granted by `setup-gcp.sh`). The integrator's
session needs none of the VM's own rights.

## 2. The roles, least privilege

All in project `trialbox-demo`. Lane G advises one new service account for the integrator. In this draft it is
called `tb-integrator`; the owner chooses the name.

| Role | Granted on | Why |
|---|---|---|
| `roles/compute.instanceAdmin.v1` | the instance `tb-gpu-sim` (zone asia-east1-a) only, as an instance-level policy | start, stop, scheduling, metadata, serial output |
| `roles/compute.instanceAdmin.v1` | the instance `tb-demo-vm` (zone asia-east1-a) only | the same, for the demo VM |
| `roles/iam.serviceAccountUser` | the Compute Engine default service account only (a policy on that service account, not on the project) | starting a VM, or changing its metadata, while the VM runs as that account |
| `roles/storage.objectAdmin` | the bucket `gs://trialbox-demo-runs` only | results, accuracy sets, the tools tarball, the source bundle, the demo image and its codes |
| A custom project role, here `tbOperator`, with only: `compute.instances.list`, `compute.zoneOperations.get`, `compute.globalOperations.get`, `compute.firewalls.get`, `compute.firewalls.list`, `compute.firewalls.update`, `compute.networks.get`, `compute.networks.updatePolicy` | the project | listing the VMs; gcloud waiting on the operations it starts; the demo VM's firewall rule update. These do not exist on single instances. |

What this leaves out, on purpose:

- creating or deleting any VM, disk, network or address;
- any secret (Secret Manager);
- setting a VM's service account;
- billing;
- IAM changes;
- every other bucket.

**Not verified.** Lane G cannot grant roles, so it could not test this set.

- Instance-level policies are documented for Compute Engine instances
  (https://cloud.google.com/compute/docs/access/granting-access-to-resources, read 2026-11-16).
- Whether gcloud's operation polling, or `compute.networks.updatePolicy` for a firewall update, is checked exactly as
  listed here is lane G's reading, not a test.
- After granting, run these free checks with the new account:
  - `deploy/gcp/box-run.sh --estimate --steps dev`;
  - `gcloud compute instances describe tb-gpu-sim --zone asia-east1-a --format='value(status)'`;
  - `gcloud storage ls gs://trialbox-demo-runs/boxruns/`;
  - `deploy/gcp/demo-vm.sh --dry-run up`.

  The first paid call then shows whether anything is missing. A refused call costs nothing.

For comparison, lane G's own account (`trialbox-deployer`) holds more than this. `setup-gcp.sh` granted it, on the
whole project:

- `roles/compute.instanceAdmin.v1`;
- `roles/compute.securityAdmin`;
- `roles/iam.serviceAccountUser`.

On the bucket it also holds `roles/storage.objectAdmin` and `roles/storage.legacyBucketOwner`.

## 3. The credential lane G's session uses

- **The kind.** A **service-account key file** (JSON) for the account `trialbox-deployer` in project
  `trialbox-demo`.
- **Where it comes from.** The owner made the account and its one key with `deploy/gcp/setup-gcp.sh` in Cloud Shell.
  The owner put a base64 copy of the key into this session's cloud environment settings as an environment variable.
  It was never pasted into chat.
- **How the session uses it.** The session decoded it once into a private file (mode 600) in its scratch folder. It
  points `TB_SA_KEY_FILE` at that file's **path**, with a private `CLOUDSDK_CONFIG` folder.
- **What reads it.** gcloud reads the file itself (`gcloud auth activate-service-account --key-file`). The driver
  passes the path and never prints or reads the content (`deploy/gcp/gcloud-auth.sh`).

## 4. What the owner does once, so the integrator has the same

Do **not** copy lane G's key to the integrator. Give the integrator its own account, so each can be revoked alone.

**Step 1: the account and its roles** (Cloud Shell, as the owner; nothing here starts a VM or costs money):

    P=trialbox-demo
    SA=tb-integrator@$P.iam.gserviceaccount.com
    VM_SA=$(gcloud projects describe $P --format='value(projectNumber)')-compute@developer.gserviceaccount.com
    gcloud iam service-accounts create tb-integrator --project $P --display-name "TrialBox integrator"
    for VM in tb-gpu-sim tb-demo-vm; do
      gcloud compute instances add-iam-policy-binding $VM --zone asia-east1-a --project $P \
        --member serviceAccount:$SA --role roles/compute.instanceAdmin.v1
    done
    gcloud iam service-accounts add-iam-policy-binding $VM_SA --project $P \
      --member serviceAccount:$SA --role roles/iam.serviceAccountUser
    gcloud storage buckets add-iam-policy-binding gs://trialbox-demo-runs \
      --member serviceAccount:$SA --role roles/storage.objectAdmin
    gcloud iam roles create tbOperator --project $P --title "TrialBox operator" \
      --permissions compute.instances.list,compute.zoneOperations.get,compute.globalOperations.get,compute.firewalls.get,compute.firewalls.list,compute.firewalls.update,compute.networks.get,compute.networks.updatePolicy
    gcloud projects add-iam-policy-binding $P --member serviceAccount:$SA \
      --role projects/$P/roles/tbOperator --condition=None

**Step 2: the credential, into the integrator's environment, not into chat.** This is the same path lane G's key
took.

    gcloud iam service-accounts keys create ~/tb-integrator-key.json --iam-account $SA
    base64 -w0 ~/tb-integrator-key.json     # copy the one line into the integrator's cloud environment settings,
                                            # as an environment variable (for example GCP_SA_KEY); never into chat
    shred -u ~/tb-integrator-key.json

- If the organisation forbids key creation (`iam.disableServiceAccountKeyCreation`), the `keys create` call is
  refused. Tell the integrator, and paste nothing.
- If the integrator's session runs in the **same** cloud environment as lane G's, that environment's variable already
  reaches it. Then the owner should still replace that variable with the integrator's own key, or give the integrator
  its own environment, so that lane G's key is not shared.

**Step 3: the integrator's side, once.** Decode the variable into a private file (mode 600) outside the repository.
Then:

    export CLOUDSDK_CONFIG=<a private folder>
    export TB_SA_KEY_FILE=<that file's path>
    export TB_BUCKET=gs://trialbox-demo-runs

Run the free checks in section 2.

**Why not an environment network secret.** A network secret puts a fixed header on requests to one host. gcloud
needs a Google OAuth access token, which expires within an hour, and it talks to several Google hosts. A service
account key cannot be sent that way. Lane G sees no way to run the driver on a network secret alone. This was not
tested.

**When the work ends**, the owner deletes the key, or the account:

    gcloud iam service-accounts keys list --iam-account $SA
    gcloud iam service-accounts keys delete <KEY_ID> --iam-account $SA

## 5. To run two GPU VMs at once

To run two GPU VMs at once, the owner must raise `GPUS_ALL_REGIONS` from 1 in the console, under IAM and admin,
Quotas. Read on 2026-11-16: limit 1, in use 0. The per-region quota for the RTX PRO 6000 in `asia-east1` appears
separately. Lane G's `gcloud` reading of the region's quotas did not list it, so its value is not known here.

Steps (the owner, in the Google Cloud console, project `trialbox-demo`):

1. Open **IAM and admin**, then **Quotas and system limits**.
2. In the filter, type `GPUs (all regions)` (metric `compute.googleapis.com/gpus_all_regions`). Tick the row. Its
   current value is 1.
3. Choose **Edit quotas**. Enter **2** as the new value. Give a short reason (for example "two GPU test VMs for a
   proof of concept, one at a time each"). Submit.
4. Filter again for the RTX PRO 6000 quota in region `asia-east1`. Check whether it allows 2. If it does not, ask
   for 2 there too. If the second VM will be spot, also check the spot (preemptible) variant of that quota if one is
   listed.
5. Also check the region's quotas for the second VM's 48 vCPUs (the G4 family's CPU quota) and its disk
   (Hyperdisk Balanced capacity, if listed). Raise them the same way if they would be passed.
6. Wait for Google's e-mail. A raise can be granted at once, take a few days, or be refused.

**Then**, before a second VM can run:

- Someone with project-level `compute.instances.create` must make it. The integrator's role in section 2 cannot
  create a VM.
- It needs its own disk. A second 400 GiB hyperdisk-balanced disk at the same settings bills about US$58 a month
  while it exists (see e1-billing).
- It doubles the running cost: US$2.74 an hour each, spot (the driver's constant).
- The driver runs one VM by name (`box-run.sh [VM] [ZONE]`, default `tb-gpu-sim`). It keeps one run's state per
  run id. Two VMs need two run ids and the VM's name on every call.

## 14. Review points carried, not applied

Lane A2's review of lane G's scorers (#639, 2026-11-15 07:25) asked for four changes. They concern code that is in
neither #628 nor #649: `tools/medtxt_eval.py`'s `negative_kinds` and `treated_in_quote` and the N-12 reproducibility
check came from commit 1f7f0765 on lane G's batch 8 (#614, closed and replaced by #649 on a clean base). Whoever
brings that code back applies them:

1. TREC eligible pairs lost: keep the absolute line against the qrels (lost / eligible <= 10 %) beside the
   reproducibility check against N-12's own recording.
2. MedTxt: test the denial in the mention's own clause first (up to the next 、 or 。), then "treated".
3. MedTxt: assert the proposed fact's status; a treated mention proposed as current counts as an error.
4. Lane A2's own card: SCREEN's compiled SQL reads condition rows whatever their clinical status.
