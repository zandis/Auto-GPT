# 18. Developing a site mapping without the site's data

**Reader:** the data steward.

The steward's procedure (T-011; TB-SITE-03). No row of the site's data leaves the hospital, and none is needed to
write the mapping. (The card named this §13; §13 was already taken by D-201.)

1. **Write the schema from the survey.** Copy `tests/fixtures/site_schema/tw-sample.yaml` (a CSV or SQL export) or
   `tests/fixtures/site_schema/jp-sample.yaml` (SS-MIX2) and fill it from the signed survey (TB-SITE-01, questions
   24 to 38; the field names are listed in `docs/plan/sites/site-survey.md` §2.3): the input, character set, date
   format and delimiter, the header row of each table, the code lists (departments, the lab table with units,
   diagnoses, drugs), the provider field, the appointment source and the note types. Structure and codes only: a
   key that would hold a value (`sample`, `rows`, `value`, `examples`, ...) is refused with "no values in a schema
   file", and so is a code-list name the site's character set cannot hold.
   `python -m tools.synth_site_from_schema validate <schema.yaml>` checks it against
   `schemas/site_schema.schema.json`.
2. **Build the synthetic site.** `python -m tools.synth_site_from_schema build <schema.yaml> --out <dir>` writes 500
   synthetic patients in the site's layout (CSV files, an SQLite database with its SQL dump, or SS-MIX2 storage),
   in its encoding and date format, with the planted faults of `plants`: lab codes no lookup knows and results in a
   unit the lookup does not expect. Chart numbers are `SYNT-0001` and so on and patients have no names, so a real
   chart number or name in the folder is something the data scan finds.
3. **Write the mapping against it.** Start from `services/adapter/mapping/templates/csv_site.yaml` (or
   `services/adapter/mapping/templates/cgrd_sql_site.yaml`, or `services/adapter/mapping/jp_core/ssmix2_site.yaml`),
   then run `python -m tools.synth_site_from_schema check <schema.yaml> --out <dir> --mapping <mapping.yaml>` until
   it passes and the unmapped codes it lists are the planted ones only. A unit-mismatch line means those results get
   no value (unknown, never a wrong number): fix the lookup's `source_unit` or `factor`, never the result.
4. **Scan the folder.** `python -m tools.data_scan <dir>` must be clean.
5. **On the hospital's hardware**, after the data-processing agreement, the steward runs the same `check` on the
   10-patient sample (question 41) with the finished mapping, then `adapter run`. Only the report leaves: per table
   the rows read, the resources, the missing columns, the unmapped codes and the unit-mismatch counts, and a parse
   error with its value cut out. Never a row, a value or a chart number.

The adapter reads UTF-8 comma-separated CSV with ISO dates (or `YYYY/MM/DD`, `YYYYMMDD`) and SS-MIX2 storage. A
site whose export is Big5 or Shift_JIS, tab-separated, or has ROC 7-digit dates is read by `check` through a staging
copy (UTF-8, ISO dates, the same headers) until the adapter's sources read those forms themselves; the nightly feed
needs the same conversion until then.

**The data scan and the site's chart number.** When the signed survey states the chart number's form (question 26),
put it in the schema's `identifiers.chart_number` and run `python -m tools.synth_site_from_schema scan-pattern
<schema.yaml>`. A form with letters or a check digit gives a pattern for a bare chart number (no label), to add to
`tools/data_scan_patterns.yaml` with its planted positive (D-203). A form of digits only, with no check digit, gives
none: such a pattern would hit every date and count, and the labelled `chart_number` pattern stays the control.
