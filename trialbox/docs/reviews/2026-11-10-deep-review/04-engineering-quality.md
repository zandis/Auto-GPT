# TB-DR-04 Software engineering quality to industrial standards

| Field | Value |
| --- | --- |
| Date | 2026-11-10 |
| Code read | `claude/tb-deep-review-plan06`, product code identical to `origin/master` at `ca8f287` (later commits on the branch are review documents only) |
| Method | Hands-on. The full unit suite run twice (once more under coverage), every merge gate run, a hand mutation experiment on a copy of the safety core, static reading of CI, lifecycle documents, build files and the safety core. Checked against an IEC 62304-style lifecycle (classification, plan, requirements, architecture, design, test levels, traceability, configuration management, problem resolution, change control, SOUP). |
| What was run | `make check-disk`, `make test` (3 workers), a re-run of every failure, the unit suite under `pytest-cov` (branch coverage), `make lint`, `make e2e-simple`, `make goldens-check`, `make data-scan`, `make lock-check`, `make allowlist-check`, `tools/gen_traceability.py --check`, `tools/complete_run.py --estimate`, `tools/fetch_jvm_deps.sh` into scratch, 28 hand mutants, the GitHub REST API (read only) for branch protection, workflow runs and repository settings. The full command table is in §8. |
| What was not run | Anything that needs Docker images or a GPU: `make images`, `make release-gates` (Trivy, Syft over images), `make pip-audit` and `make licences` (they build venvs from PyPI; their logic was read, and `lock-check` was run), `make test-integration` / `make test-e2e` / `make test-console-e2e` (need the compose stack), `make test-egress` (root, nftables, stack), `tools/complete_run.py` stub parts beyond `--estimate` (the walk needs a public console build; backup and update drills are the same code as the nightly jobs and as e2e_simple's restore stage, see §8), `tests/llm`. `make test-console` was not run separately: `tests/console` (257 tests) is inside `make test` and passed there. |

## 1. Summary

The engineering base is strong for its age: strict mypy over 669 files is clean, ruff and format are clean, product
code has 90.8 % line and 81.3 % branch coverage, the build gate and the goldens pass, the safety rules have named
tests, and the CI gate of D-206 is green on master. What is missing is the industrial frame around it: nothing
enforces the gates (master is not protected), the traceability matrix has no executed evidence, there is no safety
classification, no problem-resolution log, no coverage or mutation threshold, and no property tests. The mutation
experiment killed 21 of 28 safety-core mutants with the 231 safety-core unit tests; 7 survived, one of them on the
"unknown never excludes" rule of the v1 path (NAV, MICROBATCH, CASE). The equivalence gate between the CQL and SQL
engines can pass with zero patients compared.

Counts: Blocker 0, Critical 0, High 9, Medium 20, Low 7 (36 findings; 6 of them are registered CR rows or older
review items, cited and not counted as new).

Top 5:
1. **ENG-018** (High) a null structured inclusion that drops the patient in the v1 candidate filter survives every
   safety-core unit test (mutant U02); see §3.3 for the full-suite result.
2. **ENG-016** (High) the CQL/SQL equivalence gate passes vacuously (0 patients compared gives 100 %), allows 2 %
   direction-changing disagreement, and has 22 % unit coverage; HAPI runs in no CI workflow.
3. **ENG-005** (High) master is not protected: `protected: false`, no required checks (REST API). Every gate is
   advisory today.
4. **ENG-002** (High) traceability is plan-to-plan only: 273/273 rows `planned`, no test file names a TST or URS id,
   and the 370 SRS requirement ids of TB-DS-01 are not linked to the 92 URS.
5. **ENG-001** (High) no software safety classification for the screening core, although the product depends on
   safety invariants; "62304-light" is scoped to the profile module only.

## 2. Findings

Columns: ID, Severity, Finding, Evidence, Fix proposal, Status, PoC path.

### 2.1 Lifecycle and quality system (IEC 62304-style)

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| ENG-001 | High | No software safety classification. The plan applies "62304-light" records to the profile module only; the screening core (cascade, SQL engine, proposed-fact and coverage rules, the two-model rule, the PHI guard) carries the product's safety invariants but has no class, no segregation argument and no class-driven rigour (unit acceptance criteria, detailed design). | By reading: `docs/plan/25-master-plan.md:177` (62304 records for WS-05 only), `:283` (WS-12.1); `docs/plan/intended-use.md:49` (C12); no classification record in `docs/` (grep `62304`, `safety class`). | Write `docs/validation/software-safety-classification.md`: the safety core as an internal Class B item (a wrong "criteria not matched" can withhold a trial option; harm mitigated by the PI), the rest Class A, with the segregation argument (the six safety-core files, `authz`, prefill path) and the extra activities for Class B units: detailed design note per unit, unit acceptance criteria, mutation score. Acceptance: the record is signed by the owner and the safety-core engineer; CODEOWNERS lists exactly the Class B paths. | new | no |
| ENG-002 | High | The traceability matrix has no executed evidence and links the plan to itself. All 273 rows are `planned`; TST ids are plan rows, not tests: no test file names a TST or URS id. The design set's SRS (TB-DS-01) has 370 FR/NFR ids; 22 of them appear in tests; the plan's 92 URS do not cite them. FS-01 to FS-14 are labels with no document behind them. | By a run: `tools/gen_traceability.py --check` "273 links; clean"; CSV status column = {`planned`}; `grep -rE "TST-[A-Z]+-[0-9]+" tests` finds only data-scan fixtures and `test_gen_traceability.py`; 370 distinct FR/NFR ids in `docs/plan/design/01-SRS.md`, 22 in `tests/`. | (1) a pytest marker `@pytest.mark.verifies("TST-UNIT-02", "URS-PI-03")` on the tests that implement each TST; (2) `gen_traceability.py --evidence unit-junit.xml` fills `status` (pass/fail/not run) and `evidence` (node ids, commit) from the junit file of the CI run; (3) one mapping table SRS FR/NFR → URS, or retire TB-DS-01 ids explicitly; (4) FS: one short functional spec per workstream, or drop the FS column. Acceptance: every URS with a U/I/E level test has ≥ 1 executed passing node id on the release commit; CI fails on a URS without one from design freeze. | card WS-12.2 / T-002 covers the matrix; executed evidence is new | no |
| ENG-003 | High | No problem-resolution process. The plan names "the issue tracker as the problem-resolution log", but GitHub Issues are disabled on the repository. Problems live in review markdown files and the CR register, with no states, owners or closure evidence per item. | By a run: `gh api repos/zandis/Auto-GPT` → `has_issues: false`; `docs/plan/25-master-plan.md:283` (WS-12.1). | Either enable Issues with labels (`safety`, `CR-nnn`, `class-B`, `regression`) and a closing rule (a fixing PR plus a test node id), or keep `docs/validation/problems.csv` (id, found-by, severity, state, fix PR, verifying test) generated into the release record. Acceptance: every CR row and every ENG/UX/... finding of this review has one entry with a state. | new | no |
| ENG-004 | Medium | Change control has no form. The PR template is Auto-GPT's ("tested with multiple different prompts"); it asks for no change class (CC1 to CC6), no safety-core flag, no risk or requirement id, no test evidence. Root `CONTRIBUTING.md` is Auto-GPT's. | By reading: `../.github/PULL_REQUEST_TEMPLATE.md`; `../CONTRIBUTING.md`; `docs/plan/design/12-configuration-management.md:88-102` (the record it promises). | A `trialbox` PR template: change class, touched Class B paths (auto-labelled by a path filter job), URS/RSK/TST ids, test evidence, decision id, reviewer of the safety core. Acceptance: a CI job fails a PR that touches a Class B path without the `safety-core-reviewed` approval from CODEOWNERS. | registered CR-080 (CODEOWNERS/CONTRIBUTING); template new | no |
| ENG-005 | High | Master is not protected. The CI comment and RUNBOOK say branch protection requires the gate's jobs; the API shows none. Any push or merge lands without review or green checks. | By a run: `gh api repos/zandis/Auto-GPT/branches/master` → `"protected": false, "required_status_checks": {"contexts": [], "enforcement_level": "off"}`; `../.github/workflows/trialbox-ci.yml:2-3`. | Owner action of status §5 item 2, plus: require 1 review from CODEOWNERS on Class B paths, dismiss stale approvals, require linear history or merge queue, block force-push. Acceptance: the API shows the required contexts `lint, types, docs, contracts, trace, unit, e2e-simple, goldens, data-scan, shell, images, lock` and `required_pull_request_reviews`. | registered CR-080 (review half); protection is the owner action of T-007 | no |
| ENG-006 | Medium | The supply-chain workflow has a `paths:` filter, so it cannot be a required check (the CI file itself explains why such a check blocks for ever), and it runs only on PRs and weekly, not on push to master. pip-audit and the licence gate are therefore advisory. | By reading: `../.github/workflows/trialbox-supply-chain.yml:9-16`; `trialbox-ci.yml:9-10`. | Move `lock`, `pip-audit`, `licences` behind the CI `changes` job pattern, or drop the `paths:` filter. Acceptance: the three jobs report on every PR and are in the required list. | new | no |
| ENG-007 | High | Image vulnerability gates run in report mode; a bundle can ship images that passed no gate. | By reading: `../.github/workflows/trialbox-images.yml:90` (`--vuln-mode report`). | As registered; PR #78 is WIP (pins transitive jars only, "untested"). | registered CR-045, CR-046; in PR #78 | no |
| ENG-008 | Medium | SOUP list is an SBOM, not a SOUP evaluation. `make licences` produces CycloneDX and a licence table; 62304 §7/§8 also needs per item: purpose, version, functional and performance requirements, known anomalies that matter, and the decision to accept. The JVM side (HAPI, cql-to-elm, HL7 validator) and the model servers are the riskiest SOUP and have no record. | By reading: `Makefile` `lock-sbom`, `licences`; `tools/supply_chain/licences.py`; no SOUP record in `docs/`. | `docs/validation/soup.csv` generated from the SBOM plus a hand-kept columns file (purpose, safety relevance, anomaly review date, accepted by). Acceptance: every runtime component of the safety core's path has a row reviewed in the last 90 days. | new | no |
| ENG-009 | Low | Documents that report gate results are stale: VALIDATION says the suite is "1,405 passed, 2 skipped"; TST-UNIT-01 says "the existing 1,460 cases"; this run has 2,269 tests. | By reading: `docs/VALIDATION.md:15`; `docs/plan/25-master-plan.md:757`. By a run: §3.1. | Generate the "Last result" cells from the CI artifacts of the release commit (the release record of WS-12.5). | new | no |

### 2.2 CI, static analysis, supply chain, builds

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| ENG-010 | Medium | No secret scanning. The data-handling scan has 10 patient-data patterns and none for keys, tokens or private keys; gitleaks is planned for G2 (TST-SEC-04). The repository is public. | By reading: `tools/data_scan_patterns.yaml:26-84`; by a run: `gh api repos/zandis/Auto-GPT` → `visibility: public`. | gitleaks (pinned by sha256 like Syft/Trivy) as a CI job and in `trialbox/.pre-commit-config.yaml`, full-history scan once. Acceptance: a planted fake key in a fixture fails the job. | new (planned TST-SEC-04) | no |
| ENG-011 | Medium | SAST is thin. Ruff's `S` rules run with S603, S607, S608 (SQL built from strings), S105/S106 (hard-coded passwords), S324, S104 ignored for the whole tree and every `S` rule off under `tools/**` (which holds `pglocal`, `supply_chain`, the bundle signer and the cloud driver). No bandit, no semgrep, no CodeQL. | By reading: `pyproject.toml:102-122`. | Turn S608 back on with per-line `noqa` and a reason; run semgrep (python, secrets, dockerfile packs) as a CI job in report mode, gating from G2; remove the `tools/**` blanket. Acceptance: 0 unreviewed high findings on master. | new (planned WS-13.8) | no |
| ENG-012 | Medium | Complexity is not gated and is concentrated in the console: `create_app` is one function of 1,518 lines and 392 branch points; `home.register` 973 lines; 85 functions over 100 lines and 27 over 200. Permission checks live inside these closures (see CR-024). Ruff's PLR0911/12/13/15 are ignored and C901 is not selected. | By a run (AST count, script in scratch): `services/console/app.py:384`, `services/console/home.py:123`, `services/console/team.py:132`, `services/console/site_pages.py:90`; `pyproject.toml:104`. | Split routers per page group (`APIRouter` per module) as part of T-102's single permission function; set C901 at 25 for new code with a baseline file. Acceptance: no function over 200 lines in `services/`. | open since review E-07; new for the gate | no |
| ENG-013 | Medium | The JVM build inputs are not verified. `validator_cli.jar` is downloaded from GitHub and its sha256 is written after download (trust on first use); Maven resolves `cql-to-elm-cli` and its transitive jars with no checksum policy or lock; FHIR packages and fonts are fetched without a pinned hash. All of them are copied into `trialbox-jvm`/`trialbox-py`. | By reading: `tools/fetch_jvm_deps.sh:12-21`; `services/criteria_compiler/compile_cql/translator/pom.xml`; `tools/fetch_fonts.py:58`; `deploy/docker/jvm.Dockerfile` COPY lines. | A `tools/jvm-deps.sha256` list checked after every fetch (fail on mismatch), Maven with `-C` (strict checksums) and a dependency-verification list; the same for FHIR packages and fonts. Acceptance: tampering one byte of a cached jar fails `make jvm-deps`. | new | no |
| ENG-014 | Medium | Java version drift: CI runs the CQL translator on Temurin 21; the image ships JRE 17. The equivalence and compile tests pass on a JVM the box does not run. | By reading: `../.github/workflows/trialbox-ci.yml` (`java-version: "21"`, unit and e2e-simple jobs); `deploy/docker/jvm.Dockerfile:6` (`eclipse-temurin:17-jre@sha256:...`). | One Java version (17 or 21) named once (a `.java-version` file read by CI and the Dockerfile). Acceptance: CI fails if the two differ. | new | no |
| ENG-015 | Medium | Builds are not reproducible. `python.Dockerfile` runs `apt-get upgrade -y`, so the image depends on the build date; no `SOURCE_DATE_EPOCH`, no OCI labels with the git commit; every image is `1.0.0`. | By reading: `deploy/docker/python.Dockerfile` (RUN apt-get upgrade); `Makefile` `images`. | Pin the base by digest (done) and drop `apt-get upgrade` in favour of bumping the digest; add `org.opencontainers.image.revision`; record the image digest in `release.json`. Acceptance: two builds of one commit give the same digest, or the difference is listed. | registered CR-081 (release identity); reproducibility new | no |
| ENG-016 | High | The CQL/SQL equivalence gate can pass vacuously and is barely unit-tested. `compare()` gives 100 % to a criterion with 0 patients compared, silently skips CQL patients the SQL side lacks, and has no minimum sample size; 98 % agreement allows a decided-vs-null or true-vs-false difference on 4 of 200 patients. `gate.py` has 22.1 % unit coverage (lines 26-69 and 80-113 never run); the only real run is `tests/integration/test_compile_compose.py`, which needs HAPI and runs in no workflow. Approval blocks only on `failing`. | By reading: `services/criteria_compiler/equivalence/gate.py:59-79`; `services/criteria_compiler/service.py:262-292`. By a run: coverage §3.2. | (1) `failing` includes any criterion with `total == 0` and the report fails when `sample_size < min(200, n_patients)`; (2) a disagreement that changes the eligibility direction (TRUE/FALSE vs the other, or decided vs null on an exclusion) blocks at any rate; (3) unit tests with a fake `FhirEvaluator` and a DuckDB lake for each case; (4) a nightly job that runs `tests/integration/test_compile_compose.py` on the compose stack. Acceptance: a test with an empty CQL result fails approval. | new | no |
| ENG-017 | Medium | The compose-stack tests run nowhere. `tests/integration` tests marked `integration` (HAPI CQL, the equivalence gate against HAPI, compose data) and `tests/e2e` (mail, console POC, role walk) are in no workflow; the nightly runs `public_e2e` and the two drills only. The JS walk (`tools/public_walk.js`) runs only inside `complete_run`. | By reading: `../.github/workflows/*.yml` (grep `integration`, `test-e2e`, `public_walk`); `Makefile` `test-integration`, `test-e2e`. | A nightly `compose` job (`make up-test`, `make test-integration`, `make test-e2e`, the walk) on a runner with Docker. Acceptance: one green scheduled run per night, results kept as artifacts. | planned TST-INT-01, TST-WALK-01; new as a gap | no |
| ENG-018 | High | Mutation: the v1 candidate filter's "unknown never excludes" has no killing test. Changing `v is False` to `v is not True` in `structured_candidate` (a null structured inclusion then drops the patient, who gets tier `excluded` with no verdict explaining it) passes all 231 safety-core unit tests. NAV, MICROBATCH and CASE use this path; `tools/goldens.py` uses the same function, so the goldens move only if a golden patient has a null inclusion. | By a run: mutant U02, §3.3; `services/orchestrator/scenarios/evaluate.py:469-488,592,635-636`. | A unit test: one structured inclusion null for a patient → the patient is a candidate and tier `review`, with the criterion `unknown`; the same through `evaluate_patients`. Acceptance: U02 is killed by a unit test. | new | yes |
| ENG-019 | Medium | Mutation: six more survivors on the two rules. Proposed facts: an undated fact ignored (P05), a fact dated on the index date ignored (P06), a proposed birth date or sex ignored for derived values such as eGFR (P07), mixed bases reported as `suspected_diagnosis` (P12). Unreadable codes: an undated row in an unknown code system ignored (U09), a diagnosis with an empty code not treated as unreadable (U10). | By a run: §3.3. Code: `services/matching/proposed.py:156-176,193-197`; `services/matching/coverage.py:37-40,158`. | One test per survivor (fixtures exist in `tests/unit/test_one_rule.py` and `test_code_coverage.py`); then a mutation job (mutmut or cosmic-ray on the Class B files, nightly, score ≥ 90 %). Acceptance: the 28 mutants of §3.3 are all killed by unit tests. | new | yes |
| ENG-020 | High | Cascade exclusion paths are not run by any unit test: the certified zero-hit exclusion at S2, the index-absent exclusion at S2b, the judge-reply mapping to unknown, the S3 "no judge"/"not sampled" branches and the S4 verifier branches. | By a run: coverage of `services/matching/cascade/engine.py` 85.7 %; missing lines include 628-636, 687-696, 805-816, 837-848, 872-873, 929, 937. | As registered (FG-G, D-276): stub personas that disagree, abstain and fail; one test per exclusion path. Acceptance: those lines covered and their mutants killed. | registered CR-003 | yes |
| ENG-021 | Medium | No property-based tests anywhere (`hypothesis` is not in `uv.lock`). The safety rules are exactly the kind of invariant properties catch (monotonicity, "unknown never excludes" over random IR trees and lakes). Proposed properties in §3.4. | By a run: `grep -c 'name = "hypothesis"' uv.lock` → 0. | Add `hypothesis` to the `test` group; the eight properties of §3.4 as `tests/unit/test_safety_properties.py`, `max_examples` 200 in PR CI and 5,000 nightly. Acceptance: properties P1 to P8 pass; each of the 28 mutants is killed by at least one property. | open since review E-05 | no |
| ENG-022 | Medium | Duplicated safety logic. The structured verdict rules (D-18 unknown exclusion kept, CAS-11, D-113, D-130, D-135) are coded twice: the v1 path (`evaluate.py` `structured_verdict`, `structured_candidate`, `tier`) and the v4 cascade (`engine.py` `_pass`, `_s1_coded`, `_s1_outcome`). The mutation run shows the copies are not tested equally (U02 survives, its cascade twins U04 to U06 are killed). The third "engine", the Python derived-value code, has impossible-value guards the SQL and CQL engines lack (CR-115). | By reading: `services/orchestrator/scenarios/evaluate.py:375-488`; `services/matching/cascade/engine.py:401-547`; `libs/tb_common/derived.py:187-229`. | One pure decision table `matching/verdict.py` (kind, class, predicate, reasons → outcome, hard?) used by both paths; a parity test that runs both paths on the same lake and compares per-criterion outcomes; CR-115 fix in the generators with the same table. Acceptance: one module holds the rules; the parity test is a required check. | registered CR-115 (engines); duplication new | no |
| ENG-023 | Medium | The PHI guard fails open on a configuration error: `Guard.from_settings()` catches every exception and runs without the site MRN pattern; the gateway tripwire and the trace-store redaction then miss bare chart numbers. | By reading: `services/guard/guard.py:46-53`; used by `services/gateway/core.py:164`, `services/tracestore/store.py:82`. | In `TB_ENV=PRODUCTION`, a settings error stops the service; elsewhere log a warning. Acceptance: a test with an unreadable settings file under PRODUCTION raises. | new | no |
| ENG-024 | Low | CI helper containers are pulled by tag although every action is pinned by commit: `rhysd/actionlint:1.7.7`, `hadolint/hadolint:v2.12.0`, `python:3.12-alpine`. The model server image `vllm/vllm-openai:v0.32.0` is also by tag. | By reading: `../.github/workflows/trialbox-ci.yml` (lint, images jobs), `trialbox-identity.yml:94`; `deploy/docker-compose.yml:257`, `deploy/docker-compose.rtx5090.yml:49`, `deploy/docker-compose.rtxpro6000.yml:31`. | Pin by digest; the vLLM pin as registered. | registered CR-044 (vLLM); CI images new | no |
| ENG-025 | Low | `make ci` and CI disagree on hadolint (`|| true` locally, gating in CI). | By reading: `Makefile` `ci` target; `trialbox-ci.yml` images job. | Same command in both. | new | no |

### 2.3 Tests, isolation, data, performance

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| ENG-026 | Medium | `make test` is red on a fresh checkout: 20 tests fail with `FileNotFoundError: FHIRHelpers-4.0.1.cql not found in the cql-translator jars` when `.cache/jvm` is absent, while 4 other tests skip on the same condition. `make test` depends on the fonts only; CI fetches the jars itself. | By a run: run 2, 21 failed (20 of them this error: `tests/unit/test_compiler_service.py` ×10, `tests/integration/test_cohort_inproc.py` ×4, `test_list_demo` ×2, `test_rerun[COHORT]`, `test_e2e_simple`, `test_mail_feas_inproc`, `test_rc_demo`); re-run with jars fetched to scratch: 20 passed. | Make `test` depend on `jvm-deps` (as on fonts), or one `needs_cql` marker that skips with the same message everywhere and is refused in CI (`TB_REQUIRE_JVM=1`). Acceptance: on a clean clone `make test` is green or skips with one reason. | new | no |
| ENG-027 | Medium | A timing-dependent test, and no flaky-test policy. `test_gpu_prep::test_the_stub_profile_run_measures_and_extrapolates` failed 3 of 3 times on this machine at normal speed (`abs(0.01 - 50000 * 0.0 / 3600) < 0.01`: a rounded 0.0 s per patient against a rounded 0.01 GPU hour) and passed under coverage, which slows it. D-201 calls it flaky "under load"; it fails when the machine is fast. There is no quarantine marker, no re-run rule and no flake register. | By a run: run 2 (in the 3-worker run), the re-run (3 workers), alone (`-n 0`): FAILED; under coverage: passed. `tests/unit/test_gpu_prep.py:162`; `docs/decisions/D-201-test-isolation-and-disk.md:73-75`. | Compare unrounded values (or compute the expected value from the rounded inputs). Policy: a failing test is re-run once in CI; a test that passes on re-run is marked `@pytest.mark.flaky(issue=...)` within one working day and fixed within ten; the register is in the release record. Acceptance: 20 consecutive runs green. | new | no |
| ENG-028 | Medium | Every test needs PostgreSQL. `_private_trial_db` is autouse, so a pure-function test starts a cluster; when the cluster cannot start, all 2,260 tests error instead of one clear stop. TST-UNIT-01 promises an opt-in fixture. | By reading: `tests/conftest.py:72-75`. By a run: run 1, with `TB_SCRATCH` under the agent scratchpad (`/tmp/claude-0`, mode 0700, reset by the host after `pglocal` added o+x): "9 skipped, 2260 errors in 34.15s", each `initdb: could not access directory ... Permission denied`. | Opt-in `db_url` (a `pytest.mark.db` marker or explicit fixture use); a session-start probe that calls `pytest.exit()` with one message when the cluster cannot start. Acceptance: `tests/unit/test_one_engine.py` runs with no PostgreSQL binary on PATH. | open since review E-02 | no |
| ENG-029 | Medium | No coverage measurement or threshold in CI; the plan's G3 module targets (`matching` ≥ 70 %, `console` ≥ 80 %, ...) are not checked anywhere. Measured here: product code 90.8 % line, 81.3 % branch (§3.2), so a ratchet costs little now. | By reading: no `[tool.coverage]` in `pyproject.toml`; no `--cov` in `Makefile` or workflows. By a run: §3.2. | `--cov --cov-branch` in the CI unit job, `coverage.json` as an artifact, a ratchet per package (fail if a package drops > 0.5 points), and 95 % line / 90 % branch on the Class B files. Acceptance: the CI job prints the table and fails on a drop. | new | no |
| ENG-030 | Medium | No performance tests. The `perf` marker is defined and used by no test; the 50k scale, night window and 20-user console goals (TST-PERF-01) are checked only by hand runs of `tools/bench.py`, `complete_run scale` and the cloud run. | By reading: `pyproject.toml` markers; `git grep "mark.perf"` → 0. | A nightly perf job on the stub at 5k patients with a stored baseline (S0 to S5 wall time, peak RSS, lake build time) failing on > 20 % regression; the 50k version weekly on the acceptance box. | planned TST-PERF-01; new as a gap | no |
| ENG-031 | Low | The random-order nightly job is not built; `pytest-randomly`, `pytest-socket` and `time-machine` (all named in TST-UNIT-01) are not in the lock. Test isolation therefore is not checked for order dependence, network access or wall-clock dependence. | By reading: `docs/decisions/D-201-test-isolation-and-disk.md:77`; `pyproject.toml` `[dependency-groups] test`. | Add the three to the `test` group; nightly `-p randomly` with the seed in the log; `--disable-socket` with an allow-list for the local cluster. | open since review E-16 | no |
| ENG-032 | Medium | Migrations: no checksum and no global order (registered), and also no detection of a downgrade: `Database.migrate()` returns `len(versions)` even when `_schema_version` holds a higher version, so an older image runs silently on a newer schema. No migration is reversible; rollback relies on restore. | By reading: `libs/tb_common/db.py:221-241`. | In T-104: migrations as files with sha256 recorded in `_schema_version`; refuse to start when the database is ahead of the code or a recorded hash differs; document "rollback = restore" in the update procedure with the drill as evidence. Acceptance: a test starts an old migration list on a newer schema and gets a refusal. | registered CR-059 (checksum, order); downgrade half new | no |
| ENG-033 | Medium | The data-handling scan fails on this branch's head: 1 hit (pattern `chart_number`) in another reviewer's committed review file. The gate works; the branch cannot merge until the line is rewritten. | By a run: `make data-scan` → `docs/reviews/2026-11-10-deep-review/02b-role-journeys-authz.md:59: chart_number: 1*******`, "1 hit(s) (1861 file(s), 10 patterns)", exit 2. | The lead rewrites that example (a non-numeric placeholder) before the PR. | new | no |
| ENG-034 | Low | Legacy Auto-GPT tree at the repository root (README, Dockerfile, `.pre-commit-config.yaml` with black/isort/sourcery, CONTRIBUTING, `autogpt/`); a contributor following the root files installs the wrong hooks. | By reading: `../.pre-commit-config.yaml`, `../CONTRIBUTING.md`. | Move TrialBox to its own repository or delete the legacy tree (licence check first). | open since review E-08 | no |
| ENG-035 | Low | JavaScript has no lint and no unit test (`services/console/static/console.js`, `site/assets/app.js`, the Playwright scripts). The console's script is small and optional (CSP hash, D-133), so the risk is low. | By reading: file list (`git ls-files '*.js'`, 1,283 lines incl. vendored). | `eslint` (pinned) over the non-vendored JS in the lint job. | new | no |
| ENG-036 | Low | Exceptions in the safety core are classified by message text (`"site_fact" in msg and ("exist" in msg or "Catalog" in msg)`). It fails closed (any other text raises), but a DuckDB upgrade that changes the text would stop every run that predates step 5b. | By reading: `services/matching/proposed.py:112-118,205-209`. | Check for the table in the catalog (`information_schema.tables`) before querying. | new | no |

## 3. Measurements

### 3.1 The unit suite (`make test`)

| Run | Setting | Result | Wall time |
| --- | --- | --- | --- |
| 1 | `TB_SCRATCH` = agent scratchpad under `/tmp/claude-0` (0700) | 2,260 errors, 9 skipped: PostgreSQL could not reach its data directory (host resets the parent's o+x) | 34 s (71 s with make) |
| 2 | `TB_SCRATCH=/var/tmp/tb-04-eng`, `PYTEST_N=3`, no `.cache/jvm` | **2,236 passed, 21 failed, 12 skipped** | 988 s (16 min 27 s), load average 8 to 12 from other agents |
| re-run | the 21 failures, with CQL jars fetched to scratch (`TB_CQL_TRANSLATOR_LIB`), 3 workers | 20 passed, 1 failed (`test_gpu_prep`) | 372 s |
| alone | `test_gpu_prep::...extrapolates`, `-n 0` | failed | 2.4 s |
| coverage | 2 workers, `--cov services libs tools --cov-branch`, jars present | **2,261 passed, 8 skipped, 0 failed** | 2,385 s (39 min 45 s) |

Failures of run 2: 20 are the missing CQL jars (ENG-026), 1 is the timing-dependent test (ENG-027). No other test
failed or changed state between runs, so no further flaky test was observed in three full or partial runs.

Skips (12 in run 2, 8 with the jars), and why each skips:

| Test | Count | Reason |
| --- | --- | --- |
| `test_code_coverage.py:67`, `test_derived_definitions.py:365`, `test_derived_scores.py:275` | 3 | CQL translator jars not in `.cache/jvm` (pass when present) |
| `test_ingest_inproc.py:174` | 1 | HL7 validator jar and package cache not configured (passes when present) |
| `test_open_data_e2e.py:31,45,62,77,82` | 5 | MIMIC-IV FHIR demo not fetched (`tools/fetch_open_data.py`, network, PhysioNet) |
| `test_dataplat_thin_path.py:220`, `test_eval_public_suites.py:57` | 2 | MIMIC demo not fetched |
| `tests/integration/test_egress.py` | 1 | needs root, nftables and the compose stack (`make test-egress`) |

Slowest tests (run 2): `test_recall_ledger::test_twelve_looks...` 172 s, `test_omop_core::test_every_committed_ruleset_screens_the_same_on_both_lakes`
123 s, `test_list_demo::test_approve_list_mark_and_mail` 114 s, `test_e2e_simple` 88 s,
`test_feas_demo::test_paste_gout_coh_criteria...` 83 s, `test_recall_cert::test_sequence_covers...` 66 s. Two
Monte-Carlo tests take 4 minutes of one worker (review E-04 still open): a `slow` marker and a nightly-only run
would cut the PR gate by a quarter.

### 3.2 Coverage of the unit suite (line %, branch %)

Product code (`services` and `libs`): 42,095 statements, **90.8 % line, 81.3 % branch**. With `tools`: 64,465
statements, 78.1 % line (tools 59.3 %).

| Area | Statements | Line % | Branch % |
| --- | --- | --- | --- |
| services/console | 9,173 | 86.5 | 74.1 |
| services/orchestrator | 8,240 | 92.0 | 81.3 |
| libs/tb_common | 3,492 | 92.3 | 83.5 |
| services/adapter | 2,513 | 90.2 | 83.4 |
| services/criteria_compiler | 2,253 | 90.9 | 84.6 |
| libs/tb_contracts | 2,186 | 97.5 | 79.5 |
| services/matching | 2,044 | 92.0 | 82.4 |
| services/sitesetup | 1,590 | 91.2 | 82.2 |
| services/datacore | 1,528 | 93.0 | 84.6 |
| services/dataplat | 1,527 | 91.7 | 79.5 |
| services/omop | 1,041 | 90.9 | 85.2 |
| services/edc | 1,037 | 92.3 | 83.6 |
| services/deliverables | 956 | 97.9 | 93.1 |
| services/lake | 784 | 90.7 | 85.4 |
| services/gateway | 708 | 93.1 | 87.0 |
| services/mail_gateway | 578 | 84.4 | 74.6 |
| services/guard | 178 | 97.2 | 93.2 |
| services/embed_service | 75 | 65.3 | 42.9 |
| tools | 22,370 | 59.3 | 54.0 |

Safety core, per file (line %): `matching/cascade/engine.py` 85.7 (exclusion paths uncovered, ENG-020);
`matching/proposed.py` 91.9; `matching/coverage.py` 94.4; `matching/cascade/judge.py` 100; `tb_common/pair.py` 100;
`tb_common/quotes.py` 100; `orchestrator/scenarios/evaluate.py` 90.0; `criteria_compiler/compile_sql/generator.py`
94.3; `compile_cql/generator.py` 93.5; `compile_cql/translator.py` 84.2; `criteria_compiler/semantics.py` 97.5;
**`criteria_compiler/equivalence/gate.py` 22.1** (ENG-016); `tb_common/derived.py` 91.6; `guard/guard.py` 97.4;
`guard/recognisers.py` 95.1; `tb_common/phi_guard.py` 99.0; `gateway/core.py` 92.4; `gateway/policy.py` 92.2.

Lowest product files (≥ 30 statements): `omop/__main__.py` 0 %, `equivalence/gate.py` 22 %, `tb_common/fhir.py`
32 %, `orchestrator/precheck/__init__.py` 38 %, `console/backend.py` 41 %, `adapter/cli.py` 43 %,
`orchestrator/clients.py` 44 %, `console/cli.py` 45 %, `lake/app.py` 46 %. Most are HTTP clients and CLIs exercised
only against the compose stack (ENG-017).

### 3.3 Mutation experiment on the safety core

Method: 28 single-point mutants, written by hand against the two invariants, applied one at a time to a copy of the
tracked files under scratch (the repository was never edited), each run against the 231 safety-core unit tests
(23 files of `tests/unit` plus `tests/console/test_excluded_page.py`; baseline 231 passed, 1 skipped, 102 s), stop
on first failure. The survivors were then applied together and run against the whole unit suite and
`tools.goldens --check`. Result: **21 killed, 7 survived the safety-core tests (75 % mutation score)**.

| Id | Rule | Mutation | Result | Killed by |
| --- | --- | --- | --- | --- |
| P01 | proposed | suspected diagnoses not loaded from `site_fact` | killed | `test_suspected_diagnosis::test_sql_engine_never_excludes_on_a_suspected_diagnosis` |
| P02 | proposed | `not` no longer flips a fact's direction | killed | `test_one_rule::test_signed_atoms_and_words` |
| P03 | proposed | quantifier `none` treated as `any` | killed | `test_one_rule::test_sql_engine_proposed_facts_only_send_to_needs_information` |
| P04 | proposed | a truer-making fact matters only when already TRUE | killed | same |
| P05 | proposed | an undated proposed fact is ignored | **survived** | (ENG-019) |
| P06 | proposed | a fact dated on the index date is ignored (window bound) | **survived** | (ENG-019) |
| P07 | proposed | a proposed age or sex is ignored for derived values (eGFR) | **survived** | (ENG-019) |
| P08 | proposed | any lake error silently drops the proposed-fact rule | killed | `test_one_rule::test_a_lake_built_before_step_5b_has_no_proposed_facts` |
| P09 | proposed | cascade: a proposed fact on an exclusion excludes | killed | `test_one_rule::test_cascade_s1_never_excludes_on_a_proposed_fact` |
| P10 | proposed | cascade: proposed-fact check skipped | killed | same |
| P11 | proposed | SQL engine (NAV, CASE): proposed-fact check skipped | killed | `test_one_rule::test_sql_engine_proposed_facts_only_send_to_needs_information` |
| P12 | proposed | mixed proposed/suspected reported as `suspected_diagnosis` | **survived** | (ENG-019; reason code only) |
| U01 | unknown | `eligibility(None)` returns `fail` | killed | `test_code_coverage::test_sql_engine_keeps_unreadable_codes_unknown` |
| U02 | unknown | v1 candidate filter: a null structured inclusion drops the patient | **survived** | (ENG-018) |
| U03 | unknown | tier: any unknown makes the patient excluded | killed | `test_judge_tier::test_tiers` |
| U04 | unknown | cascade S1 depth: a null exclusion counts as failing | killed | `test_cascade_pipeline::test_end_to_end_passes` |
| U05 | unknown | cascade: a null exclusion excludes | killed | same |
| U06 | unknown | cascade: an inclusion with no value in the window excludes | killed | `test_lab_value_unknown::test_cascade_keeps_the_text_result_patient` |
| U07 | unknown | cascade: unknown-code-system rescue removed | killed | `test_code_coverage::test_cascade_s1_does_not_exclude_them` |
| U08 | unknown | coverage: no positive atoms (rescue never applies) | killed | `test_code_coverage::test_known_systems_and_positive_atoms` |
| U09 | unknown | coverage: an undated unreadable row ignored | **survived** | (ENG-019) |
| U10 | unknown | coverage: a diagnosis with an empty code is not "unreadable" | **survived** | (ENG-019) |
| U11 | unknown | pair: the judge wins on disagreement | killed | `test_agreement_judge::test_agreement_judge_blocks_only_on_agreement` |
| U12 | unknown | pair: verifier down, the judge decides alone | killed | same |
| U13 | unknown | pair: the low-confidence floor removed | killed | `test_one_engine::test_combine_table[...low_confidence...]` |
| U14 | unknown | a single model allowed to exclude | killed | `test_judge_tier::test_both_agree_without_a_verifier_falls_back_to_never` |
| U15 | unknown | a patient missing from the snapshot shown as excluded | killed | `test_one_engine::test_a_patient_missing_from_the_snapshot_is_a_review_not_an_exclusion` |
| U16 | unknown | cascade: a derived value with no value (unit, missing input) excludes | killed | `test_derived_scores::test_engines_say_why_and_never_exclude` |

The seven survivors against the whole unit suite and the goldens: SURVIVOR_RESULT

Reading: the cascade (SCREEN) and the two-model rule are well guarded; the weak spots are boundary and "absent
field" cases (undated, on the index date, empty code) and the v1 candidate filter. These are what property tests
find (§3.4). The run confirms CR-003's mechanism from the other side: what is tested is tested well; what is not
named in a test is not guarded at all.

### 3.4 Property-based tests: none today; the properties to add

`hypothesis` is not a dependency. Proposed properties for `tests/unit/test_safety_properties.py`, with generators for
random Criterion IR trees (atoms of every `Kind`, `and`/`or`/`not`, windows), random small lakes (rows dated, undated,
on the window bounds, empty codes, unknown systems) and random proposed/suspected facts:

| # | Property | Kills |
| --- | --- | --- |
| P1 | **Unknown never excludes (v1).** For any ruleset and evaluation, if no structured inclusion is FALSE, no structured exclusion is TRUE and no note answer is a confident agreed `fail`, the tier is never `excluded`. | U01, U02, U03, U15 |
| P2 | **Unknown never excludes (cascade).** Replacing any decided S1 value by NULL never turns a kept patient into an excluded one. | U04 to U07, U16 |
| P3 | **Proposed facts never count.** Adding any set of proposed or suspected facts to a lake never changes a patient from candidate to excluded and never changes an `unknown`/`fail` criterion to `pass`; it may only move a decided criterion to `unknown`. | P01 to P04, P09 to P11 |
| P4 | **Proposed-fact sensitivity is complete.** If confirming a proposed fact would change a criterion's SQL value, the unconfirmed fact already makes that criterion `unknown` (oracle: re-run the SQL with the fact inserted into the coded table). Includes undated facts, facts on window bounds, demographic facts under derived atoms. | P05, P06, P07 |
| P5 | **Unreadable codes are never a silent FALSE.** For an inclusion with a positive condition/medication atom, a row in an unknown system (or with an empty code) in the window, dated or undated, makes a FALSE answer `unknown`. | U08, U09, U10 |
| P6 | **Monotonicity of the pair.** `combine(first, second)` never returns a decided verdict that `first` did not give; its confidence is never above either input; a verifier failure or disagreement is never decided. | U11 to U13 |
| P7 | **Engine parity.** For random IR and lakes, the SQL engine and the cascade's S1 give the same outcome class per criterion (pass, fail, unknown), and the SQL and CQL generators agree (nightly, needs the translator). | duplication of ENG-022, CR-115 |
| P8 | **Guard idempotence and coverage.** `redact(redact(x)) == redact(x)`; every planted identifier of the data-scan fixtures inserted at a random position in random CJK/Latin text is detected by `tripwire`. | guard regressions |

## 4. Lifecycle mapping (IEC 62304-style) and test levels today

| 62304 activity | What exists | Gap |
| --- | --- | --- |
| 4.3 Safety classification | none (ENG-001) | classify the safety core |
| 5.1 Development plan | TB-PLAN-05 master plan, TB-VMP-01 (draft, unsigned), design set 12 (configuration management) | no single software development plan naming standards, tools, levels, and the Class B activities; the VMP is unsigned |
| 5.2 Requirements | 92 URS in the plan; 370 FR/NFR in TB-DS-01 (SRS) | two baselines, not linked (ENG-002); FS documents absent |
| 5.3 Architecture | `docs/ARCHITECTURE.md`, design set 02 | SOUP functional/performance requirements absent (ENG-008); segregation of Class B items not argued |
| 5.4 Detailed design | module docstrings (good: `proposed.py`, `coverage.py`, `pair.py` state their rules) | no unit acceptance criteria per Class B unit |
| 5.5 Unit verification | 2,269 pytest cases, 90.8 % line | no threshold, no mutation score, no property tests, autouse database (ENG-021, 028, 029) |
| 5.6 Integration testing | in-process integration tests run inside `make test`; compose tests | compose tests in no CI (ENG-017) |
| 5.7 System testing | `e2e_simple` (PR gate), goldens (PR gate), nightly drills, `complete_run` by hand | no perf tests (ENG-030); results not tied to the matrix |
| Acceptance | IQ/OQ/PQ protocols planned (TST-IQ/OQ/PQ) | not started (as planned) |
| 5.8 Release | supply-chain gates in report mode, `1.0.0` everywhere | CR-045, CR-046, CR-081 |
| 6 Maintenance, 8 Configuration management | design set 12; decisions files; PR records | change class not recorded on PRs (ENG-004) |
| 7 Risk management of software | RSK ids in the plan §6 | risk controls not linked to executed tests (ENG-002) |
| 9 Problem resolution | review markdown, CR register | no tracker with states (ENG-003) |

## 5. What is good (keep it)

* `mypy --strict` over libs, services, tools and tests is clean (669 files) and only 4 `type: ignore` sit in the
  safety core; ruff and ruff-format are clean on 873 files; doclint is clean.
* The safety rules are written down where they are coded (module docstrings of `proposed.py`, `coverage.py`,
  `pair.py`, `semantics.py`), and the two-model rule lives in one place (`tb_common/pair.py`, 100 % covered, every
  mutant killed).
* Named safety tests exist for each runtime path (`test_one_rule.py` checks the SQL engine, the cascade and FEAS on
  one lake); 21 of 28 mutants die in under two minutes.
* The PR gate (D-206) runs lint, types, docs, contracts, trace, unit, e2e-simple, goldens, data-scan, shell and
  hadolint, with every action pinned by commit and `permissions: contents: read`; it was green on master `ca8f287`.
* `make e2e-simple` (128.6 s) and the goldens (17 goldens, identical from both lake sources) are deterministic, fast
  gates; the hashed lock and its export check pass offline in under a second.
* D-201 isolation works as designed: per-branch roots, a marker check that refused an unmarked root, flock, per-worker
  clusters; no file was left under `/tmp` by the runs here.
* The data-handling scan caught a real problem in this very branch (ENG-033).

## 6. Proposed task cards for TB-PLAN-06

| Id | Goal | Files it touches | Acceptance tests | Depends on | Size | PoC prerequisite |
| --- | --- | --- | --- | --- | --- | --- |
| T-007 (add) | Gates enforced | repository settings; `trialbox-supply-chain.yml` | branch protection API shows the required contexts and CODEOWNERS reviews; supply-chain jobs report on every PR (ENG-005, ENG-006) | owner | S | no |
| T-002 (add) | Change control and problem resolution | `.github/PULL_REQUEST_TEMPLATE.md` (TrialBox section), `CODEOWNERS`, Issues or `docs/validation/problems.csv` | a Class B path change without the code owner's approval cannot merge; every CR row has a tracked entry (ENG-003, ENG-004) | T-007 | S | no |
| T-SAFE-TEST (new) | Close the safety-core test gaps | `tests/unit/test_safety_properties.py` (new), `tests/unit/test_one_rule.py`, `tests/unit/test_code_coverage.py`, `tests/unit/test_mixed_and_polarity.py`, `pyproject.toml` (hypothesis) | the 28 mutants of §3.3 all killed by unit tests; properties P1 to P6 pass at 5,000 examples nightly (ENG-018, ENG-019, ENG-021) | — | M | yes (ENG-018 is on the PoC path) |
| T-MUT (new) | Mutation testing as a gate on Class B files | CI nightly job, `tools/mutation.py` or mutmut config | nightly mutation score ≥ 90 % on the Class B files; a drop fails the run | T-SAFE-TEST | S | no |
| T-EQUIV (new) | A non-vacuous equivalence gate | `services/criteria_compiler/equivalence/gate.py`, `service.py`, new unit tests, nightly compose job | an empty CQL result or `sample_size` below the minimum fails approval; a direction-changing disagreement blocks at any rate; gate.py ≥ 95 % covered (ENG-016) | — | M | no |
| T-VERDICT (new) | One decision table for structured verdicts | `services/matching/verdict.py` (new), `evaluate.py`, `cascade/engine.py`, compile_sql/compile_cql generators (with CR-115) | parity test (P7) green; CR-115 tests green (ENG-022) | T-SAFE-TEST | M | no |
| WS-12.2 (add) | Executed traceability | `tools/gen_traceability.py`, a `verifies` marker in `tests/conftest.py`, the CI unit job (junit artifact) | `status` filled from junit; every URS at level U/I/E has a passing node id on the release commit; SRS→URS map committed (ENG-002) | T-007 | M | no |
| WS-12.1 (add) | Safety classification, SOUP list, development plan | `docs/validation/software-safety-classification.md`, `docs/validation/soup.csv`, `docs/validation/sdp.md` | signed by owner and safety-core engineer; SOUP rows reviewed (ENG-001, ENG-008) | — | S | no |
| T-003 (add) | Test hygiene | `Makefile` (`test: jvm-deps`), `tests/conftest.py` (opt-in DB, fail fast), `tests/unit/test_gpu_prep.py`, `pyproject.toml` (randomly, socket, time-machine, coverage) | clean-clone `make test` green; a pure test runs without PostgreSQL; 20 consecutive green runs; nightly random order (ENG-026, 027, 028, 031) | — | M | no |
| T-COV (new) | Coverage ratchet | CI unit job, `pyproject.toml [tool.coverage]` | CI fails on a package drop > 0.5 point; Class B files ≥ 95 % line, 90 % branch (ENG-029, ENG-020) | T-SAFE-TEST, FG-G | S | no |
| T-110 (add) | Build inputs verified, reproducible images | `tools/fetch_jvm_deps.sh`, `tools/jvm-deps.sha256`, `pom.xml`, `tools/fetch_fonts.py`, Dockerfiles, CI Java version | tampered jar fails `make jvm-deps`; CI and image use one Java; image labels carry the commit (ENG-013, 014, 015, 024) | PR #78 | M | no |
| T-SEC-SAST (new) | Secret scanning and SAST | CI jobs (gitleaks, semgrep), `pyproject.toml` ruff ignores, pre-commit | planted fake key fails CI; semgrep report clean of high findings from G2 (ENG-010, ENG-011) | — | S | no |
| T-PERF (new) | Performance regression gate | nightly workflow, `tools/bench.py` baseline file | > 20 % regression of S0 to S5 at 5k fails the nightly (ENG-030) | — | M | no |
| T-COMPOSE-NIGHTLY (new) | The compose tests run somewhere | `trialbox-e2e.yml` (a compose job) | one green scheduled run per night of `test-integration`, `test-e2e`, the walk (ENG-017) | CR-076 (images build) | M | no |
| T-104 (add) | Migration safety | `libs/tb_common/db.py`, migration files | downgrade refused; checksum mismatch refused (ENG-032) | — | (inside T-104) | no |
| T-102 (add) | Split the console's giant closures with the permission function | `services/console/app.py`, `home.py`, `team.py`, `site_pages.py` | no function over 200 lines in `services/`; C901 baseline (ENG-012) | — | (inside T-102) | no |

### 6.1 Test strategy to industrial standard (for TB-PLAN-06)

Levels, tools, thresholds, gates and evidence. "PR" means a required check on every pull request; "nightly" a
scheduled job whose red result opens a problem entry the next working day.

| Level | Scope | Tools | Threshold | Gate | Evidence kept |
| --- | --- | --- | --- | --- | --- |
| Static | all Python, JS, shell, Dockerfiles, workflows | ruff (with S608 on), ruff-format, mypy --strict, semgrep, gitleaks, shellcheck, hadolint, actionlint, eslint, doclint, C901 ≤ 25 on new code | 0 errors; 0 unreviewed high SAST findings | PR | CI log per job |
| Unit (Class A) | `tests/unit`, `tests/console` | pytest, xdist, pytest-cov (branch), pytest-randomly (nightly), pytest-socket, time-machine | package coverage ratchet (no drop > 0.5 point); every test runs without network; no wall-clock dependence | PR | junit XML, `coverage.json` |
| Unit (Class B, the safety core) | `matching/*`, `orchestrator/scenarios/evaluate.py`, `criteria_compiler/{semantics,compile_sql,compile_cql,equivalence}`, `tb_common/{pair,derived,quotes,phi_guard}`, `guard/*`, gateway policy | the above plus hypothesis (P1 to P8) and mutation testing | ≥ 95 % line, ≥ 90 % branch; mutation score ≥ 90 % (nightly), 100 % on the two invariants' mutant set; each rule with a named test | PR (coverage, properties at 200 examples); nightly (mutation, properties at 5,000) | junit, coverage, mutation report, property seeds |
| Integration, in process | `tests/integration` unmarked (DuckDB lake, local PostgreSQL, stub model) | pytest | 0 failures | PR (inside the unit job today; split out to see timing) | junit |
| Integration, compose | HAPI CQL, equivalence gate on HAPI, mail, compose data | `make up-test`, `make test-integration`, `make test-e2e` | 0 failures | nightly; PR when `criteria_compiler` or `deploy/` changes | junit, compose logs |
| System | `e2e_simple`, goldens (both lake sources), `public_e2e`, backup and update drills, the browser walk | the tools, Playwright | e2e_simple PASSED ≤ 15 min; goldens identical or regenerated with a decision id; walk 0 failures, axe 0 serious | PR (e2e_simple, goldens); nightly (drills, public_e2e, walk) | `e2e.json`, goldens diff, walk report |
| Performance | stub at 5k nightly, 50k weekly on the acceptance box | `tools/bench.py`, `complete_run scale` | ≤ 20 % regression vs the stored baseline; night window with 30 % headroom | nightly, weekly | baseline JSON per release |
| Model gate | canary 54, N-12, `public_e2e` through the gateway, `qualify` | `tools.canary`, `trialbox eval qualify` | as TST-MOD-01 | per model build and release | qualification record |
| Supply chain | lock, pip-audit, licences, image Trivy, SBOM, JVM jar hashes | `make supply-chain`, `make release-gates` | 0 unallowed advisories; gates in blocking mode | PR (lock side), release (images) | `gates.json`, SBOMs, SOUP list |
| Acceptance | IQ, OQ, PQ per site; real-data dry run; blind re-entry | protocols (TST-IQ/OQ/PQ) | as the VMP | G4, G5 | signed protocols |
| Traceability | every URS → test node ids → result on the release commit | `gen_traceability.py --evidence` | no URS of level U/I/E without a passing node id from design freeze | PR (warn) → PR (fail) from design freeze | the matrix with status, in the release record |

Rules that go with it: master protected with the required list above and CODEOWNERS on Class B paths; a failing
test re-runs once, a pass on re-run is a flake to be marked within one working day and fixed within ten; a red
nightly opens a problem entry; the release record carries the CI run ids, coverage, mutation score, matrix and SBOM.

## 7. Questions only the owner can decide

1. **Internal safety class.** Treat the screening core as Class B for engineering purposes (no regulatory claim)?
   Recommended: yes. It costs about one agent week (cards T-SAFE-TEST, T-MUT, WS-12.1) and gives the hospitals an
   answer when their IT asks how the safety rules are verified.
2. **Problem tracker.** Enable GitHub Issues on the repository, or keep a problems file in the repository?
   Recommended: Issues (labels, links to PRs) with a nightly export to `docs/validation/problems.csv` for the release
   record.
3. **Public repository.** The repository is public. Keep it public while site packs, the IT pack and the security
   design live in it? Recommended: make it private before the hospital IT meetings, or move site material out.

## 8. Commands run and their results

| # | Command (in `trialbox/`) | Result | Time |
| --- | --- | --- | --- |
| 1 | `make check-disk` (TB_SCRATCH = scratchpad) | pass, 29 GB free | < 1 s |
| 2 | `PYTEST_N=3 make test` (TB_SCRATCH = scratchpad under `/tmp/claude-0`) | rc 2: 2,260 errors, 9 skipped (initdb permission denied) | 71 s |
| 3 | `make check-disk` (TB_SCRATCH=/var/tmp/tb-04-eng) | pass, 28 GB free | < 1 s |
| 4 | `PYTEST_N=3 make test` (`--durations=40 --junitxml`) | rc 2: 2,236 passed, 21 failed, 12 skipped | 989 s |
| 5 | `tools/fetch_jvm_deps.sh /var/tmp/tb-04-eng/jvm` | rc 0, 103 jars | about 60 s |
| 6 | `pytest -n 3` on the 21 failures with the jars | 20 passed, 1 failed | 372 s |
| 7 | `pytest -n 0 tests/unit/test_gpu_prep.py::test_the_stub_profile_run_measures_and_extrapolates` | failed | 2.4 s |
| 8 | `make lint` | rc 0: contracts fresh, ruff clean, 873 files formatted, mypy strict 669 files no issue, doclint clean (8 documents) | 32 s |
| 9 | `make e2e-simple` | PASSED in 128.6 s (chain 53.8 s) | 130 s |
| 10 | `make goldens-check` | IDENTICAL: 17 goldens, legacy and omop sources | 141 s |
| 11 | `make data-scan` | rc 2: 1 hit (ENG-033), 1,861 files, 10 patterns | 96 s |
| 12 | `make lock-check` | PASS | 0.6 s |
| 13 | `make allowlist-check` | PASS (19 valid entries) | 0.4 s |
| 14 | `python tools/gen_traceability.py --check` | clean: 130 items, 92 requirements, 50 risks, 63 tests, 273 links | 0.1 s |
| 15 | `python -m tools.complete_run --estimate --patients 5000` | 2.72 h, US$7.44, cap US$10.96 (estimate only; no part run) | 2 s |
| 16 | `pytest -n 2 --cov=services --cov=libs --cov=tools --cov-branch` (unit marker set, jars present) | 2,261 passed, 8 skipped, 0 failed; 90.8 % / 81.3 % product | 2,386 s |
| 17 | 28 mutants × 231 safety-core tests (`-n 0 -x`, copy under `/var/tmp/tb-04-eng/mut`) | 21 killed, 7 survived; baseline 231 passed, 1 skipped in 102 s | about 45 min |
| 18 | the 7 survivors together: whole unit suite and `tools.goldens --check` | SURVIVOR_CMD | SURVIVOR_TIME |
| 19 | `gh api repos/zandis/Auto-GPT/branches/master` | `protected: false`, no required checks | — |
| 20 | `gh api repos/zandis/Auto-GPT` | `has_issues: false`, `visibility: public` | — |
| 21 | `gh api .../actions/runs` (master, `ca8f287`) | TrialBox CI success; unit job 12 min, goldens 2.5 min, e2e-simple 2 min | — |
| 22 | AST size scan (scratch script) | 85 functions > 100 lines, 27 > 200; largest `console/app.py:384` 1,518 lines | 5 s |

Not run: `make test-console` separately (its 257 tests are in rows 4 and 16), `make release-gates`, `make pip-audit`,
`make licences`, `make images`, compose tests, `complete_run` parts (see the header).

## 9. Assumptions

* The 20 jar failures are an environment gap, not a product defect: CI fetches the jars and the same tests pass with
  them (row 6). The finding is that `make test` does not say so (ENG-026).
* Run timings were taken with 8 to 12 load average from other agents on 4 cores; CI's 12 minutes for the unit job is
  the better speed reference.
* Mutants were run with stop-on-first-failure; "killed by" names the first failing test only.
* Severities follow the brief: no finding here is a Blocker on its own, because each safety rule tested by a
  surviving mutant is also guarded on the cascade (SCREEN) path, which is the path the PoC lists come from; ENG-018
  is High because NAV, MICROBATCH and CASE use the unguarded copy.
* Branch protection was read through the REST API with the session's token; a ruleset at organisation level would not
  show there, but the branch endpoint reports `protected: false`, which covers both.
