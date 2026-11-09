# TrialBox full pre-release system review, 2026-11-09 (six reviewers, consolidated)

| Field | Value |
| --- | --- |
| Date | 2026-11-09 |
| Head reviewed | `origin/master` ada9c8f (PR #43, D-140) |
| Inputs | Six independent, read-only reviews (copied whole in `2026-11-09-review-parts/`, see §8): 01 architecture, serving and stability (A-xx); 02 correctness bugs (B-xx); 03 security and compliance (S-xx); 04 engineering, tests and libraries (E-xx); 05 deployment, operations and wrappers (D-xx); 06 end to end, product and clinical fit (P-xx, open items O-xx) |
| Context read | `docs/plan/24-plan-v4.md`; D-120 to D-140 in `docs/DECISIONS.md`; `docs/reviews/2026-11-08-fable-standards-security-review.md` (F-xx) |
| Status | Record. Not maintained after the commit. New facts go into DECISIONS. |

How this was consolidated:

- Every finding of the six reviews is in the table of §2, alone or merged with its duplicates. The "sources" column keeps every original ID.
- Severity is the highest any reviewer gave. Four rows are raised, and each says why. Nothing was lowered.
- "Patient safety = yes" means a patient can be wrongly excluded, a safety event can be missed, or an identified patient can be exposed.
- Effort, normalised across the six scales: **S** ≤ 1 engineer-day, **M** 2–5 days, **L** more than a week.
- "D-xx" is a review-05 finding. A decision is always written "decision D-xxx" or named as a DECISIONS entry.

## 1. One-page verdict

**Is TrialBox ready for a first pilot site? No. Yes-if the conditions below are met.** It is fine today for what D-128 already allows: synthetic and public data only.

Conditions for a first real-data pilot:

1. **Wave 1 is done** (§3): the patient-safety and correctness blockers, the gateway, DB reconnect and the cloud-run fail-safe.
2. **Gate G1 passes**: the 50,000-patient scenario run on the real model pair, through the production gateway path, green in ja and zh-TW (§3, §4). Plan v4 §5 already says the platform is not complete until such a run passes.
3. **Wave 2 is done**: at least the six items review 03 names before any identified record (S-01, S-02, S-04, S-05, S-06, S-07), plus the SSO and egress fixes.
4. **From Wave 3**: scheduled off-box backups with an age alert, the update safety items, one real run of the compose stack and its update and rollback on Docker, and the admin health tiles.
5. **From Wave 5**: the pilot blockers of review 06 that apply to the site (real REDCap for a REDCap site, real SS-MIX2 for a Japanese site, OCR on real scans for a paper site, one-page role guides, honest feasibility numbers, true wording, real contact outcomes).
6. The owner's real-data gate (decision D-127, decision D-128) still applies after all of this.

**Findings after de-duplication.** 150 graded findings went in (plus 9 suspected items and 27 open items). 113 rows came out.

| Severity | Before (sum of the six tables) | After de-duplication | Of which patient safety = yes |
| --- | --- | --- | --- |
| Blocker | 5 | **5** | 5 |
| High | 27 | **25** | 7 |
| Medium | 71 | **54** | 6 |
| Low | 47 | **29** | 2 |
| Total | 150 | **113** | 20 |

**The 10 most important problems, in plain words.**

1. **On an installed box the model is never asked.** The gateway refuses every call that carries patient text, because nobody sets the data class and the gateway has no step confirmer. Every GPU run so far went around the gateway. (R-01)
2. **A lab written as text excludes the patient.** "75 H", "<0.3" or 陰性 counts as "does not meet", not "unknown". Nobody is told. (R-02)
3. **The chart number is shown to the PI and the viewer** on the CASE job page, with no reveal step and no audit record. (R-03)
4. **A death on study disappears.** A fatal SAE leaves the banner and the morning mail the moment it is saved. There is no PI acknowledgement and no reporting clock. (R-09)
5. **Nobody can see who was excluded, or why.** A suspected diagnosis (疑い) from SS-MIX2 is read as a real one and can exclude. (R-07, R-08)
6. **Two engine bugs drop or blank real data.** A patient missing from the snapshot is shown as excluded instead of "for review" (R-06). REDCap sync on a longitudinal project erases enrolment and consent dates on every run (R-10).
7. **Sign-in and keys are not hospital-grade.** There is no second factor and no AD/LDAP. Keys and files with chart numbers sit in clear on the Windows box. (R-04, R-05)
8. **One database hiccup stops the box** until someone restarts it. (R-13)
9. **A paid GPU VM can run with no limit.** Today's VM ran 61 minutes until it was stopped by hand. Its only off-switch is a trap in a laptop process. (R-14)
10. **Backups and updates are not safe yet.** No backup is scheduled, and the default target is the same disk. The update path has no crash marker, no free-space check and no anti-rollback, and it has never run on Docker. (R-20, R-21, R-23 to R-26)

**What is good.**

- The safety design holds where it was built. One two-model rule; a disagreement or a down verifier gives "unknown", never an exclusion. The canary gates note exclusions. A run whose model was down fails instead of shipping a filters-only list.
- Serving is disciplined: forced sampling, schema-checked answers, a measured serving record before a tier installs, the swap with wake checks.
- The service boundary is fixed since 2026-11-08: one token per service, a caller table, protected reads, and `TB_ENV` unset = PRODUCTION. Reveal is bound to the job's list and audited.
- The job engine, the audit chain's mechanics and the backup cryptography are good.
- Tests are plentiful and honest: 1,423 cases pass, services and libraries at 84 % coverage, and oracles that do not trust the code under test. `e2e_simple` (17 stages), `public_e2e` (112/112) and the walk pass on the stub.
- The console fixed most of the novice review: required reasons with undo, outcomes only after the PI's OK, plain refusals, phone sheets, three languages.
- The documents are honest about what has not run.

## 2. De-duplicated findings

Sorted by severity, then by patient safety. Evidence is the reviewers' file:line; "seen" means the reviewer saw it on the served console. Repro scripts are in `2026-11-09-review-parts/scratch-02/`.

### 2.1 Findings table

| ID | Sev. | Area | Finding | Evidence | Patient safety | Fix | Effort | Sources |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R-01 | **Blocker** | Model serving / gateway | On an installed box the gateway refuses every PHI prompt (judge, chart facts, consent drafts). They are labelled D3 when `TB_DATA_CLASS` is unset, which install leaves it, and the compose gateway has no step confirmer. Also, all 21 model builds have `sha256: null`, which the registry refuses to route outside DEV/TEST. Every GPU run so far bypassed the gateway. | `services/gateway/app.py:36-49`; `services/gateway/core.py:255-258`; `libs/tb_llm/client.py:205-225`; `deploy/docker-compose.yml:107,118,149`; `tools/public_e2e.py:164-171`; `models/registry.yaml` | yes | The orchestrator sends its job id as `X-TB-Step` and the gateway confirms it against live jobs, or the owner allows D3 from the orchestrator by policy. Add a compose-level test with `TB_DATA_CLASS` unset in PRODUCTION. `doctor` fails when the gateway would refuse the judge. Fill model hashes. Never "fix" it with `TB_DATA_CLASS=D0`. | M | A-01; S-13 (hash part); 06 §2 S2 |
| R-02 | **Blocker** | Screening engine | A lab in the window whose value is not a number ("75 H", "<0.3", 陰性, a `valueString`) makes the value atom FALSE, not unknown. Under v1 semantics, and for value criteria under affirmative semantics, the patient is excluded silently on both runtime paths. Reviewer 02 suspects the same class for procedure, encounter, report and observation presence (not reproduced). | `services/criteria_compiler/compile_sql/generator.py:168-176`; `adapter/mapping/engine.py:383-385`; `lake/flatten.py:260`; `matching/cascade/engine.py:526-527`; repro `repro_lake.py` part A | yes | In `_obs_value`, return NULL when no row in the window has a number. Keep unreadable rows as evidence with a new reason `unknown_value`. Mirror it in the CQL generator and the oracle. Widen D-130's `Coverage.DOMAINS`. | M | B-01; 02 suspected 4 |
| R-03 | **Blocker** | Privacy / console | The CASE job page's mail-thread row prints the chart number (`mrn=70000054`) to PI, viewer and CRC: no reveal, reason or audit. Viewer and investigator can open `/jobs` and `/audit` across all studies. `public_e2e` sweeps mail for chart numbers but not pages, so the 2026-11-08 fix regressed unseen. | `services/console/app.py:1061-1063`; seen on `/pilot/jobs/…` and `/approval` (pi and viewer, ja); `services/console/app.py:755-766,471-499`; `tools/public_e2e.py:524` | yes | `mask_ids()` on the web-request line. `/jobs` and `/audit` for admin and coordinator only, or filtered by study. A chart-number sweep over every page, every role, in the walk. | S | P-01, P-32, S-19, O-02 |
| R-04 | **Blocker** | Authentication | No second factor (no TOTP, WebAuthn or step-up). No AD/LDAP bind, although decision D-126 promises one. No forced password change after the one-time password. MHLW GL needs two factors from FY2027, the first-site window. | `services/console/auth.py` (whole file); `grep totp/ldap/webauthn` = 0 files; `docs/SECURITY.md` §3 | yes | TOTP with recovery codes and admin reset, enforced by `doctor` in PRODUCTION and VALIDATION. Step-up before reveal and both chart-number exports. LDAP bind or OIDC as the AD path. `must_change` at first sign-in. | L | S-02, P-23, O-13; F-04 |
| R-05 | **Blocker** | Platform / data at rest | Hardening and key custody are written for Ubuntu with LUKS and TPM; the product ships on Windows 11 with WSL2. `preflight.ps1` checks no BitLocker, swap or hibernation. `site_hmac.key` and `pid_map.key` are plain files next to the data. Candidate spreadsheets with chart numbers, uploaded charts and their OCR text are stored in clear. | `deploy/windows/preflight.ps1`; `docs/SECURITY.md` §1, §4; `services/orchestrator/core.py:165-176`; `scenarios/screen.py:491-493`; `services/sitesetup/service.py:81-85,205-207` | yes | Preflight FAILs without BitLocker (TPM+PIN, recovery key escrowed), WSL swap off, hibernation off, RDP off. `doctor` refuses PRODUCTION without a Windows attestation. Wrap both keys with a key-encryption key held outside the data volume. Encrypt `phi` outputs and chart uploads at rest. | L | S-01; F-01 |
| R-06 | High | SCREEN cascade | A scoped patient with no row in the pinned snapshot (record merged, future birth date, wrong death date) becomes tier **excluded**; v1 and decision D-118 say "review". The `not_in_snapshot` fallback is dead code. `SCOPE_SQL` reads the current lake, not the snapshot. Raw English reasons reach ja and zh-TW pages. | `services/matching/cascade/engine.py:420-422`; `services/orchestrator/scenarios/screen_cascade.py:181-185,262-265`; `screen.py:45-66,123-130`; repro `repro_lake.py` part B | yes | Map any `in_scope=False` not caused by consent to `not_in_snapshot` (tier review). Pass `snapshot` to `SCOPE_SQL`. Map reasons to `Reason` codes. | S | B-02, B-18 |
| R-07 | High | Product / clinical safety | No page lists the patients the box excluded, with the reason, for a person to spot-check (178 on the public site, 3,332 on the synthetic hospital). Coded exclusions are outside the two-model rule by design. | `console/studies.py:483`; `screen_cascade.py:184-191`; seen: tiers excluded 178, high 0, review 90 | yes | An "Excluded by records" page: paged, read-only, reason per criterion. A weekly sample of 10 for the PI to confirm. | M | P-04, O-04 |
| R-08 | High | Adapter / SS-MIX2 | The reader ignores the 疑い (suspected) flag, so "悪性腫瘍の疑い" becomes a coded diagnosis and can exclude. The two reviewers place the flag differently (PRB-13 in 02; the PPR-01 flag in 06), so the field must be confirmed on the JAHIS spec or a vendor sample. | `adapter/sources/ssmix2/source.py:18-19,387` (`_diagnosis`); `docs/DECISIONS.md:809-813` (the judge prompt handles 疑い in notes only) | yes | Read the flag. A suspected diagnosis is unknown, never "met" for an exclusion. Add a fixture. | M | P-04, 02 suspected 1, 06 §2 S10, O-04 |
| R-09 | High | Lifecycle / AE | A fatal (outcome 5) or recovered SAE is not "ongoing", so it leaves the SAE banner and the N1 count when saved. No investigator acknowledgement, no IRB or sponsor reporting field, no deadline (7/15 days in JP and TW). | `orchestrator/lifecycle_api.py:267`; `console/lifecycle_pages.py:188-190`; `notify.py:144`; `datacore/builtin/forms.csv` rows 25–33; seen (CRC, zh-TW) | yes | Banner and mail show serious AEs not yet acknowledged (new `ae_ack_by/at`); fatal always until acknowledged. `ae_reported` with a date. A CRC task "SAE to report by {day}". | M | P-02, P-03, O-03 |
| R-10 | High | Data core / REDCap | On a longitudinal project with no `event` set, sync reads the blank cells of other events as changes and blanks TrialBox's value at the end of every sync. Enrolment and consent dates vanish; subjects never advance; visit anchors vanish. | `services/datacore/sources.py:94-99`; `services/datacore/sync.py:92-99`; `datacore_api.py:62-68`; repro `repro_sync_blank.py` | yes | When `redcap_event_name` is present and `event` is unset, refuse or merge per record and field. Never treat `""` from another event as a change. Require `event` at attach for longitudinal projects. | S | B-03 |
| R-11 | High | Authentication / SSO | Trusted-header SSO is forgeable as shipped: to work, it must trust the Docker bridge address, so every process that reaches the port is a "proxy". Each untrusted header request writes an fsynced audit event, so anyone can fill the audit volume and stop the box. | `deploy/docker-compose.yml:194-195`; `services/console/app.py:407-452`; `services/console/auth.py:278-316`; `libs/tb_common/audit.py:93-98,172-176` | yes | OIDC code flow with PKCE, or LDAP bind. Until then: the proxy only over a Unix socket or mTLS, and one `console.sso_rejected` per peer per minute. | M | S-03; F-06 |
| R-12 | High | PHI egress / mail | Candidate and NAV spreadsheets with chart numbers are mailed as a password zip, with the password in a second mail (PPAP). `zip` is the default, and SECURITY §5 presents it as the design. | `services/mail_gateway/outbound.py:116-125,211-225`; `scenarios/screen.py:491-493`; `scenarios/nav.py:198-232`; `.env.example`; `docs/SECURITY.md` §5 | yes | Default to **link**: the mail carries pseudonyms and a console link; chart numbers only in the browser after step-up, or by S/MIME. `internal_domains` as a strict allowlist with tests. | S | S-05; F-07 |
| R-13 | High | Stability / DB | Each store keeps one psycopg connection for life and never reconnects (measured after a Postgres restart). The console's `/healthz` does not touch the DB, and compose does not restart unhealthy containers. One connection per store also serialises all DB work of a process. Migrations split on `;` and are not checksummed. | `libs/tb_common/db.py:99-177`; `services/console/app.py:642-644`; `services/orchestrator/db.py:213-221,265-289`; `deploy/docker-compose.yml:21` | no | `psycopg_pool.ConnectionPool` (min 1, max 2–4, with a check) per process. `SELECT 1` in every `/healthz`. Restart on unhealthy (autoheal or systemd). `executemany`/`COPY` for bulk writes. Run each migration whole and store its checksum. | M | A-02, A-11, E-11, 04 library table |
| R-14 | High | Cloud run | A paid GPU VM's only off-switch is an `EXIT` trap in a laptop or sandbox process. There is no cloud-side cap, no on-VM shutdown and no budget alert. The wait loop hides auth failures; `stop_vm` is best effort; parts do not resume. Today's VM ran 61 minutes until stopped by hand. The setup script prints a project-wide SA key for pasting. | `deploy/gcp/complete-run.sh:45-60,73-100,110-121`; `deploy/gcp/gpu-pro6000-run.sh`; `deploy/gcp/setup-gcp.sh:47-51,62-70`; `tools/complete_run.py:236,475-512` | no | Review 05 §3: `set-scheduling --max-run-duration=5h --instance-termination-action=STOP` (VM stopped); on-VM hard cap and idle watchdog; the workload on the VM with parts in a bucket and `--resume`; the VM's attached service account; an auth and clock probe on the driver; no printed JSON key; a budget alert with a kill switch. | M | A-03, D-30, D-31, D-32 |
| R-15 | High (raised) | End-to-end truth | Every gate runs a stub that can never exclude (`note_block: never`). The pair has never run the `e2e_simple` path. Stage 12's chart reader is the stub's regexes on charts the repository wrote. Raised from Medium: plan v4 §5 makes this run the done-check, and 06 lists it as pilot blocker O-01. | `tests/inproc_box.py:127-129`; `e2e_simple.py` stage 3 (`PAIR is None`); decision D-139 "Not done" | no | Gate G1 (§3). Mark the stub branch "structure only" in VALIDATION. | M | P-21, O-01, 06 §2 S1, E-14 (model part) |
| R-16 | High | Mail | DNS, timeout, TLS or network errors before `DATA` leave the send key in `sending`. Every retry is a 409, the day's N1/N2 are lost, and a finished SCREEN fails at step `mail`. No tool resolves a stuck key. The outbox exists but no service uses it, although ARCHITECTURE §9 and decision D-127 say delivery goes through it. | `services/mail_gateway/gateway.py:58-66,88-111`; `outbound.py:52-60`; `store.py:95-108`; `services/orchestrator/core.py:383-428`; `services/orchestrator/outbox.py` | no | Classify by SMTP phase. `trialbox mail resolve <key>` and an admin list. A failed send never fails a finished job. Wire the outbox dispatcher, or correct the documents. | M | A-04, A-13 |
| R-17 | High | Resources | No container has memory, CPU or pids limits. On the 5090 box the sleeping model (~18 GB), DuckDB (40 % of RAM), the ingest batch (~16 GB at 50k) and HAPI compete; the OOM killer picks the victim. | `grep mem_limit deploy/*.yml` = none; `deploy/docker-compose.rtx5090.yml:16-20`; `services/lake/store.py:67-70`; `deploy/docker-compose.yml:75` | no | Per-service limits per tier; an absolute lake limit; `pids_limit`; streamed `--since` ingest; the RAM budget in `check_host.sh`. | S | A-05, D-04 (limits part) |
| R-18 | High | Audit integrity | The audit chain is an unkeyed SHA-256 chain. `audit-data` is writable from six containers; the archive defaults to the same box; NTP is only a WARN. A writer can cut and recompute, and `verify()` passes. | `libs/tb_common/audit.py:47-49,180-182,215-255`; `deploy/install.sh:258`; `deploy/check_host.sh:65-66` | no | Sign each day's chain head (Ed25519, key under the R-05 key-encryption key); write heads off-box and in the weekly admin mail. One audit writer, read-only elsewhere. NTP sync a FAIL; refuse jobs beyond 60 s skew. | M | S-04, A-20; F-08 |
| R-19 | High | Supply chain | The lock pins `pypdf 6.19.0` (18 advisories) and `pillow 12.3.0` (39); pypdf parses mailed protocols and uploaded charts. The lock has no hashes; `make venv` resolves fresh, so 32 of 74 packages differ from the image. No `pip-audit`, SAST or SBOM. | `pip-audit -r deploy/requirements.lock` (62 advisories); `services/doc_parser/parser.py:309-320`; `Makefile` `venv:`; `tools/make_bundle.sh` | no | Bump pypdf ≥ 6.21.4, pillow ≥ 13.0.0, brotli, certifi, opentelemetry-api. `uv lock` with hashes and `uv sync --frozen`. A `pip-audit`, bandit and `ruff --select S` gate. A CycloneDX SBOM in the bundle. Treat doc-parser as least trusted. | M | S-06, E-03, D-36 |
| R-20 | High | Backup | `install.sh` sets the backup target to `deploy/backups` on the same disk. A hand-run backup dumps HAPI only when `TB_HAPI_DB_URL` is set, and install never sets it. | `deploy/install.sh:258-259`; `tools/trialbox/backup.py:12-16,115-165,240-241` | no | `doctor` FAILs in PRODUCTION when every target is on the data disk. The wizard asks for the hospital share or USB. Set `TB_HAPI_DB_URL`. A restore drill as acceptance. | S | S-07 |
| R-21 | High | Backup operations | No backup is scheduled. The hand-run command does not work on a compose box (decision D-138 says so). Failures are invisible; prune by count can leave no recent backup; nothing checks the hospital's key still opens one. | `deploy/install.sh:259,271-276`; `docs/RUNBOOK.md` §5; `tools/trialbox/backup.py:428-435` | no | `trialbox backup --compose` as the default; a nightly cron after INGEST; `LAST.json` and `backup.ok/failed` audit events; admin tile red after 36 h; mail on failure; a quarterly restore drill with hospital IT. | M | D-19, D-20 |
| R-22 | High | Network | The egress table is applied once at install and never persisted. After a reboot or recreate, four services on `egress-net` have open outbound. The systemd unit SECURITY §2 promises is not installed. | `deploy/install.sh:268-276`; `deploy/egress.py:17-18`; `docs/SECURITY.md` §2 | no | Install `trialbox-egress.service` and a 5-minute timer; re-apply after every `up`; "egress table loaded" on the health tile. | S | D-01 |
| R-23 | High | Update | No journal, marker or resume; no `update status` or `update rollback`. A power cut mid-update leaves mixed images and plaintext dumps, and nothing says so. | `tools/trialbox/update.py:193-258`; `tools/apply_update.sh:41,63`; `tools/trialbox/__main__.py:55-60` | no | An `IN_PROGRESS.json` marker; `update status`; `update rollback <bundle>`; refuse to start the stack while the marker exists. | M | D-11 |
| R-24 | High | Update | No free-space check. About 40 GB is staged under `/tmp`, loaded again, and dumps and a backup are added: up to 3× the bundle. Rollback image tags are never pruned. Install hashes the bundle twice. | `tools/apply_update.sh:40`; `tools/trialbox/update.py:136-154,327-333,366-367`; `deploy/install.sh:142-143` | no | A preflight that prints the numbers; stage under `deploy/updates/stage/`; `update clean`; verify once. | M | D-12, D-18 |
| R-25 | High | Update | No anti-rollback, key id, expiry or revocation. An older signed bundle still applies onto a newer schema. The vendor key cannot be rotated. | `schemas/update_manifest.schema.json`; `tools/verify_update.py:94-98`; `tools/sign_bundle.py:39-55,73-74` | no | `release_seq`, `min_installed_version`, `key_id`, `not_after` in the manifest. Refuse a lower release unless an audited `--allow-downgrade`. Two trusted keys and a rotation bundle. | M | D-13, S-12; F-15 |
| R-26 | High | Operations / Docker | Nothing has run in Docker at this head: the compose stack with tokens and egress, the HAPI equivalence gate, mail, the compose update and rollback (a HAPI `pg_restore` may exceed `max_locks_per_transaction`), the demo-VM update commands. Gates and drills run on the in-process box. | decision D-138 and decision D-139 "Not done"; `tests/unit/test_update_path.py:140-200` (fake runner); `tools/update_drill.py:24-27`; `tools/trialbox/update.py:406-424,468-476` | no | Run the demo-VM commands and a compose drill: good bundle, bad migration, unhealthy release, disk full, kill -9 at each step. HAPI restore without `--single-transaction` and with more locks. Nightly `make up-test` and `make test-e2e`. | M | D-15, O-06, 06 §2 S5 and S13, E-14 (Docker part) |
| R-27 | High | Release identity | Every version string and image tag is `1.0.0`. No git tags, no changelog. The console shows no release, digest or bundle id. | `pyproject.toml:3`; `libs/tb_common/__init__.py:3`; `libs/tb_common/http.py:65`; `deploy/docker-compose.yml:15`; `tools/make_bundle.sh:6,74` | no | A `release.json` (release id, `release_seq`, git sha, image digests, model hashes) in the images and on `/healthz` and the admin page. Image tags per release. A git tag and a CHANGELOG entry per release, checked by doclint. | M | D-35 |
| R-28 | High | CI | The one workflow runs `e2e_simple` and the backup drill on pull requests only. No pytest, ruff, mypy, doclint, contracts-check, image build, audit or SBOM; nothing on push or on a schedule. The cache is keyed on `pyproject.toml`. | `.github/workflows/trialbox-e2e.yml`; `docs/DECISIONS.md` l.2786 | no | Jobs: lint (ruff, mypy, doclint, contracts-check, shellcheck, hadolint); test (pytest `-n auto`); keep e2e. Run on push to master. Nightly `public_e2e`, `update_drill`, image build, `pip-audit`. Cache on the lock. | S | E-01, E-18 |
| R-29 | High | Tests | `_private_trial_db` is autouse, so every test needs a throwaway Postgres. Test schemas are never dropped (212 after one run); an aborted run leaks the cluster. The suite takes 18 min serial; two Monte-Carlo tests take 5 min. | `tests/conftest.py` l.21–57; `tools/pglocal.py`; dead `/tmp/tb-pgtest-*` clusters | no | An opt-in `db` fixture; drop schemas at teardown; `atexit` and SIGTERM cleanup; `pytest-xdist`; mark the statistical tests `slow` and run the large size nightly. | S | E-02, E-04 |
| R-30 | High | PI workflow | The PI's list does not prioritise. Every row reads "4/7 · 2 unknown · to review"; "ready" is 0; two pills say the same thing; "First / Second check" is unexplained. | seen `/studies/PUB-ONC/week?list=all` (pi, ja, phone) | no | Sort "needs information" by unknowns and next visit. One trust line per row. Merge the pills. Say the checks are two models. | M | P-05 |
| R-31 | Medium | Adapter / JP Core | The lab unit comes from the lookup, never from OBX-6. A site that reports CRP in mg/L is multiplied anyway. The SQL ignores `Value.unit`. | `services/adapter/mapping/engine.py:371-400`; `jp_core/jlac10_to_loinc.csv`; `source.py:456` | yes | A `source_unit` column; on mismatch emit `valueString` and count it (unknown after R-02); compare units in the SQL. | M | B-09 |
| R-32 | Medium | Audit / service auth | `GET /registry/{ruleset}/export.xlsx` on the orchestrator returns every chart number of a study with no actor and no audit event. `X-TB-Actor` is caller-asserted: a token holder acts as anyone and rotates names to beat the 60/h reveal cap, which lives in memory. | `services/orchestrator/app.py:136-140,243-258,530-543`; `libs/tb_common/service_auth.py:265-273`; `services/console/app.py:1589-1612` | yes | Audit the export with actor and sha; require `X-TB-Actor`. The console signs the actor (HMAC with the session). Rate limit by caller and actor, in Postgres. Alert at 3× the median. | S | S-09 |
| R-33 | Medium | Encodings | A Big5 sheet whose text is only in the header decodes as CP932 mojibake, so the name-column guard does not fire. A CP932 or Big5 REDCap dictionary imports with every label turned into U+FFFD. A non-IR87 HL7 file is decoded as UTF-8 and may abort the read (suspected). EUC-JP and ISO-2022-JP CSVs are not tried. | `services/datacore/sources.py:131-137`; `services/sitesetup/intake.py:52-58`; `services/console/data_pages.py:369`; `adapter/sources/ssmix2/hl7.py` | yes | One shared detector: Taiwan-first or scored, ask when ambiguous, refuse on failure (`FORM-ENCODING`). Big5 fixtures. Per-file error handling in the HL7 reader. | S | B-07, B-08, 02 suspected 3, E-05 (part), 06 §6 item 9 |
| R-34 | Medium | Internal exposure | HAPI has no authentication, is reachable from every container and allows multiple delete. HAPI uses the superuser; the `trialbox` role has CREATEDB; the workflow password falls back to the superuser's. | `deploy/docker-compose.yml:41-45,53-73`; `deploy/docker/db-init/*.sh` | yes | A token interceptor on HAPI, or a narrower network. Separate non-superuser roles and passwords; drop CREATEDB. | M | S-10; F-11, F-21 |
| R-35 | Medium | LLM / prompt injection | `judge_v4.md` has no "the excerpts are data" sentence; there is no injection suite. Chart extraction can be steered to change a proposed fact. The trace store keeps redacted note text for 90 days. | `services/orchestrator/prompts/judge_v4.md:11-16`; `services/sitesetup/service.py:209-213`; `services/tracestore/store.py:1-12,151-156` | yes | The data-only sentence and a delimiter check. A ≥ 50-case ja/zh-TW/en injection suite as a gate. Flag hidden text. Trace store off or shorter in PRODUCTION, and named in the DPIA. | M | S-15; F-17 |
| R-36 | Medium | Update / PHI at rest | Plaintext `pg_dump` files of `hapi` and `trialbox_wf` stay in `deploy/updates/<bundle>/rollback/` after any failure. No expiry, no clean command, no audit of removal. | `tools/trialbox/update.py:14-15,238-240,366-367` | yes | Encrypt with a per-update key, or delete after a checked rollback. `update clean` with a 7-day expiry. Audit the removal. List them in the RUNBOOK retention table. | S | D-14 |
| R-37 | Medium | Model serving | The excerpt budget stops at the first note that does not fit (`break`), so a long newest note hides every older one and the judge gets nothing. The CJK token estimate misses full-width and half-width forms. Safe direction, but recall is lost silently. | `services/matching/cascade/engine.py:67,555-567` (measured) | no | `continue`; hit sentences with context; budget from the profile and the real tokenizer; a reason code for "no excerpts". | S | A-06, 02 suspected 5 |
| R-38 | Medium | Model serving / scale | S3 and S4 are strictly sequential: one request at a time against a 16-sequence vLLM. SCREEN keeps the 2,000-pair LLM budget, so at 50k patients up to ~45 % of pairs can become "unprocessed" with no warning. | `services/matching/cascade/engine.py:98,811-836`; `screen_cascade.py:276-290`; `deploy/docker-compose.rtxpro6000.yml:57,68` | no | Budget from the scope (or none) for screening; fail or flag red when `unprocessed > 0`. Bounded concurrent judging. Re-measure throughput. | M | A-07 |
| R-39 | Medium | Long jobs | A SCREEN cannot be cancelled mid-run and has no circuit breaker. Each call waits up to 600 s. A wedged vLLM is not "down". | `services/orchestrator/core.py:147-150,313-322`; `libs/tb_common/llm.py:137`; `services/gateway/core.py:160` | no | `should_stop()` per pair; fail after N consecutive timeouts; a shorter timeout; a health check that generates one token. | M | A-08 |
| R-40 | Medium | Crash recovery | An orchestrator restart re-runs a job from the start and repeats every model call. On the 5090 the dead job's GPU hold lasts 3,600 s. | `services/orchestrator/core.py:464-468`; `twophase.py:60-95`; `services/gateway/swap.py:17,64-65,103-106` | no | Persist S3/S4 answers under the key the cascade already computes. Release the hold at orchestrator start. Drain jobs before an update restarts. | M | A-09 |
| R-41 | Medium | Reproducibility | "A re-run on the same snapshot is byte-identical" does not hold for note judgements (decision D-116 measured ~9 % judge drift; decision D-139 re-runs only FEAS on the card). Acceptance step 6 requires identical hashes. | `models/routing.yaml:14`; `services/orchestrator/rerun.py:82`; `tools/acceptance.py:44`; `docs/ARCHITECTURE.md` §9 | no | Byte-identical for FEAS and the structured part; note judgements to the recorded agreement rate. Compare SCREEN structurally. Try vLLM's deterministic options. | S | A-10 |
| R-42 | Medium | Cloud secrets | `gpu-sim-startup.sh` and `gpu-fit-test.sh` run `set -x` around the vLLM key, so it reaches the serial console (readable project-wide) and `/var/log`. `tb-key` stays in instance metadata after a run. Port 80 is open; some images are unpinned. | `deploy/gcp/gpu-sim-startup.sh:3-5,22-27,33-36`; `deploy/gcp/gpu-fit-test.sh:13-16,45-49`; `deploy/gcp/complete-run.sh:76-81` | no | `{ set +x; }` around the key lines, or `--env-file`. Remove `tb-key` in `stop_vm`. Restrict port 80. Pin images. Rotate the key. | S | A-12, D-34 |
| R-43 | Medium | Monitoring | No metrics, alerts, disk, GPU or DB monitoring. Only the audit volume checks free space, which turns a full disk into an outage. The admin health page says GPU, disk, backup and chain status "will be added at install", uses jargon, and has no "last run" per timer. | `libs/tb_common/audit.py:108-112`; `services/console/backend.py:324-345`; `deploy/check_host.sh`; seen `/admin?tab=health` | no | A runtime section in `/healthz` and admin tiles: free space per volume, last backup, last ingest, egress loaded, GPU and canary, chain verified at, last run per timer. Optional `/metrics`. A daily health mail. Plain names. | M | A-14, D-22, P-12, O-14 |
| R-44 | Medium | Lifecycle | `anchors()` still uses steps later taken back by `undo`, so a merely consented subject gets due and overdue visits. | `services/datacore/lifecycle.py:300-306`; repro `repro_lifecycle_anchors.py` | no | Use `live_steps()` in `anchors()`. | S | B-04 |
| R-45 | Medium | Backup | A backup of a running box can fail its own check: file hashes are taken before the files are added, and row counts after the dump. A restore then reports a mismatch after it has restored. | `tools/trialbox/backup.py:330-345,357-360`; `docs/RUNBOOK.md:142` | no | Hash the bytes as they stream into the tar. Take counts inside the dump's snapshot. Quiesce, or document it. | M | B-05 |
| R-46 | Medium | Update | If the rollback point fails after the backup stopped the services, the update says "nothing was changed" and leaves them stopped. | `tools/trialbox/update.py:196-202,383-397` | no | Restart when `snapshot` fails, or stop services inside `snapshot`. | S | B-06 |
| R-47 | Medium | Cascade S3 | S3 maps a note "pass" at any confidence ≥ 0.5 to strong (tier high). v1 sends a pass under the 0.75 floor to review. | `services/matching/cascade/engine.py:772-775`; `evaluate.py:540-542` | no | A pass below the floor is "uncertain (low confidence)". | S | B-10 |
| R-48 | Medium | Pseudonym join | Chart numbers are hashed as written. Leading zeros that Excel drops, and upper-case hex keys, give different pseudonyms. A PI's sheet then makes phantom patients whose facts never join the hospital record. Nothing lists sheet pseudonyms missing from the feed. | `sitesetup/service.py:109-111`; `adapter/mapping/engine.py:259-263`; `tb_common/crypto.py:40`; `datacore/sources.py:95-99,213` | no | One shared chart-number normaliser (the site's MRN rule). List unmatched pseudonyms at publish. One record-key rule in `sync.Row`. | M | B-15, B-16 |
| R-49 | Medium | Gateway | The gateway routes and authorises on the self-declared `X-TB-Caller`. Any accepted service can claim `orchestrator`, `eval` or `testbench` (`roles: ["*"]`) and hold or release the GPU. | `services/gateway/core.py:172-203,225,238-248`; `models/routing.yaml:107-142` | no | Use `request.state.tb_caller` and refuse a mismatch. Drop `testbench` and `eval` from production routing. Bind holds to a job id. | S | S-08; F-12 |
| R-50 | Medium | Key custody | Site keys are created silently on first use. A restore without them silently re-keys and splits the pid map. | `libs/tb_common/crypto.py:43-52`; `services/adapter/pipeline.py:52`; `services/adapter/pidmap.py:52` | no | `trialbox keys init` at install with an audited ceremony and shares. Refuse auto-creation in VALIDATION and PRODUCTION. Wrap with the R-05 key. | S | S-11; F-10 |
| R-51 | Medium | Images / containers | vLLM is pinned by tag on the x86 profiles; the Python base and GCP images by tag. No `cap_drop`, `no-new-privileges` or `read_only` on production services; `ipc: host` on vLLM. | `deploy/docker-compose.yml:210,233,244`; `rtx5090.yml:49`; `rtxpro6000.yml:31`; `deploy/docker/python.Dockerfile:7` | no | Digest-pin every image; the bundle refuses a digest mismatch. `cap_drop: [ALL]`, `no-new-privileges`, `read_only` with tmpfs. Reviewers differ on `ipc: host` (§2.3). | M | S-13, D-05, D-04 (hardening part); F-14 |
| R-52 | Medium | Passwords | Length ≥ 12 only; no breached list; no history (MHLW "no reuse" unmet). Lockout is per username only, so anyone can lock every PI out before clinic; no per-IP throttle. | `services/console/auth.py:34-36,110-115,322-350`; `services/console/home.py:814-823` | no | Delay per IP and per account; a top-100k breached list; last-5 history; alert on lockout bursts. | S | S-14; F-22 |
| R-53 | Medium | Transport | No TLS in the product; the Secure cookie defaults to 0; the hospital proxy has no reference config, certificate check or package. Internal links are plaintext. | `deploy/docker-compose.yml:195-216`; `tools/trialbox/doctor.py:171-178`; `docs/RUNBOOK.md` §9 | no | A digest-pinned Caddy or nginx overlay on 443 with the hospital certificate. Secure cookie by default in PRODUCTION. A certificate-days check in `doctor`. One table of the four proxy variables. | M | S-16, D-29; F-09 |
| R-54 | Medium | Egress | Docker's embedded DNS stays open: every container has a DNS exfiltration channel. The allowlist is resolved at apply time; `EGRESS_EXTRA` applies to any service. | `deploy/egress.py:19,171-215` | no | A local resolver that answers only the allowlist, with logging. Re-apply at WSL boot. `check_host` verifies. | M | S-17; F-13 |
| R-55 | Medium | Install | `install.sh` exits 0 and prints "running" although `check_host.sh` reported FAIL lines. | `deploy/install.sh:321-330` | no | Exit 4 on any FAIL unless `--accept-host-fail`; repeat the FAIL lines at the end. | S | D-02 |
| R-56 | Medium | Install | With `settings.yaml` but no `.env`, install copies `.env.example`: test mail hosts, site id `DEMO-A` and the hash embedder reach production. | `deploy/install.sh:164`; `.env.example:2-20` | no | Refuse, or rebuild `.env` from `settings.yaml`. Never copy `.env.example` on a site box. | S | D-03 |
| R-57 | Medium | Windows / WSL2 | `check_host.sh` will FAIL LUKS and swap on every WSL2 box. The nightly cron and console timers need WSL awake. No TLS proxy package or step. `SHA256SUMS.sig` is promised but not checked. | `docs/handover/WINDOWS-INSTALL-CHECKLIST.md`; `docs/handover/OFFLINE-MEDIA.md:11,23`; `deploy/check_host.sh:25-30`; `deploy/install.sh:134-137` | no | A `--wsl2` mode (BitLocker via `manage-bde`, `.wslconfig` swap=0); a Windows task that keeps the distro alive; the proxy package and step; verify `SHA256SUMS.sig`. | M | D-08 |
| R-58 | Medium | Compose / 5090 | The 5090's start-order helpers are one-shot. After a power cut both vLLM servers start awake and the verifier crash-loops until someone runs compose. | `deploy/docker-compose.rtx5090.yml:105,131,141` | no | A `trialbox.service` systemd unit owns the stack (`up -d --wait`, restart on failure). | S | D-10 |
| R-59 | Medium | Update / migration | A migration failure after other services migrated restores both databases (losing rows written in the window) but not the file stores (rulesets git, objects). | `libs/tb_common/db.py:155-175`; `tools/trialbox/update.py:440-443,468-476` | no | Migrate in a one-shot before services take traffic. Roll back `rulesets-data` to a tag. Document the append-only stores. | M | D-16 |
| R-60 | Medium | Update / refdata | The 2.2 GB reference pack is copied into a container's writable layer, never removed, and inflates every rollback dump and backup. A refdata failure triggers a full rollback. | `tools/trialbox/update.py:453-457`; `deploy/install.sh:284-292` | no | Bind-mount the staged pack read-only. Load refdata as its own step with its own rollback. Exclude schema `refdata` from the rollback dump. | M | D-17 |
| R-61 | Medium | Support | No PHI-free support bundle. RUNBOOK §7 asks for files by hand; nothing redacts `.env`. | `docs/RUNBOOK.md` §7; `tools/trialbox/__main__.py` | no | `trialbox support-bundle`: release id, history, doctor and check_host output, redacted compose config, the nine services' scrubbed logs, `audit_verify`, `df`, `nvidia-smi`. Never HAPI or Postgres logs or `/data`. | S | D-23 |
| R-62 | Medium | Configuration | About 100–120 `TB_*` names (the two reviewers count differently), 55 undocumented, read from four places. `doctor` treats an unset `TB_ENV` as DEV while the services treat it as PRODUCTION, so a misconfigured production box passes `check_host`. | `libs/tb_common/config.py:229-232`; `tools/trialbox/doctor.py:71,83,175,214,235`; `deploy/egress.py:116` | no | `doctor` uses `environment_name`. One declared list of every variable, a generated reference and a lint test. Service-only knobs out of `.env`. | M | D-25, E-12 |
| R-63 | Medium | Unsafe defaults | If left: Secure cookie 0; the workflow DB password falls back to the superuser's; test passwords in `.env.example`; HAPI multiple delete on; a wrong forwarded-IPs value breaks sign-in silently. | `deploy/docker-compose.yml:43,72,201,204`; `.env.example:11,40,44-48` | no | Install writes the Secure cookie on and asks for the proxy address. Drop the password fallback. `check_host` FAILs on `change-me`, `greenmail`, `mailhog`, `hospa.test`. | S | D-26 |
| R-64 | Medium | Secrets rotation | `secrets rotate --service db` changes the roles before it writes `.env`. A failure in between leaves the box without its database and with no recovery command. | `tools/trialbox/svc_secrets.py:221-234,237-277` | no | Write `.env.new` first; one transaction; `os.replace`; print the revert. Keep a 24 h copy. Show the backup key fingerprint in `secrets status`. | S | D-27 |
| R-65 | Medium | Hosted demo | The internet-facing demo has one shared password in project-readable metadata and in `docker inspect`. It applies an unsigned `tb-patch` from metadata at boot (code execution for anyone who can edit metadata). Shared-account lockout is a denial of service. A failed build keeps serving the old image. | `deploy/gcp/hosted-demo-startup.sh:16-17,32-36,47,50-53,65-66` | no | Secret Manager; per-visitor passwords or IAP; pin the base commit and drop `tb-patch`; lockout per IP; fail the boot on build failure; Secure cookie; a cloud-side run cap. | M | D-33 |
| R-66 | Medium | Parsers / tests | No property or fuzz tests for parsers. The home-grown HL7 parser ignores MSH-2 encoding characters, sub-components and repetitions. Era and 民國 date rules exist in six modules, each slightly different. | `services/adapter/sources/ssmix2/hl7.py`; `tb_common/phi_guard.py`; `orchestrator/scenarios/case.py`; `sitesetup/messy.py` and three more | no | `hypothesis` round-trip tests. python-hl7 for parsing. One `tb_common.dates` module with property tests. | M | E-05 |
| R-67 | Medium | Tests / goldens | 18 in-process integration files (63 tests) have no marker and run in no CI job. There is no committed golden of the per-ruleset funnel counts. | `tests/integration/*.py`; `tests/conftest.py` | no | Mark or move them and run them in CI. Commit a funnel golden with `--update-golden`. | S | E-06 |
| R-68 | Medium | Code quality | 29 F-grade and 29 E-grade functions (`e2e_simple.run` CC 162, `public_e2e.run` 146, `build_pack` 106). `console/app.py` has 1,724 lines. i18n is Python dicts. Some report and regex code is duplicated. | `radon cc -s`, `radon mi -s` (review 04) | no | A stage registry for the e2e tools; split `build_pack` and `console/app.py`; i18n as data; shared report helpers; one PHI regex module; a complexity limit in lint. | M | E-07, E-15 |
| R-69 | Medium | Repository / licence | The repository root is still Auto-GPT (6,115 lines, README, Dockerfile, committed LLM outputs, MIT licence) while `trialbox` says Proprietary and has no LICENSE or third-party notices (axe-core MPL-2.0, htmx). Large generated files; a nested `rulesets/.git`. | `git ls-files` at the root; `LICENSE`; `trialbox/pyproject.toml`; `tools/vendor/axe.min.js`; `tools/testbench/static/htmx.min.js` | no | Remove the legacy tree. Add `trialbox/LICENSE` and `THIRD_PARTY_NOTICES.md`. Ignore `rulesets/.git/`. Stop committing per-run predictions. | S | E-08, E-09 |
| R-70 | Medium | Dependencies | `fhir.resources` is declared and never imported. SQLAlchemy is used by one source. `pytest-cov` is missing from dev. | `grep "from fhir.resources"` = 0 | no | Remove it; SQLAlchemy as an optional extra; add the test tools to dev. | S | E-10 |
| R-71 | Medium (raised) | OCR | OCR has never run on a real scan. `doc_parser._ocr_pdf` hard-codes `lang="chinese_cht"`, so Japanese scans are never read correctly. No scanned fixture. Raised from Low: 06 lists it as pilot blocker O-08 for a paper site. | `services/doc_parser/parser.py:128-143`; `sitesetup/ocr.py`; decision D-135 "Not done" | no | `lang` from the site language. One scanned-PDF fixture per language. An OCR-quality warning on the chart page. | S | E-14 (OCR part), 06 §2 S4, O-08, 04 library table |
| R-72 | Medium | Language | Feasibility and approval pages show the study's English short labels on ja and zh-TW pages. | `feasibility.html:63`; seen `/studies/PUB-ONC/feasibility` | no | Use the site label. Make the label editor mandatory at approval for non-English pages. | S | P-06, O-10 (part) |
| R-73 | Medium | Wording | The set-up page says "Nothing is ever written to REDCap" right under the write-back switch. Enrolled and approached each have two words across pages. | `console/i18n_step3.py:57,161,265`; `console/i18n.py:731-734,1090-1093`; `i18n_life.py:189-195,362-368` | no | "TrialBox writes only its own three screening fields to its own instrument" in three languages. One word per state, held by the glossary test. | S | P-07, P-08, O-11 |
| R-74 | Medium | CRC workflow | Contact outcomes miss "treating doctor declined", "family declined" and "patient wants time". | `console/sitestore.py:40-46`; `i18n_step2.py:75-84` | no | Add the three, with registry statuses and a retry date. | S | P-09, O-12 |
| R-75 | Medium | Confirmations | No confirmation on Disable account, Reset password, Keep/Take a value, Detach REDCap or Approve all. No undo for outcomes or conflict decisions. | `users.html:69`; `data_conflicts.html:24-25`; `data_sources.html:24`; `approval.html:47` | no | One confirm sheet that names the consequence. Undo in the toast for conflicts. | S | P-10, P-28, O-15 |
| R-76 | Medium | Consistency | PI pages read participants without refreshing. The PI's enrolment report showed 3 while the screening log had 4. | seen `/studies/PUB-ONC/enrolment` vs `/screening-log` | no | Refresh where the number is issued, or on any read. | S | P-11, O-16 |
| R-77 | Medium | Feasibility honesty | The headline (1.33 consents a month, 16.0 in 12 months) rests on default rates shown nine screens lower, with decimals on counts. §11 says "about 6 %" lost on TREC 2021–2023; VALIDATION and decision D-130 say 3.1 % on 2021/22, and N-12 is a projection on English topics. §9 says there is no registry link, though decision D-140 added one. | `feas_compute.py:390-415`; `services/console/i18n_home.py:253,526,799`; `eval/trec_ct/results/n12_deployed_2026-11-08.md` | no | Assumptions on the headline card; integers; the band first. One validation sentence from one source, marked "projected". Reword §9 by `TB_CTGOV_MODE`. | S | P-13, P-14, P-29, O-10 |
| R-78 | Medium | Help | Ask TrialBox answers two canned questions; a natural question gets a wrong answer. | seen `/ask?q=…` (pi ja, crc zh-TW) | no | Say what it can answer. Route the rest to help sections and the site contact. | M | P-15, O-17 |
| R-79 | Medium | Site set-up | Only the first worksheet is read. Five analytes are known. Each confirm republishes the lake (minutes per tap at `main` scale). Pasted text without a chart number is refused. Cells cannot be fixed in TrialBox. Feed codes are not on the mapping page. | `sitesetup/intake.py:50`; `messy.py:208-275`; `sitesetup/publish.py` | no | Read every sheet, or ask. Analytes from `lab_local_to_loinc.csv`. Batched apply on `main`. A temporary key for charts without a number. | M | P-16, P-17, O-18 |
| R-80 | Medium | Interoperability | REDCap: arm 1 only, one event, no repeating instruments, some field types as text; never run against a real REDCap. The trial-data FHIR export is only on an internal route. ODM repeat key is always 1; no ODM import. | `datacore/sources.py:36-95`; `datacore/forms.py:91-110`; `orchestrator/datacore_api.py:409`; `datacore/export.py` | no | A nightly test against a real REDCap project. Arms and repeating instruments. FHIR on `/api/v1`. ODM repeating item groups for AEs and deviations. | M | P-18, P-19, O-05, O-20, O-21, 06 §2 S3 |
| R-81 | Medium | CGRD | The `cgrd_sql` template assumes identifying HIS views. CGRD itself is de-identified and yearly, so it gives feasibility only. The docs do not say so. | `adapter/mapping/templates/cgrd_sql_site.yaml` | no | Say it in DATA §1. A readiness line: "this feed has no chart numbers: feasibility only". | S | P-20, O-22 |
| R-82 | Medium | Phone | Native date inputs show `mm/dd/yyyy` on ja and zh-TW. The phone sheet opens under the long list. | seen (pi, ja, phone) | no | `lang` and a placeholder on dates; scroll-restore on Back. | S | P-22 |
| R-83 | Medium (raised) | Help / training | No ja or zh-TW user guide or one-page role sheet; `/help` says guides come "at install". Raised from Low: 06 lists it as pilot blocker O-09. | `/help` (pi, ja); decision D-139 | no | One printable page per role, from the help catalogue. USER_GUIDE in ja and zh-TW. | M | O-09, P-27 |
| R-84 | Medium (raised) | Real Japanese data | Real vendor SS-MIX2 storage and real MEDIS, JLAC10 and YJ files have never been read; the licensed lists are 10-row samples. If MEDIS prints ICD-10 without the dot (`M109`), every licensed lookup misses (safe, but the feature does nothing; suspected). Raised: 06 lists O-07 as a pilot blocker for a Japanese site. | `tests/fixtures/licensed/`; `_icd()` in the SS-MIX2 source; decision D-137 | no | A 10-patient sample from each Japanese site before install. Load the real releases. Normalise dotless codes. | M | O-07, 06 §2 S10 and S12, 02 suspected 2 |
| R-85 | Low | Site set-up units | For urate in mmol/L the unit check offers only "mg/dL" or "drop"; choosing mg/dL stores 0.42 unconverted. | `messy.py` (`_lab_cell`, `convert`) | yes | Reword the option. Add urate and creatinine mmol/L conversions. | S | B-13 |
| R-86 | Low | Logs | The log scrubber does not remove names, addresses or free text. A stack trace with a note excerpt reaches logs kept 365 days. | `libs/tb_common/logging.py:14-27,60-69` | yes | `Guard.redact` on exception and ERROR text; cap exception text. | S | S-22; F-23 |
| R-87 | Low | Lake scale | The cascade loads a year of notes for every alive patient in one Arrow table and keeps it in memory; `list_contains` on a long list. | `services/matching/cascade/engine.py:264-268,533-552` | no | Page by patient batch; join a temp table; keep only hit sentences. | M | A-15 |
| R-88 | Low | Start order | Only console and fhir-store wait for `db`; the others crash-loop at boot, and each loop starts a canary. | `deploy/docker-compose.yml:58-59,212-216` | no | `depends_on: db: service_healthy` everywhere. | S | A-16 |
| R-89 | Low | Throughput | All profiles use `--enforce-eager`, never measured against CUDA graphs. | `deploy/docker-compose.rtxpro6000.yml:58,69` and the other profiles | no | Measure once without it on the PRO 6000; a new serving record if it passes. | S | A-17 |
| R-90 | Low | Canary | The pair canary (108 calls) runs at every orchestrator start; a crash loop churns the GPU; overlapping canaries are guarded by a non-atomic flag. | `services/orchestrator/canary_gate.py:214-237`; `app.py:112,169-183` | no | Skip when a passing report is under 2 h old; a lock; never while a SCREEN holds the card. | S | A-18 |
| R-91 | Low | Audit atomicity | Job state and outputs reach Postgres before the audit line; a crash in between leaves an output with no audit record, invisible to `audit_verify`. | `services/orchestrator/core.py:165-192,296-311` | no | Write the audit line first, or reconcile at start. | S | A-19 |
| R-92 | Low | State outside Postgres | The inventory of state outside `trialbox_wf` (canary report, rulesets git, objects, audit, keys, lake, memory) matches the docs. | `services/orchestrator/canary_gate.py:71-83`; `deploy/docker-compose.yml:268-278` | no | List it in RUNBOOK §5 and check it in `backup_drill`. | S | A-21 |
| R-93 | Low | Console audit page | `/audit` reads the newest 1,000 events from JSONL files on every load. No N+1 queries were found. | `services/console/backend.py:158-191` | no | Index by day in Postgres or cache the tail; measure page times. | S | A-22 |
| R-94 | Low | Site set-up labs | `<0.3`, `8.4 H` and `陰性` lab cells vanish with no fix and no "please check" item, against decision D-132. | `services/sitesetup/messy.py:508-511` | no | A `lab_unreadable` check and a readiness count. | S | B-11 |
| R-95 | Low | Dates | `112年3月15日` (ROC year without 民國, the usual Taiwanese form) is unreadable. | `messy.py` (`_MINGUO`, `_ROC3`) | no | Make the prefix optional for years 1–150 followed by 年. | S | B-12 |
| R-96 | Low | Backup prune | `prune` matches every site's files; two boxes on one NAS folder prune each other. | `backup.py` (`prune`) | no | Match by site. | S | B-14 |
| R-97 | Low | Account expiry | Expiry compares the UTC date with a local end date (up to 9 h over in JST). | `console/auth.py:235-236` | no | Compare in the site zone. | S | B-17 |
| R-98 | Low | Code hygiene | 65 S608 and 82 B608 "SQL from strings", none injectable today. 105 guard asserts vanish under `python -O`. | `ruff --select S`; bandit (review 03 §3) | no | Parameter lists where cheap; `raise` instead of guard asserts; S rules in CI. | S | S-18; F-20 |
| R-99 | Low | SSRF | The REDCap URL check allows `http://` internal hosts; live CT.gov does not re-check `nct_id`. | `services/rc_bridge/client.py:57-61,101-103`; `criteria_compiler/ctgov.py:129-130` | no | https only outside DEV/TEST and a host allowlist; validate `nct_id`. | S | S-20 |
| R-100 | Low | Regulatory wording | "Not a medical device" appears only in `case_html.py:23`, not on pages, PDFs, mail or the sponsor pack, though SECURITY says every report says so. | `grep 医療機器` = 1 hit | no | In the page footer, every PDF and the sponsor-pack README; a forbidden-word check in the walk. | S | S-21 |
| R-101 | Low | Secrets hygiene | Mail and cloud passwords live in `.env` (0600), not compose secrets; no secret scanner in CI. Otherwise clean. | `.gitignore:9,19,24`; `tools/trialbox/svc_secrets.py:93-117` | no | Compose secrets for the three passwords; gitleaks in CI. | S | S-23 |
| R-102 | Low | Error handling | 88 `except Exception` (13 swallow), one bare `except:`, 1,458 `Any` in services. | counts in review 04 | no | ruff BLE001 and S110 with a reasoned allow-list; typed payloads at the orchestrator boundary. | M | E-13 |
| R-103 | Low | Test flakiness | 16 sleeps, 10 unfrozen clocks, 3 fixed ports; no random order in CI. A random-order sample found no order dependence. | counts in review 04; `pytest -p randomly` sample: 391 passed | no | `pytest-randomly`, `time-machine` and `pytest-socket` in dev and CI. | S | E-16 |
| R-104 | Low | Docs accuracy | README says the venv has "pinned dependencies" (false). The `e2e_simple` time is "about 2 minutes" (README), "75 s" (Makefile), "115 s" (VALIDATION); measured 109 s and 152 s. One stage number is skipped. | `README.md` l.40–41; `Makefile` l.50; `docs/VALIDATION.md` | no | Fix the sentences; doclint checks `make` targets. | S | E-17, P-31 |
| R-105 | Low | SELinux | Bind mounts have no `:z`; RHEL in enforcing mode denies them. | `deploy/docker-compose.yml:24,127,160,172,193` | no | State "Ubuntu 24.04 only" and FAIL elsewhere, or label the mounts. | S | D-06 |
| R-106 | Low | Scripts | Five shellcheck items, including an unchecked `cd` in the hosted-demo script that can build a stale image. | `deploy/install.sh:57,121,321`; `deploy/check_host.sh:35,42,71,95`; `deploy/gcp/hosted-demo-startup.sh:37` | no | Fix the lines; shellcheck in lint. | S | D-07 |
| R-107 | Low | Health wait | A GB10 cold start can exceed the 900 s `up --wait`; a false install failure triggers a rollback. | `deploy/docker-compose.gb10.yml:53,91`; `deploy/install.sh:266` | no | 1,800 s by default for gb10 and rtxpro6000. | S | D-09 |
| R-108 | Low | Restore | `restore` assumes Linux Docker volume paths and does not stop the services; RUNBOOK omits the stop. | `tools/trialbox/backup.py:58-67,463-503` | no | `restore --compose`: stop, restore through the containers, restart. | S | D-21 |
| R-109 | Low | Logs | 5 × 50 MB per container can drop hours of HAPI logs on busy days; collection cuts by UTC day. | `deploy/docker-compose.yml:9-11`; `tools/trialbox/logs.py:92-109` | no | Larger caps for HAPI and db, or collect twice; note the UTC boundary. | S | D-24 |
| R-110 | Low | Network sheet | The sheet is accurate, but it does not say egress depends on an unpersisted table, omits host listeners, does not warn on `EGRESS_EXTRA` and omits the rollback dumps. | `docs/handover/network-sheet.en.md`; `tools/network_sheet.py:266-282,328-362` | no | A Host section, the two warnings and the dumps row. | S | D-28 |
| R-111 | Low | Offline media doc | OFFLINE-MEDIA promises `SHA256SUMS.sig` and a two-key comparison; install checks neither. | `docs/handover/OFFLINE-MEDIA.md:11,23`; `deploy/install.sh:134-137` | no | Implement it, or correct the document. | S | D-37 |
| R-112 | Low | Wording ja / zh-TW | Colon spacing in errors; a Japanese middle dot in zh-TW; "第一次確認 / 第二次確認" reads as two human checks; `声かけ済み` register; `許容範囲超過`; mail gateway still says サインイン; English service names on admin pages. Flagged by a non-native reader. | seen pages; `i18n_life.py` | no | Ask the sites' CRCs; fix the catalogues. | S | P-24, P-25, P-26, O-24 |
| R-113 | Low | Visit windows | No reminder when a visit window is about to close; only the overdue list. | decision D-134 "Not done"; seen (crc, ja, home) | no | "Closes in 2 days" in N2 and on the visit list. | S | P-30, O-19 |

