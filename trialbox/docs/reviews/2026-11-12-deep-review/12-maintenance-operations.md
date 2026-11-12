# 12. Maintenance and operations

| Field | Value |
| --- | --- |
| Document ID | TB-DR2-12 |
| Date | 2026-11-12 |
| Tree | `514ae9b` (the review branch, same tree as master) |
| Area | Day-2 operations and the software side of the install: install, update, backup and restore, monitoring, support, IT handover, secrets, TLS, time, patching, accounts, the runbooks |
| Not in this file | Hardware options, serving profiles, the physical installation (reviewer HW). Cited, not repeated. |
| Run | `bash -n` on all 48 tracked `*.sh` (all parse). `tools.backup_drill` (four attempts, not completed, see §10). `tools.trialbox backup-install` with the box plan's settings (exit 1, OPS-003). `tools.support_bundle` on a scratch deploy folder and `redact_secrets` on the installer's variable names (OPS-002). `tools.keys init` and `unseal` in a scratch folder (OPS-001). `deploy/hardening/apply.sh render` (OPS-005). `tb_common.metrics.evaluate` with no host facts (OPS-009). `tools.box detect`. `tools.network_sheet` for two file sets, diffed against `docs/handover/network-sheet.*` (equal). `tools.settings_wizard` with the rehearsal's answers. A script over every `docs/runbook/*.md` (paths, `make` targets, `python -m` modules, `trialbox` sub-commands). 177 unit tests (`test_backup_without_pause`, `test_backup_schedule`, `test_support_bundle`, `test_systemd_units`, `test_runbook_install_commands`, `test_network_sheet`, `test_box_plan`, `test_metrics`): all pass. A second batch of 192 (`test_host_tree`, `test_update_safety`, `test_egress_rules`, `test_watchdog`, `test_wsl2_hardening`, `test_install_tiers`, `test_site_key`, `test_sign_keys_kek`, `test_logs_third_party`, `tests/console/test_box_install_rehearsal.py`): all pass. |
| Read only | `deploy/install.sh`, `deploy/box-install.sh`, `deploy/check_host.sh`, `deploy/hardening/*`, `deploy/systemd/*`, `deploy/egress.py` (header), `tools/apply_update.sh`, `tools/trialbox/backup*.py` (parts), `tools/rehearse_box/*`, the compose files, the runbooks, `docs/handover/*`, `docs/plan/sites/*`, D-455, D-466, D-474. |
| Could not run | Anything that needs a Docker daemon (none here): `make rehearse-box`, `sudo make test-egress`, `make test-compose`, the installers end to end, `tools/update_drill.py` case 8. No `shellcheck` and no PowerShell on this machine: the `.ps1` files were read, not parsed. |

## 1. Reading in ten lines

1. The IT-managed install, the signed update, the backup and the restore are real code with real tests. The previous
   review's Blocker and High findings in this area are mostly fixed in code (§3): the host tree is in the signed
   bundle, egress is closed at boot, keys are sealed, a watchdog, a health mail and `/metrics` exist.
2. Plan v6.1 changed the product form on 2026-11-12: a dedicated box set up by its owner, not by hospital IT. The
   operations layer has not followed. T-729 landed the installer and the wizard; T-730 (the box looks after itself)
   and T-735 (documents for the owner) are not started. Every runbook, the IT pack, the offline media sheet and the
   CGMH tabletop still describe the older forms (Windows with WSL2, the shared B200, hospital IT at the keyboard).
3. The box installer cannot finish on a real machine as written: `install.sh` stops at the backup step in
   PRODUCTION because the box has no alert route (OPS-003, reproduced at the component). The test of the box installer
   replaces `install.sh` with a stand-in, and the rehearsal of the real installer is not in CI.
4. A box whose key-encryption key is sealed to its TPM (the default) has no second way to open its site keys. A
   dead mainboard makes every backup unusable for patient identity (OPS-001, reproduced).
5. The "secret-free" support bundle sends the database passwords of every service, the hospital's mail passwords
   and the KEK passphrase to the vendor (OPS-002, reproduced).
6. On a box without a mail relay, nothing tells a person that something is wrong: the morning mail, the health mail
   and the backup alert all need SMTP, and the optional Prometheus has no way to send an alert (OPS-008).
7. The host runner that writes the health facts is installed but not enabled, so disk, backup and certificate never
   turn red (OPS-009, reproduced). The health checks do not cover a failed night, the clock or the GPU (OPS-010).
8. RPO and RTO are still targets. No restore to a second machine has been done. 13 of the 14 drills the runbooks
   name as tests do not exist (OPS-012).
9. The deploy folder carries 17 compose files, three Kubernetes overlays, a Windows path and a two-device path.
   The two pilot sites need five compose files (§5).
10. `make backup-drill` did not complete here. Two causes are the product's (missing prerequisites of the target,
    OPS-014), one is this review machine's (§10).

## 2. What a person must type today

**IT-managed install** (RUNBOOK §1, `WINDOWS-INSTALL-CHECKLIST.md`), with the media in hand:

1. Install Ubuntu 24.04 on LUKS2, with Tang or a PIN for the unlock (hospital IT, by hand; `deploy/hardening/disk-unlock.sh`).
2. `sudo apt-get install ./linux/debs/*.deb` (Docker, compose, the NVIDIA toolkit, nftables, cron). No tool in the
   tree builds this folder (OPS-006).
3. Copy the release to `/opt/trialbox`; copy `vendor_ed25519.pub` to `deploy/keys/`.
4. Write `site.yaml` (41 answers) and the mapping folder; write `deploy/site/hardening.conf` (clinic ranges, SSH,
   KEK back end).
5. `sudo deploy/install.sh trialbox-<version>.tar --tier large --answers site.yaml`.
6. It stops at the backup step (OPS-004). Add `TB_BACKUP_ALERT_CMD` to `deploy/.env` by hand, run step 5 again.
7. `python3 -m tools.trialbox backup-keygen ...` with the key holder; run `backup-install` again.
8. `systemctl enable --now trialbox-ops.timer` (RUNBOOK §15; not done by the installer, OPS-009).
9. `sudo python3 -m tools.trialbox secrets rotate` at handover.

