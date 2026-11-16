# D-967 no remote session for the pilot

- **Task:** T-730 (its supervised remote session), lane D; the owner's ruling of 2026-11-16, relayed on #639 by the
  integrator (the integrator's number for it, D-536, is already taken on master)
- **PR:** this branch (`agent/T-730-REMOTE-no-remote-session-for-the-pilot`)
- **Date:** 2026-11-16
- **Status:** accepted

## Decision

T-730's supervised remote session for Aimedics is **not built now**. A hospital box has no remote way in for the
pilot: no account, no VPN, no open port, and no tool on the box for it. The question is revisited after the pilot,
with the hospital's IT. This answers TB-DR-09 Q2 for the pilot.

- The plan rows say so: T-730 in the v6.1 addendum, and lane D's row in plan v7 section 5. The card is off lane D's
  queue.
- RUNBOOK §21 keeps its rules for a screen share that the hospital starts with its own tool, from a hospital PC.
  That is the hospital's process and is nothing on the box. The page names this ruling for the pilot and keeps
  TB-DR-09 Q2 marked as a default for after it (`test_operations_docs.py` holds the mark).
- Nothing in the code changes. The egress rules (D-377) and the IT security pack (A.3, "no vendor remote access")
  already hold.

## Test

None new: a plan and runbook change. `test_operations_docs.py` (the Q2 mark), `doclint` and `decisions_index --check`
pass.