Where "F-xx" appears in sources, the 2026-11-08 standards and security review found the same thing and it is still open.

### 2.2 Suspected, not proven (review 02), not merged above

| Item | What is suspected | Why it matters | Needs |
| --- | --- | --- | --- |
| 02 suspected 6 | HbA1c JDS vs NGSP: Japanese values before 2012-04 are 0.4 lower, same `%` unit, no conversion | Historical windows only | A rule by date |
| 02 suspected 7 | `Coverage` counts NHI-coded medicines without ATC as unreadable | More unknowns (noise), not a wrong exclusion | Check against `generator.PRESENCE` |
| 02 suspected 8 | `refdata.ctgov_search` LIKE escaping relies on Postgres's default backslash escape | Correct on Postgres; would break elsewhere | Nothing now |
| 02 suspected 9 | `find_header` takes a two-cell title row as the header | Usually caught by the `chart_column` check | A real sheet |

Suspected items 1 to 5 are merged into R-08, R-84, R-33, R-02 and R-37.

### 2.3 Where reviewers disagree

| Topic | What each says | Taken here |
| --- | --- | --- |
| MFA severity | 03: Blocker (S-02). 06: Medium (P-23) but pilot blocker O-13. 2026-11-08: High (F-04). | Blocker (R-04) |
| Counts inside two reports | 03's summary says 2/6/10/5; its table has 5 High and 6 Low. 06's summary says "1 blocker, 9 high"; its table marks 4 High. | Counted from the tables |
| Container limits | 01: High (A-05). 05: Medium (D-04). | High (R-17) |
| `ipc: host` | 03: replace it with `shm_size` (S-13). 05: keep it on the vLLM services only (D-04). | Open; measure vLLM with `shm_size` first (R-51) |
| Key in the serial log | 01: Medium (A-12). 05: Low (D-34). | Medium (R-42) |
| Supply chain | 03: High (S-06). 04: High (E-03). 05: Medium (D-36). | High (R-19) |
| Cloud cap command | 01 proposes `instances update --max-run-duration` and asks to verify the flag. 05 checked `instances set-scheduling --max-run-duration --instance-termination-action=STOP` on gcloud 570; it works only while the VM is stopped. | 05's command (R-14) |
| Cause of today's auth failure | 01 infers a bare access token (one-hour expiry). 05 infers a failed refresh of a service-account key (clock skew, a cleaned temp config, or a disabled key). Neither saw logs. Decision D-139's run commands activate a key file, which fits 05's reading. | Unknown. The fix is the same either way: a cloud-side cap and the VM's own credential. |
| 疑い flag field | 02: PRB-13, reader reads PRB-3/4/14/16. 06: the PPR-01 flag, reader reads PRB-2/3/14/16. | Confirm on the spec or a sample (R-08) |
| Byte-identical re-runs | 04 lists them as a strong oracle. 01 says they do not hold for the pair. | Both true: on the stub yes, with the pair no (R-41) |
| `TB_*` variable count | 04: 98 read in code, 55 undocumented. 05: about 121 in `libs/` and `services/`. | Different counting; the fix is the same (R-62) |
| `e2e_simple` time | 04: 109 s. 06: 151.8 s. VALIDATION: 115 s. | Host-dependent; budget 15 min (R-104) |

