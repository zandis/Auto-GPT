# TB-DR-11 Task inventory for TB-PLAN-06

| Field | Value |
| --- | --- |
| Date | 2026-11-10 |
| Code read | `origin/master` at `ca8f287` (PRs up to #65, #79, #81 merged) |
| Method | Clerical. Every card of TB-ASSESS-01 read; status doc, register (TB-REG-01 with update 1), `docs/DECISIONS.md`, `docs/decisions/`, plan WS-18 read; each open PR branch fetched and diffed against master; card artefacts checked on master by file existence and grep; register rows spot-checked by reading the cited lines. |
| What was run | `git fetch` of 14 PR branches; `git diff --stat/--name-only origin/master...<branch>`; `git log`; `git merge-tree --write-tree` (conflict probe, no checkout); `ls`, `grep`, `sed` on master. The open-PR list was read from GitHub. |
| What was not run | No test, no build, no server, no Docker. PR diffs were read by file list and commit log, not line by line. Register rows marked "not re-verified" were not opened. Fix-group work that is not pushed (D-271 to D-281) could not be inspected. |

Paths are relative to `trialbox/`. Branch names are those of the common brief; here they are shortened (`…-t7`,
`T-105-vocabulary-schema`, `tb-fix-site-today`, and so on).

## 0. Summary

* **Cards (67):** 6 merged, 4 partly merged (residue has no open card), 6 in an open PR, 3 work-in-progress with nothing
  pushed, 48 not started. The status doc (`26-status-2026-11-10.md`) is stale on three cards: T-003, T-005 and T-007 are
  merged (#81).
* **Register (115 Blocker/Critical/High rows, CR-001 to CR-115):** 27 fixed on master, 7 covered by an open PR, 33 by a
  fix group (D-271 to D-281) of which **none is pushed**, 31 by a task card only, 12 are owner actions with no card,
  **5 are engineering orphans** (CR-028, CR-037, CR-046, CR-058, CR-081).
* **T-104 has no pull request of its own.** Its commits sit under two other PRs (#82 and #83) in two different versions.
* **Three numbering collisions are live:** D-201 (master: test isolation; PR #75: prompt registry), D-205 (master: goldens;
  PR #82: vocabulary), D-204 (two different files of the same name in #82 and #83). Six PRs still append to
  `docs/DECISIONS.md` and conflict there. Three PRs each claim RUNBOOK §14.
* **Hot files:** `docs/DECISIONS.md` (6 PRs), `docs/RUNBOOK.md` (5), `deploy/docker-compose.yml` (5), `Makefile` (4),
  `services/console/app.py`, `tools/trialbox/doctor.py`, `tools/trialbox/__main__.py`, `services/sitesetup/service.py`,
  `libs/tb_contracts/generated/models.py` (3 each).

## A. Card table

Legend for "verified status": **merged** (deliverables found on master), **partly** (merged under the card's name, named
deliverables missing), **PR #n**, **WIP** (a session says it holds it; nothing on `origin`), **not started** (grep on
master finds nothing). Size is the card's own (S, M, L; "+R" = paid runs). "CR rows" lists the register rows the card
would close (rows shared with a fix group are marked FG).

### A.1 Wave 0

| Card | Goal | Verified status | Evidence | Files (globs) | Depends on | Size | Wave | CR rows |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T-001 | Integrate the three open branches in order | merged | #62, #60, #63, #58, #57 in `git log`; row CR-114 | merge commits, `docs/DECISIONS.md` | none | M | 0 | CR-114 |
| T-002 | Decisions as files, one number registry, CODEOWNERS, CONTRIBUTING, LICENSE | not started | `docs/decisions/` holds 5 files written by other cards; no `REGISTRY.md`, `tools/decisions_index.py`, `CONTRIBUTING.md`, `CODEOWNERS`, `LICENSE` | `docs/decisions/*`, `tools/decisions_index.py`, `tests/unit/test_decisions_index.py`, `CONTRIBUTING.md`, `.github/CODEOWNERS`, `LICENSE`, `docs/DECISIONS.md` (marker) | T-001 | S | 0 | CR-077, CR-080 |
| T-003 | Test isolation, plugin lock, disk hygiene | merged (#81) | `uv.lock`, `tests/unit/test_test_isolation.py`, `TB_TEST_ROOT` in `tests/conftest.py`, `tools/pglocal.py`, `Makefile` (`clean-tmp`, `check-disk`); decision file D-201 | `tests/conftest.py`, `tools/pglocal.py`, `pyproject.toml`, `uv.lock`, `Makefile`, `tests/rehearsal/rehearse.sh` | T-001 | M | 0 | CR-075 |
| T-004 | Run 5: rehearsed, bounded, then full G1 on the card | WIP (integrator; nothing in the repository) | `docs/plan/measurements/` holds only `gpu-run-2026-11-08*`; no launch record, no run-5 report | `docs/plan/measurements/gpu-run-*/`, `docs/RUNBOOK.md` §11, one decision file | T-001; owner OK per run | M + 2 R | 0 | CR-069 |
| T-005 | Data-handling scan as a G1 gate | merged (#81) | `tools/data_scan.py`, `data_scan_patterns.yaml`, `data_scan_allow.txt`, `tests/unit/test_data_scan.py`, `tests/fixtures/data_scan/`, `.pre-commit-config.yaml`, CI job `data-scan`; decision file D-203 | as listed | none | M | 0 | mitigates CR-032 |
| T-006 | Committed goldens at 5k and 50k | merged (#77); 50k files wait for T-004 | `tests/golden/{funnels,screen,feas,lake}`, `tools/goldens.py`, `tests/unit/test_goldens.py`, CI job `goldens`; decision file D-205 | `tests/golden/*`, `tools/goldens.py`, `Makefile` | T-001; T-004 for 50k | M | 0 | CR-064 |
| T-007 | CI gate v1 on every pull request and push | merged (#81) | `.github/workflows/trialbox-ci.yml` with jobs `lint types docs contracts trace unit e2e-simple goldens data-scan shell images`; `make ci`; nightly in `trialbox-e2e.yml`; pip-audit in `trialbox-supply-chain.yml`. Branch protection is the owner's, not verifiable here | `.github/workflows/trialbox-*.yml`, `Makefile` | T-003, T-005, T-006 | M | 0 | CR-074 |
| T-008 | Audited feature flags; `lake.source` first | merged (#77); review-fix residue in PR #71 | `libs/tb_common/flags.py`, `services/console/admin_flags.py`, `i18n_flags.py`, `tests/unit/test_flags.py`, `tests/console/test_flags_page.py`; decision file D-207 | as listed, `services/lake/source.py` | T-001 | M | 0 | CR-065 |
| T-009 | Decision records: measured embedder, profile cost | not started | no `docs/plan/measurements/gpu-run-2026-11-09-run4/`; no decision; `embed_mode` default is already `bge-m3` (`libs/tb_common/config.py:75`) | `docs/plan/measurements/gpu-run-2026-11-09-run4/`, one decision file, `docs/DATA.md` §embeddings | none | S | 0 | none |
| T-010 | Study A protocol v0.3 and intended use v0.3 | not started | `docs/plan/study-a-protocol.md:6` is v0.2; line 10 still says PI "Open"; `排除` occurs 8 times (target ≤ 2) | `docs/plan/study-a-protocol.md`, `docs/plan/intended-use.md`, one decision file | T-001; owner signs | S | 0 | CR-087, part of CR-095 |
| T-011 | Synthetic site built from a schema and code lists | not started | no `tools/synth_site_from_schema.py`, `schemas/site_schema.schema.json`, `tests/fixtures/site_schema/` | those, `tests/unit/test_synth_site_from_schema.py`, `docs/plan/sites/site-survey.md` (field names), RUNBOOK §13 | T-005 (merged) | M | 0 | supports CR-015, CR-088 |
| T-012 | `trialbox eval qualify` and qualification records | not started | no `tools/qualify.py`, `schemas/qualification_record.schema.json`, `eval/qualification/`; no `qualify` in `tools/trialbox/__main__.py` | `tools/qualify.py`, `tools/trialbox/__main__.py`, `services/registry/registry.py`, `models/registry.yaml`, schema, admin models page, RUNBOOK §11 | T-001 | L | 0 | CR-079 |

### A.2 Wave 1

| Card | Goal | Verified status | Evidence | Files (globs) | Depends on | Size | Wave | CR rows |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T-101 | Prompt registry: prompts and schemas resolved by id and version | PR #75 (draft; 32 files, +1,664/−60; base `0cc908b`, 96 behind) | not on master (`libs/tb_llm/prompts/` absent). Probe: conflicts with master in `libs/tb_contracts/generated/models.py`. Decision file named D-201 collides (section E) | `libs/tb_llm/prompts/*`, `libs/tb_llm/prompt_registry.py`, `services/gateway/core.py`, `services/matching/cascade/judge.py`, `libs/tb_common/llm.py`, 3 tools | T-012 (card); the PR did not wait for it | M | 1 | part of CR-079 |
| T-102 | One permission function, steward role, admin without PHI | WIP (critical-issues session); nothing pushed | no `permit` in `libs/tb_common/authz.py`; no `authz_matrix.yaml`; no `steward` or `clinician` role in `services/console/auth.py` | `libs/tb_common/authz.py`, `authz_matrix.yaml`, `services/console/{auth,team,app,home}.py`, i18n role names | T-001 | L | 1 | CR-024, CR-023 (FG-K), CR-018 (FG-D) |
| T-104 | Postgres image with pgvector and PGroonga; checksummed migrations | PR (no PR of its own): commit `ce459522` under #82; commits `ffe1a8c6` + review fixes `a5296bc6` under #83 | master: `deploy/docker-compose.yml:43` still `postgres:16-alpine`; no `db.Dockerfile`, no `deploy/images.lock`; no checksum in `libs/tb_common/db.py` | `deploy/docker/db.Dockerfile`, `deploy/docker/db-init/*`, `deploy/images.lock`, `deploy/docker-compose.yml` (1 line), `libs/tb_common/db.py`, `services/orchestrator/db_pg.py` | T-001 | M | 1 | CR-059, CR-083 |
| T-105 | Vocabulary schema; one chart-number normaliser | PR #82 (draft, "WIP, not ready, handed back"; 37 files, +2,918/−49) | master: `services/omop/vocab.py` exists (first slice); no `vocab_load.py`, no `libs/tb_common/chartno.py`. Probe: conflicts in `docs/DATA.md`, generated models, `services/criteria_compiler/app.py` | `services/omop/vocab*.py`, `services/criteria_compiler/*` (resolver, both generators), `libs/tb_common/chartno.py`, `services/adapter/pidmap.py`, `schemas/ruleset_manifest.schema.json`, `services/sitesetup/service.py` | T-001, T-006 | L | 1 | part of CR-061 |
| T-106 | OMOP second slice: adapter writes the CDM, partitions, timings | not started | no `services/omop/ddl/partitions.sql`; no `dual_write` anywhere | `services/omop/*`, `services/adapter/` (one hook), `tools/omop_parity.py`, `eval/omop_parity/` | T-001, T-006, T-008 (T-104 per status doc) | L | 1 | CR-060, part of CR-061 |
| T-108 | Wave-3 operations in code (limits, systemd, egress, mail, cancel) | not started | no `deploy/systemd/`; no `mem_limit`/`pids_limit` in any compose file; no `tests/unit/test_config_declared.py`; no `cancel` or `mail resolve` command (`secrets rotate` exists) | `deploy/docker-compose*.yml`, `deploy/systemd/*`, `deploy/{install,check_host,network}.sh`, `deploy/egress.py`, `services/mail_gateway/*`, `services/orchestrator/jobs.py`, `tools/trialbox/__main__.py`, `libs/tb_common/config.py` | T-001 | L | 1 | CR-043, CR-082, CR-085 |
| T-110 | Release identity and supply chain | partly (#61 merged in report mode) | done: hashed lock (524 `sha256` in `deploy/requirements.lock`), `tools/supply_chain/*`, pypdf 7.0.0 and pillow 13.0.0, `deploy/security/known-image-findings.md`. Missing: `tools/release.py`, `release.json`, `schemas/release.schema.json`, about page, `CHANGELOG.md`, `THIRD_PARTY_NOTICES.md`; `pyproject.toml:3` still `1.0.0`; image gate in report mode | `tools/release.py`, `schemas/release.schema.json`, about page router, `deploy/docker/*.Dockerfile`, `CHANGELOG.md`, `THIRD_PARTY_NOTICES.md`, `tools/make_bundle.sh` | T-003, T-104 | M | 1 | CR-044, CR-076 closed; CR-081, CR-046, CR-045 open |
| T-111 | Update safety: marker, rollback, anti-rollback, key id | PR #83 (draft, "WIP, not reviewed, handed back"; 28 files, +4,174/−247, includes T-104) | master: no `tools/update_status.py`, no `IN_PROGRESS`/`key_id`/`not_after` in `tools/` or `schemas/`. Probe: conflicts in generated models | `tools/apply_update.sh`, `tools/verify_update.py`, `tools/update_drill.py`, `tools/update_status.py`, `tools/sign_bundle.py`, `tools/trialbox/update.py`, `schemas/update_manifest.schema.json`, RUNBOOK §5 | T-104, T-110 | M | 1 | CR-047 |
| T-113 | `shared-quota` profile, `doctor --platform`, platform manifests | PR #85 (draft; 34 files, +3,504/−6) | master: no `deploy/platform/`, no `shared-quota` compose file. Probe: conflicts in `docs/RUNBOOK.md`. Ships its own `deploy/platform/release.json` although T-110's `release.py` does not exist | `deploy/platform/**`, `deploy/docker-compose.shared-quota.yml`, `deploy/gpu_profile.sh`, `deploy/egress.py`, `tools/trialbox/{doctor,platform,__main__}.py`, `tests/platform/*`, `docs/plan/sites/it-security-pack.md` | T-110 | L | 1 | CR-084 |
| T-114 | Qualification record on the owner's B200 (G1b) | not started | no `deploy/gcp/b200-qualify.sh`. Card text says "rented cloud B200"; the owner now uses his own B200 (brief): the card must be rewritten | `deploy/gcp/b200-qualify.sh` (or a local script), `tests/rehearsal/`, `eval/qualification/`, `docs/plan/measurements/b200-*/` | T-012, T-113, T-004; owner | M + 1 R | 1 | supports CR-089 |
| T-115 | EDC prefill follow-ups (E-12, E-14 to E-16, E-20, E-21, E-23) | WIP (critical-issues session, as FG-L); nothing pushed | master: no record lock, no keyed signature in `services/edc/store.py`; no `tests/fixtures/odm/ODM1-3-2.xsd` | `services/edc/*`, `services/orchestrator/edc_api.py`, `services/console/edc_pages.py`, `templates/edc_*.html`, `i18n_edc.py`, `deploy/docker/db-init/` | T-001, T-104 | L | 1 | CR-036 (FG-L), CR-062 |
| T-117 | Backups: layout, hashes, off-box, age alert, pgBackRest | partly (#63 merged) | done: `tools/trialbox/backup.py`, `backup_schedule.py`, `deploy/pgbackrest/`, `deploy/backup/trialbox-backup.cron`. Missing: install does not install the cron (`deploy/install.sh:287-291` installs only log retention), no backup check in `tools/trialbox/doctor.py`, no Docker-side run (D-188 "Not done here") | `deploy/install.sh`, `tools/trialbox/doctor.py`, admin tile | T-104 | M | 1 | CR-058 open |
| T-118 | Unit mismatch, one encoding detector, one dates module, reason codes | PR #70 (draft; 36 files, +1,818/−144; base `0cc908b`, 96 behind) | master: no `libs/tb_common/encoding.py`, `dates.py`; no `unit_mismatch`. Probe: no conflict with master | `libs/tb_common/{labvalue,encoding,dates,reasons,phi_guard}.py`, `services/adapter/**`, `services/sitesetup/*`, `services/llm_stub/handlers.py`, `services/orchestrator/scenarios/case.py` | T-006 | M | 1 | lookup half of CR-001 (R-31) |
| T-119 | Cloud hygiene remainder (door key, port 80, hosted demo secrets) | not started | `deploy/gcp/complete-run*.sh` still pass `tb-key` by metadata; no Secret Manager use | `deploy/gcp/{complete-run,complete-run-vm,hosted-demo-startup,setup-gcp}.sh`, `tests/rehearsal/`, `tests/unit/test_cloud_run.py` | T-004 | M | 1 | CR-048 |

### A.3 Wave 2

| Card | Goal | Verified status | Evidence | Files (globs) | Depends on | Size | Wave | CR rows |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T-103 | One reveal path for every chart-number reveal | not started | no `services/console/reveal.py`; reveal handlers still at `app.py:1309`, `home.py:787,1077`, `team.py:266` | `services/console/reveal.py`, the four handlers, `backend.py`, `services/orchestrator/app.py` | T-102 | M | 2 | CR-024, CR-017 (FG-D) |
| T-107 | Catalogue loaded as data; items page | not started | no `services/omop/catalogue_load.py`, no items page; `catalogue/items.csv` present (469 rows) | `services/omop/catalogue_load.py`, criteria parser phrasing table, `libs/tb_llm/prompts/`, items page + i18n | T-105, T-101, PR #80 | M | 2 | part of CR-067 |
| T-109 | Identity v1: TLS proxy, OIDC, TOTP, step-up, forced change | partly (#67 merged) | done: `deploy/identity/`, `services/console/{identity,oidc,totp}.py`, TOTP, enrolment codes. Missing: forced password change (no `must_change` anywhere), step-up with the second factor, WebAuthn in the console, `doctor` failing without MFA (D-192 "Open") | `services/console/auth.py`, `identity.py`, `edc_pages.py`, `tools/trialbox/doctor.py` | T-102 | L | 2 | CR-033 (rest), CR-034 (FG-J); CR-039 closed |
| T-112 | Data-operations console v1 and the `dataops` schema | not started | no `services/datacore/dataops.py`, no page; `dataops` only in a comment (`libs/tb_common/flowledger.py`) | `services/datacore/dataops.py`, `services/adapter/` (hook), dataops page + i18n, `/api/v1/data/*` router | T-102 | L | 2 | CR-067 |
| T-116 | "Criteria not matched" wording, forbidden-word check, intended-use footer | not started | no `libs/tb_common/wording.py`; "criteria not matched" absent in `services/` | `services/console/i18n*.py` (all), `services/console/templates/*`, `services/orchestrator/i18n.py`, report writers, mail templates, `libs/tb_common/wording.py` | T-010 | M | 2 | CR-078 |
| T-201 | Clinical conflicts detected; conflicts page | not started | `tb_conflict` exists as an extension table only (`services/omop/schema.py`); no `conflicts.py`, no page | `services/omop/conflicts.py`, `services/omop/load.py` (call), `libs/tb_common/reasons.py`, conflicts page + i18n | T-001, T-102, T-116 | L | 2 | part of CR-061 |
| T-202 | Lake exported from OMOP: parity in CI, flag flip | not started | CI has no `lake_source` matrix; no `tests/unit/test_omop_export_pit.py` | `services/omop/{export,load}.py`, `services/sitesetup/`, `.github/workflows/trialbox-ci.yml` | T-006, T-008, T-106 | M | 2 | CR-060 |
| T-203 | pgvector store, chunker, "patients like me" | not started | no `services/vec/`; no `halfvec`/`hnsw` | `services/vec/*`, `services/embed_service/`, `services/lake/store.py` (1 function), `services/orchestrator/scenarios/screen.py` (S2b call), neighbours page, `tools/backup_drill.py` | T-104, T-102, T-009 | L | 2 | CR-068 |
| T-204 | The twin: `tb_patient_profile` v1 and its API | not started | no `services/profile/`, no `schemas/profile.schema.json` | `services/profile/twin.py`, schema, nightly timer, `/api/v1/patients/{pid}/twin` | T-102, T-106 | M | 2 | part of CR-068 |
| T-205 | Second factor at signing; record lock | not started (same work as FG-J patch P-2 and FG-L patch P-3) | no lock in `services/edc/` | `services/edc/{service,store}.py`, `services/console/edc_pages.py`, `templates/edc_*.html`, `i18n_edc.py` | T-109, T-115 | M | 2 | CR-035 (FG-L), CR-034 part (FG-J) |
| T-206 | Opt-out worker v1 | not started | no `services/datacore/optout_worker.py`; FEAS scenario files do not read the register | `libs/tb_common/{optout,retention}.py`, `services/datacore/optout_worker.py`, FEAS basis query, `services/omop/load.py`, `services/vec/` | T-112, T-203 | L | 2 | CR-027, CR-026 (FG-I), CR-119 |
| T-207 | Derived-data framework: stored rows, definitions as data | partly (#59 merged) | done: `libs/tb_common/derived_store.py`, `catalogue/scores/*.yaml`. Missing (D-190 "Not done"): screening reads stored rows, rulesets pin definition versions, the batch is scheduled, eGFR under-18 rule; no `services/omop/derived_rows.py` | `libs/tb_common/derived.py`, `services/omop/derived_rows.py`, ruleset manifest schema, SQL generator derived templates | T-106, T-201, T-107 | M | 2 | CR-066 (rest); CR-115 is FG-F |
| T-208 | Prompt-injection and false-positive suite | not started | no `eval/injection/`, no `tools/injection_eval.py` | `eval/injection/*`, `tools/injection_eval.py`, prompts (new versions), `services/doc_parser/`, `services/tracestore/`, `tools/qualify.py` | T-101, T-012 | M | 2 | none (PV-13 Medium) |
| T-209 | Monitoring, admin screens, support bundle | not started | no `libs/tb_common/metrics.py`, no `/metrics`, no `tools/support_bundle.py`. PR #66 builds part of the admin screens | `libs/tb_common/metrics.py`, `/metrics` routers, `deploy/docker-compose.monitoring.yml`, `services/console/admin_*`, `tools/support_bundle.py`, IT pack §A.7 | T-108, T-110, T-111, T-117, PR #66 | L | 2 | part of CR-058 (tile) |
| T-210 | Windows/WSL2 hardening, keys under a KEK, unseal | not started | `deploy/windows/preflight.ps1` has 0 "BitLocker"; no `libs/tb_common/kek.py`, `tools/keys.py` | `deploy/windows/*`, `deploy/check_host.sh`, `libs/tb_common/kek.py`, `services/adapter/pidmap.py` (key load), `tools/keys.py`, `tools/trialbox/doctor.py`, `tools/apply_update.sh` | T-111, T-113 | L | 2 | CR-041 |
| T-211 | Audit integrity: signed heads, one writer, NTP FAIL, audit browser | not started | no signing or anchor in `libs/tb_common/audit.py`; no audit page module | `libs/tb_common/audit.py`, audit-writer service or role split, audit page + i18n, `tools/audit_verify.py`, `tools/trialbox/doctor.py` | T-210, T-103 | L | 2 | CR-042, CR-054 (FG-C) |
| T-212 | Boundary and egress (PPAP out, HAPI token, verified caller, SSRF, gitleaks) | not started | `services/gateway/core.py:5` still routes on `X-TB-Caller`; no gitleaks job; no SSRF guard; `zip` still the default | `services/mail_gateway/*`, `services/gateway/core.py`, `models/routing.yaml`, `deploy/docker-compose*.yml`, `deploy/docker/db-init/`, `libs/tb_common/{http,logging}.py`, CI workflow | T-108 | L | 2 | CR-025, CR-040, part of CR-037 |
| T-213 | Acceptance environment and Docker drills | not started | no `deploy/docker-compose.acceptance.yml`; `tools/acceptance.py` exists but is the older site-acceptance tool (D-83): **name clash** with the card's new file | `tools/acceptance.py` (clash), `deploy/docker-compose.acceptance.yml`, `tests/integration/test_acceptance_drills.py` | rental box; T-108, T-109, T-111, T-117 | L | 2 | CR-071 |
| T-214 | arm64 builds, `gb10` profile measured, two-device link | not started (pre-existing `deploy/docker-compose.gb10.yml`, `tools/spark_e2e.sh`, `make images-multiarch`) | no `deploy/two-device/` | `Makefile`, `deploy/docker/*.Dockerfile`, `deploy/two-device/*`, `deploy/docker-compose.gb10.yml`, `tools/trialbox/doctor.py` | the Spark; T-012, T-110 | L | 2 | supports CR-089 |
| T-215 | QMS-lite records, change classes, FS, risk file, VMP | not started | no `docs/validation/`; no PR template | `docs/validation/**`, `.github/pull_request_template.md`, `tools/gen_traceability.py`, `tools/doclint.py` | T-002, T-007 | M | 2 | part of CR-096 |
| T-216 | Missing data as the normal case (`missing_reason`) | not started | no `missing_reason` anywhere | `libs/tb_common/reasons.py`, cascade candidate record, candidate and PI templates, `i18n_missing.py`, `services/datacore/` | T-116, T-112 | M | 2 | CR-013 |

### A.4 Wave 3 (all not started; one check each)

| Card | Goal | Evidence of "not started" | Files (globs) | Depends on | Size | CR rows |
| --- | --- | --- | --- | --- | --- | --- |
| T-301 | Wave-5 product completeness, help, visit card, `.ics` | no `tools/visit_card.py`; no `.ics` | PI list, feasibility, approval, patient, phone templates + i18n; `services/orchestrator/lifecycle`; `tools/visit_card.py` | T-116, T-103 | L | CR-086 (by its contract) |
| T-302 | REDCap arms, events, repeating instruments, copy-assist, ODM import, consent record | no `copy_assist_page.py`; no `redcap_repeat` in `services/edc` | `services/edc/*`, `services/rc_sim/`, `services/datacore/`, copy-assist page | T-115, T-205 | L | CR-062 (rest) |
| T-303 | Monitor SDV page | no `sdv_page.py` | `authz_matrix.yaml`, SDV page + i18n, `services/datacore/` | T-102, T-205 | M | none |
| T-304 | Statistics page and the export set | no `services/datacore/stats.py`, `tools/extract.py` | `services/datacore/stats.py`, stats page, `tools/extract.py`, export writers | T-112, T-201, T-207 | L | none (PV-14 Medium) |
| T-305 | All-history back-fill, pinned snapshots, batched publish, retention | no snapshot pinning in `services/lake/store.py` | `services/adapter/`, `services/omop/load.py`, `services/lake/store.py`, `libs/tb_common/retention.py` | T-106, T-202 | L | CR-063, part of CR-061 |
| T-306 | HAPI out of the nightly path | HAPI has no compose profile | `services/adapter/` night sequence, `tests/integration/`, `deploy/docker-compose.yml` | T-202 | M | none |
| T-307 | Catalogue gaps and the instrument copyright register | no `instruments_page.py` | `services/omop/vocab_load.py`, `catalogue/`, instruments page | T-107; owner | M | none |
| T-308 | Specialty templates | `catalogue/specialties.csv` exists; no `tb_specialty_template` | profile page sections, `i18n_profile.py` | T-311, T-107 | M | none |
| T-309 | Break-glass | no "break-glass" string in `services`, `libs`, `tools` | `services/console/breakglass.py`, `authz_matrix.yaml`, templates + i18n | T-102, T-109, T-211 | M | CR-029 (also FG-K) |
| T-310 | Weekly PI sample, IRB-text gate, override report, SAE hardening | no weekly sample job | `services/orchestrator/` weekly job, study set-up page, SAE files | T-116, T-206, T-201 | M | CR-012, CR-014 |
| T-311 | Cited profile page; Study C/D drafts | no `services/profile/` | `services/profile/writer.py`, profile page, protocol drafts | T-101, T-203, T-204, T-208, T-004, T-116 | L | part of CR-068 |
| T-312 | Physician annotations | no `tb_annotation` | `services/omop/`, `services/profile/annotations.py`, profile page panel | T-204, T-201, T-109, T-311 | M | part of CR-068 |
| T-313 | Setpoints and gap finder, flags off | no `setpoint` | `services/profile/{setpoints,finder}.py` | T-207, T-204, T-208, T-311 | L | part of CR-068 |
| T-314 | Restricted clinician view | no `user_practitioner` | `services/datacore/`, `authz_matrix.yaml`, profile page variant | T-102, T-311, T-313 | M | CR-030 |
| T-315 | Journeys as PQ script; IQ/OQ/PQ protocols; dry-run tooling | no `tests/e2e/journeys/`, `tools/dryrun.py` | `tests/e2e/journeys/`, `docs/validation/protocols/`, `tools/dryrun.py`, CI coverage | T-116, T-102, T-115 | L | none |
| T-316 | Consortium: code-map registry, signed counts, de-identified export | no `tools/codemap_release.py`, `signed_counts.py` | those, `services/omop/vocab.py`, `tools/deid_*` | T-105, T-304, T-204 | L | CR-031 |
| T-317 | Documents made true; role guides ja and zh-TW; re-review | no `docs/guides/` | the eight documents, `docs/guides/`, `tools/doclint.py` | T-004, T-301 | M | none |
| T-318 | Privacy documents, incident plan, one-pager | no `docs/plan/sites/privacy/` | `docs/plan/sites/privacy/`, `incident-response.md` | T-116, T-209 | M | part of CR-096 |
| T-319 | Shared-host isolation drills; platform KEK variant | no `tests/platform/` on master (PR #85 adds `tests/platform/test_isolation_probe.py`) | `tests/platform/`, `deploy/platform/overlays/acceptance`, `tools/trialbox/doctor.py` | T-113, T-210, T-213 | M | none |
| T-320 | Site set-up limits, EMR launch link, work log, admin leftovers | no EMR link code | `services/sitesetup/*`, readiness pages, admin console | T-103, T-301 | M | none |

### A.5 Pull requests with no card

| PR | Purpose (from its commits) | Size vs master | State | CR rows |
| --- | --- | --- | --- | --- |
| #64 (`…-t7`) | Judge bake-off harness gating on wrong exclusions (D-181) | 4 files, +1,505; rebased on `ca8f287`; no conflict | ready (not draft) | supports CR-069 |
| #66 (`…-t4`) | IT admin (ops) screens, confirmations and undo, site pages site-wide (D-178, D-179) | 35 files, +2,332/−41; 15 behind; conflict in `docs/DECISIONS.md` | draft | parts of CR-058 |
| #68 (`…-t3`) | Box-install rehearsal, keyed model servers, model-guard (D-176, D-177) | 54 files, +3,192/−78; 15 behind; conflict in `docs/DECISIONS.md` | draft | none directly; touches files of CR-043, CR-046, CR-047, CR-058 |
| #71 (`wave0-goldens-review-fixes`) | T-006/T-008 with the adversarial review fixed (4 High, 7 Medium, 8 Low) | 39 files, +10,134/−8; base `74b661d`, 105 behind; conflicts in 13+ files because #77 merged the same work | draft; **superseded by #77**: only the review-fix residue is to port | CR-051 (touches `tools/omop_parity.py`, `tools/pglocal.py`) |
| #73 (`tb-critical-register`) | TB-REG-01 register, docs only | 1 file, +888 | draft; not on master | — |
| #76 (`…-t2`) | Japan reference data (D-173 to D-175) | 26 files, +3,482/−96; 72 behind; conflicts in `docs/DECISIONS.md`, `libs/tb_common/refdata*.py`, `tests/unit/test_refdata_tw.py`, `tools/refdata_fetch.py` (overlap with merged #65) | draft | none |
| #78 (`tb-image-vulns`) | D-186 follow-up: pin newer jars; make the image gate blocking | 1 file (`compile_cql/translator/pom.xml`), +35/−1; "WIP, untested" | draft, barely started | CR-045 |
| #80 (`…-t6`) | Catalogue completion with verified codes (D-180) | 19 files, +18,820/−637; 49 behind; conflict in `docs/DECISIONS.md` | draft | none |
| #86 (`tb-fix-site-today`) | D-270: console "today" is the site's date (DI-1, DI-2) | 19 files, +504/−47; 49 behind; no conflict | draft | CR-049, CR-050, part of DI-14 |

## B. Register table

"Verified state today" is on master `ca8f287`. "v" = cited code opened and still as described; "n/v" = not re-verified
here (status taken from the register). Coverage tag first: **FIXED**, **PR**, **FG** (fix group, decision number given;
no fix-group branch other than D-270 is on `origin`), **CARD**, **OWNER** (owner action, no card), **ORPHAN**.

| CR | Sev | One line | Verified state today | Covered by |
| --- | --- | --- | --- | --- |
| CR-001 | Blocker | Lab threshold ignores the row's unit | open, v (unit read only for derived components, `generator.py:277`) | FG D-275; lookup half in PR #70 (T-118) |
| CR-002 | Critical | Two-model rule accepts one model twice | open, v (`orchestrator/app.py:56-73` has no distinctness check) | FG D-276 |
| CR-003 | Critical | Stub cannot disagree; 12 rules untested | open, v (no personas in `services/llm_stub`) | FG D-276 |
| CR-004 | High | Both models read the same cut excerpt | open, n/v | FG D-276 |
| CR-005 | High | Record status never used | open, v (no `status` in the SQL generator) | FG D-275 |
| CR-006 | High | Sex other/unknown treated as not female | open, v (`generator.py:311` handles NULL only) | FG D-275 |
| CR-007 | High | Missing data becomes FALSE | open, n/v | FG D-275; T-216 adjacent |
| CR-008 | High | Fatal AE with Serious = No is not an SAE | open, v (`lifecycle.py:125-128`) | FG D-277 |
| CR-009 | High | SAE clock falls back to Taiwan rules | open, v (`lifecycle.py:102-106`) | FG D-277 |
| CR-010 | High | SAE alerts fail open | open, n/v | FG D-277 |
| CR-011 | High | SAE leftovers (death state, unique index, UTC fallback) | open, n/v | FG D-277 |
| CR-012 | High | SAE sync on page GET; write-path hook not built | open (D-191 "Open") | CARD T-310 |
| CR-013 | High | No per-item reason for missing data | open, v | CARD T-216 |
| CR-014 | High | No weekly PI sample; send-back does not re-enter | open, v | CARD T-310 |
| CR-015 | High | No vendor SS-MIX2 file ever read | open | OWNER (T-011 supports) |
| CR-016 | Blocker | Chart numbers in clear in the audit log | open, v (`orchestrator/core.py:301-309` writes `job.options`) | FG D-272; old chain needs OD-7 |
| CR-017 | Critical | Oldest reveal route has no delegation check | open, v (`console/app.py:1309-1336`) | FG D-273; long term T-103 |
| CR-018 | High | Delegation rule missing on sibling pages | open, n/v | FG D-273; long term T-102 |
| CR-019 | High | Opt-out not honoured on five read paths | open, n/v | FG D-273 |
| CR-020 | High | Registry export returns every chart number | open, n/v | FG D-273 |
| CR-021 | High | Opt-out endpoints are a pseudonym oracle | open, n/v | FG D-273 (PX-7) |
| CR-022 | High | `/ask` returns verdicts with no audit | open, n/v | FG D-273 (PX-8) |
| CR-023 | High | Administrator holds every patient-level right | open, v (no steward role) | FG D-280; T-102 |
| CR-024 | Blocker | Permission sprawl; no single function | open, v | CARD T-102, T-103 |
| CR-025 | High | Chart-number spreadsheets mailed as password zip | open, v (`zip` default) | CARD T-212 after owner decision OD-1 |
| CR-026 | High | FEAS counts and data-core exports ignore opt-out | open, v (FEAS files) | FG D-278; T-206 |
| CR-027 | Critical | Opt-out worker not built | open, v | CARD T-206 |
| CR-028 | High | PHI pass on note text (FR-DEID-01) not built | open (D-111 "Not done") | **ORPHAN** |
| CR-029 | High | No break-glass | open, v | CARD T-309; FG D-280 |
| CR-030 | High | No clinician role or view | open, v | CARD T-314 |
| CR-031 | High | No code-map registry, no de-identified export | open, v | CARD T-316 |
| CR-032 | Blocker | Real data could reach agents before the DPA | open | OWNER (T-005 merged and T-011 mitigate) |
| CR-033 | Blocker | No second factor, directory sign-in or TLS | partly fixed (#67): TOTP, OIDC option, Caddy on master | FG D-279 for the rest; T-109 |
| CR-034 | Blocker | E-signature is a password the admin has seen | open, v (no forced change) | FG D-279 (P-1, P-2) |
| CR-035 | High | No record lock; no second factor at signing | open, v | FG D-281 (P-3); T-205 |
| CR-036 | High | Signature binding unkeyed and partial | open, n/v | FG D-281 (P-4); T-115 |
| CR-037 | High | One PostgreSQL role for every service | open, v (`db-init/10-trialbox-wf.sh:6`, `CREATEDB`) | **ORPHAN** (T-212 names roles in passing; no card owns the per-service split) |
| CR-038 | High | Orchestrator takes the actor from the body | open, v (`datacore_api.py`) | FG D-278 |
| CR-039 | High | Trusted-header SSO forgeable | fixed by #67 (DEV/TEST only; `console/app.py:202`), by reading | FIXED |
| CR-040 | High | Gateway routes on self-declared caller | open, v | CARD T-212 (register named no card) |
| CR-041 | Blocker | No BitLocker/swap check; keys as plain files | open, v | CARD T-210 |
| CR-042 | High | Audit chain unkeyed, six writers | open, v | CARD T-211 |
| CR-043 | High | Egress table not persisted | open, v (`install.sh:285` applies once) | CARD T-108 (register says T-212; the card that persists it is T-108) |
| CR-044 | High | Lock without hashes; pypdf, pillow pins | fixed by #61, v (524 hashes; pypdf 7.0.0; pillow 13.0.0) | FIXED |
| CR-045 | Critical | Images carry HIGH/CRITICAL vulnerabilities | open; the list is now on master (`deploy/security/known-image-findings.md`), gate in report mode, owner "to assign", target 2026-12-10 | PR #78 (WIP, 1 file); owner OD-4 |
| CR-046 | High | `make_bundle.sh --gates` optional; SBOMs not in the bundle | open, v (D-186 "Not done here") | **ORPHAN** (#78 does not touch it; #68 edits the file) |
| CR-047 | High | No anti-rollback, key id or expiry on updates | open on master, v | PR #83 (T-111, WIP) |
| CR-048 | High | Cloud-run door key over plain HTTP | open (D-150 "Not done") | CARD T-119 |
| CR-049 | Critical | Console "today" is the UTC date | open on master | PR #86 (D-270) |
| CR-050 | High | N1/N2 notices run for yesterday | open on master, v (`timers.py:73,76`) | PR #86 (D-270) |
| CR-051 | High | `omop_parity` can pass on nothing | open, n/v | FG D-271; PR #71 also edits the file |
| CR-052 | High | Empty rebuild becomes CURRENT | open, n/v | FG D-271 |
| CR-053 | High | Held night promoted by the next delta | open, v (`pipeline.py:262-266`) | FG D-271 |
| CR-054 | High | Audit verify has no head anchor | open, v | FG D-272; T-211 |
| CR-055 | High | Change committed before the audit row | open, n/v | FG D-273 |
| CR-056 | High | Restore over a non-empty box keeps no copy | open, n/v | FG D-274 |
| CR-057 | High | Backup hash builds one string per table | open, v (`backup_schedule.py:140`) | FG D-274 |
| CR-058 | High | Backups not wired at install | open, v (cron file exists, install does not install it; no `doctor` check) | **ORPHAN** (T-117 is closed as merged; PR #66 adds a backup-check command and tile, PR #68 edits `install.sh`; nobody owns the row) |
| CR-059 | High | Migrations without checksum or order | open on master, v | PR #83 / #82 (T-104) |
| CR-060 | Blocker | OMOP as store of record: first slice only | open, v (flag default `legacy`) | CARD T-106, T-202 |
| CR-061 | High | Provenance, vocabulary, conflicts, back-fill: tables only | open | CARD T-105 (PR #82), T-106, T-201, T-305 |
| CR-062 | Blocker | EDC prefill lacks its GAMP 5 controls | open | CARD T-115, T-302 |
| CR-063 | High | Jobs not pinned to a snapshot | open, v | CARD T-305 (register named no card) |
| CR-064 | High | No committed goldens | fixed by #77, v | FIXED |
| CR-065 | High | No feature-flag mechanism | fixed by #77, v | FIXED |
| CR-066 | High | Derived scores not stored as data | partly fixed (#59) | CARD T-207 (rest) |
| CR-067 | High | No data-operations console | open, v | CARD T-112, T-107 |
| CR-068 | High | No vector store, profile, annotations, setpoints | open, v | CARD T-203, T-204, T-311 to T-313 |
| CR-069 | Blocker | Gate G1 has not passed | open, v (no run-5 record in the repository) | CARD T-004 (WIP) |
| CR-070 | High | GPU quota is 1 | closed as a constraint: increase refused (brief); plan on 1 GPU | OWNER (no action left) |
| CR-071 | High | Stack never run in Docker with the real pair | open | CARD T-213; owner hardware |
| CR-072 | High | EDC gateway 409 | fixed by #72, v (`models/routing.yaml:74,113`) | FIXED |
| CR-073 | High | Stage 16 crash at 500 patients | fixed by #69 (by merge) | FIXED |
| CR-074 | High | No CI beyond one workflow | fixed by #81, v | FIXED |
| CR-075 | High | Test isolation leaks | fixed by #81, v | FIXED |
| CR-076 | High | `make images` fails on master | fixed by #61, by reading only (no build run) | FIXED |
| CR-077 | High | Decision numbers taken by guess | partly fixed (D-191 text added); registry missing; new collisions (section E) | CARD T-002 |
| CR-078 | High | Product words; no forbidden-word check | open, v | CARD T-116 |
| CR-079 | High | No `qualify`; prompts are plain files | open, v | CARD T-012; PR #75 for prompts |
| CR-080 | Blocker | No second reader; no CODEOWNERS | open, v | CARD T-002; owner OD-9 |
| CR-081 | High | Everything is 1.0.0; no `release.json`, tag, changelog | open, v | **ORPHAN** (T-110 is closed as merged without these) |
| CR-082 | High | No container limits | open, v | CARD T-108 |
| CR-083 | High | `postgres:16-alpine` cannot take pgvector | open on master, v | PR #83 / #82 (T-104) |
| CR-084 | Blocker | No shared-host install path | open on master, v | PR #85 (T-113) |
| CR-085 | High | Mail send key stuck in `sending`; no resolve command | open, v | CARD T-108 |
| CR-086 | High | PI list does not prioritise | open, n/v | CARD T-301 (by its contract; register named no card) |
| CR-087 | High | Study A PI decision not in the protocol | open, v (`study-a-protocol.md:10`) | CARD T-010; owner OD-2 |
| CR-088 | Blocker | Neither site's feed is known | open | OWNER |
| CR-089 | Blocker | Japan box not ordered; B200 quota open | open | OWNER (T-114, T-214 follow) |
| CR-090 | Blocker | Hospital IT not engaged; 去識別化 wording in the IT pack | open | OWNER (the wording fix has no card) |
| CR-091 | Blocker | Licence, DPA, insurance open | open | OWNER |
| CR-092 | Blocker | CGMH identified export has no owner; IRB amendments | amendments submitted 2026-11-10 (brief); export owner open | OWNER |
| CR-093 | Blocker | Go-live straddles Lunar New Year | dates since moved to 04-28 / 05-13 (brief); row needs a re-read | OWNER |
| CR-094 | High | Pentest timing; accuracy on real records; isolation attested only | open | OWNER (T-319 covers the isolation part) |
| CR-095 | Blocker | Study A protocol defects | D-163 revised it; not re-read by anyone | OWNER (T-010 covers PI, COI, wording only) |
| CR-096 | High | Counsel view, incident plan, QMS-lite, licences | open | OWNER (T-215, T-318 cover QMS-lite and the incident plan) |
| CR-097 to CR-114 | 5 Blocker, 1 Critical, 12 High | the register's "verified as fixed" section | fixed (not re-opened here; residues are in section F) | FIXED |
| CR-115 | High | SQL/CQL engines lack the impossible-value guards | open, v (`DOMAIN` not referenced in the SQL generator) | FG D-275 |

Rows below High that the register lists (not counted): CR-116, CR-117 → FG D-279; CR-118 (Low list from #67) → nothing;
CR-119 → T-206; CR-120 (Low and Medium list from #59) → T-207 rest, nothing explicit.

### B.1 Counts by coverage (115 rows)

| Coverage | Rows | Count |
| --- | --- | --- |
| FIXED on master | CR-039, 044, 064, 065, 072, 073, 074, 075, 076, CR-097 to CR-114 | 27 |
| PR open | CR-045 (#78), 047 (#83), 049, 050 (#86), 059, 083 (#83/#82), 084 (#85) | 7 |
| FG (fix group; only D-270 is pushed and is counted under PR) | CR-001 to 011, 016 to 023, 026, 033 to 036, 038, 051 to 057, 115 | 33 |
| CARD only | CR-012, 013, 014, 024, 025, 027, 029, 030, 031, 040, 041, 042, 043, 048, 060, 061, 062, 063, 066, 067, 068, 069, 071, 077, 078, 079, 080, 082, 085, 086, 087 | 31 |
| OWNER, no card | CR-015, 032, 070, 088, 089, 090, 091, 092, 093, 094, 095, 096 | 12 |
| ORPHAN (engineering) | CR-028, 037, 046, 058, 081 | 5 |

### B.2 Orphans

**Engineering, High, no card, fix group or PR owns them:**

1. **CR-028** PHI pass on note text (FR-DEID-01). Needs a new card.
2. **CR-037** one PostgreSQL role for all services. T-212 mentions "non-superuser roles, CREATEDB dropped" but no card
   states the per-service role split. Needs a card or an explicit line in T-212.
3. **CR-046** `--gates` mandatory in `make_bundle.sh`; SBOMs inside the signed bundle; `THIRD_PARTY_NOTICES.md`.
4. **CR-058** backup wiring at install (cron, off-box target check in `doctor`, Docker-side run).
5. **CR-081** release identity (`release.json`, tag, changelog, about page).

Rows 3 to 5 are the unbuilt halves of T-110 and T-117, which the status doc closes as "merged". A new card "T-110b
release identity and bundle gates" and "T-117b backup wiring" would cover them.

**Owner actions with no card (not agent work, but nothing tracks them):** CR-015, CR-032, CR-088, CR-089, CR-090,
CR-091, CR-092, CR-093, CR-094, CR-095, CR-096 (CR-070 is moot). CR-090's document fix (the zh-TW wording in
`docs/plan/sites/it-security-pack.md`) is agent work and has no card.

**Fix groups that cover rows but cannot be verified (no branch on `origin`):** D-271 (CR-051 to 053), D-272 (CR-016,
054), D-273 (CR-017 to 022, 055), D-274 (CR-056, 057), D-275 (CR-001, 005, 006, 007, 115), D-276 (CR-002 to 004),
D-277 (CR-008 to 011), D-278 (CR-026, 038), D-279 (CR-033 rest, 034, 116, 117), D-280 (CR-023, break-glass), D-281
(CR-035, 036, SEC-6, SEC-7). Seven open Blocker or Critical rows rest on these unpushed groups alone: CR-001, CR-002,
CR-003, CR-016, CR-017, CR-033 (rest), CR-034.

Note on the register text: section 7.3 lists FG-K as "CR-023, CR-027 (break-glass)". CR-027 is the opt-out worker; the
break-glass row is CR-029. Read as a typing slip; it should be corrected in the register.

### B.3 The register's patches (section 4)

| Patch | For | Now |
| --- | --- | --- |
| P-1, P-2 | CR-034 | folded into FG D-279; P-2 is the same work as T-205's first half |
| P-3 | CR-035 | FG D-281; same work as T-205's second half |
| P-4 | CR-036 | FG D-281; same work as T-115 (E-21) |
| P-5, P-6 | SEC-6, SEC-7 | FG D-281; same as T-115 (E-20) |
| P-7 | SEC-9 | FG D-279 (CR-116) |
| PX-1, PX-2 | CR-049 | no longer needed as patches; in PR #86 (`auth.py`, `step4.py` are in its file list) |
| PX-3 | CR-016 | FG D-272 |
| PX-4, PX-5, PX-7, PX-8 | CR-017, 020, 021, 022 | FG D-273 |
| PX-6 | CR-023 | FG D-280, after owner decision OD-5 (recorded) |

### B.4 The register's Medium list (section 6)

| Item | Covered by | Item | Covered by |
| --- | --- | --- | --- |
| S-11 derived plausibility bounds | FG D-275 (with CR-115) | SEC-6, SEC-7 | FG D-281 |
| S-12 feasibility sweep hard-excludes | nothing | SEC-8 | T-211 (CR-042) |
| S-13 S4 verifier cannot disagree | nothing (near FG D-276) | SEC-9 | FG D-279 |
| S-14 no snapshot-age check | nothing | SEC-10 | fixed by #67 (TLS, Secure default) |
| S-15 lake zone from `TB_TZ` | nothing | SEC-11 mail auth fails open | nothing |
| S-16 SAE with clocks 0 is quiet | nothing (near FG D-277) | SEC-12 | PR #83 (CR-047) |
| S-17 Observation dated by period only | nothing | SEC-13 | fixed by #61 |
| PV-9 CASE page shows chart number | FG D-272 (PX-3) | SEC-14 REDCap client accepts `http://` | nothing |
| PV-10 scrubber rule off | T-212 | SEC-15 self-entered PI | T-102 (removes the `pi is None` fallback) |
| PV-11 (b–e) mail bodies, names in audit | T-212 in part | SEC-16 shared token forges `reauth-` | nothing |
| PV-12 N1/N2 patient rows tagged aggregate | nothing | SEC-17 assertion replay 120 s | nothing |
| PV-13 trace store keeps note text | T-208 in part | DI-10 restore leaves no audit | nothing |
| PV-14 office counts ignore study scope | T-304 in part | DI-11 backup not one point in time | nothing |
| PV-15 orchestrator reveal role | FG D-273; T-103 | DI-12 settings not in the backup | nothing |
| PV-16 workbooks outside the flow ledger | T-112 in part | DI-13 source delete, no erase path | T-206 |
| PV-17 pseudonyms in URLs | nothing | DI-14 other time-zone slips | PR #86 in part (`scheduler.py`, `omop/__main__.py`, `step4.py`) |
| PV-18 link mode cannot deliver files | T-212 | | |

Medium items with nothing: S-12, S-13, S-14, S-15, S-16, S-17, PV-12, PV-17, SEC-11, SEC-14, SEC-16, SEC-17, DI-10,
DI-11, DI-12 (15 items).

## C. Duplicates and overlaps

### C.1 The same work under two or three names

| Work | Appears as | Proposal |
| --- | --- | --- |
| Postgres image and checksummed migrations | T-104 commit in PR #82 and a different, reviewed T-104 in PR #83 (14 shared files, same decision file name) | Cut T-104 out as its own PR from the #83 version; rebase #82 and #83 on it |
| Goldens and flags | merged #77 and open PR #71 | Close #71; one small card "port the #71 review fixes" (six items of status §2.5) |
| Record lock and second factor at signing | T-205; FG D-281 (P-3); FG D-279 (P-2); T-115 status line in the status doc | One card "EDC signature controls" = T-115 + T-205 + FG D-281; second factor part waits for FG D-279 |
| Forced password change, step-up | T-109 residue; FG D-279 (P-1); D-192 "Open" | Close T-109; FG D-279 is the card |
| Steward role, admin without PHI | T-102; FG D-273 (authz half); FG D-280; patch PX-6 | T-102 keeps `permit` and the matrix; FG D-280 is its first slice. Decide which lands first |
| Break-glass | T-309; FG D-280 | Merge. T-309's contract (second person, 24-hour grant) contradicts the owner decision OD-5 (reason, one patient or job, 60 minutes, steward review): rewrite the card |
| One reveal path | T-103; FG D-273 (PX-4 routes the old reveal "through the one guarded path") | FG D-273 fixes the hole; T-103 does the refactor after T-102 |
| Opt-out in FEAS and exports | T-206 ("FEAS counts read it"); FG D-278 (CR-026) | Remove that line from T-206 once D-278 lands |
| Audit head anchor | T-211; FG D-272 (CR-054) | T-211 keeps signing, one writer, browser |
| Unit of a lab row | T-118 / PR #70 (lookup unit, `labvalue.py`); FG D-275 (SQL generator) | Two layers of one rule; both move goldens: land #70 first, regenerate goldens once |
| Derived-value domain guards | CR-115 (FG D-275); D-189 "Not done"; T-207 SQL templates; status §2.5 row 3 | FG D-275 owns it; T-207 must not touch the same templates before it |
| SAE hardening | T-310 (fourth part); FG D-277; CR-012; D-191 "Open" | Move all SAE work into one card (FG D-277 + CR-012); T-310 keeps the sample, the IRB gate, the override report |
| Site-local dates | PR #86 (D-270); status §2.5 row 1; DI-14 | #86 is the card; add the DI-14 remainder to it or to a follow-up |
| Update verification | T-111 / PR #83; PR #68 (`tools/verify_update.py`, `apply_update.sh`, `tools/trialbox/update.py`) | Merge #68 first (older, reviewed), rebase #83 |
| Egress persistence | T-108 (systemd unit); T-212 (register's owner of CR-043); PR #68 and PR #85 edit `deploy/egress.py` | T-108 owns CR-043; say so in T-212 |
| Admin screens | PR #66 (D-178/179); T-209 ("admin pages not created by D-178/179"); T-320 (admin leftovers) | Re-cut T-209 and T-320 after #66 merges |
| Catalogue codes | PR #80 (JLAC10 map, ICD-10-CM phenotype sets); T-307 (same items listed) | Shrink T-307 to what #80 leaves |
| Reference data | merged #65, PR #76, status §2.5 "P0 baseline data", "WS-08.8 left to the integrator" | One card for the WS-08.8 remainder after #76 |
| Isolation probe | PR #85 adds `tests/platform/test_isolation_probe.py`; T-319 owns `tests/platform/` | T-319 extends, does not create |
| Release file | T-110 (`release.json` unbuilt); PR #85 ships `deploy/platform/release.json` | Build `tools/release.py` (CR-081) before #85 merges, or #85's file is a hand-made stand-in |
| CONTRIBUTING and PR template | T-002; T-215 | Keep separate; T-215 after T-002 |
| Bake-off and qualify | PR #64 (harness); T-012 (qualify); T-114 (B200 record); status §2.5 "Gemma 4 31B" | T-012 calls the #64 harness as a step; one card for the 31B challenger run |
| Missing data | T-216; CR-007 (FG D-275); CR-013 | FG D-275 makes missing → unknown in the engine; T-216 carries the reason to the page |

### C.2 Cards that should merge

* T-115 + T-205 (+ FG D-281): one owner of `services/edc/*` at a time.
* T-309 into the FG D-280 work (same files, same owner decision).
* T-110 residue + CR-046 + CR-081: one "release identity and bundle gates" card.
* T-117 residue + CR-058 (+ the backup tile of #66): one "backup wiring" card.
* T-009 into T-004's record (both are measurement records of the same runs; T-009 is S).
* T-306 into T-305 (same night sequence, T-306 must follow T-305).
* T-308 into T-311's slot (same page file, T-308 rebases on T-311).

### C.3 Cards that should split (more than one agent session of two weeks, or several unrelated subjects)

| Card | Why | Split along |
| --- | --- | --- |
| T-102 (L) | `permit` + matrix + two new roles + 54 inline checks + three wrappers + team fallback | (a) `permit` and matrix with wrappers; (b) steward role and admin without PHI (= FG D-280); (c) call-site migration by page group |
| T-108 (L) | six subjects: limits, systemd, egress, mail gateway, job cancel/breaker, declared config | (a) compose limits and health; (b) systemd + egress persistence (CR-043); (c) mail outbox and resolve (CR-085); (d) cancel, breaker, config list |
| T-212 (L) | PPAP, HAPI token, DB roles, verified caller, SSRF, scrubber, gitleaks | (a) mail boundary (CR-025); (b) gateway caller and routing (CR-040); (c) DB roles and HAPI (CR-037); (d) SSRF, scrubber, gitleaks |
| T-210 (L) | Windows hardening + KEK + encryption at rest + unseal | (a) preflight and `check_host --wsl2`; (b) `kek.py` and key loading; (c) encrypt `phi` outputs and uploads |
| T-211 (L) | signed heads + one writer + NTP + audit browser | (a) signing and off-box heads; (b) one writer; (c) audit page |
| T-209 (L) | metrics + admin tiles + support bundle + monitoring profile | (a) `/metrics` and thresholds; (b) support bundle; (c) admin remainder after #66 |
| T-112 (L) | schema and state machine + page + API + adapter hook | (a) `dataops` schema and hook; (b) console page and API |
| T-203 (L) | `vec` schema + chunker + migration from DuckDB + screen.py source + neighbours page | (a) store and chunker; (b) S2b source behind a flag (safety core); (c) neighbours page |
| T-302 (L) | arms/events, repeating instruments, copy-assist, ODM import, consent record, sponsor fit | at least three: REDCap structure; copy-assist page; ODM import and sponsor readers |
| T-304 (L) | statistics page + five exports | (a) stats; (b) EXTRACT and Define-XML; (c) audit CSV, ISF bundle, activity report |
| T-305 (L) | back-fill + pinned snapshots + batched publish + retention | (a) snapshot pinning (CR-063, a safety property: pull forward); (b) back-fill; (c) retention |
| T-310 (M) | four unrelated parts | weekly sample; IRB-text gate; override report; SAE (to the SAE card) |
| T-311 (L) | profile writer + page + two protocol drafts | code; documents |
| T-315 (L) | PQ script + IQ/OQ/PQ protocols + dry-run tooling + coverage targets | three |
| T-316 (L) | code-map registry + signed counts + de-identified export | three |
| T-320 (M) | site set-up limits, EMR link, work log, admin leftovers | EMR link (a reveal, safety core) apart from the rest |
| T-213 (L) | environment + drill list, "spread over the wave", blocked on hardware | environment compose; drills as code |
| T-301 (L) | many pages, help, card, `.ics` | by page group |
| T-012 (L) | command + registry control + page + schema | (a) `qualify` and record; (b) registry refusal in PRODUCTION |

### C.4 Card text that no longer matches the repository

* File names: cards say `tools/trialbox_doctor.py` and `tools/trialbox.py`; the files are `tools/trialbox/doctor.py` and
  `tools/trialbox/__main__.py`. Affects T-012, T-108, T-109, T-113, T-117, T-209, T-210, T-211, T-214, T-319.
* T-213 wants a new `tools/acceptance.py`; a file of that name exists (D-83).
* T-114 says "rented cloud B200"; the owner uses his own B200.
* T-309: contract differs from the recorded owner decision (C.1).
* T-010: the protocol still says the PI is open; the owner fact is that the PI is named.
* Card decision numbers D-190 to D-207 are partly taken (section E).
* T-101 depends on T-012 in the card; PR #75 was built without it.
* T-110 depends on T-104; #61 merged without it (no `deploy/images.lock`).
* RUNBOOK sections: cards reserve §12 (T-003), §13 (T-011), §14 (T-113); master already uses §12 for identity (#67) and
  PRs #64, #66 and #68 each renumbered their section to §14.

## D. File-touch matrix

### D.1 Open PRs against each other (shared files; from `git diff --name-only origin/master...<branch>`)

| Pair | Shared files | Risk |
| --- | --- | --- |
| #82 × #83 | 14: `Makefile`, `deploy/docker-compose.yml`, `deploy/docker/db.Dockerfile`, `deploy/docker/db-init/20-extensions.sh`, `deploy/docker/db.groonga-archive-keyring.asc`, `deploy/images.lock`, `docs/DATA.md`, `docs/decisions/D-204-…md`, `libs/tb_common/db.py`, `libs/tb_contracts/generated/models.py`, `services/orchestrator/db_pg.py`, `tests/integration/test_db_image.py`, `tests/unit/test_migrations.py`, `tools/backup_drill.py` | **high** (two versions of T-104) |
| #68 × #83 | `Makefile`, `deploy/docker-compose.yml`, `docs/RUNBOOK.md`, `tools/apply_update.sh`, `tools/trialbox/update.py`, `tools/verify_update.py` | **high** |
| #66 × #86 | `docs/DECISIONS.md`, `services/console/{app,auth,home,step4}.py` | **high** |
| #66 × #68 | `deploy/docker-compose.yml`, `docs/DECISIONS.md`, `docs/RUNBOOK.md`, `tools/trialbox/__main__.py` | high |
| #68 × #85 | `deploy/egress.py`, `docs/RUNBOOK.md`, `tools/trialbox/__main__.py`, `tools/trialbox/doctor.py` | high |
| #68 × #71 | `.env.example`, `Makefile`, `deploy/docker-compose.yml`, `tools/trialbox/doctor.py` | moot if #71 is closed |
| #76 × #82 | `services/criteria_compiler/app.py`, `services/criteria_compiler/terminology/mapper.py` | medium (safety-core adjacent) |
| #75 × #82, #75 × #83 | `libs/tb_contracts/generated/models.py` | medium (regenerate, never hand-merge) |
| #66 × #82, #66 × #70, #70 × #82 | `services/sitesetup/service.py` (+ compose for #66 × #82) | medium |
| #66 × #83 | `deploy/docker-compose.yml`, `docs/RUNBOOK.md` | medium |
| #66 × #85 | `docs/RUNBOOK.md`, `tools/trialbox/__main__.py` | medium |
| #66 × #71, #71 × #86 | `services/console/app.py` (+ compose) | moot if #71 is closed |
| #68 × #82, #71 × #82, #71 × #83 | `Makefile`, `deploy/docker-compose.yml` | medium |
| #76 × #86 | `docs/DECISIONS.md`, `tools/e2e_simple.py` | medium |
| #82 × #86 | `services/omop/__main__.py` | low |
| #71 × #75 | `docs/ARCHITECTURE.md` | low |
| #71 × #85 | `tools/trialbox/doctor.py` | moot if #71 is closed |
| #64, #66, #68, #76, #80, #86 pairwise | `docs/DECISIONS.md` (tail append) | certain textual conflict, trivial content |
| #64, #66, #68, #83, #85 pairwise | `docs/RUNBOOK.md` | medium (§14 claimed three times) |
| #70, #73, #78, #80 with any other | none beyond the above (#70: `sitesetup/service.py` only) | none |

Conflict with master today (`git merge-tree`): #66, #68, #80 `docs/DECISIONS.md`; #76 `docs/DECISIONS.md` and four
refdata files; #75, #83 generated models; #82 `docs/DATA.md`, generated models, `services/criteria_compiler/app.py`;
#85 `docs/RUNBOOK.md`; #71 thirteen or more files; #64, #70, #78, #86 clean.

### D.2 Hot files: open PRs, fix groups and not-started cards on the same file

Fix groups are placed by the files their register rows cite. Cards are placed by their declared "May touch".

| File or directory | Open PRs | Fix groups | Cards not started / WIP | Risk |
| --- | --- | --- | --- | --- |
| `docs/DECISIONS.md` | #64, #66, #68, #76, #80, #86 | every D-271 to D-281 if they follow #86's pattern | all, until T-002 | **high** |
| `docs/RUNBOOK.md` | #64, #66, #68, #83, #85 | — | T-004, T-011, T-012, T-108, T-114, T-119, T-202, T-209, T-211, T-213, T-214, T-306 | **high** |
| `deploy/docker-compose.yml` (and `-*.yml`) | #66, #68, #71, #82, #83 | — | T-104, T-108, T-212, T-306; new files from T-209, T-213 | **high** |
| `services/console/app.py` | #66, #71, #86 | D-272 (PX-3), D-273 (PX-4, PX-5) | T-102, T-103, T-110 residue; one `include_router` line from T-107, T-112, T-201, T-203, T-209, T-211, T-302, T-303, T-304, T-307, T-309 | **high** |
| `services/console/auth.py` | #66, #86 | D-279, D-280 | T-102, T-109 residue | **high** |
| `services/console/home.py` | #66, #86 | D-273 | T-102, T-103, T-216, T-301 | high |
| `services/console/team.py` | #86 | D-273 (PX-7) | T-102, T-103 | high |
| `services/console/edc_pages.py`, `services/edc/*` | #86 (`edc_pages.py`) | D-279 (P-2), D-281 | T-115, T-205, T-302 | **high** |
| `libs/tb_common/authz.py` (+ `authz_matrix.yaml`) | #66 | D-273, D-280 | T-102; later T-303, T-309, T-310, T-314 | high |
| `services/console/i18n*.py`, `templates/*` | #66 (`i18n_home`, `i18n_ops`, 8 templates), #76 (`i18n_site`, `i18n_step4`, 1 template) | D-273 pages | T-116 (all i18n and templates), T-216, T-301 | high for T-116 |
| `tools/trialbox/doctor.py` | #68, #71, #85 | — | T-109 residue, T-117 residue, T-209, T-210, T-211, T-214, T-319 | high |
| `tools/trialbox/__main__.py` | #66, #68, #85 | D-274 (restore entry) | T-012, T-108 | medium |
| `tools/trialbox/backup.py`, `backup_schedule.py` | #66 (`backup.py`) | D-274 | T-117 residue | high |
| `tools/trialbox/update.py`, `tools/verify_update.py`, `tools/apply_update.sh` | #68, #83 | D-274 (rollback) | T-210 | high |
| `libs/tb_contracts/generated/models.py` | #75, #82, #83 | — | any card adding a schema (T-011, T-012, T-110 residue, T-204) | medium (regenerate) |
| `services/sitesetup/service.py` | #66, #70, #82 | D-271 (CR-052), D-273 (CR-055) | T-202, T-320 | high |
| `services/criteria_compiler/compile_sql/generator.py` | #82 | D-275 | T-207, T-216 | **high** (safety core) |
| `services/criteria_compiler/app.py`, `terminology/*` | #76, #82 | — | T-107 | medium |
| `libs/tb_common/db.py`, `services/orchestrator/db_pg.py` | #82, #83 | D-274 (cites `db.py`) | — | high |
| `deploy/docker/db-init/*` | #82, #83 | — | T-115, T-117, T-212 (roles), CR-037 | medium |
| `deploy/egress.py`, `deploy/install.sh`, `deploy/check_host.sh` | #68 (all three), #85 (`egress.py`) | — | T-108, T-210, T-212, CR-058 | high |
| `services/gateway/core.py` | #75 | — | T-212 | medium |
| `services/omop/load.py` | — | D-271 | T-106, T-201, T-202, T-206, T-305 | high |
| `services/lake/store.py` | — | D-271 | T-203, T-305 | high |
| `services/adapter/pipeline.py` and readers | #70 (ssmix2 source, mapping engine) | D-271, D-275 | T-106, T-112, T-305, T-306 | high |
| `libs/tb_common/audit.py` | — | D-272 | T-211 | medium |
| `libs/tb_common/reasons.py` | #70 | — | T-201, T-216 | medium |
| `services/llm_stub/handlers.py` | #70 | D-276 (stub personas) | — | medium |
| `services/orchestrator/scenarios/screen.py` | — | — | T-203, T-211 | medium (safety core) |
| `tools/omop_parity.py`, `tools/pglocal.py` | #71 | D-271 | T-106 | medium |
| `tools/make_bundle.sh` | #68 | — | CR-046 | medium |
| `Makefile` | #68, #71, #82, #83 | — | T-214 | medium |
| `.github/workflows/trialbox-ci.yml` | — | — | T-202, T-212, T-215, T-315 | low |
| `docs/plan/sites/it-security-pack.md` | #85 | — | T-209, T-210, CR-090 fix | low |
| `tests/golden/*` (regenerated, not edited) | #71 | D-275 moves funnels | #70 may move funnels; T-105, T-106, T-118 | high in effect: one regeneration at a time |

**Hot files (touched by three or more open items):** `docs/DECISIONS.md`, `docs/RUNBOOK.md`,
`deploy/docker-compose.yml`, `Makefile`, `services/console/app.py`, `services/console/auth.py`,
`services/console/home.py`, `services/console/edc_pages.py` with `services/edc/*`, `libs/tb_common/authz.py`,
`tools/trialbox/doctor.py`, `tools/trialbox/__main__.py`, `tools/trialbox/update.py` with `tools/verify_update.py`,
`tools/trialbox/backup.py`, `libs/tb_contracts/generated/models.py`, `services/sitesetup/service.py`,
`services/criteria_compiler/compile_sql/generator.py`, `services/omop/load.py`, `services/adapter/pipeline.py`,
`deploy/egress.py` with `deploy/install.sh`, `deploy/docker/db-init/`, the console i18n files and templates, and the
goldens.

There is no migrations directory yet: migrations are DDL lists inside `libs/tb_common/db.py` and each store module
until T-104 lands, so every card that adds a table conflicts with T-104's change of the migration mechanism.

### D.3 Not-started cards against each other

The assessment's own matrices (§4.3 to §4.5) still hold for cards that have not started. Pairs to add or stress:

| Pair | Shared | Risk |
| --- | --- | --- |
| T-102 × FG D-273 / D-280 | `authz.py`, `auth.py`, `home.py`, `team.py`, `app.py` | high: same lines |
| T-115 × T-205 × FG D-281 | `services/edc/*`, `edc_pages.py` | high |
| T-108 × T-212 | `deploy/docker-compose*.yml`, `services/mail_gateway/*`, egress | high |
| T-106 × T-202 × T-201 × T-206 × T-305 | `services/omop/load.py` | medium (ordered in the assessment: T-202 → T-201 → T-206 → T-207) |
| T-203 × T-305 | `services/lake/store.py` | medium |
| T-203 × T-211 | `scenarios/screen.py` | medium |
| T-207 × FG D-275 | SQL generator derived templates | high |
| T-116 × every page card | i18n files and templates | high during T-116's slot |
| T-209 × T-210 × T-211 × T-214 × T-319 | `tools/trialbox/doctor.py` | medium (one function each) |
| T-012 × T-101 (#75) × T-208 | admin models page, `tools/qualify.py` | medium |
| T-303 × T-309 × T-310 × T-314 | `authz_matrix.yaml` | low (append-only rows) |

## E. Decision-number collisions

State of numbers on master: `docs/DECISIONS.md` holds D-01 to D-151 (no D-99), D-160 to D-163, D-170 to D-172, D-185 to
D-193. `docs/decisions/` holds D-201, D-203, D-205, D-206, D-207.

| Number | Claimed by | Kind |
| --- | --- | --- |
| **D-201** | master: test isolation (T-003, `docs/decisions/D-201-test-isolation-and-disk.md`). PR #75: prompt registry (`D-201-prompt-registry.md`, 28 references in code). Card T-101 reserved it | **live collision**: two files, both would merge without a textual conflict |
| **D-205** | master: committed goldens (T-006). PR #82: vocabulary schema (`D-205-vocabulary-schema.md`, 44 references). PR #71: goldens (same as master). Card T-105 reserved it | **live collision** |
| **D-204** | PR #82 and PR #83 each add `D-204-db-image-and-checksummed-migrations.md` with different content. Card T-104 reserved it | same decision, add/add conflict |
| D-203 | master: data-handling scan (T-005). Card T-102 reserved D-202 and D-203 | reservation void |
| D-206, D-207 | master: CI gate (T-007), feature flags (T-008). Card T-106 reserved both | reservations void |
| D-190 to D-193 | master: derived scores (D-189/190, #59), SAE register (D-191, #60), identity and TLS (D-192/193, #67). Cards T-002 to T-005 reserved D-190 to D-193 | reservations void; the cards took D-201, D-203 instead |
| D-194, D-196, D-200 | reserved by cards T-006, T-008, T-012; master's decision files for T-006 and T-008 mention the old numbers and use D-205, D-207 | T-012's D-200 still free |
| D-170 to D-175 | D-170 to D-172 on master (#65). PR #76's branch carries its own copy of D-170 to D-172 beside D-173 to D-175 | textual conflict, same numbers same meaning |
| D-176 to D-181 | #68 (176, 177), #66 (178, 179), #80 (180), #64 (181) | consistent; all in `docs/DECISIONS.md` |
| D-182 to D-184 | "reserved for the sibling's overflow" | unused |
| D-186 | #61 (merged); PR #78 is titled "D-186 follow-up" | no new number; fine |
| D-270 to D-289 | assessment §5.1 item 7: "the integrator allocates from D-270 for new cards". Register and owner-decisions doc: D-270 to D-289 are the critical-issues fix phase; D-270 to D-281 are named (FG-A to FG-L); PR #86 uses D-270 | range claimed twice |
| D-208 to D-262 | card reservations (T-108 D-208 … T-320 D-262); in use by PRs: D-210 (#83), D-211 (#85), D-215 (#70) | consistent |
| D-263 to D-269 | reserved for G2 remainders | unused |
| D-152 to D-159, D-164 to D-169 | unused gaps (to be recorded by T-002) | — |

Second problem, the form: six open PRs (#64, #66, #68, #76, #80, #86) still append an entry to `docs/DECISIONS.md`;
five (#70, #75, #82, #83, #85) add a file under `docs/decisions/`. Master has both forms.

**Proposed rule.**

1. A number belongs to whoever has it on master. Every unmerged claim to a number that is on master is void.
2. Renumber now, before any merge: PR #75 (D-201) and PR #82 (D-205) take new numbers from the block of rule 3.
   D-204 stays T-104's: one file, taken from the #83 version; #82 drops its copy.
3. Open a fresh block for everything not yet merged and not in D-170 to D-181, D-208 to D-262 or D-270 to D-289:
   **D-300 upward**, one row per number in `docs/decisions/REGISTRY.md` (T-002), added by the integrator before the
   branch is cut. Suggested first rows: D-300 prompt registry (#75), D-301 vocabulary schema (#82), D-302 permission
   matrix (T-102), D-303 OMOP schema name and D-304 dual write (T-106), D-305 `qualify` (T-012, in place of D-200 if a
   clean start is preferred).
4. D-270 to D-289 stay with the critical-issues fix groups. Strike assessment §5.1 item 7.
5. Card reservations D-208 to D-262 stay valid; TB-PLAN-06 cards that are new take D-300+.
6. Form: D-170 to D-193 and D-270 (already written that way in #86) may stay in `docs/DECISIONS.md` only if they merge
   before T-002; from T-002 on every new entry is a file and `tools/decisions_index.py --check` runs in CI job `docs`.
   Simplest: T-002 lands first and converts the six pending tail entries to files at merge.
7. The check fails on: a duplicate number across `DECISIONS.md` and `docs/decisions/`; a file whose number has no
   `REGISTRY.md` row; a code comment citing a number with no entry.

## F. Items in the other sources that have no card

### F.1 Status doc §2.5

| Item | State | Card |
| --- | --- | --- |
| UTC "today" in the console | PR #86 | none needed |
| #71 remaining review fixes (failed flag commit recorded; rebuild source log; 503 on a dead flag store; reads create nothing; third night; `--write` needs both sources) | not on master | **none** |
| SQL/CQL engines without impossible-value guards | CR-115, FG D-275 | none needed |
| Gemma 4 31B (official) in the judge bake-off | not started; needs #64 and G1 | **none** |
| P0 baseline data (drug classes, NHI ATC, ICD bridges, MHLW lists, CTCAE, dictionaries) | part in #65 (merged) and #76 | **none** for the rest |

### F.2 Left to the integrator by the assessment (end of §3.4), no card

WS-02.5 hosted-demo hardening remainder (matters for the PoC: the hosted demo is the PoC surface); WS-08.8 reference
data; WS-15.* (owner and counsel); WS-16.2 baseline (owner, due 11-30); WS-17.3 training.

### F.3 The seven follow-up tasks

No T-number. Two merged (#65, #79); five open (#64, #66, #68, #76, #80). TB-PLAN-06 should give each open one an id.

### F.4 "Open / Not done" blocks of `docs/DECISIONS.md` and `docs/decisions/` with no card, fix group or PR

| Decision | Item | Note |
| --- | --- | --- |
| D-111 | PHI pass on note text (FR-DEID-01) | = CR-028, orphan |
| D-112, D-124 | A physical RTX 5090 record; answers after a wake | no card |
| D-113, D-122, D-130, D-142 | CQL path reads the enumerated list only and ignores the comparator (censored values) | no card; T-306 keeps the CQL gate |
| D-114 | Reads open on the internal network; no mTLS | no card (T-212 does not name mTLS) |
| D-122, D-137, D-142 | Japan completeness: real MEDIS/JLAC10/YJ releases, ADT-52, OMP-11/12 administrations, AllergyIntolerance, `_contents.xml`, PRB-10 ICD-10 position, PRB-14 status map, JP Core validator run | no card (CR-015 is the owner side) |
| D-129, D-134 | Calculated fields not computed; schedule not versioned with amendments; unscheduled visits; appointment source not joined to participants; REDCap "erase hidden values" | no card (T-302 covers repeating instruments, arms, ODM import only) |
| D-135 | Tesseract never run for real | inside T-004's acceptance; no card of its own |
| D-138 | Mail passwords and the cloud key in `deploy/.env`; the offline installer; wizard default `TB_CTGOV_MODE=cassette` (owner) | T-212 names "secrets" only; installer and default: none |
| D-140, D-172 | Full CT.gov download; NHI service-code fetcher; full NHI drug list; 2014-code mapping at ingest; withdrawing a source; jRCT; TFDA/UMIN in COHORT | no card (WS-08.8) |
| D-141 | Chia, open_cohorts, Synthea not run; billing budget (owner) | no card |
| D-142 | `doctor` does not fail when the gateway would refuse the judge (also CR-097's residue); LLM-2 step confirmation (`X-TB-Step`) | no card |
| D-143 | SAE reporting clock per box, not per study; "approached" has two words per language; rate limits in memory | first: none (not in FG D-277's rows); second: T-116 could take it; third: T-103 |
| D-146 | Mail limit shared per sender; investigator cannot refresh feasibility (J-22) | no card |
| D-149 | Shipped mappings declare no `unit_defaults` | no card (site survey item) |
| D-150 | Real weight pins on the VM (M-09); L-01, L-02; serving-record capture not rehearsed | T-119 does not name them |
| D-160 | Accept-without-edit weekly report | no card (after go-live) |
| D-186 | `THIRD_PARTY_NOTICES.md`; SBOMs in the bundle; `--gates` mandatory | = CR-046, orphan |
| D-188 | Docker-side backup runs; `doctor` on a local-only target; install of the cron; review items M2, M7, M8 | = CR-058, orphan |
| D-190 | eGFR under-18 rule; `Observation.status` in the lake table | first: none; second: FG D-275 (CR-005) |
| D-192 | Breached-password list; password history; `doctor` failing without MFA; WebAuthn in the console | not in FG D-279's rows; T-109 is closed |
| D-201 (file) | Random-order nightly job; `.cache/complete-run` out of the tree; tools' `/tmp/tb-*` defaults | no card |
| D-203 (file) | Scan limits: names outside the surname lists, split FHIR names, bare chart numbers until sites state formats, identifiers inside `.duckdb`/`.xls`/`.sqlite` | no card; revisit after the site survey |
| D-205 (file) | 50k goldens | T-004 follow-up |

Covered and so not listed: D-147 (FG D-278, T-102), D-149 opt-out worker (T-206), D-160/D-162 (T-115, T-205, T-302),
D-185 (`make venv` now uses `uv sync --frozen`: fixed, `Makefile:31`), D-189 (FG D-275), D-191 (T-310 / CR-012),
D-139 re-review and translated guides (T-317).

### F.5 WS-18 deferred items (TB-PLAN-05 §WS-18): no card by design

| ID | Item | Earliest |
| --- | --- | --- |
| WS-18.1 | Mail with answer buttons and treating-physician accounts; patient-initiated intake; stipend tracking; sponsor feasibility questionnaire filler; search; close-out and archive; site performance metrics | P1, after go-live |
| WS-18.2 | Opt-in patient messages (SMS, LINE); LINE WORKS and Teams staff notices | P1, P2 |
| WS-18.3 | Service merge to five processes; `psycopg_pool` | P1 |
| WS-18.4 | Consortium exchange between real sites; multilateral DSA; MOHW approval | P1 |
| WS-18.5 | Fleet telemetry and release channel; second model pair; forecast layer; Study B | P2 |
| WS-18.6 | Remaining 157 phenotype definitions; missing specialty-template items | P1, P2 |
| WS-18.7 | Front-end design-system assessment (MR-216) | P2 |

TB-PLAN-06 should carry these seven as one "deferred" table so they stay visible.

## G. Assumptions

* "Not started" means no named deliverable and no matching string on master; work in a session's private checkout would
  not be seen.
* Fix groups D-271 to D-281 are treated as coverage because the register and the status doc say a session holds them;
  none could be inspected.
* Register rows marked n/v keep the register's status.
* CR-070 and CR-093 are restated from the owner facts in the common brief, not from the repository.
* Sizes are the cards' own; the split proposals of C.3 use the brief's scale (L = one to two weeks of one session).