**Box install** (D-466): `sudo deploy/box-install.sh trialbox-<version>.tar`, answer one question, open
`https://<name>.local/login/first-run`, type the code, answer seven questions. This is the right shape. It needs steps
1 to 3 above first, and it stops at OPS-003 and OPS-005.

## 3. Status of the previous review's findings (`09-operations.md`, every Blocker and High)

Fixed = seen in code or a test on this tree. "By reading" where no run was possible.

| Old ID | Sev. | Status | Evidence |
| --- | --- | --- | --- |
| OPS-001 demo exits on a clean clone | Blocker | fixed (by reading) | `demo/Dockerfile:40-60` fetches the translator jar and writes `FHIRHelpers-4.0.1.cql`. The same gap is back in `make backup-drill` (new OPS-014). |
| OPS-002 no per-tester accounts | High | fixed (by reading) | `demo/README.md:18-56` (`TB_DEMO_ACCOUNTS`, per-tester passwords, expiry). |
| OPS-003 demo guarded by a password only; lock-out by a stranger | High | partly | TOTP is on with an accounts file (`demo/README.md:51`). The lock-out of a known user name by a stranger was not rechecked. |
| OPS-004 a tester can upload a real chart | High | open | no switch found: grep for an upload flag in `services/console`, `libs/tb_common/config.py` returns nothing. |
| OPS-010 host tree outside the signed bundle | High | fixed | `tools/host_tree.py`, payload kind `host`, `install.sh` re-executes from `current/` (`install.sh` step 2); `tests/unit/test_host_tree.py`. |
| OPS-011 no site mapping or feed mount | High | fixed | `install.sh` (`deploy/site/mapping`, `TB_SOURCE_DIR` required in PRODUCTION). |
| OPS-013 no clinic PC can use the box after install | High | fixed (by reading) | identity overlay added, `check-tls`, the enrolment code printed, the `https://` URL checked with curl (`install.sh` steps 4 to 6). |
| OPS-018 no gated bundle can be built | High | partly | `tools/make_bundle.sh:50` requires `--gates`; dated exceptions replaced report mode (`deploy/supply-chain-allowlist.yaml`). No real signed bundle exists in the tree's records and none has been installed on a GPU box. |
| OPS-020 update without anti-rollback, expiry, marker, free space | High | fixed | `tools/apply_update.sh` header and steps; `tests/unit/test_update_safety.py`. |
| OPS-024 host patching has no design | High | partly | `deploy/hardening/ospatch.py` and `apply_update.sh ospatch` exist. Nobody builds the monthly snapshot, and the policy names hospital IT, which the box form does not have (new OPS-016). |
| OPS-027 nothing tells a person the box is unhealthy | High | partly | `/metrics`, the health line, the daily health mail exist (`libs/tb_common/metrics.py`, `services/console/notify.py:279`). They need the ops timer and SMTP (new OPS-008, OPS-009, OPS-010). |
| OPS-028 the one alert goes nowhere | High | fixed for the IT form; open for the box | `backup_schedule.py:1076` refuses PRODUCTION without an alert route. That refusal is what stops the box install (new OPS-003). |
| OPS-038 no support model | High | partly | RUNBOOK §21, `support-sheet.md`. One person covers both countries, no backup is named, names are blank ("default until the owner answers"). |
| OPS-039 no fallback for "no remote access" | High | fixed on paper | RUNBOOK §21 "supervised remote session". The IT pack still says "no remote access" three times (`it-security-pack.md:40,79,117`). No `support.session` audit event. |
| OPS-040 the IT pack states unbuilt controls | High | partly | See OPS-011 below: four controls still stated and not built; the pack describes forms the plan dropped. |
| OPS-041 no incident plan | High | fixed on paper | `docs/plan/sites/incident-response.md` (three languages, clocks marked "counsel confirms"). Tabletop not held. |
| OPS-042 no procedure for model misbehaviour | High | fixed | RUNBOOK §19, flag `notes.reading`, `tests/unit/test_model_hold.py::test_runbook_19_model_hold`. The command as printed fails on the host (new OPS-019). |
| OPS-043 a stolen Linux box unlocks itself | High | fixed (by reading) | `deploy/hardening/luks_policy.py` FAILs a TPM-only unlock; keys sealed at install (`seal_keys.sh`). The fix created OPS-001 (no recovery copy) and blocks the box form (D-466 "Open": the box needs its own unlock rule). |
| OPS-045 RPO and RTO "measured" | High | partly | RUNBOOK §22 and the IT pack now say "not measured yet". Still not measured (T-213b). |
| OPS-049 egress open after a reboot | High | fixed (by reading) | `deploy/systemd/trialbox-egress.service` (`Before=docker.service`, `RequiredBy=docker.service`), `tests/unit/test_systemd_units.py` passes. Not seen on a real boot. |
| OPS-050 shared B200 at CGMH | Blocker | moot | v6.1 OD-11: both sites run a dedicated box. The CGMH tabletop record still says B200 (`tabletop-record-cgmh.md:10`). |
| OPS-051 sign-in with the hospital directory never ran | High | open | `trialbox-identity.yml` validates the Caddyfile and runs a smoke test with a stand-in console. No run against a real directory. |
| OPS-061 Windows and WSL2 without data-at-rest checks | Blocker | fixed, then moot | `deploy/windows/preflight.ps1` (BitLocker TPM+PIN, hibernation, swap). v6.1 §4.4: WSL2 is not the box's path. |
| OPS-062 three documents name three host systems | High | open | RUNBOOK §1: Ubuntu on LUKS. IT pack A.2 and the install checklist: Windows 11 with WSL2. v6.1: Linux on a workstation or a Spark. |
| OPS-063 DGX Spark not measured | High | open | `deploy/measured/` holds `serving_config.rtxpro6000.json` only; `--tier medium` refuses. See reviewer HW. |
| OPS-066 platform kind at CGMH unknown | High | moot | v6.1 §4.4. |
| OPS-067 two MIG instances | High | moot (wording fixed in the pack) | `it-security-pack.md` A.2, A.6. |
| OPS-068 platform form has no day-2 | High | fixed in code, frozen | `tools/trialbox/platform_day2.py`, RUNBOOK §26; not developed further (v6.1 §4.4). |
| OPS-069 patient data on a shared host | High | moot | v6.1 §4.4. |

