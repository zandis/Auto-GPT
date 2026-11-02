# TrialGPT in the cloud

This runs the same interface on a rented GPU server, open to the people you choose:

```
browser ──HTTPS + login──> Caddy ──> TrialGPT interface ──> Ollama (Gemma 4 on the GPU)
                    (only ports 80/443 open)                └──> ClinicalTrials.gov (search keywords only)
```

Everything runs on your own server. Notes go to your own model, not to an AI company.

> **Patient data.** In the cloud, patient notes leave the hospital and reach a server you rent. Use the cloud version
> for public or synthetic data (SIGIR/TREC, demos), for properly de-identified notes, or only with your hospital's
> approval (IRB, information security, data-protection officer) and a cloud region they accept. For identifiable
> CGRD data, use the on-prem setup (`RUNBOOK.md`).

## Google Cloud: one command

Open **Cloud Shell** in the Google Cloud console (the `>_` button, top right). It is already signed in to your
account, so no keys are shared with anyone. Select your project, then run:

```bash
gcloud config set project YOUR_PROJECT_ID
curl -fsSL https://raw.githubusercontent.com/zandis/Auto-GPT/claude/trialgpt-local-lcvm9p/trialgpt/deploy/gcp_deploy.sh -o gcp_deploy.sh
ALLOW=YOUR.HOSPITAL.IP.RANGE/24 bash gcp_deploy.sh        # without ALLOW the site is reachable from anywhere (login still required)
```

`gcp_deploy.sh` does sections 1–4 below for you:
- picks a zone in `asia-east1` (Taiwan) with an NVIDIA L4 (24 GB);
- reserves a static IP and opens 80 to all (HTTPS redirect and certificate check) and 443 to `ALLOW`;
- creates a `g2-standard-8` VM with Ubuntu 24.04, whose first boot installs the driver, Docker and the NVIDIA toolkit;
- starts the stack with `gemma4:26b`;
- prints the address (`https://<ip>.sslip.io`, or `DOMAIN=...`), the user name and a generated password, once.

Allow 20–30 minutes for the first start.

| variable | default | |
|---|---|---|
| `REGION` | `asia-east1` | e.g. `us-central1` if the region has no L4 |
| `MODEL` | `gemma4:26b` | `gemma4:31b` also fits the L4, tightly |
| `ALLOW` | `0.0.0.0/0` | who may open the site |
| `DOMAIN` | `<ip>.sslip.io` | your own name after you add a DNS A record |
| `SKIP_QUOTA_CHECK` | | `1` if the quota check misreads a granted GPU quota |

- **GPU quota.** New projects often have 0 GPU quota. The script stops and prints the quota page link: request
  `NVIDIA_L4_GPUS` = 1 in the region (and `GPUS_ALL_REGIONS` ≥ 1), then run it again.
- **Billing.** The GPU VM bills by the hour while running. Stop it when idle with
  `gcloud compute instances stop trialgpt --zone ZONE`; the disk and data stay. `bash gcp_deploy.sh --delete`
  removes the VM, the IP and the firewall rules.
- **Re-running** the script reuses everything, restarts the VM and issues a **new** password.

The script was syntax-checked and its parts (password hashing, `.env` writing, compose stack) were tested in a Linux
sandbox. It has not yet been run against a real Google Cloud project; if a step fails, send the message it prints.

## 1. Choose a server

Any provider works (AWS, Google Cloud, Azure, or smaller GPU clouds). You need Ubuntu 24.04, an NVIDIA GPU, at least
50 GB of disk and a fixed public IP.

| GPU memory (example GPUs) | model (`TG_LLM_MODEL`) |
|---|---|
| 16 GB (T4) | `gemma4:12b` |
| 24 GB (L4, A10G) | `gemma4:26b`, or `gemma4:31b` (tight) |
| 48 GB (L40S, A6000) | `gemma4:31b` |
| no GPU | works on CPU, but each trial takes minutes |

Firewall: open **80** and **443** to the people who need access (better: only the hospital's IP range), and **22**
for SSH from your own IP. Leave everything else closed.

## 2. Point a domain at it

Create a DNS **A record**, e.g. `trialgpt.your-hospital.org`, pointing to the server's IP. Caddy fetches the HTTPS
certificate (Let's Encrypt) automatically on first start.

## 3. Prepare the server (once)

Many providers offer a "GPU / Deep Learning" Ubuntu image with the driver, Docker and the NVIDIA Container Toolkit
already installed. In that case skip to the check at the end of this block.

```bash
sudo apt-get update && sudo apt-get install -y ubuntu-drivers-common git && sudo ubuntu-drivers install && sudo reboot
curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER      # log out and back in
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
docker run --rm --gpus all ubuntu nvidia-smi          # check: shows the GPU
```

## 4. Install and start

```bash
git clone --branch claude/trialgpt-local-lcvm9p --depth 1 https://github.com/zandis/Auto-GPT.git ~/trialgpt-src
cd ~/trialgpt-src/trialgpt/deploy
cp .env.example .env && chmod 600 .env
docker run --rm caddy:2.10 caddy hash-password --plaintext 'choose-a-strong-password'   # copy the $2a$... output
nano .env        # TG_DOMAIN, TG_USER, TG_PASSWORD_HASH (write each $ as $$), TG_LLM_MODEL
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

The first start pulls the model (8–20 GB) and builds the app image (about 1.8 GB). Follow it with
`docker compose logs -f`. Then open `https://trialgpt.your-hospital.org` and sign in. The first live search also
downloads the MedCPT retrievers (about 880 MB, kept in the `tgdata` volume).

## 5. Day to day

| task | command (in `trialgpt/deploy`) |
|---|---|
| status | `docker compose ps` |
| logs | `docker compose logs -f trialgpt` |
| update to the latest code | `git pull && docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build` |
| change the model | edit `TG_LLM_MODEL` in `.env`, then the same `up -d` |
| change the password | new hash in `.env`, then `docker compose up -d caddy` |
| stop (keeps data) | `docker compose down` |
| remove everything | `docker compose down -v` (deletes the model, caches and results) |

**More than one user.** Each person can have their own line in `Caddyfile` under `basic_auth`
(`name $2a$...hash`), so access can be removed per person.

**What is stored.** Interactive matches live in memory only, and the LLM cache is off for them. Benchmark and
head-to-head results go to the `tgdata` volume.

## What was tested

The stack was built and run in a Linux sandbox with Docker Compose v5:
- the image builds;
- the model service pulls the model before the app starts;
- the app reaches Ollama;
- Caddy answers 401 without a password and 200 with it, and redirects plain HTTP to HTTPS;
- a live patient match completed through the HTTPS front door: keywords, 148 ClinicalTrials.gov candidates, MedCPT
  ranking, LLM matching.

The GPU override was checked with `docker compose config` only: the sandbox has no GPU.
