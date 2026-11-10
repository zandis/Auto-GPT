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


.PHONY: fonts jvm-deps venv e2e-simple backup-drill demo demo-bundle contracts contracts-check lint test test-unit test-integration test-e2e test-egress images images-multiarch up up-test ingest-test down logs fixtures audit-verify bench open-data-e2e testbench testbench-test eval-public e2e-cascade spark-e2e verify-models selftest canary poc poc-down poc-status test-console test-console-e2e site site-preview clean \
	lock lock-check allowlist-check scanners lock-env pip-audit lock-sbom licences trivy-db sc-images release-gates release-bundle supply-chain

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
	$(PY) -m mypy libs services tools tests
	$(PY) tools/doclint.py

FONTS := .cache/fonts/NotoSansTC-Regular.ttf

$(FONTS):
	$(PY) tools/fetch_fonts.py

fonts: $(FONTS)

test: $(FONTS)
	$(PY) -m pytest -q -m "not integration and not e2e and not llm and not perf"

HL7_ENV := TB_HL7_VALIDATOR_JAR=$(CURDIR)/.cache/jvm/validator_cli.jar TB_FHIR_PACKAGE_HOME=$(CURDIR)/.cache/jvm/fhir-home

test-integration:
	$(HL7_ENV) TB_INTEGRATION=1 $(PY) -m pytest -q tests/integration

# the build gate (FR-OPS-11, D-111): one synthetic hospital, criteria -> report -> list -> mail -> REDCap -> log.
# Stub model, no network, no secrets; about 75 s on one laptop core.
E2E_DIR ?= /tmp/tb-e2e-simple
e2e-simple:
	TB_ENV=DEV PYTHONPATH=libs:services:. $(PY) -m tools.e2e_simple --dir $(E2E_DIR) --json $(E2E_DIR).json

# TB-PLAN-04 step 2 (D-126): the box runs the path, is backed up, wiped and restored, and must be the same box
DRILL_DIR ?= /tmp/tb-backup-drill
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

# supply chain (docs/SECURITY.md §8, D-185, D-186). uv.lock is the one hashed lock; deploy/requirements.lock is its
# export, installed by the images in pip's hash-checking mode. The gates read the scanners' JSON and the allow-list.
SC := PYTHONPATH=libs:services:. $(PY) -m tools.supply_chain
SC_DIR ?= build/supply-chain
SCANNERS := $(CURDIR)/.cache/scanners/bin
TRIVY_CACHE ?= .cache/trivy
# every image a bundle carries: ours (make images, make demo-bundle) and the third-party images compose pulls,
# the same list tools/make_bundle.sh exports
SC_OWN_IMAGES ?= trialbox-py:1.0.0 trialbox-jvm:1.0.0 trialbox-demo:step5
SC_THIRD_PARTY ?= $(shell docker compose --project-directory deploy -f deploy/docker-compose.yml -f deploy/docker-compose.test.yml \
	--profile stub --profile test --profile gpu config --images 2>/dev/null | grep -v '^trialbox-' | sort -u)
# the third-party images are scanned in their registry, by digest, for this machine's platform (or SC_PLATFORM)
SC_PLATFORM ?= linux/$(if $(filter aarch64 arm64,$(shell uname -m)),arm64,amd64)
SC_IMAGES ?= $(SC_OWN_IMAGES) $(foreach i,$(SC_THIRD_PARTY),registry:$(i)=$(SC_PLATFORM))

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
sc-images: deploy/.env
	@printf '%s\n' $(SC_IMAGES)
	@case " $(SC_IMAGES) " in *" registry:"*) ;; \
		*) echo "sc-images: no third-party images (docker compose config gave none)" >&2; exit 1 ;; esac

# a bundle only from images that passed the gates (make_bundle.sh --gates); BUNDLE_ARGS="--key ... --id ... --out ..."
release-bundle: release-gates
	tools/make_bundle.sh --gates $(SC_DIR)/gates.json $(BUNDLE_ARGS)

# what CI runs on every pull request (no images needed)
supply-chain: lock-check allowlist-check pip-audit licences

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build *.egg-info