Mediums spot-checked: OPS-022 (the update does not ask whether a job runs) open; OPS-023 (vendor signing key written
unencrypted, `tools/sign_bundle.py:44`) open; OPS-025 (staging in `/tmp`) open, with a free-space check now;
OPS-029 (watchdog) fixed; OPS-035 (third-party logs) fixed; OPS-037 (logrotate) fixed; OPS-055 (clock as FAIL)
fixed in `doctor`, still WARN in `check_host.sh:240`; OPS-057 (secrets by deny list) kept, now held by
`tests/unit/test_compose_secret_reach.py`; OPS-074 (missing pages) fixed; OPS-075 (decommissioning) fixed on paper.
Previous DATA-004 (a lost site key changes every pseudonym): fixed by `adapter.cli keys-init`
(`tests/unit/test_site_key.py`); the loss itself is now possible through the KEK (OPS-001).

## 4. Findings

| ID | Severity | Finding | Evidence | Impact | Fix | Card | Flag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| OPS-001 | Critical | The KEK sealed to the TPM has no recovery copy. `seal_keys.sh` with `KEK_BACKEND=tpm` (its default, the example conf's, and the box plan's when the board has a TPM) makes a random KEK, seals it with `systemd-creds --with-key=host+tpm2` and shreds the plain copy. The backup holds the wrapped keys and `kek.json`, not the KEK. | `deploy/hardening/seal_keys.sh:33,58-70`; `tools/box/plan.py:292`; by a run (§4.1): after `tools.keys init --backend file` and the removal of the KEK file, `unseal` answers `--from PATH is needed for the file back end`. RUNBOOK §22 "replacing hardware" step 3 says the new box unseals "from the stewards' shares or the passphrase": with this back end there are none. | A dead mainboard, a cleared TPM or a firmware reset: `pid_map.key` and `site_hmac.key` cannot be opened from any backup. Every pseudonym loses its chart number, re-ingest makes new pseudonyms, and marks, consent, EDC and SAE records no longer join to patients. | At seal time write a second copy of the KEK wrapped to the backup public key (or Shamir shares, or a printed recovery passphrase) and put it in the backup's `secrets` part. `doctor` FAILs a `file`/TPM KEK without one. Correct RUNBOOK §22 and §23. Drill: restore on a second machine with nothing from the first. | NEW-OPS-1 "A recovery copy of the TPM-sealed KEK" (M) | Go-live both |
| OPS-002 | Critical | The support bundle leaks secrets. Its redaction matches `PASSWORD`, `KEY`, `TOKEN` and similar words; it does not match `PASS`, `PW` or `PASSPHRASE`. | By a run (§4.2): `env.redacted` keeps `SMTP_PASS=hunter2secret`; `redact_secrets` keeps `TB_DB_PW_LAKE`, `TB_DB_PW_ORCHESTRATOR`, `TB_DB_PW_AUDIT_WRITER` (all eight `TB_DB_PW_*` that `install.sh` writes), `SMTP_PASS`, `IMAP_PASS`, `TB_KEK_PASSPHRASE`. `tools/support_bundle.py:69`. The same function redacts `cmd/compose-config.yaml`. The test uses `POSTGRES_PASSWORD` only (`tests/unit/test_support_bundle.py:52`). | The file RUNBOOK §21 tells the administrator to attach to a mail ticket carries the per-service database passwords, the hospital's mail account passwords and, on a passphrase box, the passphrase that opens the pid map. | Redact by allow-list: keep the value only for names declared non-secret in `tb_common.config`; everything else becomes `[redacted]`. At least add `PASS`, `PW`, `PHRASE` to the pattern today (§8). | NEW-OPS-2 "Support bundle: redact by allow-list" (S) | Go-live both |
| OPS-003 | Blocker | The box installer stops before the wizard. `box-install.sh` runs `install.sh` as root; `install.sh` defaults `TB_ENV=PRODUCTION` and dies when `backup-install` exits non-zero. The box plan sets `TB_BACKUP_MAILTO` and no `TB_BACKUP_ALERT_CMD`; a fresh Ubuntu has no `sendmail`; `backup-install` then exits 1. `box-install.sh` treats a stop before "TrialBox is running" as fatal. | By a run (§4.3): `backup-install` with `TB_ENV=PRODUCTION`, `TB_BACKUP_MAILTO=owner@box.invalid` prints "TB_BACKUP_MAILTO is set but this host has no mail transfer agent ... set TB_BACKUP_ALERT_CMD", exit 1. `deploy/install.sh` backup step (`[ "$rc" = 0 ] \|\| die "the backup schedule is not installed"`); `deploy/box-install.sh:99-102`; `tools/box/plan.py:329`. `tests/console/test_box_install_rehearsal.py:64` replaces `install.sh` (`TB_BOX_INSTALL`). The full installer needs Docker and was not run here. | The first install form of both sites cannot be installed by the script written for it. | With `TB_BOX=1` the backup step is a FAIL line, not a stop (the wizard and T-730 place the backup later). Run the real `box-install.sh` in the rehearsal container and put it in CI (OPS-004). | T-730 covers the alert path; NEW-OPS-3 "box-install runs the real install.sh in the rehearsal" (M) | Go-live both |
| OPS-004 | High | The real installer is not exercised anywhere, and by reading it cannot pass its own rehearsal. `make rehearse-box` is in no workflow. In the rehearsal container `install.sh` runs as root in PRODUCTION: (a) `seal_keys.sh` is given the Docker host's volume path, which is not in the container, and the default back end needs a TPM; (b) the answers file has no alert route, so the backup step stops (as OPS-003). The settings wizard has no question for the alert route, so the IT-managed install also stops there the first time. | `grep rehearse-box .github/workflows/*` = 0 hits; `tools/rehearse_box/box.sh:154-156` (no `TB_ENV`, no hardening conf, no alert variable); `tools/rehearse_box/site_answers.yaml`; by a run: the wizard's `.env` for these answers has no `TB_ENV`, `TB_BACKUP_*`. RUNBOOK §16 calls the rehearsal "the gate before a site's IQ". By reading; no Docker here. | Install defects reach the site visit. Two were found by reading in one afternoon. | Fix the two stops in the rehearsal (a passphrase KEK and an alert command in its site kit), run it nightly in `trialbox-e2e.yml`, add the box form as a second case. Ask the alert route in the wizard. | NEW-OPS-3 (same card) | Go-live both |
| OPS-005 | High | The address the box prints cannot be opened. The box's TLS name is `<name>.local`. Nothing installs or starts an mDNS responder, nothing sets the host name to the name the owner chose, and the input firewall the plan writes drops UDP 5353. The root certificate's download page is T-735 (not built), so every team PC also shows a certificate warning. | By a run: `deploy/hardening/apply.sh --conf <box-like conf> render` has `policy drop` and no rule for 5353; grep for `avahi`, `hostnamectl`, `5353` in `deploy/`, `tools/box/`, `libs/tb_common/box_answers.py`: none. `deploy/box-install.sh:123-124`; D-466 "What only a real box proves", third line. | The owner types the URL from the box's screen on a team computer and gets "site not found". The wizard is then reachable only at the box itself. | Decide the name: mDNS (install `avahi-daemon`, set the host name at apply, allow 5353 from the box's network) or the box's address in the URL with a certificate for the address. Print the address as well as the name. | T-735 (extend); NEW-OPS-4 "The box's name resolves" (S) | Go-live both |
| OPS-006 | High | "One installer for hardware the site bought" needs a prepared host that nothing prepares. `box-install.sh` dies without Docker; `install.sh` needs the NVIDIA driver and toolkit, nftables, cron, python3 with `cryptography`, a LUKS disk whose unlock passes `luks_policy.py`. `OFFLINE-MEDIA.md` lists `linux/debs/`, the drivers and WSL files, and says "the installer itself is built after the platform"; no script builds that media. D-466 leaves the box's disk-unlock rule open; `check_host.sh` FAILs a TPM-only unlock. | `deploy/box-install.sh:47-48`; `deploy/install.sh` step 1; `docs/handover/OFFLINE-MEDIA.md:5-7`; grep `debs` in `tools/`, `Makefile`: none; D-466 "Open", second item. | A box prepared by Aimedics works (Aimedics does it by hand each time). An owner with a new workstation cannot start. Each prepared box is hand-made and differs. | One media builder (`make media`): the debs for Ubuntu 24.04 by snapshot date with checksums, the driver, the bundle, the key, the sheets. `box-install.sh` installs the debs when Docker is missing. Decide the box's unlock rule (TPM with a PIN). Or state plainly that only prepared boxes ship for the two pilots, and drop the second form until then. | NEW-OPS-5 "Offline media builder and host preparation" (M) | Go-live both |
| OPS-007 | High | The box has no time source. The wizard asks no NTP server; the egress is closed and the hospital LAN has no internet, so `systemd-timesyncd` never syncs. `doctor` then FAILs `clock` in PRODUCTION, and the health mail does not carry the clock. TOTP accepts one 30-second step. | grep `-i ntp` in `libs/tb_common/box_answers.py`, `tools/box/plan.py`, `services/console/firstrun.py`, `tools/settings_wizard.py`: none; `tools/trialbox/doctor.py:841-863`; `libs/tb_common/metrics.py:241-262` (no clock check). | After some weeks of drift every sign-in code is refused and nobody can sign in; audit times and SAE clocks are wrong before that. | Ask for the hospital's time server in the wizard (IT's one page), write it to `timesyncd.conf` and `TB_NTP_SERVER`; add a `clock` check to the health facts (red over 20 s, before TOTP breaks). | T-735 (IT's one page); NEW-OPS-6 "Time source and a clock health check" (S) | Go-live both |
| OPS-008 | High | On a box without a mail relay no alert reaches a person. The morning mail, the daily health mail and the backup alert all go through SMTP; the box form installs with `smtp_host: ""`. The Prometheus overlay has rules and no Alertmanager, and listens on loopback. The message path to the owner is T-730, not started. | `tools/box/plan.py:353`; D-466 survey row "SMTP ... the box works without mail"; `deploy/docker-compose.monitoring.yml` (no alert target); `deploy/monitoring/rules.yml`; v6.1 §3 T-730 "a failed backup tells the owner". | A full disk, a failed backup, a failed night or an expiring certificate is seen only if someone opens the health page. On a site with no IT watching, that is nobody. | T-730, with a rule: a box is not in PRODUCTION until one message path is proven by a test message the owner confirms (mail relay, or a banner every user sees at sign-in when health is red). The banner needs no network and should come first. | T-730 (L); NEW-OPS-7 "Red health as a sign-in banner" (S) | Go-live both |
| OPS-009 | High | The host runner that writes the health facts and runs the Operations page's requests is installed and left off. Without it the health is WARN forever and never red. | `deploy/install.sh` systemd step: "trialbox-ops.timer is installed, not enabled"; RUNBOOK §15 "Turn the runner on once"; by a run: `metrics.evaluate(None, canary_ok, now)` gives level `warn`, "the host runner has not written the health facts". Neither `doctor` nor `check_host.sh` checks the timer. `box-install.sh` does not enable it. | Disk over 85 %, a backup older than 36 h and a certificate ending are never reported red in the mail or on `/metrics`. "Back up now" and "Apply this update" on the Operations page do nothing. A permanent WARN teaches people to ignore the line. | `install.sh` enables `trialbox-ops.timer` with the others; facts older than one hour are red, not warn; `doctor` FAILs when the timer is off. | NEW-OPS-8 "Enable the ops runner; stale facts are red" (S) | Go-live both |
| OPS-010 | High | The health checks miss the three things most likely to go wrong at night. They cover the canary, the backup, the backup verification, the opt-out worker, disks and the hospital certificate. They do not cover a failed or missing nightly job (ingest, micro-batch, retention), the clock, or the GPU (temperature, ECC and Xid errors, memory). The IT pack says the administrator page shows GPU, the last ingest and every timer's last run. | `libs/tb_common/metrics.py:241-262` (the whole list); grep `gpu\|nvidia` in `services/console/ops_pages.py`, `metrics_page.py`, `home.py`, `tools/trialbox/ops.py`, the admin templates: none; `it-security-pack.md:79`. | A feed that stopped arriving shows as an empty morning mail. A card that throws Xid errors is seen only when the canary fails. | Add checks: `night` (each scheduler job's last result and age against its schedule), `clock`, `gpu` (`nvidia-smi --query-gpu`, Xid count from the kernel log, written by the ops runner). | T-730; NEW-OPS-9 "Health checks: night, clock, GPU" (M) | Go-live both |
| OPS-011 | High | The handover documents describe another product. IT pack 0.2 (2026-11-09): Windows 11 with WSL2 as the appliance host, the B200 shared server for CGMH, hospital IT as the reader, "no remote access" (RUNBOOK §21 now has a supervised session). The CGMH tabletop record is written for the B200. The pack still states as fact: a syslog forwarder (no code: grep `syslog` over `services`, `libs`, `tools`, `deploy` = 0), GPU and timers on the administrator page (OPS-010), a changelog in three languages (`CHANGELOG.md` is 27 lines of English), a monthly offline Windows bundle. | `docs/plan/sites/it-security-pack.md:22-24,40,79,117`; `docs/plan/sites/tabletop-record-cgmh.md:10`; `docs/handover/WINDOWS-INSTALL-CHECKLIST.md`; v6.1 OD-11, OD-13, §4.4. | A hospital that receives the pack reads commitments the product does not keep, for a form it will not get. | T-735, with these added: rewrite the pack for the box (one page for IT: address, time server, data connection, firewall line, backup share); each control line names its test or says "not built"; move Windows, B200 and platform text to "other install forms". | T-735 (M, make it L) | Go-live both |
| OPS-012 | High | The recovery numbers and the drills are still paper. RUNBOOK §22: "No restore has been measured yet". 13 of the 14 drills the runbook pages cite by test name do not exist (`test_runbook_04_disk_full`, `_04_gpu_fault`, `_04_morning_mail_missing`, `_12_certificate_renewal`, `_20_decommission`, `_21_support_session`, `_22_moving_the_box`, `_22_power_cut`, `_22_replacing_hardware`, `_22_restore_timed`, `_23_lost_box`, `_24_patch_window`, `_25_leaver`); only `test_runbook_19_model_hold` exists. | By a run: a grep of each cited name under `tests/`; `docs/runbook/22-disaster-recovery-with-measured-rpo-and-rto.md:13-24`. | The first restore onto new hardware will happen during an outage, and OPS-001 says it will fail. | T-213b, re-scoped to the box (v6.1 §4.2), in this order: restore on a second machine, timed, with 50,000 patients; power cut; disk full; certificate renewal. Until a drill exists the page says "not drilled", without a test name. | T-213b (L) | Go-live both |
| OPS-013 | Medium | RUNBOOK §5 and the compose comment still tell the operator to build `deploy/pgbackrest/Dockerfile` and set `POSTGRES_IMAGE=trialbox-db-pitr:16` for point-in-time restore. That file builds from `postgres:16-alpine`. The box's database image is Debian with pgvector, PGroonga and pgBackRest 2.60 already in it. | `docs/runbook/05-updates-backup-restore-secrets.md` ("The default db image has no pgBackRest yet, so step 1 is still needed"); `deploy/pgbackrest/Dockerfile:6-8`; `deploy/docker/db.Dockerfile:21-56`; `deploy/images.lock` (`pgbackrest 2.60.0-1`); `deploy/docker-compose.yml:53`. | An operator who follows the page swaps the database image for one without the two extensions and with another C library (collation order of indexes). On an air-gapped box the build fails instead, and PITR stays off. | Delete `deploy/pgbackrest/Dockerfile`; rewrite the PITR part of §5 (steps 2 to 4 are done by `backup-install`). | NEW-OPS-10 "PITR page and the old Dockerfile" (S) | Go-live both |
| OPS-014 | Medium | `make backup-drill` fails on a clean clone, late and with errors about something else. The target has no prerequisite; `make test` has `$(FONTS) $(JVM_DEPS)`. | By a run: after 2 min, `FileNotFoundError: FHIRHelpers-4.0.1.cql not found`; with the jars given, after 3 min 20 s, `ReportError: font NotoSansJP-Regular.ttf not found`. `Makefile:214-215` against `Makefile:96`. | The drill RUNBOOK §5 and §22 lean on does not run for a person who follows the page. | `backup-drill: venv-check $(FONTS) $(JVM_DEPS)`; the same for any other target that runs `e2e_simple`. | NEW-OPS-11 (S) | PoC |
| OPS-015 | Medium | A box without a TPM seals its keys under a passphrase "typed after every restart". There is no page to type it on: the only way is `python3 -m tools.keys unseal` in a shell, or the passphrase in `deploy/.env` (which defeats it). | grep `unseal` in `services/console/`: none; `tools/box/plan.py` warning text; `deploy/box-install.sh:136-146`. Whether the DGX Spark has a usable TPM: reviewer HW. | After a power cut the ingest refuses the night and reveals fail until a person with a shell comes. | A locked-box page on the console (the owner types the passphrase; the console hands it to a host unit through the first-run style tmpfs folder). Or refuse to install a production box without a TPM. | T-730; NEW-OPS-12 (M) | Go-live JP |
| OPS-016 | Medium | OS patching has a tool and no owner. RUNBOOK §24 gives the host to hospital IT; the box form has no IT. `ospatch.py make --debs DIR` needs someone to collect the month's packages; no job does. The update itself is manual from USB; "applied in a quiet hour" is T-730. The update still does not ask whether a job runs (old OPS-022). | `docs/runbook/24-patch-policy.md:16-24`; `deploy/hardening/ospatch.py:8-11`; grep for a running-job check in `tools/trialbox/update.py`: none. | An air-gapped Ubuntu with Docker and an NVIDIA driver goes unpatched from install day. | One monthly job on the vendor side builds the OS snapshot bundle with the release; the owner's handbook says who applies it. Preflight of the update refuses while a job is `running`. | T-730; NEW-OPS-13 "Monthly OS snapshot bundle" (M) | Later (first month after go-live) |
| OPS-017 | Medium | Too many install forms for two sites. 17 compose files (12 in `deploy/`, plus platform, two-device ×2, `topology_a/podman-compose.yml` which nothing references, and shared-quota), three Kubernetes overlays with 33 files and about 2,400 lines, `deploy/windows` and `deploy/gcp` with about 3,200 lines. Each is kept in CI or in the documents. | `ls deploy`; grep `topology_a\|podman-compose` outside its folder: none; v6.1 §4.4. See §5. | Every install change must be made, or consciously not made, in several places; the documents drift (OPS-011, OPS-013). | §5. | NEW-OPS-14 "Prune install forms" (S to delete, M with the documents) | Later |
| OPS-018 | Medium | RUNBOOK §19 prints `python -m tools.trialbox model hold ...` "on the box, from the install folder". On the host it cannot work: `python` is not a command on Ubuntu 24.04, `TB_DB_URL` is in the root-only `deploy/.env`, and its host name `db` resolves only inside the compose network. | By a run on this machine: `model hold: TB_DB_URL is not set: no flag store`. `docs/runbook/19-model-misbehaviour.md:32-33`. The page `/ops/flags` works and is named on the same page. | In the one procedure that is run under pressure, the first printed command fails. | Print the command that works (`docker compose --project-directory deploy exec orchestrator python -m tools.trialbox model hold ...`) and put the page first. A `trialbox` wrapper on the host that picks host or container per sub-command would end this class of error. | NEW-OPS-15 (S) | Go-live both |
| OPS-019 | Medium | Support is one person for two countries with no named backup, and go-lives two weeks apart (2027-04-28, 2027-05-13). The names on the support sheet are blank "until the owner answers". | RUNBOOK §21 "Names", "Hours"; `support-sheet.md` A.1. | First-month support for two sites in two languages rests on one person; a week of illness is a week without tier 2. | The owner names a backup per country before the first go-live; the first-month morning check is a rota of two. | owner decision (TB-DR-09 Q6) | Go-live both |
| OPS-020 | Low | `tools.box detect` lists `/dev/zram0` and any disk that holds none of `/`, `/boot`, `/var`, `/usr`, swap as "disks for backups": a disk that holds `/home` or Docker's data root is offered. | By a run of `python3 -m tools.box detect` here; `tools/box/plan.py:158-175`. | Harmless today. T-730 plans to format the chosen disk with the owner's confirmation. | Offer only disks with no mounted file system and a real transport; show size and model. | T-730 | Go-live both |
| OPS-021 | Low | `trialbox.service` waits a fixed 900 s for the stack and has `TimeoutStartSec=1200` (OD-10: not derived, not a setting). On a failed wait `ExecStartPost` (the egress rules) does not run; the two-minute refresh timer covers it. The install has `TB_INSTALL_UP_TIMEOUT` as a setting; the unit does not. | `deploy/systemd/trialbox.service`. | After a power cut with a long database recovery or a cold model load the unit shows failed while the containers run. | Take the wait from the same setting, written into the unit at install. | NEW-OPS-16 (S) | Later |
| OPS-022 | Low | Small things. `deploy/network.sh print` ends in a Python traceback when Docker is not running. The network sheet says of Prometheus "no published port" beside `127.0.0.1:9090:9090`. `install.sh` stages the 40 GB bundle twice under `/tmp` (the dry run, then the real run). `check_host.sh:240` still only warns on an unsynchronised clock. | By a run (`network.sh print`, the sheet for a file set with the monitoring overlay); `deploy/install.sh` step 2; `tools/apply_update.sh` (`mktemp -d "${TMPDIR:-/tmp}/..."`). | Install time and confusion. | Catch the Docker error; fix the sheet's text; verify once and keep the stage; make the clock line `strict`. | NEW-OPS-17 (S) | Later |

