# D-576 The box installer remembers that the owner's answers were applied

- **Task:** BOX-APPLIED (given to lane D by the integrator on 2026-11-12, from the review of lane W's #362,
  finding M1)
- **PR:** this branch (`agent/BOX-applied-mark`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-466 (the box form: `box-install.sh`, the first-run code, the wizard, the apply step), D-571

## Context

`box-install.sh` leaves no lasting mark that the owner's answers were applied. The wizard's answers are in a tmpfs
folder and are removed by the apply step. If the script is interrupted after the apply and before its last line
(the window closes, the session drops), the next start runs the first-run part again: it prints a new code, which
the console no longer accepts because the set-up is finished there, and waits for answers that never come.

## Decision

1. **After the apply step succeeds the script writes `deploy/site/box/applied`** (the time, UTC).
2. **A start that finds the mark does not show a code and does not wait.** It says when the answers were applied
   and goes on with what follows the apply: the stack on the new settings, the backup schedule, the host check and
   the last line `TrialBox is ready`.
3. **A new install removes the mark**: when the script plans the box again from its hardware, the answers are
   provisional again and the wizard is due.

## Consequences

- An interrupted first run finishes on the next start, with the same last line the Windows installer reads.
- The mark is in `deploy/site/`, which a release never replaces and a backup of the host tree carries.
- No setting, no limit, no new store.
