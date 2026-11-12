# TB-DR2-03 Code quality and software engineering

| Field | Value |
| --- | --- |
| Document id | TB-DR2-03 |
| Date | 2026-11-12 |
| Tree | `514ae9b` (branch `claude/deep-review-2026-11-12`, same tree as master) |
| Area | tests, CI gates, typing, error handling, logging, dependencies, security engineering |
| Run here | `make lint` (ruff, ruff format, mypy strict over 1,075 files, doclint, contracts): clean, 60 s. The unit suite with 2 workers under a 24-minute cap (§3.1). `make property` and the targeted tests of §3.2. Two small probes (the log scrubber, DuckDB error text). `uv pip list --outdated`. `tools/gen_traceability.py --check`. Read-only GitHub REST calls for branch protection, workflow runs, check runs and job logs. |
| Tried, not finished | `make data-scan` (stopped at 280 s with no result; the machine had a load of 20 on 4 cores, CI needs 121 s). `make security-scan` (see §3.2). |
| Read only | everything else: the workflows, the Makefile, `pyproject.toml`, the locks, the console's sign-in, session, CSRF and permission code, the service tokens, the ingest pipeline, the audit log, the guard, the logging module, the supply-chain allow-list. |
| Not run | `pip-audit` (not in the venv), the image builds and scans (no Docker daemon), the compose stack, the browser walk, mutation testing. |

## 1. Reading in ten lines

1. The code is clean by every static measure: ruff with security rules, `mypy --strict` over libs, services, tools and tests with 86 `# type: ignore` in 195,000 lines, one bare `except`, no mock library anywhere, a real PostgreSQL under every database test. Dependencies are current (6 packages behind, only DuckDB 2.0 is a major).
2. The merge gate does not gate. Master is unprotected, pull requests are merged before their checks finish, and PR #303 was merged 37 minutes before its own `unit` job failed. That failing test is on master now (ENG-001).
3. The unit job takes 35 to 56 minutes in CI. Merges land every 4 to 5 minutes, so 23 of the last 30 CI runs on master were cancelled. Nobody waits for an hour-long gate.
4. The nightly jobs are red and nobody is stopped by it: the compose stack has not started for two nights, so no compose test, no e2e mail test, no browser walk and no pgvector or PGroonga SQL test has run in CI (ENG-002).
5. The cause of the red compose stack is a real go-live defect: in PRODUCTION the embed service refuses the stub and needs `sentence-transformers`, which no image the build produces contains, and no embedder model is chosen yet (ENG-003).
6. The suite itself documents wrong answers: 50 strict expected failures in CI, among them "an opted-out patient whose chart was merged still shows on the console" and "one model's note answer drops a patient in NAV". They keep CI green and have no cards (ENG-004, ENG-005).
7. Tests do aim at the real risks (units, dates, the two-model rule, opt-out, partial ingest, audit chain). The measured weakness is depth: the first nightly mutation score of the safety core was 66.6 % against a 90 % target, with the floor set at 60 % (ENG-006).
8. Authentication and authorisation are in good shape: ROLE-001, 005, 008, 010 and 011 of the last review are fixed and hold in tests run here. One permission function reads one matrix; unknown role or action is refused.
9. PHI in logs has two real holes: the log scrubber skips dict and list fields, and DuckDB error text (which quotes row values) travels into job error details and tracebacks (ENG-008, ENG-009). The PHI guard still runs without the site chart-number pattern when the configuration cannot be read (ENG-007).
10. The console's route code got worse: `create_app` is now one function of 1,728 lines, `home.register` 1,252, `team.register` 943 (ENG-012). 337 accepted image vulnerabilities all lapse on 2026-12-10 with "owner: to assign" (ENG-013).

## 2. Status of the previous review's findings

Checked in code, tests or by a run on this tree, not in a document that says so.

### 2.1 TB-DR-04 engineering quality (all 36)

