# TrialBox complete-platform run

Head `931a0f79540c` (Merge master into fix/g1-canary-rehearsal). Run: 20261112T165042Z-931a0f79-s1. Model: local/gemma-4-26b-a4b-nvfp4, local/qwen3.5-9b-awq (gateway (installed box, synthetic weight pins)). Hospital: 5,000 synthetic patients. Languages: ja, zh-TW. OCR: tesseract. Model calls in flight: 1, 4, 16, 48. Host: x86_64, 48 CPUs.
Started 2026-11-12T18:10:29+00:00, finished 2026-11-12T18:10:29+00:00.

**FAILED**: 919 of 925 checks; 90 of 90 screenshots; 62.9 min in all; 0 known findings reported.

Screenshots are in the run's `report/shots/` folder (not committed).

| part | stage | checks | result | seconds | screenshot |
| --- | --- | --- | --- | --- | --- |
| prepare | synthetic hospital | 2/2 | pass | 1.4 | `prepare.png` |
| install | install: tier and serving record | 4/4 | pass | 0.0 | `install.png` |
| chat-template | G-1 chat template: the passed file against the weights folder's own | 3/5 | FAIL | 5.3 | `chat-template.png` |
| hospital-ja@c1 | 0 data in | 5/5 | pass | 0.4 | `hospital-ja@c1-00.png` |
| hospital-ja@c1 | 1 feasibility report | 8/8 | pass | 0.1 | `hospital-ja@c1-01.png` |
| hospital-ja@c1 | 2 investigator approval | 2/2 | pass | 0.1 | `hospital-ja@c1-02.png` |
| hospital-ja@c1 | 3 screening | 7/7 | pass | 0.0 | `hospital-ja@c1-03.png` |
| hospital-ja@c1 | 4 list, marks and mail | 7/7 | pass | 0.8 | `hospital-ja@c1-04.png` |
| hospital-ja@c1 | 5 ready and needs-information lists | 9/9 | pass | 2.0 | `hospital-ja@c1-05.png` |
| hospital-ja@c1 | 7 REDCap read-back and screening log | 5/5 | pass | 0.1 | `hospital-ja@c1-06.png` |
| hospital-ja@c1 | audit | 14/14 | pass | 1.0 | `hospital-ja@c1-07.png` |
| hospital-ja@c1 | 8 REDCap write-back | 12/12 | pass | 0.7 | `hospital-ja@c1-08.png` |
| hospital-ja@c1 | 9 data core: REDCap off then on, conflicts, a PI's sheet | 13/13 | pass | 0.2 | `hospital-ja@c1-09.png` |
| hospital-ja@c1 | 10 built-in data capture | 15/15 | pass | 1.2 | `hospital-ja@c1-10.png` |
| hospital-ja@c1 | 11 trial lifecycle | 25/25 | pass | 4.1 | `hospital-ja@c1-11.png` |
| hospital-ja@c1 | 12 site set-up and data harmonization | 22/23 | FAIL | 38.3 | `hospital-ja@c1-12.png` |
| hospital-ja@c1 | 13 Japan: SS-MIX2, JP Core and the licensed code lists | 16/16 | pass | 8.6 | `hospital-ja@c1-13.png` |
| hospital-ja@c1 | 14 ClinicalTrials.gov offline: the reference data pack | 12/12 | pass | 1.4 | `hospital-ja@c1-14.png` |
| hospital-ja@c1 | re-run (FR-REP-02) | 2/2 | pass | 5.2 | `hospital-ja@c1-15.png` |
| hospital-ja@c1 | 15 delegation, candidates and referral | 16/16 | pass | 697.2 | `hospital-ja@c1-16.png` |
| hospital-ja@c1 | 16 EDC prefill | 22/22 | pass | 5.4 | `hospital-ja@c1-17.png` |
| hospital-ja@c1 | 17 screening cadence: in Tuesday's data, booked Friday, listed Wednesday | 10/10 | pass | 43.4 | `hospital-ja@c1-18.png` |
| hospital-ja@c1 | runtime | 1/1 | pass | 0.0 | `hospital-ja@c1-19.png` |
| hospital-ja@c1 | db-csv: model exclusions against the generator's note truth | 1/1 | pass | 0 | `hospital-ja@c1-20.png` |
| hospital-ja@c4 | 0 data in | 5/5 | pass | 0.4 | `hospital-ja@c4-00.png` |
| hospital-ja@c4 | 1 feasibility report | 8/8 | pass | 0.1 | `hospital-ja@c4-01.png` |
| hospital-ja@c4 | 2 investigator approval | 2/2 | pass | 0.1 | `hospital-ja@c4-02.png` |
| hospital-ja@c4 | 3 screening | 7/7 | pass | 0.0 | `hospital-ja@c4-03.png` |
| hospital-ja@c4 | 4 list, marks and mail | 7/7 | pass | 0.8 | `hospital-ja@c4-04.png` |
| hospital-ja@c4 | 5 ready and needs-information lists | 9/9 | pass | 1.3 | `hospital-ja@c4-05.png` |
| hospital-ja@c4 | 7 REDCap read-back and screening log | 5/5 | pass | 0.1 | `hospital-ja@c4-06.png` |
| hospital-ja@c4 | audit | 14/14 | pass | 1.0 | `hospital-ja@c4-07.png` |
| hospital-ja@c4 | 8 REDCap write-back | 12/12 | pass | 0.7 | `hospital-ja@c4-08.png` |
| hospital-ja@c4 | 9 data core: REDCap off then on, conflicts, a PI's sheet | 13/13 | pass | 0.2 | `hospital-ja@c4-09.png` |
| hospital-ja@c4 | 10 built-in data capture | 15/15 | pass | 1.8 | `hospital-ja@c4-10.png` |
| hospital-ja@c4 | 11 trial lifecycle | 25/25 | pass | 4.2 | `hospital-ja@c4-11.png` |
| hospital-ja@c4 | 12 site set-up and data harmonization | 22/23 | FAIL | 37.5 | `hospital-ja@c4-12.png` |
| hospital-ja@c4 | 13 Japan: SS-MIX2, JP Core and the licensed code lists | 16/16 | pass | 8.3 | `hospital-ja@c4-13.png` |
| hospital-ja@c4 | 14 ClinicalTrials.gov offline: the reference data pack | 12/12 | pass | 1.3 | `hospital-ja@c4-14.png` |
| hospital-ja@c4 | re-run (FR-REP-02) | 2/2 | pass | 5.0 | `hospital-ja@c4-15.png` |
| hospital-ja@c4 | 15 delegation, candidates and referral | 16/16 | pass | 191.6 | `hospital-ja@c4-16.png` |
| hospital-ja@c4 | 16 EDC prefill | 22/22 | pass | 5.0 | `hospital-ja@c4-17.png` |
| hospital-ja@c4 | 17 screening cadence: in Tuesday's data, booked Friday, listed Wednesday | 10/10 | pass | 42.5 | `hospital-ja@c4-18.png` |
| hospital-ja@c4 | runtime | 1/1 | pass | 0.0 | `hospital-ja@c4-19.png` |
| hospital-ja@c4 | db-csv: model exclusions against the generator's note truth | 1/1 | pass | 0 | `hospital-ja@c4-20.png` |
| hospital-ja@c16 | 0 data in | 5/5 | pass | 0.4 | `hospital-ja@c16-00.png` |
| hospital-ja@c16 | 1 feasibility report | 8/8 | pass | 0.1 | `hospital-ja@c16-01.png` |
| hospital-ja@c16 | 2 investigator approval | 2/2 | pass | 0.1 | `hospital-ja@c16-02.png` |
| hospital-ja@c16 | 3 screening | 7/7 | pass | 0.0 | `hospital-ja@c16-03.png` |
| hospital-ja@c16 | 4 list, marks and mail | 7/7 | pass | 0.8 | `hospital-ja@c16-04.png` |
| hospital-ja@c16 | 5 ready and needs-information lists | 9/9 | pass | 1.3 | `hospital-ja@c16-05.png` |
| hospital-ja@c16 | 7 REDCap read-back and screening log | 5/5 | pass | 0.1 | `hospital-ja@c16-06.png` |
| hospital-ja@c16 | audit | 14/14 | pass | 1.0 | `hospital-ja@c16-07.png` |
| hospital-ja@c16 | 8 REDCap write-back | 12/12 | pass | 0.7 | `hospital-ja@c16-08.png` |
| hospital-ja@c16 | 9 data core: REDCap off then on, conflicts, a PI's sheet | 13/13 | pass | 0.2 | `hospital-ja@c16-09.png` |
| hospital-ja@c16 | 10 built-in data capture | 15/15 | pass | 1.2 | `hospital-ja@c16-10.png` |
| hospital-ja@c16 | 11 trial lifecycle | 25/25 | pass | 4.8 | `hospital-ja@c16-11.png` |
| hospital-ja@c16 | 12 site set-up and data harmonization | 22/23 | FAIL | 38.1 | `hospital-ja@c16-12.png` |
| hospital-ja@c16 | 13 Japan: SS-MIX2, JP Core and the licensed code lists | 16/16 | pass | 8.4 | `hospital-ja@c16-13.png` |
| hospital-ja@c16 | 14 ClinicalTrials.gov offline: the reference data pack | 12/12 | pass | 1.3 | `hospital-ja@c16-14.png` |
| hospital-ja@c16 | re-run (FR-REP-02) | 2/2 | pass | 5.1 | `hospital-ja@c16-15.png` |
| hospital-ja@c16 | 15 delegation, candidates and referral | 16/16 | pass | 71.9 | `hospital-ja@c16-16.png` |
| hospital-ja@c16 | 16 EDC prefill | 22/22 | pass | 5.9 | `hospital-ja@c16-17.png` |
| hospital-ja@c16 | 17 screening cadence: in Tuesday's data, booked Friday, listed Wednesday | 10/10 | pass | 41.0 | `hospital-ja@c16-18.png` |
| hospital-ja@c16 | runtime | 1/1 | pass | 0.0 | `hospital-ja@c16-19.png` |
| hospital-ja@c16 | db-csv: model exclusions against the generator's note truth | 1/1 | pass | 0 | `hospital-ja@c16-20.png` |
| hospital-ja@c48 | 0 data in | 5/5 | pass | 0.4 | `hospital-ja@c48-00.png` |
| hospital-ja@c48 | 1 feasibility report | 8/8 | pass | 0.1 | `hospital-ja@c48-01.png` |
| hospital-ja@c48 | 2 investigator approval | 2/2 | pass | 0.1 | `hospital-ja@c48-02.png` |
| hospital-ja@c48 | 3 screening | 7/7 | pass | 0.0 | `hospital-ja@c48-03.png` |
| hospital-ja@c48 | 4 list, marks and mail | 7/7 | pass | 0.8 | `hospital-ja@c48-04.png` |
| hospital-ja@c48 | 5 ready and needs-information lists | 9/9 | pass | 1.3 | `hospital-ja@c48-05.png` |
| hospital-ja@c48 | 7 REDCap read-back and screening log | 5/5 | pass | 0.1 | `hospital-ja@c48-06.png` |
| hospital-ja@c48 | audit | 14/14 | pass | 1.0 | `hospital-ja@c48-07.png` |
| hospital-ja@c48 | 8 REDCap write-back | 12/12 | pass | 0.7 | `hospital-ja@c48-08.png` |
| hospital-ja@c48 | 9 data core: REDCap off then on, conflicts, a PI's sheet | 13/13 | pass | 0.2 | `hospital-ja@c48-09.png` |
| hospital-ja@c48 | 10 built-in data capture | 15/15 | pass | 1.2 | `hospital-ja@c48-10.png` |
| hospital-ja@c48 | 11 trial lifecycle | 25/25 | pass | 4.7 | `hospital-ja@c48-11.png` |
| hospital-ja@c48 | 12 site set-up and data harmonization | 22/23 | FAIL | 38.0 | `hospital-ja@c48-12.png` |
| hospital-ja@c48 | 13 Japan: SS-MIX2, JP Core and the licensed code lists | 16/16 | pass | 8.4 | `hospital-ja@c48-13.png` |
| hospital-ja@c48 | 14 ClinicalTrials.gov offline: the reference data pack | 12/12 | pass | 1.3 | `hospital-ja@c48-14.png` |
| hospital-ja@c48 | re-run (FR-REP-02) | 2/2 | pass | 5.1 | `hospital-ja@c48-15.png` |
| hospital-ja@c48 | 15 delegation, candidates and referral | 16/16 | pass | 58.9 | `hospital-ja@c48-16.png` |
| hospital-ja@c48 | 16 EDC prefill | 22/22 | pass | 5.0 | `hospital-ja@c48-17.png` |
| hospital-ja@c48 | 17 screening cadence: in Tuesday's data, booked Friday, listed Wednesday | 10/10 | pass | 42.3 | `hospital-ja@c48-18.png` |
| hospital-ja@c48 | runtime | 1/1 | pass | 0.0 | `hospital-ja@c48-19.png` |
| hospital-ja@c48 | db-csv: model exclusions against the generator's note truth | 1/1 | pass | 0 | `hospital-ja@c48-20.png` |
| scenario-emr-fhir | FHIR: bulk export in, chart numbers out, the funnel | 6/6 | pass | 9.1 | `scenario-emr-fhir-00.png` |
| scenario-emr-fhir | FHIR: screening with the run's model | 5/5 | pass | 252.9 | `scenario-emr-fhir-01.png` |
| scenario-gateway | installed-box gateway: a judge call and a chart-reading call | 3/3 | pass | 4.4 | `scenario-gateway.png` |

