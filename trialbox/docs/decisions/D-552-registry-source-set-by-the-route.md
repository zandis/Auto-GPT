# D-552 A registry change through the route is a manual one, and a job named with it is a job of the study

- **Task:** T-715c (a finding of the review of T-715b, #459, older than that card; the integrator's word of
  2026-11-13)
- **PR:** this branch (`agent/T-715c-registry-source-set-by-server`), stacked on #459
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** D-550 (the registry's routes take the person from the signed claim)

## The problem

A registry row says where its last change came from (`source`: manual, screen, case, import) and, when it came
from a run, which job (`source_job`). Both were fields of the request: a signed requester could record a
hand-made change as a screening's, under a job that does not exist or belongs to another study. The export and
the audit trail then said so. The console's form always sent `manual`; nothing held another caller to that.

## The decision

1. **The route sets the source.** A change through `POST /registry/{ruleset}` is recorded `manual`. `source` is
   not a field of the request any more; sent all the same, it is refused (422, an unknown field). The other
   sources are written by the orchestrator's own code (a promotion from a screening, a REDCap import), never
   through this route.
2. **A job named with the change must be a job of the route's study.** `source_job` stays a field: a contact
   outcome names the screening it came from. The orchestrator looks the job up; unknown, or of another study,
   is 400 "source_job is not a job of this study", and nothing is written.
3. **The console sends no source** (`registry_update_body`).

## What it does not do

- It does not check that the patient was on that job's list: a job of the study is enough to keep the trail
  honest about which run a contact followed; the list is the console's page.
- A status is still the requester's to set within the recorded transitions (the consent statuses are blocked on
  the console's form, not here).

## Reuse check

Nothing fits: two lines of the route's own handler.

## Dropped (D-311)

No sign-off step.
