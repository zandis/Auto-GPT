# 29. An IGX Orin developer kit with an RTX A6000: do the real models run?

**Reader:** the box owner, at an IGX Orin developer kit (Arm 64-bit) with an RTX A6000 (48 GB) on driver 535, after
page 28 (the product with the stub model) has run. This page decides, in one sitting, whether the two real models
can run on this machine, and if they can, leaves a measured record. Why each step exists: root review 24
(`docs/reviews/2026-11-root/24-igx-orin-a6000-install.md`), cards 24-4 to 24-7.

**Status: never run anywhere.** Nobody has run any step of this page on any machine: the scripts were tested only
with stand-ins for Docker and the card. Expect a surprise or two, and send every output. Synthetic data only: no
patient record goes on this machine. Nothing here changes the NVIDIA driver; never install another driver on it.

## What we do not know yet

**Only the machine can tell** (nobody has run any of it, on this or any machine):

1. whether the model engine computes on this card with driver 535 at all, and in which form;
2. whether the judge's 4-bit format loads on this card (it was built for newer cards, and runs a slower path here);
3. how much card memory the judge needs on that path (every figure below is the 96 GB card's);
4. whether the judge gives the same answers on that path (the canary's 54 cases are the first comparison);
5. how much of the machine's 53 GiB the two model servers need, and whether 12 + 10 GiB is enough;
6. whether the card also drives your screen, and how much memory that takes;
7. whether the real embedder runs on this processor, and how fast;
8. whether the CUDA 12.9 build's tag and digest are still what the registry said on 2026-11-18.

Everything else on this page is arithmetic from that one 96 GB run, or the scripts' own logic, tested against
stand-ins for Docker and the card.

**What it decides.** Three questions, in this order:

1. Does the model engine compute on this card with driver 535 at all (step 2, about 1 hour, no model)?
2. Does the real embedder run beside the stub (step 4; independent of 1, worth doing either way)?
3. Do the pinned judge and verifier load and answer on this card, and within how much host memory (steps 6 and 7,
   only when 1 said yes)?

**What it does not do:** make this machine a supported box. A record from step 6 is the material for a later
change; until then `deploy/install.sh` and `deploy/poc.sh` refuse the 48 GB draft profile (`dgpu48`), whatever is
set.

**Nothing you send identifies the machine.** The files below hold the card's model, its memory, the driver, the
architecture and the results; the scripts leave out the host name, user name, serials, device and bus IDs, addresses
and any key. Look at each file before you send it (`cat <file>`); if you see something that names the machine or you,
remove it.

## Two limits to know first

**Host memory: even a run that works cannot become a box for this machine as things stand.** The draft profile caps
each model server at 32 GiB of host memory (the repository's floor for a model server), 64 GiB for the two. On this
machine's 53 GiB the box planner refuses that: it needs **at least 63.9 GiB** with every service at half its usual
memory, and 123.9 GiB with none shrunk. The developer kit's memory cannot be extended. So step 7 runs a second option,
`pair-32k-host53`: the same settings on the card, with the model servers capped at 12 and 10 GiB, the most a 53 GiB
machine can give them beside the rest of the box. What it costs: every other service would run at half its usual
memory cap (never measured there), and the planner would need a change to hold the model servers' caps instead of
shrinking them with the rest (a later card). If a model server cannot live within those caps, the measuring run says
"OUT OF HOST MEMORY", and the answer is that this machine cannot run the real models as a box.

**The card may also drive your screen.** The arithmetic below counts the whole 49,140 MiB for the models. If the A6000
also drives the desktop, the desktop's share comes off the spare (the models' fractions are of the whole card, and the
engine refuses to start when less is free). Check before step 6:

`nvidia-smi --query-gpu=display_active,memory.used --format=csv`

`Disabled` and a small number (under about 100 MiB): nothing to do. `Enabled`, or a few hundred MiB or more used
before anything runs: the measuring run takes it off its prediction and records it, but with under about 1,000 MiB
left spare the first option may not start. Then run step 6 without the desktop: from another computer over `ssh`, or
from a text console (Ctrl+Alt+F3), type `sudo systemctl isolate multi-user.target` (the desktop closes), run the step,
then `sudo systemctl isolate graphical.target` to get the desktop back.

## The page

| # | Step | Type | Time, disk | You should see | Then |
| --- | --- | --- | --- | --- | --- |
| 0 | The version | `cd ~/Auto-GPT/trialbox`; `git fetch`; `git checkout <the tag we send>`; `conda deactivate` until the prompt has no `(base)` | minutes | "HEAD is now at …"; `which python3` prints `/usr/bin/python3` | – |
| 1 | Free the disk (below) | `df -h /` | – | at least **35 GB** free for steps 2 to 4, at least **70 GB** for step 6 | less: free more first (below) |
| 2 | The engine probe | `python3 tools/engine_probe.py run --out ~/tb-engine-probe.json` | up to about 1 hour (one or two downloads of 10 to 12 GB, one at a time, progress shown; each removed after) | a table, a `verdict:` line and one `next:` line | send `~/tb-engine-probe.json`; do what the `next:` line says |
| 3 | Read it again any time | `python3 tools/engine_probe.py show ~/tb-engine-probe.json` | – | see "Reading the probe" below | – |
| 4 | Stub judge, real embedder | page 28, "Optional: the real embedder", rows E1 to E9 (E7 deletes the synthetic data once: read it first) | 30 to 60 minutes; 2.3 GB of weights, about 2 GB of image | at the end "TrialBox POC (stub model, model embedder)" | send `~/tb-embedder.txt` (row E9) only: the start's own output shows the admin password and your folder names |
| 5 | Only if the verdict is a form (not `none`, not `inconclusive`): the two models' weights | "The weights (step 5)" below | 1 to 3 hours (about 28 GB) | the two folders and the template file; step 6 checks them against the release before it downloads or starts anything | – |
| 6 | The same condition: the measuring run, first option | check the screen (above); `deploy/poc.sh down`; then `TB_UNMEASURED_DGPU48_MEASURING_RUN=1 python3 tools/dgpu48.py measure --option pair-32k --dry-run` (shows what it will do, starts nothing); then the same without `--dry-run` | 1 to 2 hours: the engine image download first (10 to 12 GB, about 25 GB on disk, progress shown), then 5 to 35 minutes of loading (a line a minute with the memory in use), a few minutes to hash the weights, 10 to 30 minutes of canary | an `outcome` line (below) | send the three files in `~/tb-dgpu48-pair-32k/` |
| 7 | If step 6 started: the 53 GiB question. If it did not: the next option | started: the same command with `--option pair-32k-host53`. Did not start: `--option pair-16k`, then `judge-alone`, then `verifier-alone`, stopping at the first that starts | about 1 hour each (the engine image is already there) | an `outcome` line | send each folder `~/tb-dgpu48-<option>/` |
| 8 | Give the disk back | `docker image rm $(python3 -c "import json; e=json.load(open('deploy/images.lock'))['third_party']['vllm']; print(e['image'] + '@' + e['digest'])")`; if the verdict was `cu129`, also `docker image rm $(python3 -c "import tools.engine_probe as p; print(p.CU129)")`; then `df -h /` | – | about 25 GB free again | then `deploy/poc.sh` for the stub box |

Every script stops cleanly on Ctrl-C: the probe removes its running check and the image it downloaded; the measuring
run stops the model servers and writes what it measured so far. The model servers of a measuring run have no restart
policy: they do not come back after a reboot.

## The weights (step 5)

The repository's weights command (`tools/fetch_weights.py`) fetches exactly the files the release pins, checks each
against its pinned size and sha256, and only then moves the folders into place; it resumes after a network error.
It names the pair by a profile: use `rtxpro6000`, whose folders and builds are the ones the measuring run uses (the
same weights serve every profile; the measuring run checks them against the pin again before it starts anything).
It needs no other tool than the host's `python3` with `python3-yaml` (page 28 step 3).

1. See what will come, without downloading: `python3 -m tools.fetch_weights --profile rtxpro6000 --dry-run`. It
   prints the models folder, the two folders (11 and 16 files, about 27.9 GB) and the template, the free disk, and
   whether the real run would go ahead. If it says the disk is short, free it (step 1) or point `TB_MODELS_DIR` at a
   larger disk.
2. Download: `python3 -m tools.fetch_weights --profile rtxpro6000` (1 to 3 hours). After a network error, run it
   again: it continues where it stopped. Exit 0 means every folder is the pinned build.
3. Check what is there at any time, without the network: `python3 -m tools.fetch_weights --profile rtxpro6000 --verify-only`.

If a download asks for a sign-in, the model's page needs its terms accepted with a (free) Hugging Face account; then
enter the token in your own Bash shell. Using `sudo VAR=value command` shows the value in the process list.

```bash
read -rs HF_TOKEN; export HF_TOKEN
sudo --preserve-env=HF_TOKEN python3 -m tools.fetch_weights --profile rtxpro6000
unset HF_TOKEN
```

## Freeing the disk (step 1)

Your root disk had 91 GB free of 879 GB (90 % used). This page needs, at its largest step (6): the engine image about
25 GB, the two models' weights about 28 GB, the real embedder about 4.5 GB with its image, and room to work: **about
70 GB free**, on top of what page 28's stub box uses (about 12 GB). Step 2 alone needs about 30 GB (one engine image
at a time) and checks it before it downloads anything.

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

## Reading the probe (step 2)

Before any download the probe checks that Docker answers, that you may use it, that Docker has the NVIDIA runtime
and that the disk has room. Then it tries the engine in up to four forms, each without a model, and asks it to see
the card, run a small calculation on it and load its compiled kernels. It stops at the first form that passes:

| Test | What it is |
| --- | --- |
| `pinned` | the engine image the release pins (`deploy/images.lock`), as it is: built for a newer driver (580) than yours |
| `pinned+compat` | the same image with the vendor's CUDA compatibility switch on |
| `pinned+libs` | the same image with its CUDA compatibility libraries put first by hand (the exact library path is recorded) |
| `cu129` | the same engine release built for CUDA 12.9, `vllm/vllm-openai:v0.32.0-cu129@sha256:bc0445dac61accbf1c3b17fbb524a71eee0b1b32f55ba45952095e3be8991c3f`: **not pinned**; tag and digest read from the registry on 2026-11-18, **to be verified on the machine** (the probe records the digests Docker reports) |

| Status | Meaning |
| --- | --- |
| `PASS` | the engine sees the card, a calculation runs on it, its compiled kernels load |
| `PARTIAL` | the card is seen but a calculation or the kernels fail |
| `DRIVER` | the CUDA inside the image refuses driver 535 |
| `NO-GPU`, `PULL-FAILED`, `DISK`, `ERROR`, `NOT-RUN` | no answer about the card: Docker gave no card, the download failed, too little disk, the check stopped, or it was not tried |
| `SKIPPED` | not needed: an earlier form passed |

**The verdict** is one of three, and the `next:` line under it is the one thing to do:

- **A form** (`pinned`, `pinned+compat`, `pinned+libs` or `cu129`): the engine runs in that form. Steps 5 to 7 use
  exactly that form; they read it from `~/tb-engine-probe.json`. `cu129` is not the pinned engine: a result with it is
  evidence for a later change of the engine (a model change: requalify first), not for this release.
- **`inconclusive`** (exit code 3): something on this machine stopped the probe before it reached the card (Docker,
  its NVIDIA runtime, the network, the disk). This says nothing about the card. The `next:` line gives the one command
  that fixes it; then run step 2 again.
- **`none`** (exit code 1): every form reached the card and none computes on it with driver 535. **Stop here** and
  send the file: the real models cannot run on this machine with this engine release. Step 4 (the real embedder) does
  not depend on it.

## The measuring run (steps 6 and 7)

`tools/dgpu48.py measure` starts only the two model servers (not the box), from the draft overlay
`deploy/docker-compose.dgpu48.yml`, with the option's settings and exactly the engine form the probe passed. It
downloads the engine image first, with its progress shown; records card memory and each server's host memory from the
moment they start loading (also when they fail); takes the serving record with the same tool that took the 96 GB
card's record; runs the pair canary (54 stored cases) when the judge is up; and stops the servers, also on a failure
or Ctrl-C. It refuses, before anything starts, without `TB_UNMEASURED_DGPU48_MEASURING_RUN=1`, on a card that is not
about 48 GB, while the box runs, when a weights folder is not the release's (it checks each against the pinned
manifest first, which takes a few minutes), or when the probe's verdict was not a form; and it downloads nothing
with less than 30 GB free.

