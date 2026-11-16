# D-1038 One licence budget line for restic in the backup image

- **Task:** an owner's ruling, numbered by the integrator and relayed by the integrator
- **Date:** 2026-11-16
- **Status:** accepted (the owner's ruling; recorded here on 2026-11-16)

## Ruling

1. `deploy/supply-chain-allowlist.yaml` may carry one licence budget line for the image `trialbox-backup`, ecosystem
   `golang`, at most 86, reviewed by 2027-02-01. It counts restic and its Go modules, built from source, because a
   licence scanner reads no licence from a Go binary.
2. The yes is for this licence count only. It waives no vulnerability finding.
3. A count below 86 lowers the line to that count. A count above 86 goes back to the owner.

## Where the wording comes from

The owner's "yes" of 2026-11-16 in the integrator's session, to lane D's question on PR #639.

## Used by

D-968 (PERF-010, restic for the incremental backup); the line itself, which the integrator adds on the train that carries
D-968's first card.
