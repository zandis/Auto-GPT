# Canonical HIS columns (what the TW Core resource definitions read)

A site mapping maps **its** tables and columns onto these names with `rename`, and onto these codes with `values`.
After that, the shared resource definitions (`tw_core/demo_his.yaml`, inherited with `extends`) do the rest; no
code changes are needed. Columns marked † are optional (leave them unmapped if the HIS does not have them). Dates
are `YYYY-MM-DD`, date-times `YYYY-MM-DD HH:MM[:SS]` in the site time zone.

| table | key | columns | canonical codes (`values`) |
| --- | --- | --- | --- |
| patient | mrn | mrn, name, id_no, birth_date, sex, death_date†, phone† | sex: `M`, `F` |
| practitioner | staff_id | staff_id, name, dept_code | — |
| encounter | enc_no | enc_no, mrn, visit_datetime, dept_code, staff_id, enc_type | enc_type: `OPD`, `IPD`, `ER` |
| appointment | appt_no | appt_no, mrn, appt_datetime, duration_min, staff_id, dept_code, status | status: `B` booked, `A` arrived, `C` cancelled, `N` no-show |
| diagnosis | diag_no | diag_no, enc_no, mrn, icd10, diag_date, recorded_date, status | status: `A` active, `R` resolved |
| lab | lab_no | lab_no, mrn, local_code, item_name, result_value, unit, sample_datetime | local codes via the `lab` lookup CSV (local_code → LOINC) |
| vital | vital_no | vital_no, mrn, measure_datetime, height_cm†, weight_kg†, sbp†, dbp† | — |
| medication | rx_no | rx_no, mrn, nhi_drug_code, atc, drug_name, order_date, start_date, end_date, daily_dose, dose_unit, status, dept_code† | status: `active`, `completed`, `stopped` |
| procedure | proc_no | proc_no, mrn, order_code, proc_name, proc_date | — |
| report | rpt_no | rpt_no, mrn, exam_code, exam_name, exam_date, conclusion | exam_code `RAD-CXR` = chest X-ray |
| note | note_no | note_no, mrn, enc_no, note_datetime, note_type, text | note_type: `progress`, `admission`, `discharge`, `consult`, `nursing` |
| claim | claim_no | claim_no, mrn, created_date, product_code, apply_type, outcome, approval_start†, approval_end† | outcome: `approved`, `denied`, `pending` |
| registry† | mrn | mrn, consent_contact, consent_date | consent_contact: `Y`, `N` |

`identity: {name: name, national_id: id_no}` on the patient table keeps the name and national id encrypted in the
pid map (TWPAS only); they never reach the lake.

Check a filled mapping against a real export before the first nightly run:

    python tools/mapping_check.py --mapping services/adapter/mapping/<profile>/<site>.yaml --source csv --path <dir>
