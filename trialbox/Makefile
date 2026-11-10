# TrialBox developer entry points. Python targets use .venv (create with `make venv`).
SHELL := /bin/bash
PY ?= .venv/bin/python
COMPOSE := docker compose --project-directory deploy -f deploy/docker-compose.yml
# the test stack uses the example settings with a high per-sender limit: e2e suites run many times a day
TEST_SETTINGS := .cache/test-settings.yaml
COMPOSE_TEST := TB_HOST_OBJECTS_DIR=$(CURDIR)/deploy/.objects TB_SETTINGS_FILE=../$(TEST_SETTINGS) $(COMPOSE) -f deploy/docker-compose.test.yml --profile stub --profile test
BUILD_ARGS := $(if $(HTTPS_PROXY),--network host --build-arg HTTPS_PROXY=$(HTTPS_PROXY) --build-arg https_proxy=$(HTTPS_PROXY),)
comma := ,
# test-stack host ports moved in deploy/.env reach every tool and test run from make (the shell environment wins)
HOST_PORTS := $(shell grep -hE '^TB_HOST_[A-Z_]+_PORT=[0-9]+$$' deploy/.env 2>/dev/null)
$(foreach v,$(HOST_PORTS),$(eval export $(subst =, ?= ,$(v))))
CA_SECRET := $(if $(TB_EXTRA_CA),--secret id=extra_ca$(comma)src=$(TB_EXTRA_CA),)


.PHONY: rehearse fonts jvm-deps venv venv-check clean-tmp check-disk data-scan ci e2e-simple backup-drill demo demo-bundle contracts contracts-check lint test test-unit test-integration test-e2e test-egress images images-multiarch up up-test ingest-test down logs fixtures audit-verify bench open-data-e2e testbench testbench-test eval-public e2e-cascade spark-e2e verify-models selftest canary poc poc-down poc-status test-console test-console-e2e site site-preview clean

# ------------------------------------------------------------------ parallel work on one machine (D-201, RUNBOOK §12)
# Every temporary root of a run derives from TB_TEST_ROOT: one per branch, under TB_SCRATCH (an agent's scratchpad;
# default /var/tmp/trialbox-<uid>), never a fixed /tmp path that every agent on the machine shares.
BRANCH_SLUG := $(shell git rev-parse --abbrev-ref HEAD 2>/dev/null | sed 's/[^A-Za-z0-9._-]\{1,\}/-/g; s/^[-.]*//; s/[-.]*$$//' | cut -c1-40)
TB_SCRATCH ?= /var/tmp/trialbox-$(shell id -u)
TB_TEST_ROOT ?= $(TB_SCRATCH)/tb-tests-$(or $(BRANCH_SLUG),detached)
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
	@$(UV_SYNC) --check >/dev/null 2>&1 || { echo "venv-check: .venv differs from uv.lock (a package installed by hand?): run 'make venv'" >&2; exit 1; }

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

# TMPDIR too lives under TB_TEST_ROOT, so tempfile.mkdtemp() in a test never lands in the shared /tmp. Afterwards:
# TMPDIR is emptied, the branch's shared cluster (pglocal.for_work) stopped, and a green run's basetemp removed.
test: venv-check $(FONTS)
	@PYTHONPATH=libs:services:. $(PY) -c 'import os, pathlib, tools.pglocal as p; p.check_test_root(pathlib.Path(os.environ["TB_TEST_ROOT"]))'
	@rm -rf "$(TB_TEST_ROOT)/tmp" && mkdir -p "$(TB_TEST_ROOT)/tmp"
	TMPDIR="$(TB_TEST_ROOT)/tmp" $(PY) -m pytest -q -n $(PYTEST_N) --basetemp "$(TB_TEST_ROOT)/pytest" \
		-m "not integration and not e2e and not llm and not perf"; rc=$$?; \
	rm -rf "$(TB_TEST_ROOT)/tmp"; PYTHONPATH=libs:services:. $(PY) -m tools.pglocal stop "$(TB_TEST_ROOT)/pglocal"; \
	if [ $$rc = 0 ]; then rm -rf "$(TB_TEST_ROOT)/pytest"; fi; exit $$rc

# the data-handling scan (D-203, WS-13.10, TB-SITE-03): every tracked file, or SCAN="paths", or SCAN="--log f.log";
# exit 2 on a hit (place and pattern only, never the value). The same scan is the pre-commit hook and a CI job.
data-scan:
	$(PY) -m tools.data_scan $(SCAN)

# the CI gate's jobs, in the order of .github/workflows/trialbox-ci.yml (D-205): lint, types, docs, contracts, trace,
# unit (+ the scan of its log), e2e-simple, goldens, audit (listed, not gating), data-scan, shell, images (if hadolint
# is installed). Stops at the first failing job.
CI_LOG ?= $(TB_TEST_ROOT)/unit.log
ci: venv-check
	$(PY) -m ruff check . && $(PY) -m ruff format --check .
	$(PY) -m mypy libs services tools tests
	$(PY) tools/doclint.py
	$(MAKE) contracts-check
	$(PY) tools/gen_traceability.py --check
	@mkdir -p "$(TB_TEST_ROOT)"
	set -o pipefail; $(MAKE) test 2>&1 | tee "$(CI_LOG)"
	$(PY) -m tools.data_scan --log "$(CI_LOG)"
	$(MAKE) e2e-simple
	@if $(MAKE) -n goldens-check >/dev/null 2>&1; then $(MAKE) goldens-check; else echo "ci: goldens: no goldens-check target until T-006 lands"; fi
	-uv export --frozen --group test --extra dev --no-emit-project --no-hashes > "$(TB_TEST_ROOT)/requirements.txt" && \
		uvx pip-audit@2.9.0 --disable-pip --no-deps -r "$(TB_TEST_ROOT)/requirements.txt"
	$(MAKE) data-scan
	git ls-files -z '*.sh' | xargs -0 shellcheck --severity=error
	@if command -v hadolint >/dev/null; then hadolint --failure-threshold warning deploy/docker/python.Dockerfile deploy/docker/jvm.Dockerfile demo/Dockerfile || true; else echo "ci: images: hadolint not installed, skipped"; fi

