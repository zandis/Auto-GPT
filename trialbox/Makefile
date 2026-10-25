# TrialBox developer entry points. Python targets use .venv (create with `make venv`).
SHELL := /bin/bash
PY ?= .venv/bin/python
COMPOSE := docker compose --project-directory deploy -f deploy/docker-compose.yml
# the test stack uses the example settings with a high per-sender limit: e2e suites run many times a day
TEST_SETTINGS := .cache/test-settings.yaml
COMPOSE_TEST := TB_SETTINGS_FILE=../$(TEST_SETTINGS) $(COMPOSE) -f deploy/docker-compose.test.yml --profile stub --profile test
BUILD_ARGS := $(if $(HTTPS_PROXY),--network host --build-arg HTTPS_PROXY=$(HTTPS_PROXY) --build-arg https_proxy=$(HTTPS_PROXY),)
comma := ,
# test-stack host ports moved in deploy/.env reach every tool and test run from make (the shell environment wins)
HOST_PORTS := $(shell grep -hE '^TB_HOST_[A-Z_]+_PORT=[0-9]+$$' deploy/.env 2>/dev/null)
$(foreach v,$(HOST_PORTS),$(eval export $(subst =, ?= ,$(v))))
CA_SECRET := $(if $(TB_EXTRA_CA),--secret id=extra_ca$(comma)src=$(TB_EXTRA_CA),)


.PHONY: fonts jvm-deps venv contracts contracts-check lint test test-unit test-integration test-e2e test-egress images images-multiarch up up-test ingest-test down logs fixtures audit-verify bench open-data-e2e testbench testbench-test eval-public e2e-cascade spark-e2e poc poc-down poc-status poc-hermes poc-hermes-down test-hermes-e2e test-console test-console-e2e site site-preview clean

venv:
	uv venv --allow-existing --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"

contracts:
	$(PY) tools/gen_contracts.py

contracts-check:
	$(PY) tools/gen_contracts.py --check
	PYTHONPATH=libs:services:. $(PY) -m tb_contracts.criterion_ir --check

lint: contracts-check
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
	$(PY) -m mypy libs services tools tests integrations
	PYTHONPATH=libs:services:. $(PY) -m tools.mcp_snapshot --check

FONTS := .cache/fonts/NotoSansTC-Regular.ttf

$(FONTS):
	$(PY) tools/fetch_fonts.py

fonts: $(FONTS)

test: $(FONTS)
	$(PY) -m pytest -q -m "not integration and not e2e and not llm and not perf"

HL7_ENV := TB_HL7_VALIDATOR_JAR=$(CURDIR)/.cache/jvm/validator_cli.jar TB_FHIR_PACKAGE_HOME=$(CURDIR)/.cache/jvm/fhir-home

test-integration:
	$(HL7_ENV) TB_INTEGRATION=1 $(PY) -m pytest -q tests/integration

test-e2e:
	TB_INTEGRATION=1 $(PY) -m pytest -q -m e2e

# root + nftables + iproute2 + the running test stack (docs/HARDENING.md §3)
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
	$(COMPOSE_TEST) up -d --wait

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

# open data (docs/OPEN_DATA.md): fetch the PhysioNet MIMIC-IV FHIR demo (sha256-verified, not committed), then
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

# proof of concept in one command (README "Try the POC in 10 minutes", RUNBOOK §9): box + GreenMail/MailHog + admin
# console with the pilot workspace; TB_LLM_MODE=stub|openrouter|gpu. Windows: deploy/poc.ps1.
poc:
	deploy/poc.sh up

poc-down:
	deploy/poc.sh down

poc-status:
	deploy/poc.sh status

# Hermes serving through channel-relay and frontdoor-mcp on the running POC (spec v4 §9; make poc first)
poc-hermes:
	deploy/hermes/up.sh up

poc-hermes-down:
	deploy/hermes/up.sh down

# Hermes end to end against the running POC + Hermes fragment (make poc-hermes first)
test-hermes-e2e:
	TB_INTEGRATION=1 TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m pytest -q -m e2e tests/e2e/test_hermes_relay.py

test-console:
	TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m pytest -q tests/console

# browser + e-mail end to end against the running POC (make poc first): Playwright (Node) drives the console
test-console-e2e:
	TB_INTEGRATION=1 TB_ENV=TEST PYTHONPATH=libs:services:. $(PY) -m pytest -q -m e2e tests/e2e/test_console_poc.py

site:
	$(PY) tools/build_site.py

site-preview: site
	$(PY) -m http.server -d build/site 8000

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build *.egg-info
