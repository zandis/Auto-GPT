# TrialBox complete-platform run

Head `2b9eec74ab55` (Lane G: the G-4 probe's direct call to its own model server is a reviewed entry in the model-call guard). Run: 20261113T044219Z-2b9eec74-s1. Model: local/gemma-4-26b-a4b-nvfp4, local/qwen3.5-9b-awq (gateway (installed box, synthetic weight pins)). Hospital: 5,000 synthetic patients. Languages run: ja, zh-TW. OCR: tesseract. Model calls in flight: 1, 4, 16. Host: x86_64, 48 CPUs.
Run started 2026-11-13T04:49:06+00:00, finished 2026-11-13T06:29:12+00:00 (the parts' own times); report built 2026-11-13T06:38:59+00:00.

**FAILED**: 1351 of 1360 checks passed (9 failed); 130 of 130 screenshots; 99.6 min of part time (each part's wall time, summed: parts on several VMs ran at the same time); 0 known findings reported.

Screenshots are in the run's `report/shots/` folder (not committed).

Door secret after the collect (T-119): door secret tb-gpu-door: enabled version(s) 2 remain (this run's not destroyed: none); destroy each with: gcloud secrets versions destroy <version> --secret tb-gpu-door --quiet

| part | stage | checks | result | seconds | screenshot |
| --- | --- | --- | --- | --- | --- |
| prepare | synthetic hospital | 2/2 | pass | 1.4 | `prepare.png` |
| g4-decoding | G-4 structured output: backend, guided decoding on and off, eager start | 3/4 | FAIL | 61.9 | `g4-decoding.png` |
| g5-tokens | G-5 token counts: /tokenize against the product's estimates | 1/2 | FAIL | 10.4 | `g5-tokens.png` |
| g7-clipped | G-7 clipped against whole note (LLM-001) | 1/2 | FAIL | 24.3 | `g7-clipped.png` |
| hospital-ja@c1 | 0 data in | 5/5 | pass | 0.4 | `hospital-ja@c1-00.png` |
| hospital-ja@c1 | 1 feasibility report | 8/8 | pass | 0.1 | `hospital-ja@c1-01.png` |
| hospital-ja@c1 | 2 investigator approval | 2/2 | pass | 0.1 | `hospital-ja@c1-02.png` |
| hospital-ja@c1 | 3 screening | 7/7 | pass | 0.0 | `hospital-ja@c1-03.png` |
| hospital-ja@c1 | 4 list, marks and mail | 7/7 | pass | 0.8 | `hospital-ja@c1-04.png` |
| hospital-ja@c1 | 5 ready and needs-information lists | 9/9 | pass | 1.3 | `hospital-ja@c1-05.png` |
| hospital-ja@c1 | 7 REDCap read-back and screening log | 5/5 | pass | 0.1 | `hospital-ja@c1-06.png` |
| hospital-ja@c1 | audit | 14/14 | pass | 1.0 | `hospital-ja@c1-07.png` |
| hospital-ja@c1 | 8 REDCap write-back | 12/12 | pass | 1.3 | `hospital-ja@c1-08.png` |
| hospital-ja@c1 | 9 data core: REDCap off then on, conflicts, a PI's sheet | 13/13 | pass | 0.2 | `hospital-ja@c1-09.png` |
| hospital-ja@c1 | 10 built-in data capture | 15/15 | pass | 1.2 | `hospital-ja@c1-10.png` |
| hospital-ja@c1 | 11 trial lifecycle | 25/25 | pass | 4.2 | `hospital-ja@c1-11.png` |
| hospital-ja@c1 | 12 site set-up and data harmonization | 22/23 | FAIL | 34.8 | `hospital-ja@c1-12.png` |
| hospital-ja@c1 | 13 Japan: SS-MIX2, JP Core and the licensed code lists | 16/16 | pass | 9.7 | `hospital-ja@c1-13.png` |
| hospital-ja@c1 | 14 ClinicalTrials.gov offline: the reference data pack | 12/12 | pass | 0.7 | `hospital-ja@c1-14.png` |
| hospital-ja@c1 | re-run (FR-REP-02) | 2/2 | pass | 5.2 | `hospital-ja@c1-15.png` |
| hospital-ja@c1 | 15 delegation, candidates and referral | 16/16 | pass | 659.2 | `hospital-ja@c1-16.png` |
| hospital-ja@c1 | 16 EDC prefill | 22/22 | pass | 6.4 | `hospital-ja@c1-17.png` |
| hospital-ja@c1 | 17 screening cadence: in Tuesday's data, booked Friday, listed Wednesday | 10/10 | pass | 38.9 | `hospital-ja@c1-18.png` |
| hospital-ja@c1 | runtime | 1/1 | pass | 0.0 | `hospital-ja@c1-19.png` |
| hospital-ja@c1 | db-csv: model exclusions against the generator's note truth | 1/1 | pass | 0 | `hospital-ja@c1-20.png` |
| hospital-ja@c4 | 0 data in | 5/5 | pass | 0.4 | `hospital-ja@c4-00.png` |
| hospital-ja@c4 | 1 feasibility report | 8/8 | pass | 0.1 | `hospital-ja@c4-01.png` |
| hospital-ja@c4 | 2 investigator approval | 2/2 | pass | 0.1 | `hospital-ja@c4-02.png` |
| hospital-ja@c4 | 3 screening | 7/7 | pass | 0.0 | `hospital-ja@c4-03.png` |
| hospital-ja@c4 | 4 list, marks and mail | 7/7 | pass | 0.8 | `hospital-ja@c4-04.png` |
| hospital-ja@c4 | 5 ready and needs-information lists | 9/9 | pass | 1.3 | `hospital-ja@c4-05.png` |
| hospital-ja@c4 | 7 REDCap read-back and screening log | 5/5 | pass | 0.1 | `hospital-ja@c4-06.png` |
| hospital-ja@c4 | audit | 14/14 | pass | 1.6 | `hospital-ja@c4-07.png` |
| hospital-ja@c4 | 8 REDCap write-back | 12/12 | pass | 0.7 | `hospital-ja@c4-08.png` |
| hospital-ja@c4 | 9 data core: REDCap off then on, conflicts, a PI's sheet | 13/13 | pass | 0.2 | `hospital-ja@c4-09.png` |
| hospital-ja@c4 | 10 built-in data capture | 15/15 | pass | 1.2 | `hospital-ja@c4-10.png` |
| hospital-ja@c4 | 11 trial lifecycle | 25/25 | pass | 4.2 | `hospital-ja@c4-11.png` |
| hospital-ja@c4 | 12 site set-up and data harmonization | 22/23 | FAIL | 34.8 | `hospital-ja@c4-12.png` |
| hospital-ja@c4 | 13 Japan: SS-MIX2, JP Core and the licensed code lists | 16/16 | pass | 9.4 | `hospital-ja@c4-13.png` |
| hospital-ja@c4 | 14 ClinicalTrials.gov offline: the reference data pack | 12/12 | pass | 0.7 | `hospital-ja@c4-14.png` |
| hospital-ja@c4 | re-run (FR-REP-02) | 2/2 | pass | 5.1 | `hospital-ja@c4-15.png` |
| hospital-ja@c4 | 15 delegation, candidates and referral | 16/16 | pass | 179.2 | `hospital-ja@c4-16.png` |
| hospital-ja@c4 | 16 EDC prefill | 22/22 | pass | 5.1 | `hospital-ja@c4-17.png` |
| hospital-ja@c4 | 17 screening cadence: in Tuesday's data, booked Friday, listed Wednesday | 10/10 | pass | 40.0 | `hospital-ja@c4-18.png` |
| hospital-ja@c4 | runtime | 1/1 | pass | 0.0 | `hospital-ja@c4-19.png` |
| hospital-ja@c4 | db-csv: model exclusions against the generator's note truth | 1/1 | pass | 0 | `hospital-ja@c4-20.png` |
| hospital-ja@c16 | 0 data in | 5/5 | pass | 0.4 | `hospital-ja@c16-00.png` |
| hospital-ja@c16 | 1 feasibility report | 8/8 | pass | 0.1 | `hospital-ja@c16-01.png` |
| hospital-ja@c16 | 2 investigator approval | 2/2 | pass | 0.1 | `hospital-ja@c16-02.png` |
| hospital-ja@c16 | 3 screening | 7/7 | pass | 0.0 | `hospital-ja@c16-03.png` |
| hospital-ja@c16 | 4 list, marks and mail | 7/7 | pass | 0.8 | `hospital-ja@c16-04.png` |
| hospital-ja@c16 | 5 ready and needs-information lists | 9/9 | pass | 1.3 | `hospital-ja@c16-05.png` |
| hospital-ja@c16 | 7 REDCap read-back and screening log | 5/5 | pass | 0.1 | `hospital-ja@c16-06.png` |
| hospital-ja@c16 | audit | 14/14 | pass | 1.6 | `hospital-ja@c16-07.png` |
| hospital-ja@c16 | 8 REDCap write-back | 12/12 | pass | 0.7 | `hospital-ja@c16-08.png` |
| hospital-ja@c16 | 9 data core: REDCap off then on, conflicts, a PI's sheet | 13/13 | pass | 0.2 | `hospital-ja@c16-09.png` |
| hospital-ja@c16 | 10 built-in data capture | 15/15 | pass | 1.2 | `hospital-ja@c16-10.png` |
| hospital-ja@c16 | 11 trial lifecycle | 25/25 | pass | 4.2 | `hospital-ja@c16-11.png` |
| hospital-ja@c16 | 12 site set-up and data harmonization | 22/23 | FAIL | 35.6 | `hospital-ja@c16-12.png` |
| hospital-ja@c16 | 13 Japan: SS-MIX2, JP Core and the licensed code lists | 16/16 | pass | 8.7 | `hospital-ja@c16-13.png` |
| hospital-ja@c16 | 14 ClinicalTrials.gov offline: the reference data pack | 12/12 | pass | 0.7 | `hospital-ja@c16-14.png` |
| hospital-ja@c16 | re-run (FR-REP-02) | 2/2 | pass | 5.1 | `hospital-ja@c16-15.png` |
| hospital-ja@c16 | 15 delegation, candidates and referral | 16/16 | pass | 70.5 | `hospital-ja@c16-16.png` |
| hospital-ja@c16 | 16 EDC prefill | 22/22 | pass | 5.0 | `hospital-ja@c16-17.png` |
| hospital-ja@c16 | 17 screening cadence: in Tuesday's data, booked Friday, listed Wednesday | 10/10 | pass | 35.1 | `hospital-ja@c16-18.png` |
| hospital-ja@c16 | runtime | 1/1 | pass | 0.0 | `hospital-ja@c16-19.png` |
| hospital-ja@c16 | db-csv: model exclusions against the generator's note truth | 1/1 | pass | 0 | `hospital-ja@c16-20.png` |
| hospital-zh-TW@c1 | 0 data in | 5/5 | pass | 0.4 | `hospital-zh-TW@c1-00.png` |
| hospital-zh-TW@c1 | 1 feasibility report | 8/8 | pass | 0.1 | `hospital-zh-TW@c1-01.png` |
| hospital-zh-TW@c1 | 2 investigator approval | 2/2 | pass | 0.1 | `hospital-zh-TW@c1-02.png` |
| hospital-zh-TW@c1 | 3 screening | 7/7 | pass | 0.0 | `hospital-zh-TW@c1-03.png` |
| hospital-zh-TW@c1 | 4 list, marks and mail | 7/7 | pass | 0.8 | `hospital-zh-TW@c1-04.png` |
| hospital-zh-TW@c1 | 5 ready and needs-information lists | 9/9 | pass | 1.3 | `hospital-zh-TW@c1-05.png` |
| hospital-zh-TW@c1 | 7 REDCap read-back and screening log | 5/5 | pass | 0.1 | `hospital-zh-TW@c1-06.png` |
| hospital-zh-TW@c1 | audit | 14/14 | pass | 1.0 | `hospital-zh-TW@c1-07.png` |
| hospital-zh-TW@c1 | 8 REDCap write-back | 12/12 | pass | 0.7 | `hospital-zh-TW@c1-08.png` |
| hospital-zh-TW@c1 | 9 data core: REDCap off then on, conflicts, a PI's sheet | 13/13 | pass | 0.2 | `hospital-zh-TW@c1-09.png` |
| hospital-zh-TW@c1 | 10 built-in data capture | 15/15 | pass | 1.8 | `hospital-zh-TW@c1-10.png` |
| hospital-zh-TW@c1 | 11 trial lifecycle | 25/25 | pass | 4.2 | `hospital-zh-TW@c1-11.png` |
| hospital-zh-TW@c1 | 12 site set-up and data harmonization | 22/23 | FAIL | 38.3 | `hospital-zh-TW@c1-12.png` |
| hospital-zh-TW@c1 | 13 Japan: SS-MIX2, JP Core and the licensed code lists | 16/16 | pass | 8.8 | `hospital-zh-TW@c1-13.png` |
| hospital-zh-TW@c1 | 14 ClinicalTrials.gov offline: the reference data pack | 12/12 | pass | 1.4 | `hospital-zh-TW@c1-14.png` |
| hospital-zh-TW@c1 | re-run (FR-REP-02) | 2/2 | pass | 5.1 | `hospital-zh-TW@c1-15.png` |
| hospital-zh-TW@c1 | 15 delegation, candidates and referral | 16/16 | pass | 643.5 | `hospital-zh-TW@c1-16.png` |
| hospital-zh-TW@c1 | 16 EDC prefill | 22/22 | pass | 5.0 | `hospital-zh-TW@c1-17.png` |
| hospital-zh-TW@c1 | 17 screening cadence: in Tuesday's data, booked Friday, listed Wednesday | 10/10 | pass | 35.9 | `hospital-zh-TW@c1-18.png` |
| hospital-zh-TW@c1 | runtime | 1/1 | pass | 0.0 | `hospital-zh-TW@c1-19.png` |
| hospital-zh-TW@c1 | db-csv: model exclusions against the generator's note truth | 1/1 | pass | 0 | `hospital-zh-TW@c1-20.png` |
| hospital-zh-TW@c4 | 0 data in | 5/5 | pass | 0.4 | `hospital-zh-TW@c4-00.png` |
| hospital-zh-TW@c4 | 1 feasibility report | 8/8 | pass | 0.1 | `hospital-zh-TW@c4-01.png` |
| hospital-zh-TW@c4 | 2 investigator approval | 2/2 | pass | 0.1 | `hospital-zh-TW@c4-02.png` |
| hospital-zh-TW@c4 | 3 screening | 7/7 | pass | 0.0 | `hospital-zh-TW@c4-03.png` |
| hospital-zh-TW@c4 | 4 list, marks and mail | 7/7 | pass | 0.8 | `hospital-zh-TW@c4-04.png` |
| hospital-zh-TW@c4 | 5 ready and needs-information lists | 9/9 | pass | 2.0 | `hospital-zh-TW@c4-05.png` |
| hospital-zh-TW@c4 | 7 REDCap read-back and screening log | 5/5 | pass | 0.1 | `hospital-zh-TW@c4-06.png` |
| hospital-zh-TW@c4 | audit | 14/14 | pass | 1.0 | `hospital-zh-TW@c4-07.png` |
| hospital-zh-TW@c4 | 8 REDCap write-back | 12/12 | pass | 0.7 | `hospital-zh-TW@c4-08.png` |
| hospital-zh-TW@c4 | 9 data core: REDCap off then on, conflicts, a PI's sheet | 13/13 | pass | 0.1 | `hospital-zh-TW@c4-09.png` |
| hospital-zh-TW@c4 | 10 built-in data capture | 15/15 | pass | 1.2 | `hospital-zh-TW@c4-10.png` |
| hospital-zh-TW@c4 | 11 trial lifecycle | 25/25 | pass | 4.1 | `hospital-zh-TW@c4-11.png` |
| hospital-zh-TW@c4 | 12 site set-up and data harmonization | 22/23 | FAIL | 38.7 | `hospital-zh-TW@c4-12.png` |
| hospital-zh-TW@c4 | 13 Japan: SS-MIX2, JP Core and the licensed code lists | 16/16 | pass | 8.8 | `hospital-zh-TW@c4-13.png` |
| hospital-zh-TW@c4 | 14 ClinicalTrials.gov offline: the reference data pack | 12/12 | pass | 1.4 | `hospital-zh-TW@c4-14.png` |
| hospital-zh-TW@c4 | re-run (FR-REP-02) | 2/2 | pass | 4.4 | `hospital-zh-TW@c4-15.png` |
| hospital-zh-TW@c4 | 15 delegation, candidates and referral | 16/16 | pass | 238.2 | `hospital-zh-TW@c4-16.png` |
| hospital-zh-TW@c4 | 16 EDC prefill | 22/22 | pass | 5.9 | `hospital-zh-TW@c4-17.png` |
| hospital-zh-TW@c4 | 17 screening cadence: in Tuesday's data, booked Friday, listed Wednesday | 10/10 | pass | 39.1 | `hospital-zh-TW@c4-18.png` |
| hospital-zh-TW@c4 | runtime | 1/1 | pass | 0.0 | `hospital-zh-TW@c4-19.png` |
| hospital-zh-TW@c4 | db-csv: model exclusions against the generator's note truth | 1/1 | pass | 0 | `hospital-zh-TW@c4-20.png` |
| hospital-zh-TW@c16 | 0 data in | 5/5 | pass | 0.4 | `hospital-zh-TW@c16-00.png` |
| hospital-zh-TW@c16 | 1 feasibility report | 8/8 | pass | 0.1 | `hospital-zh-TW@c16-01.png` |
| hospital-zh-TW@c16 | 2 investigator approval | 2/2 | pass | 0.1 | `hospital-zh-TW@c16-02.png` |
| hospital-zh-TW@c16 | 3 screening | 7/7 | pass | 0.0 | `hospital-zh-TW@c16-03.png` |
| hospital-zh-TW@c16 | 4 list, marks and mail | 7/7 | pass | 0.8 | `hospital-zh-TW@c16-04.png` |
| hospital-zh-TW@c16 | 5 ready and needs-information lists | 9/9 | pass | 1.9 | `hospital-zh-TW@c16-05.png` |
| hospital-zh-TW@c16 | 7 REDCap read-back and screening log | 5/5 | pass | 0.1 | `hospital-zh-TW@c16-06.png` |
| hospital-zh-TW@c16 | audit | 14/14 | pass | 1.0 | `hospital-zh-TW@c16-07.png` |
| hospital-zh-TW@c16 | 8 REDCap write-back | 12/12 | pass | 0.7 | `hospital-zh-TW@c16-08.png` |
| hospital-zh-TW@c16 | 9 data core: REDCap off then on, conflicts, a PI's sheet | 13/13 | pass | 0.2 | `hospital-zh-TW@c16-09.png` |
| hospital-zh-TW@c16 | 10 built-in data capture | 15/15 | pass | 1.2 | `hospital-zh-TW@c16-10.png` |
| hospital-zh-TW@c16 | 11 trial lifecycle | 25/25 | pass | 4.2 | `hospital-zh-TW@c16-11.png` |
| hospital-zh-TW@c16 | 12 site set-up and data harmonization | 22/23 | FAIL | 38.8 | `hospital-zh-TW@c16-12.png` |
| hospital-zh-TW@c16 | 13 Japan: SS-MIX2, JP Core and the licensed code lists | 16/16 | pass | 8.8 | `hospital-zh-TW@c16-13.png` |
| hospital-zh-TW@c16 | 14 ClinicalTrials.gov offline: the reference data pack | 12/12 | pass | 0.7 | `hospital-zh-TW@c16-14.png` |
| hospital-zh-TW@c16 | re-run (FR-REP-02) | 2/2 | pass | 5.0 | `hospital-zh-TW@c16-15.png` |
| hospital-zh-TW@c16 | 15 delegation, candidates and referral | 16/16 | pass | 69.3 | `hospital-zh-TW@c16-16.png` |
| hospital-zh-TW@c16 | 16 EDC prefill | 22/22 | pass | 6.0 | `hospital-zh-TW@c16-17.png` |
| hospital-zh-TW@c16 | 17 screening cadence: in Tuesday's data, booked Friday, listed Wednesday | 10/10 | pass | 38.5 | `hospital-zh-TW@c16-18.png` |
| hospital-zh-TW@c16 | runtime | 1/1 | pass | 0.0 | `hospital-zh-TW@c16-19.png` |
| hospital-zh-TW@c16 | db-csv: model exclusions against the generator's note truth | 1/1 | pass | 0 | `hospital-zh-TW@c16-20.png` |

## Scenarios

### db-csv: Hospital database feed (CGRD-style CSV)

**FAIL**: 1344 of 1350 checks.

* Input (ja@c1): CGRD-style CSV export of 5,000 synthetic patients (two sites, JP and TW style)
* Counts: `{"patients": 5000, "screen_funnel": {"S0": 3022, "S1": 92, "S3": 92, "S4": 55}}`
* Expected: `"e2e_simple stages 0-1: lake = generator counts; FEAS INC-01/02 = recount from the CSVs"`
* Got: `{"0 data in": "5/5", "1 feasibility report": "8/8"}`
* Model calls: 604
* Model exclusions: 31 (true 31, false 0, true ones missed 1)
  * `096496fcd3` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0a30541d9a` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0eddd0ac4d` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `17f661aafb` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `1ce0e4bbbf` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `1e8065fbb9` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `22baa2bccd` GZQO-EXC-11: truth {'GZQO-EXC-11': 'yes'}, correct
  * `2731cb6ad6` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `2a869cd02a` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `2c2f3ace9a` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `2c51913915` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `363beee8cb` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `3cb0e10d48` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `476c39c443` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `59e8634b56` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `5ed9c6e253` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `60ca5ef357` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `61c6861715` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `683484ea47` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `76f8bf3013` GZQO-EXC-11: truth {'GZQO-EXC-11': 'yes'}, correct
* Time: 1685.5 s. Screenshot: `hospital-ja@c1-00.png`, `hospital-ja@c1-01.png`, `hospital-ja@c1-02.png`
* FAILED (hospital-ja@c1 / 12 site set-up and data harmonization): confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})

* Input (ja@c4): CGRD-style CSV export of 5,000 synthetic patients (two sites, JP and TW style)
* Counts: `{"patients": 5000, "screen_funnel": {"S0": 3022, "S1": 92, "S3": 92, "S4": 55}}`
* Expected: `"e2e_simple stages 0-1: lake = generator counts; FEAS INC-01/02 = recount from the CSVs"`
* Got: `{"0 data in": "5/5", "1 feasibility report": "8/8"}`
* Model calls: 598
* Model exclusions: 31 (true 31, false 0, true ones missed 1)
  * `096496fcd3` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0a30541d9a` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0eddd0ac4d` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `17f661aafb` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `1ce0e4bbbf` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `1e8065fbb9` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `22baa2bccd` GZQO-EXC-11: truth {'GZQO-EXC-11': 'yes'}, correct
  * `2731cb6ad6` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `2a869cd02a` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `2c2f3ace9a` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `2c51913915` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `363beee8cb` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `3cb0e10d48` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `476c39c443` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `59e8634b56` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `5ed9c6e253` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `60ca5ef357` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `61c6861715` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `683484ea47` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `76f8bf3013` GZQO-EXC-11: truth {'GZQO-EXC-11': 'yes'}, correct
* Time: 734.1 s. Screenshot: `hospital-ja@c4-00.png`, `hospital-ja@c4-01.png`, `hospital-ja@c4-02.png`
* FAILED (hospital-ja@c4 / 12 site set-up and data harmonization): confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})

