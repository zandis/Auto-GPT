# D-851 The handed-out dictionary keeps a calculated field's expression and a decimal field's places

- **Task:** RC13-E (from the REDCap 13.7.23 run, D-521; synthetic projects only)
- **PR:** this branch (`agent/RC13-E-calc-expression-kept`), cut from RC13-B (D-848)
- **Date:** 2026-11-16
- **Status:** proposed (merges on green CI)
- **Builds on:** D-848 (REDCap's 18 columns), D-840 (`@TB-DECIMALS`), STD-061

## Decision

1. `datacore.forms.Field.calculation` keeps a calculated field's expression as written in REDCap's dictionary; an
   `sql` field's query is never kept (it is an administrator's database query).
2. The study's stored Questionnaire carries the expression (`urn:trialbox:fhir:calculation`) and a decimal field's
   places (`urn:trialbox:fhir:decimal-places`), read back by `fields_of`; both were lost on the way through the
   Questionnaire, and the handed-out dictionary (`export.export_fields`) is built from it.
3. `forms.metadata` writes the expression in the choices-or-calculations column. On REDCap 13.7 a dictionary built
   this way was taken, and REDCap computed the field itself on import. TrialBox still never enters or computes the
   field's value for REDCap.