## 3. Fix plan in waves

Effort is engineer-days: S = 1, M = 3–4, L = 8–10. Totals are rough.

### Wave 1: before any further GPU run and before any pilot (patient safety and correctness)

| Finding IDs | Done-check |
| --- | --- |
| R-01 gateway refuses PHI prompts | A compose-level test with `TB_DATA_CLASS` unset and `TB_ENV=PRODUCTION` drives a judge call through the real gateway app and gets an answer. `doctor` fails when the gateway would refuse. The PRO 6000 builds have their `sha256` filled. |
| R-02, R-31 non-numeric labs; lab units | `repro_lake.py` part A gives `P-TEXT None`, tier review, reason `unknown_value`. The CQL oracle agrees. A unit mismatch is counted and gives unknown. |
| R-06 not-in-snapshot as excluded | `repro_lake.py` part B gives tier review with `not_in_snapshot`; the reason shows in ja and zh-TW. |
| R-03 chart number on the CASE page | The walk's new sweep finds no chart number on any page for PI, viewer and CRA, in three languages. `/jobs` and `/audit` are refused to viewer and investigator. |
| R-09 fatal SAE; PI acknowledgement | An e2e stage: a fatal SAE stays on the banner and in N1 until a PI acknowledges it; a "report by" task appears. |
| R-07, R-08 excluded list with reasons; 疑い | The excluded page lists every excluded patient with a reason. An SS-MIX2 fixture with 疑い ends "unknown", never excluded. |
| R-13 DB reconnect | A test restarts Postgres under a running service; the next call succeeds; the console's `/healthz` fails while the DB is down. |
| R-10 REDCap longitudinal blanking | `repro_sync_blank.py` keeps `en_date` after two syncs. Attaching a longitudinal project without `event` is refused. |
| R-32 registry export without audit; `X-TB-Actor` | A direct export call without an actor is refused; with one it is audited with the sha. A forged actor fails the console signature check. |
| R-14 cloud-run fail-safe | `describe` shows `maxRunDuration` and `STOP`. Killing the driver mid-run leaves the VM `TERMINATED` within the idle window. A killed run resumes from `parts/`. |
| R-42 vLLM key in the serial log | `get-serial-port-output` contains no key. `tb-key` is gone from metadata after a run. The old key is rotated. |
| R-37, R-38 excerpt budget; 2,000-pair budget | A unit test with a long newest note still gets excerpts. A 50k SCREEN reports `unprocessed = 0` or fails red. These two make Gate G1 measure the right thing. |

