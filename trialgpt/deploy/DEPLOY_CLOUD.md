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
