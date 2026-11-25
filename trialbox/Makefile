# TrialBox developer entry points. Python targets use .venv (create with `make venv`).
SHELL := /bin/bash
PY ?= .venv/bin/python
COMPOSE := docker compose --project-directory deploy -f deploy/docker-compose.yml
# the test stack uses the example settings with a high per-sender limit: e2e suites run many times a day
TEST_SETTINGS := .cache/test-settings.yaml
COMPOSE_TEST := TB_HOST_OBJECTS_DIR=$(CURDIR)/deploy/.objects TB_SETTINGS_FILE=../$(TEST_SETTINGS) $(COMPOSE) -f deploy/docker-compose.test.yml --profile stub --profile test
BUILD_ARGS := $(if $(HTTPS_PROXY),--network host --build-arg HTTPS_PROXY=$(HTTPS_PROXY) --build-arg https_proxy=$(HTTPS_PROXY),)
# release identity on every image we build (T-110b, ENG-015): the version from pyproject.toml and the commit
TB_VERSION := $(shell sed -n 's/^version = "\(.*\)"$$/\1/p' pyproject.toml | head -1)
TB_REVISION := $(shell git rev-parse HEAD 2>/dev/null || echo unknown)
OCI_LABELS := --label org.opencontainers.image.version=$(TB_VERSION) --label org.opencontainers.image.revision=$(TB_REVISION) \
	--label org.opencontainers.image.title=trialbox
comma := ,
# test-stack host ports moved in deploy/.env reach every tool and test run from make (the shell environment wins)
HOST_PORTS := $(shell grep -hE '^TB_HOST_[A-Z_]+_PORT=[0-9]+$$' deploy/.env 2>/dev/null)
$(foreach v,$(HOST_PORTS),$(eval export $(subst =, ?= ,$(v))))
CA_SECRET := $(if $(TB_EXTRA_CA),--secret id=extra_ca$(comma)src=$(TB_EXTRA_CA),)


.PHONY: differential cross-card objects-dir embed-start public-data security-scan goldens goldens-check rehearse fonts jvm-deps venv venv-check clean-tmp check-disk data-scan ci test-locked property test-random test-random-locked test-pure guard test-compose walk bench-gate bench-baseline console-timing e2e-simple backup-drill demo demo-bundle contracts contracts-check lint test test-integration test-e2e test-egress images images-multiarch buildx-check two-device-check up up-test ingest-test down logs fixtures audit-verify bench open-data-e2e testbench testbench-test eval-public e2e-cascade spark-e2e verify-models fetch-weights selftest canary poc poc-down poc-status rehearse-box runbook-install test-console test-console-e2e site site-preview clean \
	lock lock-check allowlist-check scanners lock-env pip-audit lock-sbom licences trivy-db sc-images release-gates vocab-bundle-check release-images release-bundle security-contact-check supply-chain release-version release-tag media-linux

# ------------------------------------------------------------------ parallel work on one machine (D-201, RUNBOOK §13)
# Every temporary root of a run derives from TB_TEST_ROOT: one per branch, under TB_SCRATCH (an agent's scratchpad;
# default /var/tmp/trialbox-<uid>), never a fixed /tmp path that every agent on the machine shares.
# (tools/pglocal.py branch_slug: a detached HEAD, as in CI or a review worktree, is detached-<sha>)
BRANCH_SLUG := $(shell PYTHONPATH=libs:services:. $(PY) -c 'import tools.pglocal as p; print(p.branch_slug())' 2>/dev/null)
TB_SCRATCH ?= /var/tmp/trialbox-$(shell id -u)
TB_TEST_ROOT ?= $(abspath $(TB_SCRATCH))/tb-tests-$(or $(BRANCH_SLUG),detached)
export TB_TEST_ROOT
TB_MIN_FREE_GB ?= 20
TB_ROOT_BUDGET_GB ?= 10
# pytest-xdist (D-201): one worker per core; PYTEST_N=0 runs serially
PYTEST_N ?= auto
# H-73 (D-1355): the workers steal queued tests from each other (`--dist worksteal`). Under xdist's default `load` a
# worker is sent the next tests as one run of the collection, so the seven long role walks of
# tests/console/test_prefs_10f1.py (150 to 260 s each) ran one after another on one worker while the others idled:
# shard 1's last 14 % took 13 to 21 minutes (unit-shard (1/6) cancelled at 40 minutes, jobs 137064085949 and others)
XDIST_DIST = $(if $(filter-out 0,$(PYTEST_N)),--dist worksteal,)
# T-747 (D-475): SHARD=i/N runs only shard i of N of the suite (each test file in one shard, by a hash of its path;
# tools/test_shard.py), as CI's unit-shard jobs do; SHARD_RECORD=<file> also writes what the shard collected and kept
# (`python -m tools.test_shard check` over all N records proves every test ran in exactly one shard)
SHARD ?=
SHARD_RECORD ?=
SHARD_ARGS = $(if $(SHARD),--shard $(SHARD),) $(if $(SHARD_RECORD),--shard-record "$(SHARD_RECORD)",)
UV_SYNC := uv sync --frozen --group test --extra dev --python 3.12

# .venv is exactly uv.lock (the test plugins included): `uv sync` removes whatever was installed by hand, and a uv
# venv has no pip, so `pip install` into it is refused. `make test` refuses a venv that drifted from the lock.
venv:
	$(UV_SYNC)
	@# D-829: say it before the first SCREEN job, not at its report (no download here: CI runs make venv in every job)
	@[ -f $(FONTS) ] || echo "venv: the PDF reports need the fonts, not fetched yet: run 'make fonts' once (network) before the first SCREEN job" >&2

venv-check:
	@$(UV_SYNC) --check >/dev/null 2>&1 || { echo "venv-check: .venv differs from uv.lock (a dependency or pyproject.toml changed, or a package was installed by hand): run 'make venv'" >&2; exit 1; }

# the leftovers of earlier runs that nobody uses now (tools/pglocal.py clean_tmp): /tmp/pytest-of-*, the tb-pgtest-*
# and tb-pglocal-* clusters, the drills' and e2e_simple's /tmp folders, the rehearsal's runs/, the tarballs of all but
# the two newest .cache/complete-run runs, and owned clusters whose owner died. DRY=1 lists only.
clean-tmp:
	PYTHONPATH=libs:services:. $(PY) -m tools.pglocal clean-tmp $(if $(DRY),--dry-run,)

# the first step of every card (review §5.3): at least TB_MIN_FREE_GB free, and this branch's TB_TEST_ROOT inside its
# TB_ROOT_BUDGET_GB budget (reported; the budget is advice, the free space is the gate)
check-disk:
	@avail=$$(df -Pk "$(CURDIR)" | awk 'NR==2 {print int($$4 / 1048576)}'); \
	used=$$(du -sk "$(TB_TEST_ROOT)" 2>/dev/null | awk '{print int($$1 / 1048576)}'); \
	echo "check-disk: $${avail} GB free (need $(TB_MIN_FREE_GB)); $(TB_TEST_ROOT) uses $${used:-0} GB (budget $(TB_ROOT_BUDGET_GB))"; \
	if [ "$${used:-0}" -gt "$(TB_ROOT_BUDGET_GB)" ]; then echo "check-disk: over the per-branch budget: make clean-tmp, or remove $(TB_TEST_ROOT)" >&2; fi; \
	if [ "$$avail" -lt "$(TB_MIN_FREE_GB)" ]; then echo "check-disk: FAIL, under $(TB_MIN_FREE_GB) GB free: make clean-tmp first" >&2; exit 1; fi

contracts:
	$(PY) tools/gen_contracts.py

contracts-check:
	$(PY) tools/gen_contracts.py --check
	PYTHONPATH=libs:services:. $(PY) -m tb_contracts.criterion_ir --check

lint: contracts-check
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
	$(PY) -m mypy libs services tools tests
	$(PY) tools/doclint.py
	PYTHONPATH=libs:services:. $(PY) -m tools.text_keys  # D-1220: no conflicting double, no missing key
	$(PY) -m tools.form_fields  # D-1376: every POST form uses the field macro or is on the ratchet
	$(PY) -m tools.findings_register --check
	$(PY) -m tools.inline_suppressions --check  # D-1338: every `# nosec` and `# noqa: S` line has a reviewed ledger line
	$(PY) -m tools.vex check  # D-1339: every vulnerability waiver with an owner, a date and a reason (no calendar rule)

