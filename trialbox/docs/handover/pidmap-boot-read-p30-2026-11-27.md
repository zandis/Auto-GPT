# P30: a box's boot reads the pid map without an error in the database's log

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** P-30 of the integrator's R1+1 batch D, part H: `relation "pidmap.site_key" does not exist` twice at boot
- **Date:** 2026-11-27
- **Base:** int/r1plus1 c3ba5fc4
- **Findings:** [`pidmap-boot-read-p30-2026-11-27/findings.json`](pidmap-boot-read-p30-2026-11-27/findings.json)
  (P30-01 to P30-02)

## Files outside the card

None. Lane H's own: `deploy/check_host.sh` (the pid map's read), `tools/trialbox/doctor_image.py`
(`PIDMAP_ROW_SQL`, `pidmap_row`).

The card's own: `tests/unit/test_pidmap_boot_query_p30.py`, this page and its findings.

## Why

Schema `pidmap` is made by the adapter on its first use (`adapter.pidmap.PidMap` migrates before any read), so
before the first night it is not there. The host check reads the site's row at every boot to hand it to the doctor's
container (D-621): once in `deploy/check_host.sh` and once in the doctor's launcher (`doctor_image.pidmap_row`). Both
sent a bare `SELECT ... FROM pidmap.site_key`, which failed in the database: two `ERROR` lines in its log at each
boot. Both callers already took a failed read as "not read", so the doctor said less than it could, too.

No migration is out of order: the services that use the table migrate it first. The fix is in the query.

## Change

- One query in both readers (`doctor_image.PIDMAP_ROW_SQL`, the same text in `check_host.sh` as a quoted heredoc):
  the catalog is asked first (`to_regclass`, as the doctor's own `PIDMAP_SQL` already does), and the row is read only
  when the table is there. No table gives no row: the answer is `none` ("no night has recorded a rule in the pid map
  yet"), not "unread".
- The test runs both readers' text with the real `psql` against a database with no `pidmap` schema (exit 0, nothing
  on standard error), then after the adapter's migrations (the row comes back). It also holds the two texts equal.

## What was not verified

- A real box's boot log: the test runs the queries against the test cluster, not the box's `db` container.
