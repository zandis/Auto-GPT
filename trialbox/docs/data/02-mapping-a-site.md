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
hid: enc_no}}`) names the same patient's record; when tonight the number is only another patient's, the link is left
out and counted (`references_to_another_patient`). A row with no chart number is rejected and counted; a deleted row
with no chart number removes nothing and is counted (`deletes_without_patient`): send the chart number with every
delete. Two of one night's rows of one patient with one number and other content are counted (`id_collisions`; the
last row is kept, as always). A record of no patient (a clinician, a ward) says so: `id: {hid: <column>, site_wide:
true}`; a mapping whose `hid` id names no patient and is not declared site-wide is refused when it loads. A box that
ran a release before D-1253 is rebuilt once (RUNBOOK §5, "Lake ids per patient").
