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


.PHONY: security-scan goldens goldens-check rehearse fonts jvm-deps venv venv-check clean-tmp check-disk data-scan ci test-locked test-random test-random-locked test-pure test-compose walk bench-gate bench-baseline e2e-simple backup-drill demo demo-bundle contracts contracts-check lint test test-unit test-integration test-e2e test-egress images images-multiarch two-device-check up up-test ingest-test down logs fixtures audit-verify bench open-data-e2e testbench testbench-test eval-public e2e-cascade spark-e2e verify-models selftest canary poc poc-down poc-status rehearse-box test-console test-console-e2e site site-preview clean \
	lock lock-check allowlist-check scanners lock-env pip-audit lock-sbom licences trivy-db sc-images release-gates release-bundle supply-chain release-version release-tag

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
UV_SYNC := uv sync --frozen --group test --extra dev --python 3.12

# .venv is exactly uv.lock (the test plugins included): `uv sync` removes whatever was installed by hand, and a uv
# venv has no pip, so `pip install` into it is refused. `make test` refuses a venv that drifted from the lock.
venv:
	$(UV_SYNC)

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
	@rm -rf "$(TB_TEST_ROOT)/tmp" && mkdir -p "$(TB_TEST_ROOT)/tmp"
	TB_TEST_RANDOM=1 TMPDIR="$(TB_TEST_ROOT)/tmp" uv run --frozen --no-sync --with "$(RANDOMLY)" $(NO_NETWORK) \
		python -m pytest -p randomly $(if $(RANDOM_SEED),--randomly-seed=$(RANDOM_SEED),) $(NO_NETWORK_ARGS) \
		-n $(PYTEST_N) --basetemp "$(TB_TEST_ROOT)/pytest" -m "not integration and not e2e and not llm and not perf"; rc=$$?; \
	rm -rf "$(TB_TEST_ROOT)/tmp"; PYTHONPATH=libs:services:. $(PY) -m tools.pglocal stop-idle "$(TB_TEST_ROOT)/pglocal"; \
	if [ $$rc = 0 ]; then rm -rf "$(TB_TEST_ROOT)/pytest"; fi; exit $$rc

test-locked:
	@rm -rf "$(TB_TEST_ROOT)/tmp" && mkdir -p "$(TB_TEST_ROOT)/tmp"
	TMPDIR="$(TB_TEST_ROOT)/tmp" $(PY) -m pytest -q -n $(PYTEST_N) --basetemp "$(TB_TEST_ROOT)/pytest" \
		-m "not integration and not e2e and not llm and not perf"; rc=$$?; \
	rm -rf "$(TB_TEST_ROOT)/tmp"; PYTHONPATH=libs:services:. $(PY) -m tools.pglocal stop-idle "$(TB_TEST_ROOT)/pglocal"; \
	if [ $$rc = 0 ]; then rm -rf "$(TB_TEST_ROOT)/pytest"; fi; exit $$rc

# the pure tests alone (ENG-028, T-653): the tests marked nodb (tests/conftest.py PURE_MODULES), with no PostgreSQL
# at all: TB_PG_BIN points nowhere and TB_TEST_DB_URL is unset, so a test that needs a database fails at once
test-pure: venv-check
	env -u TB_TEST_DB_URL TB_PG_BIN=/nonexistent TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m pytest -q \
		-n $(PYTEST_N) -m "nodb and not integration and not e2e and not llm and not perf"

# the data-handling scan (D-203, WS-13.10, TB-SITE-03): every tracked file, or SCAN="paths", or SCAN="--log f.log";
# exit 2 on a hit (place and pattern only, never the value). The same scan is the pre-commit hook and a CI job.
data-scan:
	$(PY) -m tools.data_scan $(SCAN)

# the security scans of CI job `security` (T-654): secrets over every tracked file, bandit over the Python code;
# reviewed findings in tools/security_scan_ignores.yaml. Exit 1 on a finding no ignore accepts.
security-scan:
	$(PY) -m tools.security_scan secrets
	$(PY) -m tools.security_scan sast

