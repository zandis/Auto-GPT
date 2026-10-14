# TrialBox: local setup on Windows

- **Repository:** https://github.com/zandis/Auto-GPT
- **Branch:** `claude/trialbox-e2e-build-lcvm9p`. This is draft PR #2. `master` already contains phases 0–9 through
  PR #1; this branch adds the D-86 review fixes on top.
- **Code:** the `trialbox/` folder. The rest of the repository is the upstream Auto-GPT project and is not used.
- **Target folder:** `I:\trialbox`, which WSL sees as `/mnt/i/trialbox`. The project folder is
  `I:\trialbox\trialbox`.

TrialBox is a Linux appliance: its Makefile uses bash, `install`, `chmod` and `sha256sum`, and the services run in
Docker. On Windows you run everything from PowerShell, while the work itself happens in **WSL2 (Ubuntu) + Docker
Desktop**. Native Windows Python is not supported. These steps were written from the Linux build; they have not been
run on Windows yet. If a step fails, the fallback at the end works the same way with the code inside WSL.

## 1. Required runtimes

| what | version | where |
|---|---|---|
| Windows | 10 22H2+ or 11, virtualization on | |
| WSL2 + Ubuntu | Ubuntu 24.04 | Windows |
| Docker Desktop | Docker Engine 27+ with Compose v2, WSL integration on for Ubuntu | Windows |
| git | any recent | Windows (clone) |
| Python | 3.12 (exactly: `>=3.12,<3.13`), installed by uv | WSL |
| uv | latest | WSL |
| make, curl, coreutils | distro | WSL |
| JDK 17 + Maven 3.9 | `openjdk-17-jdk-headless`, `maven` | WSL (`make jvm-deps` runs `mvn`; integration tests run the HL7 validator jar) |
| disk | about 25 GB free (images about 15 GB plus caches) | |
| GPU | not needed: the quickstart uses the stub LLM (`TB_LLM_MODE=stub`) | |

## 2. Environment variables and secrets (names only)

**`trialbox/deploy/.env`** is created by `make deploy/.env` from `trialbox/.env.example`; edit the values there.
- Site and time: `TB_SITE_ID`, `TB_TZ`.
- Profiles and modes: `COMPOSE_PROFILES`, `TB_LLM_MODE`, `TB_EMBED_MODE`.
- Mail in: `IMAP_HOST`, `IMAP_PORT`, `IMAP_SSL`, `IMAP_USER`, `IMAP_PASS`, `MAIL_INTAKE_ADDR`.
- Mail out: `SMTP_HOST`, `SMTP_PORT`, `SMTP_STARTTLS`, `SMTP_USER`, `SMTP_PASS`, `MAIL_FROM_ADDR`,
  `TB_MAIL_AUTHSERV_ID`.
- Service URLs: `FHIR_BASE_URL`, `LAKE_URL`, `EMBED_URL`.
- LLM: `LLM_BASE_URL`, `LLM_MODEL`, `CLOUD_LLM_BASE_URL`, `CLOUD_LLM_API_KEY`.
- Object store: `TB_OBJECT_STORE`, `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`.
- Other: `NHI_TWPAS_BASE_URL`, `ATTACH_PASSWORD_MODE`, `LOG_LEVEL`, `POSTGRES_PASSWORD`, `TB_SETTINGS`.

The default `LLM_MODEL` in `.env.example` names a Qwen model. The quickstart does not call it (it uses the stub);
choose your own model before enabling a real LLM.

**Compose overrides** (optional, read from the environment):
- Images: `TB_IMAGE`, `TB_JVM_IMAGE`, `TB_DOCPARSER_IMAGE`, `TB_EMBED_IMAGE`, `HAPI_IMAGE`, `POSTGRES_IMAGE`,
  `MINIO_IMAGE`, `GREENMAIL_IMAGE`, `MAILHOG_IMAGE`, `VLLM_IMAGE`.
- Paths and settings: `TB_SETTINGS_FILE`, `TB_SOURCE_DIR`, `TB_MODELS_DIR`, `LLM_MODEL_DIR`.
- Tuning: `HAPI_XMX`, `GPU_MEM_UTIL`, `GUIDED_BACKEND`, `VLLM_GB`, `TB_CTGOV_MODE`, `TB_EMBED_DEVICE`.