| Old ID | Sev. | Status | Evidence on `514ae9b` |
| --- | --- | --- | --- |
| ENG-001 | High | fixed | `docs/validation/software-safety-classification.md` exists; `tools/mutation.toml` `[safety_core]` lists the 18 files. Content not judged here. |
| ENG-002 | High | open | `tools/gen_traceability.py --check` run here: "130 items, 92 requirements, 50 risks, 63 tests, 273 links; clean". The check is warnings only (Makefile `ci`, D-311). No executed evidence is attached to a row. |
| ENG-003 | High | partly | `docs/validation/problems.csv` has 49 rows with state, fix PR and verifying test. GitHub Issues are still off (`has_issues: false`). The 455 findings of the last review and the G1 bugs are not all in it. |
| ENG-004 | Medium | fixed | `../.github/PULL_REQUEST_TEMPLATE.md` is TrialBox's (card, summary, data rules). |
| ENG-005 | High | **open** | Run here: `gh api repos/.../branches/master` → `"protected": false`, required checks `[]`, enforcement `off`. See ENG-001 of this review. |
| ENG-006 | Medium | open | `trialbox-supply-chain.yml:11` still has `paths:`; runs on PR paths and weekly. |
| ENG-007 | High | partly | Report mode is kept only for the two test mail servers; HAPI and vLLM findings are 307 dated allow-list entries instead (`deploy/supply-chain-allowlist.yaml`). They all lapse on 2026-12-10 (ENG-013). |
| ENG-008 | Medium | partly | `docs/validation/soup.csv` has 23 rows. Not judged per item. |
| ENG-009 | Low | not checked | |
| ENG-010 | Medium | fixed | `tools/security_scan.py secrets` (detect-secrets 1.5.0), CI job `security`. The repository is now private. |
| ENG-011 | Medium | partly | bandit 1.9.4 gates at medium; ruff still ignores S603, S607, S608, S105, S106, S324, S104 tree-wide and all of `S` under `tools/**` (`pyproject.toml`). 57 reviewed ignores, 17 of them B608 (SQL from strings). |
| ENG-012 | Medium | **worse** | `create_app` 1,728 lines (was 1,518); `home.register` 1,252 (was 973); `team.register` 943; `adapter.pipeline._run_ingest` 452. 71 functions over 100 lines, 24 over 200 (measured with `ast`). See ENG-012 of this review. |
| ENG-013 | Medium | fixed | `tools/jvm-deps.sha256` (106 lines) and `tools/fhir-packages.sha256`; the fetch fails on a missing, extra or changed jar. |
| ENG-014 | Medium | fixed | CI reads `trialbox/.java-version`; `deploy/docker/jvm.Dockerfile:8` is Temurin 21 by digest. |
| ENG-015 | Medium | partly | OCI labels with version and commit (Makefile `OCI_LABELS`). `python.Dockerfile:16` and `demo/Dockerfile:25` still run `apt-get upgrade`; no `SOURCE_DATE_EPOCH`. |
| ENG-016 | High | fixed | `services/criteria_compiler/equivalence/gate.py:67,112,159`: a criterion with 0 patients compared fails; `min_sample` from the sample size (T-652). Read, not run. |
| ENG-017 | Medium | partly, in effect open | `trialbox-e2e.yml` job `compose` runs `make test-compose` with `TB_STRICT_SKIPS=1`. It failed on 2026-11-10 and 2026-11-11 at `make up-test` (ENG-002 of this review). |
| ENG-018 | Medium | partly | Nightly mutation job exists (`trialbox-nightly-quality.yml`, `tools/mutation.py`). Survivors are listed, not yet killed (ENG-006). |
| ENG-019 | Medium | partly | Same. |
| ENG-020 | High | partly | The coverage ratchet has per-file floors for the safety core (`tools/coverage_ratchet.py`, `tools/mutation.toml`); the target is 95 % line and 90 % branch, "one that is not there yet may not fall under its baseline". Not measured here. |
| ENG-021 | Medium | fixed | `hypothesis==6.170.15` in the test group; `tests/property/` (2 files); `make property` run here (§3.2). Five skip reasons still say "hypothesis is not a dev dependency yet". |
| ENG-022 | Medium | **open, now proven** | The v1 path (`orchestrator/scenarios/evaluate.py`) and the cascade still both decide. `tests/property/test_path_independence.py:718-750` lists 33 status differences between paths as strict expected failures (ENG-004). |
| ENG-023 | Medium | open | `services/guard/guard.py:49-56` unchanged. See ENG-007. |
| ENG-024 | Low | fixed | actionlint, hadolint and the Alpine helper are pinned by digest. |
| ENG-025 | Low | fixed | `make ci` runs hadolint with `--failure-threshold warning`, as CI. |
| ENG-026 | Medium | fixed | `make test` depends on `$(JVM_DEPS)` and the fonts. (It needs the network once; this review machine had neither, see §3.1.) |
| ENG-027 | Medium | not reached | `test_gpu_prep` was not reached inside the cap here. |
| ENG-028 | Medium | fixed | `nodb` marker and `make test-pure` (`tests/conftest.py`); a cluster that cannot start stops the run with one message (seen here, §3.1 run 2). |
| ENG-029 | Medium | fixed | `[tool.coverage]`, `tools/coverage_ratchet.py`, CI step "Coverage ratchet". |
| ENG-030 | Medium | fixed | Nightly `perf-5k` (bench gate) passed on 2026-11-11. |
| ENG-031 | Low | partly | `make test-random` and the nightly `random-order` job exist; the job was cancelled on 2026-11-11, so there is no result yet. |
| ENG-032 | Medium | partly | `_schema_version` carries a sha256 per script (`libs/tb_common/db.py:441,492`); a downgrade is "the update path's decision" (`db.py:45`). Not run. |
| ENG-033 | Medium | not checked | `make data-scan` did not finish here in 280 s. CI's `data-scan` job passed on the last complete master run. |
| ENG-034 | Low | open | `../autogpt`, `../Dockerfile`, `../requirements.txt`, `../CONTRIBUTING.md` are still at the repository root. |
| ENG-035 | Low | open | No eslint in the workflows or `tools/package.json`. |
| ENG-036 | Low | open | `services/matching/proposed.py:115,207`, `libs/tb_common/optout.py:229`, `services/edc/prefill.py:99` still classify exceptions by message text. |

### 2.2 TB-DR-08 dependency currency (Critical and High)

