# Bench results (SPEC §11.3) — development host

`tools/bench.py` (D-80) runs the real code path of each job and projects linearly to the §11.3 size.

**This host is not the reference box.** The reference is x86 with one 32 GB GPU; this host is x86_64 with 4 vCPU,
16 GB RAM (15 usable), about 12 GB of free disk and **no GPU**. The LLM is the deterministic stub, so judge,
ir_extract and draft_doc latency is **not measured**. The ingest run shared the CPU with an emulated arm64 image
build, so its time is pessimistic.

| job | §11.3 size / target | measured here | time | projected to the §11.3 size | within target |
| --- | --- | --- | --- | --- | --- |
| Ingest | 50k patients / night, ≤ 2 h | 15,000 patients (CSV → mapping → NDJSON → lake, HL7 validator on the 1 % sample) | 299 s | 16.6 min | yes¹ |
| FEAS | 300k × 36 month-ends × 25 criteria, ≤ 30 min | 30,000 patients × 36 × 23 (in memory) | 25 s | 4.5 min | yes |
| FEAS | (same) | 100,200 patients × 36 × 23 (lake memory capped at 6 GB, spilling) | 215 s | 11.7 min² | yes |
| SCREEN | 1,000 × 25 CQL + 300 × 5 note, ≤ 3 h | 600 patients × 18 CQL criteria (36 expressions) on HAPI `$evaluate`, 8 concurrent | 28.7 s | 1.1 min (CQL share)³ | yes³ |
| MICROBATCH | 100 × 5 time-sensitive, ≤ 10 min | 365 patients re-evaluated (pool + first-Monday incident scope) | 5.3 s | < 0.1 min³ | yes³ |
| NAV | 500 × 15 + 50 drafts + 50 bundles, ≤ 1 h | RA-BIO + ONC-OSI: 162 patients, 17 drafts, 13 TWPAS bundles, HL7 validator (two IG loads) | 96.5 s | 6.2 min³ | yes³ |
| Compile | 25-criterion protocol incl. equivalence, ≤ 20 min | GZQO: 23 criteria → CQL (translator) + SQL, equivalence on 200 patients on HAPI | 21.5 s | 0.4 min³ | yes³ |

¹ fhir-store load not included (it runs alongside the lake rebuild in production). **Memory:** ingest holds the batch
in memory, about 4.9 GB RSS at 15k patients. A 50k batch was killed by the 15 GB host. The 128 GB reference box
fits it; smaller hosts ingest in `--since` deltas (D-80).
² 300k patients could not run here: DuckDB's spill exceeds the free disk. The cap that prevents an OOM kill
(`TB_LAKE_MEMORY_LIMIT`, default 40 % of RAM) is in the lake. At 40 % of 128 GB the reference box keeps 300k in
memory, closer to the 30k rate.
³ Deterministic share only. Measure the LLM share on the reference box:
`python tools/bench.py --tasks screen,microbatch,nav,compile --llm-url http://llm-service:8000/v1 --llm-model <name>`.

Every deterministic share is far inside its target. The go-live bench must still be repeated on the reference
hardware with the real models, as §11.3 requires.

## First real-model run: judge_ml and the cascade through tb-gateway (2026-10-25, S1-14)

Full results, pins and per-item predictions: `eval/bakeoff/results/2026-10-25/` (`summary.md`, `summary.json`,
`predictions_<build>[__trialgpt].csv`, `metrics_*.json`, `cascade_*.json`). Hosted models on OpenRouter, **open D0
data only**, every call through tb-gateway in DEV (`bakeoff` route; caller `eval`; class D0). Each build is pinned to
one dated provider version (`tools/pin_provider.py`: model id, dated canonical slug, provider endpoint, quantisation;
sha256 over that descriptor). The gateway requests that provider only, with no fallback and `data_collection: deny`,
and refuses a response that reports another model or provider (no mismatch occurred). Sampling is forced (temperature
0, seed 20261025). One seed per item. Request: `tools/mlbench.messages` (the TrialBox judge prompt) with a json_schema
answer whose evidence list is capped at 12 ids. Without the cap, greedy decoding looped on the evidence array until
the token limit (gpt-oss-120b on two providers).

English, all 1,015 SIGIR criterion pairs (NCBI TrialGPT-Criterion-Annotations, physician labels). "Lost": eligible
patient × trial pairs (physician blocks no criterion) where the model blocks at least one; 79 such pairs.

| Build (provider) | 4-way acc. | Screen acc. | False block (UB95) | Lost /79 | Block recall | Invalid | p50 s | $ / 1k |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **gpt-oss-120b + Gemma 4, block only if both block** | 0.511 | **0.974** | **0.009 (0.016)** | **8** | 0.485 | 0.6% | 1.6 | 0.04 |
| gpt-oss-120b (DeepInfra bf16) | 0.509 | 0.969 | 0.017 (0.026) | 13 | 0.545 | 0.6% | 1.6 | 0.04 |
| Gemma 4 26B-A4B (DeepInfra fp8) | 0.636 | 0.960 | 0.024 (0.034) | 15 | 0.485 | 0.9% | 0.7 | 0.05 |
| Nemotron 3 Nano 30B-A3B (Nebius fp8) | 0.489 | 0.967 | 0.018 (0.027) | 14 | 0.515 | 1.4% | 3.8 | 0.12 |
| Qwen3.6-35B-A3B (DeepInfra fp8) | 0.537 | 0.955 | 0.035 (0.046) | 22 | 0.636 | 0.2% | 5.8 | 0.99 |
| GPT-4.1 (OpenAI; closed reference) | 0.500 | 0.967 | 0.017 (0.026) | 12 | 0.485 | 0.8% | 1.1 | 1.26 |
| *Recorded GPT-4 labels (TrialGPT paper run)* | *0.873* | *0.981* | *0.014 (0.022)* | *8* | *0.848* | — | — | — |

