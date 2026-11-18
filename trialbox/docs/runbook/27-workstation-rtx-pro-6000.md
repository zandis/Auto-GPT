# 27. Installing on a workstation with an RTX PRO 6000-class card

**Reader:** the box owner, at his own workstation (an other install form: the one-command PoC with the real model
pair on synthetic data). The reasons behind each step are in root review 23
(`docs/reviews/2026-11-root/23-first-install-and-january-validation.md`).

**Status: not yet followed on a real workstation.** Every step below is written from the repository; write down
anything that differs and send it back. Synthetic data only: no patient record goes on this machine.

**You need:** Ubuntu 24.04 LTS (on Windows: a second internal disk with Ubuntu, chosen at boot, is the advised way);
500 GB free disk; 128 GB of memory advised; wired internet for the install (about 70 to 90 GB to download); the
version tag we send you; half a day.

| # | Step | Type or click | You should see | If not |
| --- | --- | --- | --- | --- |
| 1 | Identify the card | `nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv` | "NVIDIA RTX PRO 6000 Blackwell …", about 97,000 MiB | "RTX 6000 Ada" or about 49,000 MiB: stop and send the line |
| 2 | Ubuntu 24.04 | install from a USB stick onto the disk with 500 GB free; then `lsb_release -rs` | `24.04` | reinstall 24.04 |
| 3 | Base packages | `sudo apt update && sudo apt install -y git make curl python3-yaml python3-venv` | no "E:" line | send the "E:" line |
| 4 | NVIDIA driver (open modules) | `sudo ubuntu-drivers list`; `sudo apt install -y nvidia-driver-580-open` (or the newest `-open` listed); `sudo reboot`; `nvidia-smi` | the card; driver 580.65 or newer | "No devices were found": remove the non-open driver, install the `-open` one |
| 5 | Docker | follow "Install Docker Engine on Ubuntu" on docs.docker.com; `docker compose version` | v2.x | – |
| 6 | Docker without sudo | `sudo usermod -aG docker $USER`; sign out and in; `docker info` | no error | – |
| 7 | GPU in containers | install the NVIDIA Container Toolkit (NVIDIA's apt steps); `sudo nvidia-ctk runtime configure --runtime=docker`; `sudo systemctl restart docker`; `docker run --rm --gpus all ubuntu:24.04 nvidia-smi` | the card's table | "could not select device driver": repeat this step |
| 8 | The version | `git clone https://github.com/zandis/Auto-GPT.git`; `cd Auto-GPT/trialbox`; `git checkout <tag>` | "HEAD is now at …" | – |
| 9 | Card and tier check | `sh deploy/gpu_profile.sh`; `python3 tools/tiers.py check --tier large` | `rtxpro6000`; then the record's path | `default`: stop and send it |
| 10 | Model weights | the weights command sent with the tag (see below) | three folders under `deploy/models`; the template's `sha256sum` starts `ae53464b` | stop: the start will refuse other files |
| 11 | Start | `TB_LLM_MODE=gpu deploy/poc.sh` | "ok" lines for the GPU, the profile and the model folders; image build (10 to 20 min); pinning; the stack healthy (up to 15 min); **the admin password, shown once: write it down**; the canary passes; 600 synthetic patients loaded; the addresses | copy the red `poc:` line and the output of `deploy/poc.sh status`; running step 11 again is safe |
| 12 | Sign in | browser: `http://127.0.0.1:8090`, user `admin`; set up the second factor with a phone authenticator | the console | lost password: `deploy/poc.sh reset`, then step 11 |
| 13 | Feasibility | console, "Test mailbox": subject `FEAS GZQO` | web mail `http://127.0.0.1:8025`: a reply with PDF and XLSX | no reply in 10 min: send `deploy/poc.sh status` |
| 14 | First screened list | "Test mailbox": `SCREEN GZQO version=1.0.0` | an encrypted workbook and a summary PDF; the password in a second mail | send the reply text |
| 15 | Offline proof, then stop | unplug the network; repeat step 14; plug in; `deploy/poc.sh down` | the same list without network | send `deploy/poc.sh status` |

## The weights (step 10)

The start pins each folder against the hash the release expects, so each folder must hold exactly the publisher's
files at these revisions (safetensors and configuration only, no `.bin`, no `.py`, no cache folder):

| Folder under `deploy/models` | Source | Revision |
| --- | --- | --- |
| `gemma-4-26b-a4b-it-4bit` (the judge) | `nvidia/Gemma-4-26B-A4B-NVFP4` | `a19cfe00be84568a6867111c9a68c9c44fdcffe6` |
| `qwen3.5-9b-4bit` (the verifier) | `cyankiwi/Qwen3.5-9B-AWQ-4bit` | `e4d2d39cede8c5d1716d824cd843e2889c648083` |
| `chat-templates/gemma-4-26b-a4b-it/chat_template.jinja` (one file) | `google/gemma-4-26B-A4B-it` | `4d7ae4984b7db7de8f8457170b3f1a419ee76d52`, sha256 `ae53464bf3be25802b3a5b37def7fd89667067d7577049b3b2d74c4d8de4c6d4` |

Use the command sent with the tag. Until there is one, this is the manual way (not verified to give the expected
hashes): `python3 -m venv ~/hf && ~/hf/bin/pip install -U huggingface_hub`, then
`~/hf/bin/hf download <source> --revision <revision> --local-dir deploy/models/<folder>` for each model, then
remove any `.cache` folder inside, and fetch the template with `curl -fL -o
deploy/models/chat-templates/gemma-4-26b-a4b-it/chat_template.jinja
https://huggingface.co/google/gemma-4-26B-A4B-it/resolve/4d7ae4984b7db7de8f8457170b3f1a419ee76d52/chat_template.jinja`
(make the folder first with `mkdir -p`).

## On Windows instead (not verified anywhere)

Steps 2 to 7 become: `wsl --install -d Ubuntu-24.04` in an administrator PowerShell; the newest Windows NVIDIA
driver for the card (never a driver inside Ubuntu); a `%USERPROFILE%\.wslconfig` that gives WSL2 at least 96 GB of
memory (example: `deploy/windows/wslconfig.example`); `systemd=true` under `[boot]` in `/etc/wsl.conf`; then
Docker Engine and the toolkit inside Ubuntu as in steps 5 to 7. Steps 8 to 15 are the same, in the Ubuntu window.

## Every day after

Start: `TB_LLM_MODE=gpu deploy/poc.sh` (it keeps the passwords and the data). Stop: `deploy/poc.sh down`. State and
addresses: `deploy/poc.sh status`. Start again from nothing: `deploy/poc.sh reset`.