| Old ID | Sev. | Status | Evidence |
| --- | --- | --- | --- |
| DEP-001 | Critical | fixed | `translator/pom.xml:18` pins HL7 FHIR core 6.9.12 (the fix was 6.9.10), Jackson 2.21.8, Guava 33.7.2; every jar is in `tools/jvm-deps.sha256`. Not scanned here. |
| DEP-003 | High | fixed | No `eugr/spark-vllm` in `deploy/`; GB10 uses `vllm/vllm-openai:v0.32.0@sha256:befccf…`. |
| DEP-004 | High | partly | vLLM is pinned by digest in every compose file. It is still v0.32.0 with 285 accepted findings that lapse on 2026-12-10 (ENG-013). |
| DEP-005 | High | fixed (read) | `deploy/check_host.sh:51-56` checks the driver against the image's CUDA need through `tools.images_lock host`. Needs a GPU host to prove. |
| DEP-006 | High | fixed | uv 0.13.7 in every workflow. |
| DEP-007 | High | partly | Deployed judge builds name `expected.revision` (`models/registry.yaml`); `sha256` is pinned at the site. The chat-template question belongs to the LLM review. |
| DEP-008 | High | partly | Verifier builds name an expected revision. Same note. |
| DEP-012 | High | **open, now a blocker** | `deploy/requirements.lock` (74 packages) has no `sentence-transformers`, `torch` or `docling`; `deploy/docker/` has only `python`, `jvm` and `db` Dockerfiles. Since T-607 the embed service refuses the stub in PRODUCTION. See ENG-003. |

### 2.3 TB-DR-02b authentication and authorisation (Blocker, Critical, High that are code)

| Old ID | Sev. | Status | Evidence |
| --- | --- | --- | --- |
| ROLE-001 | Blocker | fixed | `services/console/home.py:1354-1401`: with TOTP on, a password without a code gets 401 and opens nothing; failures are not cleared before the code is right. `auth.py:705-717`: an API session is never a cookie session and the reverse. `tests/console/test_api_identity.py` run here (§3.2). |
| ROLE-005 | High | fixed | `authz_matrix.yaml:608-616`: `optout.keep` is steward and privacy only; `team.py:918-922`. |
| ROLE-008 | High | fixed | `team.py:144,246,659`: with no PI named on the log, nobody is PI and no investigator writes the log. |
| ROLE-010 | High | fixed | Matrix: `phi.view` and `id.reveal` are false for admin; `console/breakglass.py` (446 lines) is the only way. |
| ROLE-011 | High | fixed | `auth.py:262-265`: an SMO or CRO account without studies sees none (`NO_STUDY`). |
| ROLE-013 | High | partly | `audit.browse` is a matrix row (admin and coordinator false). The 1,000-event limit and filters were not re-checked. |
| ROLE-002, 003, 004 | Blocker to High | not checked here | Demo image and hosting; CI job `demo-boot` passed on the last complete master run. |
| ROLE-009, 012, 014 | High | not checked here | Role model and missing features: the role-journeys review. Seven roles now exist (`auth.py:47`). |

## 3. What was run

### 3.1 The unit suite (this review owns the broad run)

RUN-PENDING

### 3.2 Other runs

RUN-PENDING

### 3.3 What CI itself says (read through the GitHub REST API, 2026-11-12 about 08:10 UTC)

| What | Result |
| --- | --- |
| Branch protection on master | none (`protected: false`, no required checks) |
| Last 30 `trialbox-ci` runs on master | 6 success, 23 cancelled, 1 in progress (the head, `514ae9b`) |
| Newest complete CI run on master | `f50fc66`, 06:16 UTC, success. Six commits newer than it are on master. |
| Job times of that run | unit 3,352 s; demo-boot 598 s; e2e-simple 273 s; standards 255 s; goldens 232 s; security 158 s; property 122 s; data-scan 121 s; types 63 s |
| PR #303 (T-691, commit `6ddf4be` on master) | merged 07:23:25; its `unit` check finished 08:00:51 with `1 failed, 6586 passed, 20 skipped, 50 xfailed in 2088.94s`: `tests/unit/test_backup_without_pause.py::test_a_backup_taken_while_the_box_writes_restores_exactly_its_snapshot - BackupError: dirs/audit/log.jsonl kept changing while it was backed up (3 reads)` |
| PR #302 (T-690, the head) | merged 07:32:50; on its head commit `changes` and `lock` failed 1 minute later (`upload-pack: not our ref`, the branch was gone) and every other job was skipped |
| PR #305 (T-746) | merged 07:28:08; `unit` still in progress at 08:10 |
| Nightly `trialbox-e2e` 2026-11-10 and 2026-11-11 | failure both nights. 11-11: `compose` failed at `make up-test` (`embed_service.embedder.EmbedderRefused: TB_EMBED_MODE hash is the CI stub and is refused in PRODUCTION`), then the browser walk failed; `public-e2e` failed (`FileNotFoundError: .cache/medtxt/Test collection/MedTxt-CR/MedTxt-CR-JA-training-pub.xml`); `random-order` cancelled; `perf-5k`, `backup-drill`, `update-drill` passed |
| Nightly `trialbox-nightly-quality` (mutation, branch coverage) | 2026-11-11 on master: cancelled after 3 h 12 min. The two runs before it (on the T-651 branch): failure after 3 h and 4 h 58 min |

## 4. Findings

Severity: Blocker = go-live or PoC cannot happen, or a wrong clinical answer silently; Critical = patient-safety, PHI, data-integrity or regulatory risk likely at a site; High = will hurt a site or a deadline; Medium; Low.