FONTS := .cache/fonts/NotoSansTC-Regular.ttf

$(FONTS):
	$(PY) tools/fetch_fonts.py

fonts: $(FONTS)

# The CQL translator jars, the HL7 validator and the FHIR packages (tools/fetch_jvm_deps.sh; Maven, Java and the
# network the first time) are a prerequisite of `make test` (ENG-026, T-653): a clean clone fetches them once, and
# again when the fetch script or the translator's pom.xml changes after the last fetch (the old translator jars are
# removed first, so a version bump takes effect). `make jvm-deps` fetches whatever is missing at any time.
TRANSLATOR_POM := services/criteria_compiler/compile_cql/translator/pom.xml
JVM_DEPS := .cache/jvm/.fetched
$(JVM_DEPS): tools/fetch_jvm_deps.sh $(TRANSLATOR_POM)
	@if [ -e $@ ]; then echo "jvm-deps: the fetch script or the translator pom changed: fetching the jars again"; \
		rm -rf .cache/jvm/cql-translator/lib; fi
	$(MAKE) --no-print-directory jvm-deps

# TMPDIR too lives under TB_TEST_ROOT, so tempfile.mkdtemp() in a test never lands in the shared /tmp. The root is
# checked and marked (tools/pglocal.py mark), and held with flock for the whole run: a second run on the same root
# stops before it touches anything. Afterwards TMPDIR is emptied, the branch's shared cluster (pglocal.for_work)
# stopped if no client uses it, and a green run's basetemp removed.
test: venv-check $(FONTS) $(JVM_DEPS)
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	@flock -n -E 75 "$(TB_TEST_ROOT)/.lock" $(MAKE) --no-print-directory test-locked; rc=$$?; \
	if [ $$rc = 75 ]; then echo "test: $(TB_TEST_ROOT) is in use by another run: give this run its own TB_TEST_ROOT" >&2; fi; exit $$rc

# the nightly random-order run (D-201, review §5.2 (3); .github/workflows/trialbox-e2e.yml): the unit suite with
# pytest-randomly, which is not in uv.lock on purpose. `uv run --with` lays it over .venv for this run only, so the
# venv stays the lock's. The seed is printed in the header; RANDOM_SEED=<n> repeats a failing order.
# The same run has no network (ENG-031, T-653): pytest-socket, laid over the same way, lets a test connect to the
# loopback and to Unix sockets only (the throwaway clusters, the in-process servers); any other connect fails the test
# with SocketConnectBlockedError naming the host. NETWORK=1 leaves the network on.
RANDOMLY ?= pytest-randomly==3.16.0
SOCKET ?= pytest-socket==0.7.0
RANDOM_SEED ?=
NETWORK ?=
NO_NETWORK = $(if $(NETWORK),,--with "$(SOCKET)")
NO_NETWORK_ARGS = $(if $(NETWORK),,--allow-hosts=127.0.0.1,::1 --allow-unix-socket)
test-random: venv-check $(FONTS) $(JVM_DEPS)
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	@flock -n -E 75 "$(TB_TEST_ROOT)/.lock" $(MAKE) --no-print-directory test-random-locked; rc=$$?; \
	if [ $$rc = 75 ]; then echo "test-random: $(TB_TEST_ROOT) is in use by another run: give this run its own TB_TEST_ROOT" >&2; fi; exit $$rc

test-random-locked:
	@rm -rf "$(TB_TEST_ROOT)/tmp" && mkdir -m 0700 -p "$(TB_TEST_ROOT)/tmp"
	TB_TEST_RANDOM=1 TMPDIR="$(TB_TEST_ROOT)/tmp" uv run --frozen --no-sync --with "$(RANDOMLY)" $(NO_NETWORK) \
		python -m pytest -p randomly $(if $(RANDOM_SEED),--randomly-seed=$(RANDOM_SEED),) $(NO_NETWORK_ARGS) \
		-n $(PYTEST_N) --basetemp "$(TB_TEST_ROOT)/pytest" -m "not integration and not e2e and not llm and not perf" \
		$(SHARD_ARGS); rc=$$?; \
	rm -rf "$(TB_TEST_ROOT)/tmp"; PYTHONPATH=libs:services:. $(PY) -m tools.pglocal stop-idle "$(TB_TEST_ROOT)/pglocal"; \
	if [ $$rc = 0 ]; then rm -rf "$(TB_TEST_ROOT)/pytest"; fi; exit $$rc

test-locked:
	@rm -rf "$(TB_TEST_ROOT)/tmp" && mkdir -m 0700 -p "$(TB_TEST_ROOT)/tmp"
	TMPDIR="$(TB_TEST_ROOT)/tmp" $(if $(TRACE),TB_TRACE_OUT="$(TRACE)",) $(PY) -m pytest -q -n $(PYTEST_N) $(XDIST_DIST) \
		--basetemp "$(TB_TEST_ROOT)/pytest" -m "not integration and not e2e and not llm and not perf" $(SHARD_ARGS) \
		$(TESTS); rc=$$?; \
	rm -rf "$(TB_TEST_ROOT)/tmp"; PYTHONPATH=libs:services:. $(PY) -m tools.pglocal stop-idle "$(TB_TEST_ROOT)/pglocal"; \
	if [ $$rc = 0 ]; then rm -rf "$(TB_TEST_ROOT)/pytest"; fi; exit $$rc

# the cross-card tests (T-747, D-475; CI job `cross-card`): the tests that fail only when two cards meet (an audit
# event without a label, a route without a permit row or a role label, a table without an inventory row or a migration
# hash, a setting not declared, a schema without its data class, a decision number twice, a forbidden word, a direct
# model call, a test that leaks state; D-623: a database opened under a run-time name, a runbook command no test runs).
# CI runs them first, in minutes, with no coverage; the unit shards run them too.
CROSS_CARD_TESTS = \
	tests/console/test_audit_browser.py::test_every_event_the_code_writes_has_a_label \
	tests/unit/test_erasure_registry.py \
	tests/console/test_t102b_roles.py \
	tests/console/test_role_route_matrix.py \
	tests/unit/test_record_inventory.py \
	tests/unit/test_migrations.py \
	tests/unit/test_authz_matrix.py \
	tests/unit/test_config_declared.py \
	tests/unit/test_dataclass.py \
	tests/unit/test_decisions_index.py \
	tests/unit/test_wording.py \
	tests/unit/test_no_direct_model_calls.py \
	tests/unit/test_test_isolation.py \
	tests/unit/test_db_schemas_enumerated.py \
	tests/unit/test_runbook_install_commands.py \
	tests/unit/test_text_keys.py
cross-card: venv-check
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	@flock -n -E 75 "$(TB_TEST_ROOT)/.lock" $(MAKE) --no-print-directory test-locked TESTS="$(CROSS_CARD_TESTS)"; rc=$$?; \
	if [ $$rc = 75 ]; then echo "cross-card: $(TB_TEST_ROOT) is in use by another run: give this run its own TB_TEST_ROOT" >&2; fi; exit $$rc

# the property gate (TB-PLAN-06 §7.5, T-737): the safety properties over their enumerated domains, the hypothesis
# properties of the unit tests (named *_property; they skip with a reason when hypothesis is not installed, and say so
# below), and tests/property/ when the folder exists. The example counts are the ones the tests set themselves.
PROPERTY_TESTS = tests/unit/test_safety_properties.py tests/unit/test_dates.py tests/unit/test_encoding.py tests/unit/test_labvalue.py \
	$(wildcard tests/property)
# card 10A-1: list the approved rulesets on main with an inclusion whose line may negate what its logic asks (read-only)
.PHONY: negated-inclusion-scan
negated-inclusion-scan: venv-check
	PYTHONPATH=libs:services:. $(PY) -m criteria_compiler.negated_inclusions $(if $(RULESETS),--rulesets $(RULESETS),)

property: venv-check
	@PYTHONPATH=libs:services:. $(PY) -c "import hypothesis" 2>/dev/null || echo "property: WARNING hypothesis is not installed: its tests skip (T-737, D-463)" >&2
	TB_ENV=DEV TB_TZ=Asia/Taipei PYTHONPATH=libs:services:. $(PY) -m pytest -q -n 0 -rs -k "property or test_safety_properties" $(PROPERTY_TESTS)