**Effort: about 30–40 engineer-days** (9 M, 6 S): 6–8 weeks for one engineer, 3–4 weeks for two.

### Gate G1: the 50,000-patient scenario run (after Wave 1)

The run of §4 on the RTX PRO 6000 with the real pair, through the production gateway path, in ja and zh-TW. It closes R-15 (O-01) and checks R-01, R-02, R-06, R-08, R-10, R-37 and R-38 on data.

Done-check: the run report is green in both languages. Stage 3 says "the pair ran, the canary passed, a note excludes only when both agree". `unprocessed = 0`. The VM stops itself. Cost near decision D-139's estimate (about 4.9 h, about US$13.50).

### Wave 2: security and compliance for pilot sign-off

| Finding IDs | Done-check |
| --- | --- |
| R-04 TOTP/MFA and AD/LDAP; R-52 password policy | TOTP enforced; `doctor` FAILs in PRODUCTION without it. An LDAP bind test. A step-up before reveal and exports. Forced change at first sign-in. A breached-password and history test. |
| R-11 header SSO | OIDC or LDAP replaces header SSO, or the interim socket rule holds; a forged header from a bridge peer is refused; rejections are coalesced. |
| R-05 keys and PHI at rest; R-50 key ceremony; R-57 WSL2 path | On a Windows test box, preflight FAILs without BitLocker, with WSL swap or with hibernation. Both keys are wrapped. `phi` outputs and chart uploads are encrypted at rest. `keys init` runs at install. A `--wsl2` check mode exists. |
| R-18 keyed, append-only audit chain with off-box archive; R-91 audit atomicity | `audit_verify` fails on a removed and recomputed line. Signed heads land on the hospital share. Only one container writes `audit-data`. NTP unsynchronised is a FAIL. |
| R-12 PPAP default changed to link | The default attach mode is a link. A `phi` attachment by zip is refused. `internal_domains` tests pass. |
| R-19 pypdf and pillow upgrades, hashed lock, `pip-audit` gate, SBOM | `pip-audit` is clean in CI. The venv and the image install from one hashed lock. The bundle carries a CycloneDX SBOM. |
| R-20 backups default off-box, including HAPI | `doctor` FAILs on a local-only target. A backup contains the HAPI dump. |
| R-22 egress rules persisted; R-54 DNS egress; R-110 network sheet | After a reboot `check_host` finds the table loaded. Containers resolve only allowlisted names. The sheet says so. |
| R-49 gateway caller; R-34 HAPI and Postgres roles; R-35 prompt injection; R-51 image pins and hardening; R-53 TLS; R-63 unsafe defaults | Gateway refuses a caller mismatch. HAPI refuses a call without a token. The injection suite passes as a gate. Every image is digest-pinned and hardened. The console is reached only over TLS with a Secure cookie. `check_host` FAILs on test values. |
| R-33 encodings (name-column guard); R-86 log scrubbing; R-97 expiry zone; R-99 SSRF; R-100 disclaimer; R-101 secrets hygiene | Big5 fixtures read right and drop the name column. Names are scrubbed from ERROR logs. The disclaimer is on every surface. gitleaks runs in CI. |

