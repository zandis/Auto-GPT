# D-974 the public run finds its patients on any page of the list

- **Task:** lane D, the owner of the nightly; the integrator's request on #639 (2026-11-16) to trace the nightly's reds
- **PR:** this branch (`agent/NIGHTLY-RED-2-the-public-run-finds-its-patients-on-any-page`)
- **Date:** 2026-11-16
- **Status:** accepted
- **Builds on:** D-914 (a record that is not there never excludes)

## Context

The nightly's `public-e2e` job (`python -m tools.public_e2e`) ended 1 on 2026-11-16 with 129 of 130 checks passed. The
one red was stage 3's "PI list page", although the page answered 200. The check took the first three rows of the
week's mail list and looked for their short ids on `/studies/<trial>/week?list=all`. That page shows 25 rows at a time
(`console.studies.PAGE_SIZE`), ordered by how many criteria are still open, and the mail list is in another order.

A bisect over the trains between the last green night (`b811f3e1`, train 31) and the red one (`6c338548`, train 57),
running `tools.public_e2e` locally at each train, names train 42 (`25658c7c`) as the first red. Train 42 carried
D-914: a patient with no record of a kind is no longer excluded by it. The public site's list grew to 215 patients,
all in review, and two of the three picked patients were on later pages. The page and the product were right; the
check assumed one page.

## Decision

`tools.public_e2e.find_on_list` reads the list page by page, following the page's own next-page link
(`data-testid="next-page"`), until it has seen each picked patient's row (`data-testid="row-<short>"`). The check fails
on a page that is not 200, or when a patient is on no page, and then names the patients it did not find. It now looks
for the patient's row, not the eight characters anywhere on the page, so it asks more of the page than before.

## Test

`tests/unit/test_public_e2e_list_pages.py`: patients on later pages are found; reading stops once all are seen; a
patient on no page is named; the short id outside a row does not count; a status other than 200 stops it. A local
`python -m tools.public_e2e --lang en` on master passes the check.
