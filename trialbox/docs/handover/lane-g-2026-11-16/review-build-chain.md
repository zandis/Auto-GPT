# Chain review: lane G's box run against the real product (before the next paid launch)

Reviewed: branch `claude/lane-g-box-accuracy` at **58787f0d711c40cec5a91abf9ab8acffaedef6bf** (read-only copy,
worktree `lgreview`). Every patch below is a unified diff against that head, in
`/tmp/claude-0/-home-user-Auto-GPT/b6dc012b-d091-5e78-8158-ebd09d964152/scratchpad/chain-review-patches/`.
Apply them **in order** (01, 02, 03, 04, 05: each is made on top of the ones before; `all-stacked.diff` is all five
in one). With all five applied: `bash -n` passes, `shellcheck --severity=warning` (the repo's gate) is clean, and
`tests/unit/test_g1_box_vm.py` passes (15). I did not run the 50-minute box rehearsal (`make rehearse`); the worker
should, after applying them.

Nothing here started a VM or touched the cloud. "Confirmed by running" means I ran the real product code here
(stdlib-only Python, the real Docker CLI without a daemon, the real tools); "read" means read only.

---------------------------------------------------------------------------------------------------------------------

## A. Why six stops happened

**Root cause.** The driver was written to what the product scripts *should* do, and the rehearsal checked it
against stand-ins written with the same assumptions. So each fault sat exactly where a stand-in replaces a real
program, and it showed only when that real program (make, `docker compose`, Docker's image store, the gcloud
metadata) ran for the first time on the paid VM.

| Stop | What the driver assumed | What was really true | The stand-in that hid it |
| --- | --- | --- | --- |
| F1 b03 | The VM has what CI's runners have (Maven, a JDK) | `make images` calls `tools/fetch_jvm_deps.sh`, which needs `mvn` | `tests/rehearsal/box-run/shims/mvn` and `shims/java` |
| F2 resume | The VM keeps the launch's metadata | The collect's `reset_vm` removes every `tb-*` key | `shims/gcloud` keeps no metadata state across "launches" |
| F3 b04 | `make images` builds every image the gates scan | CI builds the demo image separately; live CVE data changed | `shims/docker` answers yes to any image; no gates run |
| F4 b04 | A kept step needs no new work after a fix | A fix that adds work to a kept step (b03) is skipped on resume | the rehearsal never resumes after changing a step's body |
| F5 b05 | `make_bundle.sh` can list its images as shipped | Its compose render needs `TB_TZ` (`${TB_TZ:?}`); the staged `.env` has none | `standins/mkbundle.py` replaces `make_bundle.sh` (no images, no compose) |
| F6 b05 | One image has one id | Docker's containerd store gives the index digest; the gate records the config digest | `shims/docker` has no image store |

I re-ran F5 here with the **real** `make_bundle.sh` and the real Docker CLI (no daemon is needed for `docker compose
config`): with `TB_TZ` unset it stops with "compose listed no trialbox-py image"; with `TB_TZ=UTC` it lists the 8
images below and goes on to the gate check. So a recording `docker` shim that passes `compose` to the real CLI
would have caught F5 for free.

### Every stand-in, and what the driver assumes about the real thing

| Stand-in (tests/rehearsal/box-run/) | Replaces | What the driver assumes about the real one | Checked here |
| --- | --- | --- | --- |
| `shims/docker` | Docker Engine, its image store, compose | images exist after `make images`; `docker compose` reads `deploy/.env` (COMPOSE_FILE, COMPOSE_PROFILES); `exec -T svc python -` runs in the service's env; `docker run --rm --user 0` works with nested bind mounts | compose render real (no daemon); store semantics not |
| `shims/gcloud` | Secret Manager, Storage, metadata | `gcloud storage cp` of a ~35 GB file works and is quick; the VM's own account may write the bucket (it did: results.tgz) | read only |
| `shims/mvn`, `shims/java` | the JDK and Maven | apt installs `openjdk-21-jdk-headless maven` (fix F1) | ran on the VM since |
| `shims/nvidia-smi` | the driver | driver new enough for the vLLM v0.32.0 (CUDA 13) image; `check_host.sh --gpu-only` passes | the VM served v0.32.0 before (gpu-sim-startup.sh) |
| `shims/systemctl`, `shims/systemd-run` | systemd | transient units for cap/watchdog; `systemd-creds` present for the seal | not checked: see B4 |
| `shims/curl` | the metadata server | each `tb-*` key readable | read |
| `standins/mkbundle.py` | `tools/make_bundle.sh`, `tools/release.py`, `docker save` | a full bundle (images + release record) comes out | real script run up to the gate check (B1 for size) |
| `standins/install-validation.sh`, `install-inner.sh`, `compose-up.sh` | `deploy/install.sh` and everything it runs | install.sh takes `--answers`, prints "TrialBox is running", leaves the stack up; runs as root; host python3 good enough | read all of install.sh; ran its host-python steps with a stdlib-only python (B3) |
| `standins/bind-models.sh` | `mount --bind /models deploy/models` | a bind mount is seen inside every `docker run -v deploy:/d` (Docker binds recursively: yes) | read |
| `standins/host-check.sh` | `deploy/check_host.sh` | a FAIL list does not stop the driver | read |
| `standins/box.py`, `boxpy` | the installed box's tools (pin_model, qualify, doctor, selftest, serving_config) | flags and outputs | flags checked against the real argparse (C) |
| `standins/accpy`, `acc_fixture.py` | the VM's python3 running `tools.public_accuracy` | stdlib only, network to the pinned sources | real fetch + build of tcga and chia with a stdlib-only python 3.13: works (C) |
| `standins/console_standin.py` | the console's first run | (production mode only; not used by validation) | not needed |
| `standins/reboot.sh` | a VM power cycle | G-9 only | not needed |
| TB_BOXRUN_MINUTE_S=1, POLL 0.2 | real time | the watchdog's 20 idle minutes are never close in the rehearsal | this is why B2 and B5 never show |

---------------------------------------------------------------------------------------------------------------------

## B. Predicted faults, in the order the run meets them

Head reviewed: 58787f0d7. Severity: **stop** = the run ends or the VM powers off; **wrong** = a wrong or missing
result; **cost** = time on the card only. Certainty: **ran** = confirmed by running the real code here; **read** =
from reading, with the derivation; **unknown** = depends on a fact about the VM that nobody has recorded (see D).

| # | Step | Driver line | What the product actually requires (file:line) | Certainty | Severity | Fix (patch) | Whose |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B1 | b05, b06, then 01 and 02 | `step_b_upload` keeps `$BUILD/out/trialbox-$RID.tar`; `step_bundle` checks only `free > size` | One 200 GB disk holds the bundle up to **four times** at 02: the build's copy (`box-install-run.sh:836`), 01's fetch (`:862`), and `tools/apply_update.sh:87` stages a full copy under `${TMPDIR:-/tmp}` twice (install.sh:233 `--dry-run`, then :234), with `tools/verify_update.py:339-345` refusing below 1.05 x the payloads. b05 peaks at 2 copies (`make_bundle.sh` stage + the signed tar), b06 at 2 (the tar + `verify_update --stage`) | read; size derived: the 8 images (list in C), vLLM v0.32.0 is 9.21 GB compressed on Docker Hub (about 20 GB unpacked, as `docker save` writes it), so the bundle is about 30 to 40 GB | **stop** (02 refused "not enough disk space to stage", or ENOSPC in b05/b06) if the disk also holds Docker's build images/cache (~45-55 GB) and more than the pair in `/models` | **01-disk-one-bundle-copy.diff**: b07 removes the local bundle once uploaded; 01 (a start on the build's VM) removes the build tree and Docker's build cache **before** the fetch, records `df` and `du /models`, and requires 1.1 x the bundle free under `${TMPDIR:-/tmp}` | lane G |
| B2 | 02-install | `need ... d_install_v` (heartbeat = the step log growing) | install.sh's bundle checks are silent: `install.sh:233` sends the dry run to /dev/null, and `:234` pipes the real load through `sed`, which holds a pipe's output until it ends. Verifying + staging ~35 GB twice and `docker load` is about 13 to 20 min at 150-250 MB/s, with nothing in the log | ran (sed held 0 bytes after 1.5 s of input; the dry run's silence is in the code); the minutes are derived | **stop**: the watchdog powers the VM off after 20 idle minutes (`tb-idle-minutes`), mid-install | **02-install-heartbeat.diff**: install.sh runs under `PYTHONUNBUFFERED=1 stdbuf -oL -eL` (reaches every child, sed included); `watched` also counts disk I/O (`/proc/diskstats`) as progress for this step only (`WATCH_IO=1`): a hang does neither | lane G; red for product: install.sh could say progress during the verify (`--dry-run` silent for minutes) |
| B3 | 02-install | `d_install_v` runs install.sh on the VM's own python3 | install.sh runs host python3 for `anchors-compose` (dies at `install.sh:498-499`) and `pre-start` (dies at `:567-568`); both import PyYAML (`tools/trialbox/anchors.py:27`; pre-start imports `tools/trialbox/doctor.py:156`). The product's own rehearsal host installs `python3-yaml python3-cryptography nftables cron` (`tools/rehearse_box/host.Dockerfile`) | ran (stdlib-only python 3.13: `ModuleNotFoundError: yaml` for both; secrets init, memcaps, images_lock, image_pins, backup-install, update run fine); the VM's python packages: unknown | **stop** if the VM's python3 lacks PyYAML (half way through the install, after the bundle loaded: ~20 min lost) | **03-host-prereqs-and-vtpm.diff**: `d_host_prereq` installs only what is missing of those four packages before the install, and records it | lane G; **red for product**: install.sh's step 1 (host) should check `python3 -c 'import yaml'` before loading anything; docs/handover say host tools are "standard library only", anchors-compose and pre-start are not |
| B4 | 02-install (seal) | none: the driver only notes "the VM needs a vTPM" (`box-install-run.sh:80`) | In VALIDATION install.sh always seals the site keys (`install.sh:583-588`) with `KEK_BACKEND=tpm` unless `deploy/site/hardening.conf` says otherwise; `deploy/hardening/seal_keys.sh:67-68` dies without `systemd-creds` or `/dev/tpmrm0`. The product's rehearsal box is TEST, which never seals: this path has never run anywhere | read; whether tb-gpu-sim has a vTPM: unknown | **stop** ~20 min into the install if there is no vTPM | 03 (same patch): the preflight refuses in the first minute (no TPM device, no systemd-creds) instead. If the VM has none: turn on Shielded VM vTPM on the stopped VM (lead's cloud action; check first with `gcloud compute instances describe tb-gpu-sim --format='value(shieldedInstanceConfig)'`, free) | lane G (preflight); the VM setting: lead |
| B5 | 60.. each acc set | `box_vm.py Box.call` (`:739-744`) uses `communicate()` | `onbox.py cmd_wait` prints a line at each change of the job "so the VM's watchdog reads a growing log as a heartbeat", but `communicate()` only hands the output over when the wait ends, and the beat is touched only then. A job may run up to `tb-acc-job-minutes` (60) | ran: with the patch the log had 2 of 3 lines after 1.5 s of a 3 s wait; without it none until the end | **stop** when any single FEAS or SCREEN job runs over 20 min (power off; `--resume` costs a boot and a model load, ~US$0.7-1) | **04-acc-call-stream.diff**: read the program's output line by line into the log and touch the beat per line (an answer line over 4000 characters is cut in the log only) | lane G |
| B6 | 51-acc-settings | `d_recreate` with no service named | `docker compose up -d --force-recreate --wait` recreates **every** service, both model servers too: two model loads (~3.5 min measured: judge 117 s + verifier 82 s) for settings they do not read | read | cost (~4-5 min of the card a launch) | **05-recreate-and-tree-mount.diff**: recreate every service but `llm-*` | lane G |
| B7 | 06 (d_weights), 09-11 (promote, resolve) | `img_tool` mounts `deploy/` at `/d` only | After a bundle install the shipped files under `deploy/` are links into `../current` and dangle in a container that gets `deploy/` alone (install.sh's `tree_args`, OPS-004, `install.sh:87-98`) | read; pin_model's paths here are site files, so likely harmless | wrong (a pin_model call that reads a shipped file under /d fails) | 05 (same patch): mount the release tree at `/current` as install.sh does | lane G |
| B8 | 12-doctor | `d_doctor`: host python3, `trialbox doctor --live` | `--live` asks the model servers, which are only on the internal `trialbox-model-net`; install.sh runs it in a container on that network with the key file (`install.sh:616-617`). From the host the serving check FAILs; doctor also needs PyYAML (B3) | read | wrong (doctor.json shows a serving FAIL that is not real; validation does not stop on it) | no patch: add `serving` to `--doctor-expected`, or run it as install.sh does | lane G |
| B9 | 02 (models-place) | `fetch "$EMBED_LIST_SRC"` (`box-run.sh:247` names `gs://…/r2/models/e-embed-1.sha256`) | No code in the repo makes that object (no file list of e-embed-1 is committed); without it `d_models_place` returns 1 | read; whether the object is in the bucket: unknown | **stop** at 02 after ~1 min (a full VM start, ~US$0.7) | check before the launch: `gcloud storage ls gs://<bucket>/r2/models/e-embed-1.sha256` (free) | lane G |
| B10 | 05-serving | `d_capture --models-dir "$MODELS"` | `tools/serving_config.py:139` hashes every file under the folder: the whole HF cache, the pair twice (the flat links and the snapshots), the embedder; silent until done | read | cost; **stop** only if `/models` holds well over ~150 GB (20 idle min at ~150 MB/s) | none needed if the probe (D) shows `/models` near the pair's 25 GB; else pass the flat folders | lane G |
| B11 | boot, before 02 | none | The VM's usual startup script (`deploy/gcp/gpu-sim-startup.sh`) made containers `judge`, `verifier`, `front` with `--restart unless-stopped`; if they still exist they start with Docker and hold ~31 GB of the card (0.22 + 0.105) and 127.0.0.1:80. The box needs 0.40 + 0.20 of the card | read; whether they exist: unknown (the build's switch to the classic image store probably left them without an image) | stop or wrong (the box's model servers short of memory) if they run | probe `docker ps -a`; if there: `docker rm -f judge verifier front` before the start | lane G |
| B12 | 01-bundle | `fetch "$BUNDLE_SRC"` | the start downloads the ~35 GB bundle that the same VM uploaded an hour before | read | cost (~3-5 min) | optional: use the build's copy when its sha256 matches (conflicts with B1's removal; keep B1) | lane G |

Counts: 12 predicted. By severity: **stop 6** (B1, B2, B3, B4, B5, B9; B11 possible), wrong 2 (B7, B8), cost 4
(B6, B10, B12, and B11 if harmless). By certainty: ran 3 (B2, B3, B5), read 6, unknown-fact 3 (B4, B9, B11; B3's
outcome too).

### What the next launches meet, in order (with the patches applied)

1. **The build launch (b01-b07)**: b05 continues past F6 to `docker save` of 8 images, the host tree, `release.py
   build`, the signature, `release.py check`; b06 stages a second copy; b07 uploads and (patch 01) removes the
   local copy. Risk left: disk (B1) before patch 01 can help, since b05/b06 peak at two copies. Know `df` first (D).
2. **The start (01-12)**: preflight now refuses without a TPM (B4) in minute 1; 01 frees the build's space (B1);
   02 installs the host packages (B3), places the weights (B9 must hold), runs install.sh with a heartbeat that
   survives its silent verify (B2); 03-12 as before, with B7 and B8 as wrong results only.
3. **acc (50-79)**: 51 no longer reloads the models (B6); each set's waits now keep the VM alive (B5).

---------------------------------------------------------------------------------------------------------------------

## C. Checked and found correct (no need to re-check)

| What | How |
| --- | --- |
| The answers file (`deploy/gcp/validation-site-answers.yaml`) through the real settings wizard | ran: `.env` has `TB_ENV=VALIDATION`, `TB_MAIL_PER_RECIPIENT_PER_DAY=0`, `TB_JOBS_PER_SENDER_PER_DAY=0`, `TB_MAIL_AUTHSERV_ID=mx.hospa.test`, `TB_TZ=Asia/Taipei`, `TB_SOURCE_DIR=./site/feed`, `COMPOSE_PROFILES=gpu`; no TLS host (VALIDATION allows that: the console stays on 127.0.0.1, `install.sh:360-362`); no SAE mailbox (a warning outside PRODUCTION) |
| install.sh's backup step on this box | read: `backup_schedule.install_cron` needs an alert route only in PRODUCTION; no backup key = "first backup: not yet", exit 0 |
| memcaps on a fresh box | ran: no lake and no `TB_SITE_PATIENTS` keeps the compose caps; the accuracy sets are a few thousand patients, far from T-692's 50k (16-17 GB) |
| Host-python steps install.sh runs, on a stdlib-only python | ran: `secrets init` (makes `operator.token` the driver's qualify uses), `memcaps`, `images_lock check-compose` (PASS), `image_pins`, `backup-install`, `update` import fine. Only anchors-compose and pre-start need PyYAML (B3) |
| The measured serving record | ran: `serving_config measured rtxpro6000 deploy/measured/serving_config.rtxpro6000.json` → "measured on rtxpro6000" (install.sh:441-460 passes) |
| make_bundle.sh's image list with `TB_TZ=UTC` | ran (real script, real compose render, recording shim): trialbox-py, trialbox-jvm, trialbox-postgres:16-1, trialbox-embed, vllm/vllm-openai:v0.32.0@sha256:befccf…, hapiproject/hapi:v8.12.0-2@…, caddy:2.11.9-alpine@…, authelia/authelia:4.39.28@… |
| The judge's chat template source | ran: the registry's URL at revision 4d7ae498… answers without a token and hashes to ae53464b… as the driver expects; the the embedder files at 7b44caba… answer too |
| `trialbox eval qualify --box` | read + ran help: dispatched before argparse (`tools/trialbox/__main__.py:38`) to `tools/box_qualify.py`; the rest of the flags the driver passes (`--profile --gateway-url --operator --out --evidence`) exist in `tools/qualify.py` |
| Other flags the driver passes | ran `--help`: doctor `--live --json --env-file`, selftest `--deploy`, serving_config capture `--container --models-dir --notes --out`, medtxt_eval fetch, chat_template_check hf `--model --prompts --out --template`, adapter.cli run `--source --path --snapshot` |
| Compose names the driver uses | read: networks `trialbox-net`, `trialbox-model-net` are fixed names; services `llm-service`, `llm-verifier`, `gateway`, `orchestrator`, `mail-gateway`, `adapter`, `lake`; every service has `env_file: [.env]`, and the tripwire is mapped explicitly (`docker-compose.yml:326`), so 51's settings reach the containers |
| Two model servers on one card | read: 0.40 + 0.20 of the card, the verifier starts after the judge is healthy; health start period 300 s, 40 retries x 30 s; install.sh waits 900 s for the whole stack; measured loads 117 s + 82 s |
| Egress rules after install | read (`deploy/egress.py`): only the box's own compose networks are filtered; the VM host (fetch, uploads) and `docker run --network bridge` (the medtxt fetch) are not |
| The registry's rtxpro6000 rows vs the driver's model links | read: snapshot revisions a19cfe00… (judge) and e4d2d39c… (verifier) and the template revision 4d7ae498… are the registry's own |
| Lane G's accuracy tools on the VM's python | ran: the real acc-tools tarball (`box_run acc-tools`), stdlib-only python 3.13: `fetch --only tcga`, `--only chia`, `build --set tcga --size 20`, `--set chia --size 5 --for-box` all work; MRNs are 8 digits (the site's `mrn_regex`); each trial's investigator is in the feed's practitioner.csv |
| The redaction filter of the install log | ran: it passes lines through as they come (not a buffering fault) |
| Sealed site keys and pidmap | read: `tb_common.crypto.load_key` opens a `.wrapped` key through the KEK, so `onbox pidmap` in the adapter container works on a sealed box |
| validation-check and the estimate | ran (free): `can_run true`, no blockers; the pair is candidate and routes in VALIDATION for judge D3, the compile's calls and qualify's D0 |

---------------------------------------------------------------------------------------------------------------------

## D. Not knowable without the GPU VM, and the cheapest way to learn each

Four of these are **free** (an API read, no VM start); the rest fit in **one probe boot** that prints facts and
stops: a VM start with a 20-line startup script and no model load is about 3-5 minutes, about US$0.25, instead of
one paid stop per fact.

| Fact | Decides | Cheapest way |
| --- | --- | --- |
| Does tb-gpu-sim have a vTPM (Shielded VM)? | B4 | free: `gcloud compute instances describe tb-gpu-sim --zone asia-east1-a --format='value(shieldedInstanceConfig)'` |
| Disk size and type (pd-balanced? hyperdisk? its throughput) | B1, B2 | free: `gcloud compute disks describe <boot disk> --format='value(sizeGb,type,provisionedThroughput)'` |
| Is `e-embed-1.sha256` in the bucket? | B9 | free: `gcloud storage ls gs://<bucket>/r2/models/e-embed-1.sha256` |
| What the build launches already recorded | B1 | free: the serial output of the last launch (`get-serial-port-output`) and the results.tgz parts |
| OS release; `python3 -c 'import yaml, cryptography'`; `command -v nft systemd-creds`; `/etc/cron.d` | B3, B4 | probe boot |
| `df -B1 / /tmp`; is /tmp a tmpfs; `du -sxb /models /var/lib/docker /srv/tb-build` | B1, B10 | probe boot |
| `docker info` (storage driver, containerd snapshotter on or off, nvidia runtime); `docker ps -a` (judge, verifier, front?); `docker system df` | B1, B11 | probe boot |
| `nvidia-smi` (driver version, memory used at idle) | B11, install.sh's `check_host.sh --gpu-only` | probe boot |
| The two snapshot folders exist (`ls /models/<judge weights>…`, `…<verifier weights>…`) | 02's models-place, pin_model --install | probe boot |
| Disk read rate: `dd if=<a 2 GB blob> of=/dev/null bs=16M` | B2's minutes | probe boot |
| The real bundle size | B1 | the next build's b05 (the size is printed by make_bundle.sh) |
| The gateway accepts the operator token for qualify's D0 route on a real box | 08 | only the start itself (validation records a failed qualify, no stop) |
| Real model-server load under compose, real compile and screen rates on the installed box | E | only the start and the first set |

The probe can be a startup script given with `--metadata-from-file startup-script=probe.sh`, ending in
`systemctl poweroff`, and printing to the serial port; it needs no new driver code. It is the lead's call (paid).

---------------------------------------------------------------------------------------------------------------------

## E. Budget fit

Money: limit US$150, spent US$61.27 (log), left US$88.73; the owner's working figure is about US$85. Price
US$2.74/h spot.

From the driver's own estimate (`tools.box_run estimate --mode validation --steps "start acc"`, run here, free):

| Part | Hours | US$ | Source |
| --- | --- | --- | --- |
| The build launch again (b01-b07) | about 1.2 | 3.3 | log: b01-b04 took 0.65 h; b05-b07 derived: `docker save` of ~35 GB, sign, check, stage, upload ~0.5 h |
| The start (boot, 01-12) | about 1.5 to 2 | 4.1 to 5.5 | boot 0.25 h (BOOT_HOURS); 02 ~0.5 h (B2's verify and load, the model loads); canary 124 s; qualify not measured on real weights (300 synthetic items + medtxt, pair + determinism: tens of minutes at the plan's rate) |
| acc, Run A as scoped (8 sets) | 3.29 to 18.54 | 9.0 to 50.8 | `plan.py` on the pinned data, rates 0.403 calls/s (compile) and 4.502 calls/s (screen at 16); the installed box's rate is **not measured** |
| Total | 6.0 to 21.7 | 16.4 to 59.6 | |
| Reserve for first-contact stops | | ~US$5-10 | each stop costs a boot (~0.25 h) plus the step |

**Verdict: as scoped it fits US$85 at the plan's high bound (about US$60 with the build and the start), with about
US$25 to spare, if the installed box runs at the rates the plan assumes.** It does not fit if the real box is more
than about 1.3 times slower than the plan's high bound (18.54 h x 1.3 = 24 h = US$66, plus US$9 = US$75, plus a
reserve). The VM's hard cap for acc is 28 h = US$76.72: by itself that cap is above what is left once the build and
the start are paid, so the cap does not protect the budget.

The even shrink that fits: measure the rate on the first two sets (jmed and tcga are the smallest, 0.15 h and 0.64 h
at the high bound). If the measured high-bound time is r times the plan's, scale every remaining set's size by
s = 24 / (18.54 x r) (24 h of acc is what US$85 leaves after the build, the start and a US$10 reserve). For example
r = 2 gives s = 0.65: every set at 65 % of its size. Set the acc cap (`tb-max-minutes`) to 24 h, not 28 h.
Run the sets in increasing cost (jmed, tcga, chia, jrct, sigir, trec2023, tfda, trec), so a stop or a pre-emption
loses the least, and trec (1.5 to 8.5 h alone) comes last.

---------------------------------------------------------------------------------------------------------------------

## F. Stopping this from recurring

Replace the stand-ins that hid real faults with the real scripts, keeping only what truly needs the GPU or the cloud:

1. **Real `make_bundle.sh` with a recording `docker` shim** that passes `docker compose ...` to the real CLI (it
   renders without a daemon) and records every `image inspect`, `pull`, `tag`, `save`. Shown here: it reproduces
   F5 in a second and prints the 8 images. Trivial to add; it would have saved one launch.
2. **Real `install.sh` in the product's own rehearsal host** (`tools/rehearse_box/host.Dockerfile`, Ubuntu 24.04),
   but in VALIDATION with lane G's answers, and a second host image **without** python3-yaml (a plain GCE image).
   VALIDATION is the only mode that seals keys: give the rehearsal host a software TPM (swtpm) or a hardening.conf
   with the passphrase back end, so the seal runs somewhere before a paid VM.
3. **Every host-python call under a stdlib-only interpreter** (a venv made with `--without-pip`, no site packages):
   one test that runs each `python3 -m tools.X` install.sh and the driver call, with `--help` or a dry argument. It
   found B3 here in seconds.
4. **Contract tests, one per driver-to-product call**, failing when the product changes a flag, an env name or an
   endpoint:
   * argparse contracts: build each tool's parser and assert the flags the driver passes (qualify `--box` dispatch;
     pin_model `--promote --record --environment --resolve --env-file --verify-all --out`; doctor `--live --json
     --env-file`; selftest `--deploy`; serving_config capture; medtxt_eval fetch; chat_template_check hf; adapter.cli
     run; make_bundle.sh `--key --id --release-seq --out --gates --sbom-dir`; install.sh `--answers --gpu --mode
     --yes`);
   * import contracts for onbox.py, run **in the built image** at b03 on the build VM (free there): `mail_gateway.app.
     gateway().handle`, `gateway.policy.parse_label`, `RoutingPolicy.candidates`, `registry.registry.Registry.resolve`,
     `tracestore.store.TraceStore.read`, `tb_common.crypto.pid_for_mrn`, `orchestrator.scenarios.screen_cascade`;
   * compose contracts from `docker compose config --format json` (no daemon): the network names, the service names,
     `env_file`, the model servers' `--model=` and `--chat-template=` arguments that box_qualify and G-1 parse.
5. **Real time in one rehearsal case**: a stand-in step that is silent for longer than the idle limit while it
   reads the disk (B2), and an acc wait that outlasts it (B5). The rehearsal's one-second minute hides every
   watchdog fault.
6. **A disk ledger at b01 and 01**: the sum of `docker image inspect --format {{.Size}}` of the bundle's images
   times the copies each step makes, against `df`, before the first copy; refuse with the numbers.
7. **A probe group** (`tb-steps=probe`): the facts of D printed in the first minute of every launch (it costs
   nothing on a launch that runs anyway) and as its own 5-minute launch before a new kind of run.
