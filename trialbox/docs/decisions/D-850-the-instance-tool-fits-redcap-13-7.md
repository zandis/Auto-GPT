# D-850 The test-instance tool fits a real REDCap (13.7)

- **Task:** RC13-C (D-521: the owner's REDCap 13.7.23 run privately and offline in lane E's container; synthetic
  projects only)
- **PR:** this branch (`agent/RC13-C-instance-tool-on-13-7`)
- **Date:** 2026-11-16
- **Status:** proposed (merges on green CI)
- **Builds on:** D-584 (our own REDCap instance), D-840, D-845

## Decision

1. `tools/redcap_instance` takes an upgrade zip (the version folder only, carrying its installer), as the owner's
   package is; the release's top-level read-me texts are left in the zip; a zip outside `redcap/`, or with one root
   file and not the other, is still refused. For an upgrade zip the tool writes its own two web entry points (the API,
   the survey pages) and the two folders REDCap writes to (temp, uploaded files), which compose mounts writeable.
2. `RealAdmin.build` sends every dictionary row with REDCap's 18 columns in order (REDCap reads them by position),
   new data access groups without a unique name (REDCap names them), and users with their instrument, export and
   logging rights (an API-made user has none).
3. R6 imports each case alone (REDCap recalculates only the calculations driven by a batch's first row) and leaves
   the checkbox-driven case to the evaluator's own tests (REDCap's import does not recalculate it). The stand-in run
   compares 22 cases; the checkbox case is listed under `not_run`.
4. Run outside compose against 13.7.23 with these fixes: R1 to R9 all pass. The compose path itself stays unrun.
