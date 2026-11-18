# Root review 23: the first install on the owner's workstation, then a DGX Spark, and the January validation (lane J, B25, 2026-11-18)

**Reader:** the owner, who will sit at the workstation next week; then whoever cuts the version he installs. Plan 10
is run at the **essential** grade [owner]; this page asks for nothing beyond it.

**The owner's words (2026-11-18).** "In January, the box is going to do a 100-200 cases validation in [the first
site], so not rush to IT, but I want a version can install on my 6000 pro workstation, next week, and go on their
online use, and then go on to spark, and then to [the site], either use my 6000 pro box or spark, not sure." His
10 GB desktop card plays no part. The workstation's operating system is not known yet, so both Linux and Windows are
covered. The first site is "the first site (a general hospital in Japan)", about 500 to 600 beds (unconfirmed).

**What it goes under, not over:** review 18 (set-up as hospital IT meets it), 13 and 19 (tiers; only the 96 GB card
is measured), 08 (serving), 17 and 20 (sample sizes, gold, the retrospective run and shadow mode), 12 (SS-MIX2), 11
(legal footing), plan 10 final draft (`origin/agent/B18-plan-10`, cited **P10**). Nothing was installed, started,
downloaded or run in a cloud. Commands run here are listed in section 12; their outputs are in
`/var/tmp/trialbox-0/b25/`.

**Marks.** [read `file:line`]; [measured: output file under `/var/tmp/trialbox-0/b25/`]; [source: link, opened
2026-11-18]; [opinion]; [rNN] a review's own marked claim; [P10] plan 10's text. "Not verified" where not checked.

---

## 0. One page for the owner

**Next week is possible on Linux, with one route, from a checkout, not from a release bundle** [opinion]. Your card
class (RTX PRO 6000, 96 GB) is the only one TrialBox has ever measured: its serving record ships in the repository
and the tier check passes for it [measured: `tiers.txt`]. The fastest honest route is the one-command proof of
concept in GPU mode (`TB_LLM_MODE=gpu deploy/poc.sh`): it checks the card, pins the two models, starts the pair,
runs a 54-case canary and loads a 600-patient synthetic hospital [read `deploy/poc.sh:7-9,73-101,259-272`]. It has
**never been run on real hardware**; on the cloud card the same pieces were run by hand ("the direct route") and
worked [read `docs/plan/measurements/poc-1-evidence.md:31-38,227`]. So next week is also the first real run of it.

**What you must find out first (five minutes):** the card's exact name and memory. If it says "RTX PRO 6000" with
about 96 GB, everything below applies. If it says "RTX 6000 Ada" (48 GB), the box falls to a profile with no second
model, the one-command route refuses it, and the plan changes (section 1.3) [measured: `gpu-profile.txt`].

**If the workstation runs Windows:** the repository has a Windows installer, but it has never run on Windows [read
`docs/handover/P-0-windows-rehearsal.md:9`], it changes the whole computer (BitLocker, sleep, Windows Update), and
the model engine supports Windows only through WSL2 [source: vLLM GPU installation page]. **Recommendation:** put
Ubuntu 24.04 on a second internal disk and boot it for TrialBox (section 2.3).

**The step list:** 15 steps, about 30 commands, half a day plus downloads (section 3; the printable copy is
`docs/runbook/27-workstation-rtx-pro-6000.md`). Every step is "not verified" on your machine.

**What blocks "next week":** almost none of this week's defects matter for synthetic data on your own machine. Two
small things do: a known-green commit to tag (the red nightlies) and a way to fetch the model weights into exactly
the folders the pin accepts (section 4.1). **Before January** most of the data defects matter, because real charts
come in through the SS-MIX2 reader and the privacy guard (section 4.2).

**The Spark:** nothing has ever run on one; its profile is marked unmeasured [read `deploy/gb10-profile.yaml:13`].
It is light (1.2 kg) and quiet; your workstation is measured, has ECC memory and reads protocols fastest. **For
January:** take whichever passes the same canary and gives the same list on the same synthetic set; if the Spark has
not done that before the box must leave, take the workstation card (section 5).

**January (100 to 200 cases):** enough to find gross faults and to state an honest upper bound of roughly 6 to 10 %
on wrongly excluded eligible patients; not enough for the 5 % release bound (124 eligible patients with at most 2
misses) unless at least 124 of the cases are eligible (section 6). The design: a retrospective run on patients the
site already screened, counts only out, then shadow mode beside the coordinator (section 7).

---

## 1. What exists today for the 96 GB card

### 1.1 The pieces, traced

