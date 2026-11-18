# Root review 24: the owner's workstation is an IGX Orin developer kit with an RTX A6000 (lane J, B26, 2026-11-18)

**Reader:** the owner, who will sit at the machine next week (section 0 is for him); then whoever cuts the version he
installs and whoever takes the head-box card (plan 10, 10E-31).

**What changed since review 23.** Review 23 and runbook page 27 (merged to master while this was written) assumed a 96 GB RTX PRO 6000 in an x86-64 workstation. The owner's `nvidia-smi`
screen shows something else: an **NVIDIA IGX Orin Development Kit** (an Arm 64-bit system-on-module with a PCIe slot),
an **RTX A6000** (49,140 MiB, Ampere, 300 W cap), **driver 535.183.01, CUDA 12.2**, an Ubuntu desktop and a conda
"(base)" shell. **The owner's answers, relayed by the coordinator the same day** [owner]: `uname -m` → `aarch64`;
`lsb_release -a` → Ubuntu 22.04.5 LTS; `free -g` → 53 GB total, 49 available, 26 GB swap; `df -h /` → one NVMe root
of 879 GB, 744 GB used, **91 GB free (90 % used)**. Still not known: Docker and its GPU runtime, the `nvidia-smi`
query line, internet, whether a second disk can go in.

**Marks.** [read `file:line`] in this repository at master `312eca7c` (merged up to `1f70d207` before the final checks) plus this branch; [source: link, opened
2026-11-18]; [measured: an output file under `/var/tmp/trialbox-0/b26/`, section 9]; [opinion]; [rNN] a review's own
marked claim. "Not verified" where not checked. Nothing was installed beyond `make venv`; no model was downloaded or
run; no Docker image was pulled (only registry metadata was read); nothing ran in a cloud.

---

## 0. One page for the owner

**Next week, on this machine, you can see the whole product run on the synthetic hospital, but not with the real
models.** [opinion, from sections 1 to 3]

- **What works:** every TrialBox image exists for Arm 64-bit, and the one-command start in its no-model mode (the
  "stub" model, a fixed stand-in that answers by rule) needs no GPU. You get the console, the test mailbox, a
  feasibility reply, a screened list of synthetic patients, and every screen. One extra command is needed first (it
  builds the database image, which the start forgets on a machine without Java build tools). This has **never been
  started on an Arm machine by anyone**: you would be the first, so expect to send us an error or two.
- **What does not work next week: the two real models on this machine.** Three separate reasons, each enough alone:
  1. **The driver.** Your machine's operating system (NVIDIA's IGX OS) carries driver 535 for the A6000, and every
     IGX Orin release NVIDIA publishes stays on 535; the newer 580 driver exists only for the newer IGX Thor. The
     model engine TrialBox pins is built for CUDA 13 and needs driver 580 or newer. Do not install another driver on
     this machine: it would leave NVIDIA's supported setup for that platform.
  2. **The card's generation.** The judge model is pinned in a 4-bit format (NVFP4) that only the newest cards
     (Blackwell) compute natively. On your Ampere card the engine would fall back to a slower path with different
     arithmetic. Nobody has run this judge that way, and it would need its own measurement before any result counts.
  3. **The settings.** TrialBox mistakes any Arm machine with a GPU for a DGX Spark and would give your 48 GB card the
     Spark's settings; the judge would not even fit. This branch fixes the mistake (the start now refuses the GPU mode
     on your machine and says why); a real profile for 48 GB cards is planned work (card 10E-31), not done.