| ID | Sev. | Finding | Evidence | Impact | Fix | Card | Flag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ENG-001 | Critical | **The merge gate does not gate.** Master has no protection and no required check; pull requests are merged before their checks end. A pull request whose unit job failed is on master. | §3.3: `protected: false`; PR #303 merged 37 min before its `unit` job failed; PR #302 and #305 merged with `unit` not finished; 23 of 30 master runs cancelled. | Any defect a test would catch can reach master and a release bundle. The failing backup test shows it already happened. Every claim "CI is green" is true only for the 6 commits that happened to finish. | The owner turns on branch protection with the jobs of `trialbox-ci.yml` as required checks (no approval step is needed for this: it is a repository setting). Make the gate fast enough to wait for (ENG-010). Until then: a release is cut only from a commit whose full CI run is green, checked by `tools/supply_chain/release.py`. | T-007 (exists, not done) | PoC |
| ENG-002 | Critical | **The nightly compose, e2e and browser jobs have been red for two nights and nothing reacts.** The stack does not start, so the tests that need the real database image, HAPI, mail servers and a browser run nowhere. | §3.3 nightly rows. `tests/integration/test_vec_store.py:1-7` and `test_vec_s2b_pg.py:3-5`: the pgvector SQL is tested only in `make test-compose`; the unit job's PostgreSQL has no pgvector (`tests/unit/test_erasure_seed.py:228` skips "CI pull-request jobs"). | Untested in CI today: the vector store's SQL and the erasure of a patient's vectors on pgvector; CQL on HAPI and the equivalence gate against HAPI; mail through GreenMail and Mailpit; the role walk; the public-data e2e; random order. A regression in any of them is found at a site. | (1) Fix the stack (ENG-003: the test compose must set `TB_ENV=TEST` for `embed-service`, as it does for the mail gateway at `docker-compose.test.yml:38,76`). (2) Fix `public-e2e`'s missing MedTxt fetch. (3) A red nightly opens a row in `problems.csv` and is the first card of the next day; show the nightly state in the README badge or the daily plan note. (4) Move the pgvector tests into the PR gate by running the unit job's PostgreSQL from the `trialbox-postgres` image. | NEW-ENG-1 "Nightly green again and kept green; pgvector tests in the PR gate" (M) | PoC |
| ENG-003 | Blocker | **In PRODUCTION the embed service cannot start with any image the build produces.** The stub is refused, the real mode imports `sentence-transformers`, which is in no image, and no embedder model is chosen or pinned. | `services/embed_service/embedder.py:127` (import), `:199-204` (stub refused in PRODUCTION), `:206-211` (no pin, refused). `deploy/requirements.lock`: 74 packages, none of `sentence-transformers`, `torch`. `deploy/docker/python.Dockerfile:26` installs only that lock. `deploy/docker-compose.yml:154-160`: `embed-service` runs `trialbox-py:1.0.0`. `models/registry.yaml`: `e-embed-1` has no `expected` revision. The nightly log shows the refusal stopping `docker compose up --wait`. | A box started with `TB_ENV=PRODUCTION` (the default, `docker-compose.yml:293`) does not come up healthy; note retrieval through the vector store (S2b) has no embedder. PoC paths set `TB_ENV=TEST` or `DEV` (`deploy/poc.sh:57-64`) and are not hit. | Choose the embedder (model, revision, licence), add an image that carries the `embed` extra from `uv.lock` with hashes (a second export `deploy/requirements-embed.lock` and `deploy/docker/embed.Dockerfile`, CPU wheels unless the profile gives it a GPU), pin `e-embed-1`, and add a CI job that starts the PRODUCTION compose with that image and a tiny safetensors model and embeds one sentence. | T-607 (reopen) and old DEP-012; NEW-ENG-2 "Embed image with hashed extras and a PRODUCTION start test" (M) | Go-live both |
| ENG-004 | Critical | **An opted-out patient whose chart was merged still shows on the console.** The console reads `OptOutRegister.active()`; the jobs read `effective()` (with the surviving chart). The suite knows: it is a strict expected failure. | `services/console/home.py:150,339,1494`, `services/console/screening_log.py:187` call `.active()`. `libs/tb_common/optout.py:175-186`: `effective()` adds the survivors. `tests/property/test_path_independence.py:901-918` (`xfail(strict=True, reason="M3 …")`). `make property` here: RUN-PENDING. | A patient who said no is listed to a coordinator on the weekly list and the screening log after a chart merge. PHI and consent breach at a site with duplicate charts (every hospital has them). | Four call sites: `.active()` → `.effective()`. Remove the `xfail` in the same change. See §8. | NEW-ENG-3 "Console reads the opt-out register with merged charts" (S) | PoC |
| ENG-005 | High | **CI is green over 50 strict expected failures, 33 of them named path differences in the clinical answer.** Each is a known defect with a finding id from an earlier review (H1 to H4, M1 to M5, CR-026) and no card in the reason. | `tests/property/test_path_independence.py:700-750` (the `KNOWN` table), `:901`, `:922`; `tests/property/test_judge_in_loop.py:541`; `tests/unit/test_valueset_family.py:162`. CI: `50 xfailed` (§3.3). Examples: H2 "NAV drops a patient on one model's note answer"; H1 "SCREEN stored one model's 'present' as verdict=fail"; H4 "the v1 path reads five retrieved chunks; their 'no flare' is final although the flare note was never shown"; M4 "FEAS counts a patient on the opt-out register"; M5 `FULL_RECORD_MAX_CANDIDATES = 100` (`orchestrator/scenarios/evaluate.py:47,702`): with more than 100 candidates in a run nobody's unknown gets the full-record read, so a status depends on run size (also an OD-10 limit with no derivation). | The same patient gets a different status by path (SCREEN v1, cascade, NAV, CASE, FEAS, COHORT, microbatch). At 50,000 patients every run is over 100 candidates. Pinning them is the right test technique; the risk is that "strict xfail" reads as "done". | One card per finding id, each closed by removing its `KNOWN` line. Print the xfail count in the CI summary and fail when it grows. Decide ENG-022 of the last review (retire the v1 path) since most lines come from it. The clinical severity of each line belongs to the matching review. | NEW-ENG-4 "Burn down the KNOWN path differences; xfail budget in CI" (L, split per id) | Go-live both |
| ENG-006 | High | **The safety core's tests kill two mutants in three, and the job that measures it does not finish.** | `tools/mutation.toml:5-9`: target 90 %, floor 60 %, "first nightly scores 66.6 % without the engine shard". §3.3: the nightly quality run on master was cancelled after 3 h 12 min. | A third of small changes to the two-model rule, the proposed-fact rule, the coverage rule and the SQL generator pass every test. The number is not tracked night by night because the job does not complete. | Shard by file so each shard fits its budget; write the score into the repository (a small JSON beside the baseline) on each complete run; raise the floor to the measured score minus 2 points after each run; kill the listed survivors file by file, `pair.py` and `proposed.py` first. | T-651 (exists; add the points above) | Go-live both |
| ENG-007 | Medium | **The PHI guard still runs without the site chart-number pattern when the configuration cannot be read.** | `services/guard/guard.py:49-56` (`except Exception: return cls(None)`); `libs/tb_common/phi_guard.py:290-298` (same, returns None). Used by the gateway tripwire (`gateway/core.py:245`), the trace store (`tracestore/store.py:119`), the doc parser (`doc_parser/parser.py:389`), the lake's note masking (`lake/app.py:38`), the embed service and the reveal page. The logging module already does it right (`libs/tb_common/logging.py:89-101`: the contract's default pattern when no site configuration is readable). | A broken or missing settings file turns off the bare chart-number rule in every PHI guard at once, silently. Labelled numbers are still caught. | In both functions: on failure use the contract default (as `logging.site_rule_on`), and in PRODUCTION raise instead. `trialbox doctor` reports which pattern is in force. §8. | NEW-ENG-5 "Guard never runs without a chart-number rule" (S) | Go-live both |
| ENG-008 | Medium | **The log scrubber does not scrub dict or list fields.** | `libs/tb_common/logging.py:137`: `redact(val) if isinstance(val, str) else val`. Probe run here: `extra={"detail": {"id": "A123456789", "phone": "0912-345-678"}}` is written as is; the same value as a string field becomes `[TWID]`. | An identifier inside a structured log field reaches the log file and the log shipping. | Serialise non-string fields to JSON, `redact` the text, parse back (or walk the structure). §8. | NEW-ENG-6 "Scrub structured log fields" (S) | Go-live both |
| ENG-009 | Medium | **Engine error text that quotes row values travels into job records and logs.** | `services/lake/app.py:73-74`: the 422 body is `str(exc)[:500]` with the comment "no data echoed". Probe run here: DuckDB says `Conversion Error: Could not convert string '王小明' to INT32 when casting from source column name`. `services/lake/client.py:46` raises it on; `services/orchestrator/core.py:677-679` stores `str(exc)[:300]` in `job.error.detail`; `core.py:497` logs the traceback. The same pattern: `adapter/pipeline.py:659,665,710,717` (`errors.append(f"… {exc}")` into `ingest_report.json`, the HELD file and the audit detail), `adapter/app.py:88`. The mailed failure notice uses only the fixed message (good). | A cast or parse error on a text column puts a name or a free-text value into the job record (shown on the job page and in job JSON), the service log (the scrubber catches numbers, never names) and the ingest report. Stays inside the box; still a record that is kept and backed up outside the PHI stores. | At the service boundary keep the error type and DuckDB's error class only; put the full text in a PHI-tagged object next to the job, readable by the roles that read rows. Same for the ingest errors. | NEW-ENG-7 "Error text is PHI: type only in job records and logs" (M) | Go-live both |
| ENG-010 | High | **The gate is too slow to wait for, and its skips do not fail.** The unit job takes 35 to 56 minutes for 6,600 tests. A skipped test passes in the PR gate. | §3.3 job times. Here: RUN-PENDING. `TB_STRICT_SKIPS=1` is set only in `make test-compose` (`Makefile`, `tests/conftest.py:326-335`). 101 skip sites in `tests/`; in CI 20 skip. | An hour-long gate is the reason merges do not wait (ENG-001). A missing jar, font, pgvector or hypothesis turns tests off without a red mark. | Split the unit job into 3 or 4 shards by file (pytest-xdist is already there; the runners have 4 cores); start one PostgreSQL template database per worker and clone it per test instead of migrating each time; print the 30 slowest tests in the job summary and give them a budget; set `TB_STRICT_SKIPS=1` in the unit job with a short allow-list of skip reasons. Target: under 12 minutes. | T-653 (exists; add the shards and strict skips) | PoC |
| ENG-011 | High | **A test of the new nightly backup fails on master in CI.** A backup taken while the audit log is appended to gives up after three reads. | §3.3 PR #303 row. `tools/trialbox/backup.py:589` `READ_TRIES = 3`, `:599-614`: a file whose size or mtime changed during the read is read again, three times, then `BackupError("… kept changing …; run the backup again")`. Run here: RUN-PENDING. | On a box that writes audit events while the backup runs (sign-ins, a night job's steps), the nightly backup fails and asks to be run again. `READ_TRIES` is a fixed limit with no derivation (OD-10). The test is right; the code is wrong for append-only files. | For an append-only file (the audit day files, `*.jsonl`) take the bytes up to the size seen at open and stop: a prefix of an append-only file is a consistent copy. Keep the re-read only for files rewritten in place. §8. | T-691 (reopen) | Go-live both |
| ENG-012 | Medium | **The console's routes and permission checks live in three functions of 1,728, 1,252 and 943 lines, and they grew since the last review.** | Measured with `ast`: `console/app.py create_app` 1,728 lines, `console/home.py register` 1,252, `console/team.py register` 943; `adapter/pipeline.py _run_ingest` 452. Ruff ignores PLR0911/12/13/15. | Route handlers are closures: they cannot be imported, unit-tested or type-checked in isolation, and every change to one page touches the function that holds the permission plumbing of all pages. `_run_ingest` holds the hold, load, rebuild and report decisions in one body (see ENG-014). | No big rewrite. A ratchet: a per-function line budget in CI at today's value for these four functions, lower for all others (ruff `PLR0915` with a per-file ceiling); each card that touches a page moves that page's handlers into an `APIRouter` module with a `Depends` for the session and the permit. | NEW-ENG-8 "Function-size ratchet; routers per page as pages are touched" (S for the ratchet) | Later |
| ENG-013 | High | **337 accepted image vulnerabilities all lapse on 2026-12-10, with no owner named.** | `deploy/supply-chain-allowlist.yaml`: 337 entries `review_by: 2026-12-10` (285 in `vllm/vllm-openai`, 30 in `trialbox-postgres`, 22 in `hapiproject/hapi`), each `owner: security owner (to assign)`. | On 2026-12-10 the image gates and `make release-gates` fail for every image at once; no bundle can be cut until someone moves three base images or re-dates 337 lines. Moving vLLM is a model change that needs requalification on a GPU. | Now: name the owner; schedule the vLLM image move with the next GPU session (requalify once); rebuild `trialbox-postgres` on the current base (30 findings in our own image); take the next HAPI patch image. Give the three images different review dates. | NEW-ENG-9 "Image patch window before 2026-12-10" (M; needs a GPU session for vLLM) | PoC |
| ENG-014 | Medium | **A failed fhir-store load does not stop the lake rebuild, and no test covers that path.** | `services/adapter/pipeline.py:702-712`: `fhir-store load failed` is appended to `errors`; `:714-716`: the lake rebuild still runs because only `held` is checked; `:727`: `passed = not errors`. `grep "fhir-store load failed" tests/` → no test. Read, not run. | The night is reported `ingest.failed` while the lake may have been rebuilt on the new snapshot; fhir-store (the CQL path) and the lake (the SQL path) then hold different nights. | Treat a fhir-store load failure as a held night before the rebuild (set `held`), or load fhir-store after the lake swap with a retry record; add the test first. | NEW-ENG-10 "Partial ingest: fhir-store failure holds the night" (S) | Go-live both |
| ENG-015 | Medium | **The derived-value store has no production caller.** `run_batch` ("the derive batch", nightly) and `DerivedStore.recompute` are called only from tests. | `grep -rn "run_batch\|recompute(" services tools libs` → only `libs/tb_common/derived_store.py:530,548`; callers are `tests/unit/test_derived_store.py` and `test_twin.py`. `patient_profile/twin.py:438` reads the store. | The patient twin's derived layer is always empty on a box; 550 lines and their tests describe behaviour the box does not have. Either a missing wire or dead code. | Decide: wire it after the ingest (beside `twins_after_ingest`, `orchestrator/scenarios/admin.py:58-90`) with a test through the scenario, or remove it until its card. | NEW-ENG-11 "Derived store: wire or remove" (S) | Later |
| ENG-016 | Low | **`tools/pglocal.py` changes the mode of directories outside the test root, and the test cluster can fail to start because of it.** | `tools/pglocal.py:189-197` adds `o+x` to every parent of the root when run as root. Run 2 here failed: `initdb: could not access directory "…/ENG/root/pg-gw0/data": Permission denied` after the session manager set the scratch parent back to 0700 between the chmod and `initdb`. | A developer's private directory becomes traversable by other users without asking; a race makes the suite error on a managed machine. | Refuse with a clear message instead of changing modes (or put the cluster under `/var/tmp/trialbox-<uid>` when the root is not reachable, and say so). | NEW-ENG-12 (S) | Later |
| ENG-017 | Low | **No request id joins the logs of the services.** A job is followed by `job_id`; a console request that calls the orchestrator, the lake and the gateway has no common id. | `libs/tb_common/http.py:105-123` (access log: method, path, status, ms); no `request_id` or `traceparent` in `libs/tb_common`. | Slower diagnosis at a site from a log bundle. | A middleware that takes or makes `X-TB-Request-Id`, puts it in a contextvar, the JSON formatter adds it, the service client forwards it. | NEW-ENG-13 (S) | Later |

