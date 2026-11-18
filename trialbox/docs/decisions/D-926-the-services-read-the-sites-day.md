# D-926 The services read the site's day, not the server's

- **Task:** 9l-7 (AQ-7 of plan 9 revision 2; plan 10 lists it as waiting for nothing), lane B2 · **PR:** `agent/9l-7-server-dates-read-the-site-day` · **Date:** 2026-11-18 · **Status:** accepted · **Builds on:** D-270, D-315

1. The eight `date.today()` calls of the services read the server's calendar day. A box whose clock keeps UTC and that serves a site in Tokyo was a day behind from 15:00 UTC.
2. They now read the site's day:
   - `tb_common.timeutil.today()`, the site's zone (`TB_TZ`), for an OMOP batch with no date of its own, the CDM source's release day, the data-quality check's day, a mapping's latest plausible year, and a code's "validity ended" in the terminology mapper;
   - the mapping's own zone for "nobody lives that long" (`Mapper._older_than_a_life`).
3. A batch's own day (`site@2026-10-31`) still wins over the clock, as before.
4. A ratchet test keeps `date.today()` and `datetime.today()` out of `services/` and `libs/`. Card 9l-8 (lane J) widens it to every clock read.
5. Tests: `tests/unit/test_9l7_server_dates_read_the_site_day.py`, with the clock fixed at 23:30 UTC on 2026-11-17 and the site in Tokyo: the site's day is 2026-11-18 for each.
