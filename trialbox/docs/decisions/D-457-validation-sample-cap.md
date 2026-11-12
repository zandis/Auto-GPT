# D-457 The ingest gate's validation sample: an absolute cap per resource type beside the 1 %

- **Task:** T-693 (`docs/plan/28-master-plan-v6.md` §6.2.10; the night and capacity lane)
- **PR:** this branch (`agent/T-693-validation-sample-cap`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Closes:** the rest of F-06 of `docs/reviews/2026-11-11-scale-timeouts.md`
- **Builds on:** D-149 (validate before `CURRENT` moves; the night is held over the limit), the fix made with the
  review (one validator run per 5,000 files), OD-10 (a count is derived, or a declared setting with a reason)

## Context

The gate validates a sample of the night's resources: 1 % of each resource type, at least 3. The share has no upper
end. A first load of a hospital of 50,000 patients is about 25 million resources: a sample of 250,000 files, 50
validator runs; ten times that at 500,000 patients. The question the gate asks does not need it: "is the share of
resources that fail validation over the limit (`validation_error_max_pct`, 0.5 %)" is answered as well by a few
thousand resources of a type as by a few hundred thousand.

## Decision

1. **The sample of a resource type is its 1 %, at least 3, and at most a cap.** The same deterministic order as
   before (the hash of type and id), so a type under the cap is sampled exactly as it was.
2. **The cap is derived from the gate's own limit**, not a number of its own: the sample size at which the standard
   error of the measured failure share is a fifth of the limit, `ceil(25 x (1 - p) / p)` for the limit `p`. For the
   default limit of 0.5 % that is **4,975 resources per type**: one validator run per type. A stricter limit gives
   a larger cap by itself.
3. **Settable:** `TB_VALIDATION_SAMPLE_CAP` (a declared setting) replaces the derived cap; `0` is "no cap" (the
   plain 1 %, as before).
4. **Recorded in the night's report:** `validation.sample_cap` (the cap in force, absent when there is none) and
   `validation.capped` (each resource type the cap cut, with the number of its resources), in `ingest_report.json`
   and in the back-fill's report. A person reading the report sees that 4,975 of 2,400,000 observations were
   checked, not "1 %".
5. The same rule in the nightly pipeline and in the back-fill (one function, `validator.sample_size`).

## Consequences

- A load of 25 million resources validates at most the cap per type: tens of thousands of files, not 250,000.
- The error share is measured on the capped sample; the limit and the hold rule are unchanged.
- The JP Core profile check keeps its own fixed sample per type (D-137).
