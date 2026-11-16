# D-819 Two minus signs in a row make a calculation blank, as REDCap stores it

- **Task:** CGRD-B4 (from the browser run against a real REDCap 17 instance; synthetic records only)
- **PR:** this branch (`agent/CGRD-B4-double-minus-is-blank`), cut from CGRD-B2 (#721)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** T-302b / D-414 (TrialBox's evaluator beside REDCap's calculations; R6)

## Decision

1. A calculation with two minus signs in a row (with or without spaces between them) is blank, as the real REDCap
   stores it; TrialBox's evaluator gave a number (`2*..*2 - -1` gave 1025). A value REDCap leaves blank is never
   filled by TrialBox.
2. Branching logic with two minus signs in a row is refused as unreadable: TrialBox does not guess what REDCap shows.
3. One minus before a bracket is a negation, as before. The evaluator test that expected 1025 now expects blank.
