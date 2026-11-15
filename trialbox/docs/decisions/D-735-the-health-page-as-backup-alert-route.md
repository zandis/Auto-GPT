# D-735 On a box with no mail, the health tab may be the backup alert route

- **Task:** T-730c, part of T-730 (the box looks after itself); the R2 installer on a box with no mail
- **PR:** this branch (`agent/T-730c-the-health-page-as-alert-route`)
- **Date:** 2026-11-15
- **Status:** proposed (applied only on the owner's yes typed in lane D's session: it loosens D-274)
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
4. `doctor` WARNs in PRODUCTION while the health tab is the only route ("someone must open /admin every working
   day"), so the choice stays in sight on every check.

## Test

`tests/unit/test_backup_alert_on_the_health_page.py`: before, 10 failed; after, 10 passed, with the backup schedule,
doctor and config tests unchanged.
