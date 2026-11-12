# D-584 The demo seeds on the Tuesday before the last Wednesday, so no date it shows is after the demo day

- **Task:** DEMO-JA (the demo as a Japanese viewer sees it; rehearsal of 2026-11-12)
- **PR:** this branch (`agent/DEMO-JA-demo-ja-polish`)
- **Date:** 2026-11-12
- **Status:** proposed (merges with its PR)
- **Changes:** D-329 (T-513, one demo clock): the day the seed plays

## Context

D-329 seeds the demo on the real day (on a weekend the Friday before) and then lets the console follow the real
clock. The seed ends with the screening cadence of T-624 (D-397, e2e stage 17): a patient first appears in the data
of the Tuesday after the seed day and is listed on that Wednesday morning. Seeded on Friday 2026-11-13, the demo
therefore showed "data as of 2026-11-17" and "the MICROBATCH of 2026-11-18" on the week list and every patient page,
four and five days after "today", while feasibility said 2026-11-11.

## Decision

1. With `TB_DEMO_DAY=today` the seed plays on **the Tuesday before the last Wednesday on or before the demo day**
   (`tools.list_demo.seed_day`). The cadence stage's Tuesday data and Wednesday run then fall on or before the demo
   day, and the console follows the real clock from the end of the seed as before. A Tuesday is a working day, so the
   coordinator's morning digest still goes out (the reason for the weekend rule of D-329).
2. The data the demo shows is then 1 to 7 days old (a Wednesday showing: yesterday's data; a Tuesday showing: last
   Tuesday's). Booked visits after today stay (they are appointments, not records).
3. `e2e_simple` stage 17 checks, in a demo on the real day, that its night is not after today. A fixed
   `TB_DEMO_DAY=YYYY-MM-DD` and the data's own day are unchanged (the tests, drills and complete runs).

## Consequences

`tests/unit/test_demo_clock.py` holds the new seed days and checks for every day of two weeks that the seed and the
cadence night are on or before the demo day.