**Effort: about 55–65 engineer-days** (2 L, 9 M, 15 S).

### Wave 3: operations

| Finding IDs | Done-check |
| --- | --- |
| R-21 scheduled backups and the backup-age alert; R-45 live backup checks; R-96 prune; R-108 restore | A nightly backup runs on a compose box; the admin tile shows its age and turns red after 36 h; a failure mails the admin; a restore drill passes. |
| R-23, R-24, R-25, R-36 update safety: crash marker, free-space preflight, anti-rollback, the plaintext dump; R-46, R-59, R-60 | `update status` reports an interrupted update. A disk-full preflight refuses with numbers. An older bundle is refused. No plaintext dump survives a finished update. |
| R-26 compose, update and rollback on Docker | The compose drill passes: good bundle, bad migration, unhealthy release, disk full, kill -9 at each step. The demo-VM commands of decision D-138 have run. |
| R-27 release identity: version, tags, changelog | `/healthz` and the admin page show the release id and digests. A git tag and a CHANGELOG entry exist for the release. |
| R-43 monitoring; R-61 PHI-free support bundle | The admin tiles show disk, GPU, backup, chain and timers. A support bundle scanned for chart numbers and names finds none. |
| R-17 container limits; R-58 5090 restart; R-88 start order; R-90 canary at start; R-107 health wait | Compose config shows limits per service. A power-cycle test brings the 5090 stack back alone. |
| R-16 the mail "uncertain" resolution path | A simulated MTA outage releases the keys; the next run sends; `mail resolve` clears a stuck key; a finished job never fails on mail. |
| R-65 hosted demo exposure | The demo password is in Secret Manager; no `tb-patch`; a run cap is set. |
| R-39, R-40 cancel and crash recovery; R-41 reproducibility wording | Cancel stops a running SCREEN within one pair. A restart re-uses persisted answers. Acceptance compares SCREEN structurally. |
| R-55, R-56, R-62, R-64 install and config; R-92, R-105, R-109, R-111 | Install exits non-zero on FAIL; `doctor` and the services agree on `TB_ENV`; every `TB_*` is declared; rotation survives an interruption. |

