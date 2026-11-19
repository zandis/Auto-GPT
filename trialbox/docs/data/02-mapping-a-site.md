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
record of no patient that names a patient's record by number, an `hid` id whose record names no patient and is
not declared site-wide, any `id.unique`, and a suffix on a site-wide id or on a link to one. A record of no patient says so: `id: {hid: <column>, site_wide: true}`. A clinician, an
organisation, a place must; a drug, a device, a substance or a group may, unless a patient's record names it by
number (then it is that patient's, per order).

**A record the hospital re-files to another chart** (D-1253, review round 3) is a new record of that chart's patient,
with that patient's id; there is no site-wide id for a patient's record, and the loader refuses `id.unique`. So a
delete, a link and a suffix never reach another patient's record. The limit: a **delta night** (one asked for with
`since`: `adapter run --since`, or an ingest job's `since` option) sends the changed rows only and cannot see that the
row left the first chart, so the lake keeps the first patient's stale copy beside the new one until the next **full
night**, which holds the new one only. The same holds after a chart merge when the hospital also re-files the
absorbed chart's rows under the surviving chart: duplicate visits and diagnoses of one patient until the next full
night. The box's scheduled night reads every table whole (it sends no `since`). A site that runs delta nights runs a
full night, a scheduled night without `since`, at least once a week. There is no separate interval setting.

A box that ran a release before D-1253 is rebuilt once (RUNBOOK §5, "Lake ids per patient").