## Scenarios

### db-csv: Hospital database feed (CGRD-style CSV)

**FAIL**: 896 of 900 checks.

* Input (ja@c1): CGRD-style CSV export of 5,000 synthetic patients (two sites, JP and TW style)
* Counts: `{"patients": 5000, "screen_funnel": {"S0": 3022, "S1": 92, "S3": 92, "S4": 54}}`
* Expected: `"e2e_simple stages 0-1: lake = generator counts; FEAS INC-01/02 = recount from the CSVs"`
* Got: `{"0 data in": "5/5", "1 feasibility report": "8/8"}`
* Model calls: 625
* Model exclusions: 0 (true 0, false 0, true ones missed 0)
* Time: 1744.3 s. Screenshot: `hospital-ja@c1-00.png`, `hospital-ja@c1-01.png`, `hospital-ja@c1-02.png`

* Input (ja@c4): CGRD-style CSV export of 5,000 synthetic patients (two sites, JP and TW style)
* Counts: `{"patients": 5000, "screen_funnel": {"S0": 3022, "S1": 92, "S3": 92, "S4": 54}}`
* Expected: `"e2e_simple stages 0-1: lake = generator counts; FEAS INC-01/02 = recount from the CSVs"`
* Got: `{"0 data in": "5/5", "1 feasibility report": "8/8"}`
* Model calls: 619
* Model exclusions: 0 (true 0, false 0, true ones missed 0)
* Time: 757.1 s. Screenshot: `hospital-ja@c4-00.png`, `hospital-ja@c4-01.png`, `hospital-ja@c4-02.png`

