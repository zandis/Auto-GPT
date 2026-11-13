# D-610 The update window is judged against the nights that ran

- **Task:** NEW-WIN-5, follow-up (`docs/plan/33-plan-v7.md` section 2.3: "placed outside the night from the night's
  measured length"; lane W)
- **PR:** this branch (`agent/NEW-WIN-5-night-length`)
- **Date:** 2026-11-13
- **Status:** accepted. Logic only; no night has run on a Windows workstation
- **Builds on:** D-606 (the update window; point 5 left this open), D-661 (NEW-B-20: the record of the nights that
  ran, `tools/night_length.py`, `deploy/site/night-length.json`)

## Context

D-606 gave `trialbox doctor` the line `update_window`: the hours in which Windows Update may restart the
workstation, against the night's start. It could fail a night that starts inside the window; it could not say
whether a night that starts outside also ends before the window opens, because nothing on the box recorded how
long a night takes. Lane B's D-661 now records it: for each night that finished on its first run, its start and
end in the site's time, copied to the host by the nightly backup.

## Decision

1. **`update_window` reads the recorded nights** (`night_runs(deploy)`), after the checks of D-606 (the window
   Windows holds, the night's start):
   - **FAIL** when a recorded night began inside the window or ran into its next opening; the line names how many
     of the recorded nights did, and the last three by date and time.
   - otherwise **WARN**, with the least time, over the recorded nights, between the end of a night and the
     window's opening.
   - with no recorded night: WARN as before, with the time between the night's start and the window.
2. **It never passes yet, and says why.** The record ends when the adapter's part of the night ends (ingest to
   the lake). What the orchestrator does after it (deriving, screening) is not in the record; lane B has that as
   a further card. Until then the line gives the margin and tells the owner to keep it larger than that work
   takes. Two more limits of the record are accepted as they are: the copy on the host is as old as the last
   backup run, so a night is seen the next day; and only nights that finished on their first run are in it, so
   after a bad week the list is short or empty, which is the unmeasured case, never a failure.
3. **The times are read as the record gives them**: each night on the clock of the day it began, in the site's own
   time with its offset. The window is in the workstation's clock; the two are the same zone on a site box
   (`check site_tz` judges that).

**Reuse check.** Lane B's function is used as it is; nothing is added.

## What is proven here, and what is not

Proven here (`tests/unit/test_windows_update.py`, written records): a night that ends before the window, with the
least margin over several; a night that ran into the window, began inside it, or ran a whole day; a night that
ends as the window opens; a window over midnight; a record with no finished night.

Not proven: any real night's length (the first night on the reference workstation), and that the nightly backup
under WSL2 copies the record to the host (lane B's and lane D's path; P-0 line 68 runs that backup).

## Consequences

- When the record also holds the orchestrator's part of the night, the WARN of point 2 becomes a PASS above a
  declared margin; that is a later, small change here.