- **If you want the real models next week** you need a different machine: an x86-64 computer with a 96 GB RTX PRO
  6000 (the only card ever measured; review 23's page 27 is written for it), or a rented cloud machine with that card
  (costs money; your decision). Your A6000 moved into an ordinary x86-64 PC with Ubuntu 24.04 and driver 580 would
  remove reason 1, but not reasons 2 and 3: those are the head-box measurement and profile already planned (10E-29,
  about 13 hours of the card, then 10E-31), not next week.

**Your disk is the first thing to fix:** 91 GB free on a 90 % full disk is enough for the no-model look (about 15
GB), not for the real models on any machine of this kind (about 120 GB with room to work; section 3). Free about 60 GB,
or add a second disk, before any model work. **Your memory (53 GB)** is enough for the no-model look and too little
for the two models by TrialBox's own rule (79 GB). **Before anything, send us three more command outputs and two
answers** (runbook 28, step 0): Docker, its GPU runtime, the card line; internet; a second disk.

---

## 1. Architecture: does every image the box needs exist and run on Arm 64-bit?

### 1.1 Image by image

| Image | What it is | Arm 64-bit? | Evidence |
| --- | --- | --- | --- |
| `trialbox-py` (console, orchestrator, gateway, compiler, adapter, lake, mail, audit writer, doc parser, stub model, the stub embedder) | built from `python:3.12-slim`, pinned by multi-arch index; pip with `--only-binary=:all:` from the hashed lock | yes: the base has `arm64/v8`; all 33 locked packages with native code have a glibc aarch64 CPython 3.12 (or abi3) wheel, and every such wheel's hash is in the pip lock | [read `deploy/docker/python.Dockerfile:2-8,24-27`]; [measured: `base-arches.txt`, `arm-wheels.txt`] |
| `trialbox-embed` (the real embedder, BGE-M3 on CPU) | `trialbox-py` + `torch==2.15.0+cpu` from the publisher's CPU index | yes: `torch-2.15.0+cpu-cp312-cp312-manylinux_2_28_aarch64.whl` is in the lock; not needed in stub mode (the stub stack uses a hash embedder in `trialbox-py`) | [read `deploy/docker/embed.Dockerfile:1-30`; `deploy/requirements-embed.lock:864-867`; `deploy/docker-compose.test.yml:74-80`]; [measured: `arm-wheels.txt`] |
| `trialbox-jvm` (FHIR validator, CQL) | `trialbox-py` + a JRE copied from `eclipse-temurin:21.0.13_9-jre` | yes: the JRE image has `arm64/v8` | [read `deploy/docker/jvm.Dockerfile:4-13`]; [measured: `base-arches.txt`] |
| `trialbox-postgres` (the database) | `postgres:16-trixie` + pgvector, PGroonga, pgBackRest at held versions | yes: the lock records `linux/arm64` for the base and every package version "for both" | [read `deploy/images.lock:11-23`, its `checked.result`]; [measured: `base-arches.txt`] |
| `trialbox-backup` | Go build of restic from `golang:1.26.11-bookworm` | yes (`arm64/v8`); not in the stub stack | [read `deploy/docker/backup.Dockerfile:22-28`]; [measured: `base-arches.txt`] |
| HAPI FHIR store, Mailpit, GreenMail | third-party, pinned by multi-arch digest | yes, each has an arm64 manifest | [read `deploy/images.lock:90-138`]; [measured: `base-arches.txt`] |
| Builder container of the one-command start (no Maven on the host) | `maven:3.9.9-eclipse-temurin-17` (by tag, not digest) | yes (`arm64/v8`) | [read `deploy/poc.sh:212-213`]; [measured: `base-arches.txt`] |
| **vLLM, the model server** | `vllm/vllm-openai:v0.32.0` by index digest | **an arm64 image exists**, built for CUDA 13.0.2 with `TORCH_CUDA_ARCH_LIST=8.0 8.7 8.9 9.0 10.0 11.0 12.0` (no 8.6; an sm_80 binary runs on an sm_86 card); **needs driver R580+** | [read `deploy/images.lock:50-88`]; [measured: `vllm-image-config.txt`]; [source 4, 6] |

**CI today** [read `.github/workflows/trialbox-images.yml:1-9,75-77,111-126`]: for a merge train and master, the image
job builds `trialbox-py`, `-jvm`, `-postgres`, `-embed` and the demo **natively on an `ubuntu-24.04-arm` runner**,
starts the embed service in PRODUCTION, runs the two-device selftest in the arm64 image and scans everything. On
master `a4aa0be1` (2026-11-18) the arm64 leg passed every step [source: GitHub Actions run 44244890568, job
"images (ubuntu-24.04-arm, linux/arm64)", read through the API]. **What CI never does on Arm:** start the whole stack.
The compose and e2e nightlies run on `ubuntu-24.04` (x86-64) only [read `.github/workflows/trialbox-*.yml`, every
`runs-on`], and no workflow runs `deploy/poc.sh` at all [read: no match for `poc.sh` in the workflows].

**The stub stack's composition** [measured: `stub-config-summary.txt`, `docker compose config` of the start's own
files]: 15 services, six images (the three own images above, HAPI, Mailpit, GreenMail), **no platform pin and no GPU
reservation**, memory caps summing 45.5 GiB.

