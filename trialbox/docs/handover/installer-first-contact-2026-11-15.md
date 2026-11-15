# Hand-over: the bundle and the installer on a real GPU VM (lane G, 2026-11-15)

**Reader:** the people who build TrialBox (the integrator and lane D).

For the integrator and lane D. Written by lane G. The evidence (logs, step states, the chain review and its patches,
cleaned of anything secret) is in the folder
[installer-first-contact-2026-11-15/](installer-first-contact-2026-11-15/README.md).

Three commits are named all through this page:

| Name here | Commit | What it is |
| --- | --- | --- |
| evidence commit | `ac36aa21fdc1a67795eb838018a433a586971db9` | the commit the bundle was built from. Its product files are master's at train 22 (`d2302999`): lane G changed no product file |
| lane G head | `7cd0250cdac1b43e1f0c234468ec3ef581d9b8c5` | branch `claude/lane-g-box-accuracy`, PR #649, the driver as it is now |
| master | `78c6fc5fc78253cc0ab412e8e37b32dd13bac62c` | train 27, read on 2026-11-15 after the last launch |

A line reference such as `install.sh:583` is at the evidence commit unless it says "master".

## 1. In one paragraph

On 2026-11-15 lane G tried, for the first time anywhere, to build a signed bundle on a GPU VM and install it with the
real installer (`deploy/install.sh --answers`) as a VALIDATION box. The build passed on its ninth VM boot, after eight
faults (F1 to F8): missing build tools, a resume bug, two image gates, a compose variable, Docker's image store, and
the disk, twice. The bundle `val-ac36aa21fdc1` (29.6 GB, signed with a throwaway key, not a release) was then
installed. The install verified and loaded the bundle in under three minutes, wrote the settings, failed to pin the
model pair (F10, a warning only), made the site keys, and stopped while sealing them: `systemd-creds encrypt
--with-key=host+tpm2` said "Failed to create TPM2 context: Operation not supported" (F9). Lane G found the cause
(the VM image has no TSS2 libraries, which systemd loads at run time) and proved it on a second attempt, which then
stopped at once because the box refused the same bundle a second time (F11). The owner then ruled that the proof of
concept needs the main system running, not the delivery wrapping. So lane G leaves the bundle and installer route for
PoC-1. Nothing after key sealing has ever run on a real box. The route still matters for a hospital delivery. The VM
is stopped; the bundle stays in the private bucket; four faults are open (F9b, F10, F11, F12).

## 2. Where everything is

### 2.1 How to look at the installer yourself

The installer and every tool it runs are in this repository. Read them at the evidence commit (what ran) and on
master (what is there now). The table gives both. Links go to GitHub at the exact commit.

