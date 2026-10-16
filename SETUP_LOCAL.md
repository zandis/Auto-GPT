# TrialBox: local setup on Windows

- **Repository:** https://github.com/zandis/Auto-GPT
- **Branch:** `claude/trialbox-e2e-build-lcvm9p`. This is draft PR #2. `master` already contains phases 0–9 through
  PR #1; this branch adds the D-86 review fixes on top.
- **Code:** the `trialbox/` folder. The rest of the repository is the upstream Auto-GPT project and is not used.
- **Target folder:** `~/trialbox` **inside WSL** (Windows Explorer: `\\wsl$\<distro>\home\<user>\trialbox`). The
  project folder is `~/trialbox/trialbox`. Do not work from a Windows drive such as `I:\` (`/mnt/i`); see §5.

TrialBox is a Linux appliance: its Makefile uses bash, `install`, `chmod` and `sha256sum`, and the services run in
Docker. On Windows you run everything from PowerShell, while the work itself happens in **WSL2 (Ubuntu) + Docker
Desktop**. Native Windows Python is not supported. These steps were run on Windows 11 with WSL2 (Ubuntu) and Docker
Desktop: lint, unit, integration and e2e tests, `make images`, `make up-test` and the e-mail FEAS round trip.

## 1. Required runtimes

| what | version | where |
|---|---|---|
| Windows | 10 22H2+ or 11, virtualization on | |
| WSL2 + Ubuntu | Ubuntu 24.04 or newer | Windows |
| Docker Desktop | Docker Engine 27+ with Compose v2, **WSL integration on for your distro** | Windows |
| git | any recent | WSL (clone) |
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
- Test-stack host ports: `TB_HOST_<NAME>_PORT` for every published port (list with defaults in `.env.example`).
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
wsl -l -v                                # the distro's exact name, e.g. "Ubuntu-24.04" or just "Ubuntu"
$D = "Ubuntu-24.04"                      # <- set to that name; every command below uses it
winget install -e --id Docker.DockerDesktop
# Docker Desktop -> Settings -> Resources -> WSL integration -> enable $D, then Apply & restart (required, see §5)

wsl -d $D -- bash -lc "sudo apt-get update && sudo apt-get install -y make curl git openjdk-17-jdk-headless maven && curl -LsSf https://astral.sh/uv/install.sh | sh"
wsl -d $D -- bash -lc "git clone --branch claude/trialbox-e2e-build-lcvm9p https://github.com/zandis/Auto-GPT.git ~/trialbox"
```

## 4. Build, run, test (PowerShell)

```powershell
function tb([string]$cmd) { wsl -d $D --cd ~/trialbox/trialbox -- bash -lc $cmd }

tb "make venv"                 # .venv with Python 3.12 and the pinned dependencies
tb "make lint test"            # ruff, mypy --strict, unit + in-process tests (no services needed)
tb "make images"               # fonts, HL7 validator, CQL translator, FHIR packages, 2 images (first run: long)
tb "make up-test"              # whole box + stub LLM + GreenMail (IMAP 3143 / SMTP 3025) + MailHog (8025)

tb "make ingest-test"           # load synthetic site A (the integration and e2e tests also do this if it is missing)
tb ".venv/bin/python tools/send_test_mail.py 'FEAS GZQO'"
Start-Process http://127.0.0.1:8025     # MailHog (or your TB_HOST_MAILHOG_PORT): "Received ...", then "Done ..." with PDF + XLSX

tb "make test-integration"     # against the running test stack
tb "make test-e2e"             # every scenario by e-mail
tb "make logs"                 # last 100 lines per service
tb "make down"                 # stop the stack
```

The other scenarios are in `trialbox/README.md` (SCREEN, NAV, COHORT). Real-site deployment (hardening, settings
wizard, mapping, `--profile gpu`) is in `trialbox/docs/RUNBOOK.md`; that part targets a Linux host, not Windows.

## 5. If something fails

- **Tests stall for many minutes, or `chmod` has no effect.** The code is on a Windows drive (`/mnt/i`, `/mnt/c`,
  ...). WSL reaches those drives over a slow file-sharing protocol (9P), and the test suite reads many small files
  (DuckDB imports pandas lazily on every query, which scans the Python path); unit tests that take seconds inside WSL
  stalled for over 30 minutes on `/mnt/i`. Clone inside WSL as in §3.
- **`criteria-compiler` restarts in a loop with `IsADirectoryError`, or mounted files are empty folders.** Docker
  Desktop's WSL integration is off for your distro, so bind mounts such as `settings.yaml` arrive as empty directories.
  Turn it on (§3), restart Docker Desktop, then `tb "make down && make up-test"`.
- **`There is no distribution with the supplied name`.** `$D` does not match `wsl -l -v` (it may be just `Ubuntu`).
- **`bash\r: No such file or directory`.** The checkout has CRLF line endings, usually from a clone made with Windows
  git. Clone inside WSL (§3); `trialbox/.gitattributes` forces LF for clones made after commit 5d1671d.
- **Ports already in use.** Every port the test stack publishes can be moved: add the matching line to
  `trialbox/deploy/.env`, e.g. `TB_HOST_FHIR_PORT=18080` for 8080 or `TB_HOST_LLM_PORT=18000` for 8000 (the full
  list is at the end of `.env.example`), then `tb "make down && make up-test"`. The tests, `make` targets and
  `tools/send_test_mail.py` read the same file.
- **`make test-egress` fails.** Expected: it needs root and nftables on a Linux host.
