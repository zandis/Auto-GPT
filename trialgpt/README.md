# TrialGPT, local

[NCBI TrialGPT](https://github.com/ncbi-nlp/TrialGPT) (Jin et al., *Nat Commun* 2024) running on **your own LLM**
(Ollama, or any OpenAI-compatible server), with:

| | what | where |
|---|---|---|
| 1 | the TrialGPT pipeline: keyword generation → hybrid BM25 + MedCPT retrieval → criterion matching → LLM aggregation → ranking | `trialgpt_local/core.py`, `retrieval.py`, `pipeline.py` |
| 2 | a benchmark on NCBI's own data (SIGIR, TREC 2021, TREC 2022) scored against the paper's numbers | `trialgpt_local/benchmark.py` |
| 3 | a local web interface: paste/upload a note, get ranked trials with criterion-by-criterion evidence | `trialgpt_local/app.py` |
| 4 | a head-to-head with [trialgpt.app](https://trialgpt.app) on the public synthetic patients | `trialgpt_local/h2h/` |
| 5 | a validation harness for CGRD (Chang Gung Research Database) judged by blinded physicians | `trialgpt_local/cgrd/` |

Step-by-step operations, including the real-CGRD setup: [RUNBOOK.md](RUNBOOK.md).

```bash
make venv                                  # Python 3.12 venv (CPU torch), nltk punkt
ollama pull qwen2.5:7b                     # or any model; set MODEL=... below
make data ZIP=TrialGPT-main.zip            # NCBI cohorts (or without ZIP: git clone from GitHub)
make serve MODEL=qwen2.5:7b                # http://127.0.0.1:8090
make bench-slice MODEL=qwen2.5:7b          # 5 patients x 12 labelled trials, report vs the paper
```

## Faithful to NCBI

* **Prompts are NCBI's, byte for byte.** `trialgpt_local/prompts.py` is generated from the vendored upstream code
  (`vendor/ncbi_trialgpt`, commit in `vendor/ncbi_trialgpt/COMMIT`) by `tools/sync_prompts.py`;
  `make lint` fails if it drifts, and `tests/test_core.py` executes the upstream functions and compares outputs.
* **Scoring is NCBI's.** The matching score (`get_matching_score`) and aggregation score (`get_agg_score`) are the
  upstream functions; final rank score = matching + aggregation, NCBI's `rank_results.py` and the paper's
  "Feature combination".
* **Retrieval is NCBI's.** BM25 over 3×title + 2×conditions + text, MedCPT article/query encoders, reciprocal-rank
  fusion with k = 20 and keyword-priority weights 1/(i+1). With the keyword file the paper used
  (gpt-4-turbo keywords), this implementation gets SIGIR recall@500 **0.931** (paper: 0.934) and recall@1000 0.964.
* **Metrics follow the paper.** NDCG@10 with linear gain, graded P@10 = Σr / 2k, AUROC of eligible (2) vs excluded
  (1). `benchmarks/paper_reference.json` holds the published values and their caveats. Table 2 only reports
  3-cohort averages.

### Where this deviates, and why

| deviation | why | turn off |
|---|---|---|
| Ollama `/api/chat` with `format: json`, temperature 0, fixed seed, explicit `num_ctx` (default 16384) | Ollama's 2048-token default would silently truncate the matching prompt | `TG_LLM_BACKEND=openai` for an OpenAI-compatible server |
| A call that fills the context raises `ContextOverflow` | Truncated prompts give confident nonsense | raise `TG_LLM_NUM_CTX` |
| Labels are lower-cased and stripped of trailing periods before checking; unparseable output becomes `parse error` | Small models write `Included.`; NCBI would score those 0 silently | `--strict-labels` |
| Patient sentences are also split on 。！？ | CJK notes would otherwise be one "sentence" | – |
| Live mode searches ClinicalTrials.gov API v2 instead of a frozen corpus | The interface is for current trials | `source=sigir/trec_*` uses the frozen corpus |

## Head-to-head with trialgpt.app: read this first

trialgpt.app is Foundation 29's service. It is **not** the NCBI pipeline. From its network traffic:
* it extracts conditions from the note and asks the user to choose the main diagnosis;
* its search sends only the chosen conditions (`docText` is empty) plus a preferred country;
* it returns about 200 trials ranked by its own logic, using cloud LLMs (Azure, with LangSmith tracing in the EU).

So the comparison is between two products on the same patients, not a replication.

* **Only public synthetic patients** (SIGIR / TREC) are ever sent to trialgpt.app. The capture script cannot
  read CGRD or any other source.
* **The capture is gentle and fully recorded.** One patient at a time, 60 s apart by default (under 20 s is refused).
  The app's own responses and a screenshot are saved per patient. The human step "choose the main diagnosis" is
  fixed by `--select first|all`.
* **There are three scoring lenses.**
  1. *Label coverage*: TREC/SIGIR labels cover their frozen corpus, so few live trials are labelled. Coverage is
     reported, not used as the verdict.
  2. *Cross-evaluation*: TrialGPT criterion matching scores both top-10s. This favours the local system when the
     judge is the same model; set `TG_JUDGE_MODEL` to a different model to reduce that bias.
  3. *Physician adjudication*: both top-10s are pooled, de-duplicated and shuffled into one blinded workbook, with no
     system labels. The report gives graded P@10, NDCG@10, wins per patient and a paired bootstrap CI.
     **Quote this one.**

## CGRD validation

A physician-judged validation that runs inside the hospital:
* `select` builds patient notes from the database through a column mapping. The note includes age, never DOB, name,
  ID or phone, and uses an HMAC pseudonym. For each trial it picks "likely" patients by BM25 plus random controls.
* `run` runs the local LLM with the disk cache off.
* `workbook` writes blinded trial-level (0/1/2) and criterion-level workbooks.
* `score` reports AUROC, sensitivity, specificity and PPV at score > 0, criterion accuracy and Cohen's κ, the
  metrics of the paper's 87.3 % criterion accuracy.

`make cgrd-demo` runs the whole loop on synthetic CGRD-format data. The RUNBOOK covers mapping the real schema.

## Privacy

| data | goes to | never to |
|---|---|---|
| note typed in the interface | the local LLM only (in memory, disk cache off) | disk, trialgpt.app, logs |
| generated search keywords (live mode) | ClinicalTrials.gov API | – |
| CGRD notes | the local LLM (cache off) and `results/cgrd/<run>` (mode 0600, gitignored) | anything else |
| SIGIR / TREC synthetic notes | the local LLM (cached) and trialgpt.app | – |

## Layout

```
trialgpt_local/   config, llm (Ollama / OpenAI-compatible, cache, cassettes), prompts (generated), core, metrics,
                  datasets, retrieval, ctgov, pipeline, benchmark, app + static/, annotate (blinded XLSX),
                  h2h/{capture,compare}, cgrd/{reader,validate,mapping.default.yaml}
vendor/           unmodified NCBI TrialGPT, for traceability
benchmarks/       paper reference numbers
tools/            sync_prompts.py, retrieval_check.py
tests/            17 offline tests (mock LLM; `-m llm` / `-m network` for the real thing)
```