RUN-PENDING (findings from the runs)

### Detail by ID

**ENG-001.** `trialbox-ci.yml:19-23` says "a running push to master is never cancelled; a push run still waiting in the group is replaced by a newer push". With a 35 to 56 minute unit job and merges every few minutes, the waiting run is replaced again and again, so most master commits never get a result. That is by design; the design assumes the pull request was green before the merge, and it was not. The plan already says the owner sets branch protection (T-007, plan §7.5, Q-21). It is the cheapest fix in this document.

**ENG-003.** The chain: T-607 (D-429) made the stub embedder a refusal in PRODUCTION, which is right. `docker-compose.test.yml` sets `TB_ENV=TEST` for the mail gateway and one other service, not for `embed-service`, so the test stack runs the embed service in PRODUCTION and it refuses: the nightly broke the day T-607 merged. The same refusal is what a real box meets, and there the fix cannot be "set TEST": it needs the weights, the pin and an image with the library. `tools/supply_chain/lock.py:29` exports "the project's runtime dependencies only (no extras)".

**ENG-005.** The technique is good and should stay: a strict xfail fails the build the day the defect is fixed without removing the line, so the table cannot rot. What is missing is the link from each line to a card and a visible count. The list as of this tree (finding id: paths): H1 microbatch after a single-model run; H2 NAV single; H3 microbatch after an amendment (6 patients); H4 SCREEN v1 and NAV (retrieved chunks final); M1 confidence 0.6 and `contact: deny`; M2 consent read only by the cascade's S0, undated statements sorted differently; M4 FEAS (no value, opt-out register, refusal); CR-026 COHORT counts an opted-out patient; M3 and M5 as separate tests.