### 4.1 OPS-001: the run

```
$ python -m tools.keys init --backend file --secrets sec --kek-out kek.new      # what seal_keys.sh does for tpm
KEK ae3bbe65... (back end file) recorded in sec/kek.json
wrapped site_hmac.key ...   wrapped pid_map.key ...
$ ls sec            # what the nightly backup takes (volume tb-secrets)
kek.json  pid_map.key.wrapped  site_hmac.key.wrapped
$ rm kek.new        # seal_keys.sh shreds it after systemd-creds encrypt --with-key=host+tpm2
$ python -m tools.keys unseal --secrets sec --out k
keys: --from PATH is needed for the file back end (the opened TPM credential or the media)
```

The sealed credential (`/etc/credstore.encrypted/trialbox-kek`) opens only with that board's TPM and that disk's host
key. Neither is in the backup, and the TPM cannot be. A restore on a new box also meets a second problem: the new
install makes and seals new keys before the restore puts the old `kek.json` back.

### 4.2 OPS-002: the run

```
$ printf 'TB_ENV=PRODUCTION\nSMTP_PASS=hunter2secret\nPOSTGRES_PASSWORD=abcDEF123\n...' > deploy/.env
$ python -m tools.support_bundle --out out --deploy deploy --no-commands
wrote .../trialbox-support-20261112T081326Z.tar.gz: 6 files; ... the finished bundle scans clean
$ tar -xzOf out/*.tar.gz support/env.redacted
TB_ENV=PRODUCTION
SMTP_PASS=hunter2secret
POSTGRES_PASSWORD=[redacted]
```