* Input (ja@c16): CGRD-style CSV export of 5,000 synthetic patients (two sites, JP and TW style)
* Counts: `{"patients": 5000, "screen_funnel": {"S0": 3022, "S1": 92, "S3": 92, "S4": 55}}`
* Expected: `"e2e_simple stages 0-1: lake = generator counts; FEAS INC-01/02 = recount from the CSVs"`
* Got: `{"0 data in": "5/5", "1 feasibility report": "8/8"}`
* Model calls: 598
* Model exclusions: 31 (true 31, false 0, true ones missed 1)
  * `096496fcd3` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0a30541d9a` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0eddd0ac4d` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `17f661aafb` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `1ce0e4bbbf` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `1e8065fbb9` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `22baa2bccd` GZQO-EXC-11: truth {'GZQO-EXC-11': 'yes'}, correct
  * `2731cb6ad6` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `2a869cd02a` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `2c2f3ace9a` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `2c51913915` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `363beee8cb` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `3cb0e10d48` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `476c39c443` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `59e8634b56` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `5ed9c6e253` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `60ca5ef357` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `61c6861715` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `683484ea47` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `76f8bf3013` GZQO-EXC-11: truth {'GZQO-EXC-11': 'yes'}, correct
* Time: 501.5 s. Screenshot: `hospital-ja@c16-00.png`, `hospital-ja@c16-01.png`, `hospital-ja@c16-02.png`
* FAILED (hospital-ja@c16 / 12 site set-up and data harmonization): confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})