**ENG-009.** DuckDB conversion, constraint and parser errors all quote the offending value. The scrubber cannot help with names or free text. The comment at `lake/app.py:73` ("no data echoed") is wrong and will mislead the next reader.

**ENG-010.** The suite is honest work: no mocks, a private database per test, in-process services. That is also why it is slow. The local run here made about 1 test per second on a loaded machine. `tests/conftest.py:202-207` gives every non-`nodb` test its own database; the cost is in creating and migrating it.

## 5. What to drop or simplify

- **The v1 evaluation path** (`orchestrator/scenarios/evaluate.py` structured verdicts and tier beside the cascade). Most of the 33 known path differences exist because two engines decide. One engine, then delete the table. (Old ENG-022.)
- **The derived store batch** until it has a caller (ENG-015).
- **The legacy Auto-GPT tree at the repository root** (`autogpt/`, root `Dockerfile`, `requirements.txt`, `tests.py`, `render.yaml`). It confuses scanners, renovate paths and new contributors. (Old ENG-034.)
- **Five stale skip reasons** "hypothesis is not a dev dependency yet": hypothesis is locked; make them plain imports so a missing package is an error.
- **The message-text exception classifiers** (`"site_fact" in msg and ("exist" in msg or "Catalog" in msg)`): one helper `missing_table(exc, name)` exists in the cascade (`matching/cascade/engine.py`); use it in the other three places or test the catalogue before the query.
- **`make ci` as a second definition of the gate.** It lists the jobs by hand and already differs from the workflow (no `standards`, no coverage ratchet, no `demo-boot`). Keep it, but generate the list from the workflow or test that the two agree.