**One defect on the way** [read `deploy/poc.sh:202-218`; `deploy/docker-compose.yml:67-76`]: when the host has no
Maven, the start builds only `trialbox-py` and `trialbox-jvm` in its builder container, but the stack's `db` service
needs `trialbox-postgres:16-1`, which has no `build:` entry and exists on no registry. On such a host the start would
stop at `compose up` trying to pull it (not run here: no Docker daemon). Runbook 28 builds it by hand first; card
24-2 fixes the script.

### 1.2 The model server on Arm 64-bit with a discrete card

- **vLLM's own documentation** lists `latest-aarch64` and `v<version>-aarch64` image tags and says CUDA 13 images
  need "an R580 or newer driver"; a compatibility mode "supports R535 and R570 host drivers" but "only supports select
  professional and datacenter NVIDIA GPUs" [source 1].
- **The pinned release publishes both** a CUDA 13.0.2 build (the pin) and a CUDA 12.9.1 build (`v0.32.0-cu129`, index
  `sha256:bc0445da…`), each with an arm64 manifest; the CUDA 12.9 arm64 build is compiled for `8.0 8.7 8.9 9.0 10.0
  12.0` [measured: `vllm-tags.txt`, `vllm-image-config.txt`, `vllm-index-digests.txt`]. **The repository pins the
  CUDA 13 build only**, and says "Moving the vLLM entry is a model change: requalify first" [read
  `deploy/images.lock:4,88`].
- **Both images' `NVIDIA_REQUIRE_CUDA`** allows a 535-branch driver through the container toolkit (alternatives
  `brand=…,driver>=535,driver<536`), so the container would start; what then decides is the CUDA runtime inside
  [measured: `vllm-image-config.txt`]. The CUDA 13 image sets `VLLM_ENABLE_CUDA_COMPATIBILITY=0` [same].
- **CUDA 12.9 on driver 535**: NVIDIA's minor-version compatibility covers CUDA 12.x on drivers from 525, with
  limits (no PTX compilation on the older driver; some calls answer "requires newer driver") [source 5]. Whether vLLM
  0.32.0's CUDA 12.9 arm64 build runs on 535 and an A6000: **not verified**.
- **CUDA 13 on driver 535** through forward compatibility: NVIDIA lists it for data-centre GPUs, "select NGC Server
  Ready SKUs of RTX cards" and Jetson boards, with no list naming the A6000 or IGX [source 6]. **Not verified**; an
  unsupported card answers error 804.
- **The repository's host check agrees** [measured: `images-lock-host.txt`]: `tools.images_lock host` with this
  machine's facts (aarch64, 535.183.01, compute 8.6) gives `PASS` arm64 build, **`FAIL` driver below 580.65.06**,
  `PASS` compute 8.6; with a 580 driver all pass, on either architecture.

### 1.3 The GPU container toolkit and the driver on that platform

NVIDIA's IGX documentation: IGX-SW 1.1.1 (IGX OS 1.1.6, Ubuntu 22.04, BSP 36.4.5) ships the dGPU driver
"R535.TRD5, version 535.183.01" [source 2] — **exactly the owner's driver**, so his machine almost certainly runs IGX
OS 1.1.x [opinion]. IGX-SW LTS 2.0 for IGX Orin stays on R535 (535.183.06.04, CUDA 12.2 update 2) [source 3]; IGX-SW
2.0 with R580 is for IGX Thor [source 7]. The release pages give no way to upgrade the dGPU driver on Orin [source 2].
The IGX guide documents the NVIDIA container runtime and `nvidia-ctk` on the platform [source 8]; whether his install
has it is step 0's `docker info | grep -i runtime`. **So: the driver cannot be moved to 580 on this platform inside
NVIDIA's support** [opinion from sources 2, 3, 7]; a stock R580 Arm server driver over the IGX kernel was not checked
and is not recommended.

