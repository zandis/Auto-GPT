PY ?= .venv/bin/python
MODEL ?= qwen2.5:7b
COHORT ?= sigir
TRIALS ?= NCT06640309,NCT07490522

.PHONY: venv data corpora lint test serve bench bench-slice retrieval h2h-capture h2h cgrd-demo

venv:
	uv venv -p 3.12 .venv && uv pip install -p $(PY) --index-url https://download.pytorch.org/whl/cpu torch && uv pip install -p $(PY) -e ".[dev]"
	$(PY) -c "import nltk; nltk.download('punkt_tab'); nltk.download('punkt')"

data:            ## cohorts from GitHub (or: ZIP=TrialGPT-main.zip make data)
	$(PY) -m trialgpt_local.datasets fetch $(if $(ZIP),--zip $(ZIP),)

corpora:         ## TREC 2021/2022 trial corpora (~260 MB, retrieval only)
	$(PY) -m trialgpt_local.datasets fetch --corpora

lint:
	$(PY) tools/sync_prompts.py --check
	$(PY) -m ruff check . && $(PY) -m ruff format --check .
	$(PY) -m mypy trialgpt_local tests

test:
	$(PY) -m pytest -q

serve:           ## local web interface on http://127.0.0.1:8090
	TG_LLM_MODEL=$(MODEL) $(PY) -m trialgpt_local.app

bench:           ## full ranking benchmark on one cohort (all patients, all labelled trials)
	TG_LLM_MODEL=$(MODEL) $(PY) -m trialgpt_local.benchmark rank --cohort $(COHORT)

bench-slice:     ## quick look: 5 patients x 12 labelled trials
	TG_LLM_MODEL=$(MODEL) $(PY) -m trialgpt_local.benchmark rank --cohort $(COHORT) --patients 5 --trials 12

retrieval:       ## recall@N with keywords from the local model
	TG_LLM_MODEL=$(MODEL) $(PY) -m trialgpt_local.benchmark retrieval --cohort $(COHORT) --keywords local

h2h-capture:     ## trialgpt.app on public synthetic patients (rate-limited)
	$(PY) -m trialgpt_local.h2h.capture --cohort $(COHORT) --patients $(or $(N),20)

h2h:             ## local system on the captured patients, cross-evaluation, pooled workbook, report
	TG_LLM_MODEL=$(MODEL) $(PY) -m trialgpt_local.h2h.compare local
	TG_LLM_MODEL=$(MODEL) $(PY) -m trialgpt_local.h2h.compare crosseval
	$(PY) -m trialgpt_local.h2h.compare workbook
	TG_LLM_MODEL=$(MODEL) $(PY) -m trialgpt_local.h2h.compare report

cgrd-demo:       ## CGRD validation loop on synthetic CGRD-format data
	cd ../trialbox && ../trialgpt/$(PY) -m tools.make_fixtures --out ../trialgpt/data/cgrd_synthetic --sites a
	$(PY) -m trialgpt_local.cgrd.validate select --db data/cgrd_synthetic/site-a/cgrd.sqlite --trials $(TRIALS) --run demo --index-date 2026-10-05
	TG_LLM_MODEL=$(MODEL) $(PY) -m trialgpt_local.cgrd.validate run --run demo
	$(PY) -m trialgpt_local.cgrd.validate workbook --run demo