**Secrets** are files, never environment variables. The `tb-secrets` Docker volume is mounted at
`/run/secrets/trialbox` and holds `site_hmac.key`, `site.key` and `pid_map.key`, created at site install
(`docs/RUNBOOK.md` §1). For tests, `make up-test` writes `.cache/test-secrets/site_hmac.key` itself.

**Build and test switches:**
- Behind a corporate proxy: `HTTPS_PROXY`, `TB_EXTRA_CA` (path to an extra CA certificate).
- Integration and egress tests: `TB_INTEGRATION`, `TB_EGRESS_TEST`, `TB_HL7_VALIDATOR_JAR`, `TB_FHIR_PACKAGE_HOME`
  (the Makefile sets these).
- Golden files: `UPDATE_SNAPSHOTS`.

## 3. Install (PowerShell, once)

```powershell
wsl --install -d Ubuntu-24.04            # reboot if asked, then open Ubuntu once to create the user
winget install -e --id Docker.DockerDesktop
# Docker Desktop -> Settings -> Resources -> WSL integration -> enable Ubuntu-24.04
winget install -e --id Git.Git

# keep LF line endings: the bash scripts break with CRLF
git clone -c core.autocrlf=false --branch claude/trialbox-e2e-build-lcvm9p https://github.com/zandis/Auto-GPT.git I:\trialbox

wsl -d Ubuntu-24.04 -- bash -lc "sudo apt-get update && sudo apt-get install -y make curl git openjdk-17-jdk-headless maven && curl -LsSf https://astral.sh/uv/install.sh | sh"
```

## 4. Build, run, test (PowerShell)

```powershell
function tb([string]$cmd) { wsl -d Ubuntu-24.04 --cd /mnt/i/trialbox/trialbox -- bash -lc $cmd }

tb "make venv"                 # .venv with Python 3.12 and the pinned dependencies
tb "make lint test"            # ruff, mypy --strict, unit + in-process tests (no services needed)
tb "make images"               # fonts, HL7 validator, CQL translator, FHIR packages, 2 images (first run: long)
tb "make up-test"              # whole box + stub LLM + GreenMail (IMAP 3143 / SMTP 3025) + MailHog (8025)

Invoke-RestMethod -Method Post -Uri http://localhost:8016/run -ContentType 'application/json' -Body '{"source":"csv"}'   # ingest synthetic site A
tb ".venv/bin/python tools/send_test_mail.py 'FEAS GZQO'"
Start-Process http://127.0.0.1:8025     # MailHog: "Received ..." then "Done ..." with the feasibility PDF + XLSX

tb "make test-integration"     # against the running test stack
tb "make test-e2e"             # every scenario by e-mail
tb "make logs"                 # last 100 lines per service
tb "make down"                 # stop the stack
```

The other scenarios are in `trialbox/README.md` (SCREEN, NAV, COHORT). Real-site deployment (hardening, settings
wizard, mapping, `--profile gpu`) is in `trialbox/docs/RUNBOOK.md`; that part targets a Linux host, not Windows.

## 5. If something fails on `I:\`

- **Builds are slow or file permissions look wrong.** WSL on a Windows drive (`/mnt/i`) is slow and ignores
  `chmod`. Clone inside WSL instead: `tb` becomes
  `wsl -d Ubuntu-24.04 --cd ~/trialbox/trialbox -- bash -lc $cmd`, after
  `wsl -d Ubuntu-24.04 -- bash -lc "git clone --branch claude/trialbox-e2e-build-lcvm9p https://github.com/zandis/Auto-GPT.git ~/trialbox"`.
- **`bash\r: No such file or directory`.** The checkout has CRLF line endings. Re-clone with
  `-c core.autocrlf=false`. `trialbox/.gitattributes` now forces LF for clones made after this commit.
- **Ports already in use.** Free 3025, 3143, 8000, 8010–8016, 8025, 8080 and 9000, or stop the other program.
- **`make test-egress` fails.** Expected: it needs root and nftables on a Linux host.