# the `differential` gate of plan §7.5 (T-711, D-480): the boundary table (ages on the birthday and 29 February,
# window ends, the day boundary, units, impossible values, derived scores) through the Python reference, the generated
# SQL and CQL; exit 1 on a disagreement. Needs a JDK and the local CQL engine (python -m tools.cql_eval --fetch).
differential: venv-check
	TB_ENV=DEV TB_TZ=Asia/Taipei PYTHONPATH=libs:services:. $(PY) -m tools.boundary_check $(DIFFERENTIAL_ARGS)

# the pure tests alone (ENG-028, T-653): the tests marked nodb (tests/conftest.py PURE_MODULES), with no PostgreSQL
# at all: TB_PG_BIN points nowhere and TB_TEST_DB_URL is unset, so a test that needs a database fails at once
test-pure: venv-check
	@mkdir -p "$(TB_TEST_ROOT)"
	env -u TB_TEST_DB_URL TB_PG_BIN=/nonexistent TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m pytest -q \
		-n $(PYTEST_N) -m "nodb and not integration and not e2e and not llm and not perf"

# the guard tests (D-1119): the files marked `guard` (pytestmark), static readers of the tree that need no database
# and no service, the way the last step of the CI `checks` job runs them on every tier (no PostgreSQL, two workers)
guard: venv-check
	env -u TB_TEST_DB_URL TB_PG_BIN=/nonexistent TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m pytest -q -n 2 \
		-m guard tests/unit

# card 10G-22 (D-1325): the MedTxt ja pair gate on the recorded answers (eval/medtxt/gate.json names the candidate);
# no model, no network. CI runs it as the guard test tests/unit/test_medtxt_pair_gate.py (the `checks` job, every tier)
.PHONY: medtxt-gate
medtxt-gate: venv-check
	$(PY) -m tools.medtxt_gate check

# the data-handling scan (D-203, WS-13.10, TB-SITE-03): every tracked file, or SCAN="paths", or SCAN="--log f.log";
# exit 2 on a hit (place and pattern only, never the value). The same scan is the pre-commit hook and a CI job.
data-scan:
	$(PY) -m tools.data_scan $(SCAN)

# the security scans of CI job `security` (T-654): secrets over every tracked file, bandit over the Python code;
# reviewed findings in tools/security_scan_ignores.yaml. Exit 1 on a finding no ignore accepts.
security-scan:
	$(PY) -m tools.security_scan secrets
	$(PY) -m tools.security_scan sast

# 10G-42 (b), D-1344: the fifteen SQL-from-strings rules (tools/sql_rules.py) over services/, libs/ and deploy/,
# report-only: the hits, the reviewed ones (tools/sql_rules_ledger.yaml) and the open findings, written to
# build/sql-rules.json; exit 0 (SQL_RULES_CHECK=1 adds --check: exit 1 on a new hit or a stale ledger line)
.PHONY: sql-rules
sql-rules:
	PYTHONPATH=libs:services:. $(PY) -m tools.sql_rules --json build/sql-rules.json $(if $(SQL_RULES_CHECK),--check,)

# the weekly report-only bandit run (10G-39, D-1338; .github/workflows/trialbox-bandit-weekly.yml): every tracked .py,
# no severity or confidence filter, --ignore-nosec; SARIF, JSON and a summary in build/bandit-weekly. Gates nothing.
.PHONY: bandit-weekly
bandit-weekly:
	$(PY) -m tools.bandit_weekly --out build/bandit-weekly

# the CI gate's jobs, in the order of .github/workflows/trialbox-ci.yml (D-206): lint, types, docs, contracts, trace,
# unit (+ the scan of its log), e2e-simple, goldens, data-scan, security, shell, images (if hadolint is installed); then the
# offline supply-chain checks (lock-check, allowlist-check; `make supply-chain` is trialbox-supply-chain.yml). Stops at
# the first failing job. Not here: the `standards` job (Maven and the FHIR registries) and the coverage ratchet.
CI_LOG ?= $(TB_TEST_ROOT)/unit.log
ci: venv-check
	$(PY) -m ruff check . && $(PY) -m ruff format --check .
	$(PY) -m mypy libs services tools tests
	$(PY) tools/doclint.py
	PYTHONPATH=libs:services:. $(PY) -m tools.decisions_index --check
	$(PY) -m tools.findings_register --check
	$(PY) -m tools.inline_suppressions --check
	$(PY) -m tools.vex check  # D-1339: every vulnerability waiver with an owner, a date and a reason (no calendar rule)
	PYTHONPATH=libs:services:. $(PY) -m tools.licence_register --check
	$(MAKE) contracts-check
	TB_ENV=DEV TB_TZ=Asia/Taipei PYTHONPATH=libs:services:. $(PY) -m tools.build_rulesets --check
	$(PY) tools/gen_traceability.py --check  # warnings only (D-311)
	@mkdir -p "$(TB_TEST_ROOT)"
	set -o pipefail; $(MAKE) test 2>&1 | tee "$(CI_LOG)"
	$(PY) -m tools.data_scan --log "$(CI_LOG)"
	$(MAKE) property
	$(MAKE) e2e-simple
	$(MAKE) goldens-check
	$(MAKE) data-scan
	$(MAKE) security-scan
	git ls-files -z '*.sh' | xargs -0 shellcheck --severity=warning  # OPS-076: warnings gate, as in CI
	@if command -v hadolint >/dev/null; then hadolint --failure-threshold warning deploy/docker/python.Dockerfile deploy/docker/backup.Dockerfile deploy/docker/jvm.Dockerfile demo/Dockerfile; else echo "ci: images: hadolint not installed, skipped"; fi
	$(MAKE) lock-check allowlist-check

HL7_ENV := TB_HL7_VALIDATOR_JAR=$(CURDIR)/.cache/jvm/validator_cli.jar TB_FHIR_PACKAGE_HOME=$(CURDIR)/.cache/jvm/fhir-home

test-integration:
	$(HL7_ENV) TB_INTEGRATION=1 $(PY) -m pytest -q tests/integration

# the build gate (FR-OPS-11, D-111): one synthetic hospital, criteria -> report -> list -> mail -> REDCap -> log.
# Stub model, no network, no secrets; about 75 s on one laptop core.
# The root is marked first (a fresh TB_TEST_ROOT holding only e2e-simple/ and no marker is refused by pglocal), and the
# tool names a missing CQL translator jar (FHIRHelpers) at once (`make jvm-deps`) instead of failing late (DATA-019).
E2E_DIR ?= $(TB_TEST_ROOT)/e2e-simple
e2e-simple:
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	TB_ENV=DEV PYTHONPATH=libs:services:. $(PY) -m tools.e2e_simple --dir $(E2E_DIR) --json $(E2E_DIR).json

# the committed goldens (T-006, D-205): the merge gate for every data-core branch. Profile ci (5,450 synthetic and
# public patients, fixed site key): both lake sources side by side, about 2.5 minutes; TB_LAKE_SOURCE=omop (or legacy)
# checks one source only.
# A deliberate change: make goldens REASON="why the numbers move" in the same pull request (any text, D-311).
# T-202: with one source (TB_LAKE_SOURCE set, the CI matrix) no parent process marks the root; mark it first, as
# e2e-simple does (a TB_TEST_ROOT holding files and no marker is refused)
goldens-check:
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	TB_ENV=DEV PYTHONPATH=libs:services:. $(PY) -m tools.goldens --check --profile ci

goldens:
	TB_ENV=DEV PYTHONPATH=libs:services:. $(PY) -m tools.goldens --write --profile ci --reason "$(REASON)"

# TB-PLAN-04 step 2 (D-126): the box runs the path, is backed up, wiped and restored, and must be the same box
DRILL_DIR ?= $(TB_TEST_ROOT)/backup-drill
backup-drill:
	TB_ENV=DEV PYTHONPATH=libs:services:. $(PY) -m tools.backup_drill --dir $(DRILL_DIR)

# one-command demo (D-111): seed and check the step 1-4 flow, then serve the console on 127.0.0.1:8080
demo:
	TB_ENV=DEV PYTHONPATH=libs:services:. $(PY) -m tools.demo

