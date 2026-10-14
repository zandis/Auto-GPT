# RUNBOOK: TrialGPT, local

Run all commands from `trialgpt/`. `MODEL` is any Ollama tag; output folders are named after it
(`qwen2.5:7b` → `results/qwen2.5-7b/`).

## Quick install on your own PC

One command installs what is missing (git, Ollama, uv), picks a Gemma 4 size from your GPU memory, pulls it, sets
up Python 3.12 and opens the interface at http://127.0.0.1:8090. Run it again to update.

```powershell
# Windows (PowerShell)
irm https://raw.githubusercontent.com/zandis/Auto-GPT/claude/trialgpt-local-lcvm9p/trialgpt/scripts/install.ps1 -OutFile install.ps1
powershell -ExecutionPolicy Bypass -File install.ps1            # -Model gemma4:12b to override
```

```bash
# Linux / WSL / macOS
curl -fsSL https://raw.githubusercontent.com/zandis/Auto-GPT/claude/trialgpt-local-lcvm9p/trialgpt/scripts/install.sh -o install.sh
bash install.sh                                                  # MODEL=gemma4:12b bash install.sh to override
```

Afterwards start it with `start-trialgpt.ps1` / `start-trialgpt.sh` in `~/TrialGPT/trialgpt`. If the repository
is private, git asks you to sign in to GitHub the first time.

| GPU memory | model the installer picks | download | notes |
|---|---|---|---|
| < 6 GB | `gemma4:e2b` | 4.6 GB | try-out only |
| 6–15 GB (RTX 3080 10/12 GB, 4070, …) | `gemma4:e4b` | 6.6 GB | fits with a 16k context |
| ≥ 16 GB | `gemma4:12b` | 8.0 GB | on 10–12 GB it also runs: Ollama moves some layers to the CPU, slower |
| 24 GB+ | pass `gemma4:26b` / `gemma4:31b` yourself | 18.7 / 20.4 GB | |

Sizes are the Ollama registry's (October 2026). Whichever you choose, compare on your own GPU with
`make bench-slice MODEL=...` before trusting it.

## 0. Local LLM (Ollama)

```bash
ollama pull qwen2.5:14b                  # pick for your hardware, see below
export TG_LLM_MODEL=qwen2.5:14b
export TG_LLM_NUM_CTX=16384              # REQUIRED headroom: matching prompts are 2-8k tokens, outputs 1-3k
```

* **Context window.** Ollama's default context is 2048 tokens, and it truncates silently. This client always sends
  `num_ctx` (`TG_LLM_NUM_CTX`, default 16384). When a call fills it, the call raises `ContextOverflow` instead of
  returning a confident answer from half a trial. TREC trials with long criteria lists may need 24576.
