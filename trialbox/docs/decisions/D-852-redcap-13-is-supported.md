# D-852 REDCap 13 is a supported version

- **Task:** RC13-F (the owner's ruling D-524: 13.7 is the hospital's production version)
- **PR:** this branch (`agent/RC13-F-redcap-13-supported`)
- **Date:** 2026-11-16
- **Status:** proposed (merges on green CI)
- **Builds on:** D-818 (17 supported), D-521 (the private 13.7.23 instance), D-847 to D-850

## Decision

1. `rc_bridge.client.SUPPORTED_MAJORS` is 13 to 17. 12 and earlier, and 18 and later, stay refused (`RC-VERSION`).
2. The evidence, from the owner's REDCap 13.7.23 run privately and offline with synthetic projects only: R1 to R9
   pass with the instance tool's fixes (D-850), and the client's ICD-04 calls (version, project, metadata, events,
   form-event mapping, data access groups, the record export and the export since a time) all answer. The recording
   stays outside the repository (D-521: nothing of REDCap's in it); the repository's tests stay on the simulator.
3. What 13.7 does differently from 17 is handled by the cards before this one: its English refusals (D-847), its
   positional dictionary import (D-848, D-850), a group user's token (D-849). Dates go to REDCap as Y-M-D, which both
   read (D-841).
