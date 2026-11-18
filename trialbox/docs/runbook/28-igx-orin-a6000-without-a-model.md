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

**You need:** wired internet for the install (images and packages, perhaps 10 to 15 GB); about 40 GB free disk; two
to three hours, most of it waiting.

| # | Step | Type or click | You should see | If not |
| --- | --- | --- | --- | --- |
| 0 | Send us the machine's facts first | `uname -m`; `lsb_release -a`; `free -g`; `df -h /`; `nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv`; `docker --version`; `docker info \| grep -i runtime` | `aarch64`; Ubuntu 22.04; about 60 GB total memory; the A6000 and 535.183.01; a Docker version; a line naming `nvidia` | copy every line to us before going on; a "command not found" is an answer too |
| 1 | Leave conda | `conda deactivate` (repeat until the prompt no longer starts with `(base)`); `which python3` | `/usr/bin/python3` | a path under `conda` or `miniconda`: `conda deactivate` once more |
| 2 | Docker ready | `docker compose version`; `docker info` | `Docker Compose version v2…` or later; no error | no Docker: follow "Install Docker Engine on Ubuntu" on docs.docker.com, then `sudo usermod -aG docker $USER`, sign out and in |
| 3 | Base packages | `sudo apt update && sudo apt install -y git make curl python3-venv python3-yaml` | no "E:" line | send the "E:" line |
| 4 | The version | `git clone https://github.com/zandis/Auto-GPT.git`; `cd Auto-GPT/trialbox`; `git checkout <the tag we send>` | "HEAD is now at …" | – |
| 5 | Confirm the card's profile | `sh deploy/gpu_profile.sh` | `arm64-dgpu` (an older version prints `gb10`) | anything else: send it; either way do not use GPU mode |
| 6 | Build the database image (the start forgets it on a machine without Java build tools) | `docker build -f deploy/docker/db.Dockerfile -t trialbox-postgres:16-1 deploy/docker` | after 5 to 15 minutes, a line naming `trialbox-postgres:16-1` | send the last 30 lines |
| 7 | Start | `deploy/poc.sh` | "fetching fonts and JVM build inputs in a builder container"; image builds (perhaps 20 to 40 minutes on this processor); "starting the stack"; **the admin password, shown once: write it down**; "ingesting synthetic site A (600 patients)"; the addresses | copy the `poc:` line and the output of `deploy/poc.sh status` to us; running step 7 again is safe |
| 8 | Sign in | browser on this machine: `http://127.0.0.1:8090`, user `admin`; set up the second factor with a phone authenticator | the console's overview | lost password: `deploy/poc.sh reset`, then step 7 |
| 9 | Feasibility | console, "Test mailbox": subject `FEAS GZQO` | web mail `http://127.0.0.1:8025`: a reply with a PDF and an XLSX | no reply in 10 minutes: send `deploy/poc.sh status` |
| 10 | A screened list | "Test mailbox": `SCREEN GZQO version=1.0.0` | an encrypted workbook and a summary PDF; the password in a second mail | send the reply's text |
| 11 | Memory, after an idle hour | `docker stats --no-stream > ~/tb-stats.txt`; `free -g >> ~/tb-stats.txt` | a table of the services and their memory | send the file (it holds no password and no patient) |
| 12 | Stop | `deploy/poc.sh down` | the containers stop; data kept | – |

## Every day after

Start: `deploy/poc.sh` (it keeps the passwords and the data). Stop: `deploy/poc.sh down`. State and addresses:
`deploy/poc.sh status`. Start again from nothing: `deploy/poc.sh reset`.

## Only when we ask: the engine probe (no model)

Two checks that tell us whether the model engine can use the card at all on this driver. Each downloads one engine
image (about 10 to 12 GB) and loads no model. Run them only when we ask, and send both outputs.

1. The pinned engine with its compatibility libraries switched on:
   `docker run --rm --gpus all -e VLLM_ENABLE_CUDA_COMPATIBILITY=1 --entrypoint python3 vllm/vllm-openai:v0.32.0@sha256:befccf0e7e4089aa23926bb6f887a85c0d46c2a99e6de5c5ffdf5cb7957c5b34 -c "import vllm, torch; print(torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name(0))"`
2. The same release's CUDA 12.9 build (not the pinned one):
   `docker run --rm --gpus all --entrypoint python3 vllm/vllm-openai:v0.32.0-cu129@sha256:bc0445dac61accbf1c3b17fbb524a71eee0b1b32f55ba45952095e3be8991c3f -c "import vllm, torch; print(torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name(0))"`

Either may print `True` and the card's name, or an error about the driver; both answers are useful. Afterwards free
the disk with `docker image rm` and the image's name.