`redact_secrets` on the names `install.sh` and the wizard write: redacted `POSTGRES_PASSWORD`,
`POSTGRES_WF_PASSWORD`, `TB_DB_URL` (user and password), `TB_LLM_API_KEY`, `TB_KMS_TOKEN`, `CLOUD_LLM_API_KEY`; kept
in clear `TB_DB_PW_LAKE`, `TB_DB_PW_ORCHESTRATOR`, `TB_DB_PW_AUDIT_WRITER` (the pattern has no `PW`), `SMTP_PASS`,
`IMAP_PASS`, `TB_KEK_PASSPHRASE`. All values here were made up for the test.

### 4.3 OPS-003: the run

```
$ cat deploy/.env
TB_ENV=PRODUCTION                       # install.sh's default
TB_BACKUP_MAILTO=owner@box.invalid      # tools/box/plan.py:329, provisional answers
TB_BACKUP_TARGETS=.../deploy/backups
$ python3 -m tools.trialbox backup-install --deploy deploy --cron-dir cron ; echo rc=$?
backup-install: TB_BACKUP_MAILTO is set but this host has no mail transfer agent (sendmail): cron cannot mail; set TB_BACKUP_ALERT_CMD (RUNBOOK §5)
rc=1
```

`install.sh` then runs `die "the backup schedule is not installed (above) ..."`, before it prints "TrialBox is
running". `box-install.sh` reads that as "the install stopped ...: nothing for the wizard to serve". The comment in
`box-install.sh` ("a FAIL list at the end (backups not yet placed, say) leaves the stack running") shows the intent;
the backup step is a `die`, not a FAIL line.

