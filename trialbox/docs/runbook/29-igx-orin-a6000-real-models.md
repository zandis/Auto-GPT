# 29. An IGX Orin developer kit with an RTX A6000: do the real models run?

**Reader:** the box owner, at an IGX Orin developer kit (Arm 64-bit) with an RTX A6000 (48 GB) on driver 535, after
page 28 (the product with the stub model) has run. This page decides, in one sitting, whether the two real models
can run on this machine, and if they can, leaves a measured record. Why each step exists: root review 24
(`docs/reviews/2026-11-root/24-igx-orin-a6000-install.md`), cards 24-4 to 24-7.

**Status: never run anywhere.** Nobody has run any step of this page on any machine: the scripts were tested only
with stand-ins for Docker and the card. Expect a surprise or two, and send every output. Synthetic data only: no
patient record goes on this machine. Nothing here changes the NVIDIA driver; never install another driver on it.

**What it decides.** Three questions, in this order, each stopping the page when the answer is no:

1. Does the model engine compute on this card with driver 535 at all (step 2, about 1 hour, no model)?
2. Does the real embedder run beside the stub (step 4; independent of 1, worth doing either way)?
3. Do the pinned judge and verifier load and answer on this card (step 6, only when 1 said yes)?

**What it does not do:** make this machine a supported box. A record from step 6 is the material for a later
change; until then `deploy/install.sh` and `deploy/poc.sh` refuse the 48 GB draft profile (`dgpu48`), whatever is
set.

**Nothing you send identifies the machine.** The files below hold the card's model, its memory, the driver, the
architecture and the results; the scripts leave out the host name, serials and device IDs, addresses, user names and
any key. Look at each file before you send it (`cat <file>`); if you see something that names the machine or you,
remove it.

## The page

| # | Step | Type | Time, disk | You should see | Then |
| --- | --- | --- | --- | --- | --- |
| 0 | The version | `cd ~/Auto-GPT/trialbox`; `git fetch`; `git checkout <the tag we send>`; `conda deactivate` until the prompt has no `(base)` | minutes | "HEAD is now at …"; `which python3` prints `/usr/bin/python3` | – |
| 1 | Free the disk (below) | `df -h /` | – | at least **35 GB** free for steps 2 to 4, at least **70 GB** for step 6 | less: free more first (below); step 2 refuses to download with under 30 GB free |
| 2 | The engine probe | `python3 tools/engine_probe.py run --out ~/tb-engine-probe.json` | about 1 hour (two downloads of 10 to 12 GB, one at a time; each removed after) | a table and a `verdict:` line (step 3) | send `~/tb-engine-probe.json` |
| 3 | Read the table | `python3 tools/engine_probe.py show ~/tb-engine-probe.json` | – | see "Reading the probe" below | the verdict says whether step 6 is worth the disk |
| 4 | Stub judge, real embedder | page 28, "Optional: the real embedder", rows E1 to E6 | 30 to 60 minutes; 2.3 GB of weights, about 2 GB of image | at the end "TrialBox POC (stub model, model embedder)" | send the lines from "embedder check" to the addresses, and `docker stats --no-stream` |
| 5 | Only if step 3's verdict is not `none`: the two models' weights | page 27, "The weights": the judge's and the verifier's folders and the template, into `deploy/models` | 1 to 3 hours (about 28 GB) | the two folders and the template file | – |
| 6 | Only if step 3's verdict is not `none`: the measuring run, first option | `deploy/poc.sh down`; then `TB_UNMEASURED_DGPU48_MEASURING_RUN=1 python3 tools/dgpu48.py measure --option pair-32k --dry-run` (shows what it will do, starts nothing); then the same without `--dry-run` | 1 to 2 hours: the engine image (10 to 12 GB download, about 25 GB on disk) the first time, 5 to 35 minutes to load, a few minutes to hash the weights, 10 to 30 minutes of canary | an `outcome` line (below) | send the three files in `~/tb-dgpu48-pair-32k/` |
| 7 | Only if step 6 said "DID NOT START": the next option | the same command with `--option pair-16k`, then `judge-alone`, then `verifier-alone`, stopping at the first that starts | about 1 hour each (the engine image is already there) | an `outcome` line | send each folder `~/tb-dgpu48-<option>/` |
| 8 | Give the disk back | `docker image rm $(python3 -c "import json; e=json.load(open('deploy/images.lock'))['third_party']['vllm']; print(e['image'] + '@' + e['digest'])")`; `df -h /` | – | the engine image's 25 GB free again | then `deploy/poc.sh` for the stub box |

## Freeing the disk (step 1)

Your root disk had 91 GB free of 879 GB (90 % used). This page needs, at its largest step (6): the engine image about
25 GB, the two models' weights about 28 GB, the real embedder about 4.5 GB with its image, and room to work: **about
70 GB free**, on top of what page 28's stub box uses (about 12 GB). Step 2 alone needs about 30 GB (one engine image
at a time).

Safe to remove (each command shows first, then removes):

- **Docker's leftovers:** `docker system df` shows them; `docker builder prune` (build cache: the next image build
  takes longer, nothing else changes); `docker image prune` (images no container uses and no tag names). Not
  `docker volume prune`: the volumes hold the stub box's data.
- **Python and conda caches:** `du -sh ~/.cache/* | sort -h | tail`; `rm -rf ~/.cache/pip`; `conda clean --all`;
  conda environments you no longer use: `conda env list`, then `conda env remove -n <name>`.