* Input (zh-TW@c1): CGRD-style CSV export of 5,000 synthetic patients (two sites, JP and TW style)
* Counts: `{"patients": 5000, "screen_funnel": {"S0": 3022, "S1": 92, "S3": 92, "S4": 55}}`
* Expected: `"e2e_simple stages 0-1: lake = generator counts; FEAS INC-01/02 = recount from the CSVs"`
* Got: `{"0 data in": "5/5", "1 feasibility report": "8/8"}`
* Model calls: 601
* Model exclusions: 31 (true 31, false 0, true ones missed 1)
  * `096496fcd3` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0a30541d9a` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0eddd0ac4d` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `17f661aafb` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `1ce0e4bbbf` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `1e8065fbb9` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `22baa2bccd` GZQO-EXC-11: truth {'GZQO-EXC-11': 'yes'}, correct
  * `2731cb6ad6` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `2a869cd02a` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `2c2f3ace9a` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `2c51913915` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `363beee8cb` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `3cb0e10d48` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `476c39c443` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `59e8634b56` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `5ed9c6e253` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `60ca5ef357` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `61c6861715` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `683484ea47` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `76f8bf3013` GZQO-EXC-11: truth {'GZQO-EXC-11': 'yes'}, correct
* Time: 1655.8 s. Screenshot: `hospital-zh-TW@c1-00.png`, `hospital-zh-TW@c1-01.png`, `hospital-zh-TW@c1-02.png`
* FAILED (hospital-zh-TW@c1 / 12 site set-up and data harmonization): confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})

