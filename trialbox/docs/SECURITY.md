# TrialBox security and compliance

*Owner: Security owner (Aimedics). Status: living; changed in the same pull request as the code it describes. History: the git log of this file; the merge into eight documents is D-139.*

For the hospital's security officer and privacy office. It lists the controls the box has, where each lives in the
code, the test that holds it, and the laws a site must check. `deploy/check_host.sh [--gb10]` checks the host and
changes nothing; run it after install and after every update. Ports and secrets for IT are on the network sheet
(`docs/handover/network-sheet.en.md`, also ja and zh-TW).

TrialBox is not a medical device: the investigator decides eligibility; the box never diagnoses, grades or advises
treatment. Every report says so (`spec/archive/SPEC_v3.md` §2.4; standards review of 2026-11-08).

## 1. The host

- **Disk.** Install Ubuntu on **LUKS2** ("Use an entire disk" and "Encrypt the LVM group"). Every store of PHI is on
  it: lake, FHIR store, objects, pid map, audit.
- **Unlock with the TPM**, so the box restarts alone but the disk is useless elsewhere:

  ```sh
  systemd-cryptenroll --tpm2-device=auto --tpm2-pcrs=7 /dev/<luks-partition>   # bound to Secure Boot state
  # /etc/crypttab: <name> UUID=<uuid> none tpm2-device=auto
  update-initramfs -u
  ```

  The LUKS recovery passphrase goes in the hospital's sealed-envelope procedure, never on the box.
- **Swap off** so PHI never pages to disk (`swapoff -a`, remove it from `/etc/fstab`, mask `swap.target`). The host
  check fails while swap is on.
- **GB10:** driver 580.142 exactly, held; the vLLM image pinned by digest.
- **Windows:** the box runs in WSL2. BitLocker, WSL swap and key custody (DPAPI/TPM) are post-platform work (D-125,
  D-128).

## 2. Network

`trialbox-net` and `trialbox-model-net` are internal (no route out). `deploy/network.sh apply` loads an nftables
table that drops every packet from the box's networks to the outside, except:

| From | To | When |
| --- | --- | --- |
| mail-gateway | `SMTP_HOST:SMTP_PORT`, `IMAP_HOST:IMAP_PORT` | always |
| gateway | a cloud model (`CLOUD_LLM_BASE_URL`) | only when set; never for D3/D4 data; the PHI guard runs first |
| criteria-compiler | clinicaltrials.gov:443 | `TB_CTGOV_MODE=live` (public registry; `cassette` closes it) |
| orchestrator | `NHI_TWPAS_BASE_URL` | only when set (SUBMIT) |
| any service | `EGRESS_EXTRA` entries | site additions, listed on the network sheet |

Container addresses change on restart, so re-apply from a systemd unit after Docker starts
(`ExecStart=/opt/trialbox/deploy/network.sh apply`, plus a path unit or a 5-minute timer). `sudo make test-egress`
proves it on a running stack: a fake outside host is reachable before the rules and only the allowed pairs after.

Only the console is published, on `127.0.0.1:8090`; the hospital reaches it through its TLS proxy with
`TB_CONSOLE_SECURE_COOKIE=1`. HAPI and Postgres have no per-caller token yet: network isolation and a password only
(D-138, not done).

## 3. Who may call what

- **Service tokens** (D-114, D-138). Each of the nine TrialBox services has its own token
  (`deploy/secrets/services/<service>.token`, 0600) and accepts only the callers in `tb_common/service_auth.py`
  `CALLERS`; a doc-parser token at the orchestrator gets 403. Reads are behind the token too (D-130). Tests:
  `tests/unit/test_service_secrets.py`.
