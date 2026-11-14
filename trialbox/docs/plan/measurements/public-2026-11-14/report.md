# TrialBox complete-platform run

Head `028586742365` (Lane G: D-502, every data set is run with the real models in three languages; lane G's order of work). Run: 20261114T061459Z-02858674-s1. Model: local/gemma-4-26b-a4b-nvfp4, local/qwen3.5-9b-awq (gateway (installed box, synthetic weight pins)). Hospital: 50,000 synthetic patients. Languages run: ja, zh-TW. OCR: tesseract. Model calls in flight: 16. Host: x86_64, 48 CPUs.
Run started 2026-11-14T06:21:37+00:00, finished 2026-11-14T08:14:43+00:00 (the parts' own times); report built 2026-11-14T08:15:50+00:00.

**FAILED**: 262 of 265 checks passed (3 failed); 26 of 26 screenshots; 113.0 min of part time (each part's wall time, summed: parts on several VMs ran at the same time); 1 known findings reported.

Screenshots are in the run's `report/shots/` folder (not committed).

Door secret after the collect (T-119): door secret tb-gpu-door: enabled version(s) 2 remain (this run's not destroyed: none); destroy each with: gcloud secrets versions destroy <version> --secret tb-gpu-door --quiet

| part | stage | checks | result | seconds | screenshot |
| --- | --- | --- | --- | --- | --- |
| public-ja | 0 public data in | 7/7 | pass | 0.2 | `public-ja-00.png` |
| public-ja | 1 criteria, approval and feasibility | 17/17 | pass | 7.5 | `public-ja-01.png` |
| public-ja | 2 screening (patient list) on real notes | 7/7 | pass | 41.4 | `public-ja-02.png` |
| public-ja | 3 list, S5 and marks | 13/13 | pass | 3.8 | `public-ja-03.png` |
| public-ja | 4 N1 / N2 mail | 3/3 | pass | 0.6 | `public-ja-04.png` |
| public-ja | 5 REDCap simulator read-back | 4/4 | pass | 0.7 | `public-ja-05.png` |
| public-ja | 5b trial lifecycle (D-134) | 7/7 | pass | 1.7 | `public-ja-06.png` |
| public-ja | 5c site set-up and data harmonization (D-135) | 6/6 | pass | 24.3 | `public-ja-07.png` |
| public-ja | 6 other screens | 48/48 | pass | 5.3 | `public-ja-08.png` |
| public-ja | 7 exports, CASE, consent explainer, Cancel / Retry | 11/11 | pass | 289.8 | `public-ja-09.png` |
| public-ja | 7b chart numbers and names by role | 6/6 | pass | 3.8 | `public-ja-10.png` |
| public-ja | 8 audit chain | 1/1 | pass | 0.0 | `public-ja-11.png` |
| public-zh-TW | 0 public data in | 7/7 | pass | 0.2 | `public-zh-TW-00.png` |
| public-zh-TW | 1 criteria, approval and feasibility | 17/17 | pass | 6.7 | `public-zh-TW-01.png` |
| public-zh-TW | 2 screening (patient list) on real notes | 7/7 | pass | 116.5 | `public-zh-TW-02.png` |
| public-zh-TW | 3 list, S5 and marks | 13/13 | pass | 3.8 | `public-zh-TW-03.png` |
| public-zh-TW | 4 N1 / N2 mail | 3/3 | pass | 0.4 | `public-zh-TW-04.png` |
| public-zh-TW | 5 REDCap simulator read-back | 4/4 | pass | 0.7 | `public-zh-TW-05.png` |
| public-zh-TW | 5b trial lifecycle (D-134) | 7/7 | pass | 1.9 | `public-zh-TW-06.png` |
| public-zh-TW | 5c site set-up and data harmonization (D-135) | 6/6 | pass | 23.4 | `public-zh-TW-07.png` |
| public-zh-TW | 6 other screens | 48/48 | pass | 5.3 | `public-zh-TW-08.png` |
| public-zh-TW | 7 exports, CASE, consent explainer, Cancel / Retry | 11/11 | pass | 289.3 | `public-zh-TW-09.png` |
| public-zh-TW | 7b chart numbers and names by role | 6/6 | pass | 3.8 | `public-zh-TW-10.png` |
| public-zh-TW | 8 audit chain | 1/1 | pass | 0.0 | `public-zh-TW-11.png` |
| scenario-public-medtxt | MedTxt-CR (ja): case reports pasted, conditions read, negations kept out | 2/3 | FAIL | 2805.0 | `scenario-public-medtxt-00.png` |
| scenario-public-trec | TREC CT: real trials, patient descriptions, qrels as truth | 0/2 | FAIL | 2708.8 | `scenario-public-trec.png` |

## Scenarios

### public-medtxt: Real data: MedTxt-CR Japanese case reports as pasted charts (CC BY 4.0)

**FAIL**: 2 of 3 checks.

* Input: 148 MedTxt-CR case reports (ja, real clinician text, CC BY 4.0)
* Counts: `{"conditions": 432, "on_positive_mention": 389, "positive_tags": 1427, "negative_tags": 195, "on_untagged_text": 24, "on_suspected_mention": 11, "on_negated_mention": 8}`
* Expected: `{"conditions_on_negated_mentions": 0}`
* Got: `{"conditions_on_negated_mentions": 8}`
* Model calls: 148
* Time: 2806.7 s. Screenshot: `scenario-public-medtxt-00.png`
* FAILED (scenario-public-medtxt / MedTxt-CR (ja): case reports pasted, conditions read, negations kept out): no proposed condition rests only on a mention the corpus marks negative: ['CR:JP0245-4: 右乳癌術後（４年前）', 'CR:JP1220-162: 平成２年４月４日に食道癌根治術施行。', 'CR:JP1553-37: ７年前に胸腺癌手術', 'CR:JP1553-37: ５年前に下肢静脈瘤手術。', 'CR:JP1553-72: 既往に開腹胆摘、上行結腸早期癌ＥＭＲがある。']

### public-trec: Real data: TREC Clinical Trials topics, trials and qrels (NIST, NCBI)

**FAIL**: 0 of 2 checks.

* Input: 100 TREC CT 2021/22 patient-trial pairs (50 eligible, 50 excluded by the qrels), 1256 criteria
* Counts: `{"criteria": 1256, "models": ["local/gemma-4-26b-a4b-nvfp4", "local/qwen3.5-9b-awq"]}`
* Expected: `{"eligible_lost": 0, "excluded_caught": 50}`
* Got: `{"eligible_lost": 12, "excluded_caught": 23}`
* Model calls: 2512
* Note: judged by tools.mlbench's prompt straight to the model (an evaluation path, not the box)
* Time: 2709.7 s. Screenshot: `scenario-public-trec.png`
* FAILED (scenario-public-trec / TREC CT: real trials, patient descriptions, qrels as truth): every criterion answered: 7
* FAILED (scenario-public-trec / TREC CT: real trials, patient descriptions, qrels as truth): eligible patients lost by the pair <= 10 % (VALIDATION §3: 3.1 % on the deployed files): (12, 50)

## Known findings (reported, not fixed in this run)

| id | part | what | expected | got | holds |
| --- | --- | --- | --- | --- | --- |
| MT-01 | scenario-public-medtxt | conditions proposed from a mention the corpus marks suspected (疑い) | 0 | 11 | NO |

## Throughput (model calls through the gateway)

Calls and tokens per second are over the seconds in which a call was in flight (the gateway's audit); the servers' `/metrics` before and after, `gpu.csv` (every 10 s) and `vllm.csv` are in `parts/<part>/`. A hospital part has two rows: **main SCREEN** (the SCREEN job's own window: the throughput of the curve) and **whole part** (with the canary's one-at-a-time calls and stages 15 and 17). GPU % is `nvidia-smi` utilisation, the share of time a kernel ran: not a headroom measure (a card at 100 % may take more calls). KV peak: each server's KV-cache usage peak (vllm.csv). Not measured: the gateway's slot wait per call (the gateway does not record it).

| part | window | in flight | calls | calls/s | tokens/s | p50 s | p95 s | queue s (vLLM) | GPU % mean | GPU % max | KV peak | GPU MiB peak | breaker opened | listed | list sha256 | refused (of asked) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| public-ja | whole part | 16 | 525 | 0.957 | 677.928 | 2.051 | 4.966 | judge 0.0039, verifier 0.018 | 39.2 | 93.0 | judge 0.04096975709568906, verifier 0.02336448598130836 | 62592.0 | 0 | 90 | `-` | 0 of 525 |
| public-zh-TW | whole part | 16 | 517 | 0.836 | 601.266 | 2.002 | 3.506 | judge 0.0002, verifier 0.0008 | 38.4 | 92.0 | judge 0.038257041434794026, verifier 0.01869158878504673 | 62592.0 | 0 | 90 | `-` | 0 of 517 |
| scenario-public-medtxt | whole part | 16 | 0 | - | - | - | - | judge 0.0014, verifier 0.0012 | 33.1 | 41.0 | judge 0.006743036071367725, verifier 0.006230529595015577 | 62592.0 | - | - | `-` | - |
| scenario-public-trec | whole part | 16 | 0 | - | - | - | - | judge 0.001, verifier 0.001 | 38.4 | 67.0 | judge 0.004092325339864478, verifier 0.012461059190031154 | 62592.0 | - | - | `-` | - |

## Part times

| part | wall seconds |
| --- | --- |
| public-ja | 600.1 |
| public-zh-TW | 664.4 |
| scenario-public-medtxt | 2806.7 |
| scenario-public-trec | 2709.7 |

## Failed checks

Each detail is cut at 300 characters here (TB_REPORT_DETAIL_CHARS); the whole detail of each is in `failed-checks.json` beside this report (as the part recorded it).

- scenario-public-medtxt / MedTxt-CR (ja): case reports pasted, conditions read, negations kept out: no proposed condition rests only on a mention the corpus marks negative: ['CR:JP0245-4: 右乳癌術後（４年前）', 'CR:JP1220-162: 平成２年４月４日に食道癌根治術施行。', 'CR:JP1553-37: ７年前に胸腺癌手術', 'CR:JP1553-37: ５年前に下肢静脈瘤手術。', 'CR:JP1553-72: 既往に開腹胆摘、上行結腸早期癌ＥＭＲがある。']
- scenario-public-trec / TREC CT: real trials, patient descriptions, qrels as truth: every criterion answered: 7
- scenario-public-trec / TREC CT: real trials, patient descriptions, qrels as truth: eligible patients lost by the pair <= 10 % (VALIDATION §3: 3.1 % on the deployed files): (12, 50)

## public-ja: screen

```json
{"funnel": {"S0": 268, "S1": 90, "S3": 90, "S4": 90}, "tiers": {"excluded": 178, "high": 0, "review": 90}, "listed": 90, "judging": {"configured_note_block": "both_agree", "disagreements": 4, "failures": 0, "judge_model": "local/gemma-4-26b-a4b-nvfp4", "may_block": true, "mode": "agreement", "note_block": "both_agree", "note_block_code": "ok", "note_block_reason": "judge and verifier must both say fail", "verifier_model": "local/qwen3.5-9b-awq"}, "request_seconds": {"PUB-ONC": 40.3, "PUB-CA": 0.9}, "stage_seconds": 41.3}
```

## public-ja: canary

```json
{"gate": "on", "allows_block": true, "code": "ok", "reason": "", "running": false, "at": "2026-11-14T06:25:09", "ok": true, "cases": 54, "pair_correct": 52, "pair_decided_wrong": 0, "models": [{"role": "judge", "model": "local/gemma-4-26b-a4b-nvfp4", "correct": 53, "flips": 1, "ok": true}, {"role": "verifier", "model": "local/qwen3.5-9b-awq", "correct": 49, "flips": 1, "ok": true}], "wake_failure": null}
```

## public-zh-TW: screen

```json
{"funnel": {"S0": 268, "S1": 90, "S3": 90, "S4": 90}, "tiers": {"excluded": 178, "high": 0, "review": 90}, "listed": 90, "judging": {"configured_note_block": "both_agree", "disagreements": 4, "failures": 1, "judge_model": "local/gemma-4-26b-a4b-nvfp4", "may_block": true, "mode": "agreement", "note_block": "both_agree", "note_block_code": "ok", "note_block_reason": "judge and verifier must both say fail", "verifier_model": "local/qwen3.5-9b-awq"}, "request_seconds": {"PUB-ONC": 115.3, "PUB-CA": 1.0}, "stage_seconds": 116.4}
```

## public-zh-TW: canary

```json
{"gate": "on", "allows_block": true, "code": "ok", "reason": "", "running": false, "at": "2026-11-14T06:35:03", "ok": true, "cases": 54, "pair_correct": 53, "pair_decided_wrong": 0, "models": [{"role": "judge", "model": "local/gemma-4-26b-a4b-nvfp4", "correct": 54, "flips": 0, "ok": true}, {"role": "verifier", "model": "local/qwen3.5-9b-awq", "correct": 49, "flips": 1, "ok": true}], "wake_failure": null}
```
