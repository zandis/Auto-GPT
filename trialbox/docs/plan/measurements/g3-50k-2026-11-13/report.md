# TrialBox complete-platform run

Head `c25cea6bc78e` (Lane G: every apt on the run VM waits for the dpkg lock, not only the script's own calls). Run: 20261113T085509Z-c25cea6b-s1. Model: local/gemma-4-26b-a4b-nvfp4, local/qwen3.5-9b-awq (gateway (installed box, synthetic weight pins)). Hospital: 50,000 synthetic patients. Languages run: ja, zh-TW. OCR: tesseract. Model calls in flight: 16. Host: x86_64, 48 CPUs.
Run started 2026-11-13T09:01:54+00:00, finished 2026-11-13T10:43:24+00:00 (the parts' own times); report built 2026-11-13T10:55:26+00:00.

**FAILED**: 462 of 466 checks passed (4 failed); 46 of 46 screenshots; 100.9 min of part time (each part's wall time, summed: parts on several VMs ran at the same time); 0 known findings reported.

Screenshots are in the run's `report/shots/` folder (not committed).

Door secret after the collect (T-119): door secret tb-gpu-door: enabled version(s) 2 remain (this run's not destroyed: none); destroy each with: gcloud secrets versions destroy <version> --secret tb-gpu-door --quiet

| part | stage | checks | result | seconds | screenshot |
| --- | --- | --- | --- | --- | --- |
| prepare | synthetic hospital | 2/2 | pass | 14.9 | `prepare.png` |
| g4-decoding | G-4 structured output: backend, guided decoding on and off, eager start | 3/4 | FAIL | 25.5 | `g4-decoding.png` |
| g5-tokens | G-5 token counts: /tokenize against the product's estimates | 1/2 | FAIL | 10.4 | `g5-tokens.png` |
| g7-clipped | G-7 clipped against whole note (LLM-001) | 2/2 | pass | 26.0 | `g7-clipped.png` |
| hospital-ja | 0 data in | 5/5 | pass | 0.4 | `hospital-ja-00.png` |
| hospital-ja | 1 feasibility report | 8/8 | pass | 0.6 | `hospital-ja-01.png` |
| hospital-ja | 2 investigator approval | 2/2 | pass | 0.1 | `hospital-ja-02.png` |
| hospital-ja | 3 screening | 7/7 | pass | 0.0 | `hospital-ja-03.png` |
| hospital-ja | 4 list, marks and mail | 7/7 | pass | 6.0 | `hospital-ja-04.png` |
| hospital-ja | 5 ready and needs-information lists | 9/9 | pass | 2.3 | `hospital-ja-05.png` |
| hospital-ja | 7 REDCap read-back and screening log | 5/5 | pass | 0.1 | `hospital-ja-06.png` |
| hospital-ja | audit | 14/14 | pass | 11.4 | `hospital-ja-07.png` |
| hospital-ja | 8 REDCap write-back | 12/12 | pass | 0.7 | `hospital-ja-08.png` |
| hospital-ja | 9 data core: REDCap off then on, conflicts, a PI's sheet | 13/13 | pass | 0.2 | `hospital-ja-09.png` |
| hospital-ja | 10 built-in data capture | 15/15 | pass | 2.1 | `hospital-ja-10.png` |
| hospital-ja | 11 trial lifecycle | 25/25 | pass | 19.2 | `hospital-ja-11.png` |
| hospital-ja | 12 site set-up and data harmonization | 24/25 | FAIL | 36.3 | `hospital-ja-12.png` |
| hospital-ja | 13 Japan: SS-MIX2, JP Core and the licensed code lists | 16/16 | pass | 8.5 | `hospital-ja-13.png` |
| hospital-ja | 14 ClinicalTrials.gov offline: the reference data pack | 12/12 | pass | 0.7 | `hospital-ja-14.png` |
| hospital-ja | re-run (FR-REP-02) | 2/2 | pass | 15.7 | `hospital-ja-15.png` |
| hospital-ja | 15 delegation, candidates and referral | 17/17 | pass | 964.9 | `hospital-ja-16.png` |
| hospital-ja | 16 EDC prefill | 22/22 | pass | 14.1 | `hospital-ja-17.png` |
| hospital-ja | 17 screening cadence: in Tuesday's data, booked Friday, listed Wednesday | 10/10 | pass | 273.3 | `hospital-ja-18.png` |
| hospital-ja | runtime | 1/1 | pass | 0.0 | `hospital-ja-19.png` |
| hospital-ja | db-csv: model exclusions against the generator's note truth | 1/1 | pass | 0 | `hospital-ja-20.png` |
| hospital-zh-TW | 0 data in | 5/5 | pass | 0.4 | `hospital-zh-TW-00.png` |
| hospital-zh-TW | 1 feasibility report | 8/8 | pass | 0.6 | `hospital-zh-TW-01.png` |
| hospital-zh-TW | 2 investigator approval | 2/2 | pass | 0.1 | `hospital-zh-TW-02.png` |
| hospital-zh-TW | 3 screening | 7/7 | pass | 0.0 | `hospital-zh-TW-03.png` |
| hospital-zh-TW | 4 list, marks and mail | 7/7 | pass | 5.7 | `hospital-zh-TW-04.png` |
| hospital-zh-TW | 5 ready and needs-information lists | 9/9 | pass | 7.8 | `hospital-zh-TW-05.png` |
| hospital-zh-TW | 7 REDCap read-back and screening log | 5/5 | pass | 0.1 | `hospital-zh-TW-06.png` |
| hospital-zh-TW | audit | 14/14 | pass | 11.6 | `hospital-zh-TW-07.png` |
| hospital-zh-TW | 8 REDCap write-back | 12/12 | pass | 0.7 | `hospital-zh-TW-08.png` |
| hospital-zh-TW | 9 data core: REDCap off then on, conflicts, a PI's sheet | 13/13 | pass | 0.2 | `hospital-zh-TW-09.png` |
| hospital-zh-TW | 10 built-in data capture | 15/15 | pass | 2.2 | `hospital-zh-TW-10.png` |
| hospital-zh-TW | 11 trial lifecycle | 25/25 | pass | 13.7 | `hospital-zh-TW-11.png` |
| hospital-zh-TW | 12 site set-up and data harmonization | 24/25 | FAIL | 39.3 | `hospital-zh-TW-12.png` |
| hospital-zh-TW | 13 Japan: SS-MIX2, JP Core and the licensed code lists | 16/16 | pass | 14.0 | `hospital-zh-TW-13.png` |
| hospital-zh-TW | 14 ClinicalTrials.gov offline: the reference data pack | 12/12 | pass | 0.8 | `hospital-zh-TW-14.png` |
| hospital-zh-TW | re-run (FR-REP-02) | 2/2 | pass | 10.4 | `hospital-zh-TW-15.png` |
| hospital-zh-TW | 15 delegation, candidates and referral | 17/17 | pass | 987.6 | `hospital-zh-TW-16.png` |
| hospital-zh-TW | 16 EDC prefill | 22/22 | pass | 5.5 | `hospital-zh-TW-17.png` |
| hospital-zh-TW | 17 screening cadence: in Tuesday's data, booked Friday, listed Wednesday | 10/10 | pass | 268.7 | `hospital-zh-TW-18.png` |
| hospital-zh-TW | runtime | 1/1 | pass | 0.0 | `hospital-zh-TW-19.png` |
| hospital-zh-TW | db-csv: model exclusions against the generator's note truth | 1/1 | pass | 0 | `hospital-zh-TW-20.png` |

## Scenarios

### db-csv: Hospital database feed (CGRD-style CSV)

**FAIL**: 454 of 456 checks.

* Input (ja): CGRD-style CSV export of 50,000 synthetic patients (two sites, JP and TW style)
* Counts: `{"patients": 50000, "screen_funnel": {"S0": 30369, "S1": 1193, "S3": 1193, "S4": 627}}`
* Expected: `"e2e_simple stages 0-1: lake = generator counts; FEAS INC-01/02 = recount from the CSVs"`
* Got: `{"0 data in": "5/5", "1 feasibility report": "8/8"}`
* Model calls: 6395
* Model exclusions: 463 (true 463, false 0, true ones missed 6)
  * `0022a3ef8c` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `01438c25c0` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0165cc61c3` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `01edb4e6e9` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `01ee48e27d` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `024c061351` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `03b8250b29` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `040ff0410e` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0494577805` GZQO-EXC-11: truth {'GZQO-EXC-11': 'yes'}, correct
  * `0501ca52d8` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0511b84955` GZQO-EXC-11: truth {'GZQO-EXC-11': 'yes'}, correct
  * `05fb8533d8` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `062c93825b` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `07203c7e1b` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `077fc3953e` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `079c744313` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `087cd4c87c` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `097bd2186f` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0995eef06a` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `09bffea94d` GZQO-EXC-11: truth {'GZQO-EXC-11': 'yes'}, correct
* Time: 2986.1 s. Screenshot: `hospital-ja-00.png`, `hospital-ja-01.png`, `hospital-ja-02.png`
* FAILED (hospital-ja / 12 site set-up and data harmonization): confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})

* Input (zh-TW): CGRD-style CSV export of 50,000 synthetic patients (two sites, JP and TW style)
* Counts: `{"patients": 50000, "screen_funnel": {"S0": 30369, "S1": 1193, "S3": 1193, "S4": 628}}`
* Expected: `"e2e_simple stages 0-1: lake = generator counts; FEAS INC-01/02 = recount from the CSVs"`
* Got: `{"0 data in": "5/5", "1 feasibility report": "8/8"}`
* Model calls: 6364
* Model exclusions: 462 (true 462, false 0, true ones missed 7)
  * `0022a3ef8c` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `01438c25c0` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0165cc61c3` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `01edb4e6e9` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `01ee48e27d` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `024c061351` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `03b8250b29` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `040ff0410e` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0494577805` GZQO-EXC-11: truth {'GZQO-EXC-11': 'yes'}, correct
  * `0501ca52d8` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0511b84955` GZQO-EXC-11: truth {'GZQO-EXC-11': 'yes'}, correct
  * `05fb8533d8` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `062c93825b` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `07203c7e1b` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `077fc3953e` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `079c744313` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `087cd4c87c` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `097bd2186f` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0995eef06a` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `09bffea94d` GZQO-EXC-11: truth {'GZQO-EXC-11': 'yes'}, correct
* Time: 2990.7 s. Screenshot: `hospital-zh-TW-00.png`, `hospital-zh-TW-01.png`, `hospital-zh-TW-02.png`
* FAILED (hospital-zh-TW / 12 site set-up and data harmonization): confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})


