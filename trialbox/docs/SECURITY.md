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

Only the console is published, on `127.0.0.1:8090`. For the hospital LAN the identity overlay
(`deploy/docker-compose.identity.yml`, D-193) puts Caddy on 443 in front of it and stops publishing 8090: TLS 1.2 or
1.3 with Caddy's internal CA (its root installed on the staff PCs) or the hospital's certificate (`TB_TLS_MODE`,
`TB_TLS_CERT_FILE`, `TB_TLS_KEY_FILE`; `console.cli check-tls` checks the files, the key and the host name first),
HSTS, and Secure session cookies. Authelia, when used, reaches the hospital AD by LDAPS only through an
`EGRESS_EXTRA` entry (`authelia=<domain controller>:636`). Steps: [Runbook §12](RUNBOOK.md#12-identity-and-tls-d-192-d-193). HAPI and Postgres have no per-caller token yet: network isolation and a password only
(D-138, not done).

## 3. Who may call what

- **Service tokens** (D-114, D-138). Each of the nine TrialBox services has its own token
  (`deploy/secrets/services/<service>.token`, 0600) and accepts only the callers in `tb_common/service_auth.py`
  `CALLERS`; a doc-parser token at the orchestrator gets 403. Reads are behind the token too (D-130). Tests:
  `tests/unit/test_service_secrets.py`.
- **The signed-in user between services** (D-143, review S-09). The console signs the user it names
  (`X-TB-Actor-Assertion`: actor, console session, two-minute expiry, HMAC with a key derived from the console's
  token); the orchestrator verifies it with the key in `deploy/secrets/services/actor/keys`, which only the
  orchestrator mounts, before a reveal, a screening-log export, a notice or a cancel. An unsigned name is refused
  and audited (`actor.refused`); the reveal and export caps count per calling service and verified person.
- **People** (`services/console/auth.py`). Five roles; study scope, affiliation and expiry per account; scrypt
  hashes; lockout after 5 failures for 15 minutes with a countdown; CSRF token on every form; a
  Content-Security-Policy that allows no outside script. Hospital SSO through a trusted header from listed proxies
  ([Runbook §1](RUNBOOK.md#1-install-a-new-site-about-one-day)).
- **Identity** (D-192; `services/console/identity.py`, `totp.py`, `oidc.py`; tests `tests/console/test_identity.py`).
  Local accounts sign in with a password and a TOTP code (RFC 6238: SHA-1, 6 digits, 30 s, one step of drift, a code
  works once). It is the default and can be off only in DEV and TEST (Japan's MHLW guideline v7.0 asks for two
  factors from FY2027). A device is registered only with a one-time enrolment code an administrator issues (24 hours;
  also after a reset), so a password alone never registers one. The TOTP secret is AES-GCM encrypted with a key file
  on the console volume, not in the database. A wrong or replayed code counts as a failed sign-in, and a right
  password does not reset the count; the lock is audited (`console.lockout`). An administrator lifts a lock, issues an
  enrolment code or resets another person's authenticator on `/ops/identity` (audited `console.unlock`,
  `console.enrol_code`, `console.totp_reset`; a reset signs the account out). Sessions end after 10 minutes idle
  (`TB_CONSOLE_IDLE_MINUTES`, 1 to 60; a page's own auto-refresh is not activity) or 8 hours
  (`TB_CONSOLE_SESSION_HOURS`, 1 to 12); session cookies are HttpOnly and SameSite=Strict, and Secure by default in
  PRODUCTION, where an explicit off is refused. The trusted-header SSO runs only with TOTP and OIDC off (DEV, TEST),
  never signs in a local account, and Caddy strips identity headers.
  Optional sign-in with the hospital account through Authelia (OIDC code flow with PKCE, off unless
  `TB_OIDC_ENABLED=1`): the ID token's signature (RS256 or ES256 only), issuer, audience, expiry and nonce are
  checked, a second factor must be reported (`amr`), and the role comes only from `TB_OIDC_GROUP_ROLES`; a person in
  no mapped group or in groups of two roles is refused, a `role` claim is ignored, and a directory account never takes
  over a local account. The role table (`console.auth.User`, `tb_common/authz.py`) and the signed actor assertion are
  unchanged. Not done: WebAuthn in the console itself (Authelia offers it), step-up before a reveal, the
  breached-password list and password history (master plan WS-13.1), and removing the trusted-header SSO.
- **Chart numbers.** The coordinator, the administrator and the study's investigator (owner's decision of
  2026-11-09, D-143, reversing D-133) may reveal one, for a listed patient, with a reason, under a rate limit
  (`TB_REVEAL_MAX_PER_HOUR`, 60); viewer and CRO accounts never see one. Each reveal or view is in the audit. The
  screening-log export with chart numbers is audited at the orchestrator too and capped (`TB_EXPORT_MAX_PER_HOUR`,
  10). Mail never carries a chart number, also not the investigator's N1.
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
  A note excludes a patient only when two different models agree on a verified quote, and every note holding the
  evidence was shown to them (D-115, D-117, D-276).
- **Planted instructions.** A fence in a note, chart, consent form or protocol cannot close a prompt's data block;
  text nobody can see on the page is flagged; the injection suite (56 attacks, 14 controls, en / ja / zh-TW) gates
  CI against the stub and `qualify` against a pair; model traces live 7 days in PRODUCTION (D-346).
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

## 8. Supply chain

What goes into the images is fixed by hashes, scanned before a release, and listed in an SBOM (D-185, D-186).
The build side needs the network; the box never runs these tools. Code: `tools/supply_chain/`; tests
`tests/unit/test_supply_chain.py` (offline, on fixtures trimmed from real Trivy and Syft output).

- **One hashed lock.** `uv.lock` records a sha256 for every file of every package. `deploy/requirements.lock` is its
  export (`make lock`); every entry carries `--hash=sha256:`, so `pip install -r` in the images runs in pip's
  hash-checking mode and refuses a file whose bytes differ. `make lock-check` fails when `uv.lock` no longer matches
  `pyproject.toml`, when `deploy/requirements.lock` is not the export of `uv.lock`, or when an entry (or the
  pip-audit lock) has no hash; CI runs it on every pull request. Never edit `deploy/requirements.lock` by hand.
- **Pinned tools.** Every GitHub action is pinned to a commit. Syft and Trivy are release archives with a pinned
  sha256 (`make scanners`); pip-audit is installed from its own hashed lock (`tools/supply_chain/pip-audit.lock`).
  The base images are pinned by digest (`deploy/docker/python.Dockerfile`, `demo/Dockerfile`).
- **pip-audit** checks the lock against PyPI and OSV advisories (`make pip-audit`, on Python 3.12 so the lock's
  markers are judged as on the box). Every advisory fails unless allow-listed; the audited set must equal the lock
  (a package left out, an extra one or another version fails); a package it could not audit fails.
- **Trivy** scans every image that ships with its database loaded first (`make trivy-db`; on the media, `oras pull`
  of `trivy-db:2` and `trivy-java-db:1`) and the scan offline, with no ignore file, no config file and no `TRIVY_*`
  environment, so only the allow-list can accept a finding. A CRITICAL or HIGH finding with a fixed version fails
  unless allow-listed (Trivy's UNKNOWN, a CVE not scored yet, counts as HIGH); a finding with a missing or odd
  severity fails; findings with no fix yet and MEDIUM/LOW are
  listed. A report must show what it scanned (OS packages, the Python packages of the TrialBox images, the jars of the
  JVM image). The database may be at most 7 days old (its `UpdatedAt`).
- **Release gates.** `make release-gates` pins each image first (a local image by its image id, a third-party image
  by its registry digest for the platform), then runs Trivy and Syft on it and checks that both name that image. It
  covers trialbox-py, trialbox-jvm, trialbox-demo and every third-party image compose pulls. The record
  (`build/supply-chain/gates.json`) and `dist/sbom/index.json` list per image the reference, platform, image id,
  digests, and the report and SBOM with their sha256. CI runs it on amd64 and arm64 for pull requests that change
  what goes into an image, weekly and for a release tag; a release tag also gates both platforms of
  `make images-multiarch`, by digest. `make release-bundle` makes a bundle only from images in a passing record
  (`tools/make_bundle.sh --gates`, which refuses any other image id or a record older than 7 days).
- **Report mode for third-party images, for now.** Until plan v6 §9 batch 1 lands (owner decision of 2026-11-10),
  CI runs the image gates with `--vuln-mode report`: fixable CRITICAL/HIGH findings in the third-party images are
  listed in the CI job summary and do not fail a pull request. Everything else still blocks: the vulnerability gate
  of our own images (trialbox-py; trialbox-jvm and trialbox-demo since T-672), the licence gate, `make lock-check`, `make allowlist-check`, `make pip-audit`, and any build,
  scan or report error. A bundle never carries an image that passed only in report mode. The open findings, with
  owner, target date (2026-12-10) and planned fix, are in `deploy/security/known-image-findings.md`. MailHog has no
  arm64 image; it is left out of the arm64 gates by name (`SC_AMD64_ONLY`).
- **SBOM per release.** Syft writes CycloneDX JSON for each image and platform, and for the Python lock: Syft over an
  environment installed from the lock with hashes (`make lock-sbom`), so each package carries the licence of its
  installed metadata. The lock's SBOM must name every locked package that installs on the box, at its version.
- **Licences.** `make licences` reads the SBOMs (nested components, licence ids, names, expressions, URLs and full
  texts) and flags GPL, LGPL, AGPL, unknown licences, and dual licences. Only a licence on the known permissive list
  counts as an `OR` choice: `LicenseRef-*`, `NOASSERTION`, `Proprietary` never do. Who must answer for a flag:
  - *The Python lock and our images* (trialbox-py, trialbox-jvm, trialbox-demo): every copyleft or dual flag, and
    every unknown licence of a Python or npm package, needs its own allow-list entry (a dual entry names the branch
    taken, an unknown entry the licence a person verified), so a stricter licence fails again. Jars, Go and Rust
    binaries and other binaries carry no licence data Syft can read: their unknowns are counted per image and
    ecosystem against a reviewed budget, which fails as soon as one more appears.
  - *Third-party images* (postgres, HAPI, GreenMail, MailHog, vLLM), redistributed unmodified under their
    publishers' terms: all their open flags are counted per image against a reviewed budget; the image's terms are
    reviewed as a whole (counsel: vLLM's CUDA libraries).
  - Distro packages of a base image are listed, not gated.
  Today: eight LGPL packages (psycopg, psycopg-binary, docxtpl, py7zr and its four helpers), dulwich under
  Apache-2.0, six Python packages whose licence the SBOM cannot read (verified in the wheels), the base image's
  interpreter and pip launchers, the JRE, one HL7 FHIR package; budgets of 68 jars (trialbox-jvm), 64 jars
  (trialbox-demo) and the third-party images' counts from the first CI run.
- **The allow-list** (`deploy/supply-chain-allowlist.yaml`) is the only way to ship with a finding. Each entry needs
  its package (or, for a budget, its image and ecosystem), a reason of at least 20 characters and a `review_by` date
  at most 180 days ahead; `make allowlist-check` rejects an entry without them, a key given twice and a list given
  as anything else. After
  `review_by` every gate fails until the entry is reviewed or removed. Changes need the security owner's approval.
- **Not done yet** (WS-14.6): `THIRD_PARTY_NOTICES.md`; the SBOMs inside the signed bundle; `--gates` made
  mandatory in `tools/make_bundle.sh` (optional today, with a warning, so the demo VM's update script keeps working);
  the venv installed from the same lock (`make venv` still resolves from `pyproject.toml`).
