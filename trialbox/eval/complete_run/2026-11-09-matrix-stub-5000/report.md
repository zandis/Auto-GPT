# TrialBox complete-platform run

Head `ada9c8f5d2f6` (Merge pull request #43: step 9 preparation (D-139); reference data pack and two CT.gov modes (D-140)) with local changes. Model: stub (stub in process). Hospital: 5,000 synthetic patients. Languages: ja, zh-TW. OCR: fake. Host: x86_64, 4 CPUs.
Started 2026-11-09T11:33:29+00:00, finished 2026-11-09T11:33:29+00:00.

**PASSED**: 662 of 662 checks; 84 of 84 screenshots; 33.2 min in all; 12 known findings reported.

Screenshots are in the run's `report/shots/` folder (not committed).

| part | stage | checks | result | seconds | screenshot |
| --- | --- | --- | --- | --- | --- |
| prepare | synthetic hospital | 2/2 | pass | 2.2 | `prepare.png` |
| install | install: tier and serving record | 3/3 | pass | 0.0 | `install.png` |
| hospital-ja | 0 data in | 4/4 | pass | 1.2 | `hospital-ja-00.png` |
| hospital-ja | 1 feasibility report | 8/8 | pass | 0.0 | `hospital-ja-01.png` |
| hospital-ja | 2 investigator approval | 2/2 | pass | 0.1 | `hospital-ja-02.png` |
| hospital-ja | 3 screening | 6/6 | pass | 0.0 | `hospital-ja-03.png` |
| hospital-ja | 4 list, marks and mail | 7/7 | pass | 1.0 | `hospital-ja-04.png` |
| hospital-ja | 5 ready and needs-information lists | 8/8 | pass | 0.9 | `hospital-ja-05.png` |
| hospital-ja | 7 REDCap read-back and screening log | 5/5 | pass | 0.1 | `hospital-ja-06.png` |
| hospital-ja | audit | 13/13 | pass | 0.8 | `hospital-ja-07.png` |
| hospital-ja | 8 REDCap write-back | 12/12 | pass | 1.0 | `hospital-ja-08.png` |
| hospital-ja | 9 data core: REDCap off then on, conflicts, a PI's sheet | 13/13 | pass | 0.3 | `hospital-ja-09.png` |
| hospital-ja | 10 built-in data capture | 15/15 | pass | 1.5 | `hospital-ja-10.png` |
| hospital-ja | 11 trial lifecycle | 25/25 | pass | 5.6 | `hospital-ja-11.png` |
| hospital-ja | 12 site set-up and data harmonization | 23/23 | pass | 31.7 | `hospital-ja-12.png` |
| hospital-ja | 13 Japan: SS-MIX2, JP Core and the licensed code lists | 16/16 | pass | 14.6 | `hospital-ja-13.png` |
| hospital-ja | 14 ClinicalTrials.gov offline: the reference data pack | 7/7 | pass | 1.5 | `hospital-ja-14.png` |
| hospital-ja | re-run (FR-REP-02) | 3/3 | pass | 22.3 | `hospital-ja-15.png` |
| hospital-ja | runtime | 1/1 | pass | 0.0 | `hospital-ja-16.png` |
| hospital-ja | db-csv: model exclusions against the generator's note truth | 1/1 | pass | 0 | `hospital-ja-17.png` |
| hospital-zh-TW | 0 data in | 4/4 | pass | 1.1 | `hospital-zh-TW-00.png` |
| hospital-zh-TW | 1 feasibility report | 8/8 | pass | 0.0 | `hospital-zh-TW-01.png` |
| hospital-zh-TW | 2 investigator approval | 2/2 | pass | 0.1 | `hospital-zh-TW-02.png` |
| hospital-zh-TW | 3 screening | 6/6 | pass | 0.0 | `hospital-zh-TW-03.png` |
| hospital-zh-TW | 4 list, marks and mail | 7/7 | pass | 1.1 | `hospital-zh-TW-04.png` |
| hospital-zh-TW | 5 ready and needs-information lists | 8/8 | pass | 1.0 | `hospital-zh-TW-05.png` |
| hospital-zh-TW | 7 REDCap read-back and screening log | 5/5 | pass | 0.1 | `hospital-zh-TW-06.png` |
| hospital-zh-TW | audit | 13/13 | pass | 0.8 | `hospital-zh-TW-07.png` |
| hospital-zh-TW | 8 REDCap write-back | 12/12 | pass | 1.1 | `hospital-zh-TW-08.png` |
| hospital-zh-TW | 9 data core: REDCap off then on, conflicts, a PI's sheet | 13/13 | pass | 0.3 | `hospital-zh-TW-09.png` |
| hospital-zh-TW | 10 built-in data capture | 15/15 | pass | 1.6 | `hospital-zh-TW-10.png` |
| hospital-zh-TW | 11 trial lifecycle | 25/25 | pass | 5.6 | `hospital-zh-TW-11.png` |
| hospital-zh-TW | 12 site set-up and data harmonization | 23/23 | pass | 31.8 | `hospital-zh-TW-12.png` |
| hospital-zh-TW | 13 Japan: SS-MIX2, JP Core and the licensed code lists | 16/16 | pass | 11.7 | `hospital-zh-TW-13.png` |
| hospital-zh-TW | 14 ClinicalTrials.gov offline: the reference data pack | 7/7 | pass | 1.2 | `hospital-zh-TW-14.png` |
| hospital-zh-TW | re-run (FR-REP-02) | 3/3 | pass | 19.3 | `hospital-zh-TW-15.png` |
| hospital-zh-TW | runtime | 1/1 | pass | 0.0 | `hospital-zh-TW-16.png` |
| hospital-zh-TW | db-csv: model exclusions against the generator's note truth | 1/1 | pass | 0 | `hospital-zh-TW-17.png` |
| public-ja | 0 public data in | 7/7 | pass | 0.8 | `public-ja-00.png` |
| public-ja | 1 criteria, approval and feasibility | 16/16 | pass | 9.1 | `public-ja-01.png` |
| public-ja | 2 screening (patient list) on real notes | 6/6 | pass | 6.4 | `public-ja-02.png` |
| public-ja | 3 list, S5 and marks | 13/13 | pass | 4.3 | `public-ja-03.png` |
| public-ja | 4 N1 / N2 mail | 3/3 | pass | 0.4 | `public-ja-04.png` |
| public-ja | 5 REDCap simulator read-back | 4/4 | pass | 1.1 | `public-ja-05.png` |
| public-ja | 5b trial lifecycle (D-134) | 7/7 | pass | 2.4 | `public-ja-06.png` |
| public-ja | 5c site set-up and data harmonization (D-135) | 6/6 | pass | 6.8 | `public-ja-07.png` |
| public-ja | 6 other screens | 38/38 | pass | 6.1 | `public-ja-08.png` |
| public-ja | 7 exports, CASE, consent explainer, Cancel / Retry | 11/11 | pass | 7.0 | `public-ja-09.png` |
| public-ja | 8 audit chain | 1/1 | pass | 0.0 | `public-ja-10.png` |
| public-zh-TW | 0 public data in | 7/7 | pass | 0.8 | `public-zh-TW-00.png` |
| public-zh-TW | 1 criteria, approval and feasibility | 16/16 | pass | 9.5 | `public-zh-TW-01.png` |
| public-zh-TW | 2 screening (patient list) on real notes | 6/6 | pass | 6.5 | `public-zh-TW-02.png` |
| public-zh-TW | 3 list, S5 and marks | 13/13 | pass | 3.8 | `public-zh-TW-03.png` |
| public-zh-TW | 4 N1 / N2 mail | 3/3 | pass | 0.3 | `public-zh-TW-04.png` |
| public-zh-TW | 5 REDCap simulator read-back | 4/4 | pass | 1.2 | `public-zh-TW-05.png` |
| public-zh-TW | 5b trial lifecycle (D-134) | 7/7 | pass | 2.2 | `public-zh-TW-06.png` |
| public-zh-TW | 5c site set-up and data harmonization (D-135) | 6/6 | pass | 6.1 | `public-zh-TW-07.png` |
| public-zh-TW | 6 other screens | 38/38 | pass | 6.1 | `public-zh-TW-08.png` |
| public-zh-TW | 7 exports, CASE, consent explainer, Cancel / Retry | 11/11 | pass | 7.1 | `public-zh-TW-09.png` |
| public-zh-TW | 8 audit chain | 1/1 | pass | 0.0 | `public-zh-TW-10.png` |
| scenario-emr-ssmix2 | SS-MIX2: storage in, JP Core, the funnel, 疑い diagnoses | 6/6 | pass | 16.2 | `scenario-emr-ssmix2-00.png` |
| scenario-emr-ssmix2 | SS-MIX2: screening with the run's model | 3/3 | pass | 5.9 | `scenario-emr-ssmix2-01.png` |
| scenario-emr-fhir | FHIR: bulk export in, chart numbers out, the funnel | 6/6 | pass | 13.9 | `scenario-emr-fhir-00.png` |
| scenario-emr-fhir | FHIR: screening with the run's model | 3/3 | pass | 5.7 | `scenario-emr-fhir-01.png` |
| scenario-site-excel | the feed: screening with the run's model, before the lists arrive | 3/3 | pass | 3.4 | `scenario-site-excel-00.png` |
| scenario-site-excel | the PI's lists: messy Excel, Shift_JIS and Big5 CSV, joined to the feed | 4/4 | pass | 25.2 | `scenario-site-excel-01.png` |
| scenario-chart-paste | charts in: the model proposes facts, nothing counts yet | 6/6 | pass | 16.4 | `scenario-chart-paste-00.png` |
| scenario-chart-paste | the coordinator confirms or rejects each fact; then the patient check counts | 2/2 | pass | 36.8 | `scenario-chart-paste-01.png` |
| scenario-chart-files | charts in: the model proposes facts, nothing counts yet | 7/7 | pass | 17.5 | `scenario-chart-files-00.png` |
| scenario-chart-files | the coordinator confirms or rejects each fact; then the patient check counts | 2/2 | pass | 27.7 | `scenario-chart-files-01.png` |
| scenario-redcap | REDCap two-way: TrialBox's records out, REDCap's fields back | 3/3 | pass | 11.5 | `scenario-redcap-00.png` |
| scenario-redcap | built-in forms: records entered in TrialBox, exported as ODM | 2/2 | pass | 1.4 | `scenario-redcap-01.png` |
| scenario-redcap | REDCap site: screening with the run's model | 3/3 | pass | 2.8 | `scenario-redcap-02.png` |
| scenario-it-dump | IT dump: hospital codes unknown until mapped, then counted | 3/3 | pass | 9.3 | `scenario-it-dump-00.png` |
| scenario-registry | offline registry: the pack loaded, trials found with no network | 2/2 | pass | 5.3 | `scenario-registry-00.png` |
| scenario-public-mimic | MIMIC-IV FHIR demo: ingest, FEAS, recount | 3/3 | pass | 14.5 | `scenario-public-mimic.png` |
| scenario-public-mimic | MIMIC-IV FHIR demo: the cascade S0..S5 (EMPULSE) | 2/2 | pass | 32.1 | `scenario-public-mimic.png` |
| scenario-public-medtxt | MedTxt-CR (ja): case reports pasted, conditions read, negations kept out | 3/3 | pass | 11.6 | `scenario-public-medtxt-00.png` |
| scenario-public-trec | TREC CT: real trials, patient descriptions, qrels as truth | 1/1 | pass | 1.1 | `scenario-public-trec.png` |
| scenario-gateway | installed-box gateway: a judge call and a chart-reading call | 1/1 | pass | 0.3 | `scenario-gateway.png` |
| walk | public console for the walk (public_e2e, stub) | 1/1 | pass | 50.1 |  |
| walk | walk (5 roles x 3 languages x desktop and phone) | 4/4 | pass | 533.2 | `walk/` |
| backup | backup, wipe and restore (tools.backup_drill) | 11/11 | pass | 154.8 | `backup.png` |
| update | signed update, two rollbacks (tools.update_drill) | 12/12 | pass | 297.7 | `update.png` |
| scale | cascade at 5000 patients (hospital_sim scale) | 2/2 | pass | 72.7 | `scale.png` |

## Scenarios

### db-csv: Hospital database feed (CGRD-style CSV)

**pass**: 338 of 338 checks.

* Input (ja): CGRD-style CSV export of 5,000 synthetic patients (two sites, JP and TW style)
* Counts: `{"patients": 5000, "screen_funnel": {"S0": 3022, "S1": 92, "S3": 92, "S4": 81}}`
* Expected: `"e2e_simple stages 0-1: lake = generator counts; FEAS INC-01/02 = recount from the CSVs"`
* Got: `{"0 data in": "4/4", "1 feasibility report": "8/8"}`
* Model calls: 316
* Model exclusions: 0 (true 0, false 0, true ones missed 27)
* Time: 155.0 s. Screenshot: `hospital-ja-00.png`, `hospital-ja-01.png`, `hospital-ja-02.png`

* Input (zh-TW): CGRD-style CSV export of 5,000 synthetic patients (two sites, JP and TW style)
* Counts: `{"patients": 5000, "screen_funnel": {"S0": 3022, "S1": 92, "S3": 92, "S4": 81}}`
* Expected: `"e2e_simple stages 0-1: lake = generator counts; FEAS INC-01/02 = recount from the CSVs"`
* Got: `{"0 data in": "4/4", "1 feasibility report": "8/8"}`
* Model calls: 316
* Model exclusions: 0 (true 0, false 0, true ones missed 27)
* Time: 160.9 s. Screenshot: `hospital-zh-TW-00.png`, `hospital-zh-TW-01.png`, `hospital-zh-TW-02.png`

### emr-ssmix2: EMR: SS-MIX2 storage

**pass**: 9 of 9 checks.

* Input: SS-MIX2 storage of 500 patients (14,080 messages, 5 疑い)
* Counts: `{"Appointment": 310, "Claim": 84, "ClaimResponse": 84, "Condition": 1347, "Consent": 322, "Coverage": 500, "DiagnosticReport": 63, "DocumentReference": 924, "Encounter": 3374, "MedicationRequest": 4572, "Observation": 3502, "Organization": 2, "Patient": 500, "Practitioner": 8, "Procedure": 5}`
* Expected: `{"start": 500, "GZQO-INC-01": 479, "GZQO-INC-02": 133}`
* Got: `{"start": 500, "GZQO-INC-01": 479, "GZQO-INC-02": 133}`
* Model calls: 13
* Model exclusions: 0 (true 0, false 0, true ones missed 3)
* Screening: `{"funnel": {"S0": 302, "S1": 8, "S3": 8, "S4": 7}, "tiers": {"excluded": 295, "high": 0, "review": 7}, "listed": 7, "judging": {"configured_note_block": "both_agree", "disagreements": 0, "failures": 0, "judge_model": "stub", "may_block": false, "mode": "single", "note_block": "never", "note_block_reason": "no verifier configured: a single model may not exclude", "verifier_model": null}, "seconds":`
* Time: 143.5 s. Screenshot: `scenario-emr-ssmix2-00.png`, `scenario-emr-ssmix2-01.png`

### emr-fhir: EMR: FHIR bulk export

**pass**: 9 of 9 checks.

* Input: FHIR bulk export of 500 patients (15,419 resources, NDJSON)
* Counts: `{"Appointment": 317, "Claim": 80, "ClaimResponse": 80, "Condition": 1398, "Consent": 318, "Coverage": 500, "DiagnosticReport": 59, "DocumentReference": 875, "Encounter": 3397, "MedicationRequest": 4483, "Observation": 3397, "Organization": 2, "Patient": 500, "Practitioner": 8, "Procedure": 5}`
* Expected: `{"start": 500, "GZQO-INC-01": 484, "GZQO-INC-02": 144}`
* Got: `{"start": 500, "GZQO-INC-01": 484, "GZQO-INC-02": 144}`
* Model calls: 0
* Model exclusions: 0 (true 0, false 0, true ones missed 0)
* Screening: `{"funnel": {"S0": 0, "S1": 0, "S3": 0, "S4": 0}, "tiers": {"excluded": 0, "high": 0, "review": 0}, "listed": 0, "judging": {"configured_note_block": "both_agree", "disagreements": 0, "failures": 0, "judge_model": "stub", "may_block": false, "mode": "single", "note_block": "never", "note_block_reason": "no verifier configured: a single model may not exclude", "verifier_model": null}, "seconds": 1.5`
* Time: 23.2 s. Screenshot: `scenario-emr-fhir-00.png`, `scenario-emr-fhir-01.png`

### site-excel: The site's own Excel and CSV lists

**pass**: 7 of 7 checks.

* Input: 100 patients in 3 files over a 500-patient feed: {'xlsx': 36, 'sjis': 12, 'big5': 52}
* Counts: `{"files": {"候補者リスト.xlsx": {"rows": 36, "patients": 36, "facts": 108, "fixes": 110, "checks": 0, "dropped": ["氏名"]}, "候補者_sjis.csv": {"rows": 12, "patients": 12, "facts": 36, "fixes": 24, "checks": 0, "dropped": ["氏名"]}, "候選名單_big5.csv": {"rows": 52, "patients": 52, "facts": 208, "fixes": 104, "checks": 0, "dropped": ["姓名"]}}, "checks_answered": 0, "codes": {"suggested": 3, "site_knowledge": 0, "wrong_suggestions": []}, "planted": {"width": 22, "era": 48, "unit": 12, "minguo": 52, "merged": 12}}`
* Expected: `{"not_eligible": 40, "ready": 60}`
* Got: `{"not_eligible": 40, "ready": 60}`
* Model calls: 42
* Model exclusions: 0 (true 0, false 0, true ones missed 9)
* Screening: `{"funnel": {"S0": 303, "S1": 20, "S3": 20, "S4": 16}, "tiers": {"excluded": 287, "high": 2, "review": 14}, "listed": 16, "judging": {"configured_note_block": "both_agree", "disagreements": 0, "failures": 0, "judge_model": "stub", "may_block": false, "mode": "single", "note_block": "never", "note_block_reason": "no verifier configured: a single model may not exclude", "verifier_model": null}, "seco`
* Time: 64.1 s. Screenshot: `scenario-site-excel-00.png`, `scenario-site-excel-01.png`

### chart-paste: A single chart, pasted EMR text

**pass**: 8 of 8 checks.

* Input: 20 patients, 25 charts (pasted; ja 13, zh-TW 12)
* Counts: `{"proposed": 94, "confirmed": 94, "rejected": 0, "traps": {"family history": 6, "ruled-out gout": 9, "negated malignancy": 8}}`
* Expected: `{"not_eligible": 15, "ready": 5}`
* Got: `{"not_eligible": 15, "ready": 5}`
* Model calls: 25
* Extraction: precision 1.0, recall 1.0 (94 of 94 true facts, 94 proposed; OCR fake)
* Time: 58.7 s. Screenshot: `scenario-chart-paste-00.png`, `scenario-chart-paste-01.png`

### chart-files: Chart files: Word, PDF, scans (OCR)

**pass**: 9 of 9 checks.

* Input: 12 patients, 18 charts (files: {'docx': 5, 'pdf': 5, 'ocr': 8}; ja 9, zh-TW 9)
* Counts: `{"proposed": 62, "confirmed": 62, "rejected": 0, "traps": {"negated malignancy": 5, "family history": 4, "ruled-out gout": 4}}`
* Expected: `{"ready": 6, "not_eligible": 6}`
* Got: `{"not_eligible": 6, "ready": 6}`
* Model calls: 18
* Extraction: precision 1.0, recall 1.0 (62 of 62 true facts, 62 proposed; OCR fake)
* Time: 50.3 s. Screenshot: `scenario-chart-files-00.png`, `scenario-chart-files-01.png`

### redcap: REDCap two-way and built-in forms

**pass**: 8 of 8 checks.

* Input: rc_sim project 202 (longitudinal, DAGs), 50 TrialBox records; 25 built-in form records
* Counts: `{"pushed": 50, "consent_back": 16, "odm_subjects": 25}`
* Expected: `{"in_redcap": 50, "read_back": 16, "forms": 25}`
* Got: `{"in_redcap": 50, "read_back": 16, "forms": 25}`
* Model calls: 2
* Model exclusions: 0 (true 0, false 0, true ones missed 2)
* Screening: `{"funnel": {"S0": 185, "S1": 2, "S3": 2, "S4": 2}, "tiers": {"excluded": 183, "high": 0, "review": 2}, "listed": 2, "judging": {"configured_note_block": "both_agree", "disagreements": 0, "failures": 0, "judge_model": "stub", "may_block": false, "mode": "single", "note_block": "never", "note_block_reason": "no verifier configured: a single model may not exclude", "verifier_model": null}, "seconds":`
* Time: 20.6 s. Screenshot: `scenario-redcap-00.png`, `scenario-redcap-01.png`, `scenario-redcap-02.png`

### it-dump: IT dump with local codes

**pass**: 3 of 3 checks.

* Input: Shift_JIS dump, 295 rows of 200 patients, 5 local diagnosis codes, a JLAC10 lab code and a YJ drug code
* Counts: `{"codes": {"suggested": 4, "site_knowledge": 3, "wrong_suggestions": ["ZC16 胃癌: suggested C22.0, the site's code C16.9", "ZC50 乳癌: suggested C22.0, the site's code C50.919", "ZI10 本態性高血圧症: suggested E78.5, the site's code I10"]}, "checks": 0, "facts": 1157}`
* Expected: `{"needs": 57, "ready": 38, "not_eligible": 102}`
* Got: `{"not_eligible": 102, "needs": 57, "ready": 38}`
* Model calls: 0
* Note: no notes in a dump: the patient check is the structured SQL engine
* Time: 12.1 s. Screenshot: `scenario-it-dump-00.png`

### registry: Offline trial registry (reference data pack)

**pass**: 2 of 2 checks.

* Input: reference data pack sample (6 CT.gov records and five other sources)
* Counts: `{"tfda_indication": 3, "ctgov": 6, "tfda_trials": 2, "mhlw_yakka": 4, "nhi_drugs": 1, "icd10cm": 10}`
* Expected: `{"Japan": ["NCT99000001", "NCT99000003"], "Taiwan": ["NCT99000001", "NCT99000002"]}`
* Got: `{"Japan": ["NCT99000001", "NCT99000003"], "Taiwan": ["NCT99000001", "NCT99000002"]}`
* Model calls: 0
* Note: a registry has no patients: trials are found with no network; no patient model is called
* Time: 7.8 s. Screenshot: `scenario-registry-00.png`

### public-mimic: Real data: MIMIC-IV demo on FHIR (ODbL)

**pass**: 5 of 5 checks.

* Input: MIMIC-IV demo on FHIR v2.1.0: 100 patients (ODbL 1.0)
* Counts: `{"Condition": 4506, "Encounter": 415, "MedicationRequest": 17552, "Observation": 26905, "Patient": 100, "Procedure": 2190}`
* Expected: `{"patients": 100}`
* Got: `{"patients": 100, "cascade": {"S0": [100, 100], "S1": [100, 7], "S2": [7, 7], "S2b": [7, 7], "S3": [7, 7], "S4": [7, 7], "S5": [7, 0]}}`
* Model calls: 0
* Note: the cascade's model path is tools.cascade_e2e's in-process gateway over the stub
* Time: 47.9 s. Screenshot: `scenario-public-mimic.png`

### public-medtxt: Real data: MedTxt-CR Japanese case reports as pasted charts (CC BY 4.0)

**pass**: 3 of 3 checks.

* Input: 16 MedTxt-CR case reports (ja, real clinician text, CC BY 4.0)
* Counts: `{"positive_tags": 183, "negative_tags": 42, "conditions": 3, "on_positive_mention": 2, "on_untagged_text": 1}`
* Expected: `{"conditions_on_negated_mentions": 0}`
* Got: `{"conditions_on_negated_mentions": 0}`
* Model calls: 16
* Time: 14.3 s. Screenshot: `scenario-public-medtxt-00.png`

### public-trec: Real data: TREC Clinical Trials topics, trials and qrels (NIST, NCBI)

**pass**: 1 of 1 checks.

* Input: 10 TREC CT 2021/22 patient-trial pairs (5 eligible, 5 excluded by the qrels), 187 criteria
* Counts: `{"criteria": 187, "models": ["stub"]}`
* Expected: `{"eligible_lost": 0, "excluded_caught": 5}`
* Got: `{"eligible_lost": 0, "excluded_caught": 0}`
* Model calls: 187
* Note: judged by tools.mlbench's prompt straight to the model (an evaluation path, not the box)
* Time: 2.5 s. Screenshot: `scenario-public-trec.png`

### gateway: Probe: the installed box's model gateway

**pass**: 1 of 1 checks.

* Input: TB_ENV=PRODUCTION, TB_PROFILE=P-PRO6000, no TB_DATA_CLASS (as install.sh leaves it)
* Counts: `{}`
* Expected: `{"judge": "answered", "chart_facts": "answered"}`
* Got: `{"judge": "refused: gateway refused judge: step_unconfirmed", "chart_facts": "refused: tb_llm: prompt 'chart_facts' has no role in v1_roles.yaml"}`
* Model calls: 0
* Time: 1.4 s. Screenshot: `scenario-gateway.png`

## Known findings (reported, not fixed in this run)

| id | part | what | expected | got | holds |
| --- | --- | --- | --- | --- | --- |
| B-01 | scenario-emr-ssmix2 | lab values with a flag or a bound ('8.2 H', '>8.2', '<5.0'), the CSV feed: true urate >= 6.8 read as FALSE (a hard exclusion) | 0 of 5 | 0 of 5; {'xH -> None': 1, 'x H -> None': 2, '>x -> None': 1, '<x -> None': 1} | yes |
| B-01 | scenario-emr-ssmix2 | lab values with a flag or a bound ('8.2 H', '>8.2', '<5.0'), SS-MIX2 OBX-5: true urate >= 6.8 read as FALSE (a hard exclusion) | 0 of 5 | 0 of 5; {'xH -> None': 1, 'x H -> None': 2, '>x -> None': 1, '<x -> None': 1} | yes |
| P-04 | scenario-emr-ssmix2 | patients whose only malignancy is a 疑い (suspected) diagnosis, excluded by GZQO-EXC-07 | 0 of 5 | 5 of 5; the 疑い diagnosis is in the lake for 5 of them; EXC-07 verdicts {'True': 5} | NO |
| B-01 | scenario-emr-ssmix2 | flagged urate values in the SCREEN cascade (S1): true urate >= 6.8 failing GZQO-INC-04 | 0 of 5 in scope | 0 of 5 in scope | yes |
| FHIR-01 | scenario-emr-fhir | SCREEN scope on the FHIR path (patients booked in the study's clinics): the bulk path hashes Practitioner references but keeps Practitioner ids | S0 > 0, as on the SS-MIX2 path | S0 = 0; appointment practitioners found in the practitioner table: 0 of 8 | NO |
| XL-02 | scenario-site-excel | SCREEN GZQO on the hospital's own space after site lists are published into it | done | failed in 33 s OutOfMemoryException: Out of Memory Error: failed to offload data block of size 32.0 KiB (1.8 GiB/1.8 GiB used). This limit was set by the 'max_temp_directory_s | NO |
| B-03 | scenario-redcap | a longitudinal REDCap project linked with no event: TrialBox's values after two syncs | 5 of 5 kept | 0 of 5 kept; RC-UPSTREAM: REDCap returned 400: The event name '' is not valid | NO |
| MAP-01 | scenario-it-dump | suggested standard codes for the dump's local codes (by name) that name another disease | none | ZC16 胃癌: suggested C22.0, the site's code C16.9; ZC50 乳癌: suggested C22.0, the site's code C50.919; ZI10 本態性高血圧症: suggested E78.5, the site's code I10 | NO |
| DUMP-01 | scenario-it-dump | a cancer diagnosis row with no date (any time, no window): the patient is excluded | 3 of 3 | 1 of 3 (Counter({'ready': 2, 'not_eligible': 1})) | NO |
| MT-01 | scenario-public-medtxt | conditions proposed from a mention the corpus marks suspected (疑い) | 0 | 0 | yes |
| A-01 | scenario-gateway | a judge call (a PHI prompt) through the installed box's gateway | answered | refused: gateway refused judge: step_unconfirmed | NO |
| GW-02 | scenario-gateway | a chart_facts call (a PHI prompt) through the installed box's gateway | answered | refused: tb_llm: prompt 'chart_facts' has no role in v1_roles.yaml | NO |

## Part times

| part | wall seconds |
| --- | --- |
| prepare | 2.2 |
| install | 0.0 |
| hospital-ja | 155.0 |
| hospital-zh-TW | 160.9 |
| public-ja | 58.8 |
| public-zh-TW | 59.7 |
| scenario-emr-ssmix2 | 143.5 |
| scenario-emr-fhir | 23.2 |
| scenario-site-excel | 64.1 |
| scenario-chart-paste | 58.7 |
| scenario-chart-files | 50.3 |
| scenario-redcap | 20.6 |
| scenario-it-dump | 12.1 |
| scenario-registry | 7.8 |
| scenario-public-mimic | 47.9 |
| scenario-public-medtxt | 14.3 |
| scenario-public-trec | 2.5 |
| scenario-gateway | 1.4 |
| walk | 584.2 |
| backup | 155.0 |
| update | 297.8 |
| scale | 72.7 |

## hospital-ja: screen

```json
{"funnel": [["S0", 3022], ["S1", 92], ["S3", 92], ["S4", 81]], "tiers": {"excluded": 2941, "high": 2, "review": 79}, "listed": 81, "judging": {"configured_note_block": "both_agree", "disagreements": 0, "failures": 0, "judge_model": "stub", "may_block": false, "mode": "single", "note_block": "never", "note_block_reason": "no verifier configured: a single model may not exclude", "verifier_model": null}}
```

## hospital-zh-TW: screen

```json
{"funnel": [["S0", 3022], ["S1", 92], ["S3", 92], ["S4", 81]], "tiers": {"excluded": 2941, "high": 2, "review": 79}, "listed": 81, "judging": {"configured_note_block": "both_agree", "disagreements": 0, "failures": 0, "judge_model": "stub", "may_block": false, "mode": "single", "note_block": "never", "note_block_reason": "no verifier configured: a single model may not exclude", "verifier_model": null}}
```

## public-ja: screen

```json
{"funnel": {"S0": 268, "S1": 90, "S3": 90, "S4": 90}, "tiers": {"excluded": 178, "high": 0, "review": 90}, "listed": 90, "judging": {"configured_note_block": "both_agree", "disagreements": 0, "failures": 0, "judge_model": "stub", "may_block": false, "mode": "single", "note_block": "never", "note_block_reason": "no verifier configured: a single model may not exclude", "verifier_model": null}, "request_seconds": {"PUB-ONC": 4.6, "PUB-CA": 1.6}, "stage_seconds": 6.3}
```

## public-zh-TW: screen

```json
{"funnel": {"S0": 268, "S1": 90, "S3": 90, "S4": 90}, "tiers": {"excluded": 178, "high": 0, "review": 90}, "listed": 90, "judging": {"configured_note_block": "both_agree", "disagreements": 0, "failures": 0, "judge_model": "stub", "may_block": false, "mode": "single", "note_block": "never", "note_block_reason": "no verifier configured: a single model may not exclude", "verifier_model": null}, "request_seconds": {"PUB-ONC": 4.6, "PUB-CA": 1.7}, "stage_seconds": 6.3}
```

## walk: walk

```json
{"checks": 786, "failed": 0, "summary": {"pages": 774, "axe_by_impact": {"minor": 84}, "targets": 21735, "targets_under_44": 0, "taps": {"T1": 2, "T2": 2, "T3": 2, "T4": 5, "T5": 5, "T6": 3, "T7": 2, "T8": 2, "T9": 3}, "taps_max": {"T1": 2, "T2": 2, "T3": 2, "T4": 10, "T5": 5, "T6": 3, "T7": 3, "T8": 2, "T9": 3}}}
```

## scale: scale

```json
{"patients": 5000, "generate_s": 2.4, "pipeline_s": 70.2, "ms_per_patient": 14.04, "peak_rss_mb": 1831, "model_calls": 127, "final_list": 5}
```
