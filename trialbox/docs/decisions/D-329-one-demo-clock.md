# D-329 One demo clock: the demo day is the real day in the site's time zone

- **Task:** T-513 (TB-PLAN-06 §6.2.3, wave P)
- **PR:** this branch (`agent/T-513-demo-clock`)
- **Date:** 2026-11-10
- **Status:** proposed
- **Closes:** UX-003, UX-020 (the time part); builds on D-270 (PR #86, CR-049, CR-050) and D-315

## Context

The demo had three clocks (UX-003). The synthetic hospital is made for 2026-11-01, so the box's day and the
console's clock were frozen at 2026-11-02 07:00, while the jobs carried the real time. The frozen clock was 07:00
at UTC+9 on every site, which is 06:00 in Taipei. A clinician on 2026-11-10 saw a week page "SCREEN run of
2026-11-10" next to a not-matched page "run of 2026-11-02", visits of 11-04 under "next 2 weeks", and a participant
visit "done 2026-11-09" that EDC refused as a date in the future. The morning digest list showed the stored UTC time
(UX-020).

## Decision

1. **The demo day.** `tools.demo --day` (or `TB_DEMO_DAY`) is `today` by default. The demo day is then the real
   day in the site's zone (`site.tz`, D-315). On a Saturday or Sunday it is the Friday before, because the
   coordinator's digest goes out on working days only and the seed plays the morning mail. `--day data` keeps the
   synthetic data's own day (2026-11-02) with a frozen clock; the tests, drills and the complete run use it, so
   their results do not change with the calendar. `--day YYYY-MM-DD` plays that day.
2. **The data moves, the generator does not.** The synthetic hospital is still made for 2026-11-01. Before the
   ingest, every date and date-time cell of its landing tables moves by the same number of days, so the data is as
   of the day before the demo day (`feas_demo.shift_dates`; the folder records the shift). Intervals between dates
   are kept. Note text is not rewritten.
3. **One clock.** The box's day is the demo day. When the demo day is today, the console's clock is the real clock
   from the start of the seed, as the jobs' times are. On a weekend seed the clock stands at 07:00 site time on the
   Friday. After the seed, the console's clock and the box's day follow the real time in the site's zone, also after
   a `--keep` restart (`demo-state.json` records `live`). The seed clock's 07:00 is in the site's zone, not UTC+9.
4. **Run dates.** The week list, the cohort list and the reports page show the run's date (`job.run_date`, the site's
   day), as the not-matched page does, not the UTC date of the job's last update.
5. **Digest list.** `/notices/received` shows the send time in the site's zone.

## Consequences

* A clinician sees today's date on the lists, marks and mail of the seed, and no run, mark, mail or log row dated
  after today. Future dates on a page are booked clinic visits, due dates and re-check dates.
* The funnel counts on month ends. With the data moved to a day that is not a month end, a patient seen only after
  the last month end joins the population next month. The e2e recount now counts the visits in the window the funnel
  uses, so it holds on any day.
* A patient whose birthday falls within a day of the demo day can read one year older or younger than on the data's
  own day where the move crosses 29 February. This is synthetic data; the checks on the data's own day are unchanged.
