# D-1364 The support-session switch: every patient page closed to every role, at most 2 hours (10K-15)

- **Task:** lane K, plan 10 row 10K-15 (review 18, SO-15; owner decision 99, SO-D4: "no standing access; the
  support-session switch"). · **Date:** 2026-11-19 · **Owner's yes:** 2026-11-19 20:20 UTC: "10K-15 support-session
  switch, with closing the feedback export and the one-time-code pages: yes."
- **Decision:**
  - **Who:** the administrator role (the hospital's own operator, runbook 21 tier 1) starts and ends a support session
    at `/ops/support-session` (in the administrator's menu, and one click from the Admin page's accounts tile, so that
    the plain menu of J-7, D-1251, reaches it too), with an optional ticket number and a tick. The ticket field takes the shape of a ticket
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
    widen what a viewer or CRO account sees. Who holds each open row (the matrix; an open row keeps its answer
    exactly, so nothing is widened): the administrator alone holds `support.session`, `ops.*`,
    `job.retry_scheduled`, `account.reset`, `account.disable`, `account.enable`, every `account.create.*` and
    `redcap.connection`; the administrator and the coordinator `site.setup` and `command.CANCEL`; the administrator,
    the coordinator and the investigator `command.STATUS`; the administrator and the steward `account.confirm`,
    `dataops.view` and `restore.release`; the administrator and the study's PI (`investigator: [pi]`)
    `edc.switch_off`; the viewer and the CRO account `report.aggregate_only`; the CRO account `report.sponsor_form`.
    None is a patient-level row, and the administrator has none (D-280).
  - **Open without a matrix row:** routes that ask `is_admin` (or nothing but a session) and no `permit` row are not
    closed by the switch. The walk with a session on finds them; the reviewed list of the routes of the router table
    that the switch does not refuse in the walk's box, and to which columns of the walk, is `OPEN_DURING_A_SESSION` in
    `tests/console/test_10k15_support_session.py` (113 routes on 2026-11-19). "Not refused" is any answer but the
    switch's refusal (every 403 during a session is that refusal) or a sign-in answer: 86 routes answer there (Y), 27
    answer 404 or 503 in the walk's box (a feature off, an unknown id, no setup service or study store), each pinned
    with a one-line reason. A route that the switch stops refusing, or that answers one more column, fails
    `test_the_matrix_walk_finds_no_patient_route_open_during_a_session` until it is added there after a review. A
    route's answer on a box with the feature on is what the list's reason says, not what the walk saw. Among them,
    pages guarded by `is_admin` (or a helper of the administrator) rather than a `permit` row, open to the
    administrator during a session: `/metrics`, `/admin`, `/admin/accounts`, `/admin/redcap`, `/admin/notice`,
    `/data/instruments`, `POST /ops/notices`, `POST /ops/ingest`, `/admin/models/canary`, and `POST /site/remote`
    (remote help on or off, `is_admin`, then `ops.network`; in the walk's box it answers 503: the CSRF check passes,
    then the missing setup service fails); none shows a patient row. The 404 and 503 routes of the list:
    `GET /data-ops/batches/{bid}`, `GET /api/v1/data/batches/{bid}`, `GET /admin/ops/network/{name}`,
    `GET /site/templates/{name}.xlsx`, `GET /api/v1/site/codes`, `GET /api/v1/site/checks`, `POST /site/codes`,
    `POST /site/checks/{cid}`, `POST /site/remote`, `GET /api/v1/studies/{rs}/forms`,
    `GET /api/v1/studies/{rs}/sources`, `POST /studies/{rs}/edc/switch`, `GET /pilot/jobs/{job_id}/files/{filename}`,
    `GET /pilot/jobs/{job_id}/view/{filename}`, `GET /pilot/cascade/{run_id}` and its files, `POST /admin/ops/{action}`,
    `POST /studies/{rs}/sae/{record}/{event}/{what}` (404 for an unknown step, before the record's scope, which is
    closed), `/demo/ack`, the console's own OIDC sign-in (`/auth/oidc/start`, `/auth/oidc/callback`), and the EDC
    door's routes below.
  - **What is reachable during a session, exactly** (the role-route walk with a session on, every route of the
    router table, `test_the_matrix_walk_finds_no_patient_route_open_during_a_session`; the review's leak walk found no
    patient marker in any 2xx answer): (1) aggregate pages and files with counts only: the feasibility report,
    `/reports`, the sponsor form, a SCREEN or FEAS job's page (its counts, no row) and a FEAS job's aggregate files;
    (2) the session's own page `/ops/support-session` (start, end); (3) signing in, the first sign-in `/enrol`, the
    TOTP step, `/account` and its password change, and signing out (`/logout`); (4) the administrator's operations,
    accounts, identity and site-setup pages (`/admin…`, `/ops/…`, `/site…`, `/data-ops`, `/metrics`), without the
    answers that show a secret (below); (5) pages that hold no patient row: home, Help, About, the notice settings,
    the feedback form, `/jobs` (see the known limits), a study's team, IRB, forms and sources pages (staff and study
    documents), and the week, registry and mailbox pages, whose patient rows ask closed rows and are not shown.
  - **Closed besides the matrix rows** (checks that only narrow, each refused like a closed page: 403, the support
    page, a `console.denied` event; no row of their own): the feedback file `/feedback/export.csv` (the paths of the
    pages an entry was given on, a patient page's pseudonym among them, and free text); and every answer that shows a
    sign-in secret once: `POST /ops/users` `add` and `reset` (a one-time password, or a protected account's enrolment
    code and one-time link), `POST /ops/identity` `enrol_code` and `reset_totp` (an enrolment code), `POST
    /ops/accounts/requests` `confirm` of a `create`, `password` or `totp` request (a code, a link or a password; the
    request stays pending, to be confirmed after the session). `GET /ops/users` does not show a one-time password kept
    from before the start (it stays kept for its 10 minutes). Unlocking an account, disabling it, a scope change, a
    refusal of a request, signing in and the first sign-in stay open: nobody is locked out by the switch. The EDC
    door (the review of the EDC door): `POST /api/edc/tools` and `POST /api/edc/tools/{id}/confirm` (a tool call,
    `find_patient`, `draft_form`, `quality_check` and the rest, answers about one EDC record; a held write stays
    held, to be confirmed after the session), refused before their CSRF and body are read; and
    `GET /api/edc/oidc/authorize` (the EDC's sign-in, for any signed-in role, when `TB_EDC_OIDC=1`): no sign-in code
    is issued during a session; and `POST /api/edc/oidc/token` (the EDC's server redeems a code): a code issued up to
    120 s before the start is not redeemed during the session (refused after the client check, before the code is
    read; JSON `{"error": "support.session_on"}`, a `console.denied` event with actor `edc`), so no EDC sign-in
    completes during it. `/admin/edc` and `/api/edc/map` (the connection and the study map, no record) stay open.
    So do the EDC door's `GET /api/edc/oidc/userinfo` (a token's subject only; no token is issued during a session),
    `GET /api/edc/health`, `GET /api/edc/oidc/.well-known/openid-configuration` (the issuer's public metadata) and
    `POST /api/edc/events/v1` (the EDC's signed event feed, no console session): none shows a record.
  - **Aggregate pages stay open.** Report pages that show counts only (the feasibility report, the reports list, the
    sponsor form) stay open to the roles that have them: they ask no closed row, and the two rows they do ask are the
    restrictions above, which keep their answer so that a viewer or a CRO account is not shown more. A SCREEN or FEAS
    job page stays open with its counts; its patient rows are behind `phi.view`, closed.
  - **A page about one patient is a patient page.** The pages of a CASE job (one patient's sheet, its counts by
    criterion, the chart number masked) are refused during a session to every role, by the switch's middleware
    (`ONE_PATIENT_JOBS`); a job that cannot be read is refused (closed on doubt). This narrows only.
  - **What the person sees:** a 403 during a session is the console's problem page saying, in en, ja and zh-TW, that a
    support session is running and when it ends at the latest; `/api/v1` answers `{"error": "support.session_on"}`
    with the end time; the EDC's sign-in and a tool confirmation posted from the form of `/admin/edc` are opened by
    a browser, so their refusal is the page. The page is rendered as if at `/`: the refused URL (a study, a pseudonym, a job id) is not
    repeated in a link, a form's way back or the feedback control; nothing is read for it. The administrator's pages
    carry a banner with a link to end it. A break-glass grant opened before cannot be used, listed or opened.
  - **Audit:** `console.support_session_start` (the administrator, session id, start, latest end, ticket) and
    `console.support_session_end` (`how`: `hand` with the administrator as actor, or `auto` with
    `console:support-session`, and the end time). The rows are the `support_sessions` table, schema `breakglass`
    version 3 (record R-12, no patient data). **A session is never on without its start event:** the event is written
    before the insert commits, and a failed write rolls the row back (the page says nothing changed). The audit trail
    is its own store, not that database transaction: if the commit itself fails after the event was written, the trail
    holds a start event with no session (the safe direction: never a session without its event). An end by
    hand is the same: a failed event leaves the session on (closed) and the end can be tried again. **An automatic
    end is never lost:** the row is ended first (so the pages open on time), with `end_audited` false; the event is
    written at the next requests, inside a transaction that sets `end_audited` (`FOR UPDATE SKIP LOCKED`: one writer),
    until it is written. A commit lost after the event was written can repeat an event; it cannot lose one.
  - **It ends by itself after 2 hours** (`SUPPORT_SESSION_MINUTES = 120`), computed at every request from the stored
    start time, never from a timer or a stored end: a restart keeps it on until then, a stopped scheduler cannot keep
    it on longer. The first request after the end closes the row at its latest end (not when seen). **A start later
    than the request's time** (the clock was moved back) is set to the request's time, so the session lasts at most
    2 hours from the first request that sees it, not until the clock reaches the stored start; the move is the audit
    event `console.support_session_moved` (the start it had, the start it has, the new latest end), written in the
    update's transaction (`FOR UPDATE SKIP LOCKED`: one process moves it once); a failed event leaves the start
    unmoved and the request answers as on doubt (closed). As with an automatic end, a commit lost after the event was
    written repeats it: the next request moves the start again and writes a second event (with its own new start);
    it cannot lose one. Removing the repeat would need the audit trail and the database in one transaction, or an
    event id the trail refuses twice; neither is a small change, so it is a known limit. **A start that cannot
    be read** (a damaged row) keeps the session on (closed on doubt) until the administrator ends it: the page lists
    every row not ended, and the end reads no stored time.
  - **Fail direction:** closed. When the state cannot be read (the trial database does not answer), the request runs
    as under a session and the page says the console cannot tell whether one is running. Before and after a session,
    and in every process that does not set the mark (the orchestrator, the tools), `permit` answers as before.
- **Not in this card, said plainly:** the switch marks console requests only. Code outside a request is not marked
  and not stopped: the morning-mail timer and its notices, the nightly REDCap read (`rc_read`), the orchestrator's
  own jobs and its mail (a mailed CASE). The orchestrator does not read the switch; it refuses a patient read the
  console did not sign, and the console signs none during a session. A terminal on the box (runbook 21 rule 3) is
  outside the switch: what it shows is the hospital person's care. The support bundle's Docker drill (runbook 21) is
  not part of the new drill. `python -m console.cli` (on the box's terminal) can still issue an enrolment code.
- **Known limits:**
  - A `support_sessions` row deleted by hand (in the database) ends the session with no end event: the trail holds a
    start with no end. The console cannot write an event for a row it no longer sees; the steward's review of the
    trail is where it shows.
  - A clock moved forward ends a session early (the pages open while support may still watch); one moved back is
    re-anchored and audited (above). Both are the clock's, not the switch's.
  - `/jobs` and the administrator's home list a CASE job's row (its id, type, ruleset, requester and time) during a
    session. It is not patient-level: the id is a random job id the box makes, and it holds no pseudonym, chart
    number or clinical fact; every route of that job is refused during a session with no job id in the body.
  - A data-ops batch step shows a steward's free-text reason, which could name a patient if a steward wrote one.
  - The person's own sign-in steps (`/enrol`, the TOTP step's new authenticator) stay open: closing them would lock
    a person out; the hospital's person signs in with the screen share paused.
  - Windows rendered before the start stay on screen; reload and back are covered by `Cache-Control: no-store`.
- **Held by:** `tests/console/test_10k15_support_session.py` (a patient page refused during a session in three
  languages and through `/api/v1`; two audit events; the auto-end on a frozen clock; closed on doubt; only the
  administrator; a failing audit append at the start, at an end by hand and at an automatic end; a damaged and a
  future start; a CASE job page refused; the role-route walk with a session on finds no patient-level route open and nothing widened;
  `test_runbook_21_support_session`; the feedback file, a new account or reset password, an enrolment code and a
  confirmation that shows a secret, each shown with the session off and refused with it on, the refusal audited;
  sign-out, sign-in and the end still work; an EDC tool call, its confirmation and the EDC's sign-in refused during
  a session in three languages, the refusal audited, a held write confirmed after the end; a sign-in code issued
  before the start not redeemed during it and redeemed after the end; the list of routes the switch
  does not refuse pinned; a PI lists no grant of its study (`breakglass.study`); a moved start is
  one audit event; a FEAS job's file of counts stays open); `tests/console/test_role_route_matrix.py` (the three new routes, the
  administrator's only); `tests/unit/test_migrations.py` (breakglass version 3).