**Effort: about 65–75 engineer-days** (15 M, 18 S).

### Wave 4: engineering

| Finding IDs | Done-check |
| --- | --- |
| R-28 CI: full suite, lint, mypy, doclint, contracts, golden counts (R-67), audit, container build | CI is green on push to master with every job; a nightly job builds images and runs `public_e2e` and `update_drill`. |
| R-29 opt-in Postgres fixture with cleanup and xdist | No schema or cluster is left after a run, even a killed one. The suite takes about 5 min with `-n auto`. |
| R-66 parser property tests, one dates module, python-hl7; R-95 ROC dates | `hypothesis` tests on HL7, dates and CSV encodings pass. One `tb_common.dates` module is used everywhere. |
| tenacity (§5) | The client-side retry loops use one declared policy. |
| Performance fixes (§5): ruleset cache, DuckDB connection reuse, sqlguard cache, compiled mapping paths | `e2e_simple` goes from about 109 s to 60–70 s on the same host; a `perf` test holds each gain. |
| R-71 OCR language | One scanned PDF per language reads right; `lang` follows the site. |
| R-69 repo cleanup (legacy Auto-GPT root, licences, third-party notices); R-70 unused dependencies | The root has no Auto-GPT tree; `trialbox/LICENSE` and the notices exist. |
| R-68 complexity hot spots; R-102 error handling; R-98 SQL strings and asserts | A complexity limit in lint passes; no swallowed exception without a reason comment. |
| R-87, R-89, R-93 scale and throughput; R-103 flakiness; R-104 docs; R-106 shellcheck | Notes paged by batch; one measurement without `--enforce-eager`; random-order CI; the README and Makefile agree. |

