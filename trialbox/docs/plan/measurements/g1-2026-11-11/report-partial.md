# TrialBox complete-platform run

Head `986d91c91352` (Orchestrator drain: a finished job is progress however long it took (G1 2026-11-11 failed on a 2.6 h job)). Run: 20261111T183639Z-986d91c9-s1. Model: local/gemma-4-26b-a4b-nvfp4, local/qwen3.5-9b-awq (gateway (installed box, synthetic weight pins)). Hospital: 50,000 synthetic patients. Languages: ja, zh-TW. OCR: tesseract. Host: x86_64, 48 CPUs.
Started 2026-11-12T00:01:04+00:00, finished 2026-11-12T00:01:04+00:00.

**FAILED**: 216 of 238 checks; 22 of 22 screenshots; 299.6 min in all; 0 known findings reported. **21 part(s) crashed or never ran** (hospital-zh-TW, public-ja, public-zh-TW, scenario-emr-ssmix2, scenario-emr-fhir, scenario-site-excel, scenario-chart-paste, scenario-chart-files, scenario-redcap, scenario-it-dump, scenario-registry, scenario-public-mimic, scenario-public-medtxt, scenario-public-trec, scenario-gateway, walk, backup, update, scale, embed, profile): their own checks never ran (number unknown); each counts as one failed check above.

Screenshots are in the run's `report/shots/` folder (not committed).

| part | stage | checks | result | seconds | screenshot |
| --- | --- | --- | --- | --- | --- |
| prepare | synthetic hospital | 2/2 | pass | 14.8 | `prepare.png` |
| install | install: tier and serving record | 4/4 | pass | 0.0 | `install.png` |
| hospital-ja | 0 data in | 4/4 | pass | 0.4 | `hospital-ja-00.png` |
| hospital-ja | 1 feasibility report | 8/8 | pass | 0.2 | `hospital-ja-01.png` |
| hospital-ja | 2 investigator approval | 2/2 | pass | 0.1 | `hospital-ja-02.png` |
| hospital-ja | 3 screening | 7/7 | pass | 0.0 | `hospital-ja-03.png` |
| hospital-ja | 4 list, marks and mail | 7/7 | pass | 4.8 | `hospital-ja-04.png` |
| hospital-ja | 5 ready and needs-information lists | 8/8 | pass | 0.8 | `hospital-ja-05.png` |
| hospital-ja | 7 REDCap read-back and screening log | 5/5 | pass | 0.1 | `hospital-ja-06.png` |
| hospital-ja | audit | 14/14 | pass | 14.9 | `hospital-ja-07.png` |
| hospital-ja | 8 REDCap write-back | 12/12 | pass | 0.7 | `hospital-ja-08.png` |
| hospital-ja | 9 data core: REDCap off then on, conflicts, a PI's sheet | 13/13 | pass | 0.2 | `hospital-ja-09.png` |
| hospital-ja | 10 built-in data capture | 15/15 | pass | 1.7 | `hospital-ja-10.png` |
| hospital-ja | 11 trial lifecycle | 25/25 | pass | 12.2 | `hospital-ja-11.png` |
| hospital-ja | 12 site set-up and data harmonization | 22/23 | FAIL | 37.1 | `hospital-ja-12.png` |
| hospital-ja | 13 Japan: SS-MIX2, JP Core and the licensed code lists | 16/16 | pass | 10.3 | `hospital-ja-13.png` |
| hospital-ja | 14 ClinicalTrials.gov offline: the reference data pack | 12/12 | pass | 0.8 | `hospital-ja-14.png` |
| hospital-ja | re-run (FR-REP-02) | 2/2 | pass | 9.5 | `hospital-ja-15.png` |
| hospital-ja | 15 delegation, candidates and referral | 15/15 | pass | 8584.1 | `hospital-ja-16.png` |
| hospital-ja | 16 EDC prefill | 21/21 | pass | 10.6 | `hospital-ja-17.png` |
| hospital-ja | runtime | 1/1 | pass | 0.0 | `hospital-ja-18.png` |
| hospital-ja | db-csv: model exclusions against the generator's note truth | 1/1 | pass | 0 | `hospital-ja-19.png` |
| hospital-zh-TW | hospital-zh-TW did not report | 0/1 | FAIL | 0 |  |
| public-ja | public-ja did not report | 0/1 | FAIL | 0 |  |
| public-zh-TW | public-zh-TW did not report | 0/1 | FAIL | 0 |  |
| scenario-emr-ssmix2 | scenario-emr-ssmix2 did not report | 0/1 | FAIL | 0 |  |
| scenario-emr-fhir | scenario-emr-fhir did not report | 0/1 | FAIL | 0 |  |
| scenario-site-excel | scenario-site-excel did not report | 0/1 | FAIL | 0 |  |
| scenario-chart-paste | scenario-chart-paste did not report | 0/1 | FAIL | 0 |  |
| scenario-chart-files | scenario-chart-files did not report | 0/1 | FAIL | 0 |  |
| scenario-redcap | scenario-redcap did not report | 0/1 | FAIL | 0 |  |
| scenario-it-dump | scenario-it-dump did not report | 0/1 | FAIL | 0 |  |
| scenario-registry | scenario-registry did not report | 0/1 | FAIL | 0 |  |
| scenario-public-mimic | scenario-public-mimic did not report | 0/1 | FAIL | 0 |  |
| scenario-public-medtxt | scenario-public-medtxt did not report | 0/1 | FAIL | 0 |  |
| scenario-public-trec | scenario-public-trec did not report | 0/1 | FAIL | 0 |  |
| scenario-gateway | scenario-gateway did not report | 0/1 | FAIL | 0 |  |
| walk | walk did not report | 0/1 | FAIL | 0 |  |
| backup | backup did not report | 0/1 | FAIL | 0 |  |
| update | update did not report | 0/1 | FAIL | 0 |  |
| scale | scale did not report | 0/1 | FAIL | 0 |  |
| embed | embed did not report | 0/1 | FAIL | 0 |  |
| profile | profile did not report | 0/1 | FAIL | 0 |  |

