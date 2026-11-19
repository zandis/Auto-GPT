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
| 10 | Model weights | `python3 -m tools.fetch_weights --profile rtxpro6000 --dry-run`, then the same without `--dry-run` (see below) | the list of files and about 28 GB; then "ok" for the two model folders and the chat template, each licence, and "Next step"; `python3 -m tools.fetch_weights --profile rtxpro6000 --verify-only` says "All present and pinned." | send the red `fetch-weights:` line; running it again resumes and is safe |
| 11 | Start | `TB_LLM_MODE=gpu deploy/poc.sh` | "ok" lines for the GPU, the profile and the model folders; image build (10 to 20 min); pinning; the stack healthy (up to 15 min); **the admin password, shown once: write it down**; the canary passes; 600 synthetic patients loaded; the addresses | copy the red `poc:` line and the output of `deploy/poc.sh status`; running step 11 again is safe |
| 12 | Sign in | browser: `http://127.0.0.1:8090`, user `admin`; set up the second factor with a phone authenticator | the console | lost password: `deploy/poc.sh reset`, then step 11 |
| 13 | Feasibility | console, "Test mailbox": subject `FEAS GZQO` | web mail `http://127.0.0.1:8025`: a reply with PDF and XLSX | no reply in 10 min: send `deploy/poc.sh status` |
| 14 | First screened list | "Test mailbox": `SCREEN GZQO version=1.0.0` | an encrypted workbook and a summary PDF; the password in a second mail | send the reply text |
| 15 | Offline proof, then stop | unplug the network; repeat step 14; plug in; `deploy/poc.sh down` | the same list without network | send `deploy/poc.sh status` |

## The weights (step 10)

The start pins each folder against the hash the release expects, so each folder must hold exactly the publisher's
files at the pinned revisions (safetensors and configuration only, no `.bin`, no `.py`, no cache folder). One command
puts them there, from the repository's own pin record: the build rows of `models/registry.yaml` (each source and
revision, and the expected manifest hash) and the measured record they name (`deploy/measured/`, every file with
its size and sha256). It names no model itself, so the version tag decides what is fetched.

| Command (from `trialbox/`) | What it does |
| --- | --- |
| `python3 -m tools.fetch_weights --profile rtxpro6000 --dry-run` | lists every file, its size and address, the free disk; downloads nothing, writes nothing |
| `python3 -m tools.fetch_weights --profile rtxpro6000` | fetches, checks every file's sha256, moves each verified folder into `deploy/models` |
| `python3 -m tools.fetch_weights --profile rtxpro6000 --verify-only` | checks what is there against the pin; no network |
| `make fetch-weights` (`ARGS=--dry-run` or `ARGS=--verify-only`) | the same through the Makefile |

What it puts in place: `deploy/models/gemma-4-26b-a4b-it-4bit` (the judge, from `nvidia/Gemma-4-26B-A4B-NVFP4`),
`deploy/models/qwen3.5-9b-4bit` (the verifier, from `cyankiwi/Qwen3.5-9B-AWQ-4bit`) and
`deploy/models/chat-templates/gemma-4-26b-a4b-it/chat_template.jinja` (the judge's template, from
`google/gemma-4-26B-A4B-it`), each at the revision the registry names. The models root and the folder names are found as the start finds them:
`TB_MODELS_DIR` from the environment, else from `deploy/.env` (a line `TB_MODELS_DIR=...` with no spaces round
`=`), else `deploy/models`; `JUDGE_MODEL_DIR`, `VERIFIER_MODEL_DIR` and `JUDGE_CHAT_TEMPLATE` from the environment,
else the defaults above (not from `deploy/.env`, which the start does not read for them). The first line it prints
is the models root it will fill: check it. Every folder must lie inside that root: a symbolic link on the way out
of it is refused (to use another disk, set `TB_MODELS_DIR` to a folder there).

- It needs only `python3` and `python3-yaml` (step 3); the publisher's own download tool is not needed.
- Files arrive under `deploy/models/.fetch-weights` first. A folder is moved into place only when every file has
  its pinned sha256 and nothing else is in it (no extra, hidden or linked file); a file with another hash is
  deleted and the run stops.
- One run at a time: a second run started while one is fetching stops at once and says so.
- An interrupted download (network, power) resumes where it stopped: run the same command again.
- A folder already in place is never changed. If it is the pinned build it is reported present; if not, the run
  stops and names the differing files: move the folder aside (`mv <folder> <folder>.old`) and run again.
- It checks the free disk before downloading (the download plus 1 GB); if the disk fills anyway, it says "the disk
  is full" and stops.
- It sends only the download requests, over https, to the hub and the content store it redirects to. If the hub
  answers "refused" (HTTP 401 or 403) for a gated repository: sign in on the hub, accept the terms on the model's
  page, make a read token under the hub's settings (Access Tokens), and run again with it in the environment:
  `read -rs HF_TOKEN && export HF_TOKEN` (type or paste the token; it is not shown and not saved), then the
  command. The token goes only to the hub itself (never to the content store it redirects to, and never when
  `HF_ENDPOINT` names a mirror), and is never printed.
- At the end it prints each model's licence as `docs/licences/register.csv` records it, with the obligation (for
  the judge: the Apache 2.0 text beside the weights, outside the pinned folder), and the next step (step 11).

Nothing runs this command at install or start: the start only checks the folders and refuses other files.

## On Windows instead (not verified anywhere)

Steps 2 to 7 become: `wsl --install -d Ubuntu-24.04` in an administrator PowerShell; the newest Windows NVIDIA
driver for the card (never a driver inside Ubuntu); a `%USERPROFILE%\.wslconfig` that gives WSL2 at least 96 GB of
memory (example: `deploy/windows/wslconfig.example`); `systemd=true` under `[boot]` in `/etc/wsl.conf`; then
Docker Engine and the toolkit inside Ubuntu as in steps 5 to 7. Steps 8 to 15 are the same, in the Ubuntu window.

## Every day after

Start: `TB_LLM_MODE=gpu deploy/poc.sh` (it keeps the passwords and the data). Stop: `deploy/poc.sh down`. State and
addresses: `deploy/poc.sh status`. Start again from nothing: `deploy/poc.sh reset`.
