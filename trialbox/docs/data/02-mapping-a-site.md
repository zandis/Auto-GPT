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
