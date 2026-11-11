# 1. Install a new site (about one day)

**Pick the tier.** The three boxes we sell install with `--tier` (D-138):

| Tier | `--gpu` profile | Box | Serving |
| --- | --- | --- | --- |
| `small` | `rtx5090` | one RTX 5090 (32 GB) | the pair with the sleep swap, 8k |
| `medium` | `gb10` | DGX Spark (GB10) | the pair resident, 16k |
| `large` | `rtxpro6000` | one RTX PRO 6000 (96 GB) | the pair resident, 32k |

A tier installs only when its profile has a serving record of its own uncapped card (`deploy/site/` or the vendor's
`deploy/measured/serving_config.<gpu>.json`, checked by `tools/serving_config.py measured`) and the machine's card
is that card. Otherwise the installer stops before it touches anything (exit 3) and says what is missing. There is no
override. `deploy/install.sh --tier large --tier-check` only asks. Today only `large` has a vendor record. To measure a
new card: a trial boot with `TB_ACCEPT_UNMEASURED_GPU=1 deploy/install.sh <bundle> --gpu <profile>`, then on the box
`python3 tools/serving_config.py capture --container judge=trialbox-llm-service-1 --container
verifier=trialbox-llm-verifier-1 --models-dir deploy/models --out deploy/site/serving_config.<profile>.json`.
`python -m tools.gpu_sizing` prints the hardware estimate. Feasibility needs no GPU; notes need one. The tier
rule is held by `tests/unit/test_install_tiers.py`.

**One command.** With the vendor's signed bundle on a USB stick:
`sudo deploy/install.sh trialbox-<version>.tar --tier large --answers site.yaml`. It verifies and loads the bundle,
runs the settings wizard, makes one token per service, starts the stack, creates the first administrator, writes the
site's network sheet to `deploy/site/network-sheet.{en,ja,zh-TW}.{md,html}` (print it for hospital IT), installs the
nightly log job and runs the host check. `--mode stub` installs a box without a GPU. The vendor builds the bundle with
`tools/make_bundle.sh` (`make release-bundle`: `--gates` is required, so only images that passed the release gates;
the bundle carries `release.json`, the SBOMs, `NOTICE` and `CHANGELOG.md`, T-110b). The image vulnerability gate blocks
for every image a bundle carries; the dated exceptions and open findings are in `deploy/security/known-image-findings.md`
(SECURITY.md §8). On Windows the box runs in WSL2: `docs/handover/OFFLINE-MEDIA.md`,
`docs/handover/WINDOWS-INSTALL-CHECKLIST.md` and `deploy/windows/preflight.ps1`.

**The same, step by step.**

1. **Host.** Ubuntu 24.04 LTS on LUKS2 with TPM2 unlock, swap off, Docker Engine 27+, nftables; the NVIDIA driver
   and container toolkit when there is a GPU (GB10: driver 580.142, held). See [Security §1](../SECURITY.md#1-the-host).
2. **Images.** `tools/apply_update.sh trialbox-<version>.tar` loads images, models and approved rulesets. A
   development host can build instead: `make images` (or `make images-multiarch` for x86 and GB10).
3. **Settings.** `python -m tools.settings_wizard --out deploy/settings.yaml --env-out deploy/.env`, or
   `--answers site.yaml` (example: `tests/fixtures/onboarding/site_c_answers.yaml`). Re-check an edited file with
   `--check deploy/settings.yaml`. Mail: the hospital MTA must add an `Authentication-Results` header; answer
   `mta_authserv_id` with its first token (for example `mx.hospital.tw`). A mail command is accepted on `dmarc=pass`,
   or on an SPF or DKIM pass for the From: domain.
4. **Mapping.** Copy a template from `services/adapter/mapping/templates/` and check it against an export with
   `tools/mapping_check.py` ([Data §2](../DATA.md#2-mapping-a-site)). It must report 0 missing columns.
5. **Start.** `sudo python3 -m tools.trialbox secrets init`, then `cd deploy && docker compose -f docker-compose.yml
   -f docker-compose.secrets.yml -f docker-compose.<gpu>.yml --profile gpu up -d --wait` (`--profile stub` without a
   GPU). Then `deploy/network.sh apply`.
6. **Vendor key.** Install `deploy/keys/vendor_ed25519.pub`, received out of band.
7. **First ingest.** `docker compose exec adapter python -m adapter.cli run`, or wait for 02:00. Check
   `/data/lake/ndjson/<date>/ingest_report.json`: `passed: true`, validator errors under 0.5 %.
8. **Host check.** `deploy/check_host.sh [--gb10]`: no FAIL line.
9. **Backup key.** With hospital IT, once (§5).
10. **Acceptance** before go-live (§6).

**Sign-in.** Local accounts, or the hospital's single sign-on behind its reverse proxy: set `TB_CONSOLE_SSO_HEADER`
(for example `X-Forwarded-User`), `TB_CONSOLE_SSO_TRUSTED_PROXIES` (addresses or CIDRs), optionally
`TB_CONSOLE_SSO_ROLE_HEADER` and `TB_CONSOLE_SSO_ROLE_MAP=ad-group:admin,crc-group:coordinator`. Behind TLS set
`TB_CONSOLE_SECURE_COOKIE=1`; the doctor check fails without it in PRODUCTION (D-121).