* Input (ja@c16): CGRD-style CSV export of 5,000 synthetic patients (two sites, JP and TW style)
* Counts: `{"patients": 5000, "screen_funnel": {"S0": 3022, "S1": 92, "S3": 92, "S4": 55}}`
* Expected: `"e2e_simple stages 0-1: lake = generator counts; FEAS INC-01/02 = recount from the CSVs"`
* Got: `{"0 data in": "5/5", "1 feasibility report": "8/8"}`
* Model calls: 623
* Model exclusions: 0 (true 0, false 0, true ones missed 0)
* Time: 512.4 s. Screenshot: `hospital-ja@c16-00.png`, `hospital-ja@c16-01.png`, `hospital-ja@c16-02.png`

* Input (ja@c48): CGRD-style CSV export of 5,000 synthetic patients (two sites, JP and TW style)
* Counts: `{"patients": 5000, "screen_funnel": {"S0": 3022, "S1": 92, "S3": 92, "S4": 55}}`
* Expected: `"e2e_simple stages 0-1: lake = generator counts; FEAS INC-01/02 = recount from the CSVs"`
* Got: `{"0 data in": "5/5", "1 feasibility report": "8/8"}`
* Model calls: 629
* Model exclusions: 0 (true 0, false 0, true ones missed 0)
* Time: 484.8 s. Screenshot: `hospital-ja@c48-00.png`, `hospital-ja@c48-01.png`, `hospital-ja@c48-02.png`
* FAILED: confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f
* FAILED: confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f
* FAILED: confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f
* FAILED: confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f