The options, in the order to try them (`python3 tools/dgpu48.py arith` prints the arithmetic, from the 96 GB card's
figures; nobody knows yet how much more the judge needs on this card; "judge room" is its cache past one
full-length request):

| Option | What | Card memory used of 49,140 MiB (predicted) | Judge room | Gives up |
| --- | --- | --- | ---: | --- |
| `pair-32k` | both models resident at 32k | 45,128 MiB, 4,012 spare | 5,564 MiB | nothing of the product's rule |
| `pair-32k-host53` | the same, the model servers capped at 12 + 10 GiB of host memory | the same | 5,564 MiB | every other service at half its memory cap; needs a planner change |
| `pair-16k` | both at 16k; the judge keeps its share, the verifier's is smaller | 42,179 MiB, 6,961 spare | 7,327 MiB | protocol reading at 32k; the verifier's margin is small |
| `judge-alone` | the judge alone at 32k | 42,482 MiB, 6,658 spare | 16,866 MiB | a note answer never excludes (one model) |
| `verifier-alone` | the verifier alone (a check of engine and card with a model) | 20,336 MiB | – | the judge: not a way to run the product |

**The `outcome` line** says what happened, told apart by cause:

- "STARTED, RECORD TAKEN, CANARY PASSED": the option runs on this card. Send the three files.
- "STARTED, CANARY FAILED": the servers run but the judge's answers differ from the stored cases. Send the files:
  this is the Ampere question of review 24 (the judge's 4-bit format is not native on this card).
- "OUT OF CARD MEMORY": a model did not fit the card with this option. Send the files; then the next option.
- "OUT OF HOST MEMORY": a model server hit its host memory cap or the machine ran out. For `pair-32k-host53` this is
  the answer to the 53 GiB question. Send the files.
- "FAILED TO LOAD": a server stopped while loading; the end of its log is in the file. Send the files; then the next
  option.
- "DID NOT START IN TIME": still loading after 35 minutes with no error. Send the files; then the next option.
- "ENGINE IMAGE NOT DOWNLOADED" or "NOT ENOUGH DISK": the line says what to fix; then run the same command again.
- "INTERRUPTED": you pressed Ctrl-C; the servers were stopped and what was measured is in the file.
- "STARTED, RECORD INCOMPLETE", "STARTED AFTER A RESTART": send the files.

**What to send** from each `~/tb-dgpu48-<option>/`: `measure.<option>.json` (the summary: settings, engine form, what
the card held before, start time, memory peaks on the card and in the host, the engine's own cache figures, the
canary's counts), `serving_config.dgpu48.<option>.json` (the record: the same fields as the 96 GB card's, host name
and device ID withheld) and `canary.<option>.json`.

## What this page does not verify

Everything on it ran only against stand-ins. Not verified: that the probe's checks behave on this machine as on the
stand-ins; any engine form on driver 535; the CUDA 12.9 build's tag and digest (read once from the registry); the
judge's weight-only path on Ampere and its memory (the predicted figures are the 96 GB card's); the model servers'
host memory on a 53 GB machine; the canary's answers on this card; the real embedder on Arm. MedTxt ja (review 24's
card 24-6) is not in the measuring run: it needs its own data fetch and is a later step.
