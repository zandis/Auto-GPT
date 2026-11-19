# D-1364 The support-session switch: every patient page closed to every role, at most 2 hours (10K-15)

- **Task:** lane K, plan 10 row 10K-15 (review 18, SO-15; owner decision 99, SO-D4: "no standing access; the
  support-session switch"). · **Date:** 2026-11-19
- **Decision:**
  - **Who:** the administrator role (the hospital's own operator, runbook 21 tier 1) starts and ends a support session
    at `/ops/support-session`, with an optional ticket number (letters, digits, `# . _ / -`, at most 40: never a name)
    and a tick that the hospital started the screen share and its person stays at the keyboard. One new matrix row,
    `support.session`, `admin: true`, every other role `false`. It is within decision 99: the hospital starts it, no
    support person gets an account or a way in, and the switch only closes pages.
  - **Where the refusal sits:** in `tb_common.authz.permit`, the one permission function. The console's middleware
    (`console.support_session`) marks each request (a context variable); while the mark is on, `permit` refuses every
    action outside `SUPPORT_SESSION_OPEN` to every role, basis `support session`. Every patient-level page and route
    asks `permit` (T-102c, D-425), and the console signs no patient read it would refuse (`console.actor.assert_for`
    asks `permit` before it mints), so a new patient route, and a new matrix row, is closed by construction.
  - **What stays open** (`SUPPORT_SESSION_OPEN`): the switch; the operations rows (`ops.*`, `job.retry_scheduled`,
    `command.STATUS`, `command.CANCEL`); the account rows; `site.setup`, `redcap.connection`, `restore.release`,
    `dataops.view`; `edc.switch_off` (a stop narrows); and the two rows that are restrictions, not rights
    (`report.aggregate_only`, `report.sponsor_form`), which keep their answer because refusing a restriction would
    widen what a viewer or CRO account sees. Every open row but the two restrictions is an administrator row, and the
    administrator has no patient-level row (D-280). An open row keeps its answer exactly: nothing is widened.
  - **What the person sees:** a 403 during a session is the console's problem page saying, in en, ja and zh-TW, that a
    support session is running and when it ends at the latest; `/api/v1` answers `{"error": "support.session_on"}`
    with the end time. The administrator's pages carry a banner with a link to end it. A break-glass grant opened
    before cannot be used, listed or opened during the session.
  - **Audit:** `console.support_session_start` (the administrator, session id, start, latest end, ticket) and
    `console.support_session_end` (`how`: `hand` with the administrator as actor, or `auto` with
    `console:support-session`, and the end time). The rows are the `support_sessions` table, schema `breakglass`
    version 3 (record R-12, no patient data).
  - **It ends by itself after 2 hours** (`SUPPORT_SESSION_MINUTES = 120`), computed at every request from the stored
    start time, never from a timer or a stored end: a restart keeps it on until then, a stopped scheduler cannot keep
    it on longer. The first request after the end closes the row at its latest end (not when seen) and writes the
    `auto` event, exactly once (an `UPDATE ... WHERE ended_at IS NULL`).
  - **Fail direction:** closed. When the state cannot be read (the trial database does not answer), the request runs
    as under a session and the page says the console cannot tell whether one is running. Before and after a session,
    and in every process that does not set the mark (the orchestrator, the tools), `permit` answers as before.
- **Not in this card:** the orchestrator does not read the switch (the console refuses before it signs, and the
  orchestrator refuses an unsigned patient read); mail (the morning list, a mailed CASE) is not a screen and is not
  stopped by the switch; the support bundle's Docker drill (runbook 21) is not part of the new drill.
- **Held by:** `tests/console/test_10k15_support_session.py` (a patient page refused during a session in three
  languages and through `/api/v1`; two audit events; the auto-end on a frozen clock; closed on doubt; only the
  administrator; the role-route walk with a session on finds no patient-level route open and nothing widened;
  `test_runbook_21_support_session`); `tests/console/test_role_route_matrix.py` (the three new routes, the
  administrator's only); `tests/unit/test_migrations.py` (breakglass version 3).