- **People** (`services/console/auth.py`). Five roles; study scope, affiliation and expiry per account; scrypt
  hashes; lockout after 5 failures for 15 minutes with a countdown; sessions end after 30 minutes idle or 8 hours;
  CSRF token on every form; a Content-Security-Policy that allows no outside script. Hospital SSO through a trusted
  header from listed proxies ([Runbook §1](RUNBOOK.md#1-install-a-new-site-about-one-day)). TOTP is not built
  (Japan's MHLW guideline v7.0 asks for two factors from FY2027).
- **Chart numbers.** Only the coordinator may reveal one, for a listed patient, with a reason, under a rate limit;
  the investigator may not (D-127, D-133). Each reveal is in the audit.
- **Mail commands** need an allowed sender, a passing `Authentication-Results` (DMARC, or SPF/DKIM for the From:
  domain), the command's permission group and the daily rate limit.

## 4. Secrets

| Secret | Where | Protection |
| --- | --- | --- |
| service tokens, operator token | `deploy/secrets/services/` | 0600, one per service, mounted into that service only; rotated with `trialbox secrets rotate` |
| database, mail and cloud passwords | `deploy/.env` | 0600, root; cleared in the containers that do not need them |
| `site_hmac.key` (pseudonyms), `pid_map.key` (AES-GCM key of the pid map) | volume `tb-secrets` | 0600; seal at rest with the TPM (below) |
| backup public key | `deploy/secrets/backup.pub` | the private key is on a USB stick with hospital IT, never on the box |
| vendor update key | `deploy/keys/vendor_ed25519.pub` | public key only |

Seal the two site keys with the TPM and decrypt them into the secrets volume at start:

```sh
systemd-creds encrypt --with-key=tpm2 --name=pid_map.key /root/pid_map.key /etc/trialbox/creds/pid_map.key.cred
shred -u /root/pid_map.key
# trialbox.service: ExecStartPre=systemd-creds decrypt /etc/trialbox/creds/pid_map.key.cred <volume>/pid_map.key
```

Losing the site key changes every pseudonym: keep a sealed copy with the LUKS recovery material. No secret value is
ever printed, logged or put in the audit; `secrets status` shows names, modes and ages only.

## 5. Data protection

- **Pseudonyms at the door.** The adapter turns each chart number into `HMAC(site key, chart number)`; names and IDs
  live only in the AES-GCM pid map. The lake has no chart number, ID or phone column (`e2e_simple` stage 0).
- **Log scrubbing.** Logs carry pseudonyms only; the scrubber removes Japanese and Taiwanese IDs, phone numbers and
  postcodes (`tb_common/logging.py`, D-121).
- **Small cells.** Counts under 5 are shown as `<5` in anything that leaves the study team (`tb_common/smallcell.py`).
- **Routing.** Patient-level files go only to the study's internal list, as 7z AES-256 with the password in a second
  mail; aggregate files may go to `aggregate_to`. Checked before every send (`tb_common/routing.py`).
- **Models.** Every call goes through the gateway, which routes by data class; local models only for patient data.
  A note excludes a patient only when two models agree on a verified quote (D-115, D-117).
- **One-way hospital systems.** TrialBox never writes to an EMR, SS-MIX2 or CGRD (owner decision 2).

## 6. Audit, retention, updates

- **Audit.** Append-only daily JSONL, each line hashed with the one before (`tb_common/audit.py`); a torn line is
  repaired, never hidden (D-127). `tools/audit_verify.py` checks it. Archived nightly, compressed and verified;
  never deleted; 10 years on the box (D-138).
- **Retention** by country (wizard defaults, D-138): service logs 365 days; mail logs 5 years in Japan (医師法 §24),
  7 years in Taiwan (醫療法 §70); outputs 365 days; attachments 90 days; snapshots 3 nightly and 36 month-ends.
  Every deletion is audited with the object's sha256.
- **Updates.** Offline, signed (Ed25519), never automatic; verified in a container with no network; tampered,
  unsigned, foreign-key, path-traversal and symlink bundles are refused; backup and rollback point first (D-77,
  D-138). Not done: anti-rollback, key id and expiry in the manifest (review F-15).
- **Backups** are encrypted to a key the box does not hold (D-126).

## 7. Laws a site must check

None of this is legal advice. Items marked *legal review* need the site's counsel.

**Both countries.** ICH E6(R3) data governance (audit trail, validation by risk, provider oversight): the audit chain,
byte-identical re-runs and `tools/acceptance.py` support it; a validation plan is a document, not code. Part 11 and
Annex 11 apply only if the box's records become trial records (a screening log in the TMF, a sheet the PI signs):
*legal review*, sponsor by sponsor. Hospital IT will ask for ISO/IEC 27001 and ISO 27799 (an organisational item).

**Japan.**

| Framework | What it asks of the box |
| --- | --- |
| APPI 個人情報保護法 | medical data is 要配慮個人情報: consent or an exception; 仮名加工情報 supports feasibility but not contacting patients; leak reports to the PPC |
| 生命・医学系指針 (2023) | existing records by opt-out with notice and an ethics committee |
| MHLW 安全管理ガイドライン v7.0 (2026) | two factors from 1 April 2027; lockout; no password reuse |
| MIC/METI provider guideline v2.0 (2025) | the vendor's risk assessment, service specification, SLA and 責任分界 |
| 次世代医療基盤法 | only when data goes through a certified operator; one hospital's own pre-screening is outside it |
| J-GCP, ER/ES guidance | if the box's output becomes a 治験 record |

**Taiwan.**

| Framework | What it asks of the box |
| --- | --- |
| PDPA 個人資料保護法 (2023; 2025 amendment pending) | medical data is special data; the basis for pre-screening with re-identification: *legal review* |
| 人體研究法 | IRB approval; consent or a listed waiver; non-de-linked data destroyed after the study |
| 醫療法 and the EMR regulation (2022) | access control, encrypted transfer, a full access log for the retention period, incidents reported within 72 h, data in Taiwan |
| 資通安全管理法 (2025) | medical centres are critical infrastructure: CISO, SOC, incident reporting |
| 人體生物資料庫管理條例 | when the source is a biobank |
| GCP 藥品優良臨床試驗作業準則 | the IRB approves the recruitment method, EMR search included |

The 2022 Constitutional Court judgment (111年憲判字第13號) means any NHI-sourced data must allow opt-out.

The full catalogue of integration scenarios, with sources, is `spec/archive/INTEGRATION_SCENARIOS.md`. The latest
independent review of standards and security is `docs/reviews/2026-11-08-fable-standards-security-review.md`.
