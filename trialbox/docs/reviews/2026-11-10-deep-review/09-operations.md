# TB-DR-09 Operations

| Field | Value |
| --- | --- |
| Date | 2026-11-10 |
| Code read | `origin/master` at `ca8f287`. Open PRs read by diff: #68 (box-install rehearsal, head `7bc8a127`), #83 (update safety, head `a9ef5bea`), #85 (shared-quota platform, head `554ecc11`). |
| Method | One reviewer. Read every file under `deploy/`, the host tools (`tools/trialbox/*`, `apply_update.sh`, `make_bundle.sh`, `sign_bundle.py`, `verify_update.py`, `settings_wizard.py`, `network_sheet.py`, `canary.py`, `spark_e2e.sh`), `docs/RUNBOOK.md`, `docs/SECURITY.md`, `docs/handover/*`, `docs/plan/sites/*`, the operations cards of TB-ASSESS-01 and the register (CR rows). Then ran every procedure that runs without Docker or a GPU. |
| What was run | `bash -n` / `sh -n` on 22 shell scripts (all parse). `docker compose config` on 8 file sets (7 render, 1 fails as expected alone). The settings wizard with the RUNBOOK's example answers. `trialbox secrets init/status`, `doctor`, `backup-status`, `check_host.sh`, `network_sheet`, `egress.py print`. A throwaway signed bundle through `apply_update.sh --dry-run` (good, tampered, wrong key). `tools.gpu_sizing`. The demo (`tools.demo`) and the role demo (`tools.role_demo`) on ports 18650 and 18651, with a sign-in and lock-out probe. Evidence files: the review session's scratch folder, subfolder `09-operations/` (`syntax.txt`, `rendered.rtxpro6000.yml`, `demo.log`, `role_demo.log`, `probe2.py`). |
| What was not run | Anything that needs the Docker daemon (it is not running here: `docker info` fails on the socket): `install.sh`, `poc.sh`, `make_bundle.sh`, the update and backup paths on a compose box, `network.sh apply`, `spark_e2e.sh`, image builds. Anything that needs a GPU, a Spark, WSL2, Windows (`preflight.ps1`), Kubernetes or a B200. `shellcheck` and `hadolint` are not installed here. No cloud call was made; prices in §4 are list prices from memory and must be checked at order. The two demos ran with their temp root in `/var/tmp` because the session scratch folder is not reachable by the `postgres` user (the folder was removed afterwards). |

## 1. Summary

Operations is the least proven part of TrialBox. The code for install, update, backup and identity is careful and
well tested in process. But nothing has run on a real box, and the documents for hospital IT promise more than
exists. The CGMH form (a shared B200) has install checks in PR #85 and no day-2 operation.

Counts: **Blocker 3, Critical 0, High 26, Medium 40, Low 8** (77 findings). About half are already registered or
covered by a card, at least in part; they are listed so the operations picture is whole, with what to add. The
three Blockers: OPS-001 (new), OPS-050 (CR-084) and OPS-061 (CR-041).

Top 5:

1. **OPS-001 (Blocker, PoC).** The default demo image does not start when built from a clean clone: a jar that git
   does not carry is missing. Render and Cloud Run builds hit this. Found by a run.
2. **OPS-010 (High).** The host-side files (compose files, `tools/`, `egress.py`, the Caddyfile, `routing.yaml`) are
   not in the signed bundle and no update changes them. A release that changes a compose file cannot be delivered.
3. **OPS-011 (High).** An installed box has no place for the site's mapping file and no mount for the site's feed.
   The one-command install cannot work for a real site.
4. **OPS-050 (Blocker, registered CR-084).** Shared B200: the platform kind is unknown, the quota must be two MIG
   instances not one, and backup, logs, update and restore do not exist for that form.
5. **OPS-040 (High).** The hospital IT pack states about twenty controls that are not built (metrics, health mail,
   syslog, DNS allowlist, decommission, key wrapping). It is about to be handed to hospital IT.

Also high: no support model, no incident plan, no decided appliance OS, and no measured RPO or RTO.

## 2. Findings

Status words: `new`, `registered CR-nnn`, `card T-nnn covers`, `in PR #nn`. "By a run" means I ran it here.

