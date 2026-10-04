# TrialBox developer entry points. Python targets use .venv (create with `make venv`).
SHELL := /bin/bash
PY ?= .venv/bin/python
COMPOSE := docker compose --project-directory deploy -f deploy/docker-compose.yml
COMPOSE_TEST := $(COMPOSE) -f deploy/docker-compose.test.yml --profile stub --profile test
BUILD_ARGS := $(if $(HTTPS_PROXY),--network host --build-arg HTTPS_PROXY=$(HTTPS_PROXY) --build-arg https_proxy=$(HTTPS_PROXY),)
CA_SECRET := $(if $(TB_EXTRA_CA),--secret id=extra_ca$(comma)src=$(TB_EXTRA_CA),)
comma := ,

.PHONY: venv contracts contracts-check lint test test-unit test-integration test-e2e images up up-test down logs fixtures audit-verify bench clean

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

test-integration:
	TB_INTEGRATION=1 $(PY) -m pytest -q -m integration

test-e2e:
	TB_INTEGRATION=1 $(PY) -m pytest -q -m e2e

deploy/.env:
	cp .env.example deploy/.env && chmod 600 deploy/.env

images:
	docker build $(BUILD_ARGS) $(CA_SECRET) -f deploy/docker/python.Dockerfile -t trialbox-py:1.0.0 .
	@if [ -f deploy/docker/compiler.Dockerfile ]; then docker build $(BUILD_ARGS) $(CA_SECRET) -f deploy/docker/compiler.Dockerfile -t trialbox-compiler:1.0.0 .; fi

up: deploy/.env
	$(COMPOSE) --profile stub up -d --wait

up-test: deploy/.env
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