## Throughput (model calls through the gateway)

Calls and tokens per second are over the seconds in which a call was in flight (the gateway's audit); the servers' `/metrics` before and after, `gpu.csv` (every 10 s) and `vllm.csv` are in `parts/<part>/`. A hospital part has two rows: **main SCREEN** (the SCREEN job's own window: the throughput of the curve) and **whole part** (with the canary's one-at-a-time calls and stages 15 and 17). GPU % is `nvidia-smi` utilisation, the share of time a kernel ran: not a headroom measure (a card at 100 % may take more calls). KV peak: each server's KV-cache usage peak (vllm.csv). Not measured: the gateway's slot wait per call (the gateway does not record it).

| part | window | in flight | calls | calls/s | tokens/s | p50 s | p95 s | queue s (vLLM) | GPU % mean | GPU % max | KV peak | GPU MiB peak | breaker opened | listed | list sha256 | refused (of asked) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| g4-decoding | whole part | 16 | 0 | - | - | - | - | judge 0.1608 | 23.0 | 48.0 | judge 0.02109717722558946, verifier 0.0 | 62582.0 | - | - | `-` | - |
| g5-tokens | whole part | 16 | 0 | - | - | - | - | - | 0.0 | 0.0 | judge 0.0, verifier 0.0 | 62582.0 | - | - | `-` | - |
| g7-clipped | whole part | 16 | 14 | 0.554 | 1360.642 | 1.627 | 2.524 | judge 0.0014, verifier 0.207 | 29.5 | 42.0 | judge 0.006681031141975824, verifier 0.009345794392523366 | 62590.0 | 0 | - | `-` | 0 of 14 |
| hospital-ja | main SCREEN | 16 | 3226 | 4.447 | 5213.022 | 3.221 | 5.116 | judge 0.0001, verifier 0.0002 | 71.0 | 96.0 | judge 0.06414409945590671, verifier 0.14641744548286606 | 62968.0 | 0 | 627 | `964a677dd1f0` | 0 of 6568 |
| hospital-ja | whole part | 16 | 6568 | 3.876 | 4497.205 | 3.191 | 5.084 | judge 0.0001, verifier 0.0002 | 48.0 | 97.0 | judge 0.07091813799197033, verifier 0.14953271028037385 | 62968.0 | 0 | 627 | `964a677dd1f0` | 0 of 6568 |
| hospital-zh-TW | main SCREEN | 16 | 3217 | 4.558 | 5325.943 | 3.187 | 5.013 | judge 0.0001, verifier 0.0 | 70.7 | 97.0 | judge 0.07087163429492649, verifier 0.12928348909657317 | 62968.0 | 0 | 628 | `a6686bfc1ee7` | 0 of 6550 |
| hospital-zh-TW | whole part | 16 | 6550 | 3.934 | 4555.476 | 3.175 | 5.056 | judge 0.0001, verifier 0.0 | 46.9 | 97.0 | judge 0.07380136720869312, verifier 0.12928348909657317 | 62968.0 | 0 | 628 | `a6686bfc1ee7` | 0 of 6550 |

## Review tests G-4, G-5, G-7, G-8 (plan v7 §7.1)

### G-4 (g4-decoding)

Structured-output backend: **auto** (the serving record (the container's command line)). Eager start: needs a restart: not run (--enforce-eager is a start flag; the part never restarts a server) (record: enforce_eager True).

| setting | calls | answered | calls/s | p50 s | p95 s | schema failures |
| --- | --- | --- | --- | --- | --- | --- |
| guided on | 64 | 64 | 3.79 | 2.7008 | 9.0476 | 1 |
| guided off | 64 | 64 | 7.532 | 1.79 | 4.1587 | 64 |

Profile: guided decoding on (16 in flight, 64 prompts each way).

guided on: answers outside the schema by finish_reason: stop 1; the first 1 (finish_reason, completion tokens, the first 200 characters):

- stop, 67 tokens: `"{\n \"verdict\": \"unknown\",\n \"reason\": \"The provided excerpt does not contain any information regarding gout flares or a diagnosis of gout.\",\n \"quote\": \"unknown\",\n \"quote_date\": \"0000-01-01\",\n \"confidenc"`

guided off: answers outside the schema by finish_reason: stop 64; the first 5 (finish_reason, completion tokens, the first 200 characters):

- stop, 64 tokens: `"\u0060\u0060\u0060json\n{\n \"answer\": \"fail\",\n \"quote\": \"過去一年間に痛風発作はなく、関節の発赤・腫脹もない。\",\n \"quote_date\": \"2026-06-01\",\n \"confidence\": 1.0\n}\n\u0060\u0060\u0060"`
- stop, 74 tokens: `"\u0060\u0060\u0060json\n{\n \"answer\": \"unknown\",\n \"quote\": \"ベースラインと比べDAS28は0.5低下し、治療反応は良好。生物学的製剤を継続する。\",\n \"quote_date\": \"2026-06-02\",\n \"confidence\": 1.0\n}\n\u0060\u0060\u0060"`
- stop, 76 tokens: `"\u0060\u0060\u0060json\n{\n \"answer\": \"unknown\",\n \"quote\": \"現在、右第一中足趾節関節に急性の発赤・腫脹・疼痛あり、急性痛風発作中である。\",\n \"quote_date\": \"2026-06-03\",\n \"confidence\": 1.0\n}\n\u0060\u0060\u0060"`
- stop, 87 tokens: `"\u0060\u0060\u0060json\n{\n \"answer\": \"unknown\",\n \"quote\": \"2025年12月1日に右足関節の発赤・腫脹・熱感・疼痛あり、急性痛風発作と診断しコルヒチンで改善した。\",\n \"quote_date\": \"2026-06-04\",\n \"confidence\": 0.8\n}\n\u0060\u0060\u0060"`
- stop, 238 tokens: `"\u0060\u0060\u0060json\n{\n \"answer\": \"pass\",\n \"quote\": \"令和8年2月3日に左膝関節の発赤・腫脹・熱感・疼痛あり、急性痛風発作と診断しコルヒチンで改善した。\",\n \"quote_date\": \"2026-06-05\",\n \"confidence\": 1.0\n}\n\u0060\u0060\u0060\n\n**Note on reasoning:** The note dated 2026-06-05 (whi"`

### G-5 (g5-tokens)

| language | estimator | n | p50 | p95 | max |
| --- | --- | --- | --- | --- | --- |
| ja | budget | 200 | 0.7477 | 0.8443 | 0.9412 |
| ja | cascade | 200 | 0.753 | 0.8571 | 0.9697 |
| ja | prompt | 200 | 0.9398 | 1.0028 | 1.0188 |
| zh-TW | budget | 200 | 0.8577 | 0.9552 | 1.1111 |
| zh-TW | cascade | 200 | 0.9064 | 1.0159 | 1.2121 |
| zh-TW | prompt | 200 | 0.9806 | 1.014 | 1.032 |

Largest ratio 1.2121 x 1.05 against 1 / SAFETY = 1.1765: **DOES NOT FIT**; SAFETY from this measurement: 0.7857.

### G-7 (g7-clipped)

| case | clipped | left out | view | judge | verifier | pair | final |
| --- | --- | --- | --- | --- | --- | --- | --- |
| LLM-001-ja-family-history | True | 1 | clipped | unknown | unknown | unknown | review |
| LLM-001-ja-family-history | True | 0 | whole | unknown | unknown | unknown | review |
| LLM-001-zh-TW-denied-list | True | 1 | clipped | fail | fail | fail | met |
| LLM-001-zh-TW-denied-list | True | 0 | whole | fail | fail | fail | met |

Final not met from a clipped note: **none**.


## Part times

| part | wall seconds |
| --- | --- |
| prepare | 16.4 |
| g4-decoding | 26.1 |
| g5-tokens | 10.9 |
| g7-clipped | 26.5 |
| hospital-ja | 2986.1 |
| hospital-zh-TW | 2990.7 |

## Failed checks

Each detail is cut at 300 characters here (TB_REPORT_DETAIL_CHARS); the whole detail of each is in `failed-checks.json` beside this report (as the part recorded it).

- g4-decoding / G-4 structured output: backend, guided decoding on and off, eager start: guided on: no answer outside the judge schema: 1
- g5-tokens / G-5 token counts: /tokenize against the product's estimates: the largest real / estimated ratio x 1.05 fits the budget's share (1 / SAFETY = 1.176): {'max_ratio': 1.2121, 'safety_from_measurement': 0.7857}
- hospital-ja / 12 site set-up and data harmonization: confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})
- hospital-zh-TW / 12 site set-up and data harmonization: confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})