# the same as one image file for the demo VM (docs/RUNBOOK.md §11): dist/trialbox-demo.tar.gz
# T-501: the jar the compiler reads FHIRHelpers from comes from jvm-deps (the Dockerfile fetches it on a fresh clone)
demo-bundle: jvm-deps vocab-bundle-check
	docker build $(CA_SECRET) $(NO_CACHE_ARG) -f demo/Dockerfile -t trialbox-demo:step5 .
	mkdir -p dist && docker save trialbox-demo:step5 | gzip > dist/trialbox-demo.tar.gz
	@ls -l dist/trialbox-demo.tar.gz

test-e2e:
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	TB_INTEGRATION=1 $(PY) -m pytest -q -m e2e

# the nightly compose job (ENG-017, T-653; trialbox-e2e.yml): with `make up-test` running, every test marked
# the Real-MedNLP MedTxt test collection (NTCIR-16, CC BY 4.0, Sociocom NAIST, 1.4 MB), fetched once into .cache/medtxt and
# never committed. The eval, the medtxt gate and the public-medtxt scenario need it (the negative and suspicious tags).
# The public-data site and `tools.public_e2e` no longer do: they read the JMED-LLM datasets committed under
# eval/medtxt/jmed-llm (D-639; #639 7116467086). The corpus host is not reachable from the CI runner.
public-data:
	PYTHONPATH=libs:services:. $(PY) -c "import tools.medtxt_eval as m; m.fetch(); print('public-data: MedTxt in', m.CACHE)"

# integration or e2e (HAPI CQL and the equivalence gate against HAPI, the compose data, the database image, mail
# through GreenMail and Mailpit, the role walk) except the egress test (root and nftables: `make test-egress`) and the
# console POC (`make poc`, `make test-console-e2e`) and the steps-mode walks (`make test-walks`). TB_STRICT_SKIPS=1: a
# skipped test fails, so a missing stack, browser or jar never passes for green. COMPOSE_JUNIT names the junit file.
COMPOSE_JUNIT ?= $(TB_TEST_ROOT)/compose-junit.xml
test-compose:
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	$(HL7_ENV) TB_INTEGRATION=1 TB_STRICT_SKIPS=1 PYTHONPATH=libs:services:. $(PY) -m pytest -q \
		-m "(integration or e2e) and not egress" --junitxml "$(COMPOSE_JUNIT)" \
		--ignore tests/e2e/test_console_poc.py $(addprefix --ignore ,$(WALK_TESTS)) tests/integration tests/e2e

# 9i-1: the five steps-mode walks. Each module starts its own local box (tools.demo on pglocal; no compose stack) and
# took 8 to 19 minutes on 2026-11-19, 63 in all: in the compose job they ran it past its 90 minutes. The nightly runs
# them in its `walks` job, one module per runner (WALK_TEST); nothing may skip. WALKS_JUNIT names the junit file.
WALK_TESTS := tests/e2e/test_new_study_walk.py tests/e2e/test_life_cycle_walk.py tests/e2e/test_life_cycle_walk_390.py \
	tests/e2e/test_phone_walk.py tests/e2e/test_module_walks.py
WALK_TEST ?= $(WALK_TESTS)
WALKS_JUNIT ?= $(TB_TEST_ROOT)/walks-junit.xml
.PHONY: test-walks
test-walks:
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	$(HL7_ENV) TB_INTEGRATION=1 TB_STRICT_SKIPS=1 TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m pytest -q -m e2e \
		--junitxml "$(WALKS_JUNIT)" $(WALK_TEST)

# the browser walk of the public console (tools/public_walk.js: 5 roles x 3 languages x desktop and phone, axe-core,
# 44 px targets, tap counts) on the stub, as the complete run's walk part; needs Node Playwright with Chromium
# (NODE_PATH, or /opt/node-tools). WALK_DIR keeps the result and the screenshots.
WALK_DIR ?= $(TB_TEST_ROOT)/walk
walk:
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	TB_ENV=DEV PYTHONPATH=libs:services:. $(PY) -m tools.complete_run part walk --dir "$(WALK_DIR)" \
		--shots "$(WALK_DIR)/shots"

# H-31 (D-1109): the failure drill on the compose test stack (tools/failure_drill.py): each service killed in turn
# during a night's work, then the database, then a full data volume; no lost job, no double mail, an intact audit
# chain. Needs Docker and `make images`; brings its own stack up and down for each target (about 75 minutes in all).
# Not in test-compose: it kills the stack's parts. DRILL_OUT keeps one record per target and the raw records.
DRILL_OUT ?= build/failure-drill
.PHONY: failure-drill
failure-drill:
	TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m tools.failure_drill run --out "$(DRILL_OUT)"

# H-10 (D-1121): a new study from its first step, in Chromium, on a local box in steps mode (D-1062: tools/demo.py,
# demo mode off, the stub model), once per language; about 7 minutes of seed, then about 70 s per language.
# TB_WALK_ACCOUNTS, TB_WALK_BASE, TB_WALK_PASSWORD, TB_WALK_ID: tests/e2e/test_new_study_walk.py
.PHONY: walk-new-study
walk-new-study:
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	TB_INTEGRATION=1 TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m pytest -q -m e2e tests/e2e/test_new_study_walk.py

# H-20 (D-1135): the whole life of a study on a local steps-mode box, four roles, three languages; reports findings
.PHONY: walk-life-cycle
walk-life-cycle:
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	TB_INTEGRATION=1 TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m pytest -q -m e2e tests/e2e/test_life_cycle_walk.py

# H-32 (D-1110): plant the seven faults of plan 8's V17 on the in-process box, one at a time, and record the first
# page, the mail, /metrics and the runbook as a person meets them (as root the backup target and the disk are mounts)
.PHONY: planted-faults
planted-faults:
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	TB_INTEGRATION=1 TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m pytest -q -m integration tests/e2e/test_planted_faults.py

# H-29 (D-1103): one walk per module H-10 and H-20 do not cover (feasibility, safety, monitoring, amendment) on a local
# steps-mode box, the roles that use each, three languages; reports findings. walk-<module> walks one module
# H-35 (D-1101): every stated limit at the limit, one over and far over, on the in-process box; reports, fixes nothing
.PHONY: limits-edge
limits-edge:
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	TB_INTEGRATION=1 TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m pytest -q -m e2e -n 0 tests/e2e/test_limits_edge_box.py

.PHONY: walk-modules walk-feasibility walk-safety walk-monitoring walk-amendment
walk-modules:
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	TB_INTEGRATION=1 TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m pytest -q -m e2e tests/e2e/test_module_walks.py

walk-feasibility walk-safety walk-monitoring walk-amendment:
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	TB_INTEGRATION=1 TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m pytest -q -m e2e tests/e2e/test_module_walks.py -k "$(@:walk-%=%)"

# H-21 (D-1138): the same walk on a phone 390 px wide; reports what does not fit (screenshots outside the repository)
.PHONY: walk-life-cycle-390
walk-life-cycle-390:
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	TB_INTEGRATION=1 TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m pytest -q -m e2e tests/e2e/test_life_cycle_walk_390.py

# H-34 (D-1100): imperfect hospital data (cut-off files, the same file twice, wrong column counts, Big5, ROC and
# placeholder dates, a long note, unknown codes, chart numbers, empty exports, line endings) through the box's own
# `adapter run`, in every source format the adapter reads; reports and fixes nothing. Results in
# $(TB_TEST_ROOT)/imperfect-feed/results.json; TABLE=1 prints the page's table. About two minutes
.PHONY: imperfect-feed
imperfect-feed:
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	rm -rf "$(TB_TEST_ROOT)/imperfect-feed"
	TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m tools.imperfect_feed --out "$(TB_TEST_ROOT)/imperfect-feed" \
		$(if $(TABLE),--table,)

# root + nftables + iproute2 + the running test stack (docs/SECURITY.md §2)
test-egress:
	TB_EGRESS_TEST=1 $(PY) -m pytest -q -m egress tests/integration/test_egress.py

deploy/.env:
	cp .env.example deploy/.env && chmod 600 deploy/.env

jvm-deps:
	tools/fetch_jvm_deps.sh
	@touch $(JVM_DEPS)

