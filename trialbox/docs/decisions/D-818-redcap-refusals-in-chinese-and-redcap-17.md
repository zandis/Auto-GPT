# D-818 REDCap's refusals in Traditional Chinese read as their kinds; REDCap 17 is supported

- **Task:** CGRD-B2 (from the browser run against a real REDCap 17 instance; synthetic records only)
- **PR:** this branch (`agent/CGRD-B2-redcap-chinese-refusals`)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** NEW-EDC-7 (`error_kind`: REDCap's text is never shown, only its kind), FR-RC-14 (supported majors)

## Decision

1. A REDCap whose interface is Traditional Chinese answers an import in that language. Its phrases for a locked form,
   a field not in the project, an invalid category, a value that is not validated and an invalid date sit beside the
   English markers: the send reads the same kinds. A list of field names after a full-width colon is read too.
2. REDCap 17 joins the supported majors: it was exercised on a real instance. 18 and later stay refused until run.
