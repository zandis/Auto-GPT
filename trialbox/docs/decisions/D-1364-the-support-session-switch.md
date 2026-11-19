# D-1364 The support-session switch: every patient page closed to every role, at most 2 hours (10K-15)

- **Task:** lane K, plan 10 row 10K-15 (review 18, SO-15; owner decision 99, SO-D4: "no standing access; the
  support-session switch"). · **Date:** 2026-11-19
- **Decision:**
  - **Who:** the administrator role (the hospital's own operator, runbook 21 tier 1) starts and ends a support session
    at `/ops/support-session`, with an optional ticket number and a tick. The ticket field takes the shape of a ticket
    number only: an optional prefix of up to 6 letters (or `#`), then digits in up to four groups (`TB-2026-0117`,
    `#4711`); letters alone (`TaroYamada`) are refused. A pattern cannot prove that no name is typed (`Taro-1` has the
    shape); the page asks for none, and the person's name stays in the ticket, never in the box. The tick says that
    the hospital started the screen share and its person stays at the keyboard. One new matrix row,
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
  - **Aggregate pages stay open.** Report pages that show counts only (the feasibility report, the reports list, the
    sponsor form) stay open to the roles that have them: they ask no closed row, and the two rows they do ask are the
    restrictions above, which keep their answer so that a viewer or a CRO account is not shown more. A SCREEN or FEAS
    job page stays open with its counts; its patient rows are behind `phi.view`, closed.
  - **A page about one patient is a patient page.** The pages of a CASE job (one patient's sheet, its counts by
    criterion, the chart number masked) are refused during a session to every role, by the switch's middleware
    (`ONE_PATIENT_JOBS`); a job that cannot be read is refused (closed on doubt). This narrows only.
  - **What the person sees:** a 403 during a session is the console's problem page saying, in en, ja and zh-TW, that a
    support session is running and when it ends at the latest; `/api/v1` answers `{"error": "support.session_on"}`
    with the end time. The page is rendered as if at `/`: the refused URL (a study, a pseudonym, a job id) is not
    repeated in a link, a form's way back or the feedback control; nothing is read for it. The administrator's pages
    carry a banner with a link to end it. A break-glass grant opened before cannot be used, listed or opened.
  - **Audit:** `console.support_session_start` (the administrator, session id, start, latest end, ticket) and
    `console.support_session_end` (`how`: `hand` with the administrator as actor, or `auto` with
    `console:support-session`, and the end time). The rows are the `support_sessions` table, schema `breakglass`
    version 3 (record R-12, no patient data). **A session is never on without its start event:** the event is written
    inside the insert's transaction, and a failed write rolls the row back (the page says nothing changed). An end by
    hand is the same: a failed event leaves the session on (closed) and the end can be tried again. **An automatic
    end is never lost:** the row is ended first (so the pages open on time), with `end_audited` false; the event is
    written at the next requests, inside a transaction that sets `end_audited` (`FOR UPDATE SKIP LOCKED`: one writer),
    until it is written. A commit lost after the event was written can repeat an event; it cannot lose one.
  - **It ends by itself after 2 hours** (`SUPPORT_SESSION_MINUTES = 120`), computed at every request from the stored
    start time, never from a timer or a stored end: a restart keeps it on until then, a stopped scheduler cannot keep
    it on longer. The first request after the end closes the row at its latest end (not when seen). **A start later
    than the request's time** (the clock was moved back) is set to the request's time, so the session lasts at most
    2 hours from the first request that sees it, not until the clock reaches the stored start. **A start that cannot
    be read** (a damaged row) keeps the session on (closed on doubt) until the administrator ends it: the page lists
    every row not ended, and the end reads no stored time.
  - **Fail direction:** closed. When the state cannot be read (the trial database does not answer), the request runs
    as under a session and the page says the console cannot tell whether one is running. Before and after a session,
    and in every process that does not set the mark (the orchestrator, the tools), `permit` answers as before.
- **Not in this card, said plainly:** the switch marks console requests only. Code outside a request is not marked
  and not stopped: the morning-mail timer and its notices, the nightly REDCap read (`rc_read`), the orchestrator's
  own jobs and its mail (a mailed CASE). The orchestrator does not read the switch; it refuses a patient read the
  console did not sign, and the console signs none during a session. A terminal on the box (runbook 21 rule 3) is
  outside the switch: what it shows is the hospital person's care. `/feedback/export.csv` (the administrator's
  free-text feedback file, comments scanned by `tools.data_scan`, guarded by the operator check, not a matrix row)
  stays open: closing it needs a row of its own, and this card adds no row but the switch (left to the owner). The
  support bundle's Docker drill (runbook 21) is not part of the new drill.
- **Held by:** `tests/console/test_10k15_support_session.py` (a patient page refused during a session in three
  languages and through `/api/v1`; two audit events; the auto-end on a frozen clock; closed on doubt; only the
  administrator; a failing audit append at the start, at an end by hand and at an automatic end; a damaged and a
  future start; a CASE job page refused; the role-route walk with a session on finds no patient-level route open and nothing widened;
  `test_runbook_21_support_session`); `tests/console/test_role_route_matrix.py` (the three new routes, the
  administrator's only); `tests/unit/test_migrations.py` (breakglass version 3).
