# D-856 The planned values are read again just before the import; one a person changed is held

- **Task:** EDC-011 (deep review 2026-11-12, Medium, case 9b; wave 6, unfrozen by D-1027)
- **PR:** this branch (`agent/EDC-011-reread-before-import`), cut from EDC-018 (#848)
- **Date:** 2026-11-16
- **Status:** proposed (merges on green CI)
- **Builds on:** D-693 (ownership from TrialBox's own writes; it left EDC-011 to a later card), NEW-EDC-2 (a repeat
  instance whole or not at all), E-17 (TrialBox's own values re-read before the import)

## Decision

1. Just before the import (after TrialBox's own values are re-read, E-17, and before the attempt is ledgered), the
   send reads REDCap's values of the planned fields once more, for the planned records only. A value that differs
   from what REDCap held at the first read was changed by a person while the send ran: it is held as a `conflict`,
   never overwritten; its ledger line says so and keeps the value seen at the first read. A repeat instance with such
   a change is held whole (`instance_taken` for its other values).
2. REDCap's API has no conditional write, so this narrows the window to the time between this read and the import;
   it cannot close it. It costs one more export of the planned records per send.
3. Class B (the prefill path): no change to who sees patient data, so no adversarial review in the build phase
   (D-511).