## 6. What the plan must change (inputs to plan v7)

1. **First day, S, no dependency:** branch protection with the CI jobs as required checks (T-007). Nothing else in this list holds without it.
2. **First week, M:** nightly green again (ENG-002): `TB_ENV=TEST` for the test stack's embed service, the MedTxt fetch for `public-e2e`, the random-order job to completion. Then a rule in the daily plan: a red nightly is the first card.
3. **First week, M, before any more features:** the unit gate under 12 minutes (ENG-010): shards, template database, strict skips. Depends on nothing; unblocks item 1 in practice.
4. **Before G2, M, needs the embedder choice:** the embed image and the PRODUCTION start test (ENG-003). Depends on the model decision (LLM review) and the supply-chain lock export.
5. **Before the PoC, S each:** ENG-004 (opt-out with merged charts), ENG-007 (guard default), ENG-008 (scrubber), ENG-011 (backup of append-only files), ENG-014 (partial ingest).
6. **Before 2026-12-10, M, needs one GPU session:** the image patch window (ENG-013); do the vLLM move together with the next requalification so the GPU is paid for once.
7. **Through G2, L split per id:** burn down the `KNOWN` table (ENG-005) and raise the mutation floor after each complete nightly (ENG-006). Order: H2 and H1 (two-model rule), M4 and CR-026 (opt-out in FEAS and COHORT), H4, H3, M1, M2, M5.
8. **Go-live, M:** error text as PHI (ENG-009).
9. **Later, S:** ENG-012 ratchet, ENG-015, ENG-016, ENG-017.

Sizes: S up to 1 day, M 2 to 4 days, L more than a week or to be split.

## 7. Needs GCP / owner hardware