### emr-fhir: EMR: FHIR bulk export

**pass**: 11 of 11 checks.

* Input: FHIR bulk export of 500 patients (15,419 resources, NDJSON)
* Counts: `{"Appointment": 317, "Claim": 80, "ClaimResponse": 80, "Condition": 1398, "Consent": 318, "Coverage": 500, "DiagnosticReport": 59, "DocumentReference": 875, "Encounter": 3397, "MedicationRequest": 4483, "Observation": 3397, "Organization": 2, "Patient": 500, "Practitioner": 8, "Procedure": 5}`
* Expected: `{"start": 500, "GZQO-INC-01": 484, "GZQO-INC-02": 144}`
* Got: `{"start": 500, "GZQO-INC-01": 484, "GZQO-INC-02": 144}`
* Model calls: 16
* Model exclusions: 1 (true 1, false 0, true ones missed 0)
  * `0d445f7540` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
* Screening: `{"funnel": {"S0": 311, "S1": 8, "S3": 8, "S4": 7}, "tiers": {"excluded": 304, "high": 0, "review": 7}, "listed": 7, "judging": {"configured_note_block": "both_agree", "disagreements": 0, "failures": 0, "judge_model": "local/gemma-4-26b-a4b-nvfp4", "may_block": true, "mode": "agreement", "note_block": "both_agree", "note_block_code": "ok", "note_block_reason": "judge and verifier must both say fail`
* Time: 263.3 s. Screenshot: `scenario-emr-fhir-00.png`, `scenario-emr-fhir-01.png`

