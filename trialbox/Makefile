# TrialBox developer entry points. Python targets use .venv (create with `make venv`).
SHELL := /bin/bash
PY ?= .venv/bin/python
COMPOSE := docker compose --project-directory deploy -f deploy/docker-compose.yml
COMPOSE_TEST := $(COMPOSE) -f deploy/docker-compose.test.yml --profile stub --profile test
BUILD_ARGS := $(if $(HTTPS_PROXY),--network host --build-arg HTTPS_PROXY=$(HTTPS_PROXY) --build-arg https_proxy=$(HTTPS_PROXY),)
CA_SECRET := $(if $(TB_EXTRA_CA),--secret id=extra_ca$(comma)src=$(TB_EXTRA_CA),)
comma := ,


.PHONY: jvm-deps venv contracts contracts-check lint test test-unit test-integration test-e2e images up up-test down logs fixtures audit-verify bench clean

venv:
	uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"

contracts:
	$(PY) tools/gen_contracts.py

contracts-check:
	$(PY) tools/gen_contracts.py --check

lint: contracts-check
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
	$(PY) -m mypy libs services tools tests

test:
	$(PY) -m pytest -q -m "not integration and not e2e and not llm and not perf"

HL7_ENV := TB_HL7_VALIDATOR_JAR=$(CURDIR)/.cache/jvm/validator_cli.jar TB_FHIR_PACKAGE_HOME=$(CURDIR)/.cache/jvm/fhir-home

test-integration:
	$(HL7_ENV) TB_INTEGRATION=1 $(PY) -m pytest -q tests/integration

test-e2e:
	TB_INTEGRATION=1 $(PY) -m pytest -q -m e2e

deploy/.env:
	cp .env.example deploy/.env && chmod 600 deploy/.env

jvm-deps:
	tools/fetch_jvm_deps.sh

images: jvm-deps
	docker build $(BUILD_ARGS) $(CA_SECRET) -f deploy/docker/python.Dockerfile -t trialbox-py:1.0.0 .
	docker build -f deploy/docker/jvm.Dockerfile -t trialbox-jvm:1.0.0 .

up: deploy/.env
	$(COMPOSE) --profile stub up -d --wait

.cache/test-secrets/site_hmac.key:
	install -d -m 0777 .cache/test-secrets
	printf 'trialbox-test-site-key-0123456789abcdef' > $@ && chmod 0644 $@

up-test: deploy/.env .cache/test-secrets/site_hmac.key
	$(COMPOSE_TEST) up -d --wait

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

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build *.egg-info