## Scenarios

### db-csv: Hospital database feed (CGRD-style CSV)

**FAIL**: 210 of 212 checks.

* Input (ja): CGRD-style CSV export of 50,000 synthetic patients (two sites, JP and TW style)
* Counts: `{"patients": 50000, "screen_funnel": {"S0": 30369, "S1": 1193, "S3": 1193, "S4": 623}}`
* Expected: `"e2e_simple stages 0-1: lake = generator counts; FEAS INC-01/02 = recount from the CSVs"`
* Got: `{"0 data in": "4/4", "1 feasibility report": "8/8"}`
* Model calls: 6704
* Model exclusions: 464 (true 464, false 0, true ones missed 4)
  * `0022a3ef8c` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `01438c25c0` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0165cc61c3` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `01edb4e6e9` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `01ee48e27d` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `024c061351` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `03b8250b29` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `040ff0410e` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
  * `0494577805` GZQO-INC-05: truth {'GZQO-INC-05': 'no'}, correct
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
* Time: 17959.7 s. Screenshot: `hospital-ja-00.png`, `hospital-ja-01.png`, `hospital-ja-02.png`

* Input (zh-TW): -
* Counts: `{}`
* Expected: `{}`
* Got: `{}`
* Model calls: 0
* Time: 0 s. Screenshot: -
* FAILED: confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f
* FAILED: part ran: no result file

### emr-ssmix2: EMR: SS-MIX2 storage

**FAIL**: 0 of 1 checks.

* Input: -
* Counts: `{}`
* Expected: `{}`
* Got: `{}`
* Model calls: 0
* Time: 0 s. Screenshot: -
* FAILED: part ran: no result file

### emr-fhir: EMR: FHIR bulk export

**FAIL**: 0 of 1 checks.

* Input: -
* Counts: `{}`
* Expected: `{}`
* Got: `{}`
* Model calls: 0
* Time: 0 s. Screenshot: -
* FAILED: part ran: no result file

### site-excel: The site's own Excel and CSV lists

**FAIL**: 0 of 1 checks.

* Input: -
* Counts: `{}`
* Expected: `{}`
* Got: `{}`
* Model calls: 0
* Time: 0 s. Screenshot: -
* FAILED: part ran: no result file

### chart-paste: A single chart, pasted EMR text

**FAIL**: 0 of 1 checks.

* Input: -
* Counts: `{}`
* Expected: `{}`
* Got: `{}`
* Model calls: 0
* Time: 0 s. Screenshot: -
* FAILED: part ran: no result file

### chart-files: Chart files: Word, PDF, scans (OCR)

**FAIL**: 0 of 1 checks.

* Input: -
* Counts: `{}`
* Expected: `{}`
* Got: `{}`
* Model calls: 0
* Time: 0 s. Screenshot: -
* FAILED: part ran: no result file

### redcap: REDCap two-way and built-in forms

**FAIL**: 0 of 1 checks.

* Input: -
* Counts: `{}`
* Expected: `{}`
* Got: `{}`
* Model calls: 0
* Time: 0 s. Screenshot: -
* FAILED: part ran: no result file

### it-dump: IT dump with local codes

**FAIL**: 0 of 1 checks.

* Input: -
* Counts: `{}`
* Expected: `{}`
* Got: `{}`
* Model calls: 0
* Time: 0 s. Screenshot: -
* FAILED: part ran: no result file

### registry: Offline trial registry (reference data pack)

**FAIL**: 0 of 1 checks.

* Input: -
* Counts: `{}`
* Expected: `{}`
* Got: `{}`
* Model calls: 0
* Time: 0 s. Screenshot: -
* FAILED: part ran: no result file

### public-mimic: Real data: MIMIC-IV demo on FHIR (ODbL)

**FAIL**: 0 of 1 checks.

* Input: -
* Counts: `{}`
* Expected: `{}`
* Got: `{}`
* Model calls: 0
* Time: 0 s. Screenshot: -
* FAILED: part ran: no result file

### public-medtxt: Real data: MedTxt-CR Japanese case reports as pasted charts (CC BY 4.0)

**FAIL**: 0 of 1 checks.

* Input: -
* Counts: `{}`
* Expected: `{}`
* Got: `{}`
* Model calls: 0
* Time: 0 s. Screenshot: -
* FAILED: part ran: no result file

### public-trec: Real data: TREC Clinical Trials topics, trials and qrels (NIST, NCBI)

**FAIL**: 0 of 1 checks.

* Input: -
* Counts: `{}`
* Expected: `{}`
* Got: `{}`
* Model calls: 0
* Time: 0 s. Screenshot: -
* FAILED: part ran: no result file

### gateway: Probe: the installed box's model gateway

**FAIL**: 0 of 1 checks.

* Input: -
* Counts: `{}`
* Expected: `{}`
* Got: `{}`
* Model calls: 0
* Time: 0 s. Screenshot: -
* FAILED: part ran: no result file


## Part times

| part | wall seconds |
| --- | --- |
| prepare | 14.8 |
| install | 0.0 |
| hospital-ja | 17959.7 |
| hospital-zh-TW | 0 |
| public-ja | 0 |
| public-zh-TW | 0 |
| scenario-emr-ssmix2 | 0 |
| scenario-emr-fhir | 0 |
| scenario-site-excel | 0 |
| scenario-chart-paste | 0 |
| scenario-chart-files | 0 |
| scenario-redcap | 0 |
| scenario-it-dump | 0 |
| scenario-registry | 0 |
| scenario-public-mimic | 0 |
| scenario-public-medtxt | 0 |
| scenario-public-trec | 0 |
| scenario-gateway | 0 |
| walk | 0 |
| backup | 0 |
| update | 0 |
| scale | 0 |
| embed | 0 |
| profile | 0 |

## Failed checks

- hospital-ja / 12 site set-up and data harmonization: confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready: (7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f
- hospital-zh-TW / hospital-zh-TW did not report: part ran: no result file
- public-ja / public-ja did not report: part ran: no result file
- public-zh-TW / public-zh-TW did not report: part ran: no result file
- scenario-emr-ssmix2 / scenario-emr-ssmix2 did not report: part ran: no result file
- scenario-emr-fhir / scenario-emr-fhir did not report: part ran: no result file
- scenario-site-excel / scenario-site-excel did not report: part ran: no result file
- scenario-chart-paste / scenario-chart-paste did not report: part ran: no result file
- scenario-chart-files / scenario-chart-files did not report: part ran: no result file
- scenario-redcap / scenario-redcap did not report: part ran: no result file
- scenario-it-dump / scenario-it-dump did not report: part ran: no result file
- scenario-registry / scenario-registry did not report: part ran: no result file
- scenario-public-mimic / scenario-public-mimic did not report: part ran: no result file
- scenario-public-medtxt / scenario-public-medtxt did not report: part ran: no result file
- scenario-public-trec / scenario-public-trec did not report: part ran: no result file
- scenario-gateway / scenario-gateway did not report: part ran: no result file
- walk / walk did not report: part ran: no result file
- backup / backup did not report: part ran: no result file
- update / update did not report: part ran: no result file
- scale / scale did not report: part ran: no result file
- embed / embed did not report: part ran: no result file
- profile / profile did not report: part ran: no result file

## hospital-ja: screen

```json
{"funnel": [["S0", 30369], ["S1", 1193], ["S3", 1193], ["S4", 623]], "tiers": {"excluded": 29746, "high": 33, "review": 590}, "listed": 623, "judging": {"configured_note_block": "both_agree", "disagreements": 8, "failures": 3, "judge_model": "local/gemma-4-26b-a4b-nvfp4", "may_block": true, "mode": "agreement", "note_block": "both_agree", "note_block_reason": "judge and verifier must both say fail", "verifier_model": "local/qwen3.5-9b-awq"}}
```

## hospital-ja: canary

```json
{"gate": "on", "allows_block": true, "code": "ok", "reason": "", "running": false, "at": "2026-11-11T18:50:49", "ok": true, "cases": 54, "pair_correct": 52, "pair_decided_wrong": 0, "models": [{"role": "judge", "model": "local/gemma-4-26b-a4b-nvfp4", "correct": 53, "flips": 1, "ok": true}, {"role": "verifier", "model": "local/qwen3.5-9b-awq", "correct": 49, "flips": 1, "ok": true}], "wake_failure": null}
```
