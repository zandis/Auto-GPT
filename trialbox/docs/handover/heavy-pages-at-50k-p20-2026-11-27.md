# P20: the heavy pages at 50,000 candidates

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** P-20 (the integrator's R1+1 batch D, part H, comment 7210967559 on #1504): the study week list 5.2 s,
  the candidates page and API about 3 s, the coordinator's home up to 4.4 s at 15k to 47k candidates
- **Date:** 2026-11-27
- **Base:** int/r1plus1
- **Findings:** [`heavy-pages-at-50k-p20-2026-11-27/findings.json`](heavy-pages-at-50k-p20-2026-11-27/findings.json)
  (P20-01, P20-02)

## What was there

The week list and the candidates page already showed one page of 25 rows, but each view built every row of the run's
list first. Measured with a profiler at 50k synthetic candidates, a view spent its time in:

- the cyclic garbage collector: building 33k rows makes about 300k objects, and each batch of new objects started a
  full collection over everything the process holds, the parsed list included (0.8 s of 1.0 s for the rows alone);
- the week list's first appearances, written again for every listed pseudonym at every view (`SiteStore.seen`);
- the week page reading the whole list twice (once for the list, once more for the patient panel), and the candidates
  page twice (the week list's rows, then its own);
- the same state worked out again for every person nobody had recorded anything about, and the same to-do words
  for every row.

## Change

- `services/console/studies.py`: `no_cycle_collection()` and `@heavy_page`: a page that reads a whole candidate
  list runs with the cyclic collector paused, counted under a lock so that nested and parallel pages put it back as
  they found it (on after the last one, off if it was off). The rows hold no cycles; reference counting frees them when
  the page is answered. `weekly_rows` works out the to-do words once per list.
- `services/console/home.py`: `/home` and `/studies/{rs}/week` are heavy pages; the list's JSON is parsed under the
  pause; the week page hands its list to the patient panel; `week_bundle(..., rows=False)` gives a page the list
  without the week list's rows.
- `services/console/team.py`: the candidates page and `GET /api/v1/studies/{rs}/candidates` are heavy pages and read
  the list once. The API takes `page` (from 1) and `size` (default 100, at most 1000) and then answers one page with
  `total`, `page`, `pages` and `size`; without `page` it answers every row, as before.
- `services/console/sitestore.py`: `seen` writes only the pseudonyms not yet recorded.
- `services/console/person_state.py`: a person with no recorded fact gets the one blank state, worked out once.
- `tests/console/test_heavy_pages_at_50k_p20.py`: five heavy views and the paged API at 50,000 synthetic candidates,
  each under a p95 of 2.5 s over 7 requests after a first view; the paged API's rows, totals and clamping; `seen`
  writes nothing for a list read again; the collector is back as it was after nested, failed and overlapping pages.

## The bound and where it was measured

Measured in a 4-core cloud container with 15 GB of memory, Python 3.12, one process, no coverage, 50,000 synthetic
candidates (33,334 listed), seconds per request after a first view, 5 requests each:

| Page | Base | Head |
| --- | --- | --- |
| `/studies/GZQO/week` | 4.45 to 6.04 | 0.73 to 0.81 |
| `/studies/GZQO/week?list=all&page=700` | 5.64 to 6.49 | 0.74 to 0.81 |
| `/studies/GZQO/candidates` | 3.62 to 4.01 | 0.53 to 0.61 |
| `/studies/GZQO/candidates?page=900` | 3.35 to 3.83 | 0.47 to 0.60 |
| `/home` | 2.22 to 3.51 | 0.66 to 0.74 |

The bound, 2.5 s at the 95th percentile, is about three times the head's slowest request, so that CI's parallel
workers and coverage do not make it fail by chance. The base fails it on every page (p95 3.29 s to 5.92 s, the test
run on the base). Under CI's conditions (coverage, `-n auto`, with the role and team pages beside it) the test passed
twice.

## Not done

- A view still reads the whole list and builds every listed row, because the counts and the order of the lists need
  all of them; the time grows with the list (about 0.8 s at 50k here). A cache per run would remove that: P20-01.
- The p95 bound is checked in CI's container, not on a box: P20-02.