# PLATFORM=linux/arm64: one platform other than this machine's (emulated off an arm64 host), as
# docker-compose.gb10.yml names it; unset, this machine's own
PLATFORM ?=
PLATFORM_ARG := $(if $(PLATFORM),--platform $(PLATFORM),)
# H-70: every Dockerfile uses RUN --mount, which needs BuildKit: without the buildx plugin `docker build` falls back to
# the legacy builder and stops with "the --mount option requires BuildKit". Say so before anything is fetched.
buildx-check:
	@docker buildx version >/dev/null 2>&1 || { echo "images: Docker's buildx plugin is missing (docker buildx version failed); install docker-buildx-plugin (Docker's packages) or docker-buildx (Ubuntu's), then run make again" >&2; exit 1; }

# H-143: the Debian security-upgrade layer (python.Dockerfile, demo/Dockerfile) is unpinned, so a warm cache keeps
# an older day's libraries (the bench's bundle at c3a5b2b2: libzstd1 in trialbox-py, -backup, -jvm and -embed).
# Dev builds keep the cache. `make release-images` (and so `make release-bundle`, ahead of its gates) first pulls
# every outside base the Dockerfiles pin by digest, then builds every image with --no-cache and without --pull:
# --pull would send the FROM of trialbox-py (backup, jvm, embed) to a registry, where it is not. The gates then hold
# each image to deploy/images.lock security_floors (tools/supply_chain/floors.py).
RELEASE_DOCKERFILES := deploy/docker/python.Dockerfile deploy/docker/backup.Dockerfile deploy/docker/jvm.Dockerfile \
	deploy/docker/embed.Dockerfile deploy/docker/db.Dockerfile demo/Dockerfile
RELEASE_BASES = $(sort $(shell grep -hoE '[a-z0-9./_-]+:[^ @"]*@sha256:[0-9a-f]{64}' $(RELEASE_DOCKERFILES)))
NO_CACHE_ARG = $(if $(RELEASE_NO_CACHE),--no-cache,)
release-images:
	for b in $(RELEASE_BASES); do docker pull $(PLATFORM_ARG) "$$b" || exit 1; done
	$(MAKE) images demo-bundle RELEASE_NO_CACHE=1

images: buildx-check jvm-deps $(FONTS)
	docker build $(PLATFORM_ARG) $(BUILD_ARGS) $(CA_SECRET) $(OCI_LABELS) $(NO_CACHE_ARG) \
		--build-arg TB_REVISION=$(TB_REVISION) -f deploy/docker/python.Dockerfile -t trialbox-py:1.0.0 .
	docker build $(PLATFORM_ARG) $(BUILD_ARGS) $(CA_SECRET) $(OCI_LABELS) $(NO_CACHE_ARG) \
		-f deploy/docker/backup.Dockerfile -t trialbox-backup:1.0.0 .
	docker build $(PLATFORM_ARG) $(OCI_LABELS) $(NO_CACHE_ARG) -f deploy/docker/jvm.Dockerfile -t trialbox-jvm:1.0.0 .
	docker build $(PLATFORM_ARG) $(BUILD_ARGS) $(CA_SECRET) $(OCI_LABELS) $(NO_CACHE_ARG) \
		-f deploy/docker/embed.Dockerfile -t trialbox-embed:1.0.0 .
	deploy/build_db_image.sh $(PLATFORM_ARG) $(OCI_LABELS) $(NO_CACHE_ARG)  # the db build of deploy/poc.sh too (card 24-2)

# ENG-003 (D-563): a PRODUCTION box starts its embed service. The box's compose file, the trialbox-embed image,
# TB_ENV=PRODUCTION, a tiny model made on the spot (no download), pinned by the installer's own call; one
# sentence embedded. Needs Docker and `make images`. CI: the image gates' job and the nightly compose job.
embed-start:
	TB_INTEGRATION=1 TB_STRICT_SKIPS=1 TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m pytest -q -n 0 \
		-p no:cacheprovider -m integration tests/integration/test_embed_production_start.py

# both architectures (x86_64 servers, GB10 aarch64); push to the site registry or export with --output type=oci
PLATFORMS ?= linux/amd64,linux/arm64
REGISTRY ?= localhost:5000
images-multiarch: buildx-check jvm-deps $(FONTS)
	docker buildx build --platform $(PLATFORMS) $(BUILD_ARGS) $(CA_SECRET) $(OCI_LABELS) \
		--build-arg TB_REVISION=$(TB_REVISION) -f deploy/docker/python.Dockerfile -t $(REGISTRY)/trialbox-py:1.0.0 --push .
	docker buildx build --platform $(PLATFORMS) $(BUILD_ARGS) $(CA_SECRET) $(OCI_LABELS) \
		--build-arg BASE_IMAGE=$(REGISTRY)/trialbox-py:1.0.0 -f deploy/docker/backup.Dockerfile \
		-t $(REGISTRY)/trialbox-backup:1.0.0 --push .
	docker buildx build --platform $(PLATFORMS) $(OCI_LABELS) --build-arg BASE_IMAGE=$(REGISTRY)/trialbox-py:1.0.0 \
		-f deploy/docker/jvm.Dockerfile -t $(REGISTRY)/trialbox-jvm:1.0.0 --push .
	docker buildx build --platform $(PLATFORMS) $(BUILD_ARGS) $(CA_SECRET) $(OCI_LABELS) \
		--build-arg BASE_IMAGE=$(REGISTRY)/trialbox-py:1.0.0 -f deploy/docker/embed.Dockerfile \
		-t $(REGISTRY)/trialbox-embed:1.0.0 --push .
	docker buildx build --platform $(PLATFORMS) $(BUILD_ARGS) $(CA_SECRET) $(OCI_LABELS) -f deploy/docker/db.Dockerfile \
		-t $(REGISTRY)/trialbox-postgres:16-1 --push deploy/docker

# the GB10 two-device form (T-214, D-373): each device's rendered compose against deploy/gb10-profile.yaml (what runs
# where, the link the only listener on the Spark, the memory limits), the profile's own checks, and the link selftest
# in the built image (mutual TLS 1.3: a round trip, then an unauthenticated peer, another CA and an unknown route
# refused). CI and the bench: TB_LINK_ADDR and TB_LINK_PEER from the shell, else documentation addresses (RFC 5737),
# never deploy/.env's. On a device, `python -m tools.trialbox doctor --two-device` checks its own configuration.
TWO_DEVICE_DIR ?= build/two-device
TB_LINK_ADDR ?= 192.0.2.10
TB_LINK_PEER ?= 192.0.2.11
TWO_DEVICE_ENV := TB_LINK_ADDR=$(TB_LINK_ADDR) TB_LINK_PEER=$(TB_LINK_PEER)
SPARK_SERVICES := gateway model-guard llm-service llm-verifier link
WORKSTATION_SERVICES := db fhir-store lake embed-service doc-parser criteria-compiler adapter orchestrator mail-gateway \
	console audit-writer link
two-device-check: deploy/.env
	mkdir -p $(TWO_DEVICE_DIR)
	$(TWO_DEVICE_ENV) $(COMPOSE) -f deploy/docker-compose.secrets.yml -f deploy/docker-compose.gb10.yml \
		-f deploy/two-device/docker-compose.spark.yml --profile gpu config --format json $(SPARK_SERVICES) \
		> $(TWO_DEVICE_DIR)/spark.json
	$(TWO_DEVICE_ENV) $(COMPOSE) -f deploy/docker-compose.secrets.yml -f deploy/two-device/docker-compose.workstation.yml \
		config --format json $(WORKSTATION_SERVICES) > $(TWO_DEVICE_DIR)/workstation.json
	$(PY) -m tools.two_device profile
	$(PY) -m tools.two_device check --role spark --compose-config $(TWO_DEVICE_DIR)/spark.json
	$(PY) -m tools.two_device check --role workstation --compose-config $(TWO_DEVICE_DIR)/workstation.json
	docker run --rm --network none $(PLATFORM_ARG) trialbox-py:1.0.0 python -m tools.two_device selftest

up: deploy/.env
	$(COMPOSE) --profile stub up -d --wait

.cache/test-secrets/site_hmac.key:
	install -d -m 0777 .cache/test-secrets
	printf 'trialbox-test-site-key-0123456789abcdef' > $@ && chmod 0644 $@

$(TEST_SETTINGS): deploy/settings.example.yaml
	install -d .cache
	sed 's/^rate_limit_per_sender_per_day: .*/rate_limit_per_sender_per_day: 1000/' $< > $@