* **Model size.** TrialGPT asks for one structured judgement per criterion, which small models do poorly. A 1.5B
  model runs the whole pipeline but parrots the instructions instead of reasoning (seen in this repo's smoke run).
  Use 7B or larger to try it out; 14–32B (qwen2.5, llama3.1/3.3, gemma) or a 70B for numbers you would publish.
  The paper's reference is GPT-4.
* **Thinking models.** Gemma 4, Qwen3 and similar "think" before answering unless told not to: in Ollama a short
  Gemma 4 call took 98–166 s thinking vs 7 s without, for the same JSON. NCBI's prompts already ask for the reasoning
  inside the JSON, so `TG_LLM_THINK` is off by default (`think: false` is sent; models without a thinking mode
  accept it). `TG_LLM_THINK=true` to let them think.
* **Determinism.** temperature 0, `TG_LLM_SEED` (default 42), and `format: json`. Responses are cached on disk by
  request hash (`data/cache/`), so benchmark reruns are free. Interactive and CGRD runs never use the cache.
* **Other servers** (vLLM, llama.cpp server, LM Studio, a hospital gateway): `TG_LLM_BACKEND=openai`
  `TG_LLM_BASE_URL=http://host:port/v1` `TG_LLM_API_KEY=...`.
* **Check:** `curl -s http://127.0.0.1:11434/api/tags`, or the interface header, which shows reachable / model
  available.

| variable | default | |
|---|---|---|
| `TG_LLM_BACKEND` | `ollama` | or `openai` |
| `TG_LLM_BASE_URL` | `http://127.0.0.1:11434` | |
| `TG_LLM_MODEL` | `qwen2.5:7b` | |
| `TG_LLM_NUM_CTX` | `16384` | |
| `TG_LLM_TIMEOUT` | `900` | seconds per call |
| `TG_LLM_THINK` | `false` | let thinking models (gemma4, qwen3) reason before answering: much slower |
| `TG_LLM_MODE` | `live` | `record` / `cassette` for replayable runs |
| `TG_JUDGE_MODEL` | = `TG_LLM_MODEL` | head-to-head cross-evaluation judge |
| `TG_DEVICE` | `cpu` | `cuda` for MedCPT on a GPU |
| `TG_DATA_DIR`, `TG_RESULTS_DIR`, `TG_CACHE_DIR` | `data/`, `results/`, `data/cache/` | |

## 1. Install and data

```bash
make venv                                 # uv + Python 3.12, CPU torch, nltk punkt
make data ZIP=/path/TrialGPT-main.zip     # cohorts from the GitHub zip (or `make data` to clone)
make corpora                              # TREC 2021/2022 trial corpora (~260 MB), only for retrieval / frozen search
make lint test                            # prompt-sync check, ruff, mypy --strict, 17 offline tests
```

`data/ncbi/<cohort>/` gets `queries.jsonl` (patients), `qrels/test.tsv` (labels), `corpus.jsonl` (trials) and
NCBI's `retrieved_trials.json`. MedCPT (two ~440 MB encoders) downloads from Hugging Face on first use. Encoding a
corpus takes about 30 min on 4 CPU cores and is cached in `data/index/<name>/`.

## 2. Benchmark against the paper

```bash
make bench-slice MODEL=qwen2.5:14b COHORT=sigir        # 5 patients x 12 labelled trials (minutes-hours on CPU)
make bench       MODEL=qwen2.5:14b COHORT=trec_2021    # everything (days on CPU; use a GPU box)
.venv/bin/python -m trialgpt_local.benchmark report    # results/<model>/report.md + report.json
make retrieval   MODEL=qwen2.5:14b COHORT=sigir        # recall@100/500/1000 with your model's keywords
```

* `rank` mirrors NCBI's run: every labelled trial among the retrieved trials per patient, in NCBI's output layout
  (`matching_results_*.json`, `aggregation_results_*.json`). It is resumable, and `timing.json` records seconds per
  pair.
* `report` computes NDCG@10, P@10 and AUROC for the paper's four Table 2 variants per cohort, and the 3-cohort
  average beside the published GPT-4/GPT-3.5 numbers, plus parse errors and seconds per pair. A context overflow
  stops the run with the trial named (raise `TG_LLM_NUM_CTX`, rerun: it resumes).
* Slices are seeded and keep every label (0/1/2) represented. Slice numbers are not the paper's numbers; only the
  full run of all three cohorts is comparable to Table 2.
* Fidelity check already done: SIGIR recall@500 0.931 (paper 0.934) with the paper's gpt-4-turbo keywords
  (`tools/retrieval_check.py`).

## 3. Local interface

```bash
make serve MODEL=qwen2.5:14b     # http://127.0.0.1:8090  (TG_HOST/TG_PORT to change; keep it on localhost)
```

1. Paste a note, or upload a PDF or text file. Scanned PDFs need OCR first.
2. Choose the source: **live** searches ClinicalTrials.gov (API v2) with the generated keywords; **sigir/trec_*** use
   the frozen NCBI corpus. Set top-k and, optionally, a preferred country (that reorders and never drops trials).
3. Each result card shows the trial score (matching + aggregation), R/E with the model's explanations, and every
   criterion with its label, reasoning and the note sentences the model cited as evidence.
4. The **Reports** tab shows the benchmark and head-to-head reports.

The note goes only to the LLM. Jobs live in memory, and only the keywords leave the machine (to ClinicalTrials.gov).
API docs are at `/api/docs`.

## 4. Head-to-head with trialgpt.app

```bash
make h2h-capture COHORT=sigir N=20        # Playwright, one patient per 60 s; ~25 min for 20
make h2h MODEL=qwen2.5:14b                # local run + cross-evaluation + pooled workbook + report
# physicians fill results/h2h/pooled.xlsx (blinded), then:
.venv/bin/python -m trialgpt_local.h2h.compare report --adjudicated results/h2h/pooled.xlsx
```

* **What is sent.** Only SIGIR/TREC synthetic patient notes, which are public data. The capture refuses any other
  source and any `--delay` under 20 s.
* **Evidence.** `results/h2h/trialgpt_app/<patient>.json` keeps the app's own responses (extracted conditions, the
  ~200 ranked trials), the choices made for the user, the app bundle version and the search time. A `.png`
  screenshot is saved alongside.
* **Making it fair.** The local system searches live ClinicalTrials.gov too, and `--prefer-country` defaults to the
  country the app used. The app ranks on the conditions the user picks (`--select first` = its first-listed
  condition; `all` = every one). Report both if the choice matters.
* **Reading the report.**
  1. Label coverage is informational.
  2. Cross-evaluation favours the local system when the judge is the same model, so run it again with
     `TG_JUDGE_MODEL` set to a different, ideally larger, model.
  3. The physician-adjudicated pooled P@10/NDCG@10, with a paired bootstrap CI, is the result.