| Piece | What it does | Evidence |
| --- | --- | --- |
| Card detection | `deploy/gpu_profile.sh` prints `rtxpro6000` for any name containing "RTX PRO 6000" (Workstation and Max-Q alike); "RTX 6000 Ada" and "RTX PRO 5000" print `default`; any arm64 GPU host prints `gb10` | [read `deploy/gpu_profile.sh:32-38`]; [measured: `gpu-profile.txt`] |
| Tier rule | `tools/tiers.py check --tier large` passes on that card from `deploy/measured/serving_config.rtxpro6000.json`; `medium` (Spark) and `small` (5090) are refused: no record | [read `tools/tiers.py:1-24`]; [measured: `tiers.txt`, exit 0 / 3 / 3] |
| The measured record | taken on a cloud RTX PRO 6000 (server card, 96 GB, driver 580) by `deploy/gcp/gpu-pro6000-run.sh`; never on a workstation card | [read `deploy/measured/README.md`]; [read `docs/handover/gpu-vm-handover-2026-11-16.md:17-27`] |
| Serving settings | judge and verifier both resident, 32k context, 16 sequences, eager mode, 0.40 and 0.20 of the card, a 48 GB host-memory cap each, `HF_HUB_OFFLINE=1`, no usage statistics | [read `deploy/docker-compose.rtxpro6000.yml:38-39,60,68-71,76,84`] |
| Engine | the official vLLM v0.32.0 image, CUDA 13.0.2, lowest driver 580.65.06 | [read `deploy/images.lock:50-88`] |
| The two models | judge: a 26B mixture-of-experts open model in the publisher's NVFP4 build; verifier: a 9B dense open model, AWQ 4-bit; both Apache-2.0, both `verified: true` in the licence register; the embedder BGE-M3, MIT | [read `models/registry.yaml:116-171,587`]; [read `docs/licences/register.csv:30,31,33`] |
| Weights on the machine | the installer and the PoC **expect** them in `deploy/models` (or `TB_MODELS_DIR`) and pin them against a manifest hash; neither downloads them. A signed bundle can carry them (`make_bundle.sh --models`). On the cloud card a VM-only tool placed them | [read `deploy/install.sh:513-532`; `deploy/poc.sh:94-104`; `tools/make_bundle.sh:177-181`; `deploy/gcp/box_vm.py:573-581`] |
| Sizes | the model cache about 48 GB; the Spark page says about 55 GB of disk; the embedder 2.3 GB; one earlier validation bundle 29.6 GB | [read `gpu-vm-handover-2026-11-16.md` §1 "/models"; `docs/runbook/08-dgx-spark-end-to-end.md:17-18`; `docs/runbook/01-install-a-new-site.md:45-47`; `poc-1-evidence.md:34`] |
| Installer (`install.sh`) | bundle → signature → settings wizard → pins → serving record check → start → accounts → host check; default environment PRODUCTION, which demands an encrypted disk, a TLS name, a feed folder and a trial-office mailbox | [read `deploy/install.sh:1-60,570-589`; `01-install-a-new-site.md:95-99`] |
| PoC (`poc.sh`), GPU mode | Docker and GPU checks first, builds two images when missing (10 to 20 min), pins the pair, starts it as a TEST box, makes the administrator (password printed once), runs the canary, ingests 600 synthetic patients; console on `127.0.0.1:8090`, web mail on `:8025` | [read `deploy/poc.sh:7-9,73-104,136,219,259-272,140-150`] |
| First run and `doctor` | the PoC makes the administrator itself; the box form's browser wizard is not used by it. `doctor` on a bare checkout prints 39 checks, 7 FAIL, all of the "not configured here" kind | [read `deploy/poc.sh:259`]; [measured: `doctor-main.txt`] |
| Scripts | `bash -n` passes on install, poc, box-install, box-prepare, bootstrap, check_host, check_weights | [measured: `bash-n.txt`] |

### 1.2 What has and has not run on real hardware

| Route | Ever run on a real 96 GB card? | Evidence |
| --- | --- | --- |
| The direct route (the product's commands in the installer's order) | yes, on a cloud VM, 2026-11-15 and 16: pair up, canary, accuracy sets | [read `poc-1-evidence.md:24-38`] |
| `install.sh --answers` | tried twice on that VM, stopped (F9, F10); fixes merged later (D-833, D-835); not re-run | [read `poc-1-evidence.md:38,153`] |
| `TB_LLM_MODE=gpu deploy/poc.sh` | **no** (item B10 "not measured") | [read `gpu-vm-handover-2026-11-16.md:575`] |
| The box form, the Windows installer | no real machine | [r18, read]; [read `P-0-windows-rehearsal.md:9`] |

### 1.3 If the card is the 48 GB Ada card

Review 19 was told the owner's card is "48 GB-class" [r19 line 29]. On "RTX 6000 Ada" the profile is `default`, "the
base llm-service only": one model, no verifier [read `deploy/gpu_profile.sh:18`; measured: `gpu-profile.txt`], and
the PoC in GPU mode **refuses** it ("the one-command PoC serves the pair on rtxpro6000 or gb10") [read
`deploy/poc.sh:80-82`]. The fix is P10 card 10E-31 (the head-box profile for 48 GB cards, M), which waits for the
free runs 10E-29 on that card [P10]. Until then next week could show only the stub PoC (no real model) on that card
[opinion].