# D-972: the test stack's object folder (bind-mounted, D-121) and its buckets (tb_common.objstore.BUCKETS), open to
# the services (uid 10001) and to the host's integration tests (the runner's user): a bucket the services made first
# (mode 755) refused the host test its job folder. Synthetic test objects only; no box uses this folder.
OBJECTS_DIR ?= deploy/.objects
OBJECTS_BUCKETS := attachments outputs rulesets lake twpas
objects-dir:
	@mkdir -p $(addprefix $(OBJECTS_DIR)/,$(OBJECTS_BUCKETS))
	@chmod 0777 $(OBJECTS_DIR) $(addprefix $(OBJECTS_DIR)/,$(OBJECTS_BUCKETS)) || { \
	  echo "objects-dir: cannot open $(OBJECTS_DIR) to the services and the tests (an earlier stack made it as" \
	       "another user): remove it (sudo rm -rf $(OBJECTS_DIR)) and run again" >&2; exit 1; }

up-test: deploy/.env .cache/test-secrets/site_hmac.key $(TEST_SETTINGS)
	$(MAKE) --no-print-directory objects-dir OBJECTS_DIR=$(CURDIR)/deploy/.objects && $(COMPOSE_TEST) up -d --wait

# load synthetic site A into the running test stack (adapter -> lake + FHIR store)
ingest-test:
	$(PY) -m tests.stack

down:
	$(COMPOSE_TEST) down

logs:
	$(COMPOSE_TEST) logs --tail=100

fixtures:
	$(PY) tools/make_fixtures.py --out tests/fixtures/synthetic_patients

# ANCHOR=<folder>: also against every signed head kept there (NEW-STD-2, D-562): a removed and recomputed event fails
ANCHOR ?=
audit-verify:
	$(PY) tools/audit_verify.py $${TB_AUDIT_DIR:-data/audit} $(if $(ANCHOR),--heads "$(ANCHOR)",)

bench:
	$(PY) tools/bench.py

# the performance regression gate (ENG-030, T-653; nightly): the stub at BENCH_PATIENTS against
# tools/bench_baseline.json, exit 1 when a phase is more than 20 % slower; `make bench-baseline` rewrites the baseline
# (in the pull request that changes the speed on purpose, with the reason in the commit)
BENCH_PATIENTS ?= 5000
BENCH_OUT ?= $(TB_TEST_ROOT)/bench-gate
# BENCH_REF=<file>: the baseline's reference commit measured on this runner (`make bench-baseline` in a checkout of it,
# the copy of its tools/bench_baseline.json): the gate is then on the ratio to it. The nightly sets it when the runner's
# CPU model is not the one the baseline was written on (`tools/bench.py --cpu-differs`)
BENCH_REF ?=
bench-gate:
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) tools/bench.py --gate --patients $(BENCH_PATIENTS) --out "$(BENCH_OUT)" \
		$(if $(BENCH_REF),--ref "$(BENCH_REF)",)

# D-1245 (10E-13): the console's ten-page timing walk (p95 of the Server-Timing header under 300 ms; marker perf, nightly
# in trialbox-e2e.yml's perf-5k job). The walk's rules and the planted slow page are tests/console/test_console_timing.py
CONSOLE_TIMING_OUT ?= $(TB_TEST_ROOT)/console-timing
console-timing: venv-check
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	TB_CONSOLE_TIMING_OUT="$(CONSOLE_TIMING_OUT)" $(PY) -m pytest -q -n 0 -m perf \
		--basetemp "$(TB_TEST_ROOT)/console-timing-pytest" tests/perf/test_console_timing_walk.py

bench-baseline:
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) tools/bench.py --gate --write-baseline --patients $(BENCH_PATIENTS) \
		--out "$(BENCH_OUT)"

# open data (docs/VALIDATION.md §5): fetch the PhysioNet MIMIC-IV FHIR demo (sha256-verified, not committed), then
# adapter -> lake -> FEAS in process for the two ClinicalTrials.gov rulesets; writes .cache/open_data/report.{json,md}
open-data-e2e:
	$(PY) tools/fetch_open_data.py
	PYTHONPATH=libs:services:. $(PY) tools/open_data_e2e.py

testbench:
	TB_ENV=DEV PYTHONPATH=libs:services:. $(PY) -m tools.testbench --host 127.0.0.1 --port $${TB_TESTBENCH_PORT:-8765}

testbench-test:
	TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m pytest -q tests/testbench

eval-public:
	PYTHONPATH=libs:services:. $(PY) -m tools.trialbox eval judge_public
	PYTHONPATH=libs:services:. $(PY) -m tools.trialbox eval ingest_fhir_demo

e2e-cascade:
	TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m tools.cascade_e2e --source tests/fixtures/synthetic_patients/site-a --trial $${TB_E2E_TRIAL:-GZQO} --out $${TB_E2E_OUT:-build/e2e}

# full stack end to end on one box (docs/RUNBOOK.md "DGX Spark end to end"): GB10 + vLLM + pinned local model by
# default; TB_LLM_MODE=stub on any Docker host without a GPU. One PASS/FAIL report under build/spark-e2e/.
spark-e2e:
	PY=$(PY) tools/spark_e2e.sh

# model robustness (survey 2026-11-07): re-check pinned weights; run the 54-question canary inside the orchestrator
verify-models:
	PYTHONPATH=libs:services:. $(PY) -m tools.pin_model --verify-all deploy/models

# W-1: fetch a GPU profile's pinned weights into deploy/models (or TB_MODELS_DIR), verified file by file against the
# pin record (models/registry.yaml and the measured record it names); runs only when asked, never at install or start.
# GPU=rtxpro6000 by default; ARGS=--dry-run (no network) or ARGS=--verify-only. Without make (no venv needed):
# python3 -m tools.fetch_weights --profile rtxpro6000
GPU ?= rtxpro6000
fetch-weights:
	$(if $(wildcard $(PY)),$(PY),python3) -m tools.fetch_weights --profile $(GPU) $(ARGS)

# the pair canary in the box with the box's own compose files (COMPOSE_FILE in deploy/.env; OPS-033). On a box
# without make: `sudo python3 -m tools.trialbox selftest`
selftest:
	python3 -m tools.trialbox selftest --deploy deploy

# the same 54-case canary from this checkout against the models in the environment (TB_GATEWAY_URL ...): each model,
# then the pair as the box decides (both must give the same decided answer); exit 1 when it fails (D-115). The box
# runs it itself at start, nightly and from the admin Models tile; a passing pair is what lets a note answer exclude
# (D-117). Two servers directly: ARGS="--judge-url http://<vm>/judge/v1 --verifier-url http://<vm>/verifier/v1 --swap"
canary:
	PYTHONPATH=libs:services:. $(PY) -m tools.canary $(ARGS)

# proof of concept in one command (README "Try the POC in 10 minutes", RUNBOOK §9): box + GreenMail/Mailpit + admin
# console with the pilot workspace; TB_LLM_MODE=stub|openrouter|gpu. Windows: deploy/poc.ps1.
poc:
	deploy/poc.sh up

poc-down:
	deploy/poc.sh down

poc-status:
	deploy/poc.sh status

# the gate before any site's installation qualification (D-176, docs/RUNBOOK.md §16): offline media -> the real
# install.sh --tier large in a clean Ubuntu 24.04 container, strict vLLM stand-ins for the GPU (tools/vllm_standin.py)
rehearse-box:
	PY=$(PY) tools/rehearse_box/rehearse.sh

# H-22 (D-1136): the install runbook (RUNBOOK hub + §1) followed alone, beside the box rehearsal: the rehearsal's clean
# Ubuntu host image, a site bundle made the vendor's way, the box images cleared; records time, commands and findings
# and compares them with docs/plan/measurements/runbook-install-2026-11-17/findings.json. Needs make images, trivy-db
runbook-install:
	PYTHONPATH=libs:services:. $(PY) -m tools.runbook_install run --py $(PY) \
		$(if $(TB_EXTRA_CA),--extra-ca $(TB_EXTRA_CA),) $(RUNBOOK_INSTALL_ARGS)