* Input (zh-TW@c4): CGRD-style CSV export of 5,000 synthetic patients (two sites, JP and TW style)
* Counts: `{"patients": 5000, "screen_funnel": {"S0": 3022, "S1": 92, "S3": 92, "S4": 55}}`
* Expected: `"e2e_simple stages 0-1: lake = generator counts; FEAS INC-01/02 = recount from the CSVs"`
* Got: `{"0 data in": "5/5", "1 feasibility report": "8/8"}`
* Model calls: 602
* Model exclusions: 31 (true 31, false 0, true ones missed 1)
  * `096496fcd3` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0a30541d9a` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0eddd0ac4d` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `17f661aafb` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `1ce0e4bbbf` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `1e8065fbb9` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `22baa2bccd` GZQO-EXC-11: truth {'GZQO-EXC-11': 'yes'}, correct
  * `2731cb6ad6` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `2a869cd02a` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `2c2f3ace9a` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `2c51913915` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `363beee8cb` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `3cb0e10d48` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `476c39c443` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `59e8634b56` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `5ed9c6e253` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `60ca5ef357` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `61c6861715` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `683484ea47` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `76f8bf3013` GZQO-EXC-11: truth {'GZQO-EXC-11': 'yes'}, correct
* Time: 791.5 s. Screenshot: `hospital-zh-TW@c4-00.png`, `hospital-zh-TW@c4-01.png`, `hospital-zh-TW@c4-02.png`
* FAILED (hospital-zh-TW@c4 / 12 site set-up and data harmonization): confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})