**Effort: about 30–35 engineer-days** (4 M, 13 S, plus about 5 days for performance and tenacity).

### Wave 5: product completeness for the pilot

| Finding IDs | Done-check |
| --- | --- |
| R-77 feasibility number honesty (P-13, P-14); R-72 labels | The headline card states its assumptions; one validation sentence from one source; site labels on feasibility and approval pages. |
| R-30 PI list priority; R-47 low-confidence pass | The PI list sorts by unknowns and visit; a 0.55-confidence pass is not "high". |
| R-73 true wording; R-74 contact outcomes; R-75 confirmations; R-76 refresh | The walk checks each sentence, outcome, confirmation and count. |
| R-80 interoperability and real REDCap; R-84 real Japanese data; R-83 role guides | For each pilot site: a real REDCap round trip (REDCap site), a vendor SS-MIX2 sample read (Japanese site), a printed one-page guide per role. |
| R-79 site set-up limits; R-48 pseudonym join; R-85, R-94 lab cells; R-44 undo anchors | A multi-sheet workbook imports every sheet; a zero-padded chart number joins; unreadable lab cells are listed. |
| R-78 Ask TrialBox; R-81 CGRD; R-82 phone dates; R-112 wording; R-113 window reminder | As each fix says. |

Remaining open items of review 06 and where they sit:

| O-item | Covered by | Pilot blocker (06)? |
| --- | --- | --- |
| O-01 card run | R-15, Gate G1 | yes |
| O-02 chart number on job pages | R-03 | yes |
| O-03 SAE | R-09 | yes |
| O-04 excluded list; 疑い | R-07, R-08 | yes |
| O-05 real REDCap | R-80 | yes for a REDCap site |
| O-06 compose in Docker | R-26 | yes |
| O-07 real SS-MIX2; licensed releases | R-84 | yes for a Japanese site |
| O-08 OCR on real scans | R-71 | yes for a paper site |
| O-09 user guides | R-83 | yes |
| O-10 feasibility wording | R-77, R-72 | yes |
| O-11 REDCap sentence; two words | R-73 | yes |
| O-12 contact outcomes | R-74 | yes |
| O-13 TOTP; forced change | R-04 | yes |
| O-14 admin health tiles | R-43 | yes |
| O-15 to O-22, O-24 | R-75, R-76, R-78, R-79, R-113, R-80, R-81, R-112 | later |
| O-23 per-caller tokens, mTLS, anti-rollback, Windows keys | R-49, R-34, R-25, R-05 | later in 06; Wave 2 here |
| O-25 randomisation, SDV, eConsent and the rest | owner decision 4 of plan v4 | later |
| O-26 jRCT/UMIN, full CT.gov pack, NHI service codes, TW parsers on real files | decision D-140 "Not done" | later |
| O-27 independent re-review of the eight documents | decision D-139 "Not done" | later (after Gate G1) |

**Effort: about 35–40 engineer-days** (7 M, 14 S), plus the site-specific checks.

**All waves: about 215–255 engineer-days.**

## 4. Test-reality gap

Review 06 §2 lists where the gates use a stub, a simulator or a shortcut. The planned 50,000-patient scenario run on the real model pair covers: DB-CSV 50,000 patients; SS-MIX2 with non-numeric labs and 疑い diagnoses; FHIR; messy Excel; pasted charts; PDF, Word and scanned charts with OCR; REDCap longitudinal; an IT dump with local codes; the offline registry. It routes through the production gateway path, which needs R-01 first: as written today, `complete_run --model pair` attaches the models directly and bypasses the gateway (A-01).

| # (06) | Stub or shortcut | Remedy | Closed by the 50k run? |
| --- | --- | --- | --- |
| S1 | Stub model instead of the pair; never excludes | The card run with stage-3 checks; stage 12 with the real model compared to a hand-labelled list | **Yes** for the pair and the canary. Partly for stage 12: still needs a hand-labelled answer list. |
| S2 | Gateway bypassed (no routing, PHI tripwire, swap, trace store) | Run through the gateway; a unit case where the tripwire fires on a ja note and the patient ends "needs information" | **Yes**, once R-01 is fixed. |
| S3 | `rc_sim` instead of REDCap | A nightly job against a real REDCap test project over HTTPS | **Partly**: longitudinal logic (R-10) on the simulator. Real REDCap stays open. |
| S4 | Fake OCR | Five scanned pages per language with expected facts; an OCR-quality warning | **Partly**: real OCR on the run's synthetic scans (after R-71). Real hospital scans stay open. |
| S5 | In-process box instead of compose (no tokens, egress, HAPI gate, concurrency) | `make up-test`, `make test-e2e`, `make test-integration` nightly; one concurrency test | **No.** Stays open (R-26). |
| S6 | `HashEmbedder` in every gate | One run of the scale and public site with BGE-M3 | **Only if** the run serves BGE-M3. Add it to the run. |
| S7 | Mail transport is a list | `make test-e2e` in CI; one send to a real hospital relay at install | **No.** Stays open. |
| S8 | Frozen clock; timers off | A 48 h soak with timers on and `faketime` | **No.** Stays open. |
| S9 | CT.gov cassette and a 6-study sample pack | Build and load the full pack; time `ctgov_search` | **Partly**: offline mode is exercised. The full 2.2 GB pack stays open unless the run loads it. |
| S10 | SS-MIX2 written by our own exporter | A 10-patient sample of each site's real storage | **Partly**: non-numeric labs and 疑い are added (R-02, R-08). Vendor storage stays open (R-84). |
| S11 | JP Core check is a Python differential, not the HL7 validator | Run the HL7 jar once on a snapshot | **No.** Stays open. |
| S12 | Licensed lists are 10-row samples | Load the sites' real releases | **No.** Stays open (R-84). |
| S13 | Backup and update drills on the in-process box | The demo-VM commands; a compose drill | **No.** Stays open (R-26). |
| (04 E-14) | Windows/WSL2 path has no test | A Windows runner that parses and runs the preflight | **No.** Stays open. |
| (04 E-14) | No load or performance tier | A `perf` smoke at 1/50 scale nightly | **Partly**: 50k scale and GPU throughput are measured. Concurrent users and two jobs at once stay open. |
| (04 E-14) | `install.sh` never run end to end | One install in a VM or container | **No.** Stays open. |

**Gaps that stay open after the run:** Docker and compose (stack, tokens, egress, HAPI gate, update and rollback, mail transport); real REDCap; Windows/WSL2; load and concurrency; real vendor SS-MIX2 and licensed lists; real hospital scans; the clock soak; the HL7 JP Core validator; `install.sh` end to end.

