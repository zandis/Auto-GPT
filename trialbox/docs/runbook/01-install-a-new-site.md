# 1. Install a new site (about one day)

**Reader:** Aimedics and hospital IT, who install a site's box (the box form's owner sets a box up from the owner's pages in `docs/handover/`).

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
new card: a trial boot on a rehearsal box (D-726; an unmeasured card is accepted on a rehearsal box only) with
`TB_COMPOSE_OVERRIDE= TB_ACCEPT_UNMEASURED_GPU=1 deploy/install.sh <bundle> --gpu <profile> --rehearsal` (the empty
override keeps the real model servers, not the stand-ins), then on the box
`python3 tools/serving_config.py capture --container judge=trialbox-llm-service-1 --container
verifier=trialbox-llm-verifier-1 --models-dir deploy/models --out deploy/site/serving_config.<profile>.json`.
The trial box stays a rehearsal box (TB_ENV VALIDATION with its mark, doctor says "REHEARSAL BOX"): empty it before
the site's install (RUNBOOK §16, "A rehearsal box"), keeping the record.
`python -m tools.gpu_sizing` prints the hardware estimate. Feasibility needs no GPU; notes need one. The tier
rule is held by `tests/unit/test_install_tiers.py`.

**One command** (H-22, D-996). The vendor hands over a USB stick with four files: the signed bundle
`trialbox-<version>.tar` and its `.sha256`, and the bootstrap `trialbox-bootstrap.sh` and its `.sig`. The vendor key,
`vendor_ed25519.pub`, comes apart from the stick (out of band). Nothing TrialBox is on the machine before this command:
it runs from the stick, as root, with the stick mounted (here at `/media/usb`), the key at `/root/vendor_ed25519.pub`
and the site's folder at `/root/site` (below):
`cd /media/usb && openssl pkeyutl -verify -pubin -inkey /root/vendor_ed25519.pub -rawin -in trialbox-bootstrap.sh -sigfile trialbox-bootstrap.sh.sig && sudo bash trialbox-bootstrap.sh trialbox-<version>.tar --pub /root/vendor_ed25519.pub -- --tier large --answers /root/site/site.yaml`.
`openssl` must print `Signature Verified Successfully`; anything else, stop and call the vendor. The bootstrap checks
the bundle's signature with the same key and the release's host tree against it, unpacks the tree to `/opt/trialbox`
(never over a folder that holds anything else), places the key at `/opt/trialbox/deploy/keys/vendor_ed25519.pub`
and runs `/opt/trialbox/deploy/install.sh` with the bundle and the options after `--`. An install that stopped (a
missing answer, a machine check) is run again by the same command. The installer verifies and loads the bundle,
runs the settings wizard, makes one token per service, turns TLS on (the identity overlay, after `console.cli
check-tls` passed), starts the stack, creates the first administrator and prints the password and the enrolment code
once, writes the site's network sheet to `deploy/site/network-sheet.{en,ja,zh-TW}.{md,html}` (print it for hospital
IT), installs both cron files (log retention and backups), runs the host check, names the judge (its role, the
registry's label of the build the profile serves, and the pin) and ends with the `https://` console URL, which it
checks from the box with the certificate the clinic PCs will see. It exits 1 when a FAIL line remains, and lists them
(T-632, D-382). On a machine without a GPU, `--mode stub` takes the place of `--tier` (the installer refuses
the two together). A box without a GPU is a product form (D-1066): a feasibility-only site, which may add a GPU
later. It runs feasibility and screening on the structured criteria (diagnoses, labs, medicines, ages, dates);
criteria that need a note's free text wait for a GPU or a pinned cloud model. The installer pins the embedder
(`e-embed-1`, BGE-M3, on the CPU) from the bundle's weights: every site bundle carries them (about 2.3 GB, 18
files), and `release check` refuses a site bundle without them. A PRODUCTION install stops when they are missing.
How fast the CPU embeds a hospital's records is not measured yet.