### 4.4 The runbooks: commands and paths checked

A script read every `docs/runbook/*.md` (35 files) and checked each quoted repository path, `make` target and
`python -m` module (279 checks), then each `trialbox` sub-command. Result: no stale repository path, no stale `make`
target, no stale module. Every "missing" path is a file the install makes on the box (`deploy/.env`,
`deploy/site/...`, `deploy/secrets/...`). Sub-commands tried with `--help`: `logs prune`, `logs collect`,
`ops status`, `ops metrics-token`, `secrets status`, `mail status`, `doctor --weights`, `doctor --verify-all`,
`eval qualify`, `model hold`, `platform-day2`: all exist. `tests/unit/test_runbook_install_commands.py` passes.
Stale or wrong content found: the 13 drill names (OPS-012), the PITR step (OPS-013), the model-hold command line
(OPS-018), `make backup-drill` (OPS-014), "Aimedics has no remote access" in the pack against §21 (OPS-011). The
pages still address hospital IT throughout (T-735).

### 4.5 The network sheet against the compose files

`tools.network_sheet` for the six files the handover sheet names gives output equal to
`docs/handover/network-sheet.{en,ja,zh-TW}.{md,html}` byte for byte. Published ports in the compose files: the
console on `127.0.0.1:8090` (reset to none by the identity overlay), Caddy on `0.0.0.0:443`, Prometheus on
`127.0.0.1:9090` (optional overlay). The sheet says the same. Not on the sheet and needed by the box form: mDNS
(OPS-005). Not verified: that the nftables rules do what the sheet says on a running box (`sudo make test-egress`
needs Docker and root, and is in no workflow).

