# D-845 The REDCap simulator locks a form and keeps a log, as a real REDCap does

- **Task:** CGRD-B5c (packet 2, B5 items 5 and 6; EDC-001), from the browser run against a real REDCap 17
- **PR:** this branch (`agent/CGRD-B5c-sim-locks-and-logs`), cut from CGRD-B5b (#738)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** D-584 (the stand-in run), NEW-EDC-7 (a locked form is a refusal)

## Decision

1. A form is locked or unlocked through the simulator's admin route `/sim/lock` (on a real REDCap a person or an
   administrator locks it); the stand-in run's admin uses it. An import that touches a locked form is refused whole,
   saying the form is locked; nothing of the file is written.
2. The simulator keeps the project's log, as REDCap writes it: `Create record (import) <id>`, `Update record (import)
   <id>`, `Update record (import) (Auto calculation) <id>`, `Lock instrument` / `Unlock instrument`, each with the user
   and the values (`field = 'value'`). The API's `log` content returns it (`logtype=record`: the writes). A refused
   import writes no entry.
3. The stand-in run's expected failures drop R3 and R9; R4 (rights per token) and R7 remain.