* Input (zh-TW@c16): CGRD-style CSV export of 5,000 synthetic patients (two sites, JP and TW style)
* Counts: `{"patients": 5000, "screen_funnel": {"S0": 3022, "S1": 92, "S3": 92, "S4": 55}}`
* Expected: `"e2e_simple stages 0-1: lake = generator counts; FEAS INC-01/02 = recount from the CSVs"`
* Got: `{"0 data in": "5/5", "1 feasibility report": "8/8"}`
* Model calls: 601
* Model exclusions: 31 (true 31, false 0, true ones missed 1)
  * `096496fcd3` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0a30541d9a` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0eddd0ac4d` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `17f661aafb` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `1ce0e4bbbf` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `1e8065fbb9` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `22baa2bccd` GZQO-EXC-11: truth {'GZQO-EXC-11': 'yes'}, correct
  * `2731cb6ad6` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `2a869cd02a` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `2c2f3ace9a` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `2c51913915` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `363beee8cb` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `3cb0e10d48` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `476c39c443` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `59e8634b56` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `5ed9c6e253` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `60ca5ef357` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `61c6861715` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `683484ea47` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `76f8bf3013` GZQO-EXC-11: truth {'GZQO-EXC-11': 'yes'}, correct
* Time: 507.9 s. Screenshot: `hospital-zh-TW@c16-00.png`, `hospital-zh-TW@c16-01.png`, `hospital-zh-TW@c16-02.png`
* FAILED (hospital-zh-TW@c16 / 12 site set-up and data harmonization): confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})