| Order | Path | What it does | Evidence commit | Master now |
| --- | --- | --- | --- | --- |
| 1 | `Makefile` target `images` (:311) | builds trialbox-py, -jvm, -embed, -postgres; needs `jvm-deps` (:303), which runs `tools/fetch_jvm_deps.sh` (needs `mvn`, :64) | [Makefile](https://github.com/zandis/Auto-GPT/blob/ac36aa21fdc1a67795eb838018a433a586971db9/trialbox/Makefile#L303-L320) | [Makefile](https://github.com/zandis/Auto-GPT/blob/78c6fc5fc78253cc0ab412e8e37b32dd13bac62c/trialbox/Makefile#L305-L322): same, plus a TB_TZ for the gate list (D-828) |
| 2 | `Makefile` targets `trivy-db` (:549), `release-gates` (:555) and `tools/supply_chain/` | scans every image of the bundle and writes `gates.json`; `RELEASE_GATES_ARGS="--vuln-mode report"` is the report mode | [supply_chain](https://github.com/zandis/Auto-GPT/tree/ac36aa21fdc1a67795eb838018a433a586971db9/trialbox/tools/supply_chain) | [supply_chain](https://github.com/zandis/Auto-GPT/tree/78c6fc5fc78253cc0ab412e8e37b32dd13bac62c/trialbox/tools/supply_chain): test mail images report-only (D-827), containerd store (D-830) |
| 3 | `tools/make_bundle.sh` (`make release-bundle`, :569) | lists the images from compose, checks them against `gates.json` (`supply_chain bundle-check`), `docker save`s them, adds the host tree, writes `release.json` (`tools/release.py`), signs (`tools/sign_bundle.py`) | [make_bundle.sh](https://github.com/zandis/Auto-GPT/blob/ac36aa21fdc1a67795eb838018a433a586971db9/trialbox/tools/make_bundle.sh) | [make_bundle.sh](https://github.com/zandis/Auto-GPT/blob/78c6fc5fc78253cc0ab412e8e37b32dd13bac62c/trialbox/tools/make_bundle.sh): every required compose variable (D-828), space check (D-830) |
| 4 | `tools/verify_update.py` | checks the Ed25519 signature with a key the box trusts, every hash, the release seq (:275), the room to stage (:345, 1.05 x) | [verify_update.py](https://github.com/zandis/Auto-GPT/blob/ac36aa21fdc1a67795eb838018a433a586971db9/trialbox/tools/verify_update.py) | unchanged |
| 5 | `deploy/box-install.sh` | the box form: detects the hardware, plans the answers (`tools/box/plan.py`), runs install.sh with `TB_BOX=1`, then the first-run wizard. Lane G did not use it | [box-install.sh](https://github.com/zandis/Auto-GPT/blob/ac36aa21fdc1a67795eb838018a433a586971db9/trialbox/deploy/box-install.sh) | unchanged |
| 6 | `deploy/install.sh` | the installer: host checks, bundle verify and load (`tools/apply_update.sh`), settings (`tools/settings_wizard.py`), model pins, site keys and their seal, database, stack, egress, systemd units, cron, backups, host check | [install.sh](https://github.com/zandis/Auto-GPT/blob/ac36aa21fdc1a67795eb838018a433a586971db9/trialbox/deploy/install.sh) | [install.sh](https://github.com/zandis/Auto-GPT/blob/78c6fc5fc78253cc0ab412e8e37b32dd13bac62c/trialbox/deploy/install.sh): host python3 check, heartbeat (D-831), PostgreSQL sizing, boot wait |
| 7 | `tools/apply_update.sh` | stages the bundle under `${TMPDIR:-/tmp}` (:87), verifies, loads images, switches `current` | [apply_update.sh](https://github.com/zandis/Auto-GPT/blob/ac36aa21fdc1a67795eb838018a433a586971db9/trialbox/tools/apply_update.sh) | unchanged |
| 8 | `deploy/hardening/seal_keys.sh` | makes a KEK, wraps the site keys under it (:79), seals the KEK with `systemd-creds` (:80) | [seal_keys.sh](https://github.com/zandis/Auto-GPT/blob/ac36aa21fdc1a67795eb838018a433a586971db9/trialbox/deploy/hardening/seal_keys.sh#L64-L91) | unchanged |
| 9 | `deploy/hardening/hardening.example.conf` | the template of `deploy/site/hardening.conf`: `KEK_BACKEND=tpm` (:14), firewall ranges, `SSH=off` | [hardening.example.conf](https://github.com/zandis/Auto-GPT/blob/ac36aa21fdc1a67795eb838018a433a586971db9/trialbox/deploy/hardening/hardening.example.conf) | unchanged |
| 10 | `deploy/check_host.sh` | host checks; GPU-only part at the start, full at the end (install.sh:826) | [check_host.sh](https://github.com/zandis/Auto-GPT/blob/ac36aa21fdc1a67795eb838018a433a586971db9/trialbox/deploy/check_host.sh) | unchanged at the lines cited here |
| - | `deploy/docker-compose*.yml`, `tools/pin_model.py`, `tools/settings_wizard.py`, `tools/box/` | what install.sh starts and calls | [deploy/](https://github.com/zandis/Auto-GPT/tree/ac36aa21fdc1a67795eb838018a433a586971db9/trialbox/deploy) | [deploy/](https://github.com/zandis/Auto-GPT/tree/78c6fc5fc78253cc0ab412e8e37b32dd13bac62c/trialbox/deploy) |

The product's own rehearsal of a real install (a TEST box with stand-in models, US$0, Docker needed):
`make rehearse-box` (Makefile:467, `tools/rehearse_box/rehearse.sh`). It never seals keys: a TEST box does not.

### 2.2 `TB_BOX_DEFER_SEAL=1`: the setting lane G now uses

| Question | Answer |
| --- | --- |
| Where | `deploy/install.sh:581-582` (master :625-626). Described in the comment at :46-49 |
| What it does | install.sh skips `seal_keys.sh` and prints "site keys: sealed at the box's apply step, under the owner's passphrase (box-install.sh, T-729)". The keys stay plain files in the secrets volume |
| Who sets it | `deploy/box-install.sh:99-105`, when its hardware check found no TPM device; the box's apply step then seals under the owner's passphrase |
| Documented | Only in that comment and in decision D-466 section 5. Not in the RUNBOOK. Not a declared setting (`libs/tb_common/config.py` has no entry) |
| Lane G's use | Since lane G head (`box-install-run.sh:684-685`), the PoC install runs install.sh with it, after the owner ruled that key sealing is not needed for a public-data PoC. The notes of every start say "not sealed" |
| What it leaves | With install.sh alone nothing seals the keys later (that is box-install.sh's apply step). `check_host.sh:147-157` FAILs a plain site key in VALIDATION, so install.sh ends with exit 1 after printing "TrialBox is running" (install.sh:861, :869-871). Lane G's driver accepts that end. Not yet seen on a real box |

### 2.3 Lane G's driver (the cloud side)

| Path (lane G head) | What it does |
| --- | --- |
| [deploy/gcp/box-run.sh](https://github.com/zandis/Auto-GPT/blob/7cd0250cdac1b43e1f0c234468ec3ef581d9b8c5/trialbox/deploy/gcp/box-run.sh) | runs on the lead's machine: sets up the VM's metadata and caps, starts it, `--collect`, `--resume`, `--stop`, `--estimate`, `--dry-run` |
| [deploy/gcp/box-install-run.sh](https://github.com/zandis/Auto-GPT/blob/7cd0250cdac1b43e1f0c234468ec3ef581d9b8c5/trialbox/deploy/gcp/box-install-run.sh) | the VM's startup script: steps b01-b07 (build) and 01-12 (start), watchdog, cost cap, results to the bucket after every step |
| [deploy/gcp/box_vm.py](https://github.com/zandis/Auto-GPT/blob/7cd0250cdac1b43e1f0c234468ec3ef581d9b8c5/trialbox/deploy/gcp/box_vm.py) | the VM-side helper (redaction, model folders, the wizard, calls into the box) |
| [tools/box_run.py](https://github.com/zandis/Auto-GPT/blob/7cd0250cdac1b43e1f0c234468ec3ef581d9b8c5/trialbox/tools/box_run.py) | metadata, estimates, validation-check, reports |
| [deploy/gcp/validation-site-answers.yaml](https://github.com/zandis/Auto-GPT/blob/7cd0250cdac1b43e1f0c234468ec3ef581d9b8c5/trialbox/deploy/gcp/validation-site-answers.yaml) | the synthetic site's answers; `env_extra: TB_ENV: VALIDATION` |
| [tests/rehearsal/box-run/](https://github.com/zandis/Auto-GPT/tree/7cd0250cdac1b43e1f0c234468ec3ef581d9b8c5/trialbox/tests/rehearsal/box-run) | the local rehearsal: shims for docker, gcloud, mvn, java, nvidia-smi, systemctl; stand-ins for make_bundle and install.sh. 22 cases, US$0 |

Re-run lane G's local rehearsal, from `trialbox/` on the lane G branch: `tests/rehearsal/box-run/rehearse-box-run.sh`.

### 2.4 The bundle and the runs

| Item | Value |
| --- | --- |
| Bundle | `val-ac36aa21fdc1`, 29,611,929,600 bytes (29.6 GB), 29 files in its manifest, release seq 1, version 1.0.0, commit `ac36aa21`, not dirty, not a rehearsal bundle |
| Status | **Not a release.** Signed with a throwaway key made on the build VM; only its public half left the VM. Gates **not all green**: run in report mode for the two test-only mail images (mailpit, greenmail) |
| Where | the private bucket `gs://trialbox-demo-runs/r2/val-ac36aa21fdc1/` (the bundle, its `.sha256`, the throwaway public key). Not public |
| Images in it | trialbox-py, trialbox-jvm, trialbox-embed, trialbox-postgres:16-1, vllm/vllm-openai v0.32.0, hapiproject/hapi v8.12.0-2, caddy 2.11.9-alpine, authelia 4.39.28 (8) |
| VM | tb-gpu-sim (g4-standard-48, one RTX PRO 6000), Ubuntu 24.04, Docker 29.9.3, systemd 255, disk enlarged 200 to 400 GB at 09:21 |
| Run ids | build `box-20261115T060826Z-f6bcc176`, `box-20261115T073901Z-e7504de38`, `box-20261115T080047Z-5618bd840`, probe `box-20261115T085016Z-876ff6506`, build `box-20261115T091037Z-ac36aa21f` (complete), install `box-20261115T094747Z-4c7c47017` |
| Results | `gs://trialbox-demo-runs/boxruns/<run id>/results.tgz`, cleaned copies in the evidence folder |

### 2.5 How to reproduce one launch

Every command but `--estimate`, `--dry-run` and the rehearsal starts a paid VM: the owner's yes first, the cost posted
first, one VM at a time. Placeholders in angle brackets. No secret is typed on a command line.

    export CLOUDSDK_CONFIG=<a private folder> TB_SA_KEY_FILE=<the deployer's key file> TB_BUCKET=gs://trialbox-demo-runs
    cd trialbox                                        # on branch claude/lane-g-box-accuracy
    tests/rehearsal/box-run/rehearse-box-run.sh        # free, a few minutes
    deploy/gcp/box-run.sh --estimate --mode validation --steps build
    git bundle create /tmp/src.bundle <COMMIT> && gcloud storage cp /tmp/src.bundle "$TB_BUCKET/r2/val-<commit12>/src.bundle"
    deploy/gcp/box-run.sh --mode validation --steps build --release-id val-<commit12> --release-seq 1 --commit <COMMIT> --dry-run
    deploy/gcp/box-run.sh --mode validation --steps build --release-id val-<commit12> --release-seq 1 --commit <COMMIT> --no-wait
    deploy/gcp/box-run.sh --collect <run id> --follow
    deploy/gcp/box-run.sh --mode validation --steps start --release-id val-<commit12> --no-wait     # the install
    deploy/gcp/box-run.sh --resume <run id>            # after a fix: finished steps kept, the stopped one again
    deploy/gcp/box-run.sh --stop <run id>              # checks TERMINATED and puts the VM back

## 3. The path as it really runs

Times are measured on the VM unless marked. "Got through" says whether lane G passed the step on 2026-11-15.

| # | Step (driver step) | Needs from the host | Prints | Time | Got through |
| --- | --- | --- | --- | --- | --- |
| 1 | source (b01): the commit from a git bundle | git, network to the bucket | clone, checkout | 11-18 s | yes |
| 2 | `make venv scanners` (b02) | python3 with venv, network to PyPI and the scanners' downloads | pip | 11-22 s (the VM had run builds before; a fresh VM: not measured) | yes |
| 3 | `make images` (b03), and the demo image the gates also scan | Docker, **Maven and a JDK 21** (fetch_jvm_deps.sh:64), network to Docker Hub, Maven Central, GitHub | docker build | 2 min 41 s to 5 min 6 s | yes, after F1 |
| 4 | `make trivy-db release-gates` (b04) | the scanners, network to the vulnerability databases; every image of the bundle present, the demo image too | PASS/FAIL per image | 4 min 51 s to 5 min 56 s | yes, after F3, F4 (report mode) |
| 5 | `tools/make_bundle.sh` with a key (b05) | a `TB_TZ` (F5), the classic image store or master's D-830 (F6), **free disk for two copies of the bundle** under TMPDIR and `--out` (F7, F8) | the image list, bundle-check PASS (8 images), the saves, sign | 521 s | yes, after F5 to F8 |
| 6 | `tools/verify_update.py` with the public key (b06) | python3 with cryptography, a staging copy | verified | 51 s | yes |
| 7 | upload (b07) | network to the bucket | - | 73 s | yes |
| 8 | VM start of the install launch | - | - | about 45 s from launch to boot | yes |
| 9 | fetch and check the bundle (01) | the bundle's size free, network | sha256, manifest | 75 s (the fetch 31 s at 2.0 GiB/s) | yes |
| 10 | host packages (02, driver) | apt; python3-yaml, python3-cryptography, nftables, cron, **tpm2-tools** (F9) | packages added | 5 s; 15 s with tpm2-tools | yes |
| 11 | model folders (02, driver) | the pair's weights on the VM, the embedder from its public source | links and fetched files | 55 s first time, 11 s after | yes |
| 12 | install.sh: host checks | root, Docker 27+ with compose, NVIDIA driver 580.65.06+, python3 with PyYAML (master checks it first, D-831), the vendor public key at `deploy/keys/vendor_ed25519.pub` (:192) | PASS lines | seconds | yes |
| 13 | install.sh: bundle verify and load (:233-234) | 1.05 x the payloads free under TMPDIR, twice | the file list, "release: ... -> releases/val-ac36aa21fdc1" | inside 2 min 41 s for steps 12 to 17 together | yes |
| 14 | install.sh: settings (wizard, `--answers`) | - | warnings: no TLS host, no SAE mailbox (VALIDATION allows both) | seconds | yes |
| 15 | install.sh: pin the model pair (:424-438) | write access to `deploy/site` **for the image's user** (F10) | traceback, "a model of the rtxpro6000 pair is not pinned" | seconds | **no**: a warning, the install went on with no pins |
| 16 | install.sh: site keys made (:574-576) | Docker volumes | "made" per key | seconds | yes |
| 17 | install.sh: keys sealed (:577-589) | root, systemd 250+, systemd-creds, a TPM 2.0 device, **the TSS2 libraries** (F9) | "Failed to create TPM2 context: Operation not supported" | - | **no**: stop |
| 18 to 30 | database, stack, egress, systemd units, cron, promotion, backups, host check, URL | see section 6 | - | not measured | never run |

## 4. Every fault

"VM min lost" is VM time that bought nothing, from the run log. The reds are lane G's comments on PR #639.

| # | When (UTC) | Step | What happened | Root cause (file:line) | Whose | Fixed how, or open | VM min lost | Red |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F1 | 06:12 | b03 | `make images` stopped: mvn not found | `tools/fetch_jvm_deps.sh:64` needs Maven; CI runners have it, the VM image does not | lane G (build host) | driver installs Maven and the JDK: 3b4adb40, c67e96f8. Master: still needs mvn (by design) | 4 | - |
| F2 | 06:29 | resume | the resumed VM booted without its run | the collect's reset removed every `tb-*` metadata key | lane G | e7d6bfd3 | 4 | - |
| F3 | 06:42 | b04 | gates failed | (a) the demo image is built by CI, not by `make images`; (b) new fixable CVEs in the test-only mailpit and greenmail images, gates in block mode (Makefile:555) | (a) lane G, (b) lane D | a441cecd (report mode for a validation build). Master: D-827, PR #698 (test mail images report-only in every mode) | 11 | [6890673656](https://github.com/zandis/Auto-GPT/pull/639#issuecomment-6890673656) |
| F4 | 07:00 | b04 | demo image still missing | a fix to b03 does not run when b03 is kept on resume | lane G | 70d10eba | 6 | - |
| F5 | 07:17 | b05 | "compose listed no trialbox-py image" | `make_bundle.sh:104` stages a `.env` with only TB_TLS_HOSTNAME; compose needs `TB_TZ`; `:109` discards compose's error | lane D | 2214674b (TB_TZ=UTC for that call). Master: D-828, PR #704 (`make_bundle.sh:103-108`) | 4 | [6891173775](https://github.com/zandis/Auto-GPT/pull/639#issuecomment-6891173775) |
| F6 | 07:52 | b05 | bundle-check rejected all four third-party images | `tools/supply_chain/__main__.py:113` compares the local image Id; under Docker's containerd store that is the index digest, the gates recorded the config digest | lane D | 5618bd84 (classic store on the build VM). Master: D-830, PR #709 (`__main__.py:118-119`) | 13 | [6891396791](https://github.com/zandis/Auto-GPT/pull/639#issuecomment-6891396791) |
| F7 | 08:21 | b05 | no space left on device while saving the vLLM image | 44 GB free of 193 GB: 47 GB of unused images in the old containerd store, 29 GB of build images; the bundle needs about two copies at b05 | lane G (VM disk) | 44303db0 (old store removed, staging under the build root). Master: D-830 now checks the space before the first save (`make_bundle.sh:130-132`, `tools/bundle_space.py`) | 9 | [6891631432](https://github.com/zandis/Auto-GPT/pull/639#issuecomment-6891631432) |
| F8 | 09:31 | b05 | no space again, in the signing | 51 GB free at b05; the disk enlarged online at 09:21 was not yet in the file system | lane G (VM disk) | disk 200 to 400 GB (lead), 4c7c4701 (grow the root at every boot) | about 10 | [6892387630](https://github.com/zandis/Auto-GPT/pull/639#issuecomment-6892387630) |
| F9 | 09:53 | 02, seal | "Failed to create TPM2 context: Operation not supported" | `seal_keys.sh:80` (`systemd-creds encrypt --with-key=host+tpm2`). The VM has a vTPM and systemd-creds, but not the TSS2 libraries that systemd loads at run time. The product judges a TPM by its device node only: `seal_keys.sh:67-68`, `tools/box/plan.py:150`, `check_host.sh:145` | VM image (lane G); the check: lane D | d647434b installs tpm2-tools; the second attempt recorded `has-tpm2` "yes" in every part and a round trip through the TPM: **cause confirmed**. Then 7cd0250c defers the seal (section 2.2). Product check: open on master | about 6 | not posted |
| F9b | 09:53 | 02, seal | the failed seal left a box no re-run can finish | `seal_keys.sh:79` wraps the site keys under a new KEK and writes `kek.json` before `:80` seals it; the trap at `:78` then shreds the only copy of the KEK. A re-run sees `kek.json` (`:56`) and needs a KEK nobody has. Read from the code; lane G wiped the volumes before the next attempt (`d_half_install`) | lane D | open on master | 0 (seen in the code) | not posted |
| F10 | 09:52 | 02, pin | `PermissionError: [Errno 13] Permission denied: '/d/site/manifests'`; the install went on with no pins | `install.sh:426-427` runs `pin_model --install` in trialbox-py, which runs as user `tb` (uid 10001, `deploy/docker/python.Dockerfile:48`), with `deploy/` mounted writable; `deploy/site` is made by root (`install.sh:420`; the box's facts show `root root 755`). `pin_model.py:277` cannot make the `manifests` folder there. The failure is only a warning (`install.sh:428`), so verify-all and the shipped promotion (`:689`) are skipped and the gateway routes nothing to the pair. Not reproduced off the VM | lane D | open on master (`install.sh:464-473`) | 0 (same launch) | not posted |
| F11 | 10:23 | 02, attempt 2 | "release_seq 1 is not above the installed 1 (a downgrade or a repeat)" | the first attempt's load recorded seq 1 as installed; `verify_update.py:275` refuses the same bundle; lane G's cleanup removed the volumes but not that record. install.sh's own message after a seal failure says "re-run" (`:588`), which cannot work with the same bundle | lane G (cleanup); lane D (re-run after a stop past the load) | open | about 2 | not posted |
| F12 | 09:53 | 02, facts | the box's facts lack `docker compose ps` | the facts command runs the driver's shell function `dc` through `timeout`, which cannot see it | lane G | open (facts only) | 0 | - |

Counts: 13 faults. Main owner: lane D 5 (F3b, F5, F6, F9b, F10), lane G 7 (F1, F2, F3a, F4, F7, F8, F12; F11 shared),
VM image 1 (F9; its product check is lane D's). Fixed: F1 to F8 (the product parts of F3, F5, F6 and the space check
of F7 are on master). Open: F9 product check, F9b, F10, F11, F12.

### The review's predictions (chain review, 08:40) and what happened

| # | Predicted | Outcome |
| --- | --- | --- |
| B1 | disk: the bundle up to four copies | **confirmed** (F7, F8) |
| B2 | install.sh silent 13 to 20 min, the watchdog powers off | **disproved on this VM**: install.sh's steps 12 to 17 took 2 min 41 s in all. Master added a heartbeat anyway (D-831) |
| B3 | host python3 lacks PyYAML | **disproved on this VM** (the probe: PyYAML 6.0.1); real on a plain host (reproduced locally). Master checks it first (D-831, install.sh:179-190) |
| B4 | no vTPM or systemd-creds: the seal dies | **confirmed in another form**: device and systemd-creds present, libraries missing (F9) |
| B5 | accuracy waits not streamed | not reached |
| B6 | the settings step recreates the model servers | not reached |
| B7 | the image tool lacks the release tree | not reached (fixed before) |
| B8 | doctor from the host shows a serving FAIL that is not real | not reached |
| B9 | the embedder's file list not in the bucket | **disproved** (present, fetched) |
| B10 | the serving record hashes all of /models | not reached |
| B11 | old model containers hold the card | **disproved** (none) |
| B12 | the start downloads the bundle again | **disproved as a cost** (31 s) |

Not predicted: F9b, F10, F11, F12.

## 5. Product behaviour a PoC or VALIDATION box does not need, that the installer forces today

| Behaviour | Where | A setting today? | What lane D would need to add |
| --- | --- | --- | --- |
| Key sealing with a TPM | install.sh:583-588, seal_keys.sh | Partly: `KEK_BACKEND=passphrase` (with `TB_KEK_PASSPHRASE`) or `shamir` in `deploy/site/hardening.conf`, but that file also turns on the input firewall and SSH rules (install.sh:629-632; template `SSH=off`), which can cut a cloud VM off. `TB_BOX_DEFER_SEAL=1` skips the seal (section 2.2) but is undeclared and meant for box-install.sh | **needs a PoC setting**: a declared, documented "keys not sealed" choice for a public-data box, that `check_host.sh` and doctor read as intended, not as a FAIL |
| A signature on every bundle | install.sh:192, verify_update.py | No (by design) | nothing; document the throwaway-key route (`tools/sign_bundle.py keygen`) for non-release bundles |
| Release gates | Makefile:555 | Yes: `RELEASE_GATES_ARGS="--vuln-mode report"`; test mail images report-only on master (D-827) | nothing for a PoC; the bundle should say "not all green" in `release.json` itself (lane G writes it in its own record only) |
| A clean commit, no rehearsal mark | `tools/trialbox/update.py:578-590` | No | nothing (build from a commit) |
| A release seq above the installed one | verify_update.py:275 | `--allow-downgrade REASON` on apply_update | **needs** a re-run of install.sh after a stop past the load (F11) |
| Daily limits | `libs/tb_common/config.py:707`, `:715` | Yes: `TB_JOBS_PER_SENDER_PER_DAY=0`, `TB_MAIL_PER_RECIPIENT_PER_DAY=0` | nothing |
| PHI tripwire | config.py:607 | Yes: `TB_GATEWAY_PHI_TRIPWIRE` | nothing |
| TLS host name | install.sh:354-364 | VALIDATION may run without (console on the loopback address) | nothing |
| SAE office mailbox | install.sh:376-382 | a warning outside PRODUCTION | nothing |
| Backup schedule and alert route | install.sh:742-756 | `TB_BACKUP_ALERT_ROUTE=health-page` (config.py:405); a non-box install stops when `backup-install` fails. Lane G sets it; whether VALIDATION needs it: not known | not known until it runs |
| Egress rules and systemd units | install.sh:622-662 | `TB_SYSTEMD=0` for the units; none seen for the egress rules | not known until it runs on a cloud VM |
| Plain keys FAIL the host check | check_host.sh:147-157 | No | the same PoC setting as the first row |
| The model pair routes only as champion | earlier finding (`first-accuracy-run.md` of lane G); master has since changed VALIDATION routes (D-794) | not re-checked here | not known |

## 6. What is still unknown beyond the seal

Nothing below has run on a real box. Lines are install.sh at the evidence commit.

| Step | Specific risk | Cheapest way to learn it |
| --- | --- | --- |
| model pins (:424-438) | F10: no pins, so the pair routes nothing; lane G's step 04 stops on the missing `registry.site.yaml` | free: run the pin step as root on a root-owned `deploy/site` in the product's rehearsal host |
| database up and `db-up` (:590-607) | host python3 runs it; memory sizing (master adds `pgsize`) | free: product rehearsal host in VALIDATION |
| stack up `--wait` (:608-609; master `bootwait`) | two model loads, about 3.5 min measured earlier; the wait 900 s | GPU VM only |
| `doctor --serving` (:610-621) | with no pins (F10) the served names may not match: a stop | GPU VM, or a stub check in the rehearsal |
| egress rules, systemd units (:622-661) | rules at boot on a cloud VM; the review read that only the box's own networks are filtered (`deploy/egress.py`) | free: rehearsal host; then the VM |
| cron, retention (:662-672) | cron present (lane G installs it) | free |
| shipped promotion and canary (:684-724) | skipped without pins (F10); with pins, the canary through the gateway on the real pair | GPU VM |
| backups (:738-757) | stops a non-box install if `backup-install` fails (B-route above) | free: rehearsal host in VALIDATION |
| audit head, judge name, host check, URL (:815-866) | host check FAILs plain keys (section 2.2): exit 1 after "TrialBox is running" | free |
| lane G 03 to 12: VALIDATION check, pin, serving record, G-1, canary, qualify, promote, resolve, doctor | B7, B8, B10 of the review; qualify never run on real weights | GPU VM |
| a re-run after any stop past the load | F11 | free: run install.sh twice with one bundle in the rehearsal |

The cheapest single step: the product's own rehearsal host (`tools/rehearse_box/host.Dockerfile`) running the real
install.sh in VALIDATION with lane G's answers and stand-in models (US$0). It would reach every free row above.

## 7. Why the local rehearsal caught none of this, and what to change

Lane G's rehearsal checked the driver against stand-ins written with the driver's own assumptions. Every fault sat
where a stand-in replaced a real program (chain review, section A). The product's `make rehearse-box` runs the real
install.sh, but as a TEST box, which never seals keys and, with stand-in models, never pins on a GPU.

| Stand-in today | Hid | Replace with |
| --- | --- | --- |
| `shims/mvn`, `shims/java` | F1 | a check that the build host has what `make images` calls (or a build host image with them) |
| `shims/gcloud` (no metadata state) | F2 | a gcloud shim that keeps metadata across launches and resets |
| `shims/docker` (no store, no gates) | F3, F6 | a recording shim that passes `docker compose` to the real CLI (it renders without a daemon), and a store test for both image stores |
| `standins/mkbundle.py` | F5, F7 | the real `tools/make_bundle.sh` with that recording shim (reproduces F5 in a second), plus a disk ledger |
| `standins/install-validation.sh`, `install-inner.sh`, `compose-up.sh` | F9, F9b, F10, F11 | the real install.sh in the product's rehearsal host, in VALIDATION, with a software TPM (swtpm) and a second host image without PyYAML or the TSS2 libraries |
| one-second minutes | B2, B5 | one case in real time with a step silent past the idle limit |

Contract tests, one per driver-to-product call (the review's section F.4, plus what this run added):

| Call | Contract to test |
| --- | --- |
| `make_bundle.sh --key --id --release-seq --out --gates --sbom-dir` | the flags; the image list renders with no site `.env` |
| `install.sh --answers --gpu --mode --yes` | the flags; `TB_BOX_DEFER_SEAL`; a second run with the same bundle after a stop (F11) |
| `install.sh` pin step as root | `deploy/site` writable by uid 10001 (F10) |
| `seal_keys.sh` | refuses before making a KEK when `systemd-creds has-tpm2` is not yes; no wrapped key without a sealed KEK (F9, F9b) |
| `pin_model --install --promote --record --resolve --verify-all --out` | argparse |
| `trialbox doctor --live --json --env-file`, `selftest --deploy`, `eval qualify --box` | argparse and dispatch |
| `serving_config capture`, `medtxt_eval fetch`, `chat_template_check hf`, `adapter.cli run` | argparse |
| onbox imports in the built image (`mail_gateway`, `gateway.policy`, `registry`, `tracestore`, `tb_common.crypto`, `orchestrator.scenarios`) | import at b03 |
| `docker compose config --format json` | network names, service names, `env_file`, the model servers' `--model=` and `--chat-template=` |

## 8. Recommendations to the integrator, ranked

1. **Lane D: fix F10 first.** The pin step fails for any root install on a GPU (the box form runs the same
   install.sh), and it fails quietly. Run it as root or make `deploy/site` writable by uid 10001, and make a failed pin
   a stop in GPU mode.
2. **Lane D: make install.sh re-runnable after a stop past the load (F11).** Skip the load when `current` already
   points at the same verified bundle, or record the release as installed only when the install ends. Its own error
   messages tell the operator to re-run.
3. **Lane D: prove the TPM before touching the keys (F9, F9b).** In `seal_keys.sh`, `tools/box/plan.py:150` and
   `check_host.sh:145`, ask `systemd-creds has-tpm2` (and a round trip), not the device node. Seal the KEK before
   wrapping any key. List the TSS2 libraries (`tpm2-tools` brings them) beside python3-yaml as host prerequisites.
4. **Lane D: a declared PoC/VALIDATION install mode.** One declared setting with a reason (OD-10), documented in the
   RUNBOOK: keys not sealed (what `TB_BOX_DEFER_SEAL` does now, but read by `check_host.sh` and doctor), no hardening
   file needed, the throwaway-key route for non-release bundles, the gates' report mode written into `release.json`.
5. **Lane D: run the real install.sh in the product rehearsal in VALIDATION** (swtpm, a plain host image), and add the
   contract tests of section 7. This would have found F9, F9b, F10 and F11 at US$0.
6. Lane D: list the build host's needs (Maven, JDK, disk for two bundle copies) in the release docs; master's D-830
   space check covers part.
7. Lane G keeps the cloud driver (`box-run.sh`, `box-install-run.sh`, `box_vm.py`, `box_run.py`, its rehearsal), the
   VM's facts, the estimates and the cost log, and will run the next real install when lane D's fixes land. Lane G
   hands over the installer path itself, F9b, F10 and F11, the PoC install mode, and the product-side rehearsal.

## 9. Cost of the attempt

US$2.74 an hour (spot). Hours and US$ from lane G's run log, except the install launch, which the log does not close.

| Launch | Run id | Boots | VM hours | US$ |
| --- | --- | --- | --- | --- |
| L1 build f6bcc176 | `box-20261115T060826Z-f6bcc176` | 5 | 0.61 | 1.68 |
| L2 build e7504de3 | `box-20261115T073901Z-e7504de38` | 1 | 0.22 | 0.60 |
| L3 build 5618bd84 | `box-20261115T080047Z-5618bd840` | 1 | 0.35 | 0.96 |
| L4 probe | `box-20261115T085016Z-876ff6506` | 1 | 0.09 | 0.25 |
| L5 build ac36aa21 (complete) | `box-20261115T091037Z-ac36aa21f` | 2 | 0.57 | 1.56 |
| Logged total | | 10 | 1.84 | 5.05 (the log's running total: 59.00 to 64.04) |
| L6 install | `box-20261115T094747Z-4c7c47017` | 2 | about 0.13 (derived: launch 09:47:47 to the last part 09:53:32, and about 10:22:45 to the upload at 10:24:22; the power-off times are not recorded) | about 0.36 |
| All | | 12 | about 1.97 | about 5.41 |

Nine of the ten logged boots were the build (L1, L2, L3, L5). Not in these figures: the disk enlarged from 200 to
400 GB at 09:21, billed per GB-month whether the VM runs or not; its rate is not verified.