**The questions it asks.** Without `--yes`, at the terminal, the installer asks whether to start the stack now and,
when the answers lack them, the ClinicalTrials.gov mode (`ctgov_mode`), the console's name (`tls_hostname`) and the
trial office's mailbox (`sae_office_mailbox`). With all three in the answers, add `--yes` after `--` for an install
that asks nothing.

**Memory caps from the hospital's size** (T-692, D-473). The night's ingest and the lake rebuild stream: what they
hold grows only slowly with the patient count. The installer sizes `TB_MEM_ADAPTER` and `TB_MEM_LAKE` in
`deploy/.env` from the number of patients (the lake's `CURRENT` snapshot on a re-install, else `TB_SITE_PATIENTS`,
which the site puts in `deploy/.env` before the first install) and the measured record
`deploy/measured/ingest_memory.json` (`python -m tools.trialbox.memcaps --measure` re-measures it). The compose
defaults are the floor; a cap set by hand is kept. `trialbox doctor` (`memory_caps`) fails when a cap is below what
the patient count needs; `python -m tools.trialbox.memcaps --env-file deploy/.env --write` sizes them again.

**The chart-number format** (D-579). The answers file says how the hospital writes a chart number, in
`chartno_rule`: `digits:8` for eight digits with leading zeros, `hex:8` for a hexadecimal key, `asis` when the number
is to be taken exactly as written. The wizard writes it to `deploy/.env` as `TB_CHARTNO_RULE`, and every service
writes a chart number that way before it becomes a pseudonym, so `123456` from a sheet that dropped the zeros and
`00123456` are one patient. The wizard refuses a rule the MRN pattern does not fit (the pattern must say one fixed
width, with both anchors). With no answer it keeps `asis` and warns; it never reads a rule from the pattern. Set
it at install: once the box has loaded patients the tools refuse another rule, because it would change the
pseudonym of every chart number that is not already written the new way.

**What the site brings** (D-382). A folder with the answers file and the site's mapping beside it:
`site.yaml` and `mapping/tw_core/<site>.yaml` (with its lab lookup). Put it where root can read it and nobody else
needs to, for example `/root/site`, and give the answers by their full path in the one command. The installer copies `mapping/` into
`deploy/site/mapping/`, which every update keeps; the wizard and the adapter look there before the image, so the
mapping is never part of the image. The answers name the feed folder on the host (`data_source_host_dir`, for example
`/srv/his-export`; written as `TB_SOURCE_DIR`) and the folder the adapter sees it at (`data_source_path`; compose
mounts the one at the other, read-only); the folder must exist and hold the hospital's first export before the
one command, put there by the hospital's IT from its HIS export (a PRODUCTION install stops without it), and the console's DNS name (`tls_hostname`) with `tls_mode` `hospital` (the
default and first choice; then `tls_cert_file` and `tls_key_file`) or `internal` (Caddy's own CA: its root must be on
every clinic PC by group policy, and personal devices cannot use it; the wizard warns). A PRODUCTION install stops without a feed folder or a TLS host
name, or without the trial office's mailbox (`sae_office_mailbox` in the answers, written as `TB_SAE_OFFICE_MAILBOX`;
asked with the TLS name: told at once when a serious adverse event is entered, without the AE term; D-736). A re-run
on a site that has its settings and a box install only warn, and `doctor` WARNs (`sae_mailbox`) until it is set. The vendor builds the bundle with
`tools/make_bundle.sh` (`make release-bundle`: `--gates` is required, so only images that passed the release gates;
the bundle carries `release.json`, the SBOMs, `NOTICE` and `CHANGELOG.md`, T-110b). The image vulnerability gate blocks
for every image a bundle carries; the dated exceptions and open findings are in `deploy/security/known-image-findings.md`
(SECURITY.md §8). On Windows the box runs in WSL2: `docs/handover/OFFLINE-MEDIA.md`,
`docs/handover/WINDOWS-INSTALL-CHECKLIST.md` and `deploy/windows/preflight.ps1`.