# the CI gate's jobs, in the order of .github/workflows/trialbox-ci.yml (D-206): lint, types, docs, contracts, trace,
# unit (+ the scan of its log), e2e-simple, goldens, data-scan, security, shell, images (if hadolint is installed); then the
# offline supply-chain checks (lock-check, allowlist-check; `make supply-chain` is trialbox-supply-chain.yml). Stops at
# the first failing job.
CI_LOG ?= $(TB_TEST_ROOT)/unit.log
ci: venv-check
	$(PY) -m ruff check . && $(PY) -m ruff format --check .
	$(PY) -m mypy libs services tools tests
	$(PY) tools/doclint.py
	$(MAKE) contracts-check
	$(PY) tools/gen_traceability.py --check  # warnings only (D-311)
	@mkdir -p "$(TB_TEST_ROOT)"
	set -o pipefail; $(MAKE) test 2>&1 | tee "$(CI_LOG)"
	$(PY) -m tools.data_scan --log "$(CI_LOG)"
	$(MAKE) e2e-simple
	$(MAKE) goldens-check
	$(MAKE) data-scan
	$(MAKE) security-scan
	git ls-files -z '*.sh' | xargs -0 shellcheck --severity=error
	@if command -v hadolint >/dev/null; then hadolint --failure-threshold warning deploy/docker/python.Dockerfile deploy/docker/jvm.Dockerfile demo/Dockerfile || true; else echo "ci: images: hadolint not installed, skipped"; fi
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
demo-bundle: jvm-deps
	docker build $(CA_SECRET) -f demo/Dockerfile -t trialbox-demo:step5 .
	mkdir -p dist && docker save trialbox-demo:step5 | gzip > dist/trialbox-demo.tar.gz
	@ls -l dist/trialbox-demo.tar.gz

test-e2e:
	TB_INTEGRATION=1 $(PY) -m pytest -q -m e2e

# the nightly compose job (ENG-017, T-653; trialbox-e2e.yml): with `make up-test` running, every test marked
# integration or e2e (HAPI CQL and the equivalence gate against HAPI, the compose data, the database image, mail
# through GreenMail and MailHog, the role walk) except the egress test (root and nftables: `make test-egress`) and the
# console POC (`make poc`, `make test-console-e2e`). TB_STRICT_SKIPS=1: a skipped test fails, so a missing stack,
# browser or jar never passes for green. COMPOSE_JUNIT names the junit file.
COMPOSE_JUNIT ?= $(TB_TEST_ROOT)/compose-junit.xml
test-compose:
	$(HL7_ENV) TB_INTEGRATION=1 TB_STRICT_SKIPS=1 PYTHONPATH=libs:services:. $(PY) -m pytest -q \
		-m "(integration or e2e) and not egress" --junitxml "$(COMPOSE_JUNIT)" \
		--ignore tests/e2e/test_console_poc.py tests/integration tests/e2e

# the browser walk of the public console (tools/public_walk.js: 5 roles x 3 languages x desktop and phone, axe-core,
# 44 px targets, tap counts) on the stub, as the complete run's walk part; needs Node Playwright with Chromium
# (NODE_PATH, or /opt/node-tools). WALK_DIR keeps the result and the screenshots.
WALK_DIR ?= $(TB_TEST_ROOT)/walk
walk:
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	TB_ENV=DEV PYTHONPATH=libs:services:. $(PY) -m tools.complete_run part walk --dir "$(WALK_DIR)" \
		--shots "$(WALK_DIR)/shots"

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
images: jvm-deps $(FONTS)
	docker build $(PLATFORM_ARG) $(BUILD_ARGS) $(CA_SECRET) $(OCI_LABELS) --build-arg TB_REVISION=$(TB_REVISION) \
		-f deploy/docker/python.Dockerfile -t trialbox-py:1.0.0 .
	docker build $(PLATFORM_ARG) $(OCI_LABELS) -f deploy/docker/jvm.Dockerfile -t trialbox-jvm:1.0.0 .
	docker build $(PLATFORM_ARG) $(BUILD_ARGS) $(CA_SECRET) $(OCI_LABELS) -f deploy/docker/db.Dockerfile \
		-t trialbox-postgres:16-1 deploy/docker

