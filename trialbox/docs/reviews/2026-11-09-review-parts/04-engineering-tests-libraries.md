# 04 — Engineering practice, test strategy and libraries

Reviewer 4 of 6. Read-only review of `trialbox/` at `ada9c8f` (origin/master), 2026-11-09. Scope: tests, CI, code
quality, libraries, performance, repository hygiene. No cloud, no secrets printed, nothing edited or pushed.

## Summary

* **Suite result.** `pytest -m "not integration and not e2e and not llm and not perf" tests/unit tests/console tests/testbench`
  with coverage: **1,423 passed, 2 skipped (MIMIC demo not fetched), 0 failed, 18 min 07 s wall, single process.**
  `ruff check` and `ruff format --check` are clean (718 files). `pytest-cov` was missing from the venv (it is not in the
  `dev` extra) and was installed with `uv`; `--cov-report=term-skipped` is not a valid report name in pytest-cov 7.1,
  `term-missing:skip-covered` was used instead.
* **Coverage.** **72 % overall** (49,864 statements). Excluding `tools/` (gates, drills and eval scripts, which the
  prescribed command does not exercise) the services and libraries are at **84 %**. The weak spots are the orchestrator
  scenarios (`nav.py` 13 %, `case.py` 24 %, `screen.py` 35 %, `cohort.py` 44 %), `console/backend.py` 40 %,
  `console/screening_log.py` 50 %, `mail_gateway/gateway.py` 63 % and `llm_stub/handlers.py` 60 %.
* **The headline problem is CI, not the tests.** The tests are plentiful (1,013 functions, 1,423 cases, mean 4.4
  asserts per test, only 3 zero-assert tests) and the oracles are good (planted generator counts, recounts from CSV,
  CQL-vs-SQL equivalence, byte-identical re-runs). But the one GitHub workflow runs only `e2e_simple` and the backup
  drill, on pull requests only. **No pytest, no ruff, no mypy, no doclint, no contracts-check, no container build, no
  dependency audit, no SBOM runs in CI**, although the spec (§16, l.632–637) requires `mypy --strict`, hadolint,
  shellcheck, hashes in the lock and an SBOM allowlist. The "done" that `docs/DECISIONS.md` records at each step is a
  manual local run.
* **The test database fixture is the contention the other reviewers saw.** `tests/conftest.py` makes
  `_private_trial_db` **autouse**, so every one of the 1,423 tests, including pure-logic unit tests, depends on a
  session-scoped throwaway PostgreSQL (`tools/pglocal.py`). Each test gets its own schema prefix and **nothing drops
  the schemas** (212 schemas and 113 MB in the database after one run; 440 MB on disk with WAL), and an aborted
  run **leaks the cluster** (four dead `/tmp/tb-pgtest-*` directories, ~260 MB, were on this host).
* **Supply chain.** `deploy/requirements.lock` has **no hashes**; `make venv` installs **unpinned** `-e ".[dev]"`, so the
  venv the tests run in differs from the image in **32 of 74** locked packages (pypdf 6.19 → 7.0 major, fastapi
  0.142 → 0.162, pydantic 2.13 → 2.14). The README's "pinned dependencies" is not true for the venv. `python:3.12-slim`
  is pinned by tag, not digest. `fhir.resources` is declared and never imported.
* **Code quality.** Mostly good: mypy strict with only 40 `# type: ignore` in production code, 76 custom exception
  classes, structured JSON logging with a PHI scrubber, low duplication, almost no dead code. The hotspots are a few
  very large procedural functions (29 F-grade, 29 E-grade by radon; `e2e_simple.run` CC 162, `public_e2e.run` 146,
  `deliverables.pack.build_pack` 106) and 1,458 `Any` usages in services.
* **Hygiene.** The repository root is still Auto-GPT (79 Python files, 6,115 lines, Auto-GPT README, Dockerfile,
  requirements, committed LLM `outputs/`, MIT licence by Toran Bruce Richards) while `trialbox/pyproject.toml` says
  `Proprietary` and `trialbox/` has no LICENSE or third-party notices (axe-core MPL-2.0 and htmx are vendored).

## Findings

Severity: **H** high, **M** medium, **L** low. Effort: XS (<½ day), S (≤2 days), M (≤2 weeks), L (more).