## 5. What to drop or simplify

Counted: 17 compose files, 3 Kubernetes overlays and 3 components over a base, a Windows path, a two-device path.

| Needed for CGMH and Japan (the box) | Keep for development and tests | Freeze or delete |
| --- | --- | --- |
| `docker-compose.yml`, `.secrets.yml`, `.identity.yml`, `.box.yml`, and one GPU file: `.rtxpro6000.yml` or `.gb10.yml` (chosen from measured numbers, T-667, T-734) | `.test.yml`, `.testbench.yml`, `.acceptance.yml`, `.poc.yml` (the PoC) | `topology_a/podman-compose.yml` (dead: delete). `deploy/pgbackrest/Dockerfile` (OPS-013: delete). `.rtx5090.yml` and the `small` tier (no site, no record, the sleep-swap helpers: freeze). `.shared-quota.yml`, `deploy/platform/**` (v6.1 §4.4: freeze, out of the owner's documents). `deploy/two-device/**` (decided only if the Spark cannot hold the stores: freeze). `deploy/windows/**`, `WINDOWS-INSTALL-CHECKLIST.md` (not the box's path: move to "other forms"). `.monitoring.yml` (Prometheus with no way to send an alert: drop from the site documents until OPS-008 has an answer; hospital IT can scrape `/metrics` itself). |

Also simplify:

- Two installers. `box-install.sh` wraps `install.sh`, whose 41-question wizard and PRODUCTION stops were written for
  hospital IT. Make the box the default path of `install.sh` and the IT-managed answers file the option.
- Three places decide whether a step may fail (`die`, `FAILS+=`, a warning). Decide per step once, for the box.
- `trialbox` commands run in three ways (host `python3`, `docker run` of the image, `compose exec`). One host
  wrapper that picks the place per sub-command (OPS-018).
- The image tag is `trialbox-py:1.0.0` for every release. Tag by release id as well, so `docker images` says what
  runs.

## 6. What the plan must change (inputs to plan v7)

**Day 1 at the first site (minimum operations set):**

1. An installer that finishes on the real hardware, rehearsed in CI (OPS-003, OPS-004) and from built media (OPS-006).
2. A reachable name and a trusted certificate on the team's PCs (OPS-005).
3. A time source (OPS-007).
4. A backup off the box, its key held by two people, a recovery copy of the KEK, and one restore on a second
   machine done and timed (OPS-001, OPS-012).
5. One proven way for red health to reach a person; the ops runner on (OPS-008, OPS-009).
6. A support bundle that leaks nothing (OPS-002) and a named backup for support (OPS-019).
7. The owner's handbook: set-up, a normal day, the five "something is wrong" pages (no mail, disk, GPU, power cut,
   locked out), and IT's one page (T-735, OPS-011).

**Can follow in the first month:** health checks for the night, the clock and the GPU (OPS-010) if the banner of
OPS-008 is there; the monthly OS snapshot (OPS-016); updates in a quiet hour; the remaining drills; PITR on.

**Can wait:** every other install form (§5); the Prometheus overlay; the syslog forwarder (remove it from the pack).