## hospital-ja: screen

```json
{"funnel": [["S0", 30369], ["S1", 1193], ["S3", 1193], ["S4", 627]], "tiers": {"excluded": 29742, "high": 32, "review": 595}, "listed": 627, "judging": {"configured_note_block": "both_agree", "disagreements": 13, "failures": 11, "judge_model": "local/gemma-4-26b-a4b-nvfp4", "may_block": true, "mode": "agreement", "note_block": "both_agree", "note_block_code": "ok", "note_block_reason": "judge and verifier must both say fail", "verifier_model": "local/qwen3.5-9b-awq"}, "window": {"from": 1794561204.195836, "to": 1794562151.189515, "from_at": "2026-11-13T17:13:24.195836+08:00", "to_at": "2026-11-13T17:29:11.189515+08:00"}}
```

## hospital-ja: canary

```json
{"gate": "on", "allows_block": true, "code": "ok", "reason": "", "running": false, "at": "2026-11-13T09:13:09", "ok": true, "cases": 54, "pair_correct": 53, "pair_decided_wrong": 0, "models": [{"role": "judge", "model": "local/gemma-4-26b-a4b-nvfp4", "correct": 54, "flips": 0, "ok": true}, {"role": "verifier", "model": "local/qwen3.5-9b-awq", "correct": 49, "flips": 1, "ok": true}], "wake_failure": null}
```

