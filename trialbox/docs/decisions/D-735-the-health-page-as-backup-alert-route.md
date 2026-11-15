# D-735 On a box with no mail, the health tab may be the backup alert route

- **Task:** T-730c, part of T-730 (the box looks after itself); the R2 installer on a box with no mail
- **PR:** this branch (`agent/T-730c-the-health-page-as-alert-route`)
- **Date:** 2026-11-15
- **Status:** accepted (the owner's yes, typed in lane D's session on 2026-11-15: on boxes without mail, the backup
  alert goes to the health page; it loosens D-274)
- **Builds on:** D-274 (backups wired at install, OPS-028), D-406 (the `/admin` health tab's backup tile)

## Context

D-274 made a PRODUCTION install refuse without a backup alert route (`TB_BACKUP_ALERT_CMD`, or `TB_BACKUP_MAILTO`
with a mail transfer agent), because the one alert had gone to `root` on a box with no mail. Many hospital boxes
have no mail relay the box may use, so the install stopped there (OPS-003). The `/admin` health tab already shows
the backup tile red, and every alert is audited (`backup.alert`).

## Decision

1. `TB_BACKUP_ALERT_ROUTE=health-page` is the site's written choice that the health tab and the audit carry the
   backup alert. With it, a PRODUCTION install goes on and says that nobody is mailed; status is not red for a
   missing route.
2. It is never a default: unset, everything is as D-274 decided. Any other value is a setting error and no route.
3. It does not replace a mail route: with `TB_BACKUP_ALERT_CMD` or `TB_BACKUP_MAILTO` set, those still send.
4. `doctor` WARNs in PRODUCTION while the health tab is the only working route ("someone must open /admin every
   working day"), so the choice stays in sight on every check. "Only working": no alert command, and no
   `TB_BACKUP_MAILTO` this host can send (without a mail transfer agent cron mails nothing).
5. A box (`tools/box/plan.py`) writes `TB_BACKUP_ALERT_ROUTE=health-page` with the owner's address: with a mail agent
   the owner is mailed as before, without one the install goes on and the page carries the alert.
6. The health tile sees what the hourly `backup-status` sees: the box's health facts ask the WAL archiver too
   (`ops.health_facts`), so an archiving problem turns the tile red on a box that mails nobody.
7. A bad value is printed by `backup-install` and named where a PRODUCTION install stops.

## Adversarial review

One fresh read-only review. Fixed test-first: a box always names the owner's address, so without a mail agent the
install still stopped before the page was looked at, and `doctor` said nothing (FIX FIRST); archiving problems
reached only the hourly mail, never the tile (FIX FIRST); a bad value was not printed at install; the doctor test
did not prove the WARN; the installer's stop text and doctor's docstring named only the mail routes. Left as is: a
bad value of any backup setting stops the nightly run with a record (D-455), the tile shows it.

## Test

`tests/unit/test_backup_alert_on_the_health_page.py`: before, 10 failed (6 more after the review); after, 14 passed,
with the backup schedule, doctor, box plan and ops tests unchanged.
