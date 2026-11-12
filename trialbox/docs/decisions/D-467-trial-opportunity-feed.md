# D-467 The trial-opportunity feed: rounded aggregates per recruiting trial, signed by the site, shown on a hub

- **Task:** T-740 (`docs/plan/32-trial-opportunity-feed.md`)
- **PR:** this branch (`claude/project-thread-dq324y`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-74 (trial simulation inside COHORT), D-140 (ClinicalTrials.gov live, offline or cassette)

## Decision

1. **Feed, not data.** A site publishes one feed per night: for each actively recruiting ClinicalTrials.gov study in
   its areas, the counts of COHORT's trial simulation, reduced by `tb_common.opportunity.row_from_sim`. No patient
   identifier, row or note text is published.
2. **Rounding.** Every published count, including the drop of each top exclusion, goes through `round_count` at the
   feed threshold (default 10, never below 5 in code, never below 10 by site policy in T-742). Rates and the enrolment
   band are dropped when the eligible count is a small cell. The first counted criterion defines the pool and is not
   listed as an exclusion.
3. **Allow-list guard.** `guard` refuses any feed or row key outside the allow-list and any unrounded count, so a
   later change cannot add a field without changing this decision.
4. **Signature.** The site signs the canonical JSON (sorted keys, no spaces) with Ed25519; the hub shows a feed as
   "signed by site" only when it verifies against that site's registered key. The sample page uses throwaway keys.
5. **No smart contracts.** Provenance is the signed feed plus the sponsor's own re-run; payment is by contract.