# H-33 (D-1122): the compose test stack (stub model, synthetic site A) does a night's work, is backed up as RUNBOOK §5
# says, has every volume wiped and is restored by §5's restore page alone, timed; every store is then compared with
# its fingerprint from before. Root, Docker and `make images` (the box's own images); about 10 minutes. The record
# (no secret, no row) goes to RESTORE_DRILL_OUT; docs/plan/measurements/restore-drill-2026-11-18.md reads it.
RESTORE_DRILL_OUT ?= $(TB_TEST_ROOT)/restore-drill/run.json
.PHONY: restore-drill
restore-drill:
	TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m tools.restore_drill run --out "$(RESTORE_DRILL_OUT)" \
		--work "$(TB_TEST_ROOT)/restore-drill/work"

# H-145 (#1504): the console tests run as `make test` runs the unit suite: the same marked TB_TEST_ROOT and its lock,
# the xdist workers with --dist worksteal, TMPDIR and basetemp under the root. TB_STRICT_SKIPS=1 (tests/conftest.py):
# a browser file that cannot start node or Chromium fails with its reason, it never turns the stage green by skipping.
# The lead's bench (#1504): a run under nohup (SIGHUP ignored) is refused, since its workers, servers and browsers
# would outlive a closed session; so is a root that group or others can write into, or that lies under such a folder
# without the sticky bit (pglocal mark closes the folders this user owns; this refuses the ones it cannot close).
test-console: venv-check test-console-preflight
	@flock -n -E 75 "$(TB_TEST_ROOT)/.lock" $(MAKE) --no-print-directory test-console-locked; rc=$$?; \
	if [ $$rc = 75 ]; then echo "test-console: $(TB_TEST_ROOT) is in use by another run: give this run its own TB_TEST_ROOT" >&2; fi; exit $$rc

.PHONY: test-console-preflight
test-console-preflight:
	@case "$$(sed -n 's/^SigIgn:[[:space:]]*//p' /proc/$$$$/status)" in *[13579bdfBDF]) \
		echo "test-console: SIGHUP is ignored (nohup?): run it in a session that can end it" >&2; exit 1;; esac
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	@d="$(TB_TEST_ROOT)"; while :; do m=$$(stat -L -c %A "$$d") || exit 1; \
		case "$$m" in ?????w????|????????w?) case "$$m" in *[tT]) ;; *) \
			echo "test-console: $$d ($$m) can be written by others: give TB_TEST_ROOT a parent only you can write" >&2; \
			exit 1;; esac;; esac; [ "$$d" = / ] && break; d=$$(dirname "$$d"); done

.PHONY: test-console-locked
test-console-locked:
	@rm -rf "$(TB_TEST_ROOT)/tmp" && mkdir -m 0700 -p "$(TB_TEST_ROOT)/tmp"
	TB_STRICT_SKIPS=1 TB_ENV=TEST TMPDIR="$(TB_TEST_ROOT)/tmp" PYTHONPATH=libs:services:. $(PY) -m pytest -q -n $(PYTEST_N) $(XDIST_DIST) \
		--basetemp "$(TB_TEST_ROOT)/pytest" tests/console; rc=$$?; \
	rm -rf "$(TB_TEST_ROOT)/tmp"; PYTHONPATH=libs:services:. $(PY) -m tools.pglocal stop-idle "$(TB_TEST_ROOT)/pglocal"; \
	if [ $$rc = 0 ]; then rm -rf "$(TB_TEST_ROOT)/pytest"; fi; exit $$rc

# browser + e-mail end to end against the running POC (make poc first): Playwright (Node) drives the console
test-console-e2e:
	TB_INTEGRATION=1 TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m pytest -q -m e2e tests/e2e/test_console_poc.py

site:
	$(PY) tools/build_site.py

site-preview: site
	$(PY) -m http.server -d build/site 8000

# supply chain (docs/SECURITY.md §8, D-185, D-186). uv.lock is the one hashed lock; deploy/requirements.lock is its
# export, installed by the images in pip's hash-checking mode. The gates read the scanners' JSON and the allow-list.
SC := PYTHONPATH=libs:services:. $(PY) -m tools.supply_chain
SC_DIR ?= build/supply-chain
SCANNERS := $(CURDIR)/.cache/scanners/bin
TRIVY_CACHE ?= .cache/trivy
# every image a bundle carries: ours (make images, make demo-bundle) and the third-party images compose pulls,
# the same list tools/make_bundle.sh exports
SC_OWN_IMAGES ?= trialbox-py:1.0.0 trialbox-backup:1.0.0 trialbox-jvm:1.0.0 trialbox-embed:1.0.0 trialbox-postgres:16-1 trialbox-demo:step5
# The identity overlay too (Caddy, Authelia; D-574): make_bundle.sh puts it in every bundle, and an image the gates
# never saw cannot pass bundle-check. Its host name is a placeholder here, as there: only the images are read.
SC_THIRD_PARTY ?= $(shell TB_TLS_HOSTNAME=bundle.invalid TB_TZ=$${TB_TZ:-UTC} docker compose --project-directory deploy \
	-f deploy/docker-compose.yml -f deploy/docker-compose.test.yml -f deploy/docker-compose.identity.yml \
	--profile stub --profile test --profile gpu --profile oidc config --images 2>/dev/null | grep -v '^trialbox-' | sort -u)
# the third-party images are scanned in their registry, by digest, for this machine's platform (or SC_PLATFORM)
SC_PLATFORM ?= linux/$(if $(filter aarch64 arm64,$(shell uname -m)),arm64,amd64)
# third-party images published for amd64 only (named here so nothing is skipped silently; tracked in
# deploy/security/known-image-findings.md): left out of the arm64 gates, and a GB10 bundle cannot carry them. None
# since D-348 (Mailpit replaced MailHog; every deploy/images.lock third_party entry has a linux/arm64 build)
SC_AMD64_ONLY ?=
SC_PLATFORM_IMAGES = $(if $(filter linux/arm64%,$(SC_PLATFORM)),$(foreach i,$(SC_THIRD_PARTY),$(if \
	$(filter $(addsuffix :%,$(SC_AMD64_ONLY)) $(addsuffix @%,$(SC_AMD64_ONLY)),$(i)),,$(i))),$(SC_THIRD_PARTY))
SC_IMAGES ?= $(SC_OWN_IMAGES) $(foreach i,$(SC_PLATFORM_IMAGES),registry:$(i)=$(SC_PLATFORM))

lock:
	uv lock
	$(SC) lock-export
	uv pip compile -q --no-config --generate-hashes --universal --python-version 3.12 \
		tools/supply_chain/pip-audit.in -o tools/supply_chain/pip-audit.lock

lock-check:
	$(SC) lock-check

allowlist-check:
	$(SC) allowlist-check

# Syft, Trivy and Dockle release archives with pinned sha256 (tools/supply_chain/scanners.py) into .cache/scanners/bin
scanners:
	$(SC) scanners --dest .cache/scanners

# an environment installed from the hashed lock alone (what the images install), for the lock's SBOM
lock-env:
	uv venv -q --allow-existing --python 3.12 .cache/lock-env
	uv pip install -q --no-config --python .cache/lock-env/bin/python --require-hashes --only-binary :all: \
		-r deploy/requirements.lock

# build side only (needs PyPI/OSV); the box never runs it. pip-audit itself comes from a hashed lock and runs on
# Python 3.12, so the lock's markers are judged as on the box. It exits 1 on any advisory; the gate decides
# (allow-list, audited set = the lock), and fails on a missing report, so an old report is removed first.
pip-audit:
	uv venv -q --allow-existing --python 3.12 .cache/pip-audit-env
	uv pip install -q --no-config --python .cache/pip-audit-env/bin/python --require-hashes \
		-r tools/supply_chain/pip-audit.lock
	mkdir -p $(SC_DIR) && rm -f $(SC_DIR)/pip-audit.json
	-.cache/pip-audit-env/bin/pip-audit -r deploy/requirements.lock --require-hashes --disable-pip \
		-f json -o $(SC_DIR)/pip-audit.json
	$(SC) pip-audit-gate $(SC_DIR)/pip-audit.json

# the lock's SBOM (Syft over the environment installed from the lock: licences from the installed metadata)
lock-sbom: scanners lock-env
	PATH=$(SCANNERS):$$PATH $(SC) lock-sbom --env .cache/lock-env --out dist/sbom/requirements.lock.cdx.json

