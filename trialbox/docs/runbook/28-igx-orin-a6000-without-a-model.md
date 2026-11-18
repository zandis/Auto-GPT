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
| 6 | Build the database image (the start forgets it on a machine without Java build tools) | `docker build -f deploy/docker/db.Dockerfile -t trialbox-postgres:16-1 deploy/docker` | after 5 to 15 minutes, a line naming `trialbox-postgres:16-1` | send the last 30 lines |
| 7 | Start | `deploy/poc.sh` | "fetching fonts and JVM build inputs in a builder container"; image builds (perhaps 20 to 40 minutes on this processor); "starting the stack"; **the admin password, shown once: write it down**; "ingesting synthetic site A (600 patients)"; the addresses | copy the `poc:` line and the output of `deploy/poc.sh status` to us; running step 7 again is safe |
| 8 | Sign in | browser on this machine: `http://127.0.0.1:8090`, user `admin`; set up the second factor with a phone authenticator | the console's overview | lost password: `docker compose --project-directory deploy -f deploy/docker-compose.yml -f deploy/docker-compose.test.yml -f deploy/docker-compose.poc.yml --profile stub --profile test exec console python -m console.cli reset-password admin` prints a new one, shown once (not `deploy/poc.sh reset`: that deletes all the data) |
| 9 | Feasibility | console, "Test mailbox": subject `FEAS GZQO` | web mail `http://127.0.0.1:8025`: a reply with a PDF and an XLSX | no reply in 10 minutes: send `deploy/poc.sh status` |
| 10 | A screened list | "Test mailbox": `SCREEN GZQO version=1.0.0` | an encrypted workbook and a summary PDF; the password in a second mail | send the reply's text |
| 11 | Memory, after an idle hour | `docker stats --no-stream > ~/tb-stats.txt`; `free -g >> ~/tb-stats.txt` | a table of the services and their memory | send the file (it holds no password and no patient) |
| 12 | Stop | `deploy/poc.sh down` | the containers stop; data kept | – |

## Every day after

Start: `deploy/poc.sh` (it keeps the passwords and the data). Stop: `deploy/poc.sh down`. State and addresses:
`deploy/poc.sh status`. Start again from nothing, deleting all data: `deploy/poc.sh reset`.

The builder container of step 7 runs as root and leaves root-owned files under `.cache` in the checkout. They do no
harm; to delete the checkout later, use `sudo rm -rf Auto-GPT`.

## Optional: the real embedder (stub judge, real embedder)

The stub answers every note question; the **embedder**, the model that finds the note sentences a question is about,
can be the real one (build `e-embed-1` of `models/registry.yaml`), on the processor, beside the stub judge. It needs
about 2.3 GB of weights, about 2 GB more for its image, about 3.5 GB of memory, and 30 to 60 minutes (card 24-7).
Not verified on any Arm machine. Page 29 (step 4) runs it after the engine probe.

| # | Step | Type or click | You should see | If not |
| --- | --- | --- | --- | --- |
| E1 | A tool to download, at the version this page was written against | `python3 -m venv ~/hf && ~/hf/bin/pip install "huggingface_hub==2.4.0"` | no error | send the last lines |
| E2 | The source and revision the release pins (read from the registry, so nothing is typed by hand) | `REPO=$(python3 -c "import yaml; print(next(b['repository'] for b in yaml.safe_load(open('models/registry.yaml'))['builds'] if b['build_id'] == 'e-embed-1'))")`; `REV=$(python3 -c "import yaml; print(next(b['revision'] for b in yaml.safe_load(open('models/registry.yaml'))['builds'] if b['build_id'] == 'e-embed-1'))")`; `echo $REPO $REV` | a repository name and `7b44caba5c06fd6f1ef1d2786261e636c38e4295` | send it |
| E3 | See what will come, without downloading: one `--exclude` per file (with one `--exclude` and three names the tool downloads only the three names) | `~/hf/bin/hf download "$REPO" --revision "$REV" --local-dir deploy/models/embedder.download --exclude pytorch_model.bin --exclude colbert_linear.pt --exclude sparse_linear.pt --dry-run` | "Will download 20 files … 2.3G": `model.safetensors` (2.3G), `tokenizer.json`, `config.json` and the other small files, and no `pytorch_model.bin`, `colbert_linear.pt`, `sparse_linear.pt` or `onnx/` (two of the 20 are hidden files, `.gitattributes` and `imgs/.DS_Store`, which the check in E5 leaves out: it counts 18) | anything else: send it, and do not go on |
| E4 | Download | the same command without `--dry-run`; then `rm -rf deploy/models/embedder.download/.cache` | the files arrive (2.3 GB; 5 to 30 minutes) | a network error: run it again (it continues) |
| E5 | Check it is the pinned build before it goes in place | `docker run --rm -v "$PWD/deploy/models/embedder.download:/m:ro" trialbox-py:1.0.0 python -m tools.pin_model --build e-embed-1 --model-dir /m --endpoint embed --served-name e-embed-1 --out /tmp/check.yaml` | `pinned e-embed-1: sha256 e131f3203849…` (18 files) | any other line: send it, and do not go on |
| E6 | Put it in place | `mv deploy/models/embedder.download deploy/models/embedder` | – | – |
| E7 | Start again from nothing, once. Step 7 made the synthetic data with the stand-in embedder, and the real one cannot read it. `deploy/poc.sh reset` **deletes all the data of this proof of concept**: the synthetic hospital's database and lake, the test mailboxes, the console's accounts and the admin password. All of it is synthetic and is made again by the next start. It keeps `deploy/.env`, the images and the weights. Type it only if you agree | `deploy/poc.sh reset` | the containers and their volumes are removed | – |
| E8 | Start with it | `TB_POC_EMBED=model deploy/poc.sh` | "embedder check", "building the embedder image", "pinning the embedder", **a new admin password, shown once: write it down**, and at the end "TrialBox POC (stub model, model embedder)" | "the synthetic lake was embedded with the hash embedder": E7 was skipped. Anything else: send the `poc:` line |

The choice is kept in `deploy/.env` (`TB_POC_EMBED=model`): a later plain `deploy/poc.sh` keeps the real embedder. To
go back, `deploy/poc.sh reset` and then `TB_POC_EMBED=hash deploy/poc.sh`. This manual download is replaced by the
weights command of card W-1 (pull request #1085) once it is on master.

## Only when we ask: the engine probe (no model)

Replaced by page 29 step 2: one command (`python3 tools/engine_probe.py run`) tries the pinned engine as it is, with
its compatibility switch, with its compatibility libraries, and the same release's CUDA 12.9 build, one image at a
time, and writes one small file to send. The commands that were here did half of that by hand.
