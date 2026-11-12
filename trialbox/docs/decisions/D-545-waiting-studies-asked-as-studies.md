# D-545 The studies waiting for approval are asked as studies, not cut from a listing of jobs

- **Task:** NEW-JRN-1b (the integrator's follow-up to NEW-JRN-1, #380, before go-live; OD-10, T-700's rule)
- **PR:** this branch (`agent/NEW-JRN-1b-waiting-studies-no-cut`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-540 (a study that waits for its first approval opens its delegation log), D-464 (callers per
  route)

## The problem

D-540 found the studies that wait for their first approval by reading up to 500 jobs in `awaiting_approval` and
taking their studies. A study whose one waiting job stands behind 500 newer waiting jobs was not found: its
delegation log did not open, so no PI could be named and the criteria could not be approved. The limits lint
named the fixed 500; the allow-list line said plainly that it was a cut.

## The decision

1. **The job store answers the question.** `JobDB.waiting_rulesets()`: the distinct studies with a job in
   `awaiting_approval`, the one with the newest such job first. One row per study, no limit.
2. **One route.** `GET /jobs/waiting-studies` returns that list (study ids, no job). It is in the route group
   `jobs_list` of `route_callers.yaml`: the callers of `GET /jobs` (the console, the operator's token) and no
   other. It changes nothing, so it has no stage in `route_actors.yaml`.
3. **The console asks it.** `Backend.waiting_studies()`; `console.studies.waiting_studies` reads no listing of
   jobs. The allow-list line for `console/studies.py` is gone.

## What it does not do

- The other `list_jobs(limit=500)` calls of the console (`home.py`, `screening_log.py`) stay on the allow-list
  with their reasons; they are T-700's.
- The list is as long as the number of studies that wait, which is bounded by the number of studies.

## What the adversarial review changed

One review by a fresh reviewer. Verdict: merge; no HIGH or MED. From its LOW points: a study id of blanks names
no study (the query and the console's reader); the route test also asserts the operator's token reads it; D-540
points here. Not changed: the order rests on the stored text timestamps, as `GET /jobs` does (display only); the
console's test stand-in returns the studies in the order they were added.

## Reuse check

Nothing fits: one SQL query on the box's own job table.

## Dropped (D-311)

No sign-off step.
