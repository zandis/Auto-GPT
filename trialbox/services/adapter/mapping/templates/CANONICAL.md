# Canonical HIS columns (what the TW Core resource definitions read)

A site mapping maps **its** tables and columns onto these names with `rename`, and onto these codes with `values`.
After that, the shared resource definitions (`tw_core/demo_his.yaml`, inherited with `extends`) do the rest; no
code changes are needed. Columns marked † are optional (leave them unmapped if the HIS does not have them). Dates
are `YYYY-MM-DD`, date-times `YYYY-MM-DD HH:MM[:SS]` in the site time zone. A column the source writes in
the Republic-of-China calendar or a Japanese era is declared in the site mapping (`tables.<table>.dates: {<column>:
roc}`; `era`), and the source's placeholder dates in `empty_dates` (D-589); nothing is detected from the values.

| table | key | columns | canonical codes (`values`) |
| --- | --- | --- | --- |
| patient | mrn | mrn, name, id_no, birth_date, sex, death_date†, phone† | sex: `M`, `F` |
| practitioner | staff_id | staff_id, name, dept_code | — |
| encounter | enc_no | enc_no, mrn, visit_datetime, dept_code, staff_id, enc_type | enc_type: `OPD`, `IPD`, `ER` |
| appointment | appt_no | appt_no, mrn, appt_datetime, duration_min, staff_id, dept_code, status | status: `B` booked, `A` arrived, `C` cancelled, `N` no-show |
| diagnosis | diag_no | diag_no, enc_no, mrn, icd10, diag_date, recorded_date, status, suspected†, diag_code_system† | status: `A` active, `R` resolved; suspected: `Y` a suspected diagnosis (疑い, 疑似診斷), FHIR `verificationStatus` provisional: never excludes (D-142); diag_code_system: `icd9cm` or `icd10cm`, the edition of the code in `icd10` (D-586): it wins over the date rule of the site's `params.icd9cm_before` |
| lab | lab_no | lab_no, mrn, local_code, item_name, result_value, unit, sample_datetime, result_status† | local codes via the `lab` lookup CSV (local_code → LOINC); result_status: `final`, `amended`, `corrected`, `preliminary`, `registered`, `cancelled`, `entered-in-error` (empty: not recorded, counts; any other code: unknown, never counted as a result; D-275) |
| vital | vital_no | vital_no, mrn, measure_datetime, height_cm†, weight_kg†, sbp†, dbp† | — |
| medication | rx_no | rx_no, mrn, nhi_drug_code, atc, drug_name, order_date, start_date, end_date, daily_dose, dose_unit, status, dept_code† | status: `active`, `completed`, `stopped`, `on-hold`, `cancelled`, `entered-in-error`, `draft` (cancelled, entered-in-error and draft never count; empty: not recorded, counts; any other code: unknown, the order is kept undated; D-275) |
| procedure | proc_no | proc_no, mrn, order_code, proc_name, proc_date | — |
| report | rpt_no | rpt_no, mrn, exam_code, exam_name, exam_date, conclusion | exam_code `RAD-CXR` = chest X-ray |
| note | note_no | note_no, mrn, enc_no, note_datetime, note_type, text | note_type: `progress`, `admission`, `discharge`, `consult`, `nursing` |
| claim | claim_no | claim_no, mrn, created_date, product_code, apply_type, outcome, approval_start†, approval_end† | outcome: `approved`, `denied`, `pending` |
| registry† | mrn | mrn, consent_contact, consent_date | consent_contact: `Y`, `N` |

The Japan mapping (`jp_core/ssmix2_site.yaml`, D-137) reads a few more optional columns, which the SS-MIX2 reader
fills: encounter `end_datetime`, `enc_status` (`finished`, `in-progress`), `prev_enc_type` and `class_changed_at`
(ADT-52); diagnosis `byomei_code`, `byomei_name` (the 標準病名 code beside the ICD-10), and from PPR-01 (10B-3)
`written_name` (PRB-17), `modifiers` (ZPR 修飾語), `diagnosed_date` (PRB-7), `end_date` (PRB-9), `outcome` and
`outcome_date` (PRB-14 転帰 and PRB-15), `main_diagnosis` (PRB-18: `Y` 主診断, `N` 副診断), with `status` also `I`
inactive (転帰 死亡), `M` remission (寛解) and `U` (an outcome that says neither: unconfirmed, never active, D-587);
a PRB-1 `DE` diagnosis is a tombstone, never a row; lab `jlac10_code`,
`hosp_lab_code`, `specimen`; medication `hot_code`, `rp_no`, `rx_kind` (`prescription`, `injection`), `source_drug_code` (the code the order
line carried, when the site's drug master turned a HOT or local code into `nhi_drug_code`'s YJ code) and `yj_stem`
(the ingredient, T-610; empty when the line reached none); note_type
`report` and `document` (extended-storage documents).

`identity: {name: name, national_id: id_no}` on the patient table keeps the name and national id encrypted in the
pid map (TWPAS only); they never reach the lake.

Check a filled mapping against a real export before the first nightly run:

    python tools/mapping_check.py --mapping services/adapter/mapping/<profile>/<site>.yaml --source csv --path <dir>
