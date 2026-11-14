# D-612 The update window passes when whole nights were measured and clear it

- **Task:** NEW-WIN-5, second follow-up (lane W)
- **PR:** this branch (`agent/NEW-WIN-5-update-window-pass`)
- **Date:** 2026-11-13
- **Status:** accepted. Logic only; no night has run on a Windows workstation
- **Builds on:** D-610 (the window judged against the recorded nights; its point 2 left the PASS open), D-667
  (NEW-B-26: the orchestrator's `work_start` and `work_end` in the night record)

## Context

D-610 could fail a recorded night that ran into the update window, and otherwise only warn: the record ended with
the adapter's part of the night, and what the orchestrator does after it (deriving, the twins, screening) was not
in it. D-667 adds that work to the record, for the nights where the orchestrator measured it.

## Decision

1. **A night's end is the end of its work where the record has it**: when a night carries `work_start` and
   `work_end`, and the work ends at or after the ingest's end, the night ends at `work_end`. A night without the
   two keys was measured only to the end of ingest; that is never read as "no work after the publish".
2. **FAIL** as in D-610, now with that end: a recorded night began inside the window or ran into its next
   opening, to the end of its work where known.
3. **PASS** when every recorded night was measured to the end of its work and each ended before the window
   opens. The line gives the least margin. No margin figure is required of it: D-610 spoke of "a declared
   margin", and no measurement exists yet to set one from; the owner reads the margin and judges it.
4. **WARN** otherwise: no recorded night; or some nights measured only to the end of ingest. The line then gives
   both groups with their least margins and says the work after ingest is not known for the second.

**Reuse check.** Lane B's record and function are used as they are; nothing is added.

## What is proven here, and what is not

Proven here (`tests/unit/test_windows_update.py`, written records): whole nights clear of the window pass with
the least margin; work that ran into the window fails though the ingest did not; a night without its work keeps
the line at a warning; work that ends before its ingest ended is not taken as the night's end.

Not proven: any real night, and that the orchestrator's work reaches the host's copy of the record under WSL2.