**Working days** (10C-14, D-1230). A site in Japan counts working days without its national holidays and its New
Year break: no coordinator digest on those days (the overdue SAE reports still go), and a visit window the protocol
counts in working days skips them. The break is 12-29 to 01-03 unless the answers say otherwise (`new_year_break`,
written as `TB_NEW_YEAR_BREAK`: `MM-DD/MM-DD` from December to January, at most 14 days, or `none`); the hospital's
own days off and the holidays it works go in the answers' `env_extra` as `TB_DAYS_OFF` and `TB_DAYS_OPEN`
(`YYYY-MM-DD`, comma separated). A value that cannot be read stops the box with a plain message. The schedule page
lists the coming days off. The holiday list ships in the update bundle; each year, when the Cabinet Office publishes
the next year (February), the vendor downloads `syukujitsu.csv`, records its sha256 in the licence register row
`jp-holidays` and runs `python3 -m tools.holidays_import syukujitsu.csv --sha256 <hex> --years <first>-<last>`; the
health line warns 90 days before the list runs out and is red after it.

**The same, step by step.**

1. **Host.** Ubuntu 24.04 LTS on LUKS2 with TPM2 unlock, swap off, Docker Engine 27+ with its compose plugin
   (`docker-compose-plugin` from Docker's packages, `docker-compose-v2` from Ubuntu's), nftables, and the packages
   `python3-yaml`, `python3-cryptography`, `curl`, `cron` and `openssl` (Ubuntu Server has `python3`, `tar` and
   `openssl`; the installer names the compose plugin and PyYAML when they are missing); the NVIDIA driver
   and container toolkit when there is a GPU (GB10: driver 580.142, held). See [Security §1](../SECURITY.md#1-the-host).
2. **Images.** `tools/apply_update.sh trialbox-<version>.tar` loads images, models and approved rulesets. A
   development host can build instead: `make images` (or `make images-multiarch` for x86 and GB10). The build host
   needs Docker, Maven and the JDK `.java-version` names, network to Docker Hub, Maven Central and GitHub, and disk
   for two copies of the bundle (D-830, D-885); the JVM fetch step names what is missing before it starts.
   A new box holds **no study**: the shipped example rulesets are seeded only where `TB_ENV` is DEV or TEST
   (D-640). The site's first study is compiled and approved in the console. For a synthetic run on a PRODUCTION
   box (never beside real patients), an operator installs an example after the stack is up:
   `docker compose exec criteria-compiler sh -c 'cd /app/rulesets && python -m zipfile -c /tmp/GZQO.zip GZQO &&
   python -m criteria_compiler.import_ruleset /tmp/GZQO.zip --by "synthetic-run:<who>"'`.
   The embedder's folder is `deploy/models/embedder`: the whole folder of the release (the registry's
   `e-embed-1` row: the publisher's revision without its three pickle files; README and images included), because
   its pin is the digest of every file in it (ENG-003, D-563). The judge's chat template goes beside the weights, at
   `deploy/models/chat-templates/gemma-4-26b-a4b-it/chat_template.jinja`: the developer's file at the revision
   `models/registry.yaml` names (`chat_template`, D-392). Compose starts the judge with `--chat-template` on it
   (`JUDGE_CHAT_TEMPLATE` moves it), and the install pins its sha256 with the weights; a judge without it is not
   pinned and routes nothing. The registry names the file's sha256 (HW-005, D-567): the install refuses any other
   file (`sha256sum` of yours must print the registry's `chat_template.sha256`).
3. **Settings.** `python -m tools.settings_wizard --out deploy/settings.yaml --env-out deploy/.env`, or
   `--answers site.yaml` (example: `python -m tools.settings_wizard --answers
   tests/fixtures/onboarding/site_c_answers.yaml --out deploy/settings.yaml --env-out deploy/.env`, which finds its
   mapping in `tests/fixtures/onboarding/mapping/`, beside the answers). Re-check an edited file with
   `--check deploy/settings.yaml`. The first question is the site's country (`country`: `jp`, `tw`, `us` or
   `other`, 10K-1): the report language, time zone, retention rules, source type and mapping offered next follow it
   (`libs/tb_common/site_country.py`); a Japan site is offered `ja`, `Asia/Tokyo`, Japan's retention and an SS-MIX2
   source (`data_source_host_dir` is then the storage's root folder, mounted read-only), and the TWPAS questions are
   asked for a Taiwan site only. Where TrialBox holds no value for the country the question has no default. An
   answers file without `country` reads exactly as before. Mail: the hospital MTA must add an `Authentication-Results` header; answer
   `mta_authserv_id` with its first token (for example `mx.hospital.tw`). A mail command is accepted on `dmarc=pass`,
   or on an SPF or DKIM pass for the From: domain.
4. **Mapping.** Copy a template from `services/adapter/mapping/templates/` to
   `deploy/site/mapping/tw_core/<site>.yaml` (its lab lookup beside it; keep `extends`: the shared mapping comes from
   the image) and check it against an export, in the release's Python image once the one command has loaded it
   (the host has the tool but not its packages):
   `docker run --rm --network none --user 0:0 -v /opt/trialbox/deploy/site/mapping:/app/deploy/site/mapping:ro -v <export dir>:/export:ro trialbox-py:1.0.0 python tools/mapping_check.py --mapping deploy/site/mapping/tw_core/<site>.yaml --source csv --path /export`
   ([Data §2](../DATA.md#2-mapping-a-site)). It must report 0 missing columns.
5. **Start.** `sudo python3 -m tools.trialbox secrets init`, then `cd deploy && docker compose -f docker-compose.yml
   -f docker-compose.secrets.yml -f docker-compose.identity.yml -f docker-compose.<gpu>.yml --profile gpu up -d
   --wait` (`--profile stub` without a GPU; TLS settings first, [§12](12-identity-and-tls.md)). Then
   `deploy/network.sh apply`. `install.sh` does both and enables the systemd units of `deploy/systemd`
   (D-377): the egress table closed at boot before Docker, the stack after a host restart, the egress refresh and
   watchdog timers. By hand: copy the units with `@TB_ROOT@` replaced by the install folder, then
   `systemctl enable trialbox-egress.service trialbox.service trialbox-egress-refresh.timer trialbox-watchdog.timer`.
6. **Vendor key.** The one command placed it (`deploy/keys/vendor_ed25519.pub`, from the key received out of
   band); the installer refuses to start without it.
7. **First ingest.** From `/opt/trialbox`: `docker compose --project-directory deploy exec adapter python -m adapter.cli run`,
   or wait for 02:00. It reads the feed folder (`TB_SOURCE_DIR`) with the site's mapping (`deploy/site/mapping`).
   The report is in the lake's volume, which the adapter mounts:
   `docker compose --project-directory deploy exec adapter cat /data/lake/ndjson/<date>/ingest_report.json`
   (`<date>` is the run's, `YYYY-MM-DD`): `passed: true`, validator errors under 0.5 %.
8. **Host check.** `deploy/check_host.sh [--gb10]`: no FAIL line.
9. **Backup key.** With hospital IT, once (§5).
10. **Acceptance** before go-live (§6).

**Sign-in.** Local accounts, or the hospital's single sign-on behind its reverse proxy: set `TB_CONSOLE_SSO_HEADER`
(for example `X-Forwarded-User`), `TB_CONSOLE_SSO_TRUSTED_PROXIES` (addresses or CIDRs), optionally
`TB_CONSOLE_SSO_ROLE_HEADER` and `TB_CONSOLE_SSO_ROLE_MAP=ad-group:admin,crc-group:coordinator`. Behind TLS set
`TB_CONSOLE_SECURE_COOKIE=1`; the doctor check fails without it in PRODUCTION (D-121).