- **Package caches:** `sudo apt clean`.
- **Your own large files:** `du -xh ~ | sort -h | tail -20` shows the largest folders; move what you keep to another
  disk.

Do not remove: anything under `/opt/nvidia`, `/usr`, `/var/lib/docker` by hand (only through the `docker` commands
above), the checkout's `deploy/.env` (it holds the stub box's passwords), or `deploy/models` once it is filled. A
second disk is still the better answer for any model work (review 24, section 3): put Docker's folder and
`TB_MODELS_DIR` on it.

## Reading the probe (step 3)

The probe tries the engine four ways, each without a model, and asks it to see the card, run a small calculation on
it and load its compiled kernels:

| Test | What it is |
| --- | --- |
| `pinned` | the engine image the release pins (`deploy/images.lock`), as it is: built for a newer driver (580) than yours |
| `pinned+compat` | the same image with the vendor's CUDA compatibility switch on |
| `pinned+libs` | the same image with its CUDA compatibility libraries put first by hand |
| `cu129` | the same engine release built for CUDA 12.9, `vllm/vllm-openai:v0.32.0-cu129@sha256:bc0445dac61accbf1c3b17fbb524a71eee0b1b32f55ba45952095e3be8991c3f`: **not pinned**; tag and digest read from the registry on 2026-11-18, **to be verified on the machine** (the probe records the digests Docker reports) |

| Status | Meaning |
| --- | --- |
| `PASS` | the engine sees the card, a calculation runs on it, its compiled kernels load |
| `PARTIAL` | the card is seen but a calculation or the kernels fail: the detail column says which |
| `DRIVER` | the CUDA inside the image refuses driver 535 |
| `NO-GPU` | Docker gave the container no card: the NVIDIA container runtime is missing or not set up (`docker info \| grep -i runtime` should name `nvidia`) |
| `PULL-FAILED`, `DISK`, `ERROR` | no answer about the card: the download failed, too little disk, or the check stopped (the detail says why); fix and run step 2 again |

**The verdict** is the first `PASS` in the order of the first table:

- `pinned`, `pinned+compat` or `pinned+libs`: the pinned engine runs in that form. Step 6 uses it (it reads the
  verdict from `~/tb-engine-probe.json`) and records the form with the result.
- `cu129`: only the unpinned build runs. Step 6 can still run with it and says so in every file: a result is then
  evidence for a later change of the engine (a model change: requalify first), not for this release.
- `none`: no form of this engine release computes on this card with this driver. **Stop here** and send the file:
  the real models cannot run on this machine with this release, and step 6 would only spend disk. Step 4 (the real
  embedder) does not depend on it.

## The measuring run (steps 6 and 7)

`tools/dgpu48.py measure` starts only the two model servers (not the box), from the draft overlay
`deploy/docker-compose.dgpu48.yml`, with the option's settings; records card memory and each server's host memory at
their highest; takes the serving record with the same tool that took the 96 GB card's record; runs the pair canary
(54 stored cases) when the judge is up; and stops the servers. It refuses, before anything starts, without
`TB_UNMEASURED_DGPU48_MEASURING_RUN=1`, on a card that is not about 48 GB, while the box runs, without the weights,
or when the probe found no form of the engine.

The options, in the order to try them (`python3 tools/dgpu48.py arith` prints the arithmetic, from the 96 GB card's
figures; nobody knows yet how much more the judge needs on this card):

| Option | What | Card memory used of 49,140 MiB (predicted) | Gives up |
| --- | --- | --- | --- |
| `pair-32k` | both models resident at 32k | 45,128 MiB, 4,012 spare | nothing of the product's rule |
| `pair-16k` | both at 16k with more room | 40,214 MiB, 8,926 spare | protocol reading at 32k |
| `judge-alone` | the judge alone at 32k | 42,482 MiB, 6,658 spare | a note answer never excludes (one model) |
| `verifier-alone` | the verifier alone (a check of engine and card with a model) | 20,336 MiB | the judge: not a way to run the product |

**The `outcome` line:**

- "STARTED, RECORD TAKEN, CANARY PASSED": the option runs on this card. Send the three files; that record is what a
  later change turns into a profile.
- "STARTED, CANARY FAILED": the servers run but the judge's answers differ from the stored cases. Send the files:
  this is the Ampere question of review 24 (the judge's 4-bit format is not native on this card).
- "STARTED, RECORD INCOMPLETE" or "STARTED AFTER A RESTART": send the files.
- "DID NOT START": send the files, then step 7 with the next option.

**What to send** from each `~/tb-dgpu48-<option>/`: `measure.<option>.json` (the summary: settings, engine form,
start time, memory peaks, the engine's own cache figures, the canary's counts), `serving_config.dgpu48.<option>.json`
(the record: the same fields as the 96 GB card's, host name and device ID withheld) and `canary.<option>.json`.

## What this page does not verify

Everything on it ran only against stand-ins. Not verified: that the probe's checks behave on this machine as on the
stand-ins; any engine form on driver 535; the CUDA 12.9 build's tag and digest (read once from the registry); the
judge's weight-only path on Ampere and its memory (the predicted figures are the 96 GB card's); the model servers'
host memory on a 53 GB machine; the canary's answers on this card; the real embedder on Arm. MedTxt ja (review 24's
card 24-6) is not in the measuring run: it needs its own data fetch and is a later step.
