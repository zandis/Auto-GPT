# 28. An IGX Orin developer kit with an RTX A6000: the product without a model

**Reader:** the box owner, at an IGX Orin developer kit (Arm 64-bit) with an RTX A6000 (an other install form: the
one-command proof of concept in its no-model mode, on synthetic data). The reasons behind each step are in root
review 24 (`docs/reviews/2026-11-root/24-igx-orin-a6000-install.md`).

**Status: never followed on any Arm machine.** Write down anything that differs and send it back. Synthetic data only:
no patient record goes on this machine.

**What you get:** the console, accounts, the test mailbox, a feasibility reply and a screened list of the 600-patient
synthetic hospital, with the **stub model**: a fixed stand-in that answers by rule. The lists show the product
working, not what the real models would decide. **What you do not get:** the real models. This machine's driver (535,
fixed by NVIDIA's IGX OS) is older than the model engine needs (580), and no TrialBox profile fits this card yet
(review 24, section 4). Never start it with `TB_LLM_MODE=gpu`, and never install another NVIDIA driver on it.

**You need:** wired internet for the install (images and packages, perhaps 5 to 10 GB to download); about 12 GB of
disk for this page, **but your root disk is 90 % full (91 GB free): free at least 30 GB more first** (step 0b); two to
three hours, most of it waiting. Ubuntu 22.04 (yours) is accepted: nothing on this page checks the version. The real
models need about 100 GB free and more memory than this machine has (review 24, section 3).

| # | Step | Type or click | You should see | If not |
| --- | --- | --- | --- | --- |
| 0 | Send us the facts we still lack (you already sent `uname -m`, `lsb_release -a`, `free -g`, `df -h /`) | `docker --version`; `docker info \| grep -i runtime`; `nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv`; `python3 -c "import urllib.request; print(urllib.request.urlopen('https://hub.docker.com', timeout=10).status)"`; and in words: can a second disk go in? | a Docker version; a line naming `nvidia`; the A6000 and 535.183.01; `200` (the machine reaches the internet) | copy every line to us before going on; a "command not found" is an answer too |
| 0b | Make room on the disk | move or delete files you do not need (large downloads, old conda environments: `conda env list`, then `conda env remove -n <name>` for one you no longer use); then `df -h /` | at least 120 GB free (Avail): this page needs about 12 GB, and the disk should not stay near full | less: tell us; under about 30 GB free, stop here |
| 1 | Leave conda | `conda deactivate` (repeat until the prompt no longer starts with `(base)`); `which python3` | `/usr/bin/python3` | a path under `conda` or `miniconda`: `conda deactivate` once more |
| 2 | Docker ready | `docker compose version`; `docker info` | `Docker Compose version v2…` or later; no error | no Docker: follow "Install Docker Engine on Ubuntu" on docs.docker.com, then `sudo usermod -aG docker $USER`, sign out and in |
| 3 | Base packages | `sudo apt update && sudo apt install -y git make curl python3-venv python3-yaml` | no "E:" line | send the "E:" line |
| 4 | The version | `git clone https://github.com/zandis/Auto-GPT.git`; `cd Auto-GPT/trialbox`; `git checkout <the tag we send>` | "HEAD is now at …" | – |
| 5 | Confirm the card's profile | `sh deploy/gpu_profile.sh` | `arm64-dgpu` (an older version prints `gb10`) | anything else: send it; either way do not use GPU mode |
| 6 | Start (it builds every image it needs, the database's too, the first time) | `deploy/poc.sh` | "fetching fonts and JVM build inputs in a builder container"; image builds; "building the database image trialbox-postgres:16-1" (all builds together perhaps 30 to 60 minutes on this processor); "starting the stack"; **the admin password, shown once: write it down**; "ingesting synthetic site A (600 patients)"; the addresses | copy the `poc:` line and the output of `deploy/poc.sh status` to us; running step 6 again is safe (an image already built is not built again). If the build fails, see below the table |
| 7 | Sign in | browser on this machine: `http://127.0.0.1:8090`, user `admin`; set up the second factor with a phone authenticator | the console's overview | lost password: `docker compose --project-directory deploy -f deploy/docker-compose.yml -f deploy/docker-compose.test.yml -f deploy/docker-compose.poc.yml --profile stub --profile test exec console python -m console.cli reset-password admin` prints a new one, shown once (not `deploy/poc.sh reset`: that deletes all the data) |
| 8 | Feasibility | console, "Test mailbox": subject `FEAS GZQO` | web mail `http://127.0.0.1:8025`: a reply with a PDF and an XLSX | no reply in 10 minutes: send `deploy/poc.sh status` |
| 9 | A screened list | "Test mailbox": `SCREEN GZQO version=1.0.0` | an encrypted workbook and a summary PDF; the password in a second mail | send the reply's text |
| 10 | Memory, after an idle hour | `docker stats --no-stream > ~/tb-stats.txt`; `free -g >> ~/tb-stats.txt` | a table of the services and their memory | send the file (it holds no password and no patient) |
| 11 | Stop | `deploy/poc.sh down` | the containers stop; data kept | – |

**If the build fails** (step 6 stops with `poc: the database image trialbox-postgres:16-1 did not build`, or another
build's error): it is almost always a download that failed. Check the internet (the last command of step 0), run
`deploy/poc.sh` again (nothing was started, and what was built is kept), and if it fails a second time send us the
`poc:` line and the 30 lines above it.

## Every day after

Start: `deploy/poc.sh` (it keeps the passwords and the data). Stop: `deploy/poc.sh down`. State and addresses:
`deploy/poc.sh status`. Start again from nothing, deleting all data: `deploy/poc.sh reset`.

The builder container of step 6 runs as root and leaves root-owned files under `.cache` in the checkout. They do no
harm; to delete the checkout later, use `sudo rm -rf Auto-GPT`.

## Only when we ask: the engine probe (no model)

Two checks that tell us whether the model engine can use the card at all on this driver. Each downloads one engine
image (10 to 12 GB to download, about 25 GB on disk once unpacked) and loads no model. On your disk, run them one at
a time and remove the first image before pulling the second (two at once take about 50 GB). Run them only when we
ask, and send both outputs.

1. The pinned engine with its compatibility libraries switched on:
   `docker run --rm --gpus all -e VLLM_ENABLE_CUDA_COMPATIBILITY=1 --entrypoint python3 vllm/vllm-openai:v0.32.0@sha256:befccf0e7e4089aa23926bb6f887a85c0d46c2a99e6de5c5ffdf5cb7957c5b34 -c "import vllm, torch; print(torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name(0))"`
   Then free its space: `docker image rm vllm/vllm-openai@sha256:befccf0e7e4089aa23926bb6f887a85c0d46c2a99e6de5c5ffdf5cb7957c5b34`
   and check `df -h /`.
2. The same release's CUDA 12.9 build (not the pinned one):
   `docker run --rm --gpus all --entrypoint python3 vllm/vllm-openai:v0.32.0-cu129@sha256:bc0445dac61accbf1c3b17fbb524a71eee0b1b32f55ba45952095e3be8991c3f -c "import vllm, torch; print(torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name(0))"`

Either may print `True` and the card's name, or an error about the driver; both answers are useful. Afterwards free
the disk: `docker image rm vllm/vllm-openai@sha256:bc0445dac61accbf1c3b17fbb524a71eee0b1b32f55ba45952095e3be8991c3f`.
