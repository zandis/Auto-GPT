# D-847 REDCap 13.7's English refusals read as their kinds

- **Task:** RC13-A (D-1021: the owner's REDCap 13.7.23 run privately and offline in lane E's container; synthetic
  projects only)
- **PR:** this branch (`agent/RC13-A-redcap-13-refusals`)
- **Date:** 2026-11-16
- **Status:** proposed (merges on green CI)
- **Builds on:** D-818 (the Chinese refusals), NEW-EDC-7 (REDCap's text is never shown)

## Decision

1. `rc_bridge.client.error_kind` reads five refusals 13.7 gives in English that it did not know: a date it cannot
   read and a value outside the field's choices (a value that does not fit its validation), a missing record-id
   field, an import that is not well-formed JSON, and a write to a record of another data access group (a kind of
   its own: "a record belongs to another data access group", read before the group's own kind).
2. A bad repeat instance reads as a repeating-instrument problem: REDCap's sentence names the event first, so the
   instance's marker is read before the event's.
3. Nothing else changes: an unknown text is still not shown. The simulator keeps 17's date reading (Y-M-D or M/D/Y,
   D-843); 13.7 takes M/D/Y only when the call names its date format, and TrialBox always sends Y-M-D (D-841).
