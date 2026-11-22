# D-1069 What a note answer may do, and the bar accuracy is held to

- **Task:** an owner's ruling, numbered by the integrator; the engine's cards (lane E), the accuracy sheets
- **Date:** 2026-11-22
- **Status:** accepted (the owner's ruling of 2026-11-22 10:40 UTC; recorded here the same day)

## Ruling

1. For rc1 and the pilot a note answer never removes a patient silently. An inclusion criterion answered "not met"
   from notes sends the patient to review. Only an exclusion criterion whose quote states the condition removes a
   patient, and only when two different models agree (the existing rule).
2. "13.8 % against 5 %" is not quoted any more. That figure came from a benchmark prompt on a public set whose
   labels are not clean, and the 5 % limit was written for physician-labelled sets.
3. The bar is the per-criterion false-block rate and the decided share, per language, on physician-checked sets,
   and beside them the product-path figure of D-918 with its labels checked by a person.
4. At most 5 % of eligible patients wrongly excluded stays the goal for a site's own retrospective run, where the
   labels are an investigator's.
5. The numbers of point 3 are fixed after a review of comparable systems; until then they are measured and
   reported, not a gate (D-1068 point 2 stands).

## What it changes in earlier records

- D-918 stands for how the product-path figure is measured. Its use as a pass or fail at 5 % on the public set is
  superseded by points 2 to 4 here, in part: the figure is still taken and reported.
- D-343 ("N-12 gates on the unadjusted figure") is superseded in the same part.
- Plan 10's criterion 1 (`docs/plan/47-plan-10-2026-11-18.md`, section 5.2) is read with points 3 and 4.

## Where the wording comes from

The owner's rulings on the plan 10 review, relayed by the integrator on the inbox (#639 comment 7077918101, ruling
1). The review is pull request #1327, sections 2.1 and 4.2 (decision 1).

## Used by

Lane E's engine cards (one function decides what a note answer may do, for every scenario); the accuracy sheet of
rc1; the bench's product-path run.