| ID | Sev | Area | Finding | Evidence | Fix | Gain vs cost | Effort |
|---|---|---|---|---|---|---|---|
| E-01 | H | CI | CI runs no test suite and no lint. The single workflow runs `make e2e-simple` and `make backup-drill` on `pull_request` paths `trialbox/**`; nothing on `push` to master, no schedule. The 1,423-case suite, `make lint` (ruff, mypy strict, doclint, contracts-check), the ruleset equivalence gate and `public_e2e` are only run by hand. | `.github/workflows/trialbox-e2e.yml` (one job, two `make` steps); `docs/DECISIONS.md` l.2786 records "Suites … 1,412 passed … `make lint` clean" as a manual step | Add jobs: `lint` (ruff, mypy, doclint, contracts-check, shellcheck, hadolint; ~4 min), `test` (pytest with `-n auto`, Postgres from the runner image, sharded unit/console/testbench + in-process integration), keep `e2e-simple`; add `push: branches: [master]` and a nightly `schedule` for `public_e2e`, `update_drill`, image build and `pip-audit`. | Very high: today a green PR check proves only one path on one profile; a merge that breaks 1,400 tests or mypy is not caught. Cost: one workflow file, ~10 min CI time with xdist. | S |
| E-02 | H | Tests / fixture | Autouse Postgres for every test; schemas never dropped; cluster leaks on abort. `_private_trial_db` (autouse) → `db_url` → `pg_cluster_url` (session) starts a cluster via `tools/pglocal.py` before the first test, even for tests that never touch a DB. Each test's `tb_prefix` schemas stay (212 schemas / 113 MB after one run, 440 MB on disk). Cleanup is only in the generator's `yield` tail, so Ctrl-C/kill/OOM leaves `pg_ctl` running and `/tmp/tb-pgtest-*` behind. `max_connections=300` and one connection per store (15 `Database.connect` sites) make concurrent suites contend. | `tests/conftest.py` l.21–57; `tools/pglocal.py` `ensure()`/`stop()`; `/tmp/tb-pgtest-{7wed960u,dw9e5cjo,m0303uro}` dead clusters 46–118 MB each; live cluster 212 schemas (`pg_namespace`) | Make the DB opt-in: a `db` marker or make `db_url` lazy (only tests that request it); drop the test's schemas in `db_url` teardown (`DROP SCHEMA … CASCADE` for the prefix) or create one database per session and `DROP DATABASE` at the end; register `atexit`/`SIGTERM` cleanup in `pglocal`; put the cluster under `tmp_path_factory` with the pid in the name. | High: removes the cross-agent contention, ~250 MB/run of disk, and the Postgres dependency for ~60 % of tests; makes `-n auto` safe. Cost: ~40 lines. | S |
| E-03 | H | Dependencies | Lock without hashes; venv not from the lock; dev deps unpinned; base image by tag; no audit/SBOM. `requirements.lock` is `uv pip compile` output with 0 `sha256`; `make venv` runs `uv pip install -e ".[dev]"` (resolves fresh), so the tested set drifts from the image: 32/74 differ, incl. pypdf 6.19.0→7.0.0 (major), fastapi 0.142.2→0.162.2, starlette 1.7→1.10, pydantic 2.13.5→2.14.3, python-dateutil 2.9→4.0. `python.Dockerfile` `FROM python:3.12-slim` (no digest). No `pip-audit`, `syft`/`cyclonedx` anywhere; spec §16 l.637 requires hashes and an SBOM allowlist. CI's uv cache is keyed on `pyproject.toml`, so it never invalidates on upstream releases. | `deploy/requirements.lock` header; `Makefile` `venv:`; drift list in this review's notes; `deploy/docker/python.Dockerfile` l.7; `spec/v4/16_vv_engineering_operations.md` l.637 | Adopt `uv lock` (`uv.lock` with hashes, incl. dev group) and `uv sync --frozen` in `make venv` and the Dockerfiles (`uv export --format requirements-txt --hash`); digest-pin `python:3.12-slim`; add `pip-audit` and a CycloneDX SBOM job (weekly and on release); key the CI cache on the lock. | High: reproducible tests = image, supply-chain integrity the spec already promises. Cost: half a day plus a one-time re-resolve. | S |
| E-04 | M | Tests / speed | 18 min serial suite; 5 min in two Monte-Carlo tests. `test_recall_cert::test_sequence_covers_true_rate_over_monthly_looks` 172 s and `test_recall_ledger::test_twelve_looks…` 125 s; `test_cascade_pipeline` setup 49 s; testbench e2e 41 s. No `pytest-xdist`; `-p randomly` not installed; the `slow` marker is used once. | `--durations=40` in `scratchpad/cov/full_run.log`; `pyproject.toml` `[dev]` | Mark the two statistical tests `slow` and run the 150-ledger per-commit size (spec VV-23) with the 2,000-ledger size nightly; add `pytest-xdist` (`-n auto`, safe once E-02 is fixed; per-pid prefixes already exist); cache the session `ingested` lake as a `tmp_path_factory` artefact keyed on the fixture inputs. | ~18 → ~5 min on 4 cores; developers will actually run the suite. Cost: small. | S |
| E-05 | M | Tests / parsers | No property-based or fuzz tests for the parsers. `hypothesis` is not a dependency; the only fuzz is a seeded random routing-document test. The HL7 v2 parser is home-grown (100 lines) and ignores MSH-2 encoding characters, sub-components (`&`) and non-first repetitions, and decodes anything not labelled `IR87` as UTF-8 (a cp932 file raises `UnicodeDecodeError`). Era/Minguo date regexes exist in **six** modules, each slightly different. CSV encodings (cp932/big5) are detected in two places. | `services/adapter/sources/ssmix2/hl7.py`; `grep 令和\|民國` → `tb_common/phi_guard.py`, `llm_stub/handlers.py`, `orchestrator/scenarios/case.py`, `sitesetup/service.py`, `sitesetup/messy.py`, `guard/recognisers.py`; tests: `test_messy.py`, `test_japan_completeness.py`, `test_site_setup.py` are example-based | Add `hypothesis` to `dev`; round-trip properties for `hl7.escape/unescape`, `parse(render(msg)) == msg`, `ts(hl7_ts(x)) == x`; one `tb_common.dates` module for ISO/Minguo/era with a property test (`year == base + n`) and a fuzz over full-width digits and separators; a CSV-encoding property (`detect(encode(text, enc)) decodes to text`). | High for a clinical ingest path that must fail closed; the current example tests cannot find the MSH-2 or cp932 cases. Cost: 1–2 days. | S–M |
| E-06 | M | Tests / goldens | The screening-count regression gate is outside both the CI and the prescribed command. `rulesets/*/tests/expected.json` (CQL verdicts recorded from HAPI) is replayed by `tests/integration/test_ruleset_expected.py`; `test_screen_inproc.py` and `test_e2e_simple.py` check counts in process. These 18 files (63 tests) carry **no marker**, so `make test` runs them but `tests/unit tests/console tests/testbench` does not, and CI runs none of them (only `e2e_simple`, whose oracle is the generator's planted counts, is in CI). There is no committed golden of the per-ruleset funnel counts for the `ci` hospital profile; a silent change in SQL generation would show only as an `e2e_simple` recount mismatch. | `tests/integration/*.py` without `pytestmark` (list in notes); `conftest.py` skips only `integration`/`e2e` markers | Move the in-process files to `tests/inproc/` (or mark `inproc`) and run them in CI; commit `eval/.../funnel_golden.json` (ruleset × stage → count for the `ci` profile, seed fixed) with a `--update-golden` flag and a diff in the failure message. | Medium–high: protects the one number the product is about. Cost: small. | S |
| E-07 | M | Code quality | Complexity hotspots. radon: 29 F and 29 E functions; MI 0 for `criteria_compiler/service.py`, `matching/cascade/engine.py`, `tools/build_site.py`, `tools/e2e_simple.py`, `tools/synth/generator.py`. Worst: `e2e_simple.run` CC 162 (file 1,358 lines), `public_e2e.run` 146, `deliverables/pack.build_pack` 106, `build_site.report_fragments` 89, `console/studies.feas_report` 71, `sitesetup/messy.clean` 69, `adapter/pipeline.run_ingest` 68, `channels/grammar.parse_line` 67, `scenarios/nav.run` 67, `criteria_compiler.Compiler.approve` 56. Console i18n is 4 Python files of ~1,100 lines of string dicts with E501 ignored. `console/app.py` is 1,724 lines. | `radon cc -s`, `radon mi -s` (this review); `pyproject.toml` per-file-ignores | Turn the e2e stages into a registry of `Stage` callables with a shared runner (the three e2e tools already share scaffolding); split `build_pack` per deliverable; move i18n to YAML/JSON loaded once; split `console/app.py` by page module (the `register(app)` pattern already exists). Add `radon cc -n D` or ruff `C901` (max 25) to `make lint` to hold the line. | Medium: fewer regressions when stages change (they change every plan step). Cost: mechanical. | M |
| E-08 | M | Hygiene / licence | Legacy Auto-GPT at the repo root; licence ambiguity. 79 `.py` / 6,115 lines in `autogpt/`, `tests/`, `scripts/`; root `README.md` is Auto-GPT's ("USE `stable` not `master`"); root `Dockerfile`, `docker-compose.yml`, `requirements*.txt` (openai 0.27, pinecone…), `main.py`, `tests.py`, `run.bat`, `.flake8/.isort.cfg/.sourcery.yaml/.pre-commit-config.yaml`, `.devcontainer/`, `azure.yaml.template`, and **committed LLM outputs** `outputs/*.txt`. Root `LICENSE` is MIT (c) 2023 Toran Bruce Richards; `trialbox/pyproject.toml` says `Proprietary`; `trialbox/` has no LICENSE and no THIRD_PARTY notice for vendored `tools/vendor/axe.min.js` (MPL-2.0, header present) and `tools/testbench/static/htmx.min.js` 2.0.4 (no licence header). | `git ls-files` at root; `README.md` l.1; `LICENSE`; `trialbox/pyproject.toml` `license` | Delete the legacy tree in one commit (history keeps it) and either make `trialbox/` the root or leave a one-paragraph root README pointing to it; add `trialbox/LICENSE` matching `pyproject`, and `THIRD_PARTY_NOTICES.md` (axe-core MPL-2.0, htmx 0BSD/BSD-2, NCBI, Noto fonts OFL, MIMIC ODbL as already noted in VALIDATION.md). | Medium: removes a real licence contradiction before release and 6 k lines of noise for every grep/scanner. Cost: hours. | S |
| E-09 | L | Hygiene / git | Large and generated files committed; nested `.git`. Five `rulesets/*/tests/patients.ndjson` 3.4–4.7 MB (19 MB, regenerable), four `eval/bakeoff/results/…/predictions_*.csv` 1.2 MB each, two `note.csv` fixtures 1.0–1.2 MB, `icd10cm_full.parquet` 1.0 MB; pack 25 MB. `site/assets/screens/` screenshots (11) and `libs/tb_contracts/generated/` are committed (the latter deliberately, with `contracts-check`). `trialbox/rulesets/.git` is a nested repository on disk (made by the dulwich-based ruleset registry), not in `.gitignore`. | `git rev-list --objects … | cat-file --batch-check`; `git ls-files`; `ls trialbox/rulesets/.git` | Generate `patients.ndjson` from the seed in CI (or git-lfs); keep eval CSVs under `eval/` but stop adding per-run predictions (store aggregates); add `rulesets/.git/` to `.gitignore` with a comment. | Low–medium; mostly keeps the clone small as eval runs accumulate. | S |
| E-10 | M | Libraries | Declared-but-unused and misfit dependencies. `fhir.resources>=8` is in `dependencies` and imported nowhere (FHIR validation is HAPI's validator jar; models are hand-written); `sqlalchemy>=2.0` is used by one adapter source (`cgrd_sql/source.py`) only; `pytest-cov` is absent from `dev`. | `grep -r "from fhir.resources"` → 0; `grep sqlalchemy` → 1 file | Remove `fhir.resources` (or use it in `adapter/validate`); keep SQLAlchemy only as an optional extra for the SQL source; add `pytest-cov`, `pytest-xdist`, `hypothesis`, `pytest-randomly` to `dev`. | Smaller images and a true dependency list. Cost: trivial. | XS |
| E-11 | M | Code / DB layer | One connection per store, no reconnect, no pool; migration runner splits on `;`. `tb_common.db.Database.connect` opens one `psycopg.connect(autocommit=True)` per store (15 sites), serialised with an `RLock`; an `OperationalError` after connect (server restart, idle timeout) is not caught anywhere, so a store stays broken until the service restarts. `migrate()` splits each version on `;`, which breaks any PL/pgSQL `DO $$ … $$` or trigger body; applied versions are counted, not checksummed. | `libs/tb_common/db.py` l.99–177; `grep OperationalError` → only the connect path | Use `psycopg_pool.ConnectionPool(min_size=1, max_size=N)` per process and `with pool.connection()` in `transaction()`; execute a version script as one `execute()` (psycopg 3 accepts multi-statement strings) and store a SHA-256 of each applied version in `_schema_version`. Alembic is **not** recommended: the schema-per-store, append-only list is small and fits the signed-bundle update path. | Medium: resilience on a box that runs for months; the pool is 20 lines. | S–M |
| E-12 | L | Configuration | Env-var sprawl: 98 distinct `TB_*` variables are read in code (177 tokens), **55 are not mentioned** in `docs/`, `.env.example`, `settings.example.yaml` or compose files (e.g. `TB_SCREEN_WORKERS`, `TB_FHIR_WORKERS`, `TB_WORKERS`, `TB_SCHEDULER`, `TB_TZ`, `TB_REVEAL_MAX_PER_HOUR`, `TB_SKIP_AUDIT`, `TB_UPDATE_*`). Settings live in three places: `.env` via `tb_common.config.Env`, `settings.yaml` (jsonschema-validated) and ad-hoc `os.environ.get` in services and tools. | `grep -o "environ.*TB_[A-Z_]*"` vs docs (lists in notes); `libs/tb_common/config.py` | One `Env` class that declares every variable (name, default, doc, which services) and a generated `docs/` reference table; a unit test that every `TB_*` read in code is declared. `pydantic-settings` is optional; the gain is the declaration, not the library. | Medium for operators (the box is configured by hospital IT); cost small. | S |
| E-13 | L | Conventions | Error handling and types. 88 `except Exception` in production code, 13 of them swallow (`pass`/`continue`/`return …`) against the spec's "no silently swallowed exceptions"; 1 bare `except:`. mypy `--strict` passes with 40 `# type: ignore` (good), but `Any` appears 1,458 times in `services/` (route payloads as `dict[str, Any]`). Logging is consistent where `tb_common.http.create_app` is used (12/14 apps; JSON + PHI scrubber) but `logging.getLogger` appears in only 22 modules, and the two 1,000-line e2e tools print. | `grep` counts in notes; `libs/tb_common/logging.py` | Enable ruff `BLE001` and `S110` (allow-list the 13 with a reason comment); introduce `TypedDict`/pydantic models for the console payloads at the orchestrator boundary. | Low–medium; mostly guards future code. | M |
| E-14 | L | Tests / e2e scope | What no automated run covers: the **real model pair** (only `complete_run --model pair` on a paid GPU VM, by hand); **real OCR** (`doc_parser._ocr_pdf` is `pragma: no cover`, hard-codes `lang="chinese_cht"`, so Japanese scans are never OCR'd correctly, and has no test with a scanned PDF); **Docker/compose** (compose integration tests need `TB_INTEGRATION=1` + `make up-test`; CI never builds an image; no hadolint); **`install.sh` end to end** (tests do `bash -n`, grep the text and run `--tier`/`--ctgov-check` branches with a fake docker; no VM/container run of a full install); the **Windows path** (`deploy/windows/preflight.ps1`, 67 lines, no test at all, no `pwsh` parse); **load/performance** (zero `perf`-marked tests, `tools/bench.py` 0 % covered, `hospital_sim scale` manual). `e2e_simple`/`public_e2e`/walk/backup/update drills cover the business path, the console in 3 languages × 5 roles, backup-restore and signed update very well, on the stub model only. | `services/doc_parser/parser.py` l.128–143; `tests/unit/test_install_tiers.py`; `deploy/windows/`; `grep pytest.mark.perf` → 0 | Nightly: `docker compose build` + hadolint + `make up-test` + `tests/integration`; a Windows runner job that runs `pwsh -c "[ScriptBlock]::Create((gc preflight.ps1 -Raw))"` and the preflight on a stub; a perf smoke (`bench.py --quick`) asserting the §11.3 budgets at a 1/50 scale; a weekly GPU run of `complete_run --model pair` whose report is committed under `eval/`. OCR: pick `lang` from the site language and add one scanned-PDF fixture per language. | Medium; these are the paths a hospital IT department hits first. | M–L |
| E-15 | L | Duplication | Low overall (a hash of 8-line windows finds few pairs), but real: `reports/cohort_pdf.py` ↔ `reports/screen_summary_pdf.py` (16 shared windows) and `feasibility_pdf.py`; `libs/tb_llm/client.py` copied into `tools/bakeoff_live.py` (9 windows); era-date and PHI regex sets in 3–6 modules (E-05); `e2e_simple`/`public_e2e`/`cascade_e2e` stage scaffolding; `make_cohort_docs` ↔ `make_nhi_docs`. | duplication scan in notes | Shared reportlab table/header helper; `bakeoff_live` imports `tb_llm`; `tb_common.dates`; one `tb_common.phi` regex module used by `logging`, `phi_guard` and `guard.recognisers`. | Low–medium; the PHI regex divergence is the one with a safety angle. | S |
| E-16 | L | Tests / flakiness | Order dependence: see the randomized-sample result below. Risk indicators: 16 `time.sleep` in tests, 10 unfrozen `datetime.now()`/`date.today()` calls (no freezegun/time-machine), 3 fixed ports (3143, 8025, 8090), 3 hard-coded `/tmp` paths; 0 unseeded `random`, 0 direct `os.environ[...] =`. Tests that hit the network: none in the unit tier (every `httpx` use goes through `MockTransport`/monkeypatch; `test_no_direct_model_calls` enforces the gateway path); the compose/e2e tiers do by design. | `grep` counts in notes; randomized re-run (`pytest -p randomly`) of `tests/console`, `tests/testbench` and 12 unit files: **391 passed, 0 failed, 4 min 42 s** — no order dependence found in the sample | Add `pytest-randomly` to `dev` and run with a printed seed in CI; `time-machine` for the month-end/quarter tests; `pytest-socket` (`--disable-socket --allow-unix-socket`) in the unit tier to make the no-network property explicit. | Low; cheap insurance. | XS |
| E-17 | L | Docs accuracy | README: "`make venv` # .venv with the pinned dependencies" is wrong (E-03); "`make e2e-simple` about 2 minutes" vs Makefile "about 75 s" vs measured **109 s (1 min 50 s wall) on this 2-core container**, so both are roughly right and should agree; `docs/DECISIONS.md` references `make poc-hermes`, which does not exist. Otherwise README's repository map, commands and the eight-document set are accurate and `doclint` passes. | `README.md` l.40–41; `Makefile` l.52; `grep "make poc-hermes" docs/DECISIONS.md` | Fix the three sentences; have `doclint` also check `make <target>` names against the Makefile. | Low. | XS |
| E-18 | L | CI speed/caching | What exists is reasonable: uv cache, maven cache, `.cache/jvm`+fonts cache keyed on the fetch scripts, `concurrency` cancel-in-progress, 20-min timeout, `permissions: contents: read`. Gaps: cache key on `pyproject.toml` rather than a lock (E-03); `apt-get install postgresql` on every run if the runner image changes; no matrix; `workflow_dispatch` only otherwise. | `.github/workflows/trialbox-e2e.yml` | Key caches on the lock; use `services: postgres:16` or the runner's binaries explicitly; add the jobs from E-01. | Low on its own. | XS |

### Positive observations (no action)

* Oracles are independent of the code under test: planted generator states, CSV recounts, HAPI-recorded CQL verdicts,
  hash-chained audit log, byte-identical re-runs (`test_rerun.py`, `test_second_run_is_reproducible`).
* `test_no_direct_model_calls.py` and `test_service_token_everywhere.py` are architecture tests that enforce the two
  most important invariants (no model call outside the gateway; a token on every inter-service call).
* The `req` marker is validated against the spec requirement ids at collection time.
* `contracts-check` fails on drift between `schemas/` and the generated models.
* Shell scripts are clean under `shellcheck -S warning` (3 warnings, 0 errors, 757 lines).
* `vulture` at 80 % confidence finds 2 unused variables; at 60 % the hits are pydantic validators and
  decorator-registered routes. Dead code is not a problem.

## Coverage table

Prescribed command, `--cov=services --cov=libs --cov=tools`, 1,423 tests. `tools/` entries are low because the
gates (`e2e_simple`, `public_e2e`, `complete_run`, `build_site`, `bench`) are exercised only by the unmarked
`tests/integration` wrappers and by `make` targets, which the prescribed paths exclude.

| Package | Stmts | Covered | % |
|---|---|---|---|
| tools (top-level scripts) | 11820 | 3804 | 32% |
| services/orchestrator | 7864 | 5274 | 67% |
| services/console | 6028 | 4926 | 82% |
| services/adapter | 2386 | 2036 | 85% |
| libs/tb_contracts | 2172 | 2118 | 98% |
| libs/tb_common | 2162 | 1951 | 90% |
| services/criteria_compiler | 2127 | 1919 | 90% |
| services/matching | 1970 | 1793 | 91% |
| tools/trialbox (CLI: backup, update, doctor) | 1657 | 1452 | 88% |
| services/dataplat | 1527 | 1401 | 92% |
| services/sitesetup | 1481 | 1342 | 91% |
| services/datacore | 1439 | 1328 | 92% |
| services/deliverables | 956 | 936 | 98% |
| tools/testbench | 869 | 689 | 79% |
| tools/synth | 850 | 841 | 99% |
| services/gateway | 678 | 623 | 92% |
| services/mail_gateway | 576 | 466 | 81% |
| services/lake | 545 | 457 | 84% |
| services/rc_bridge | 437 | 407 | 93% |
| tools/synth_hospital | 308 | 249 | 81% |
| services/rc_sim | 296 | 274 | 93% |
| services/llm_stub | 294 | 186 | 63% |
| services/channels | 263 | 232 | 88% |
| services/registry | 262 | 233 | 89% |
| services/doc_parser | 227 | 198 | 87% |
| services/guard | 178 | 173 | 97% |
| libs/tb_testkit | 138 | 133 | 96% |
| libs/tb_llm | 129 | 116 | 90% |
| services/tracestore | 109 | 106 | 97% |
| services/embed_service | 75 | 49 | 65% |
| **TOTAL** | **49864** | **35748** | **72%** |
| services + libs only (derived) | 34360 | 28713 | 84% |

**Critical modules with low coverage** (≥150 statements, outside `tools/`):

| Module | % | Why it matters |
|---|---|---|
| `services/console/cli.py` | 0 % | operator CLI |
| `services/orchestrator/scenarios/nav.py` | 13 % | NAV scenario (RA-BIO/ONC-OSI drafts) — covered only by in-process integration tests |
| `services/orchestrator/scenarios/case.py` | 24 % | CASE scenario incl. the era/Minguo date parser |
| `services/orchestrator/scenarios/screen.py` | 35 % | SCREEN — the screening list itself; the cascade engine (`matching/cascade/engine.py`) is at 86 % |
| `services/console/backend.py` | 40 % | console ↔ orchestrator HTTP backend (the in-process backend is what tests use) |
| `services/orchestrator/scenarios/cohort.py` | 44 % | cohort lists |
| `services/console/screening_log.py` | 50 % | screening log HTML/XLSX |
| `services/llm_stub/handlers.py` | 60 % | the stub model every gate relies on |
| `services/orchestrator/scenarios/consent.py` | 62 % | consent read-back |
| `services/mail_gateway/gateway.py` | 63 % | IMAP/SMTP path (compose-only tests) |
| `services/embed_service/*` | 65 % | real embedder only in the image |
| `services/orchestrator/app.py` | 69 % | the orchestrator HTTP surface |
| `services/adapter/pipeline.py` (`run_ingest`, CC 68) | 72 % | the ingest entry point |

Running the unmarked `tests/integration` files (63 tests) would lift `nav`, `case`, `screen`, `cohort` and the
`tools/` gates substantially; that is the E-06 recommendation.

## Library recommendations

| Area | Current | Proposed | Why | Cost |
|---|---|---|---|---|
| DB access | psycopg 3, one connection per store, home-grown `Database`/`Tx` with `?` placeholders | **Keep psycopg 3; add `psycopg_pool.ConnectionPool`**. Do not adopt SQLAlchemy Core. | Queries are plain SQL and small; a pool gives reconnect and bounded connections (E-11). SQLAlchemy would add a second SQL dialect layer for no query the code needs; it is already used by one adapter source and can stay there. | S: ~20 lines in `tb_common.db`; test with the existing fixtures |
| Migrations | home-grown versioned list in `Database.migrate`, per schema, advisory-locked | **Keep**; execute scripts whole, add a checksum column | Alembic brings autogenerate and env.py machinery the signed-bundle update path (`other/migrations/NNN_*.sql`, D-138) does not want; the current design is auditable. | XS |
| Job queue / outbox | home-grown Postgres outbox with claim/backoff and a kill-loop test | **Keep** | The kill-loop tests (`test_outbox_killloop`) are exactly the property a queue library would have to prove again; `procrastinate`/`pgqueuer` add little for one worker type. | — |
| Scheduler | APScheduler 3.11 (`<4`) in `scheduler.py`, `console/timers.py` | **Keep, pinned `<4`** | 3.x is maintenance-only and 4.x is a rewrite; the use is a few cron-like timers. Revisit at 4.0 GA. | — |
| HTTP client | httpx 0.28 + hand-written retry loops in 6 places (`tb_common.http`, `tb_common.llm` 2 attempts, outbox backoff, three eval tools 6–8 attempts) | **httpx + `tenacity`** for the client-side loops (not for the outbox, whose backoff is persisted state) | One declarative policy (exponential, jitter, retry-on 5xx/connect) instead of five variants; better logs. | S |
| Settings | `tb_common.config.Env` (+ `.env`) and `settings.yaml` validated by jsonschema | **Keep the two-file model; declare every variable** (E-12). `pydantic-settings` optional. | The gap is undocumented variables, not the loader; jsonschema validation of `settings.yaml` is already strict and shared with the console. | S |
| HL7 v2 (SS-MIX2) | home-grown 100-line parser | **`hl7` (python-hl7, BSD, pure Python)** for parsing/escaping; keep the `decode()` by MSH-18 and the `ts()` helpers | Handles MSH-2 encoding characters, repetitions, sub-components and escapes; the SS-MIX2 source is the only user, so the swap is local. Alternative `hl7apy` validates against the 2.5 tables but is heavier and slower. | S (one module + property tests) |
| FHIR models | `fhir.resources` declared, unused; hand-written dicts; HAPI validator jar for JP Core | **Remove `fhir.resources`** | Dead weight in every image; validation already happens in HAPI. | XS |
| Excel | openpyxl (write reports; read intake sheets) | **Keep openpyxl**; `python-calamine` only if intake sheets exceed ~10 MB | Report generation needs styling, which calamine does not do; intake files are small. | — |
| Date parsing | `python-dateutil` declared; six ad-hoc regex sets for ISO/Minguo/Japanese era | **One `tb_common.dates` module** with property tests; no external library (none covers 民國 + 令和 + full-width digits well; `japanera` covers JP only) | Consistency across PHI scrubber, CASE, site set-up and the stub; today the six differ. | S |
| OCR | PaddleOCR, `lang="chinese_cht"` hard-coded, optional, untested | **Keep PaddleOCR; select `lang` per site (`japan`/`chinese_cht`/`en`) and add one scanned-PDF fixture per language**. Tesseract (`jpn+chi_tra`) is the lighter fallback for CPU-only boxes. | PaddleOCR is better than Tesseract for CJK; the bug is the fixed language, not the library. | S |
| LLM client | home-grown `GatewayClient` (httpx, OpenAI-compatible, strict `json_schema`, labels) | **Keep** | The `openai` SDK would bypass the gateway labels and the no-direct-model-call invariant; the client is 225 lines and 90 % covered. | — |
| Lake | DuckDB 1.5.5 + sqlglot + pyarrow | **Keep** (pinned exactly; good) | — | — |
| Dependency management | `uv pip compile` lock without hashes; unpinned dev venv | **`uv lock` / `uv sync --frozen` with hashes; `pip-audit`; CycloneDX SBOM** | E-03; the spec already requires it. | S |
| Test libraries | pytest 9, pytest-timeout | **Add `pytest-cov`, `pytest-xdist`, `hypothesis`, `pytest-randomly`, `pytest-socket`, `time-machine`** to `dev` | E-04, E-05, E-16. | XS |

## Performance and optimisation

`make e2e-simple` equivalent (`python -m tools.e2e_simple --dir … --json …`, stub model, `ci` profile = 2 sites ×
2,500 patients): **PASSED in 109 s wall (chain 56 s)** on this 2-core container; the Makefile says ~75 s on one laptop
core, the README "about 2 minutes". The 15-minute budget (`BUDGET_S`) has an 8× margin.

**Stage times** (the `Stage.seconds` timers; stages 0–8 run through `feas_demo`/`list_demo`/`rc_demo` and are mostly
untimed, hence "chain 56 s"):

| Stage | s | share of timed |
|---|---|---|
| 12 site set-up and data harmonization | 21.0 | 40 % |
| re-run (FR-REP-02, byte-identical FEAS/SCREEN) | 11.5 | 22 % |
| 13 Japan: SS-MIX2, JP Core, licensed code lists | 9.6 | 18 % |
| 11 trial lifecycle | 4.8 | 9 % |
| 10 built-in data capture | 1.3 | 2 % |
| 0, 4, 5, 8, 14, audit (each) | 0.6–0.8 | — |
| 1, 2, 3, 7, 9 (each) | ≤ 0.2 | — |

**cProfile of the whole `e2e_simple.run()`** (profiled wall 207 s; the profiler roughly doubles Python-heavy code, so
the shares below, not the seconds, are the honest numbers). Profile at
`scratchpad/prof.log`; harness `scratchpad/prof_e2e.py`.

| Hotspot | Calls | Cumulative | What is happening | Optimisation | Expected gain |
|---|---|---|---|---|---|
| `tb_common.ruleset.load_approved` → `Ruleset.load` | 2,129 | **38.8 s** (`yaml.safe_load` 23 s, `pathlib.relative_to` 60,719 calls 8.8 s, `_strptime`/json the rest) | `console/backend.ruleset_infos` calls `load_approved` for every ruleset on **every console request** (1,801 of the calls), and `Ruleset.load` `rglob`s and `read_bytes()` **every file** in the ruleset directory — including `tests/patients.ndjson` (3.4–4.7 MB each) and `cql/elm/*.json` — then parses the manifest YAML and every IR/valueset JSON, to return four fields. | (a) `ruleset_infos` reads only `manifest.yaml` (`manifest_of(dir)`); (b) `Ruleset.load` excludes `tests/` and loads `cql/elm` lazily; (c) an in-process cache keyed on `(dir, max mtime)` for full loads; (d) `yaml.CSafeLoader` when libyaml is present. | **−30 to −35 s of 207 s profiled (≈ −20 s of the 109 s real run); the console's per-page cost for this part drops from ~100 ms to ~1 ms.** Also the single biggest win for the real box, where the console is used all day. |
| `lake.store.Lake.query` / `Lake.connect` | 57 / 61 | 47.5 s + 44 s own (native DuckDB time) | Each `query()` opens a new read-only `duckdb.connect` on the snapshot file and closes it after one statement, so DuckDB re-reads the catalog, re-attaches the parquet views and starts with a cold buffer pool for every FEAS/SCREEN statement (~0.8 s each). | One connection per `(lake, snapshot)` per process kept open (DuckDB shares the instance anyway), `con.cursor()` per query, `cursor.interrupt()` on the timer; close on snapshot rebuild. | −5 to −15 s of the real run (the queries themselves stay; the per-query cold start goes). Re-check the `_CONNECT_LOCK` reasoning for rebuild. |
| `adapter.mapping.engine.map_row` (`prune` 4.9 M calls, `set_path` 1.8 M, `value` 1.8 M) | 203,524 rows | 32.3 s | Pure-Python per-row mapping: paths are split and dicts pruned for every row of every table (ingest of 2 × 2,500 patients → 155 k resources). | Pre-compile each mapping rule's path to a tuple and a setter closure once per table; prune once per resource, not per field; build rows with a comprehension. | 2–3× on the map stage: −10 s profiled (≈ −4 to −6 s real); scales linearly with the 50 k-patient nightly delta (§11.3 ingest budget). |
| `lake.sqlguard.check_select` → `sqlglot.parse` | 128 | 10.4 s | Every FEAS/SCREEN statement is re-parsed by sqlglot (80 ms each) although the SQL text repeats (same ruleset, different params). | `functools.lru_cache` on the SQL text hash (the guard's verdict is pure). | −8 s profiled (≈ −4 s real). |
| `embed_service.embedder.HashEmbedder.embed` | 240 | 11.0 s | The stub hash embedder (test only). | Not worth it; the image embedder is different code. | — |
| `_strptime` (303 k) / `json.raw_decode` (276 k) / `json.iterencode` (213 k) | — | ~10 s | Date parsing with `strptime` and NDJSON round-trips in the generator and ingest. | `date.fromisoformat`; `orjson` for the NDJSON paths (optional). | −3 to −5 s profiled. |

Together the first four items would take `e2e_simple` from ~109 s to roughly **60–70 s** on this host and, more
importantly, remove a console-side pathology (reading ~100 MB of ruleset files per page view) that no test measures.
A `perf` tier with one budgeted test per item above (`tests/perf/test_budgets.py`, `pytest -m perf`, run nightly) would
keep them from coming back.

## Not checked

* The compose, e2e (`tests/e2e`, Playwright walk), `llm`, `egress` and `perf` tiers were not run (no Docker, no stack,
  no GPU in this container). Their design was read, not executed.
* `public_e2e`, `complete_run`, `update_drill` and the backup drill were not run here (the CI workflow runs the backup
  drill; the other reviewers cover the drills).
* mypy was not re-run (the DECISIONS log records `make lint` clean at this head and ruff is clean here; running mypy
  over 94 k lines would have contended with the suite for the two cores).
* No dependency CVE scan was run (no network policy for `pip-audit` databases was assumed; the finding is that none
  exists in the repo).
* The 55 undocumented `TB_*` variables were not individually traced for whether they are internal test knobs or
  operator settings.
* `eval/` results and `docs/research` were not reviewed for reproducibility.
* Windows (`deploy/windows/preflight.ps1`) was not executed (no PowerShell here).
* Housekeeping: this review's own work directories (`e2e`, `e2e_prof`, ~830 MB) were removed; the suite's throwaway
  cluster was cleaned by the fixture. The four dead `/tmp/tb-pgtest-*` clusters and `/tmp/tb-pglocal-0` (~260 MB) and
  the large `drill*`, `s9`, `e2e_*`, `dl`, `rv-e2e` directories in the shared scratchpad belong to other sessions and
  were left in place.

## Working notes (evidence)

* Suite log and `coverage.json`: `/tmp/claude-0/-home-user-Auto-GPT/b6dc012b-d091-5e78-8158-ebd09d964152/scratchpad/cov/`.
* Test inventory: unit 108 files / 737 functions; console 13 / 157; testbench 3 / 27; integration 22 / 76 (18 files,
  63 tests unmarked); e2e 3 / 14; llm 1 / 2. Markers: `parametrize` 77, `skipif` 6, `skip` 3, `e2e` 3, `llm` 2,
  `integration` 2, `slow` 1, `egress` 1, `perf` 0.
* Unmarked `tests/integration` files: `test_case_inproc`, `test_cohort_inproc`, `test_consent_inproc`, `test_e2e_simple`,
  `test_feas_demo`, `test_feas_lake`, `test_ingest_inproc`, `test_list_demo`, `test_mail_feas_inproc`, `test_nav_inproc`,
  `test_nav_retro`, `test_onboarding`, `test_rc_demo`, `test_rerun`, `test_ruleset_expected`, `test_screen_inproc`,
  `test_ssmix2_path`, `test_twpas_inproc`.
* Undocumented `TB_*` read in code: `TB_AUDIT_MIN_FREE_MB TB_BACKUP_KEEP TB_BACKUP_PUBKEY TB_CANARY_CASES TB_COMPOSE
  TB_CONSOLE_HOST TB_CONSOLE_PUBLIC_URL TB_CQL_TRANSLATOR_LIB TB_CTGOV_BASE_URL TB_DEMO_* (7) TB_DOTENV TB_DRILL_DIR
  TB_E2E_DIR TB_EVAL_LIMIT TB_FHIR_PACKAGE_HOME TB_FHIR_WORKERS TB_FONTS_DIR TB_GATEWAY_EXPECT_SHA
  TB_GATEWAY_VERIFIER_EXPECT_SHA TB_GATEWAY_VERIFIER_URL TB_HL7_VALIDATOR_JAR TB_INSTALL_UP_TIMEOUT TB_JAVA
  TB_NPM_REGISTRY TB_PG_BIN TB_PG_DIR TB_PROMPT_DIRS TB_PUBLIC_DIR TB_RC_SIM_* (3) TB_REVEAL_MAX_PER_HOUR TB_SCHEDULER
  TB_SCHEMAS_DIR TB_SCREEN_WORKERS TB_SKIP_AUDIT TB_SOURCE_PATH TB_STEP_ID TB_TESTBENCH_HOST TB_TESTBENCH_PORT TB_TZ
  TB_UPDATE_* (5) TB_VALIDATOR_IGS TB_WORKERS`.
* Lock vs venv drift (32): anyio, brotli, certifi, click, dulwich, fastapi 0.142.2→0.162.2, fhir-core, fonttools,
  markdown, numpy, opentelemetry-api, pillow 12.3→13.0, psycopg 3.3.6→3.3.8, py7zr, pyarrow 25→26, pycparser,
  pycryptodomex, pydantic 2.13.5→2.14.3, pydantic-core, pypdf 6.19→7.0, python-dateutil 2.9→4.0, python-multipart,
  reportlab 5.0.1→5.1.0, rpds-py, sqlalchemy 2.1.3→2.1.8, sqlglot, starlette 1.7→1.10, texttable, typing-inspection,
  tzdata, tzlocal.
* Convention counts (production code, non-generated): `# type: ignore` 40 (tests 124); `cast(` 14; `Any` 1,458 in
  services; `except Exception` 88 (13 swallowing); bare `except:` 1; `print(` 36 in services (CLIs) / 225 in tools;
  `getLogger` 22; custom exception classes 76; TODO/FIXME 0.
* Vendored third-party: `tools/vendor/axe.min.js` 4.10.2 (MPL-2.0 header), `tools/testbench/static/htmx.min.js` 2.0.4
  (no header); fonts fetched to `.cache/` (not committed); `eval/criterion_ml/LICENSE.NCBI`,
  `services/matching/registry_match/ncbi_upstream/LICENSE` present.