Reading the table:

- **The 4-way gap to the recorded GPT-4 labels comes from the prompt convention, not from the harness or the
  models.** Checks: the gold labels, label sets and scorer are `tools/mlbench` (as `judge_public`); the whole note is
  in every prompt (about 460 input tokens); reasoning is returned apart from the JSON; under 1.5% of answers are
  invalid, and an invalid answer counts as an abstention.
- An independent harness (draft PR #6, `tools/trialgpt_compare.py`) gets the same numbers: GPT-4.1 50.7%, gpt-oss
  50.0%, Gemma 65.2%, Qwen 51.3%.
- The TrialBox prompt says a finding the note does not mention is not a negative finding. TrialGPT's prompt says the
  opposite ("use as less 'not enough information' as possible … assume that the fact is not true"), and the NCBI
  labels follow it. Of the 484 `not excluded` exclusion pairs, GPT-4.1 answered `not enough information` for 372.
  That answer still leaves the patient open.
- With TrialGPT's criterion wording (`--variant trialgpt`, seeded 100 pairs per model), GPT-4.1's 4-way accuracy rises
  from 0.50 to 0.69 and Qwen3.6's from 0.57 to 0.78, as in PR #6. False blocks rise too (GPT-4.1 0% → 11.9%, Nemotron
  4.5% → 11.9%, Qwen 1.5% → 9.0%).
- **Safety floor** (`eval/bakeoff/weights.yaml`: false-block UB95 ≤ 0.030): the two-model rule (0.016), gpt-oss-120b,
  Nemotron 3 Nano and GPT-4.1 pass. Gemma 4 (0.034) and Qwen3.6 (0.046) fail alone. No model meets the 4-way language
  floors (en 0.85) under the TrialBox prompt.
- The two-model rule (gpt-oss-120b judge, Gemma 4 verifier; the verifier is asked only when the judge blocks) loses
  8 of 79 eligible pairs. That equals the recorded GPT-4 labels and PR #6, at about $0.04 per 1,000 judgements on
  hosted models.
- Cost and latency: Qwen3.6 spends about 1,050 reasoning tokens per answer even at low effort, which makes it about
  27 times dearer than gpt-oss-120b and the slowest.
- Per language (zh-TW, ja, mixed; full 1,015 per open model, GPT-4.1 on a seeded 200-item subset; see
  `summary.md`), screening accuracy drops by at most 1.4 points and the safety ranking holds. The two-model rule stays
  at false-block UB95 ≤ 0.021 in every language.
- On the translated notes, the gateway's PHI tripwire refused 103 of the 3,045 calls per model (zh-TW 52, ja 40,
  mixed 11; `NAME` detector, refused, never relabelled). Those items count as abstentions. It is a false-positive rate
  of the name detector on CJK text, worth tuning before D1/D2 notes in Chinese or Japanese go through it.

Cascade end to end (synthetic site A, GZQO, `tools/cascade_e2e.py --no-repro` against each gateway, as
`tools/spark_e2e.sh` runs it; hosted inference is not bit-reproducible, and with the repro check on, every hosted
build failed only `reproducible`):

| Build | Checks | Funnel S0→S5 | Certificate | Calls | Cost |
| --- | --- | --- | --- | --- | --- |
| gpt-oss-120b + Gemma 4 (`TB_GATEWAY_VERIFIER_URL`, `AgreementJudge`) | all pass | 600→18→18→17→12→12→2 | issued | 17 + 14 | $0.003 |
| gpt-oss-120b | all pass | 600→18→18→17→12→12→2 | issued | 17 | $0.002 |
| Gemma 4 26B-A4B | all pass | 600→18→18→17→12→12→2 | issued | 17 | $0.001 |
| Nemotron 3 Nano | all pass | 600→18→18→17→12→12→2 | issued | 18 | $0.005 |
| Qwen3.6-35B-A3B | all pass | 600→18→18→17→11→11→2 | issued | 17 | $0.012 |
| GPT-4.1 | `gateway_build_pinned` fails | 600→18→18→17→17→17→2 | issued | 0 (18 × HTTP 400) | $0 |

- The cascade's model calls are D0 (synthetic notes) and go by the `dev-public` route. No D3 rule was touched: the
  stage logs stay D3-labelled inside the perimeter.
- GPT-4.1: OpenAI's strict structured-output mode rejects the `judge@3` output schema, because its optional fields
  (`quote`, `quote_date`, `reason`) are not in `required`. Every S3 question therefore stayed unknown, which is never
  an exclusion. The open models accept the schema.
- The PHI tripwire refused one synthetic note per pass (an ID-number pattern). It was not relabelled (LLM-15).