## Throughput (model calls through the gateway)

Calls and tokens per second are over the seconds in which a call was in flight (the gateway's audit); the servers' `/metrics` before and after, `gpu.csv` (every 10 s) and `vllm.csv` are in `parts/<part>/`. A hospital part has two rows: **main SCREEN** (the SCREEN job's own window: the throughput of the curve) and **whole part** (with the canary's one-at-a-time calls and stages 15 and 17). GPU % is `nvidia-smi` utilisation, the share of time a kernel ran: not a headroom measure (a card at 100 % may take more calls). KV peak: each server's KV-cache usage peak (vllm.csv). Not measured: the gateway's slot wait per call (the gateway does not record it).

| part | window | in flight | calls | calls/s | tokens/s | p50 s | p95 s | queue s (vLLM) | GPU % mean | GPU % max | KV peak | GPU MiB peak | breaker opened | listed | list sha256 | refused (of asked) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| g4-decoding | whole part | 1 | 0 | - | - | - | - | judge 0.1591 | 29.4 | 50.0 | judge 0.022895320177954148, verifier 0.0 | 62582.0 | - | - | `-` | - |
| g5-tokens | whole part | 1 | 0 | - | - | - | - | - | 0.0 | 0.0 | judge 0.0, verifier 0.0 | 62582.0 | - | - | `-` | - |
| g7-clipped | whole part | 1 | 14 | 0.593 | 997.843 | 1.53 | 2.309 | judge 0.0006, verifier 0.2038 | 29.2 | 42.0 | judge 0.00601447815101297, verifier 0.010903426791277204 | 62590.0 | 0 | - | `-` | 0 of 14 |
| hospital-ja@c1 | main SCREEN | 1 | 244 | 0.385 | 402.705 | 2.353 | 4.086 | judge 0.0021, verifier 0.0009 | 37.6 | 59.0 | judge 0.0061229867774488245, verifier 0.010903426791277204 | 62590.0 | 0 | 55 | `e54da5f3a38b` | 0 of 606 |
| hospital-ja@c1 | whole part | 1 | 606 | 0.402 | 378.825 | 2.168 | 4.049 | judge 0.0021, verifier 0.0009 | 32.6 | 59.0 | judge 0.006138488009796772, verifier 0.010903426791277204 | 62590.0 | 0 | 55 | `e54da5f3a38b` | 0 of 606 |
| hospital-ja@c4 | main SCREEN | 4 | 244 | 1.435 | 1492.028 | 2.424 | 4.193 | judge 0.0003, verifier 0.0004 | 83.1 | 92.0 | judge 0.015997271783106726, verifier 0.03738317757009346 | 62592.0 | 0 | 55 | `7fe07e4bb815` | 0 of 597 |
| hospital-ja@c4 | whole part | 4 | 597 | 1.046 | 973.783 | 2.222 | 4.109 | judge 0.0003, verifier 0.0004 | 47.8 | 92.0 | judge 0.017268372835640422, verifier 0.03738317757009346 | 62592.0 | 0 | 55 | `7fe07e4bb815` | 0 of 597 |
| hospital-ja@c16 | main SCREEN | 16 | 246 | 4.391 | 4580.144 | 2.845 | 5.413 | judge 0.0002, verifier 0.0002 | 62.3 | 93.0 | judge 0.0559749500085257, verifier 0.06074766355140182 | 62592.0 | 0 | 55 | `e54da5f3a38b` | 0 of 603 |
| hospital-ja@c16 | whole part | 16 | 603 | 1.779 | 1661.548 | 2.414 | 4.888 | judge 0.0002, verifier 0.0002 | 32.7 | 93.0 | judge 0.0559749500085257, verifier 0.07943925233644855 | 62592.0 | 0 | 55 | `e54da5f3a38b` | 0 of 603 |
| hospital-zh-TW@c1 | main SCREEN | 1 | 243 | 0.388 | 402.122 | 2.36 | 4.109 | judge 0.0013, verifier 0.0009 | 34.0 | 41.0 | judge 0.006076483080404871, verifier 0.012461059190031154 | 62592.0 | 0 | 55 | `297e93f53461` | 0 of 600 |
| hospital-zh-TW@c1 | whole part | 1 | 600 | 0.404 | 377.656 | 2.168 | 4.013 | judge 0.0013, verifier 0.0009 | 31.0 | 41.0 | judge 0.0061229867774488245, verifier 0.015576323987538943 | 62592.0 | 0 | 55 | `297e93f53461` | 0 of 600 |
| hospital-zh-TW@c4 | main SCREEN | 4 | 246 | 1.432 | 1499.917 | 2.511 | 4.281 | judge 0.0003, verifier 0.0005 | 72.4 | 92.0 | judge 0.02074064888158611, verifier 0.024922118380062308 | 62592.0 | 0 | 55 | `e54da5f3a38b` | 0 of 602 |
| hospital-zh-TW@c4 | whole part | 4 | 602 | 0.958 | 905.552 | 2.237 | 4.22 | judge 0.0003, verifier 0.0005 | 46.7 | 92.0 | judge 0.0213606981755049, verifier 0.03582554517133951 | 62592.0 | 0 | 55 | `e54da5f3a38b` | 0 of 602 |
| hospital-zh-TW@c16 | main SCREEN | 16 | 244 | 4.613 | 4785.824 | 2.741 | 4.652 | judge 0.0003, verifier 0.0003 | 76.2 | 92.0 | judge 0.056238470958441145, verifier 0.05763239875389403 | 62592.0 | 0 | 55 | `7fe07e4bb815` | 0 of 600 |
| hospital-zh-TW@c16 | whole part | 16 | 600 | 1.741 | 1625.514 | 2.392 | 4.377 | judge 0.0003, verifier 0.0003 | 34.1 | 94.0 | judge 0.056238470958441145, verifier 0.05919003115264798 | 62592.0 | 0 | 55 | `7fe07e4bb815` | 0 of 600 |

Candidate lists of hospital-ja at every setting: **DIFFERENT** (the list must not depend on the calls in flight): 1 patient(s) not listed alike (pseudonymous ids; `-`: not listed at that setting).

| pid | hospital-ja@c1 | hospital-ja@c4 | hospital-ja@c16 |
| --- | --- | --- | --- |
| `f148c65925863f2deeabae1e52a0de36` | high | review | high |

Candidate lists of hospital-zh-TW at every setting: **DIFFERENT** (the list must not depend on the calls in flight): 2 patient(s) not listed alike (pseudonymous ids; `-`: not listed at that setting).

| pid | hospital-zh-TW@c1 | hospital-zh-TW@c4 | hospital-zh-TW@c16 |
| --- | --- | --- | --- |
| `51a5db6a4e6e790ae6d7889320738e46` | review | high | high |
| `f148c65925863f2deeabae1e52a0de36` | high | high | review |

## Review tests G-4, G-5, G-7, G-8 (plan v7 §7.1)

### G-4 (g4-decoding)

Structured-output backend: **auto** (the serving record (the container's command line)). Eager start: needs a restart: not run (--enforce-eager is a start flag; the part never restarts a server) (record: enforce_eager True).

| setting | calls | answered | calls/s | p50 s | p95 s | schema failures |
| --- | --- | --- | --- | --- | --- | --- |
| guided on | 64 | 64 | 1.765 | 2.2438 | 9.3917 | 1 |
| guided off | 64 | 64 | 2.499 | 1.7916 | 3.8942 | 64 |

Profile: guided decoding on (16 in flight, 64 prompts each way).

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
| LLM-001-ja-family-history | True | 0 | clipped | pass | pass | unknown | review |
| LLM-001-ja-family-history | True | 0 | whole | unknown | pass | unknown | review |
| LLM-001-zh-TW-denied-list | True | 0 | clipped | pass | pass | pass | not met (final) |
| LLM-001-zh-TW-denied-list | True | 0 | whole | fail | fail | fail | met |

Final not met from a clipped note: **LLM-001-zh-TW-denied-list**.


## Part times

| part | wall seconds |
| --- | --- |
| prepare | 3.0 |
| g4-decoding | 62.5 |
| g5-tokens | 10.8 |
| g7-clipped | 24.8 |
| hospital-ja@c1 | 1685.5 |
| hospital-ja@c4 | 734.1 |
| hospital-ja@c16 | 501.5 |
| hospital-zh-TW@c1 | 1655.8 |
| hospital-zh-TW@c4 | 791.5 |
| hospital-zh-TW@c16 | 507.9 |

## Failed checks

Each detail is cut at 300 characters here (TB_REPORT_DETAIL_CHARS); the whole detail of each is in `failed-checks.json` beside this report (as the part recorded it).

- g4-decoding / G-4 structured output: backend, guided decoding on and off, eager start: guided on: no answer outside the judge schema: 1
- g5-tokens / G-5 token counts: /tokenize against the product's estimates: the largest real / estimated ratio x 1.05 fits the budget's share (1 / SAFETY = 1.176): {'max_ratio': 1.2121, 'safety_from_measurement': 0.7857}
- g7-clipped / G-7 clipped against whole note (LLM-001): 0 exclusions on a clipped note (no final not met from a clipped note): ['LLM-001-zh-TW-denied-list']
- hospital-ja@c1 / 12 site set-up and data harmonization: confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})
- hospital-ja@c4 / 12 site set-up and data harmonization: confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})
- hospital-ja@c16 / 12 site set-up and data harmonization: confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})
- hospital-zh-TW@c1 / 12 site set-up and data harmonization: confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})
- hospital-zh-TW@c4 / 12 site set-up and data harmonization: confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})
- hospital-zh-TW@c16 / 12 site set-up and data harmonization: confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})