### gateway: Probe: the installed box's model gateway

**pass**: 3 of 3 checks.

* Input: TB_ENV=PRODUCTION, TB_PROFILE=P-PRO6000, no TB_DATA_CLASS (as install.sh leaves it)
* Counts: `{}`
* Expected: `{"judge": "answered", "chart_facts": "answered"}`
* Got: `{"judge": "answered", "chart_facts": "answered"}`
* Model calls: 0
* Time: 5.1 s. Screenshot: `scenario-gateway.png`


## Throughput (model calls through the gateway)

Calls and tokens per second are over the seconds in which a call was in flight (the gateway's audit); the servers' `/metrics` before and after, `gpu.csv` (every 10 s) and `vllm.csv` are in `parts/<part>/`.

| part | in flight | calls | calls/s | tokens/s | p50 s | p95 s | queue s (vLLM) | GPU % mean | GPU MiB peak | breaker opened | listed | list sha256 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| chat-template | 1 | 0 | - | - | - | - | - | 0.0 | 62576.0 | - | - | `-` |
| hospital-ja@c1 | 1 | 628 | 0.4 | 377.846 | 2.182 | 3.9 | judge 0.0061, verifier 0.0052 | 33.2 | 62590.0 | 0 | 1 | `632590f638de` |
| hospital-ja@c4 | 4 | 623 | 1.041 | 976.043 | 2.291 | 4.07 | judge 0.0003, verifier 0.0005 | 49.4 | 62592.0 | 0 | 1 | `632590f638de` |
| hospital-ja@c16 | 16 | 626 | 1.774 | 1670.776 | 2.46 | 4.462 | judge 0.0002, verifier 0.0004 | 32.6 | 62592.0 | 0 | 1 | `632590f638de` |
| hospital-ja@c48 | 48 | 633 | 1.947 | 1847.379 | 2.601 | 4.682 | judge 0.0002, verifier 0.0002 | 32.1 | 62592.0 | 0 | 1 | `632590f638de` |
| scenario-emr-fhir | 1 | 0 | - | - | - | - | judge 0.0013, verifier 0.0012 | 31.1 | 62592.0 | - | - | `-` |
| scenario-gateway | 1 | 0 | - | - | - | - | judge 0.0015 | 0.0 | 62592.0 | - | - | `-` |

Candidate lists of hospital-ja at every setting: **identical**.

## Part times

| part | wall seconds |
| --- | --- |
| prepare | 2.9 |
| install | 0.3 |
| chat-template | 5.9 |
| hospital-ja@c1 | 1744.3 |
| hospital-ja@c4 | 757.1 |
| hospital-ja@c16 | 512.4 |
| hospital-ja@c48 | 484.8 |
| scenario-emr-fhir | 263.3 |
| scenario-gateway | 5.1 |

## Failed checks

- chat-template / G-1 chat template: the passed file against the weights folder's own: the two templates are identical (sha256 of the text): {'folder': '94899c0f917d93f6fe81c95744d1e8ddab2d21d39228d2e4aec1fb2a25bff413', 'passed': 'ae53464bf3be25802b3a5b37def7fd89667067d7577049b3b2d74c4d8de4c6d4'}
- chat-template / G-1 chat template: the passed file against the weights folder's own: 20 prompts: the server's token ids equal the folder tokenizer's: [{'prompt': 1, 'first_difference_at': 22, 'lengths': [108, 107]}, {'prompt': 3, 'first_difference_at': 22, 'lengths': [153, 152]}, {'prompt': 5, 'first_difference_at': 22, 'lengths': [99, 98]}, {'prom
- hospital-ja@c1 / 12 site set-up and data harmonization: confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f
- hospital-ja@c4 / 12 site set-up and data harmonization: confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f
- hospital-ja@c16 / 12 site set-up and data harmonization: confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f
- hospital-ja@c48 / 12 site set-up and data harmonization: confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f

## chat-template: chat_template

```json
{"judge_model": "nvidia/Gemma-4-26B-A4B-NVFP4", "judge_started_with": null, "passed": {"path": "/var/lib/tb/runs/20261112T165042Z-931a0f79-s1/chat-template/chat_template.passed.jinja", "sha256": "ae53464bf3be25802b3a5b37def7fd89667067d7577049b3b2d74c4d8de4c6d4", "served_with_it": false, "from": "fetched: google/gemma-4-26B-A4B-it at 4d7ae4984b7d"}, "passed_text_sha256": "ae53464bf3be25802b3a5b37def7fd89667067d7577049b3b2d74c4d8de4c6d4", "folder_template_sha256": "94899c0f917d93f6fe81c95744d1e8ddab2d21d39228d2e4aec1fb2a25bff413", "folder_template_chars": 16934, "transformers": "5.19.0", "tokens": {"prompts": 20, "tokens": 2268, "server_equals_folder": false, "server_different": [{"prompt": 1, "first_difference_at": 22, "lengths": [108, 107]}, {"prompt": 3, "first_difference_at": 22, "lengths": [153, 152]}, {"prompt": 5, "first_difference_at": 22, "lengths": [99, 98]}, {"prompt": 7, "first_difference_at": 22, "lengths": [144, 143]}, {"prompt": 9, "first_difference_at": 22, "lengths": [114, 113]}], "passed_equals_folder": true, "passed_different": []}, "identical": false}
```

## hospital-ja@c1: screen

```json
{"funnel": [["S0", 3022], ["S1", 92], ["S3", 92], ["S4", 54]], "tiers": {"excluded": 2968, "high": 3, "review": 51}, "listed": 54, "judging": {"configured_note_block": "both_agree", "disagreements": 0, "failures": 0, "judge_model": "local/gemma-4-26b-a4b-nvfp4", "may_block": true, "mode": "agreement", "note_block": "both_agree", "note_block_code": "ok", "note_block_reason": "judge and verifier must both say fail", "verifier_model": "local/qwen3.5-9b-awq"}}
```

## hospital-ja@c1: canary

```json
{"gate": "on", "allows_block": true, "code": "ok", "reason": "", "running": false, "at": "2026-11-12T17:01:34", "ok": true, "cases": 54, "pair_correct": 53, "pair_decided_wrong": 0, "models": [{"role": "judge", "model": "local/gemma-4-26b-a4b-nvfp4", "correct": 54, "flips": 0, "ok": true}, {"role": "verifier", "model": "local/qwen3.5-9b-awq", "correct": 49, "flips": 1, "ok": true}], "wake_failure": null}
```

## hospital-ja@c4: screen

```json
{"funnel": [["S0", 3022], ["S1", 92], ["S3", 92], ["S4", 54]], "tiers": {"excluded": 2968, "high": 3, "review": 51}, "listed": 54, "judging": {"configured_note_block": "both_agree", "disagreements": 0, "failures": 0, "judge_model": "local/gemma-4-26b-a4b-nvfp4", "may_block": true, "mode": "agreement", "note_block": "both_agree", "note_block_code": "ok", "note_block_reason": "judge and verifier must both say fail", "verifier_model": "local/qwen3.5-9b-awq"}}
```

## hospital-ja@c4: canary

```json
{"gate": "on", "allows_block": true, "code": "ok", "reason": "", "running": false, "at": "2026-11-12T17:30:37", "ok": true, "cases": 54, "pair_correct": 53, "pair_decided_wrong": 0, "models": [{"role": "judge", "model": "local/gemma-4-26b-a4b-nvfp4", "correct": 54, "flips": 0, "ok": true}, {"role": "verifier", "model": "local/qwen3.5-9b-awq", "correct": 49, "flips": 1, "ok": true}], "wake_failure": null}
```

## hospital-ja@c16: screen

```json
{"funnel": [["S0", 3022], ["S1", 92], ["S3", 92], ["S4", 55]], "tiers": {"excluded": 2967, "high": 4, "review": 51}, "listed": 55, "judging": {"configured_note_block": "both_agree", "disagreements": 1, "failures": 0, "judge_model": "local/gemma-4-26b-a4b-nvfp4", "may_block": true, "mode": "agreement", "note_block": "both_agree", "note_block_code": "ok", "note_block_reason": "judge and verifier must both say fail", "verifier_model": "local/qwen3.5-9b-awq"}}
```

## hospital-ja@c16: canary

```json
{"gate": "on", "allows_block": true, "code": "ok", "reason": "", "running": false, "at": "2026-11-12T17:43:16", "ok": true, "cases": 54, "pair_correct": 53, "pair_decided_wrong": 0, "models": [{"role": "judge", "model": "local/gemma-4-26b-a4b-nvfp4", "correct": 54, "flips": 0, "ok": true}, {"role": "verifier", "model": "local/qwen3.5-9b-awq", "correct": 49, "flips": 1, "ok": true}], "wake_failure": null}
```

## hospital-ja@c48: screen

```json
{"funnel": [["S0", 3022], ["S1", 92], ["S3", 92], ["S4", 55]], "tiers": {"excluded": 2967, "high": 3, "review": 52}, "listed": 55, "judging": {"configured_note_block": "both_agree", "disagreements": 0, "failures": 0, "judge_model": "local/gemma-4-26b-a4b-nvfp4", "may_block": true, "mode": "agreement", "note_block": "both_agree", "note_block_code": "ok", "note_block_reason": "judge and verifier must both say fail", "verifier_model": "local/qwen3.5-9b-awq"}}
```

## hospital-ja@c48: canary

```json
{"gate": "on", "allows_block": true, "code": "ok", "reason": "", "running": false, "at": "2026-11-12T17:51:55", "ok": true, "cases": 54, "pair_correct": 53, "pair_decided_wrong": 0, "models": [{"role": "judge", "model": "local/gemma-4-26b-a4b-nvfp4", "correct": 54, "flips": 0, "ok": true}, {"role": "verifier", "model": "local/qwen3.5-9b-awq", "correct": 49, "flips": 1, "ok": true}], "wake_failure": null}
```