| Task | Size | Depends on | Order |
| --- | --- | --- | --- |
| NEW-OPS-2 support bundle redaction | S | none | now |
| NEW-OPS-3 real installer in the rehearsal and in CI, box form included; the backup step a FAIL line on a box | M | T-729 | now |
| NEW-OPS-1 recovery copy of the KEK; restore on a second machine | M | none | before any site key exists |
| NEW-OPS-8 ops runner on; stale facts red | S | none | now |
| NEW-OPS-4 the box's name, NEW-OPS-6 time source | S + S | T-729 | with T-735 |
| T-730 split into: 730a sign-in banner and message path (S), 730b backup target and key ceremony in the wizard (M), 730c health checks night, clock, GPU (M), 730d locked-box page (M), 730e updates in a quiet hour and the OS snapshot (M) | L as five cards | T-729, T-691 | a, b first |
| NEW-OPS-5 media builder and host preparation | M | T-729 | before T-213b |
| T-735 owner's handbook and IT's one page, pack rewritten | L (was M) | T-729 | parallel |
| T-213b drills on the rental workstation: restore timed, power cut, disk full, certificate | L | all above | last, before the first site |
| NEW-OPS-14 prune install forms | S | none | any time |

## 7. Needs GCP / owner hardware

1. **Box install end to end** on the rental workstation (and a Spark): from built media, `sudo deploy/box-install.sh
   <bundle>`, the wizard from a second PC by the printed name, `trialbox doctor`. Record: minutes from first command
   to the first sign-in; every stop. Pass: no shell command besides the one line; no FAIL line that the owner cannot
   clear from the console.
2. **Restore on a second machine, timed**: a 50,000-patient synthetic box, nightly backup to a share, the first
   machine switched off, a new install, restore with the envelope's key and the KEK's recovery copy. Record: RTO in
   minutes by step, the size of the `.tbbak`, the nightly backup's duration, `to_reapply` count. Pass: the box
   verifies (`backup_drill` checks), pseudonyms equal, RTO at or under the IT pack's figure, or the figure is changed.
3. **Reboot and power cut** on real hardware: pull the power during a night job. Record: seconds until the stack is
   healthy (to derive the unit's wait, OPS-021), that the egress table is closed before Docker starts (`nft list
   ruleset` from a rescue shell at boot), that the TPM unseal ran, that the job resumes or is retried (D-474).
   Pass: no manual step. Also `sudo make test-egress` on that box: all cases pass.

## 8. Small certain fixes

1. **OPS-002**, `tools/support_bundle.py:69`: change the pattern to
   `r"PASS|(?:^|_)PW(?:_|$)|PHRASE|SECRET|TOKEN|KEY|CREDENTIAL|PRIVATE|DSN|AUTH|SALT|PEPPER|COOKIE|PIN"`
   (`ATTACH_PASSWORD_MODE` stays safe through `SAFE_KEY`). Test that fails first: in
   `tests/unit/test_support_bundle.py` add `SMTP_PASS`, `IMAP_PASS`, `TB_DB_PW_LAKE`, `TB_KEK_PASSPHRASE` with
   `FAKE_PASSWORD` to the fake `.env` (line 52) and keep the existing assertion of line 124.
2. **OPS-009**, `deploy/install.sh` systemd step: add `trialbox-ops.timer` to the `systemctl enable` and `start`
   lines and drop the "installed, not enabled" line. Test that fails first: `tests/unit/test_systemd_units.py`, assert
   the enable line of `install.sh` names every `*.timer` in `deploy/systemd` (except `trialbox-firstrun`).
3. **OPS-003**, `deploy/install.sh` backup step: `[ "$rc" = 0 ] || { [ "${TB_BOX:-0}" = 1 ] && FAILS+=("backups: not
   scheduled yet (the wizard sets the target)") || die "..."; }`. Test that fails first: a case in
   `tests/console/test_box_install_rehearsal.py` that runs the real backup step (not the `TB_BOX_INSTALL` stand-in)
   with the provisional plan's `.env` and expects the installer to reach "TrialBox is running".
   Also **OPS-014**, `Makefile:214`: `backup-drill: venv-check $(FONTS) $(JVM_DEPS)`.

## 9. What is good

- The signed bundle path: verify before staging, anti-rollback, expiry, key rotation, compatibility table, free-space
  preflight, crash marker, rollback, the host tree inside the signature. Clear and tested.
- Backups the box cannot read (public key only), a manifest with hashes and row counts, the "to re-apply" list after
  a restore (D-455), the pre-restore copy, off-box enforced in PRODUCTION.
- Egress closed at boot before Docker; images only from the bundle with `--pull never`; third-party images pinned by
  digest; the database image's packages pinned by version.
- The network sheet is generated from the compose files and equals the handover copies.
- The support bundle's design (allow what goes in, scan the result) is right; only the secret pattern is wrong.
- RUNBOOK §4, §19, §21 to §25 exist and are concrete; they say "not measured" and "not built" where that is true.
- Third-party logs kept apart as D3; host logs rotated; a watchdog that respects a paused backup.
- D-466's survey of who can answer which question is the right way to design the box install.

## 10. What was not checked

- **`make backup-drill` did not complete.** Attempts 1 to 3 stopped on the product's missing prerequisites
  (OPS-014) once the database started. Attempt 4, with another reviewer's fetched jars and fonts, ran 5 min 45 s under
  a load average of 20 and reached stage 11 of the end-to-end chain (before the backup step); then the throwaway
  PostgreSQL stopped because the review machine's scratch parent folder lost its search bit during the run
  (`could not stat data directory ... Permission denied`). That is this machine, not the product. The unit tests of
  the backup were then run with their database under `/var/tmp/trialbox-0/OPS-dr2` (outside the assigned scratch
  folder, for that reason; removed afterwards): 177 passed in 101 s.
- No Docker daemon: nothing in a container was run. OPS-003's last step and all of OPS-004 are by reading.
- No real GPU, TPM, LUKS, systemd boot, nftables load, Caddy, Authelia or mail relay.
- `.ps1` files: read only. `shellcheck`: not installed; `bash -n` only.
- The update drill, the Kubernetes day-2 tools, the PoC scripts and the demo image were not run (frozen or another
  reviewer's).
- The first-run wizard's pages, wording and brute-force rules (reviewers UX, JRN).
- D-474's stated open race (two retries in the same instant) was not reproduced.
- The 369 unit tests run here pass; they prove the parts, not the install on a machine. The box-install test passes
  because it replaces `install.sh` (OPS-003).