## hospital-zh-TW: screen

```json
{"funnel": [["S0", 30369], ["S1", 1193], ["S3", 1193], ["S4", 628]], "tiers": {"excluded": 29741, "high": 33, "review": 595}, "listed": 628, "judging": {"configured_note_block": "both_agree", "disagreements": 13, "failures": 14, "judge_model": "local/gemma-4-26b-a4b-nvfp4", "may_block": true, "mode": "agreement", "note_block": "both_agree", "note_block_code": "ok", "note_block_reason": "judge and verifier must both say fail", "verifier_model": "local/qwen3.5-9b-awq"}, "window": {"from": 1794564211.801495, "to": 1794565138.385137, "from_at": "2026-11-13T18:03:31.801495+08:00", "to_at": "2026-11-13T18:18:58.385137+08:00"}}
```

## hospital-zh-TW: canary

```json
{"gate": "on", "allows_block": true, "code": "ok", "reason": "", "running": false, "at": "2026-11-13T10:03:17", "ok": true, "cases": 54, "pair_correct": 53, "pair_decided_wrong": 0, "models": [{"role": "judge", "model": "local/gemma-4-26b-a4b-nvfp4", "correct": 54, "flips": 0, "ok": true}, {"role": "verifier", "model": "local/qwen3.5-9b-awq", "correct": 49, "flips": 1, "ok": true}], "wake_failure": null}
```