1. **vLLM image move (ENG-013).** On the GPU profile of each site (RTX PRO 6000; GB10): start the stack with the candidate `vllm/vllm-openai` tag by digest; run `make canary ARGS="--swap"` (the 54-case pair canary) and the judge and verifier qualification (`python -m tools.qualify`, the model-change protocol's set). Record: canary pass count per model and for the pair, structured-output failures, tokens per second. Pass: 54 of 54 for the pair, no schema failure, speed within 10 % of the current row in `docs/plan/gpu-ledger.md`. Then `make release-gates` without `--vuln-mode report` must pass with the 285 vLLM entries removed.
2. **Embed service in PRODUCTION (ENG-003).** On the box hardware: `TB_ENV=PRODUCTION docker compose --profile gpu up -d --wait` with the new embed image and the pinned weights; record the start time, the resident memory of `embed-service` against `TB_MEM_EMBED` (4g), and the time to embed and index the notes of 5,000 patients (`python -m tools.bench_embed`). Pass: healthy start, memory under the limit, the full 50,000-patient index inside the night window measured for that site.
3. **Host driver check (old DEP-005).** On each GPU host: `deploy/check_host.sh`; record the driver version it reads and its verdict; pass: FAIL below the image's CUDA need, PASS on the pinned driver.

## 8. Small certain fixes

1. **ENG-004 (Critical).** `services/console/home.py:150`, `:339`, `:1494` and `services/console/screening_log.py:187`: replace `.optout.active()` with `.optout.effective()` (`libs/tb_common/optout.py:184`). Test that fails first: `tests/property/test_path_independence.py::test_the_console_reads_the_register_as_the_jobs_do` rewritten to drive the console read (today it asserts on `reg.active()` itself, so point it at `effective()` and add a console test with a merged chart on the weekly list); remove its `xfail`.
2. **ENG-011 (High).** `tools/trialbox/backup.py:599-614`: for an append-only file (the audit folder's day files and `*.jsonl`) read exactly `before.st_size` bytes and accept the copy when the file only grew (`after.st_size >= before.st_size` and same inode); keep the re-read loop for other files. Test that fails first: the one that failed in CI, `tests/unit/test_backup_without_pause.py::test_a_backup_taken_while_the_box_writes_restores_exactly_its_snapshot`, run 20 times.
3. **ENG-007 (Medium, safety-relevant).** `services/guard/guard.py:55-56` and `libs/tb_common/phi_guard.py:297-298`: on failure return the contract default `Settings.model_fields["mrn_regex"].default` instead of `None` (the three lines `logging.site_rule_on` already has), and re-raise when `environment_name(os.environ) == "PRODUCTION"`. Test that fails first: a new unit test that makes `get_config` raise and asserts `Guard.from_settings().detect("chart 12345678")` finds the number.
4. **ENG-008 (Medium).** `libs/tb_common/logging.py:137`: `payload[key] = redact(val) if isinstance(val, str) else json.loads(redact(json.dumps(val, ensure_ascii=False, default=str)))`. Test that fails first: log `extra={"detail": {"id": "A123456789"}}` and assert `[TWID]` in the line.
5. **ENG-002 (Critical, the stack part).** `deploy/docker-compose.test.yml`: add `embed-service: environment: {TB_ENV: "${TB_ENV:-TEST}"}` as for `mail-gateway` (line 38). Test: the nightly `compose` job itself.

## 9. What is good

- Typing: `mypy --strict` with the pydantic plugin over 1,075 files including tests, clean; 86 ignores in product code, each with an error code; `Any` at 2 to 3 per 100 lines, mostly lake rows.
- Tests use real things: no `unittest.mock` anywhere, a throwaway PostgreSQL per session and a private database per test, in-process services, strict markers, a `nodb` set that runs with the database refused.
- The strict-xfail table of path differences and the enumerated safety properties are the right way to hold known defects and invariants.
- Authentication: scrypt with per-user salt, password history and breached list, per-address and per-account lockout that cannot be used to lock someone out, TOTP required outside DEV and TEST with replay guard, API and page sessions kept apart, server-side sessions with idle and absolute limits, `HttpOnly` `SameSite=Strict` cookies, CSRF token per session checked by a test on every POST, header SSO refused when TOTP is on.
- Authorisation: one function over one YAML matrix, unknown role or action refused, a generated role × route test.
- Service calls: one token per service with a caller table, signed single-use actor assertions, reads protected where they carry patient rows, fail closed without a token outside DEV and TEST.
- Input handling: ODM XML through expat with DTD and entities off; uploads read with a cap and a sanitised name; SQL identifiers validated and values bound in every f-string query sampled (`vec/store.py`, `cgrd_sql/source.py`, `twpas.py`, `sitesetup/store.py`, `lake/store.py`); an egress guard on every client a person or a document can steer; Jinja autoescape on, one `|safe` (the console's own script).
- Audit: hash chain with a head anchor, fsync, torn-line repair, disk-space check; a reveal is audited before the number is returned.
- Supply chain: one hashed lock, hash-checked image installs, actions and images pinned by digest, jar and package checksums, dated allow-list entries, a secret scan and bandit in the gate.
- Dependencies: 6 packages behind on 2026-11-12 (`datamodel-code-generator`, `duckdb` and its FTS extension 1.5.5 → 2.0.0, `fastapi` patch, `isort`, `types-pyyaml`).

## 10. What was not checked

- The full unit suite to its end on this machine (the cap), `tests/console`, `tests/testbench`, `tests/integration`, `tests/e2e`, the goldens, `e2e-simple`, the bench gate, mutation testing, coverage numbers.
- `make data-scan` (no result in 280 s), `pip-audit`, the image builds and scans, the SBOMs, licences.
- Whether renovate is installed on the repository and opens pull requests (the GraphQL API is not reachable from here).
- OIDC code flow (`console/oidc.py`), break-glass internals, the KEK and key wrapping, pseudonymisation strength, exports: read at the level of entry points only.
- The JVM side (HAPI, cql-to-elm) beyond the pom pins. JavaScript.
- `deploy/monitoring` rules beyond their existence (`prometheus.yml`, `rules.yml`, Prometheus pinned by digest and bound to 127.0.0.1).
- OD-10 limits in general: only `READ_TRIES` and `FULL_RECORD_MAX_CANDIDATES` were met on the way; the scale and timeout review owns the rest.