### 1.4 What the repository's Arm path (the Spark) proves, and what it does not

The `gb10` profile is the only Arm path: everything `linux/arm64`, the pinned image's arm64 manifest, the driver held
at 580.142, the pair at 0.30 and 0.15 of 128 GB unified memory [read `deploy/docker-compose.gb10.yml:39-60,86-89`;
`deploy/gb10-profile.yaml:13-31`]. It is `status: unmeasured`: no Spark has run it [read
`deploy/gb10-profile.yaml:13-14`]. What it proves for the owner's machine: the compose files and own images carry no
x86-only part (also shown by CI's arm64 leg, 1.1). What it does not: anything about a discrete card on Arm, a 535
driver, an Ampere card, or 64 GB of host memory. **On master, `deploy/gpu_profile.sh` gives `gb10` to any aarch64 host**
[read master `deploy/gpu_profile.sh:34`]: measured on this machine's facts, `aarch64` + "NVIDIA RTX A6000" →
`gb10`, and `tools/tiers.py` then says "this card is tier medium" and suggests a gb10 rehearsal [measured:
`gpu-profile.txt`, `tiers.txt`]. Review 13 already noted the rule (its card 13-6, for the 64 GB Spark) [r13 line 598].

---

## 2. The card: the two pinned models on an A6000 with driver 535

**The pinned formats** [read `models/registry.yaml:116-171`; `docs/licences/register.csv:30-31`]: the judge is the
publisher's NVFP4 build of a 26B-A4B mixture-of-experts model (revision `a19cfe00`); the verifier a community AWQ
4-bit build of a 9B dense model (revision `e4d2d39c`). These are the only builds of the pair in the licence register.

**The judge's format on Ampere.** The publisher's model card names "NVIDIA Blackwell" as its microarchitecture, B200
as the test hardware, vLLM as the runtime, and the `nvfp4_experts_only` recipe (weights and activations of the expert
layers in NVFP4; the rest BF16) [source 9]. vLLM's quantisation page has no NVFP4 row; it marks "Marlin
(GPTQ/AWQ/FP8/FP4)" supported on Ampere, and says vLLM "by default falls back to a weight-only kernel (Marlin …) that
keeps the quantized weights but runs activations in 16-bit, so … W4A4 [runs] as W4A16"; `VLLM_STRICT_QUANT_SCHEME=1`
forbids that and may land on "NVFP4 emulation" or fail [source 10]. That page is the latest documentation, not
v0.32.0's. So on an A6000 the judge would run, if at all, as **W4A16 through Marlin's mixture-of-experts kernels:
unsupported by its publisher, different arithmetic from every measured run** [opinion]; review 19 drew the same
conclusion for Ada and Ampere head boxes and left it unverified [r19 lines 251-255, 703-704]. **The verifier's AWQ** is
supported on Ampere [source 10].

**Driver and engine.** As section 1.2: the pinned CUDA 13 build fails the repository's own driver check on 535
[measured]; the same release's CUDA 12.9 build is plausible on 535 but unpinned and untested.

**Memory on 48 GB** (review 19's method and stored figures [r19 lines 244-249]; arithmetic here):

| Item | MiB |
| --- | ---: |
| Card total (the owner's screen) | 49,140 |
| Judge, non-cache, inside its budget / outside it | 18,920 / 3,170 |
| Verifier, non-cache, inside / outside | 9,000 / 680 |
| Sum before any cache | 31,770 |
| Left for both caches (and for the desktop, if the card drives the screen) | 17,370 |
| Review 19's split: judge 0.57 (28,010; cache 9,090 ≈ 86k tokens), verifier 0.27 (13,268; cache 4,268) | 41,278 + 3,850 outside = 45,128 |
| Spare | 4,012 |
| **The `gb10` profile's 0.30 for the judge** (what master gives this machine) | 14,742: **below the judge's 18,920: it cannot load** |
| The `rtxpro6000` profile's 0.40 / 0.20 at 32k | judge cache 736, verifier 828; one 32k judge sequence needs about 3.4 GiB [r13 line 246], a verifier 8k one 0.35 GiB [r13 line 217]: **neither starts** |

So **both models resident at 32k fit only with a profile of their own** (review 19's 0.57 / 0.27), which does not
exist (10E-31) [read plan 10 `docs/plan/47-plan-10-2026-11-18.md:595`]. The stored figures were taken with
Blackwell's native FP4 kernels; Marlin's repacked weights and workspace on Ampere may differ [not verified].

**If the pinned judge cannot run here, the options** [opinion]:

| Option | What it needs | What it loses |
| --- | --- | --- |
| Another build of the same judge (BF16 or a 4-bit format Ampere computes natively) | a new licence-register row, a registry build, a weight manifest, a qualification and its own accuracy run; BF16 of a 26B model does not fit 48 GB beside the verifier [opinion: about 2 bytes a parameter] | every measured figure; weeks, not days |
| The verifier alone (`TB_SCREEN_JUDGE=single`-like operation) | one model on the card | a note can never exclude (D-89): review 19's option (a) [r19 line 298] |
| Stub mode (runbook 28) | nothing | every note answer; the lists show the product, not its accuracy |
| The stub with a cloud model (`TB_LLM_MODE=openrouter`, synthetic data only, DEV) | a paid key; synthetic text leaves the machine | the pinned pair; costs money (the owner's decision); not considered further here [read `deploy/poc.sh:5-6,130-132`] |

---

## 3. The host

- **The system.** Ubuntu 22.04.5 on aarch64 [owner]. The one-command start checks no OS version [read
  `deploy/poc.sh:52-54,72-108`]; the installer's host check only **warns** on anything but 24.04 ("D-408 names Ubuntu
  24.04 LTS") [read `deploy/check_host.sh:97-106`]; nothing refuses 22.04 on Arm. 22.04 is what IGX OS 1.1.x is
  built on [source 2], so this fits the driver's evidence that the machine runs IGX OS.
- **Memory.** The developer kit is sold with "64 GB 256-bit LPDDR5" and a "12-core Arm Cortex-A78AE v8.2" at up to
  1.971 GHz [source 11]; his `free -g` shows **53 GB** (the rest is presumably reserved by the module's firmware
  [opinion; not verified]) with 49 available and 26 GB of swap [owner].
- **Beside the model server.** Idle memory per service has never been measured anywhere [r13 line 466]; what was
  measured is each Python service's import, 66 to 148 MB [r13 line 464]. The caps are the evidence: the stub stack's
  caps sum to 45.5 GiB [measured: `stub-config-summary.txt`] and are ceilings, not reservations. The repository's own
  box planner, on **53 GiB**, gives the stub box exactly its default caps (44.2 GiB, 5.3 GiB kept for the system),
  **refuses the pair profile ("TrialBox needs at least 79 GiB with this GPU profile")** and even the one-model
  `default` profile ("at least 55 GiB") [measured: `memory-caps-53.txt`; the 64 GiB run for comparison:
  `memory-caps-64.txt`]. So: the stub box fits, with nothing to switch off beyond what is already off in stub mode
  (no model server, the hash embedder instead of the real one) [opinion; idle use not measured]; keep the desktop
  light while it runs (close the browser tabs and the conda tools you are not using) and watch step 11's figures.
  With any model, 53 GB does not fit by the repository's own rule, and lowering the caps below that rule's floor is
  exactly what the rule forbids (services never measured there) [read `tools/box/plan.py:330-365`].
- **CPU.** Twelve embedded-class Arm cores: enough for the services on synthetic data [opinion]; the image build in
  step 5 of runbook 28 is slower than on a desktop (perhaps 20 to 40 minutes) [opinion]; the real embedder's speed on
  Arm is unmeasured [r13 line 446] and not used in stub mode.
- **Disk: the first hard obstacle.** 91 GB free, 90 % used [owner]. The budget (the six third-party and base images
  are 1.1 GB compressed for arm64 [measured: `image-sizes-arm64.txt`]; everything else is [opinion], not measured):

  | Item | Stub path | Model path (if it ever runs) |
  | --- | ---: | ---: |
  | Third-party and base images, unpacked (about 2 to 3 × compressed) | 3 GB | 3 GB |
  | Own images (`trialbox-py`, `-jvm`, `-postgres`) and the build cache | 6 GB | 8 GB (with `-embed`) |
  | The checkout and the project's Python environment | 1 GB | 1 GB |
  | Database, lake, FHIR store and mail for the 600-patient synthetic hospital | 2 GB | 2 GB |
  | The engine image (10.3 GB compressed arm64 [measured: `vllm-tags.txt`], unpacked and layers in flight) | – | 25 GB |
  | The two models' weights and the template (about 48 GB of model cache [r23 §1.1]) | – | 50 GB |
  | Working space: a download verified in a folder of its own, then moved on the same disk (a move needs no copy) | – | 5 GB |
  | Free space the start itself demands in GPU mode [read `deploy/poc.sh:101-107`] | – | 30 GB |
  | **Total** | **about 12 GB** | **about 125 GB** |

  **91 GB is enough for the stub path, not for the model path.** A disk at 90 % is also near the point where Docker
  and the database misbehave when a write fills it [opinion]; free at least 30 GB more even for the stub path, and
  about 60 GB more, or add a second disk, before any model work. The developer kit lists "4x SATA 6 Gbps expansion
  ports" [source 11], so a second disk is possible in principle (which bays his unit has: not verified). Point
  Docker's data folder and `TB_MODELS_DIR` at it, not the root disk [opinion].

---

## 4. Verdict

**(b) Works only in a reduced mode next week: the product on the synthetic hospital with the stub model, on this
machine; the real models elsewhere.** [opinion, from sections 1 to 3]

- The reduced mode: console, accounts, the test mailbox, feasibility, structured criteria, the screened list, every
  screen; note criteria answered by the stub. Runbook 28. It has never been started on Arm by anyone: CI builds and
  scans the Arm images daily but never starts the stack there (1.1).
- The real pair on this machine is (c), **does not work next week**: driver 535 is fixed by the platform (1.3), the
  judge's format is not native on Ampere (2), no profile fits 48 GB of card memory (2), 53 GB of host memory is
  below the planner's 79 GB for the pair (3), and 91 GB of free disk is below the model path's about 125 GB (3).
- **The smallest alternatives for real models:** (1) an x86-64 machine with the 96 GB RTX PRO 6000, the one card
  measured, with review 23's page 27; (2) a rented cloud machine with that card, the route that has actually worked
  [r23 §1.2] (costs money: the owner's decision); (3) later, his A6000 in an x86-64 PC with Ubuntu 24.04 and a 580
  driver as the head box, after 10E-29's runs and 10E-31's profile. Nothing in (3) has ever run.

### 4.1 Cards

| Card | What | Size | File(s) | What proves it |
| --- | --- | --- | --- | --- |
| 24-1 | **Done in this branch:** an aarch64 host whose card is not a GB10 gets `arm64-dgpu` (UNMEASURED; refused by `install.sh` and the start in GPU mode; a stub box in `tools.box`); a GB10 and an unreadable name stay `gb10` | S | `deploy/gpu_profile.sh`, `deploy/install.sh:215`, `tests/unit/test_arm64_dgpu_profile.py` | the new tests; `gpu-profile-after.txt`, `tiers-after.txt` |
| 24-2 | The start's builder path also builds `trialbox-postgres` (and states the images it needs) | S | `deploy/poc.sh:202-218` | a unit test that the builder path names `db.Dockerfile`; a stub start on a host without Maven |
| 24-3 | The first stub start on Arm, on his machine: console, FEAS and SCREEN replies, `docker stats` after an idle hour (review 13's S-2 on Arm) | S (1 to 2 h of his time) | runbook 28 | his output files filed under `docs/plan/measurements/` |
| 24-4 | Engine probe on his machine, no model: does `v0.32.0` start CUDA with `VLLM_ENABLE_CUDA_COMPATIBILITY=1` on 535 and the A6000; does `v0.32.0-cu129` | S (about 1 h, two image pulls, 22 GB) | runbook 28, "Only when we ask" | the two printed lines |
| 24-5 | 10E-31 (head-box profile for 48 GB cards) widened to say which hosts it serves: x86-64 with R580 only, or also IGX with R535 and a CUDA 12.9 engine (a model change: requalify) | M (as planned) | `deploy/docker-compose.<head>.yml`, `tools/serving_config.py`, `deploy/images.lock` | 10E-29's records on the card; 24-4's answer |
| 24-6 | The judge on Ampere: one run of the canary and MedTxt ja at W4A16 against the stored control, before any head-box result counts | M | 10E-29's O-runs | the record; the difference to the Blackwell control |

### 4.2 What has never been run anywhere

The stack on any Arm machine; `deploy/poc.sh` in any mode on a host without Maven (24-2); the pinned engine on a 535
driver in compatibility mode; any vLLM build on an IGX; the judge on any Ampere card; the pair on 48 GB.

---

## 5. Questions for the owner (exact commands; runbook 28 step 0)

Answered already [owner]: `uname -m`, `lsb_release -a`, `free -g`, `df -h /` (see the top). Still to send:

```
docker --version
docker info | grep -i runtime
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
curl -sI https://hub.docker.com | head -1
```

(the last prints an `HTTP/` line when the machine reaches the internet). And in words: can a second disk go in (a
SATA or NVMe bay, and its size)? What on the 744 GB in use can be moved off? And: is this the machine that should go to the site in January (review 23 section 5 then needs an Arm and
Ampere column), and does the A6000 drive the desktop's screen?

## 6. Sources (opened 2026-11-18)

| # | What | Link |
| --- | --- | --- |
| 1 | vLLM GPU installation (aarch64 tags; CUDA 13 needs R580; compatibility mode for R535/R570, select GPUs only) | https://docs.vllm.ai/en/latest/getting_started/installation/gpu.html |
| 2 | IGX-SW 1.1.x production release (IGX OS 1.1.6, Ubuntu 22.04, dGPU driver 535.183.01, CUDA dGPU 12.6) | https://docs.nvidia.com/igx/user-guide/2.0/software-releases/software-release-1-1-pr.html |
| 3 | IGX-SW LTS 2.0 for IGX Orin (driver 535.183.06.04, CUDA 12.2 update 2) | https://docs.nvidia.com/igx/long-term-support/latest/software-releases/software-release-lts2-pr.html |
| 4 | Hopper compatibility guide (an sm_80 cubin runs on sm_86) | https://docs.nvidia.com/cuda/hopper-compatibility-guide/ |
| 5 | CUDA minor-version compatibility (12.x from driver 525; limits) | https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html |
| 6 | CUDA forward compatibility (data-centre GPUs, select NGC Server Ready RTX SKUs, Jetson; error 804) | https://docs.nvidia.com/deploy/cuda-compatibility/forward-compatibility.html |
| 7 | IGX-SW 2.0.1 ("GPU Driver: 580.00"; "IGX Orin is not supported in this release") | https://docs.nvidia.com/igx/user-guide/latest/software-releases/software-release-2-0-1-thor-notes-pr.html |
| 8 | IGX user guide 1.1, simultaneous iGPU and dGPU (`--runtime=nvidia`, `nvidia-ctk`, Docker 25+ and toolkit 1.14.5+ for CDI) | https://docs.nvidia.com/igx/user-guide/1.1/igpu-dgpu.html |
| 9 | The judge's model card (Blackwell, B200, vLLM, `nvfp4_experts_only`, Apache-2.0) | https://huggingface.co/nvidia/Gemma-4-26B-A4B-NVFP4 |
| 10 | vLLM quantisation (hardware table; weight-only fallback; `VLLM_STRICT_QUANT_SCHEME`) | https://docs.vllm.ai/en/latest/features/quantization/ |
| 11 | NVIDIA IGX product page (developer kit: 12-core A78AE, 64 GB LPDDR5, 500 GB NVMe, RTX A6000 or RTX 6000 Ada) | https://www.nvidia.com/en-us/edge-computing/products/igx/ |

Registry metadata (tags, digests, image configuration, base-image architectures) was read from Docker Hub's public
API on 2026-11-18 (section 9); CI's result from the repository's Actions API.

## 7. What this review did not verify

- Anything on the owner's machine beyond his four answers: Docker, the container runtime, internet, a second bay.
- The disk budget's own-image, data and unpacked sizes (estimates); the reason for 53 GB rather than 64 GB.
- That IGX OS is what runs (inferred from the driver version alone).
- The stub stack starting on Arm; the start without Maven failing at the database image (read, not run).
- vLLM 0.32.0 on driver 535 in either build; compatibility mode on an A6000; Marlin's NVFP4 MoE path in 0.32.0.
- Memory figures on Ampere; whether the card drives the desktop; the A6000's speed for TrialBox.
- A stock R580 driver on the IGX kernel (not tried, not recommended).

## 8. What this branch changed in code

`deploy/gpu_profile.sh`: `aarch64` + a card name without "GB10" now prints `arm64-dgpu` (UNMEASURED); `aarch64` + "GB10"
or an empty name stays `gb10`; B200 first as before; x86 unchanged. `deploy/install.sh:215`: refuses `arm64-dgpu` with
the reason. No measured profile, no pin, no record, no compose file changed. What production accepts only narrows: an
Arm host with a non-GB10 card could before reach a gb10 rehearsal; now it cannot. The start's GPU mode already refused
any word but `rtxpro6000` and `gb10` [read `deploy/poc.sh:79-83`]. Tests: `tests/unit/test_arm64_dgpu_profile.py`.

## 9. Commands run here

| Output file (`/var/tmp/trialbox-0/b26/`) | Command | Result |
| --- | --- | --- |
| `gpu-profile.txt` | `sh deploy/gpu_profile.sh <arch> "<name>"` on master | aarch64 + A6000 → `gb10`; x86 + A6000 → `default` |
| `gpu-profile-after.txt` | the same on this branch | aarch64 + A6000 → `arm64-dgpu`; GB10 and empty → `gb10` |
| `tiers.txt`, `tiers-after.txt` | `python3 tools/tiers.py check --tier large/medium --arch … --card "NVIDIA RTX A6000"` | before: "this card is tier medium"; after: "not one of the three measured boxes"; exit 3 |
| `images-lock-host.txt` | `python3 -m tools.images_lock host --arch {aarch64,x86_64} --driver {535.183.01,580.95.05} --compute-cap 8.6 --image <pin>` | 535: FAIL driver; 580: all PASS |
| `memory-caps-64.txt` | `tools.box.plan.memory_caps(64 and 61 GiB, stub / rtxpro6000 / default)` | stub fits (×1.23); pair refused: needs 80 GiB |
| `memory-caps-53.txt` | the same at 53 GiB (the owner's figure) | stub fits (×1.00); pair refused (79 GiB); one model refused (55 GiB) |
| `image-sizes-arm64.txt` | Docker Hub tag API, arm64 compressed sizes | HAPI 0.44, Maven 0.23, Postgres 0.16, GreenMail 0.11, JRE 0.11, Python 0.04, Mailpit 0.01 GB |
| `stub-config-summary.txt` | `docker compose … --profile stub --profile test config` (the start's files; a throwaway `deploy/.env` from the example, removed) | 15 services, 6 images, no platform pin, no GPU, caps 45.5 GiB |
| `arm-wheels.txt` | a script over `uv.lock` and the two pip locks | 33 native packages, all with aarch64 wheels and hashes |
| `base-arches.txt`, `vllm-tags.txt`, `vllm-image-config.txt`, `vllm-index-digests.txt` | Docker Hub registry API (metadata only) | the architectures, sizes and CUDA settings quoted above |
| `profile-tests.txt` | `pytest` on the profile, tier, plan and start tests | 73 passed |