licences: lock-sbom
	$(SC) licences dist/sbom/*.cdx.json --out dist/sbom/licences.md

# Trivy DB into $(TRIVY_CACHE), the only online Trivy step (on the media: oras pull of trivy-db:2 and trivy-java-db:1)
trivy-db: scanners
	$(SCANNERS)/trivy image --download-db-only --cache-dir $(TRIVY_CACHE) --skip-version-check
	$(SCANNERS)/trivy image --download-java-db-only --cache-dir $(TRIVY_CACHE) --skip-version-check

# the release gates: each image pinned (a local one by image id, registry:REF=os/arch by digest), then offline
# Trivy, Syft SBOM, licences, one record (build/supply-chain/gates.json, dist/sbom/index.json). Needs make trivy-db.
# under `make release-bundle` the gates wait for release-images (the images they scan); alone they scan what is there
release-gates: lock-sbom sc-images $(if $(filter release-bundle,$(MAKECMDGOALS)),release-images,)
	PATH=$(SCANNERS):$$PATH $(SC) release-gates --cache-dir $(TRIVY_CACHE) --out $(SC_DIR) --sbom-dir dist/sbom \
		--lock-sbom dist/sbom/requirements.lock.cdx.json $(RELEASE_GATES_ARGS) $(foreach i,$(SC_IMAGES),--image $(i))

# the images the gates will scan; fails when compose gave no third-party image (no docker, or a broken config),
# so a release is never gated on our images alone by accident
# SC_LOCAL_IMAGES=1: a caller that names local images on purpose (the box rehearsal, the demo VM drill; T-110b)
sc-images: deploy/.env
	@printf '%s\n' $(SC_IMAGES)
	@[ -n "$(SC_LOCAL_IMAGES)" ] || case " $(SC_IMAGES) " in *" registry:"*) ;; \
		*) echo "sc-images: no third-party images (docker compose config gave none)" >&2; exit 1 ;; esac

# card 22-4 (root review 22): no row of a vocabulary the licence register classes c (must not ship) in a shipped
# terminology artefact (tables, maps, value sets) or in VOCAB_BUNDLE_PATHS; make_bundle.sh checks what it stages
# beside the images itself (rule-set zips, reference data packs, the models folder)
VOCAB_BUNDLE_PATHS ?=
vocab-bundle-check:
	PYTHONPATH=libs:services:. $(PY) -m tools.vocab_bundle_check --tree $(VOCAB_BUNDLE_PATHS)

# D-1343 (10G-41, review 21 OT-3): every Dockerfile under trialbox/ is linted by hadolint. HADOLINT_GATING are the
# three the CI `images` job gates on at warning since D-206 (unchanged); HADOLINT_REPORT are linted report-only
# (`make hadolint-report`, the CI job's report step: findings in the job summary and artifact, never a failure)
# until their findings are closed (D-1343). tests/unit/test_image_config_scans.py holds the two lists, the CI job
# and the tree as one set. No hadolint ignore is added for them (no scan allow-list entry).
HADOLINT_GATING := deploy/docker/python.Dockerfile deploy/docker/jvm.Dockerfile demo/Dockerfile
HADOLINT_REPORT := deploy/docker/backup.Dockerfile deploy/docker/embed.Dockerfile deploy/docker/db.Dockerfile \
	deploy/redcap-test/Dockerfile tools/rehearse_box/host.Dockerfile tools/bench_ci/runner.Dockerfile
HADOLINT_IMAGE := hadolint/hadolint:v2.12.0@sha256:30a8fd2e785ab6176eed53f74769e04f125afb2f74a6c52aef7d463583b6d45e
# each image of SC_OWN_IMAGES and the Dockerfile it is built from
IMAGE_SCAN_IMAGES ?= trialbox-py:1.0.0=deploy/docker/python.Dockerfile trialbox-backup:1.0.0=deploy/docker/backup.Dockerfile \
	trialbox-jvm:1.0.0=deploy/docker/jvm.Dockerfile trialbox-embed:1.0.0=deploy/docker/embed.Dockerfile \
	trialbox-postgres:16-1=deploy/docker/db.Dockerfile trialbox-demo:step5=demo/Dockerfile
IMAGE_SCAN_DIR ?= build/image-scan
# three tools per image (hadolint on its Dockerfile, Trivy secret+misconfig, Dockle) and `trivy config` over the
# Dockerfile folders; JSON and summary.md in IMAGE_SCAN_DIR. Report-only (exit 0) until the date in D-1343, then
# IMAGE_SCAN_ARGS="--fail-at HIGH". Needs Docker, `make images` and the demo image (trialbox-images.yml builds them).
.PHONY: image-scan
image-scan: scanners
	PATH=$(SCANNERS):$$PATH $(SC) image-scan --out $(IMAGE_SCAN_DIR) --cache-dir $(TRIVY_CACHE) \
		--hadolint-image $(HADOLINT_IMAGE) $(foreach i,$(IMAGE_SCAN_IMAGES),--image $(i)) \
		--config-dir deploy/docker --config-dir demo $(IMAGE_SCAN_ARGS)

# D-1343: hadolint on HADOLINT_REPORT, report-only (exit 0 whatever it finds; the hadolint image by digest, Docker).
HADOLINT_REPORT_OUT ?= build/hadolint-report.txt
.PHONY: hadolint-report
hadolint-report:
	@mkdir -p $(dir $(HADOLINT_REPORT_OUT)); : > $(HADOLINT_REPORT_OUT)
	@for f in $(HADOLINT_REPORT); do echo "== $$f" >> $(HADOLINT_REPORT_OUT); \
		docker run --rm -i $(HADOLINT_IMAGE) hadolint --no-fail - < "$$f" >> $(HADOLINT_REPORT_OUT) 2>&1 \
		|| echo "hadolint did not run on $$f" >> $(HADOLINT_REPORT_OUT); done
	@cat $(HADOLINT_REPORT_OUT)

# a bundle only from images that passed the gates (make_bundle.sh needs --gates, T-110b); the SBOMs of dist/sbom ride
# inside it with release.json. BUNDLE_ARGS="--key ... --id ... --release-seq N --out ..."
# 10G-9 (D-1239): no release bundle while the public security contact (deploy/security/contact.json) is not set; a
# --rehearsal or --allow-dirty bundle, which is no release, passes with a warning
release-bundle: security-contact-check release-images release-gates vocab-bundle-check
	tools/make_bundle.sh --gates $(SC_DIR)/gates.json --sbom-dir dist/sbom $(BUNDLE_ARGS)

# OPS-006 (D-966): the offline media of a bare Ubuntu box from a signed bundle and the packages of
# `python3 -m tools.linux_media debs` (online, run apart); sign it on the signing machine (tools.linux_media sign)
#   make media-linux MEDIA_ARGS="--version 1.0.0 --bundle dist/trialbox-1.0.0.tar --debs debs/ --vendor-pub keys/vendor_ed25519.pub"
media-linux:
	PYTHONPATH=libs:. $(PY) -m tools.linux_media build --out dist/media --measured deploy/measured $(MEDIA_ARGS)

security-contact-check:
	PYTHONPATH=libs:. $(PY) -m tools.security_contact release-check $(BUNDLE_ARGS)

# the release version (pyproject.toml, the one place) and its tag (T-110b)
release-version:
	@PYTHONPATH=libs:services:. $(PY) -m tools.release version
release-tag:
	@PYTHONPATH=libs:services:. $(PY) -m tools.release tag

# what CI runs on every pull request (no images needed)
supply-chain: lock-check allowlist-check pip-audit licences

# the cloud run's local rehearsal (D-150): the real driver and VM script against stand-ins, US$0, about an hour.
# The gate before any paid GPU launch (docs/RUNBOOK.md §11); CASES="run-a served" runs some cases only.
rehearse:
	tests/rehearsal/rehearse.sh $(CASES)

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build *.egg-info

# rc1 line 1: the whole test set (unit, integration, e2e, goldens, the GPU suites) three runs in a row, a log per stage
# per run, a summary (tools/full_set.py). FULL_SET_ARGS: --out DIR --llm-url URL --llm-model NAME, --only, --list
FULL_SET_ARGS ?=
.PHONY: full-set
full-set: venv-check
	PYTHONPATH=libs:services:. $(PY) -m tools.full_set $(FULL_SET_ARGS)
