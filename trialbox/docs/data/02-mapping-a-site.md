# 2. Mapping a site

1. Copy `services/adapter/mapping/templates/csv_site.yaml` (or `cgrd_sql_site.yaml`; Japan:
   `services/adapter/mapping/jp_core/ssmix2_site.yaml`) to the site's mapping file.
2. Fill in `tables:`: `source`, `rename` (local to canonical columns, `services/adapter/mapping/templates/CANONICAL.md`)
   and `values` (local to canonical codes). Copy and edit the lab lookup CSV.
3. Check it against a real export:
   `python tools/mapping_check.py --mapping <file> --source csv --path <dir>` (also `--source ssmix2`). It must show 0
   missing columns and 0 structural errors. It lists unmapped lab codes for the lab team, and the rows with no
   ICD-10 or ATC code.

No code change is needed for a new site. A code nobody can read is never a "no": the answer becomes unknown with
reason `unknown_code_system`, and the feasibility page counts those patients (D-130).

**Record ids are per patient (D-1253).** The id of a patient's record (a visit, a booking, a diagnosis, a lab result,
a vital, an order, a procedure, a report, a note, a claim) is made from the site's number **and the patient**
(`id: {hid: <column>}`, HMAC of type, pid and number), because a hospital system may give two patients the same number
(an SS-MIX2 order number is unique per patient, day and type only). A reference by number (`{ref: {type: Encounter,
hid: enc_no}}`) is always to the same patient's record. A link to a patient's record the lake does not hold is
counted per table and type over the merged snapshot (`links_to_absent_records`). A row with no chart number is
rejected and counted (`rejected_no_patient`); a deleted row with no chart number removes nothing and is counted
(`deletes_without_patient`): send the chart number with every delete. Two of one night's rows with one id and other
content are counted (`id_collisions`; the last row is kept, as always). A chart merged into another keeps its records' ids
(made under the chart that sent the row) and every one of them names the surviving patient: two charts that each had
a visit "E1" keep two visits of one patient.

The loader refuses a mapping that could give a patient's record an id without its patient: `id: {column: ...}` on a
patient's record, an `id.patient` the record does not name as its patient (`{ref: {type: Patient, pid: <col>}}`), a
record of no patient that names a patient's record by number, and an `hid` id whose record names no patient and is
not declared site-wide. A record of no patient says so: `id: {hid: <column>, site_wide: true}`. A clinician, an
organisation, a place must; a drug, a device, a substance or a group may, unless a patient's record names it by
number (then it is that patient's, per order).

**Choosing `unique: site`.** Leave it out (the default) unless the source system guarantees that the number is
unique across the whole site for that record type, for all time. Declared (`id: {hid: <column>, unique: site}`), the
id is the number's alone: a record the source re-files to another chart keeps its id, moves to that patient, and is
counted (`moved_to_another_patient`). Left out, a re-filed record is a new record of the new patient, and the old one
stays under the first patient until the next full night. When unsure, leave it out: a wrong `unique: site` merges two
patients' records, the fault D-1253 ends. The shipped mappings (`tw_core/demo_his.yaml`, `jp_core/ssmix2_site.yaml`,
the CSV and SQL templates) declare none: their sources do not promise site-wide numbers.

A box that ran a release before D-1253 is rebuilt once (RUNBOOK §5, "Lake ids per patient").