## hospital-ja@c1: screen

```json
{"funnel": [["S0", 3022], ["S1", 92], ["S3", 92], ["S4", 55]], "tiers": {"excluded": 2967, "high": 4, "review": 51}, "listed": 55, "judging": {"configured_note_block": "both_agree", "disagreements": 1, "failures": 0, "judge_model": "local/gemma-4-26b-a4b-nvfp4", "may_block": true, "mode": "agreement", "note_block": "both_agree", "note_block_code": "ok", "note_block_reason": "judge and verifier must both say fail", "verifier_model": "local/qwen3.5-9b-awq"}, "window": {"from": 1794545709.165318, "to": 1794546357.267139, "from_at": "2026-11-13T12:55:09.165318+08:00", "to_at": "2026-11-13T13:05:57.267139+08:00"}}
```

## hospital-ja@c1: canary

```json
{"gate": "on", "allows_block": true, "code": "ok", "reason": "", "running": false, "at": "2026-11-13T04:54:58", "ok": true, "cases": 54, "pair_correct": 52, "pair_decided_wrong": 0, "models": [{"role": "judge", "model": "local/gemma-4-26b-a4b-nvfp4", "correct": 53, "flips": 1, "ok": true}, {"role": "verifier", "model": "local/qwen3.5-9b-awq", "correct": 49, "flips": 1, "ok": true}], "wake_failure": null}
```

## hospital-ja@c4: screen

```json
{"funnel": [["S0", 3022], ["S1", 92], ["S3", 92], ["S4", 55]], "tiers": {"excluded": 2967, "high": 3, "review": 52}, "listed": 55, "judging": {"configured_note_block": "both_agree", "disagreements": 1, "failures": 0, "judge_model": "local/gemma-4-26b-a4b-nvfp4", "may_block": true, "mode": "agreement", "note_block": "both_agree", "note_block_code": "ok", "note_block_reason": "judge and verifier must both say fail", "verifier_model": "local/qwen3.5-9b-awq"}, "window": {"from": 1794547397.268217, "to": 1794547576.546876, "from_at": "2026-11-13T13:23:17.268217+08:00", "to_at": "2026-11-13T13:26:16.546876+08:00"}}
```

## hospital-ja@c4: canary