### 2.1 Hosting the PoC

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| OPS-001 | Blocker | The default demo (`TB_DEMO_TOOL=demo`) exits at start when the image is built from a clean clone. The CQL translator jar is in `.cache/`, which git ignores, and `demo/Dockerfile` fetches fonts only. Render (`render.yaml`) and `gcloud run deploy --source` build from git. | By a run: `python -m tools.demo` ends with `FileNotFoundError: FHIRHelpers-4.0.1.cql not found in the cql-translator jars`, then `AssertionError: ('GOUT-COH', 'failed')` (`demo.log`). `.gitignore:15` (`.cache/`); `demo/Dockerfile:29-31`; `Makefile:149-151` (`demo-bundle` does not depend on `jvm-deps`). | Fetch the jar in the Dockerfile with a pinned sha256 (as `tools/fetch_jvm_deps.sh` does), or make `demo-bundle` depend on `jvm-deps` and fail the build when the jar is absent. Acceptance: a CI job builds `demo/Dockerfile` from a fresh checkout, starts it and gets 200 on `/login` and a `pi` sign-in. | new | yes |
| OPS-002 | High | No per-tester accounts. Six fixed accounts (`admin, crc, pi, smo, cra, viewer`) share one password. There is no sub-investigator account. Feedback and audit lines cannot be tied to a tester. | `demo/README.md:5`; by a run: "accounts: admin, crc, pi, smo, cra, viewer" (`role_demo.log:34`). | Seed accounts from `TB_DEMO_ACCOUNTS` (a JSON file: name, role, language, own password, end date). Ship a PoC list: PI, sub-investigator and CRC for each tester. Acceptance: two testers sign in with their own names; `/audit` shows each. | new | yes |
| OPS-003 | High | A public demo is guarded by a password only (no second factor in DEV), and anyone who knows the URL can lock the testers out: five wrong passwords for `pi` lock it for 15 minutes. | By a run (`probe2.py`): `pi` signs in with the password alone; after six wrong passwords the right one gets 401. Lock-out itself is CR-116. | Put an identity front door before the console: Cloudflare Access or Google IAP with the two testers' mail addresses. Keep the console's own sign-in behind it. Acceptance: the URL without an Access session returns the provider's page, not `/login`. | new (lock-out: registered CR-116) | yes |
| OPS-004 | High | A tester can upload or paste a real chart into the hosted demo. The console has upload forms and no PoC switch turns them off. Testers are clinicians with real charts one window away. This would break the data rule. | `services/console/app.py:1593` (`charts: list[UploadFile]`), `templates/case.html:10`, `consent.html:9`, `protocol.html:8`; grep for a demo guard on uploads: none. | A `TB_POC_MODE=1` setting: every upload and paste box shows "synthetic data only" in three languages and refuses a file or text that the data-handling scan flags (reuse `tools/data_scan`). A banner on every page. Acceptance: a planted Taiwan ID in a pasted note is refused. | new | yes |
| OPS-005 | Medium | The demo needs more memory than the README says, and Render's free plan cannot run it. | By a run: role demo 435 MB RSS for Python alone, about 0.9 GB with its PostgreSQL; the full demo passed 670 MB while seeding. `demo/README.md:19` says "About 250 MB"; `render.yaml` says `plan: free` (512 MB, sleeps after 15 minutes). | README: 2 GB. `render.yaml`: a 2 GB plan, or remove the Render path. Cloud Run: `--memory 2Gi`. | new | yes |
| OPS-006 | Medium | Every restart wipes the demo (`shutil.rmtree` at start, data in `/tmp`). A PoC of several weeks loses the testers' marks on any redeploy, VM restart or Cloud Run cold start. | `tools/demo.py:48-50`; `demo/Dockerfile:34`. | A `--keep` mode with the data on a volume; reset only on request. Or announce a fixed reset time. | new | yes |
| OPS-007 | Medium | The hosted demo script serves HTTPS but switches the Secure cookie off. The older demo VM serves plain HTTP on port 80. | `deploy/gcp/hosted-demo-startup.sh:51,53` (`TB_CONSOLE_SECURE_COOKIE=0`); `docs/RUNBOOK.md:403-405`. | Seed in process, then start the server with Secure cookies. Never share a plain HTTP link. | new | yes |
| OPS-008 | Medium | The hosted demo builds on the VM at every boot from a git clone, pulls `caddy:2` by tag, and the other script pipes `get.docker.com` to a shell. The demo image has 32 fixable HIGH or CRITICAL findings. | `hosted-demo-startup.sh:32-33,47,66`; `demo-vm-startup.sh:16`; `deploy/security/known-image-findings.md` (trialbox-demo row). | Build once, push by digest to a private registry, run that digest. Pin Caddy by digest. Front door of OPS-003 limits exposure. | new (image findings: registered CR-045, in PR #78) | yes |
| OPS-009 | Low | The demo image carries the whole repository (`COPY . /app`), with `docs/reviews` (the open security register) and the tests. | `demo/Dockerfile:28`; `.dockerignore` (no `docs/` line). | Exclude `docs/` and everything the demo does not import. | new | no |
| OPS-077 | Low | A temp root made by `tools.demo` has no marker, so the next tool run with the same `TB_TEST_ROOT` is refused. | By a run: `TB_TEST_ROOT=... is refused: it holds files and no .tb-test-root marker`. | `pglocal.for_work` writes the marker when it creates the root. | new | yes (option b) |

### 2.2 Install

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| OPS-010 | High | The host tree is outside the signed bundle and outside the update path. The bundle carries images, models, rulesets and five loose files. The compose files, `tools/`, `libs/` for the host tools, `deploy/egress.py`, the Caddyfile, `db-init` and `models/routing.yaml` come from an unsigned copy ("Copy the release to `/opt/trialbox`") and an update never replaces them. Image tags are fixed at `1.0.0`, so only image content changes. A release that adds a service, a volume or an environment variable cannot be shipped. | `tools/make_bundle.sh:85` (the `other` list); `tools/trialbox/update.py:170-176,438` (`copy_other` writes to `deploy/updates/<bundle>/files`, nothing reads it back); `docs/handover/OFFLINE-MEDIA.md:9-27` (no source tree in the layout); `WINDOWS-INSTALL-CHECKLIST.md` "Copy the release". PRs #68 and #83 do not change this. | A payload kind `host`: one signed tarball of the host tree. Install and update unpack it to `/opt/trialbox/releases/<id>` and switch a `current` link; rollback switches back. `verify_update` checks it like any payload. Acceptance: the update drill ships a compose change and it takes effect; a changed byte in a compose file on the media is refused. | new | no |
| OPS-011 | High | A real site cannot give the box its mapping file or its feed. The adapter resolves the mapping under the image path `services/adapter/`; no compose file mounts a site mapping folder. The feed mount defaults to a test fixture path and the wizard never writes `TB_SOURCE_DIR`; the mount point is fixed at `/data/source/site-a` while the wizard's answer may say another path. | `services/adapter/cli.py:26,43-45`; `deploy/docker-compose.yml:158-163`; by a run: the wizard's `.env` has no `TB_SOURCE_DIR`; `tools/settings_wizard.py:201` (the mapping must exist inside the image when the wizard runs in the container, `install.sh:153-154`). | Mount `deploy/site/mapping` read-only into the adapter and resolve relative mappings there first. The wizard asks for the feed folder, writes `TB_SOURCE_DIR`, and compose uses `${TB_SOURCE_DIR:?}` in PRODUCTION. `doctor` checks that the mapping and the feed folder exist. Acceptance: the box rehearsal of PR #68 installs with a mapping that is not in the image. | new | no |
| OPS-012 | Medium | The RUNBOOK's example answers file does not work. | By a run: `python -m tools.settings_wizard --answers tests/fixtures/onboarding/site_c_answers.yaml ...` → `not written: mapping file mapping/tw_core/site_c.yaml not found`, exit 1. `docs/RUNBOOK.md:44`. | Fix the fixture or the reference; add a test that runs every command the RUNBOOK names with a fixture. | new | no |
| OPS-013 | High | After `install.sh` ends, no clinic PC can use the box. The identity overlay is not added, the TLS host name is not asked, the printed URL is `http://127.0.0.1:8090` while the cookie is Secure in PRODUCTION, the first administrator's enrolment code is a separate shell step that the installer does not print, and the backup cron is not installed. | `deploy/install.sh:261-270,287-292,326-347`; `docs/RUNBOOK.md:536-537,557-559`; backup cron: `RUNBOOK.md:222-223`. PR #68 does not add these (grep of its `install.sh`). | The installer asks TLS mode and host name, appends the overlay, runs `check-tls`, installs both cron files, prints the enrolment code once, and ends with the `https://` URL. It exits 1 on a FAIL (T-108 has this). | card T-108 covers part (exit code, `.env.example`); backup cron registered CR-058; TLS and enrolment steps new | no |
| OPS-014 | Medium | The network sheet tool crashes on the identity overlay, and the installer hides the error. The sheet hospital IT gets never shows port 443, Caddy, Authelia, LDAPS, NTP or the backup share. | By a run: `yaml.constructor.ConstructorError: could not determine a constructor for the tag '!reset'` (`deploy/docker-compose.identity.yml:68`, `tools/network_sheet.py:217`); `install.sh:294-297` (`>/dev/null 2>&1 ... \|\| echo note`); the sheet without the overlay lists only `127.0.0.1:8090`. | Read `docker compose config --format json` instead of raw YAML, or add a loader for `!reset` and `!override`. Add the host-level flows (NTP, backup share). Test with every overlay. | new | no |
| OPS-015 | Medium | `check_host.sh` is weaker than it reads. The LUKS check passes when any dm-crypt device exists, not when Docker's data root is on it. It has no check for free disk, the two cron files, the host time zone, the certificate or a host firewall. It always fails on WSL2. | `deploy/check_host.sh:25-29,65-67`; by a run here: `FAIL LUKS`, `WARN clock not NTP-synchronised`. | Resolve `docker info` `DockerRootDir` and the backup staging folder to their block device and require dm-crypt under them. Add the missing checks. Modes `--wsl2` and `--platform`. | card T-210 covers `--wsl2`; T-211 covers NTP as FAIL; the rest new | no |
| OPS-016 | Low | `doctor` prints a Python traceback when the settings file is missing, and reads the model pins from the repository root, not from the deploy folder it was given. | By a run: `FileNotFoundError` from `tools/trialbox/doctor.py:313`; `registry_pins ... no override at <repo>/deploy/site/registry.site.yaml` with `--env-file` elsewhere. | A FAIL line instead; derive the site folder from `--env-file`. | new | no |
| OPS-017 | Medium | The release bundle for a hospital contains the test mail servers. MailHog alone has 1,590 fixable findings. A hospital scan of the media or of `docker images` will list them. | `tools/make_bundle.sh:41-44` (`-f docker-compose.test.yml --profile test`); `deploy/security/known-image-findings.md` (mailhog row). | The release bundle takes the `gpu` and `stub` profiles only; `--with-test` for the acceptance box. | new | no |
| OPS-018 | High | A gated release bundle cannot be built today. Every third-party image is in report mode, and a bundle "never carries an image that passed only in report mode". Without `--gates` there is only a warning. So no real signed bundle exists and the install has never run from one on a GPU box. | `docs/SECURITY.md:215-220`; `tools/make_bundle.sh:51-60`; RUNBOOK:602 ("has not been started on a box yet"). | Close PR #78, then make `--gates` mandatory. First real bundle is an acceptance criterion of T-213. | registered CR-045, CR-046, CR-071; in PR #78 | no |
| OPS-019 | Medium | The Spark profile serves the models from a community-built vLLM image in a personal registry namespace. It is digest-pinned, but nobody owns its patches, licence review or rebuild. The x86 profiles use the official image by tag only. | `deploy/docker-compose.gb10.yml:38,61`; `deploy/docker-compose.yml:257`; `docker-compose.rtxpro6000.yml:31`. | Build the arm64 vLLM image in our own pipeline (or mirror it with an SBOM and a rebuild recipe). Pin the x86 image by digest. A decision record names the owner. | tag pin: registered CR-044; Spark image provenance new | no |

### 2.3 Update and rollback

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| OPS-020 | High | Master's update has no anti-rollback, key id, expiry, crash marker or free-space check. PR #83 adds all of them. Still missing after #83: the host tree (OPS-010), the platform form (OPS-052), and OPS-021 to OPS-024. | `tools/verify_update.py`; PR #83 `docs/decisions/D-210-update-safety.md`. By a run on master: a good bundle verifies, a tampered payload and a wrong key are refused, nothing is left in the stage folder. | Merge #83 after its review. Add the items below to T-111. | registered CR-047; in PR #83 | no |
| OPS-021 | Medium | The rollback point covers the two databases, the images and the models. It does not cover `lake-data` (Parquet, DuckDB), `objects-data`, `console-data` (the TOTP key) or the audit volume. A release that rewrites lake files is not undone by a rollback; old code then reads new files. | `tools/trialbox/update.py:427-433,472-480`. PR #83 adds the rulesets tag only. | A lake schema version that old code checks and refuses; keep the previous snapshot folder until the update is confirmed; one drill case "lake format change, then rollback". | new | no |
| OPS-022 | Medium | The update stops the services without asking whether a job is running or whether it is inside the night window. A screening run in flight is killed. | `tools/trialbox/update.py:377` (`stop PY_SERVICES`); no job query in the file. | Preflight refuses while a job is `running` or between the first night job and 07:30 site time, unless `--force REASON` (audited). | new | no |
| OPS-023 | Medium | The vendor signing key is written as an unencrypted PEM file. There is no custody procedure: who holds it, where, how a release is signed by two people, what to do when it leaks. PR #83 adds rotation, not custody. | `tools/sign_bundle.py:35` (`NoEncryption()`); RUNBOOK and SECURITY name only the public key. | Keep the key on a hardware token or encrypted with a passphrase held by a second person. A one-page key ceremony and a compromise drill (rotation bundle applied on the acceptance box). | new | no |
| OPS-024 | High | Host patching has no design. The bundle updates containers only. "Driver updates are outside the bundle." The pack promises a monthly offline Windows bundle and a Linux update "by the same signed release"; neither exists. An air-gapped Ubuntu or WSL2 host will be months behind at the first hospital scan. | `docs/RUNBOOK.md:200`; `docs/plan/sites/it-security-pack.md:23`; `OFFLINE-MEDIA.md` (`linux/debs/` for install only). | A patch policy (who, cadence, window). A payload kind `ospatch`: a dated offline apt snapshot applied by `apply_update.sh` with a reboot plan and the canary after. Try it on the rental box. | new | no |
| OPS-025 | Medium | Staging goes to `/tmp` by default (a 40 GB bundle). | `tools/apply_update.sh:40`. | In PR #83 (free-space preflight, staging under `deploy/updates/stage/`). | registered CR-047; in PR #83 | no |
| OPS-026 | Medium | No staged roll-out procedure is written (acceptance box, then Japan, then CGMH, three working days apart), and no rule says who may apply an update on site with no remote access. | Plan WS-12.7 (not started); RUNBOOK §5 has none. | Add to RUNBOOK §5 with a sign-off line per stage. | card T-215 covers (change classes); procedure text new | no |

### 2.4 Monitoring and alerting

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| OPS-027 | High | Nothing on the box tells a person that it is unhealthy, except the backup age. There is no `/metrics`, no daily health mail, no disk, GPU, canary or certificate alert. | By a run: `GET /metrics` → 404. grep: `/healthz` on each service only; `TB_BACKUP_ALERT_CMD` is the only alert hook (`tools/trialbox/backup_schedule.py:37-38`). | T-209. Before it lands, a small `trialbox health --mail`: one PHI-free mail a day through the mail gateway to `site.contact` (last ingest, canary, backup age, disk, certificate days, egress table loaded). Put one health line in the 07:00 mail so a missing or red line is seen by the CRC. | card T-209 covers | no |
| OPS-028 | High | The one alert that exists goes nowhere by default. Cron mails `root` on a box with no local mail transfer agent, and install sets neither `MAILTO` nor `TB_BACKUP_ALERT_CMD`. | `deploy/backup/trialbox-backup.cron:7`; `deploy/install.sh` (no line for either). By a run: `backup-status` prints `backup ALERT` and exits 1 only. | The wizard asks for the alert address; `backup-status` sends through the mail gateway; `doctor` FAILs in PRODUCTION when no alert route is set. | new (cron itself: registered CR-058) | no |
| OPS-029 | Medium | An unhealthy container is not restarted. `restart: unless-stopped` acts on exit, not on a failed health check. A hung vLLM stays "up" and screening waits. | `deploy/docker-compose.yml:21,270` and the health checks; Docker's restart rule. | A small watchdog (systemd timer: restart a service unhealthy for N minutes, audit it), or an autoheal sidecar. The "hung vLLM" drill of T-213 proves it. | card T-213 covers the drill; the watchdog new | no |
| OPS-030 | Medium | Certificate expiry is checked only when a person runs `check-tls`. | `services/console/identity.py:159-163`; RUNBOOK:531-535. | Daily in the health check; red at 30 days. | new | no |
| OPS-031 | Medium | Disk is watched only by the backup preflight and the lake spill cap. Nothing watches Docker's root, WAL growth or the backup share's fill. | `tools/trialbox/backup_schedule.py:382`; `services/lake/store.py:205`. | In T-209: per-volume thresholds (70 % warn, 85 % red) and a forecast line. | card T-209 covers | no |
| OPS-032 | Medium | A failed canary is visible only in the audit log and on an admin tile. No document says who is told that note criteria are switched off for the night. | `docs/RUNBOOK.md:72,179`. | The morning mail says in one line "note reading was off last night" when `selftest.failed` is the last event. | new | no |
| OPS-033 | Low | `make selftest` uses the base compose file only and needs `make` on the box. | `Makefile:241-242`; RUNBOOK:392. | A `trialbox selftest` host command that uses `COMPOSE_FILE` from `deploy/.env`. | new | no |

### 2.5 Logs

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| OPS-034 | Medium | Service logs can have gaps. Each container keeps 5 × 50 MB; the collector copies yesterday's lines once a night. The gateway and the orchestrator log one line per request; a 50,000-patient night writes more than 250 MB, so the oldest lines are rotated away before 00:20. The compose comment also says 180 days where the RUNBOOK says 365. | `deploy/docker-compose.yml:9-11`; `libs/tb_common/http.py:94-110`; `tools/trialbox/logs.py:8-10`. By reading, not measured. | Measure lines per night in the G1 run. Then raise the cap, or collect hourly, or use the `local` driver with a larger budget. A test: the collected day has no gap after a full SCREEN. | new | no |
| OPS-035 | Medium | The collector takes every compose service, so PostgreSQL and HAPI logs (not scrubbed; a failed statement is logged with its values) are kept 365 days beside the scrubbed ones and would be forwarded with them. The scrubber's chart-number rule is also never switched on. | `tools/trialbox/logs.py:8` ("every compose service"); register §6 PV-10. | Collect third-party logs into a separate class marked D3, never forwarded and never in a support bundle; set `log_min_error_statement=panic` or `log_parameter_max_length_on_error=0` for the `db`. | scrubber: registered (PV-10, Medium list); the third-party logs new | no |
| OPS-036 | Low | The log day is a UTC day while the cron runs in host local time. | `tools/trialbox/logs.py:93,185`. | Use the site day. | registered (DI-14, Medium list) | no |
| OPS-037 | Low | `/var/log/trialbox-retention.log` and `/var/log/trialbox-backup.log` have no rotation. | `install.sh:289`; `trialbox-backup.cron:9`. | A `logrotate.d` file from the installer. | new | no |

### 2.6 Support, remote access, incidents

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| OPS-038 | High | There is no support model. RUNBOOK §7 is four lines. No tiers, hours, named people, ticket channel, severity table, hardware return path or first-month on-call list. The two sites are one hour apart (JST, TST) and both expect a morning mail at 07:00 local. | `docs/RUNBOOK.md:303-308`; plan WS-15.5, WS-17.4 (not started). | Proposed in §5 (card T-404): tier 1 the site administrator, tier 2 one named Aimedics person per country with a backup, tier 3 engineering; cover 07:30 to 18:00 in both zones (08:30 to 19:00 JST from Taiwan); severity 1 answer in 1 hour, on site next working day. | registered CR-096 | no |
| OPS-039 | High | Remote access is promised as "none", with no fallback written. With a team of a few people in two countries, each incident then needs travel or hospital IT at the keyboard, and the pack's RTO of 4 hours cannot hold. The survey asks the hospital's policy (question 63) but TrialBox has no procedure for a supervised screen share: who approves, what may be on screen, how it is logged. | `docs/plan/sites/it-security-pack.md:40,78,87`; `site-survey.md` question 63. | Decide (owner question 2). Recommended: no standing access; a hospital-started, hospital-watched screen share for the administrator role only (which sees no patient data after T-102), opened by a ticket number, recorded in the audit as `support.session` with start, end and the hospital person. | new | no |
| OPS-040 | High | The hospital IT pack states controls that are not built. See §2.12 for the list (about twenty). Hospital IT is not engaged yet, so the pack as written would become a set of commitments. | `docs/plan/sites/it-security-pack.md` §A.3 to §A.8a against the code (§2.12). | Mark each line "today" or "at IQ" with its card. A doc-lint rule: each control line in the pack names a test id or a card. | new (CR-090 covers the zh-TW wording only) | no |
| OPS-041 | High | There is no incident plan. The RUNBOOK has one bullet ("stop mail"). Missing: severity scale, roles on both sides, containment steps per case, the first-hour evidence list, the notification clocks (plan §9.3: APPI 速報 3 to 5 days and 確報 30 or 60 days; Taiwan 72 hours; 資安法 1 hour for a designated agency), the vendor-to-hospital clock, templates in ja and zh-TW, a tabletop. | `docs/RUNBOOK.md:307-308`; plan WS-13.5 (line 299), line 854. | T-318 with the cases of §5 card T-404: privacy breach, stolen or lost box, compromised account, model misbehaviour, data corruption, platform incident on the shared host. Vendor tells the hospital within 24 hours of knowing. | registered CR-096; card T-318 covers | no |
| OPS-042 | High | Model misbehaviour has no operator procedure. Nothing says how to switch note reading off in one step, how to list the runs and patients a given model build touched, and who re-reviews them. | RUNBOOK has no such section; the canary gate (`RUNBOOK.md:390-392`) only blocks the next night. | A `trialbox model hold` command (sets the flag that makes note answers "review, never match-against"), a report "runs by build sha between two dates", and a RUNBOOK page. Acceptance: after `hold`, a SCREEN uses no note answer; `release` needs a passed canary. | new | no |
| OPS-043 | High | A stolen Linux box unlocks itself. The documented setup binds LUKS to the TPM with PCR 7 and no PIN, so the whole machine boots to a running stack anywhere. Sealing the two site keys with the TPM is a manual, optional step the installer does not do. WSL2 has no check at all. | `docs/SECURITY.md:17-25,110-116`; `deploy/check_host.sh:31` (TPM is a WARN). | TPM plus PIN, or network-bound unlock (a Tang server on the hospital network) so the disk opens only in the hospital. The installer seals the site keys and `check_host` FAILs when they are plain files in PRODUCTION. | WSL2: registered CR-041, card T-210; the Linux auto-unlock new | no |
| OPS-044 | Medium | There is no "box lost" list of what to revoke outside the box: the AD bind account, the SMTP and IMAP passwords, the REDCap API tokens, the OIDC client secret, the backup public key pair, the staff TOTP secrets. | SECURITY §4 lists where secrets are, not what to do on loss. | A table in the incident plan: secret, where it is changed, who does it, within how long. | new | no |

### 2.7 Disaster recovery

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| OPS-045 | High | RPO 24 hours and RTO 4 hours are written for hospital IT as "measured in the restore drill". No such measurement exists. The drill runs in process on a small synthetic set. A real restore needs a reinstall, a 40 GB bundle, the person with the key envelope and the reference packs. There is no spare hardware plan: Japan has one box, and a replacement GPU takes weeks. | `docs/plan/sites/it-security-pack.md:78`; `tools/backup_drill.py` (in-process box); `RUNBOOK.md:260-268`. | Measure on the rental box with the 50,000-patient set and write the numbers. State two RTOs: software fault on the same hardware, and hardware loss with a loaner (owner question 5). Put the quarterly drill in the site calendar. | new (restore defects: registered CR-056, CR-057, CR-058) | no |
| OPS-046 | Medium | A backup file does not hold what a rebuild needs besides data: `deploy/.env`, `settings.yaml`, the model pins, the pgBackRest cipher, the site mapping, and the volumes `traces-data`, `authelia-data` and `caddy-data`. | `tools/trialbox/update.py:394-403` (the volume list); register §6 DI-12. | An encrypted "host bundle" inside each `.tbbak`; add the three volumes or say in writing why not (Caddy's CA: a new root must be pushed to the PCs). | registered (DI-12, Medium list); the three volumes new | no |
| OPS-047 | Medium | The backup private key is one USB stick in one envelope. No second copy is asked for, and no schedule proves that the key still reads the backups. | `docs/RUNBOOK.md:203-205,233-234`. | Two envelopes in two offices. `backup-verify` each quarter writes `backup.verified` to the audit; the health check is red after 100 days without one. | new | no |
| OPS-048 | Medium | Point-in-time restore is optional and a five-step manual set-up. Without it a signed EDC value, an SAE entry or a mark made after the nightly backup is lost with the disk. | `docs/RUNBOOK.md:236-258`; compose `archive_mode` default `off`. | In PRODUCTION with an off-box share, the installer sets it up and `doctor` warns when it is off. RPO then is the archive timeout (5 minutes). | new | no |

### 2.8 Hospital network, identity, hardening

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| OPS-049 | High | Egress is open after a reboot until someone runs `network.sh apply`. The comment in `network.sh` points to a systemd unit "in docs/RUNBOOK.md" that is not there. | `deploy/network.sh:7-8`; `deploy/install.sh:284-286`; RUNBOOK has no unit (SECURITY.md:45-46 has one sentence). | T-108 (a unit the installer enables; re-apply after every `up`). | registered CR-043; card T-108 covers | no |
| OPS-050 | Blocker | Shared B200 at CGMH. See §2.10. | | | registered CR-084; in PR #85 | no |
| OPS-051 | High | Sign-in with the hospital directory has never run. "The whole stack with Authelia has not been started on a box yet." The lead time for a DNS name, a certificate, a bind account and LDAPS is 2 to 6 weeks, and hospital IT is not engaged. Many clinic PCs cannot run an authenticator app, and personal phones may be banned (survey question 64). | `docs/RUNBOOK.md:524-527,600-603`. | Run it on the acceptance box against a test directory (T-213). Ask both sites question 57, 58 and 64 now. Offer hardware TOTP tokens as the default second factor. | card T-213 covers the run; schedule risk registered CR-090 | no |
| OPS-052 | Medium | The host has no firewall baseline. The egress table filters forwarded container traffic only. Nothing sets an input policy, SSH settings or the bind address of 443 (`0.0.0.0` by default). The pack promises a CIS benchmark output. | `deploy/egress.py:215-216` (forward hook); `deploy/docker-compose.identity.yml:36`. | `deploy/hardening/`: an nftables input policy (443 from the clinic ranges, SSH from the IT range or off), `sshd` settings, and the checks in `check_host`. | new | no |
| OPS-053 | Medium | Antivirus and EDR coexistence is not defined. The pack promises "a documented WSL2 exclusion list"; none exists. An EDR agent with cloud telemetry on the host conflicts with "nothing leaves". Scanning Docker's storage or the WSL2 disk file slows DuckDB and Postgres badly. | `it-security-pack.md:23`; grep for an exclusion list: none. | Write the list (Docker root, the WSL2 `.vhdx`, the model folder), test with Microsoft Defender on the rental box, and state the telemetry point in the responsibility sheet. | new | no |
| OPS-054 | Medium | Nothing prepares the site for its own vulnerability scan (survey question 66): expected findings, credentialed or not, the third-party images with 24 to 30 fixable findings each. | `deploy/security/known-image-findings.md`. | An "expected findings" sheet per release from the Trivy records; a dry scan of the acceptance box before G2. | new (images: in PR #78) | no |
| OPS-055 | Medium | Time. NTP out of sync is a WARN. TOTP accepts one step of drift, so a clock 60 seconds off locks every person out, and SAE clocks and audit times go wrong. WSL2 clocks drift after host sleep. | `deploy/check_host.sh:65-67`; SECURITY.md:73 ("one step of drift"). | T-211 (FAIL, refuse jobs over 60 seconds). Add: the sign-in page says "the box clock is off" to an administrator; a WSL2 time-sync task. | card T-211 covers | no |
| OPS-056 | Medium | Host time zone is never checked. The cron jobs (00:20, 04:45) run in host local time, the containers run in UTC, the application uses `site.tz`. A host left on UTC runs the backup at 13:45 in Japan. HAPI falls back to `Asia/Taipei` when `TB_TZ` is missing, also on a Japan box. | `deploy/backup/trialbox-backup.cron:4`; `deploy/docker-compose.yml:96`. | `check_host` compares the host zone with `TB_TZ`; compose uses `${TB_TZ:?}`. | new | no |
| OPS-057 | Medium | Secrets reach every container through `env_file: [.env]` and are blanked per service by a deny list. A new secret in `.env` (a model-server key, an OIDC value, a REDCap token) is visible to all nine services until someone adds a blank line. | `deploy/docker-compose.yml:19`; `deploy/docker-compose.secrets.yml:10-13,18-30`. | Per-service env files or compose secrets for every secret; a test that renders the config and fails when a name matching `PASS|KEY|TOKEN|SECRET` is non-empty in a service that is not on its allow list. | card T-212 covers three passwords; the test new | no |
| OPS-058 | Medium | Key rotation is documented for service tokens and database passwords only. No procedure exists for `pid_map.key`, `totp.key`, the backup key pair, the pgBackRest cipher, Caddy's internal CA, the Authelia secrets, the OIDC client secret, or the statement that `site_hmac.key` is never rotated. | `docs/RUNBOOK.md:271-284`; SECURITY §4. | A key inventory table: key, holder, rotation rule, what breaks, compromise action. Code for the two that need it (`pid_map.key` re-encrypt; backup re-key). | new | no |
| OPS-059 | Medium | Leavers. With local accounts a person keeps access until the monthly delegation-log comparison. No end date is required, and no report lists unused accounts. | `it-security-pack.md:86`. | An end date is required for a local account (at most 12 months); a weekly PHI-free mail to the administrator lists accounts unused for 60 days and ending in 14. | new (OIDC session life: registered CR-117) | no |
| OPS-060 | Low | The internal-CA TLS mode needs the root on every clinic PC by group policy and does not work on personal devices. | `docs/RUNBOOK.md:538-541`. | Make the hospital certificate the first choice in the survey and the wizard. | new | no |

### 2.9 Hosting forms: appliance

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| OPS-061 | Blocker | Windows with WSL2 has no data-at-rest checks (BitLocker, swap, hibernation), and the keys are plain files. Add to the card: Windows Update restarts at night, WSL2 stops when nobody is signed in, clock drift, the disk file that only grows. | `deploy/windows/preflight.ps1` (six checks: build, virtualisation, WSL2, driver, disk, memory). | T-210, plus a restart policy and a start-at-boot task in its acceptance list. | registered CR-041; card T-210 covers | no |
| OPS-062 | High | Three documents name three host systems for the same appliance. RUNBOOK §1 and SECURITY §1: Ubuntu 24.04 on LUKS2 with a TPM. The IT pack and the install checklist: Windows 11 with WSL2 and BitLocker. The Spark: its own Linux. `check_host` can pass only on bare Linux. The Japan hardware order is due at G2 (01-08). | `docs/RUNBOOK.md:39`; `docs/SECURITY.md:15,29`; `it-security-pack.md:22`; `WINDOWS-INSTALL-CHECKLIST.md`. | Decide now (owner question 1). Recommended: bare Ubuntu LTS (or the Spark's own Linux) for the pilot; Windows only when a hospital demands it in writing. This removes half of T-210 and OPS-053's worst case. | new | no |
| OPS-063 | High | DGX Spark. The profile is not measured. The driver is held at exactly 580.142 because later builds break vLLM, so driver security fixes are blocked. Unified memory (128 GB) is shared by the models, Postgres, HAPI and DuckDB with no container limits. The two-device form of the plan (Spark plus a CPU box, encrypted link) has no compose split. The model server image is OPS-019. | `deploy/docker-compose.gb10.yml:13-25`; `docs/RUNBOOK.md:323-326`; plan WS-14.9. | T-214. Add: a dated decision on the driver hold (who re-tests each new driver, how often), memory limits per service, and the benchmark's pass line for a back-fill night. | card T-214 covers; limits registered CR-082 | no |
| OPS-064 | Medium | RTX 5090 tier. Not measured on a real card. After a host restart the stack does not come back in the right order by itself ("run compose up again"); the sleep and wake helpers never restart. Neither pilot site uses this tier. | `docs/RUNBOOK.md:394-396`; `deploy/docker-compose.rtx5090.yml:105,131,141`. | State in the tier table that `small` is not offered for the pilot. Power-cycle test of T-108 covers the restart when it is offered. | card T-108 covers the restart | no |
| OPS-065 | Medium | RTX PRO 6000 is the only measured profile, and it was measured on a cloud VM, not on a workstation in WSL2 or on hospital hardware. vLLM runs with `ipc: host`. | `deploy/measured/README.md`; rendered config (`rendered.rtxpro6000.yml:743,793`). | Capture the serving record again on the rental workstation; measure `shm_size` in G1 and drop `ipc: host` (plan WS-14.3). | registered CR-071; card T-213 covers | no |

### 2.10 Hosting forms: CGMH's shared B200 (OPS-050)

OPS-050 is CR-084 and PR #85 is the code answer. PR #85 is a sound start: one allowlist rendered as nftables and as
NetworkPolicy, a `doctor --platform` job that writes IQ evidence, serving values that refuse to start until measured.
What is still open, as separate findings:

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| OPS-066 | High | The platform kind at CGMH is unknown: Kubernetes, plain Docker, Slurm or a vendor scheduler. PR #85 builds Kubernetes manifests and a compose form. A Slurm or batch-only B200 cannot hold long-running services, and neither form fits. Survey question 51 has no answer. | PR #85 `docs/RUNBOOK.md` §14; `site-survey.md` question 51; status §5 item 3. | Ask three things this week, before more platform code: which platform, who is root, which storage. Owner question 4. | new | no |
| OPS-067 | High | The quota must be two MIG instances, not "a dedicated MIG partition". In Kubernetes one GPU device goes to one container; the judge and the verifier each need one. The plan, the pack and the survey still say one. | PR #85 `D-211` ("two MIG instances ... plan change requested"); `it-security-pack.md:24,64`. | Change the three documents and the request to CGMH. Record the two profiles (memory each) from the qualification run. | in PR #85 (documents not yet changed) | no |
| OPS-068 | High | The platform form has no day-2 operation. No backup job, no restore, no log collection, no audit archive, no update or rollback, no secret rotation. The appliance does these with host cron and `docker compose exec`; none of that exists in a namespace. | PR #85 `D-211` "Not done here: ... the update path on the platform"; grep of `deploy/platform` for backup, CronJob, logs: none. | Card T-405 (§5): a backup CronJob to the hospital share with the same `.tbbak` format, a log and audit-archive CronJob, an update procedure (new image digests through the release component, a database dump first, rollback by the previous overlay), and a restore drill on the kind cluster. | new | no |
| OPS-069 | High | Where patient data lives on a shared host, and who can read it. Volumes are on the hospital's shared storage; the platform's administrators are root and can read volumes, pod memory and Kubernetes Secrets. PR #85 puts the database URL and the service tokens in Secrets. The key-encryption key is refused as a Secret, but its unseal path is not built, so today the site keys would be plain files on the shared volume. | PR #85 RUNBOOK §14 "Secrets" row; `it-security-pack.md:65-66`; cards T-210, T-319 (not started). | Build the unseal (T-210) before any real data. Until then the shared host holds synthetic data only. Name the root holders in the responsibility sheet. Ask for a storage class that is block storage (ReadWriteOnce) for Postgres: the PR asks for ReadWriteMany, and a database on a network file system is an integrity and speed risk. | card T-210, T-319 cover the key; storage class new | no |
| OPS-070 | Medium | Noisy neighbours. MIG separates GPU memory and compute. It does not separate CPU, host memory, storage or network. Changing the MIG layout needs the card idle. An error from another tenant can reset the card. Nobody is named to restart TrialBox's pods at 03:00. | `it-security-pack.md:64`; survey question 52, 72. | Requests and limits on every pod (in PR #85's quota check); the canary "with the other tenants running" is already in the pack: make it a number (night duration p95 over five nights). The first-call contact goes in the responsibility sheet. | in PR #85 (quota); measurement new | no |
| OPS-071 | Medium | The qualification on the owner's own B200 transfers to CGMH only when the MIG profiles, the driver and the vLLM build are the same. The serving record names the MIG profile; nothing compares driver and runtime. | PR #85 RUNBOOK §14 ("the record must name the MIG profile"). | Add driver, CUDA and vLLM image digest to the serving record and to `doctor --platform`'s comparison. | new | no |

### 2.11 Capacity, runbook, decommissioning

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| OPS-072 | Medium | There is no capacity model: patients per night per tier, disk growth per year, backup size. The tool the RUNBOOK names prints an old model set (a 120B model and a 35B model, not the deployed pair) and has no B200 or MIG row. The sites' volumes (survey question 25) are unknown. | By a run: `python -m tools.gpu_sizing` output; `docs/RUNBOOK.md:25`. | After G1: `tools/capacity.py` from the measured run (seconds and tokens per patient, GB per patient-year, backup size) with a table per tier and site; `doctor` warns when the forecast passes 70 % of disk or of the night window. | new (volumes: registered CR-088) | no |
| OPS-073 | Medium | The RUNBOOK is for site IT but half of it is developer content (§11 cloud runs, §13 parallel test runs, the CI tables in §3). | `docs/RUNBOOK.md:121-163,398-515,605-640`. | Split: RUNBOOK (site), DEVELOPING (team). | new | no |
| OPS-074 | Medium | The RUNBOOK has no page for: the morning mail did not arrive, disk full, GPU fault, planned power cut (the yearly electrical inspection in Japanese hospitals), certificate renewal, a leaver, moving the box to another address, replacing hardware. | Section list of `docs/RUNBOOK.md`. | One page each, and each is a drill in T-213 ("a drill whose recovery step is missing from RUNBOOK fails" is already its rule). | card T-213 covers the rule; pages new | no |
| OPS-075 | Medium | Decommissioning is promised (NIST 800-88 purge with a certificate) and not written. It must also cover what is off the box: 14 backups and the pgBackRest repository on the hospital share, the audit archive, USB disks, the model weights, and on the shared host the volumes on hospital storage. | `it-security-pack.md:57`; grep for "decommission" in `docs/RUNBOOK.md`, `tools/`: none. | `trialbox decommission --plan` lists every store from the settings (on and off the box). A procedure with crypto-erase (destroy the keys first), the purge, and a certificate template in three languages. | new | no |
| OPS-076 | Low | Shell lint could not be run here. CI lists ten warnings in `deploy/` and gates on errors only. | `docs/RUNBOOK.md:158`. | Triage the ten; gate on warnings for `deploy/*.sh` and `tools/apply_update.sh`. | new | no |

### 2.12 The IT pack against the code (OPS-040)

| Pack line | Today | Card |
| --- | --- | --- |
| §A.3 "DNS answers only the allowlist" | not built | T-212 |
| §A.3 NTP as a FAIL | WARN | T-211 |
| §A.4 "The administrator sees no patient data"; break-glass | in progress | T-102, T-309 |
| §A.5 BitLocker TPM+PIN, wrapped site keys, encrypted outputs | not built | T-210 |
| §A.5 opt-out "within minutes" from profiles and vectors | no worker | T-206 |
| §A.5 decommissioning with a certificate | not written | OPS-075 |
| §A.7 `release.json`, changelog in three languages, SBOM in the release | not built (report mode) | T-110 |
| §A.7 "an older release is refused" | in PR #83 | T-111 |
| §A.8 admin page with disk, GPU, timers; daily health mail; `/metrics`; syslog forwarder | not built | T-209 |
| §A.8 RPO 24 h, RTO 4 h "measured" | not measured | OPS-045 |
| §A.8 quarterly restore drill; PHI-free support bundle | not scheduled; not built | T-209, OPS-047 |
| §A.8a re-authentication before a reveal and an export | not built | T-205 |
| §A.8a 12 characters, breached list, history, forced change, per-IP delay | not built | T-109 rest |
| §A.8a audit chain's daily signed head on the hospital share | not built | T-211 |
| §A.2 monthly offline Windows bundle; EDR exclusion list | not built | OPS-024, OPS-053 |
| §A.6 key unseal by the steward; platform evidence at IQ | not built | T-210, T-319 |

Also: the ja and zh-TW parts are not the same as the English part. §B.2 and §C.2 still describe a PRO 6000 box with
256 GB and "a fixed GPU quota"; §A.2 says Spark or PRO 6000 and "a dedicated MIG partition, a time-slice is not
accepted". §B.8 and §C.8 have no RPO, RTO or syslog line (`it-security-pack.md:22-24` against `:132`, `:174`,
`:156`, `:198`). Fix: one table with three language columns, as the survey has. (Medium, new; counted in OPS-040.)

### 2.13 RUNBOOK procedures tried here

| Procedure | Result |
| --- | --- |
| 22 shell scripts, syntax | all parse |
| `docker compose config`: base; + secrets; + each GPU file; + identity; + test | render (rc 0) |
| `docker compose config`: base + poc alone | fails (`undefined network host-net`); works only with the test file, as `poc.sh` does |
| §1 step 3, wizard with the example answers | fails (OPS-012); works with a mapping that is in the image |
| `secrets init`, `secrets status` | work; no value printed; files 0600 |
| `doctor` | works; traceback on a missing settings file (OPS-016) |
| `backup-status` with no target, then an on-box target in PRODUCTION | red, exit 1, clear message |
| `check_host.sh` on a plain machine | FAIL lines as designed (LUKS, egress table, doctor) |
| `network_sheet` | works without the identity overlay; crashes with it (OPS-014) |
| `apply_update.sh --dry-run`: good, tampered, wrong key | accepted, refused, refused; stage folder removed |
| `tools.gpu_sizing` | runs; stale content (OPS-072) |
| `tools.demo` | fails at start (OPS-001) |
| `tools.role_demo` | serves in about 50 s; three languages; lock-out works (OPS-003) |
| `egress.py print` with no Docker daemon | traceback from `docker network ls` (expected without a stack; a plain message would be kinder) |

## 3. What is good (do not change)

* The update path verifies before it touches anything; a tampered bundle and a foreign key are refused cleanly (run).
* Backups are encrypted to a key the box does not hold; `backup-status` is strict about "off-box" and about age.
* `trialbox-net` and `model-net` are internal networks; only the gateway joins the model network.
* One token per service, a caller table, and `secrets status` that never prints a value.
* Tier install refuses a GPU profile without a measured serving record. No override. Keep it.
* The request log is our own JSON middleware; uvicorn's access log is off, so no query string reaches a log.
* PR #68's box rehearsal found real install faults (a 0600 settings file no service could read, a bundle with no
  third-party image, digest pins lost by `docker save`). This rehearsal is the right pattern; extend it, do not
  replace it.
* PR #85: serving values with no default, so a shared quota can never run on guessed numbers.
* The console's sign-in page: strict CSP, `no-store`, HttpOnly and SameSite cookies, `noindex`.

## 4. How to host the PoC for two remote clinicians

Goal: two clinicians (Japan, Taiwan) test synthetic screening flows in ja, zh-TW and en as PI, sub-investigator and
CRC. Synthetic and public data only. The rule "no cloud spending" bound this review, not the plan: option (a) asks
the owner to approve a small monthly cost.

| | (a) Demo image on a small cloud host | (b) Owner's own machine behind a tunnel | (c) A real box on the owner's B200, real models |
| --- | --- | --- | --- |
| What runs | `demo/Dockerfile` (one process, stub model), or the compose PoC (`deploy/poc.sh`) on a larger VM | the same, on the owner's PC | the installed stack with the judge and the verifier |
| Time to ready | 1 to 2 working days after OPS-001, 002, 004 are fixed (about one day of work) | 2 to 4 hours after the same fixes | 2 to 4 weeks: needs PR #68 merged, G1 passed, the first real install, and it competes with G1b on the same card |
| Cost per month | GCP `e2-standard-2` (8 GB) always on: about US$60; `e2-standard-4` (the existing demo VM size): about US$110; half that on a 12-hour schedule. Cloud Run, one instance kept warm, 1 vCPU and 2 GiB: about US$50 to 65. Render 2 GB plan: about US$25. Front door (Cloudflare Access, up to 50 users; or Google IAP): free. A domain name: about US$10 a year | none (electricity) | none in cloud; the B200's time |
| HTTPS | Cloud Run and Render give it; on a VM, Caddy (already in `hosted-demo-startup.sh`) with a real host name | the tunnel gives it (Cloudflare Tunnel) | the tunnel gives it; or Caddy from the identity overlay |
| Per-tester identity | front door by mail address, plus own console accounts (OPS-002) | the same | the same; here the real TOTP path can be used |
| Region and delay | GCP `asia-east1` (Taiwan) or `asia-northeast1` (Tokyo): either is a few tens of milliseconds from the other country. Render has Singapore only: still fine for a server-rendered console | depends on the owner's line | depends on the owner's line |
| Risk | low: no hospital network, no real data on it; the upload risk (OPS-004) is the main one | medium: it stops when the PC sleeps or the line drops; it exposes a personal machine; the testers see downtime | high: first install on real hardware in front of users; an on-premises GPU server reachable from the internet; any fault eats G1b time |
| What it proves | the console flows, the wording in three languages, the roles. Not the models, not the install | the same as (a) | everything in (a), plus real note reading, speed, and the install and identity path |
| What it does not prove | model quality: the stub's answers are fixed, so clinical feedback on note criteria is not valid | the same | hospital network, AD, real feeds |

Notes on (a):

* **Cloud Run with scale to zero is not suitable** today: each cold start reseeds for 30 to 70 seconds and wipes the
  testers' work (OPS-006). Use one warm instance or a VM.
* **Render's free plan is not suitable** (512 MB, sleeps; OPS-005).
* The demo image is the fast choice. The compose PoC on a 16 GB VM is closer to the product (real services, real
  account pages, a mail viewer) and costs about US$110 a month.

**Recommendation.** Two steps.

1. **PoC-1 now: option (a)** on the existing GCP project: one `e2-standard-2` or `-4` VM in `asia-east1`, the demo
   image built once and run by digest, Caddy with a real host name, Cloudflare Access (or IAP) limited to the two
   testers and the owner, six own accounts (PI, sub-investigator, CRC for each tester), `TB_POC_MODE` on, a daily
   snapshot of the data folder. Ask the owner for about US$60 to 110 a month for two months. Keep (b) as the same-day
   fallback for a first look.
2. **PoC-2 after G1 and PR #68: option (c)** for a fixed two-week window on the owner's B200 behind the same front
   door, still synthetic data, to get the clinicians' judgement of real note reading. Not before G1b is recorded.

PoC prerequisites found: OPS-001 (demo starts), OPS-002 (accounts), OPS-003 (front door), OPS-004 (upload guard and
banner), OPS-005 (memory), OPS-006 (keep data), OPS-007 (Secure cookie).

## 5. Proposed task cards for TB-PLAN-06

| Id | Goal | Files | Acceptance | Depends on | Size | PoC prerequisite |
| --- | --- | --- | --- | --- | --- | --- |
| T-401 (new) PoC hosting pack | A hosted PoC that starts from a clean build, with own accounts, a guard on uploads, kept data and a front door | `demo/Dockerfile`, `Makefile` (`demo-bundle`), `tools/demo.py`, `tools/role_demo.py`, `tools/feas_demo.py` (accounts), console upload routes (PoC guard, banner, i18n), new `deploy/gcp/poc-host.sh`, `demo/README.md`, `render.yaml`, a CI job | (1) CI builds the image from a fresh checkout and signs in as each seeded account; (2) a pasted note with a planted ID is refused in PoC mode; (3) data survives a container restart with `--keep`; (4) the URL without a front-door session never shows `/login`; (5) README states 2 GB | none | M | yes |
| T-402 (new) Host tree in the signed release | Compose files, host tools and configuration ship in the bundle and change by update | `tools/make_bundle.sh`, `tools/verify_update.py`, `tools/trialbox/update.py`, `deploy/install.sh`, `docs/handover/OFFLINE-MEDIA.md`, update drill | (1) drill: an update that changes a compose variable takes effect and rolls back; (2) a changed compose byte on the media is refused; (3) `/opt/trialbox/current` names the release | T-111 (PR #83), T-110 | M | no |
| T-403 (new) Site inputs and a finished install | Mapping folder and feed mount; installer ends with TLS on, cron files installed, the enrolment code printed; network sheet correct | `deploy/docker-compose.yml` (adapter mounts), `services/adapter/cli.py` (mapping lookup only), `tools/settings_wizard.py`, `deploy/install.sh`, `tools/network_sheet.py`, `tools/trialbox/doctor.py`, `tests/fixtures/onboarding/*`, PR #68's rehearsal | (1) the rehearsal installs with a mapping not in the image and ingests from a mounted feed folder; (2) the last line printed is an `https://` URL that answers; (3) the sheet lists 443 and every overlay renders; (4) every RUNBOOK §1 command runs in a test | PR #68, T-108 | M | no |
| T-108 (add) | Add: alert route required in PRODUCTION (OPS-028); unhealthy-service watchdog (OPS-029); host time zone check (OPS-056); log caps sized from G1 (OPS-034); `logrotate` file | as the card, plus `deploy/backup/*.cron`, `tools/trialbox/logs.py` | the card's list, plus: a stopped vLLM health endpoint leads to a restart and an audit line; a full SCREEN night leaves no log gap | as the card | L (unchanged) | no |
| T-111 (add) | Add to PR #83: job and night-window guard (OPS-022); lake format check on rollback (OPS-021); vendor key custody and a compromise drill (OPS-023) | `tools/trialbox/update.py`, `tools/sign_bundle.py`, RUNBOOK §5 | update refused while a job runs; rollback after a lake format change leaves a box that screens; a passphrase or token is needed to sign | PR #83 | S on top | no |
| T-209 (add) | Add: one health line in the morning mail and a daily health mail before the full metrics work (OPS-027, 032); certificate days (OPS-030); third-party logs kept apart (OPS-035); `backup.verified` age (OPS-047); unused-account report (OPS-059) | as the card | red health line when the canary failed, the backup is old, a disk is over 85 %, or the certificate ends within 30 days (frozen-clock tests) | as the card | L (unchanged) | no |
| T-404 (new) Operations documents | Support model, supervised remote session, incident plan with clocks and cases, DR with measured RPO and RTO, decommissioning, key inventory, patch policy, leaver and the missing RUNBOOK pages; RUNBOOK split | `docs/RUNBOOK.md`, new `docs/DEVELOPING.md`, `docs/plan/sites/` (incident plan, responsibility sheet draft, support sheet in ja and zh-TW), `docs/SECURITY.md` §4 | each page names its drill in T-213; the incident plan has the six cases of OPS-041 and a filled clock table; a tabletop record per site | owner answers 1, 2, 5, 6; T-318 (merge the incident part into it) | M, plus owner | no |
| T-405 (new) Platform day-2 | Backup, restore, logs, audit archive, update and rollback for the namespace form; block storage for the database; the platform questionnaire | `deploy/platform/` (CronJobs, an update overlay), `tools/trialbox/platform.py`, `tests/platform/`, RUNBOOK §14, `site-survey.md` (three questions), `it-security-pack.md` (two MIG instances) | on the kind cluster: a backup file appears on the share claim, a wipe and restore pass, an image-digest update and its rollback pass, `doctor --platform` fails when no backup job exists | PR #85, T-210 (keys) | L | no |
| T-406 (new) Pack truth table | Every control line in the IT pack marked today or at IQ with a test id or a card; three languages in one table | `docs/plan/sites/it-security-pack.md`, `tools/doclint.py` | doclint fails on a control line with neither; the ja and zh-TW columns have the same rows as en | none | S | no |
| T-407 (new) Capacity model | Patients per night, disk per patient-year and backup size per tier and site, from the G1 run | new `tools/capacity.py`, `tools/gpu_sizing.py` (retire or refresh), `doctor` (forecast warning), RUNBOOK §1 | the table for the 50,000-patient run equals the measured run within 15 %; a row for the B200 with two MIG instances | G1 (T-004), T-114 | S | no |
| T-408 (new) Host baseline | The decided host system hardened and checked: disk unlock that fails outside the hospital, sealed site keys at install, input firewall, SSH, offline OS patches | `deploy/hardening/`, `deploy/check_host.sh`, `deploy/install.sh`, `tools/apply_update.sh` (`ospatch`), SECURITY §1 | on the rental box: a moved disk or a box off the hospital network does not unlock; `check_host` FAILs on plain site keys; an OS patch bundle applies and the canary passes | owner answer 1; T-210 (shares the key code) | M | no |
| T-213 (add) | Add: the first real signed bundle installed from media; every RUNBOOK page as a drill; RPO and RTO measured with 50,000 patients; a Defender run with the exclusion list; a dry vulnerability scan | as the card | numbers written into the pack; each drill has its RUNBOOK page | as the card | L (unchanged) | no |
| T-214 (add) | Add: our own arm64 vLLM image or a mirrored one with an SBOM; a dated driver-hold decision; memory limits on the Spark | as the card | the Spark profile starts from an image our pipeline built | as the card | L (unchanged) | no |

## 6. Questions for the owner

1. **Which host system does the Japan appliance run?** Recommended: bare Ubuntu LTS (or the Spark's own Linux).
   Windows with WSL2 only if the hospital demands it in writing. It decides T-210, T-408 and the hardware order.
2. **Remote support: none, or a supervised session?** Recommended: no standing access; a hospital-started, watched
   screen share for the administrator role only, logged in the audit, once T-102 has removed patient data from that
   role.
3. **PoC hosting cost.** Recommended: approve about US$60 to 110 a month for two months for one small VM in
   `asia-east1`, with a free identity front door (§4).
4. **CGMH's platform.** Please ask now: Kubernetes, Docker or a batch scheduler; who is root; which storage class;
   and request two MIG instances, not one.
5. **Spare hardware for Japan.** Recommended: the acceptance box (or the Spark, if it is not chosen) is the loaner;
   state "hardware loss: 5 working days" beside "software fault: 4 hours" in the pack.
6. **Who is first line in each country, and who is the backup?** Two names per country are needed before the pack
   goes out.
7. **Is the repository public?** `hosted-demo-startup.sh` clones it without a credential. If it is public, the open
   security register is public too. Recommended: private, or keep the register outside the public tree.

## 7. Assumptions

* The Docker daemon cannot run in this session, so every statement about a compose box is by reading, or by the
  in-process tools. PR #68's rehearsal was read, not run.
* Prices are list prices from memory (US dollars, on-demand) and are indicative only.
* "RTX 5090 pair" in the brief means the model pair on one RTX 5090 (the `small` tier), not two cards.
* The owner's own B200 is a whole card he controls; its MIG layout can be set to match CGMH's.
* The notification clocks are quoted from the master plan §9.3; they need counsel's reading (CR-096).
* The log-gap estimate in OPS-034 assumes about 300 bytes per request line and about 20 gateway calls per patient; it
  must be measured in G1.
* Findings in other areas seen on the way (for example `pi` can open `/audit` in the role demo) are left to their
  reviewers.
