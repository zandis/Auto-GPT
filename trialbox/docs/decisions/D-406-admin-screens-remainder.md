# D-406 Admin screens remainder: backup and update tiles, identity links, third-party logs, unused accounts

- **Task:** T-209c, admin screens remainder after PR #66 part c (`docs/plan/28-master-plan-v6.md` §6.2)
- **PR:** this branch (`agent/T-209c-admin-screens`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** ROLE-021, ROLE-022 (`docs/reviews/2026-11-10-deep-review/02b-role-journeys-authz.md`), OPS-035,
  OPS-059 (`docs/reviews/2026-11-10-deep-review/09-operations.md`)
- **Builds on:** D-178 (the operations screens), D-379 (T-209a: box health), D-192 (`/ops/identity`), D-207
  (`/ops/flags`), D-138 (log retention)

## Context

`/ops/identity` and `/ops/flags` had no link anywhere: an administrator who did not know the address could not
unlock a colleague (ROLE-021). The `/admin` health tab had no backup or update tile and said they would come later
(ROLE-022). The log collector put PostgreSQL and HAPI logs, which are not scrubbed, beside TrialBox's own and kept
them 365 days (OPS-035). Nothing listed accounts that were no longer used, and a local account needed no end date
(OPS-059).

## Decision

1. **Tiles.** The `/admin` health tab gets a Backups tile (age and level of the newest backup, the last key check
   from T-209a's `backup_verified`, the last check run from the console) and an Update tile (last bundle and how it
   ended, bundles waiting, rollback points). Each links to its tab of `/admin/ops`.
2. **Links.** The Accounts tile names the locked accounts and links to `/ops/users`, `/ops/identity`,
   `/admin/accounts` and `/ops/flags`. Each row of `/ops/users` links to its row of `/ops/identity`. Unlock is two
   clicks from `/admin`: the link, then the row's Unlock button.
3. **Unused-account report** on `/admin/accounts` (administrators only): accounts with no session for 60 days (or
   never, counted from creation), end dates within 14 days or passed, and local accounts with no end date. The last
   sign-in is a new column `users.last_login` (auth migration 4), written when a session opens. The administrators'
   health mail carries the same list on Mondays: user names, roles and dates, no patient data. No new mail kind.
4. **End dates.** A local account other than an administrator always has an end date at most 365 days ahead; an
   empty one on the Accounts page is set to that limit, a later one is refused. An administrator's end date is
   optional (the box must keep one administrator) but has the same limit. Identity-provider accounts follow the
   directory. The limits are constants, not settings.
5. **Third-party logs.** `trialbox logs collect` puts the logs of `db`, `fhir-store`, `llm-service`, `authelia`,
   `caddy` and `prometheus` under `TB_LOG_DIR/third-party/<day>/` (0600, folder 0700) with a `CLASS` file marking
   them D3: never forwarded, never in a support bundle, kept `retention.third_party_logs_days` (default 30) days.
   PostgreSQL runs with `log_min_error_statement=panic` and `log_parameter_max_length_on_error=0`, so a failed
   statement's text and values are not logged.
   The third-party tree has its own `COVERAGE.json` (D-389), and `gaps` reads both trees. `trialbox support-bundle`
   (D-405) refuses an `--add` path under `logs/third-party/`.

## Consequences

- A locked colleague is found and unlocked from `/admin` without knowing any address.
- A leaver's local account ends within twelve months at the latest and shows on the Monday list after 60 idle days.
- An account that existed before this change shows "never signed in" until its next sign-in.
- Dropped (D-311): no named reviewer or sign-off for the limits.