* **How many patients.** About 20 patients × 2 top-10s ≈ 300–400 unique pairs after pooling, roughly 1–2 physician
  days at 15–20 pairs an hour. Two raters on a 20 % overlap give a kappa.
* **If the app changes its UI.** The capture fails loudly at the first missing step and keeps a screenshot. Update
  the selectors in `h2h/capture.py`.

## 5. CGRD validation

Do all of this on the hospital's approved machine, under the IRB protocol, with the results folder on an encrypted
volume. Nothing goes to trialgpt.app. Run folders are written with mode 0600 and are gitignored.

### 5a. Demo on synthetic CGRD-format data

```bash
make cgrd-demo MODEL=qwen2.5:14b          # TRIALS=NCT...,NCT... to change; builds data/cgrd_synthetic first
```

### 5b. Real CGRD

1. **Map the schema.** Copy `trialgpt_local/cgrd/mapping.default.yaml`. Under `tables:`, change only the table and
   column names to the CGRD tables you have (patient, diagnosis, lab, vital, medication, procedure, report, note).
   Remove a table you don't have. Point `icd10_names` at the full ICD-10-CM (TW) code table (`code,display,display_zh`
   CSV). Fix `sex_values` to CGRD's coding. Identity columns are never mapped, and the composer cannot read what the
   mapping does not name.
2. **Site key.** `export TG_SITE_KEY=...` (or let it create `data/cgrd/.site_key`, 0600). Pseudonyms are
   `HMAC(site key, chart no.)`. Keep the key with the data custodian; it is the only way to re-identify a row.
3. **Restrict the population.** For a whole-hospital database, pre-filter with SQL (for example, any ICD code of the
   trial's condition in the last 2 years plus a random sample of everyone else) and pass the chart numbers with
   `--mrns-file`. Notes are composed in memory for every listed patient.
4. **Select pairs.**
   ```bash
   .venv/bin/python -m trialgpt_local.cgrd.validate select --db "mssql+pyodbc://..." --mapping my_cgrd.yaml \
       --trials NCT0xxxxxxx,NCT0yyyyyyy --run ra2026 --index-date 2026-09-30 --per-trial 20 --controls 10 \
       --mrns-file cohort.txt
   ```
   `--db` takes an SQLite file or any SQLAlchemy URL; install `pip install -e ".[cgrd-sql]"` plus the driver. Queries
   are read-only and batched 500 chart numbers at a time. `--trials` also accepts a JSON file of in-house protocols
   in NCBI trial format.
5. **Read a few notes.** Open `results/cgrd/<run>/notes.json` and read 3–5 notes against the chart before going on.
   Fix the mapping until they are right.
6. **Match.** Run `.venv/bin/python -m trialgpt_local.cgrd.validate run --run ra2026`. It is resumable and the LLM
   cache is off.
7. **Workbooks.** Run `... workbook --run ra2026 --criteria-pairs 40`. This writes `trial.xlsx` (every pair graded
   0/1/2) and `criteria.xlsx` (a stratified sample, every criterion). Both are blinded and shuffled, with keys in
   `*.key.json`.
8. **Score.** After the physicians return the files, run `... score --run ra2026`. It writes `report.md` in the run
   folder: AUROC of the combined score for eligible vs not, sensitivity, specificity and PPV at score > 0, recall of
   eligible patients and AUROC per trial, criterion accuracy and Cohen's κ. Compare with the paper's 87.3 % (GPT-4) and
   88.7–90.0 % (experts).

## 6. Troubleshooting

| symptom | cause / fix |
|---|---|
| `ContextOverflow` | raise `TG_LLM_NUM_CTX` (and check the GPU or RAM fits it) |
| many `parse error` labels | model too small or not instruction-tuned; try a bigger one. `--strict-labels` makes it worse on purpose |
| `LLMError: ... connect` | `ollama serve` not running, or wrong `TG_LLM_BASE_URL` |
| retrieval very slow the first time | MedCPT encoding of the corpus (cached afterwards); `TG_DEVICE=cuda` if you have a GPU |
| `nltk` refuses to download behind a proxy | `NLTK_ALLOW_PROXIED_URLOPEN=1` if the proxy is trusted, then rerun the installer |
| capture: `ERR_CERT_AUTHORITY_INVALID` behind a TLS-inspecting proxy | import the proxy CA into Chromium's NSS DB (`certutil -d sql:$HOME/.pki/nssdb -A -t C,, -n proxy -i ca.crt`); never disable verification |
| capture stops at a step | the app changed; see the screenshot and update the selector in `h2h/capture.py` |
