# D-481 A service container holds its own database role's password and no other: the clears move into the base compose file, one check for the test and for `doctor`

- **Card:** T-712 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.2, TB-PLAN-06.1; wave T, safety core)
- **PR:** this branch (`agent/T-712-db-passwords-own-role`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-378 (one database role per service), D-394 (the audit journal's one writer), D-450 (T-212d: the
  secrets overlay clears the eight `TB_DB_PW_*`; the rendered-compose test)
- **Closes:** finding F1 and proposal TR-1 of `docs/reviews/2026-11-12-architecture/trust.md` (what D-450 left open)

## The problem

D-378 gives each service its own PostgreSQL role. Its acceptance ("a service role cannot read another service's
schema") is true of the role and was not true of the container: every TrialBox service reads `deploy/.env` through
`env_file`, and that file holds every role's password and both administrator passwords. D-450 cleared them in
`deploy/docker-compose.secrets.yml`. What it left:

1. **The clears live in an overlay.** A stack started without the overlay (the PoC, `make test-compose`, the
   platform compose form, a hand-typed `docker compose up`) gives every container every password, and the
   services that open no database (`embed-service`, `doc-parser`) the host tools' administrator URL.
2. **The test that proves it can be skipped.** `tests/unit/test_compose_secret_reach.py` needs the `docker compose`
   plugin and is skipped without it; it renders eight file sets and not the PoC, the box, the platform or the
   two-device sets.
3. **A missing role password is silent.** Each `TB_DB_URL` falls back to the workflow administrator's password when
   its `TB_DB_PW_<SERVICE>` is not in `deploy/.env`. A box in that state runs, and every service holds the password
   of `trialbox`, the one member of `audit_writer` and of every schema group.
4. **Nothing looks at a box.** `trialbox doctor` does not check what the box's compose files or its running
   containers hold.

## The decision

(filled in with the build; see the pull request)