# both architectures (x86_64 servers, GB10 aarch64); push to the site registry or export with --output type=oci
PLATFORMS ?= linux/amd64,linux/arm64
REGISTRY ?= localhost:5000
images-multiarch: jvm-deps $(FONTS)
	docker buildx build --platform $(PLATFORMS) $(BUILD_ARGS) $(CA_SECRET) $(OCI_LABELS) \
		--build-arg TB_REVISION=$(TB_REVISION) -f deploy/docker/python.Dockerfile -t $(REGISTRY)/trialbox-py:1.0.0 --push .
	docker buildx build --platform $(PLATFORMS) $(OCI_LABELS) --build-arg BASE_IMAGE=$(REGISTRY)/trialbox-py:1.0.0 \
		-f deploy/docker/jvm.Dockerfile -t $(REGISTRY)/trialbox-jvm:1.0.0 --push .
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

up-test: deploy/.env .cache/test-secrets/site_hmac.key $(TEST_SETTINGS)
	mkdir -p deploy/.objects && $(COMPOSE_TEST) up -d --wait

# load synthetic site A into the running test stack (adapter -> lake + FHIR store)
ingest-test:
	$(PY) -m tests.stack

down:
	$(COMPOSE_TEST) down

logs:
	$(COMPOSE_TEST) logs --tail=100

fixtures:
	$(PY) tools/make_fixtures.py --out tests/fixtures/synthetic_patients

audit-verify:
	$(PY) tools/audit_verify.py $${TB_AUDIT_DIR:-data/audit}

bench:
	$(PY) tools/bench.py

# the performance regression gate (ENG-030, T-653; nightly): the stub at BENCH_PATIENTS against
# tools/bench_baseline.json, exit 1 when a phase is more than 20 % slower; `make bench-baseline` rewrites the baseline
# (in the pull request that changes the speed on purpose, with the reason in the commit)
BENCH_PATIENTS ?= 5000
BENCH_OUT ?= $(TB_TEST_ROOT)/bench-gate
bench-gate:
	@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null
	TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) tools/bench.py --gate --patients $(BENCH_PATIENTS) --out "$(BENCH_OUT)"

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

test-console:
	TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m pytest -q tests/console

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
SC_OWN_IMAGES ?= trialbox-py:1.0.0 trialbox-jvm:1.0.0 trialbox-postgres:16-1 trialbox-demo:step5
SC_THIRD_PARTY ?= $(shell docker compose --project-directory deploy -f deploy/docker-compose.yml -f deploy/docker-compose.test.yml \
	--profile stub --profile test --profile gpu config --images 2>/dev/null | grep -v '^trialbox-' | sort -u)
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

# Syft and Trivy release archives with pinned sha256 (tools/supply_chain/scanners.py) into .cache/scanners/bin
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
release-gates: lock-sbom sc-images
	PATH=$(SCANNERS):$$PATH $(SC) release-gates --cache-dir $(TRIVY_CACHE) --out $(SC_DIR) --sbom-dir dist/sbom \
		--lock-sbom dist/sbom/requirements.lock.cdx.json $(RELEASE_GATES_ARGS) $(foreach i,$(SC_IMAGES),--image $(i))

# the images the gates will scan; fails when compose gave no third-party image (no docker, or a broken config),
# so a release is never gated on our images alone by accident
# SC_LOCAL_IMAGES=1: a caller that names local images on purpose (the box rehearsal, the demo VM drill; T-110b)
sc-images: deploy/.env
	@printf '%s\n' $(SC_IMAGES)
	@[ -n "$(SC_LOCAL_IMAGES)" ] || case " $(SC_IMAGES) " in *" registry:"*) ;; \
		*) echo "sc-images: no third-party images (docker compose config gave none)" >&2; exit 1 ;; esac

# a bundle only from images that passed the gates (make_bundle.sh needs --gates, T-110b); the SBOMs of dist/sbom ride
# inside it with release.json. BUNDLE_ARGS="--key ... --id ... --release-seq N --out ..."
release-bundle: release-gates
	tools/make_bundle.sh --gates $(SC_DIR)/gates.json --sbom-dir dist/sbom $(BUNDLE_ARGS)

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