---

## 2. Prerequisites for the workstation

### 2.1 Linux (the supported host)

| Item | Requirement | Evidence |
| --- | --- | --- |
| Operating system | Ubuntu 24.04 LTS (desktop or server); the host check warns on anything else | [read `deploy/check_host.sh:97-105`] |
| GPU driver | R580 or newer, at least 580.65.06; for Blackwell cards the **open** kernel modules (the proprietary flavour does not support Blackwell) | [read `deploy/images.lock:84-85`]; [source: https://download.nvidia.com/XFree86/Linux-x86_64/595.84/README/kernel_open.html] |
| Containers | Docker Engine 27+ with the compose plugin; NVIDIA Container Toolkit, Docker's `nvidia` runtime configured | [read `01-install-a-new-site.md:95-99`; `deploy/poc.sh:77-79`] |
| Build inputs | the PoC builds two images; with no Maven/JDK on the host it fetches them in a builder container | [read `deploy/poc.sh:210-216`] |
| Disk | the PoC refuses under 30 GB free under Docker's root and the models folder; the real need is weights (~50 GB) + images + build cache + data: **at least 300 GB free, 500 GB advised** | [read `deploy/poc.sh:101`]; Windows installer's floor 500 GB [read `deploy/windows/box-install.ps1:58`]; the figure is [opinion] |
| Host memory | each model server is capped at 48 GB of host memory; the cloud card had a large host; **128 GB advised, 64 GB not verified** | [read `docker-compose.rtxpro6000.yml:60,76`]; [opinion] |
| Network at install | Docker Hub (engine, base images, the vLLM image), Ubuntu and NVIDIA package mirrors, GitHub (the checkout), Maven Central (JVM build), Hugging Face (weights): roughly 70 to 90 GB in all, mostly weights and the engine image | [read `01-install-a-new-site.md:110-112`]; the total is [opinion], not measured |
| Network at run time | none: model servers run with `HF_HUB_OFFLINE=1` and no usage statistics; ClinicalTrials.gov is offline by default; only the gateway may reach a model host | [read `docker-compose.rtxpro6000.yml:38-39`; `deploy/egress.py:1-15`]; [measured: `doctor-main.txt`, `gateway_only_model_reach`] |

**How "nothing leaves" is checked next week** [opinion]: the PoC does not install the nftables egress rules the
installer sets [read `deploy/install.sh:30-32` against `deploy/poc.sh`], so check it plainly: after step 11, pull the
network cable (or switch Wi-Fi off) and run the screen again (step 15). If the list comes back, nothing it needed was
outside. The egress rules are tested at the site's install, not now.

### 2.2 Windows: what the repository has

- **An installer for Windows exists**: `deploy/windows/box-install.ps1` puts Ubuntu 24.04 into WSL2, Docker Engine and
  the toolkit inside it, and runs the Linux box installer there [read `deploy/windows/box-install.ps1:1-40`]. It needs
  Windows 10 22H2 or 11 Pro/Workstations/Enterprise/Education, an offline media built with a signed bundle, and it
  turns on BitLocker with recovery keys, turns sleep and hibernation off and sets Windows Update's restart policy
  [read `box-install.ps1:11-30`; `P-0-BUILD-THE-MEDIA.md:145-160`]. **It has never run on Windows** [read
  `P-0-windows-rehearsal.md:9`].
- **The PoC on Windows** runs only the stub or a cloud model; GPU mode "is for Linux hosts … WSL2 users can also run
  deploy/poc.sh from their Ubuntu shell" [read `deploy/poc.ps1:8-9,49`].
- **The engine:** "vLLM does not support Windows natively … you can use the Windows Subsystem for Linux (WSL)"
  [source: https://docs.vllm.ai/en/latest/getting_started/installation/gpu.html].
- **CUDA on WSL2:** the Windows driver serves WSL ("you must not install any NVIDIA Linux GPU driver within WSL");
  the container toolkit works but "only `--gpus all` is supported"; pinned memory "availability … is limited";
  `nvidia-smi` "does not support all the queries yet" [source: https://docs.nvidia.com/cuda/wsl-user-guide/index.html].

### 2.3 Windows: the options

| Option | Effort | Risk | Verdict [opinion] |
| --- | --- | --- | --- |
| **A. Ubuntu 24.04 on a second internal disk, chosen at boot** | half a day: one SSD (1 TB or more), the Ubuntu installer, the BIOS boot menu; Windows untouched on its own disk | low: the same host as the measured cloud card; the main danger is installing onto the wrong disk (unplug or note the Windows disk first) | **recommended** |
| B. Same disk, dual boot (shrink Windows, install Ubuntu beside it) | half a day | medium: partitioning and BitLocker recovery prompts on the Windows side | only if no second disk fits |
| C. WSL2 + Ubuntu 24.04 + Docker Engine inside it + `poc.sh` in GPU mode | 2 to 3 hours | medium to high: never run; host memory split by `.wslconfig`; the CUDA-on-WSL limits above; the console is reachable only on the PC itself unless port rules are added; speed not measured | acceptable for a look, not for the January machine |
| D. The Windows installer (`box-install.ps1`) | a day, plus building its media with a signed bundle | high on a personal PC: BitLocker, power and update policy for the whole computer; first run ever | not next week |
| E. A virtual machine (Hyper-V, VirtualBox, VMware Workstation) | – | no GPU without pass-through, which these desktop products do not give a card like this [opinion; not verified per product] | no |

---

## 3. The step list (Linux, from a bare machine to a first screened list)

Every step is **not verified on the owner's machine**; steps 1 to 7 are standard vendor procedures, steps 8 to 15 are
TrialBox's and never ran end to end on real hardware (section 1.2). The printable copy, without this analysis, is
`docs/runbook/27-workstation-rtx-pro-6000.md`.

| # | Step | What you type or click | What you should see | If you see something else |
| --- | --- | --- | --- | --- |
| 1 | Identify the card (on any system) | `nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv` | "NVIDIA RTX PRO 6000 Blackwell …", about 97,000 MiB | "RTX 6000 Ada" or ~49,000 MiB: stop and send us the line (section 1.3) |
| 2 | Ubuntu 24.04 LTS on a disk with 500 GB free | the Ubuntu installer from a USB stick; then `lsb_release -rs` | `24.04` | another version: reinstall 24.04 |
| 3 | Base packages | `sudo apt update && sudo apt install -y git make curl python3-yaml python3-venv` | ends without "E:" lines | an "E:" line: send it |
| 4 | NVIDIA driver, open modules, then reboot | `sudo ubuntu-drivers list`, then `sudo apt install -y nvidia-driver-580-open` (or the newest `-open` listed), `sudo reboot`, then `nvidia-smi` | the card, driver 580.65 or newer | "No devices were found": the proprietary (non-open) driver is in; remove it and install the `-open` one |
| 5 | Docker Engine and compose | Docker's own Ubuntu steps (docs.docker.com, "Install Docker Engine on Ubuntu"), then `docker compose version` | v2.x | "permission denied": step 6 |
| 6 | Let your account use Docker | `sudo usermod -aG docker $USER`, sign out and in, `docker info` | no error | – |
| 7 | GPU in containers | NVIDIA Container Toolkit's apt steps; `sudo nvidia-ctk runtime configure --runtime=docker`; `sudo systemctl restart docker`; `docker run --rm --gpus all ubuntu:24.04 nvidia-smi` | the card's table printed from inside a container | "could not select device driver": the toolkit step did not take; repeat it |
| 8 | Get the version | `git clone https://github.com/zandis/Auto-GPT.git`, `cd Auto-GPT/trialbox`, `git checkout <the tag we send>` | "HEAD is now at …" | – |
| 9 | Check card and tier (reads only) | `sh deploy/gpu_profile.sh`, then `python3 tools/tiers.py check --tier large` | `rtxpro6000`, then `rtxpro6000 deploy/measured/serving_config.rtxpro6000.json` | `default`: section 1.3 |
| 10 | Put the model weights | the commands we send with the tag (section 4.1, W-1): three folders under `deploy/models`, each at the registry's revision, and the judge's chat template at `deploy/models/chat-templates/gemma-4-26b-a4b-it/chat_template.jinja` | ~50 GB downloaded; `sha256sum` of the template prints `ae53464b…` | a different hash, or `.bin`/`.py` files in a folder: stop; the pin will refuse them |
| 11 | Start the box | `TB_LLM_MODE=gpu deploy/poc.sh` | "ok GPU …", "ok GPU profile rtxpro6000", model folders ok, "building images" (10 to 20 min), "pinning", the stack healthy (up to 15 min), **the administrator's password, printed once**, "the pair canary" passing, "ingesting synthetic site A (600 patients)", then the URLs | any `poc:` line in red: copy it and `deploy/poc.sh status` to us; nothing is lost by running step 11 again |
| 12 | Sign in | open `http://127.0.0.1:8090`, user `admin`, the password from step 11; set up the second factor with an authenticator app on your phone | the console's overview | the password is lost: `deploy/poc.sh reset` and step 11 again (synthetic data only) |
| 13 | Feasibility | console, "Test mailbox" page: subject `FEAS GZQO` | in the web mail `http://127.0.0.1:8025`, a reply with a PDF and an XLSX within minutes | no reply in 10 min: `deploy/poc.sh status` to us |
| 14 | The first screened list | "Test mailbox": `SCREEN GZQO version=1.0.0` | an encrypted candidate workbook and a summary PDF; the workbook's password in a second mail | a refusal naming an approval: send it to us (not verified whether the shipped study needs one on this box) |
| 15 | Prove it runs offline | unplug the network, repeat step 14; plug back in; stop with `deploy/poc.sh down` | the same list again | no answer offline: send `deploy/poc.sh status` |

**Count:** 15 steps; about 30 typed commands (steps 2 to 11 and 15), one browser sign-in and two console messages
[counted here]. Time: half a day of attention, plus the downloads (about 70 to 90 GB) [opinion].

**On Windows with option C** steps 2 to 7 become: `wsl --install -d Ubuntu-24.04` in an administrator PowerShell;
the newest Windows NVIDIA driver for the card (no driver inside Ubuntu); a `%USERPROFILE%\.wslconfig` giving WSL2
at least 96 GB of memory (example in `deploy/windows/wslconfig.example`); systemd on in `/etc/wsl.conf`; Docker
Engine and the toolkit inside Ubuntu as in steps 5 to 7. Steps 8 to 15 are the same in the Ubuntu window [read
`box-install.ps1:17-33`; source: CUDA on WSL user guide]. Not verified anywhere.

---

## 4. What blocks "next week", and what blocks January

### 4.1 Must be in next week's version (synthetic data, his machine)

| # | Item | P10 id | Size | Why |
| --- | --- | --- | --- | --- |
| 1 | The compose nightly green | 9i-1 | S | the tag must name a commit known to start [P10 §6 row 6] |
| 2 | The e2e nightly green | 9i-2 | S | the same, for the screening path [P10 §6 row 7] |
| 3 | **W-1, new:** one command that fetches the three weight folders and the template at the registry's revisions into the exact folder shape the pin's manifest accepts, checking hashes | none in P10 | S | nothing in the repository fetches weights for a workstation (section 1.1); a Hugging Face download into a folder may add files the manifest does not expect (not verified) |
| 4 | **W-2, new:** the tag, and one person who did not write it following runbook 27 once on a GPU host (the B10 item) | none in P10 (a small form of 10K-17) | S | `poc.sh` in GPU mode never ran on real hardware (section 1.2) |
| 5 | Only if the card is the 48 GB Ada | 10E-31 | M | otherwise no verifier, and the PoC refuses the card |

**Not needed next week** [opinion]: the matching-engine defects (10A-1, 10A-2) change verdicts but not whether the
box installs; the SS-MIX2 faults (10B-1 to 10B-5) and the Japanese identifiers (10C-1) touch only real Japanese
data; the wizard's foreign defaults (10K-1) are not on the PoC route; certification, the EDC and the O and R cards.

**What "a version" should mean next week** [opinion]: **a git tag on a master commit with both nightlies green**,
installed by `poc.sh` from a checkout, plus W-1's weights. Not a release bundle: `make release-bundle` runs the
release gates and signs with the vendor key [read `Makefile:638-639`; `01-install-a-new-site.md:86-90`], the bundle
path has never completed on real hardware, and its PRODUCTION install asks for an encrypted disk, a TLS name, a
feed folder and a trial-office mailbox that a personal workstation does not have [read `install.sh:570-589`;
`01-install-a-new-site.md:95-120`]. The **signed bundle is the right form for the machine that goes to the site**,
because the site box must install offline from verified files.

### 4.2 Must be in before January (real charts, counts only)

| Item | P10 id | Size | Why |
| --- | --- | --- | --- |
| Negated inclusions held, never run as presence | 10A-1 | S | a patient never treated would be excluded [r15] |
| Mixed inclusions keep their note question | 10A-2 | S | the same defect family |
| The guard masks Japanese identifiers (katakana names, insurance numbers) | 10C-1 | M | F3; nothing with an identifier may reach a model unmasked [r11] |
| SS-MIX2: the exporter to the specification (the test source) | 10B-1 | L | the reader is tested only against TrialBox's own exporter [P10] |
| SS-MIX2: visits by the specification's key | 10B-2 | S | three visits on three days read as one [r12] |
| SS-MIX2: diagnoses, doses, extended storage | 10B-3, 10B-4, 10B-5 | M, M, M | the four faults of review 12 (with 10B-2) |
| The site profile and its questionnaire form | 10B-6, 10B-19 | L, S | 10B-4 and 10B-5 wait for it |
| Japan defaults and SS-MIX2 in the wizard | 10K-1, 10K-16 | S, S | a Japanese box otherwise gets another country's report language and retention |
| The ladder report beside every figure | 10A-3 | M | each miss must be traced to a rung |
| The site's protocol, the enrolment-log run kit, the shadow mode | 10G-24, 10G-36, 10A-19 | M, M, M | section 7 |
| Pre-consent lists only for delegation-log staff | 10C-3 | S | F5 |
| The January machine's record and a timed backup and restore | 10E-1, 10E-15 (+ Spark run C-1 if the Spark goes) | M, S | section 5 |

The two lists hold 4 + 1 conditional items and 19 cards; none is an O or R card.

---

## 5. Then the Spark

**What the repository has** [read]: the `gb10` profile, the pair resident at 16k context, 8 sequences, 0.30 and 0.15
of unified memory, a host-memory cap per service, the driver held at 580.142 because later 580.x builds broke the
engine on that chip; `status: unmeasured`, every measured field null [read `deploy/gb10-profile.yaml:1-35`;
`docs/runbook/08-dgx-spark-end-to-end.md:16-21`]. The engine image has an arm64 build "for CUDA 13 and sm_120, which
runs on the GB10's sm_121 … to be confirmed on a Spark" [r13, read `docker-compose.gb10.yml:46-49`]. The judge's
NVFP4 build on that chip is therefore unconfirmed. `install.sh --tier medium` refuses it today [measured: `tiers.txt`];
`poc.sh` accepts `gb10` [read `deploy/poc.sh:80-82`].

**What he does differently** [read; opinion]: the Spark comes with DGX OS (Ubuntu-based); check its driver against
580.142 before anything else; images are built on the Spark itself (arm64) by the same step 11; weights are the same
files; the record is captured after the first start with `tools/serving_config.py capture … --out
deploy/site/serving_config.gb10.json` [read `01-install-a-new-site.md:20-23`].

**Measure on the borrowed or bought unit first** (review 13's run C-1, about 2 days, US$0 on a loan [r13]): the
canary passes; the same SCREEN on the same synthetic hospital gives **the same list** as the workstation; the
serving record captured; memory peaks under the caps; first-load hours for 600 synthetic patients; the embedder's
speed on its Arm CPU; one Japanese protocol compiled at 16k.

**Risks** [opinion]: the NVFP4 judge on sm_121 may not load (then the Spark cannot run the pair at all); the held
driver may conflict with DGX OS updates; 16k context may truncate long Japanese protocol parts (the workstation has
32k); 273 GB/s memory makes it roughly 5 to 6 times slower than the 96 GB card [r13 table §0]; no second unit to swap.

**The January machine, plainly**

| | Workstation with the 96 GB card | DGX Spark |
| --- | --- | --- |
| Measured for TrialBox | yes (cloud card of the same chip) | no |
| Capacity, 600 beds, 3 to 5 studies | far more than needed: 0.5 h a night at 15 studies [r13] | enough: 2.8 h a night at 15 studies, estimated [r13] |
| For a 100 to 200 case validation | either is ample [opinion] | |
| Protocol reading | 32k context, under a minute | 16k, 1 to 2 minutes [r13] |
| Memory errors | ECC on the card [source: nvidia.com RTX PRO 6000 page] | not stated |
| Power | card 600 W (Max-Q 300 W) [source]; a whole tower near 1,000 W or more [opinion] | 240 W supply [source: nvidia.com DGX Spark page] |
| Noise, size, weight | a tower, audible under load, 15 to 25 kg [opinion] | 150 × 150 × 50.5 mm, 1.2 kg [source] |
| Carrying to Japan | checked or shipped freight; Japan's 100 V wall circuit (15 A) is near the limit of a 1,000 W+ tower under full load [opinion; not verified for his supply] | hand luggage; its supply's input range not verified |
| Customs | a computer with **no data on it**, carried as one's own equipment: no declaration expected for temporary use [not verified]; carry the purchase invoice | the same |
| Support | one known machine; the owner's own | one unit, no spare; NVIDIA's support through the reseller [not verified] |

**Recommendation** [opinion]: decide by one test, not by preference: if the Spark passes the C-1 list (same list,
canary, record) before the January box must be packed, take the Spark (portable, quiet, low power); otherwise take
the workstation card. Either way it goes as a vendor-prepared box from a signed bundle (P10 10K-22 in its lean form),
with nothing on its disk but the release and synthetic test data.

---

## 6. What 100 to 200 cases can and cannot show

**A case** = one patient screened against one study, with the reference being **that study's coordinator's or
investigator's own recorded decision** (eligible or enrolled; or screen-failed, with the failing criterion). Two
studies screening the same patient are two cases. Only cases where the reference says eligible count for "wrongly
excluded" [r17; opinion].

**Wrongly excluded eligible patients**, exact one-sided 95 % upper bound (Clopper-Pearson) [measured:
`binom.txt`; script `b25binom.py`; it reproduces review 17's 59 / 93 / 124]:

| Eligible cases n | 0 misses | 1 miss | 2 misses |
| ---: | ---: | ---: | ---: |
| 30 | 9.5 % | 14.9 % | 19.5 % |
| 50 | 5.8 % | 9.1 % | 12.1 % |
| 100 | 3.0 % | 4.7 % | 6.2 % |
| 150 | 2.0 % | 3.1 % | 4.1 % |
| 200 | 1.5 % | 2.3 % | 3.1 % |

**Recall of coordinator-found patients** (shadow mode), one-sided 95 % lower bound with 0 / 1 / 2 missed: n = 30:
90.5 / 85.1 / 80.5 %; 50: 94.2 / 90.9 / 87.9 %; 100: 97.0 / 95.3 / 93.8 % [measured: `binom.txt`].

**Criterion-level agreement** (k patient-criterion cells, clustered within patients; design effect 1.45 as review 17
used) [measured: `binom.txt`]: with k = 300 cells and 90 % observed, the 95 % interval is 84.8 to 93.6 %; at 600
cells 86.8 to 92.8 %; at 1,000 cells 87.5 to 92.1 %. 150 cases of about 6 criteria each give about 900 cells.

**Coverage** (the share of cells the box decides, the rest go to a person): with 150 cases and 30 % observed, 22.8 to
38.0 %; with 50 %, 41.7 to 58.3 % [measured: `binom.txt`, patient level; cells are tighter].

**What it cannot show** [opinion]: the 5 % release bound unless at least 124 cases are eligible with at most 2
misses (if only enrolled patients are counted, they are the easy eligible ones [r20]); the 2 % bound (313 eligible
[r17]); rates per criterion kind or per rare criterion; anything about studies, departments or hospitals not in the
run; speed or capacity of the site box; "accuracy at Japanese hospitals".

## 7. The simplest honest design

**Part 1, retrospective** [r20 G4; opinion]: 2 to 3 studies the site screened in the last few years or is screening
now. The site's coordinator lists, from the screening logs, each screened patient's chart number, the screening
date and the decision; the box screens each patient **as of that date**; the comparison is counts only. With 100 to
200 cases, perhaps 40 to 120 are eligible (depends on the studies; [opinion]).
**Part 2, shadow** [r17 §3.3; P10 10A-19]: for new candidates of the same studies, the coordinator screens as usual
and fixes the list first; then the box's list is opened beside it; every coordinator-found patient the box excluded
is a miss and is traced to a rung.

**Who does what, and hours** [r20 line 402; opinion]: the coordinator: the log extract (about 4 to 6 h) and the miss
reads (about 15 min each, perhaps 10: 2.5 h); in shadow about 1 h a week. The trial office (治験事務局): the
submission, which this page drafts. Hospital IT: a read-only copy of the SS-MIX2 storage for the box and a place to
put it (about half a day). The investigator: decides any disputed case.

**What is recorded** [opinion]: per case, the box's verdict and rung, the reference decision, agree or not; per
miss, the rung and cause; the coordinator's minutes. **Every chart read stays in the hospital; only counts and
reason codes leave**, by the counts-only records of 10G-36 and 10A-19 [P10]. The box sits on the site's network,
with no route out.

**Legal footing** [r11]: the hospital's posted purposes of use (利用目的) must cover "searching records for trial and
research candidates"; the site adds one line to its 院内掲示 and website (review 11's text: 治験・臨床研究への参加を
ご検討いただける方を探すための診療記録の確認); for the retrospective part, which is research on existing records,
the ethics guideline's notice and opt-out route as revised from 2026-12-01 applies [r11]. **The site's trial office
and ethics committee decide**; no outside reader was engaged, by the owner's ruling [owner].

**The pass/fail rule, stated before the run** [opinion; arithmetic from section 6]:
1. Wrongly excluded eligible cases: pass if 0 misses at 30 to 49 eligible, at most 1 at 50 to 99, at most 2 at 100
   or more (upper bound at most 9.5 %, 9.1 % and 6.2 %). The bound is reported with n and gold kind, never pooled.
2. Shadow: every coordinator-found patient the box excluded is traced; pass if recall's lower bound is at least 90 %.
3. Zero lines of chart text in anything that left the hospital (the counts-only record's own check).
A fail is not a stop: each miss becomes a card, and the run is repeated on the fixed version.

### 7.1 Protocol outline for the site's trial office (one page)

| Section | Content |
| --- | --- |
| 1. Purpose (目的) | To measure, on the site's own records, how often a candidate-finding aid wrongly excludes patients the study team found eligible, and how much of the screening it can decide |
| 2. Design (研究デザイン) | Retrospective comparison on past screening logs, then prospective shadow comparison; no change to care or to study conduct; the aid's list is not used for recruitment during the run |
| 3. Cases (対象) | 100 to 200 patient–study pairs from 2 to 3 named studies; reference = the study team's recorded decision |
| 4. Procedure (方法) | The aid runs inside the hospital on a copy of the SS-MIX2 storage; the coordinator compares lists after fixing her own; disputed cases go to the investigator |
| 5. Outcomes (評価項目) | Primary: wrongly excluded eligible cases with the 95 % upper bound. Secondary: criterion agreement, share decided, coordinator minutes |
| 6. Pass rule (判定基準) | As above, fixed before the first case |
| 7. Personal information (個人情報の取扱い) | No record, text or identifier leaves the hospital; only counts and reason codes; the box has no outward network route; data deleted at the end |
| 8. Ethics and notice (倫理的配慮) | The 利用目的 line posted; opt-out notice for the retrospective part as the ethics committee requires; the trial office decides |
| 9. Roles (実施体制) | Investigator, coordinator, trial office, hospital IT, the vendor (no access to records) |
| 10. Records and report (記録と報告) | A counts-only report to the trial office and the vendor; misses with their causes |

## 8. What must be true of the product before that run, in order

| Order | Cards | Size | Waits for |
| --- | --- | --- | --- |
| 1 | 9i-1, 9i-2 (green nightlies) | S, S | – |
| 2 | 10A-1, 10A-2 (the matching defects) | S, S | – |
| 3 | 10C-1 (Japanese identifiers in the guard) | M | – |
| 4 | 10B-2, then 10B-1 (visit key; the exporter to the specification) | S, L | decision 71 for 10B-2 [P10] |
| 5 | 10B-6 + 10B-19 (site profile, questionnaire form) | L, S | – |
| 6 | 10B-3, 10B-4, 10B-5 (diagnoses, doses, extended storage) | M, M, M | 10B-1, 10B-6 |
| 7 | 10K-1 + 10K-16 (Japan defaults; SS-MIX2 counts in the wizard) | S, S | 10B-1, 10B-2, 10B-19 |
| 8 | 10A-3 (the ladder report) | M | – |
| 9 | 10G-24 + 10G-36 + 10C-3 (protocol, run kit, list access) | M, M, S | the site's agreement |
| 10 | 10A-19 (shadow mode), with 10E-1 and 10E-15 for the chosen machine | M, M, S | 10A-3; section 5's test |

At the site, 10B-21 (counts against the hospital's own) runs first, before any case is scored [P10].

---

## 9. Owner decisions (four)

| # | Decision | Recommendation |
| --- | --- | --- |
| 1 | Next week's "version": a tag on a green master commit installed by `poc.sh` from a checkout (not a signed bundle) | **Yes**; the bundle is for the site box |
| 2 | If the workstation runs Windows: a second disk with Ubuntu 24.04 | **Yes**; WSL2 only for a quick look |
| 3 | The January machine is chosen by section 5's test (Spark if it gives the same list in time, else the workstation card); this reopens decision 32 (a 32 GB card for the first site) for the validation only | **Yes** |
| 4 | January's pass rule is section 7's lean rule (bound reported, at most 9.5 % at the low end), not criterion 1's 5 % gate | **Yes**; the 5 % bound is stated only if 124 eligible cases are reached |

## 10. What the owner must tell us

1. The card line from step 1; the workstation's operating system and version; free disk and on which drive; host
   memory; whether it has wired internet (and its speed); what "go on their online use" means: reaching the console
   from other computers, or the site's staff using it remotely (the PoC binds the console to the machine itself
   [read `deploy/poc.sh:141`]; remote use needs a TLS proxy and a VPN [read `docs/runbook/09-proof-of-concept-with-docker.md`]).
2. Which machine goes to Japan, or whether a Spark can be borrowed before then.
3. The 2 to 3 studies for January, and from the site, as counts only: patients screened and enrolled per study and
   whether the screening logs carry the screening date [r20 §9].

## 11. What this document did not verify

- Any step on the owner's machine; `poc.sh` in GPU mode on any real card; the installer after its F9 to F11 fixes.
- Whether a Hugging Face download reproduces the registry's manifest hashes folder for folder (W-1's reason).
- The host memory TrialBox needs on the workstation; the disk and download totals (estimates, not measured).
- Whether the shipped study GZQO screens on a fresh TEST box without an approval step.
- Ubuntu's driver package names on the day; Docker Desktop's licence terms (not used here).
- Anything on a Spark; the NVFP4 judge on its chip; its power supply's input range; customs rules for a carried computer.
- The site's bed count, studies, screening-log contents and ethics route.
- Japanese wording of the protocol headings beyond a plain reading (no clinician reader checked them).

## 12. Commands run here

| Output file (`/var/tmp/trialbox-0/b25/`) | Command | Result |
| --- | --- | --- |
| `bash-n.txt` | `bash -n` on seven deploy scripts | all ok |
| `install-help.txt` | `bash deploy/install.sh --help` | usage printed, exit 0 |
| `gpu-profile.txt` | `sh deploy/gpu_profile.sh <arch> "<name>"` for five card names | PRO 6000 Workstation and Max-Q → `rtxpro6000`; RTX 6000 Ada, PRO 5000 → `default`; GB10 → `gb10` |
| `tiers.txt` | `python3 tools/tiers.py check --tier large/medium/small --arch … --card …` | exit 0 / 3 / 3 |
| `poc-gpu.txt` | `TB_LLM_MODE=gpu bash deploy/poc.sh` (no Docker daemon here) | stops at "Docker is not running", exit 1, nothing written but an ignored folder |
| `doctor-main.txt` | `python -m tools.trialbox doctor` in the main checkout | 39 checks, 7 FAIL (nothing configured) |
| `binom.txt` | `python -I b25binom.py` (exact binomial bounds by bisection) | the tables of section 6 |