## 5. Library and optimisation recommendations (review 04)

| Area | Now | Recommendation | Cost |
| --- | --- | --- | --- |
| DB access | psycopg 3, one connection per store | Keep psycopg; add `psycopg_pool.ConnectionPool` (R-13). Do not adopt SQLAlchemy Core. | S |
| Migrations | Home-grown versioned list | Keep; run each script whole; add a checksum | XS |
| Job queue / outbox | Home-grown Postgres outbox | Keep (wire it, R-16) | — |
| Scheduler | APScheduler 3.11 | Keep, pinned below 4 | — |
| HTTP retries | httpx plus six hand-written loops | httpx plus `tenacity` for client-side loops (not the persisted outbox) | S |
| Settings | `Env` plus `settings.yaml` | Keep both; declare every variable (R-62) | S |
| HL7 v2 | Home-grown 100-line parser | python-hl7 for parsing and escapes; keep the MSH-18 decode | S |
| FHIR models | `fhir.resources` unused | Remove it | XS |
| Excel | openpyxl | Keep; `python-calamine` only for very large intake sheets | — |
| Dates | Six regex sets | One `tb_common.dates` module with property tests; no external library | S |
| OCR | PaddleOCR, `chinese_cht` fixed | Keep; choose `lang` per site; Tesseract as CPU fallback (R-71) | S |
| LLM client | Home-grown gateway client | Keep (the OpenAI SDK would bypass the gateway labels) | — |
| Lake | DuckDB, sqlglot, pyarrow | Keep | — |
| Dependency management | Lock without hashes; unpinned venv | `uv lock`, `uv sync --frozen` with hashes; `pip-audit`; CycloneDX SBOM (R-19) | S |
| Test libraries | pytest, pytest-timeout | Add pytest-cov, pytest-xdist, hypothesis, pytest-randomly, pytest-socket, time-machine | XS |

Performance (profile of `e2e_simple`, 109 s on a 2-core host):

| Hotspot | Fix | Expected gain |
| --- | --- | --- |
| `Ruleset.load` on every console request reads every file of every ruleset (38.8 s of 207 s profiled) | Read only `manifest.yaml` for lists; skip `tests/`; cache by directory and mtime; `CSafeLoader` | About −20 s real; console per-page cost from ~100 ms to ~1 ms |
| `Lake.query` opens a new DuckDB connection per statement | One connection per lake and snapshot; a cursor per query | −5 to −15 s |
| `map_row` splits paths and prunes dicts per row | Compile paths once per table; prune once per resource | 2–3× on the map stage |
| `sqlguard.check_select` re-parses repeated SQL | `lru_cache` on the SQL text | About −4 s |
| `strptime` and JSON round trips | `date.fromisoformat`; optional `orjson` | −3 to −5 s profiled |

Together the first four take `e2e_simple` from about 109 s to **60–70 s**. A nightly `perf` tier should hold them.

## 6. Compliance matrix summary (review 03)

Nothing here is legal advice. Items marked *counsel* need the site's lawyer.

| Framework | Met | Partial | Missing | Main gaps |
| --- | --- | --- | --- | --- |
| **Japan** (APPI, MHLW 安全管理ガイドライン 6.0/7.0, ER/ES 指針, J-GCP, 倫理指針, 医療機器該当性) | 見読性; contact only after PI approval and an audited reveal (in design) | 安全管理措置; lockout and no reuse; access log 真正性; backup; network; remote maintenance; 真正性; 保存性; J-GCP alignment; ethics gate; non-device position in the product | Two-factor sign-in (R-04); encryption at rest and media disposal (R-05); APPI leak reporting plan; 責任分界 and vendor disclosure |
| **Taiwan** (個資法, 電子病歷辦法, 人體研究法, 資通安全管理法, 醫療器材管理法) | Data stays in Taiwan, no cloud for D3/D4; non-device position (in design) | Art. 27 security measures; access log and retention; IRB approval of recruitment | Breach notice plan (72 h); encrypted transmission in the product (R-53); incident and disposal procedures; ISMS if the site is a designated agency; Art. 6 basis is *counsel* |
| **ICH E6(R3)** | Screening log (Annex 1 §C) | Risk-based validation (no URS/FRS trace or IQ/OQ/PQ); audit trail (no reason for change, no record lock, unsigned chain); access control (no MFA; caller-asserted actor); data governance (no SBOM, anti-rollback) | — |
| **Part 11-like** (sponsor audits) | Human-readable and electronic copies (ODM, CSV, XLSX, JSONL) | Validated system; unalterable audit trail (R-18); authority checks; operational checks | Electronic signatures: no name, meaning or re-authentication on approval |
| **SaMD positioning** | Not a device in JP or TW while TrialBox never diagnoses, grades, scores or advises treatment, the investigator decides, and nothing writes to the EMR or reaches patients | The disclaimer is on one page only (R-100) | A written 該当性 consultation is advised before pharma sales, not before an academic pilot |

One owner decision is open: under J-GCP and ICH E6(R3), the built-in forms of decision D-129 make TrialBox a candidate source record. Either it becomes an eCRF of record (then reason for change, record lock and e-signatures are needed), or it is a worklist only and the UI and exports must say so.

## 7. Corrections to the record

These records or texts say something that is no longer true, or never was. DECISIONS is append-only, so its corrections belong in a new entry.

| Record | What it says | What is true | Finding |
| --- | --- | --- | --- |
| Console feasibility §11 (`services/console/i18n_home.py:253,526,799`) vs `docs/VALIDATION.md` §3 and decision D-130 | "About 6 % of eligible patients lost" on TREC 2021–2023 | VALIDATION and decision D-130 say 3.1 % (95 % 1.8–5.0) on TREC 2021/22, audit-adjusted, and it is a projection from a per-criterion rate on English topics, not a SCREEN run on ja or zh-TW notes | R-77 (P-14) |
| `README.md` l.40 | `make venv` gives "the pinned dependencies" | `make venv` resolves fresh; 32 of 74 packages differ from the lock and the image | R-19, R-104 (E-03, E-17) |
| `docs/ARCHITECTURE.md` §9, `docs/VALIDATION.md` (l.31, l.45), `services/orchestrator/rerun.py`, acceptance step 6 | A re-run on the same snapshot is byte-identical | True on the stub. With the pair, decision D-116 measured ~9 % judge label drift and decision D-139 re-runs only FEAS on the card | R-41 (A-10) |
| `docs/SECURITY.md` §5 | Patient-level files go as 7z AES-256 with the password in a second mail (presented as the design) | This is PPAP; it should not be the design (S-05) | R-12 |
| `docs/SECURITY.md` §1, §4 | Hardening and key custody with LUKS, TPM, `systemd-creds` | The product ships on Windows 11 with WSL2 (decision D-125); none of it is checked there | R-05 (S-01) |
| `docs/SECURITY.md` (top) | "Every report says so" (not a medical device) | Only `case_html.py` says it | R-100 (S-21) |
| `docs/SECURITY.md` §1 | The vLLM image is pinned by digest | Only on the GB10 overlay | R-51 (D-05) |
| Decision D-139 "Not run here" | "The pair has never run the `e2e_simple` path" | Still true, but incomplete. The production gateway path has never run either and cannot run as wired (A-01). The planned card run, as scripted, bypasses the gateway, so passing it would not prove the box. Its cost estimate assumes one stream (A-07). Its VM wrapper is the design that failed in today's incident (A-03, D-30, D-31). | R-01, R-14, R-38 |
| `docs/ARCHITECTURE.md` §9 and decision D-127 | "Delivery goes through the outbox, never twice" | "Never twice" holds through idempotency keys; no service uses the outbox | R-16 (A-13) |
| Decision D-126 | Backup targets: a hospital NAS share by default; sign-in by AD/LDAP or local accounts | Install defaults to `deploy/backups` on the same disk; there is no LDAP code | R-20, R-04 |
| Decision D-133 | "The chart number in job lines and subjects was fixed in PR #35" | Reopened on the CASE job page by the web-request row | R-03 (P-01) |
| Decisions D-131 and D-132 | "Nothing ambiguous is guessed silently" | Unreadable lab cells vanish; a Big5 sheet can be read as CP932 | R-94, R-33 |
| `docs/RUNBOOK.md` §5 | Back up by hand with `trialbox backup --to …`; "a person checks the mailbox and resolves it" | The hand-run backup does not work on a compose box (decision D-138 says so); there is no command to resolve a stuck send | R-21, R-16 |
| `tools/trialbox/doctor.py` vs decision D-127 | Unset `TB_ENV` = DEV in `doctor` | Unset = PRODUCTION everywhere else | R-62 (D-25) |
| `docs/handover/OFFLINE-MEDIA.md` | `SHA256SUMS.sig` and a two-key comparison | Install checks neither | R-111 (D-37) |
| Set-up page (`console/i18n_step3.py`) | "Nothing is ever written to REDCap" | TrialBox writes three screening fields to its own instrument (decision D-123) | R-73 (P-07) |
| Feasibility §9 | TrialBox is not connected to jRCT or ClinicalTrials.gov | Decision D-140 added the offline pack and a live mode | R-77 (P-29) |
| README, Makefile, VALIDATION | `e2e_simple` takes "about 2 minutes", "75 s", "115 s" | 109–152 s depending on the host | R-104 |

Not a correction: review 04 notes that DECISIONS names `make poc-hermes`. Decision D-121 records its removal, and DECISIONS is history.

## 8. Appendix: source reports

The six reports are copied unchanged into `2026-11-09-review-parts/`:

- [01 Architecture, model serving and stability](2026-11-09-review-parts/01-architecture-serving-stability.md) (A-01 to A-22)
- [02 Correctness bugs](2026-11-09-review-parts/02-correctness-bugs.md) (B-01 to B-18, suspected 1–9)
- [03 Security, privacy and regulatory compliance](2026-11-09-review-parts/03-security-compliance.md) (S-01 to S-23, compliance matrix, threat model)
- [04 Engineering practice, tests and libraries](2026-11-09-review-parts/04-engineering-tests-libraries.md) (E-01 to E-18, coverage, libraries, performance)
- [05 Deployment, operations, scripts and wrappers](2026-11-09-review-parts/05-deployment-ops-wrappers.md) (D-01 to D-37, cloud-run design in §3)
- [06 End to end, product completeness, clinical fit](2026-11-09-review-parts/06-e2e-product-clinical.md) (P-01 to P-32, O-01 to O-27, stub table)

Review 02's repro scripts (each under 5 KB) are in `2026-11-09-review-parts/scratch-02/`. They carry a `.py.txt` suffix so that `ruff check .` in `make lint` does not lint them; the content is unchanged. Rename to `.py` and run from `trialbox/` to reproduce:

- [repro_lake.py.txt](2026-11-09-review-parts/scratch-02/repro_lake.py.txt): B-01 (part A) and B-02 (part B)
- [repro_lifecycle_anchors.py.txt](2026-11-09-review-parts/scratch-02/repro_lifecycle_anchors.py.txt): B-04
- [repro_sync_blank.py.txt](2026-11-09-review-parts/scratch-02/repro_sync_blank.py.txt): B-03

Paths inside the copied reports that start with `/tmp/` point to the reviewers' working folders. They are not kept.