HL7_ENV := TB_HL7_VALIDATOR_JAR=$(CURDIR)/.cache/jvm/validator_cli.jar TB_FHIR_PACKAGE_HOME=$(CURDIR)/.cache/jvm/fhir-home

test-integration:
	$(HL7_ENV) TB_INTEGRATION=1 $(PY) -m pytest -q tests/integration

# the build gate (FR-OPS-11, D-111): one synthetic hospital, criteria -> report -> list -> mail -> REDCap -> log.
# Stub model, no network, no secrets; about 75 s on one laptop core.
E2E_DIR ?= $(TB_TEST_ROOT)/e2e-simple
e2e-simple:
	TB_ENV=DEV PYTHONPATH=libs:services:. $(PY) -m tools.e2e_simple --dir $(E2E_DIR) --json $(E2E_DIR).json

# TB-PLAN-04 step 2 (D-126): the box runs the path, is backed up, wiped and restored, and must be the same box
DRILL_DIR ?= $(TB_TEST_ROOT)/backup-drill
backup-drill:
	TB_ENV=DEV PYTHONPATH=libs:services:. $(PY) -m tools.backup_drill --dir $(DRILL_DIR)

# one-command demo (D-111): seed and check the step 1-4 flow, then serve the console on 127.0.0.1:8080
demo:
	TB_ENV=DEV PYTHONPATH=libs:services:. $(PY) -m tools.demo

# the same as one image file for the demo VM (docs/RUNBOOK.md §11): dist/trialbox-demo.tar.gz
demo-bundle:
	docker build $(CA_SECRET) -f demo/Dockerfile -t trialbox-demo:step5 .
	mkdir -p dist && docker save trialbox-demo:step5 | gzip > dist/trialbox-demo.tar.gz
	@ls -l dist/trialbox-demo.tar.gz

test-e2e:
	TB_INTEGRATION=1 $(PY) -m pytest -q -m e2e

# root + nftables + iproute2 + the running test stack (docs/SECURITY.md §2)
test-egress:
	TB_EGRESS_TEST=1 $(PY) -m pytest -q -m egress tests/integration/test_egress.py

deploy/.env:
	cp .env.example deploy/.env && chmod 600 deploy/.env

jvm-deps:
	tools/fetch_jvm_deps.sh

images: jvm-deps $(FONTS)
	docker build $(BUILD_ARGS) $(CA_SECRET) -f deploy/docker/python.Dockerfile -t trialbox-py:1.0.0 .
	docker build -f deploy/docker/jvm.Dockerfile -t trialbox-jvm:1.0.0 .

# both architectures (x86_64 servers, GB10 aarch64); push to the site registry or export with --output type=oci
PLATFORMS ?= linux/amd64,linux/arm64
REGISTRY ?= localhost:5000
images-multiarch: jvm-deps $(FONTS)
	docker buildx build --platform $(PLATFORMS) $(BUILD_ARGS) $(CA_SECRET) -f deploy/docker/python.Dockerfile \
		-t $(REGISTRY)/trialbox-py:1.0.0 --push .
	docker buildx build --platform $(PLATFORMS) --build-arg BASE_IMAGE=$(REGISTRY)/trialbox-py:1.0.0 \
		-f deploy/docker/jvm.Dockerfile -t $(REGISTRY)/trialbox-jvm:1.0.0 --push .

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

selftest:
	docker compose --project-directory deploy -f deploy/docker-compose.yml exec orchestrator python -m orchestrator.selftest

# the same 54-case canary from this checkout against the models in the environment (TB_GATEWAY_URL ...): each model,
# then the pair as the box decides (both must give the same decided answer); exit 1 when it fails (D-115). The box
# runs it itself at start, nightly and from the admin Models tile; a passing pair is what lets a note answer exclude
# (D-117). Two servers directly: ARGS="--judge-url http://<vm>/judge/v1 --verifier-url http://<vm>/verifier/v1 --swap"
canary:
	PYTHONPATH=libs:services:. $(PY) -m tools.canary $(ARGS)

# proof of concept in one command (README "Try the POC in 10 minutes", RUNBOOK §9): box + GreenMail/MailHog + admin
# console with the pilot workspace; TB_LLM_MODE=stub|openrouter|gpu. Windows: deploy/poc.ps1.
poc:
	deploy/poc.sh up

poc-down:
	deploy/poc.sh down

poc-status:
	deploy/poc.sh status

test-console:
	TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m pytest -q tests/console

# browser + e-mail end to end against the running POC (make poc first): Playwright (Node) drives the console
test-console-e2e:
	TB_INTEGRATION=1 TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m pytest -q -m e2e tests/e2e/test_console_poc.py

site:
	$(PY) tools/build_site.py

site-preview: site
	$(PY) -m http.server -d build/site 8000

# the cloud run's local rehearsal (D-150): the real driver and VM script against stand-ins, US$0, about an hour.
# The gate before any paid GPU launch (docs/RUNBOOK.md §11); CASES="run-a served" runs some cases only.
rehearse:
	tests/rehearsal/rehearse.sh $(CASES)

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build *.egg-info
