# 1. Install a new site (about one day)

**Reader:** Aimedics, who install a site's box by hand or prepare it (a hospital installs from its own page, [hospital-install](../handover/hospital-install.en.md), in three languages, with one line to type; the box form's owner sets a box up from the owner's pages in `docs/handover/`).

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
`capture` needs Docker: it reads each server's settings from Docker's inspect output (`tools/serving_config.py:36-38`), so
a rented GPU without Docker (a pod) cannot make the record; use a VM with Docker and Compose (review 19 §4.2).
The `rtx5090` record may come from an RTX 5090 or from the RTX PRO 4500, its fallback card (plan 10 decision 106).
The trial box stays a rehearsal box (TB_ENV VALIDATION with its mark, doctor says "REHEARSAL BOX"): empty it before
the site's install (RUNBOOK §16, "A rehearsal box"), keeping the record.
`python -m tools.gpu_sizing` prints the hardware estimate. Feasibility needs no GPU; notes need one. The tier
rule is held by `tests/unit/test_install_tiers.py`.

**Load from the stick, two packs** (H-95). A release comes as a software pack `trialbox-<version>.tar` (the box's
own images, the host tree, rule sets, reference data, the installer; a few GB, what every update carries) and a model
pack `trialbox-models-<version>.pack` (the engine image and the weights; installed once, and again only when the
pair or the engine changes), each signed on its own, each with its `.sha256`. The software pack names its model
pack by that pack's signed identity (its bundle id and the sha256 of its signed manifest), and `install.sh` finds
the model pack beside it by that identity (or takes the one its model-pack option names); a whole bundle of before still installs
alone. Nothing is copied off the stick: the verify pass hashes every payload on the stick (no image archive and no
weight file is written), then each pack is loaded straight from the stick, the model pack first, every image and
weight file hashed again as it goes in (a weight file takes its name only when its hash holds; an image stream
whose hash fails at its end is cut short and removed). Before it loads, the install prints
`disk: installed size …; peak during the load …, at most … (installed + 10 %); the stick holds …`;
the free disk needed is that peak. A software pack whose model pack the box does not hold
is refused before anything is loaded, naming the model pack's bundle id and manifest sha256. The release walked on
2026-11-23 was 60.7 GB in one bundle; the bundle builder prints the two packs' sizes when it builds them.
An update that changes the pair (a new model pack with a new software pack) loads the model pack first with the
software pack named by `--for-software` (the update tool refuses a model pack that the software on the box does not
name, unless the software pack loaded straight after it names it), then the software pack; the installer does this
itself for a first install. An update of the software alone takes the software pack only.

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
check-tls` passed), starts the stack, creates the first administrator and shows the password and the enrolment code
once on the terminal (never in its output, which a log may keep: box-install.sh keeps one; with no terminal at all
they are in `/root/trialbox-admin-first-sign-in`, root only: read it once, hand both on in person, remove it), writes the site's network sheet to `deploy/site/network-sheet.{en,ja,zh-TW}.{md,html}` (print it for hospital
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

**A machine without a usable TPM** (H-96). The site keys are then sealed under a passphrase (12 characters or more,
one line). It goes in a file only root can read, and its name goes after `--`: after sudo's own password prompt, type
the passphrase, then press Enter (nothing is shown):
`sudo bash -c 'umask 077; IFS= read -rs p; printf "%s\n" "$p" > /root/trialbox-kek.pass'`, then the one command
with `-- --tier large --answers /root/site/site.yaml --kek-passphrase-file /root/trialbox-kek.pass`, and with
TB_KEK_BACKEND=passphrase set by sudo before bash. The file must be a regular file owned by root with mode 0600; the
seal step removes it once the keys are sealed. `--kek-passphrase-stdin` instead asks for it twice on the terminal. A
passphrase in the environment (sudo's preserve-env or -E option) is refused before anything, on every box: sudo writes a variable it keeps, with its value, to the system journal. A box
installed that way rotates its passphrase (§23, "Rotate the KEK passphrase").

**Re-running the installer.** After the release's own checks pass (pre-start) and before the database starts, the installer may run Compose `down --remove-orphans` on its own project. It does so only when every container of the project was started from this `deploy` folder and the stack is not running healthy (a failed earlier run). A healthy stack is kept with its logs. A `COMPOSE_PROJECT_NAME` in the shell that is not this install's project, or a container of the project from another folder, stops the installer and nothing is removed. Volumes and data are always kept.
重新執行安裝程式時，版本檢查（pre-start）通過後、資料庫啟動前，只有當此專案的所有容器都來自本 `deploy` 資料夾且堆疊並非健康運行（先前執行失敗）時，才會對本專案執行 `down --remove-orphans`。健康運行的堆疊與其日誌會保留。若 shell 的 `COMPOSE_PROJECT_NAME` 不是本安裝的專案，或專案中有來自其他資料夾的容器，安裝程式會停止且不移除任何項目。資料卷與資料一律保留。
再実行時は、リリースの確認（pre-start）が通った後、データベースの起動前に、プロジェクトの全コンテナがこの `deploy` フォルダーから起動され、かつスタックが正常稼働していない場合（以前の失敗した実行）に限り `down --remove-orphans` を実行します。正常稼働中のスタックはログとともに保持されます。シェルの `COMPOSE_PROJECT_NAME` がこのインストールのプロジェクトでない場合や、別フォルダーから起動されたコンテナがある場合は、何も削除せずに停止します。ボリュームとデータは常に保持されます。

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
SCREEN and FEAS of the whole hospital hold its rows in the orchestrator, so `TB_MEM_ORCH` grows with the hospital: the
installer writes it from `deploy/measured/orchestrator_memory.json` (the size ladder's peaks, H23b-01, D-1005) once the
need passes the compose default of 4 GiB, from about 45,000 patients (about 8.3 GiB at 100,000). Below that the box
keeps the shipped cap. The machine needs that memory beside the other services'.

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
the bundle carries `release.json`, the SBOMs, `NOTICE` and `CHANGELOG.md`, T-110b). A site bundle carries its weights:
the option `--models` names a folder laid out as the profile's compose file reads it (the judge's and the
verifier's folders, the judge's chat template and `embedder/`), read through its links (H-43). `release check` refuses
a site bundle without `embedder/`. The vendor's `tools.fetch_weights` with `--embedder` fills such a folder once the
embedder's file record is committed (H43-01); until then the cloud build places it (`box_vm.py models-place`,
runbook §11). The image vulnerability gate blocks
for every image a bundle carries; the dated exceptions and open findings are in `deploy/security/known-image-findings.md`
(SECURITY.md §8). On Windows the box runs in WSL2: `docs/handover/OFFLINE-MEDIA.md`,
`docs/handover/WINDOWS-INSTALL-CHECKLIST.md` and `deploy/windows/preflight.ps1`.

**Working days** (10C-14, D-1230). A site in Japan counts working days without its national holidays and its New
Year break: no coordinator digest on those days (the overdue SAE reports still go), and a visit window the protocol
counts in working days skips them. The break is 12-29 to 01-03 unless the answers say otherwise (`new_year_break`,
written as `TB_NEW_YEAR_BREAK`: `MM-DD/MM-DD` from December to January, at most 14 days, or `none`); the hospital's
own days off and the holidays it works go in the answers' `env_extra` as `TB_DAYS_OFF` and `TB_DAYS_OPEN`
(`YYYY-MM-DD`, comma separated, at most 30 days a year). The wizard refuses a value it cannot read; a running box never
stops on one: it leaves the value out and the health line is red until it is put right. The schedule page lists the
coming days off. The holiday list ships in the update bundle; each year, when the Cabinet Office publishes
the next year (February), the vendor downloads `syukujitsu.csv`, records its sha256 in the licence register row
`jp-holidays` and runs `python3 -m tools.holidays_import syukujitsu.csv --sha256 <hex> --years <first>-<last>`; the
health line warns 90 days before the list runs out and is red after it.

**The same, step by step.**

1. **Host.** Ubuntu 24.04 LTS on LUKS2 with TPM2 unlock, swap off, Docker Engine 27+ with its compose plugin
   (`docker-compose-plugin` from Docker's packages, `docker-compose-v2` from Ubuntu's), nftables, and the packages
   `python3-yaml`, `python3-cryptography`, `curl`, `cron` and `openssl` (Ubuntu Server has `python3`, `tar` and
   `openssl`; the installer names the compose plugin and PyYAML when they are missing); the NVIDIA driver
   and container toolkit when there is a GPU (GB10: driver 580.142, held). See [Security §1](../SECURITY.md#1-the-host).
   Installing over SSH: with `SSH=off` in `deploy/site/hardening.conf` (the example's default) the host baseline
   would stop sshd under you, so the installer refuses at its start, before it loads anything (H-70). Run it from the
   box's console, set `SSH=it` with your address in `IT_RANGES`, or add `--ssh-off-over-ssh` (the session ends).
2. **Images.** `tools/apply_update.sh trialbox-<version>.tar` loads images, models and approved rulesets. A
   development host can build instead: `make images` (or `make images-multiarch` for x86 and GB10).
   The build needs Docker's buildx plugin (every Dockerfile uses `RUN --mount`): `docker buildx version` must print a
   version. Without it `make images` stops first with "images: Docker's buildx plugin is missing" (Docker's own
   builder: "the --mount option requires BuildKit"); install `docker-buildx-plugin` from Docker's packages
   (`docker-buildx` from Ubuntu's), as found by an install test, 2026-11-20 (H-70). The build host
   needs Docker, Maven and the JDK `.java-version` names, network to Docker Hub, Maven Central and GitHub, and disk
   for two copies of the bundle (D-830, D-885); the JVM fetch step names what is missing before it starts.
   The build needs memory (how much is not measured): on a Windows host raise the Linux VM's memory limit or build with fewer parallel jobs, or `make images` can take the VM down.
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
   watchdog timers. For a manual install, render the units as the installer does (install folder, timeouts and
   Compose scale options), then run
   `systemctl enable trialbox-egress.service trialbox.service trialbox-egress-refresh.timer trialbox-watchdog.timer`.
   Start `trialbox.service` after enabling it so systemd can stop the stack immediately after installation.
   手動安裝時，請依安裝程式填入安裝目錄、逾時值及 Compose 容器數量設定。啟用後請啟動 `trialbox.service`，這樣安裝完成後即可透過 systemd 停止所有容器。
   手動インストールでは、インストーラーと同様に配置先、タイムアウト、Compose のコンテナ数を設定します。
   有効化したら `trialbox.service` を起動します。これでインストール直後から systemd でコンテナを停止できます。
6. **Vendor key.** The one command placed it (`deploy/keys/vendor_ed25519.pub`, from the key received out of
   band); the installer refuses to start without it.
7. **First ingest.** From `/opt/trialbox`: `docker compose --project-directory deploy exec adapter python -m adapter.cli run`,
   or wait for 02:00. It reads the feed folder (`TB_SOURCE_DIR`) with the site's mapping (`deploy/site/mapping`).
   The report is in the lake's volume, which the adapter mounts:
   `docker compose --project-directory deploy exec adapter cat /data/lake/ndjson/<date>/ingest_report.json`
   (`<date>` is the run's, `YYYY-MM-DD`): `passed: true`, validator errors under 0.5 %.
8. **Host check.** `deploy/check_host.sh [--gb10]`: no FAIL line. It names the box's tier; on a desk-side or unknown
   tier a disk the TPM alone opens is a FAIL (add a Tang server or a PIN, D-1342). Then the live preflight with the next action under
   each line that is not green (10K-3; the box's first-run page shows the same list):
   `python3 -m tools.trialbox doctor --preflight --env-file deploy/.env --lang ja`.
9. **Backup key.** With hospital IT, once (§5).
10. **Acceptance** before go-live (§6).

**Sign-in.** Local accounts, or the hospital's single sign-on behind its reverse proxy: set `TB_CONSOLE_SSO_HEADER`
(for example `X-Forwarded-User`), `TB_CONSOLE_SSO_TRUSTED_PROXIES` (addresses or CIDRs), optionally
`TB_CONSOLE_SSO_ROLE_HEADER` and `TB_CONSOLE_SSO_ROLE_MAP=ad-group:admin,crc-group:coordinator`. Behind TLS set
`TB_CONSOLE_SECURE_COOKIE=1`; the doctor check fails without it in PRODUCTION (D-121).

**Choices a PRODUCTION site answers** (D-1365). The wizard refuses an empty `chartno_rule` on a PRODUCTION site
(`asis` is an answer); `doctor` (`named_choices`) warns a site installed before, with the line to add.