```json
{"gate": "on", "allows_block": true, "code": "ok", "reason": "", "running": false, "at": "2026-11-13T05:23:08", "ok": true, "cases": 54, "pair_correct": 52, "pair_decided_wrong": 0, "models": [{"role": "judge", "model": "local/gemma-4-26b-a4b-nvfp4", "correct": 53, "flips": 1, "ok": true}, {"role": "verifier", "model": "local/qwen3.5-9b-awq", "correct": 49, "flips": 1, "ok": true}], "wake_failure": null}
```

## hospital-ja@c16: screen

```json
{"funnel": [["S0", 3022], ["S1", 92], ["S3", 92], ["S4", 55]], "tiers": {"excluded": 2967, "high": 4, "review": 51}, "listed": 55, "judging": {"configured_note_block": "both_agree", "disagreements": 1, "failures": 0, "judge_model": "local/gemma-4-26b-a4b-nvfp4", "may_block": true, "mode": "agreement", "note_block": "both_agree", "note_block_code": "ok", "note_block_reason": "judge and verifier must both say fail", "verifier_model": "local/qwen3.5-9b-awq"}, "window": {"from": 1794548130.856609, "to": 1794548196.091453, "from_at": "2026-11-13T13:35:30.856609+08:00", "to_at": "2026-11-13T13:36:36.091453+08:00"}}
```

## hospital-ja@c16: canary

```json
{"gate": "on", "allows_block": true, "code": "ok", "reason": "", "running": false, "at": "2026-11-13T05:35:21", "ok": true, "cases": 54, "pair_correct": 52, "pair_decided_wrong": 0, "models": [{"role": "judge", "model": "local/gemma-4-26b-a4b-nvfp4", "correct": 53, "flips": 1, "ok": true}, {"role": "verifier", "model": "local/qwen3.5-9b-awq", "correct": 49, "flips": 1, "ok": true}], "wake_failure": null}
```

## hospital-zh-TW@c1: screen

```json
{"funnel": [["S0", 3022], ["S1", 92], ["S3", 92], ["S4", 55]], "tiers": {"excluded": 2967, "high": 3, "review": 52}, "listed": 55, "judging": {"configured_note_block": "both_agree", "disagreements": 1, "failures": 0, "judge_model": "local/gemma-4-26b-a4b-nvfp4", "may_block": true, "mode": "agreement", "note_block": "both_agree", "note_block_code": "ok", "note_block_reason": "judge and verifier must both say fail", "verifier_model": "local/qwen3.5-9b-awq"}, "window": {"from": 1794548639.621386, "to": 1794549280.38576, "from_at": "2026-11-13T13:43:59.621386+08:00", "to_at": "2026-11-13T13:54:40.385760+08:00"}}
```

## hospital-zh-TW@c1: canary

```json
{"gate": "on", "allows_block": true, "code": "ok", "reason": "", "running": false, "at": "2026-11-13T05:43:50", "ok": true, "cases": 54, "pair_correct": 52, "pair_decided_wrong": 0, "models": [{"role": "judge", "model": "local/gemma-4-26b-a4b-nvfp4", "correct": 53, "flips": 1, "ok": true}, {"role": "verifier", "model": "local/qwen3.5-9b-awq", "correct": 49, "flips": 1, "ok": true}], "wake_failure": null}
```

## hospital-zh-TW@c4: screen

```json
{"funnel": [["S0", 3022], ["S1", 92], ["S3", 92], ["S4", 55]], "tiers": {"excluded": 2967, "high": 4, "review": 51}, "listed": 55, "judging": {"configured_note_block": "both_agree", "disagreements": 1, "failures": 0, "judge_model": "local/gemma-4-26b-a4b-nvfp4", "may_block": true, "mode": "agreement", "note_block": "both_agree", "note_block_code": "ok", "note_block_reason": "judge and verifier must both say fail", "verifier_model": "local/qwen3.5-9b-awq"}, "window": {"from": 1794550296.421137, "to": 1794550477.172428, "from_at": "2026-11-13T14:11:36.421137+08:00", "to_at": "2026-11-13T14:14:37.172428+08:00"}}
```

## hospital-zh-TW@c4: canary

```json
{"gate": "on", "allows_block": true, "code": "ok", "reason": "", "running": false, "at": "2026-11-13T06:11:26", "ok": true, "cases": 54, "pair_correct": 52, "pair_decided_wrong": 0, "models": [{"role": "judge", "model": "local/gemma-4-26b-a4b-nvfp4", "correct": 53, "flips": 1, "ok": true}, {"role": "verifier", "model": "local/qwen3.5-9b-awq", "correct": 49, "flips": 1, "ok": true}], "wake_failure": null}
```

## hospital-zh-TW@c16: screen

```json
{"funnel": [["S0", 3022], ["S1", 92], ["S3", 92], ["S4", 55]], "tiers": {"excluded": 2967, "high": 3, "review": 52}, "listed": 55, "judging": {"configured_note_block": "both_agree", "disagreements": 1, "failures": 0, "judge_model": "local/gemma-4-26b-a4b-nvfp4", "may_block": true, "mode": "agreement", "note_block": "both_agree", "note_block_code": "ok", "note_block_reason": "judge and verifier must both say fail", "verifier_model": "local/qwen3.5-9b-awq"}, "window": {"from": 1794551096.797366, "to": 1794551158.863316, "from_at": "2026-11-13T14:24:56.797366+08:00", "to_at": "2026-11-13T14:25:58.863316+08:00"}}
```

## hospital-zh-TW@c16: canary

```json
{"gate": "on", "allows_block": true, "code": "ok", "reason": "", "running": false, "at": "2026-11-13T06:24:47", "ok": true, "cases": 54, "pair_correct": 52, "pair_decided_wrong": 0, "models": [{"role": "judge", "model": "local/gemma-4-26b-a4b-nvfp4", "correct": 53, "flips": 1, "ok": true}, {"role": "verifier", "model": "local/qwen3.5-9b-awq", "correct": 49, "flips": 1, "ok": true}], "wake_failure": null}
```
