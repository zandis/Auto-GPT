# D-854 A reason or a citation longer than 300 characters is refused, never cut

- **Task:** EDC-022 (deep review 2026-11-12, Low; wave 6, unfrozen by D-1027)
- **PR:** this branch (`agent/EDC-022-long-reason-refused`)
- **Date:** 2026-11-16
- **Status:** proposed (merges on green CI)
- **Builds on:** D-281 (reasons for change), EDC-010 / D-581 (texts checked before they are stored)

## Decision

1. A reason for change (a decision, the prefill switch, a copy-assist tick) or a citation's text longer than 300
   characters (`edc.store.TEXT_MAX`) is refused with `edc.too_long` (400), saying how long it is; nothing is stored.
   300 characters still go in whole. The store cut them silently, so a regulated trail kept part of what a person
   wrote.
2. The check is in the store (`edc.store.said`), before anything is written, and in the service's decision path
   beside the character check of EDC-010, so the refusal is audited like the others.
3. Class B (the prefill path): no change to who sees patient data, so no adversarial review in the build phase
   (D-511).
