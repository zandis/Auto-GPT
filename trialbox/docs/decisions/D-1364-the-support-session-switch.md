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
    `command.STATUS`); the account rows; `site.setup`, `redcap.connection`, `restore.release`,
    `dataops.view`; `edc.switch_off` (a stop narrows); and the two rows that are restrictions, not rights
    (`report.aggregate_only`, `report.sponsor_form`), which keep their answer because refusing a restriction would
    widen what a viewer or CRO account sees. Who holds each open row (the matrix; an open row keeps its answer
    exactly, so nothing is widened): the administrator alone holds `support.session`, `ops.*`,
    `job.retry_scheduled`, `account.reset`, `account.disable`, `account.enable`, every `account.create.*` and
    `redcap.connection`; the administrator and the coordinator `site.setup`; the administrator,
    the coordinator and the investigator `command.STATUS`; the administrator and the steward `account.confirm`,
    `dataops.view` and `restore.release`; the administrator and the study's PI (`investigator: [pi]`)
    `edc.switch_off`; the viewer and the CRO account `report.aggregate_only`; the CRO account `report.sponsor_form`.
    None is a patient-level row, and the administrator has none (D-280).
  - **Open without a matrix row:** routes that ask `is_admin` (or nothing but a session) and no `permit` row are not
    closed by the switch. The walk with a session on finds them; the reviewed list of the routes of the router table
    that the switch does not refuse in the walk's box, and to which columns of the walk, is `OPEN_DURING_A_SESSION` in
    `tests/console/test_10k15_support_session.py` (113 routes on 2026-11-19; 109 since the review of aeb978e6, below). "Not refused" is any answer but the
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
  - **A job's pages and files are closed by default** (the review of aeb978e6, H2 and H3; it replaces the CASE-only
    close). During a session the switch's middleware refuses every page and file of a job whose type is not in
    `JOBS_OPEN_DURING_A_SESSION` (FEAS: counts per criterion and step; SCREEN: the run's counts, its rows ask
    `phi.view` and its candidate list is not read), so a CASE sheet, a SUBMIT job's pid and a NAV draft named by a
    pseudonym are refused, and so is any new job type until it is added after a review. Of an open job, only the
    files of `DOWNLOADS_OPEN_DURING_A_SESSION` are served, each named with why it holds no patient-linked text (a FEAS
    job's `feasibility_*.pdf|json`, not `.raw.json`; its `feasprofile_*.json`); every other file is refused whatever
    its tag: the `aggregate` tag is not trusted for the switch, since an ingest report tagged `aggregate` carries
    validation messages that can name a patient (`Patient/<pseudonym>: birthDate`). The sponsor pack, a job's reveal
    and release, and a cascade run's files are refused too. The check runs only for a signed-in request (a
    signed-out one gets the route's sign-in answer, so no job type is told to a stranger, the review's item 8), a job
    that cannot be read is refused (closed on doubt), and every refusal is a `console.denied` event (`why`:
    `support session`).
  - **Content, not only rows (the review of aeb978e6, H1):** a page that mixes staff content with patient-linked
    content is an open row, so the closing is also at the helpers that hand a page patient-linked content. They ask
    one function, `tb_common.authz.session_on()` (true under a session, or when its state could not be read), and
    answer nothing while it is true; the page shows its staff parts and the line "Closed during the support
    session" (en, ja, zh-TW). `console.home`'s `load` (every job file a home, week or study card reads) answers None
    for every file but the counts-only ones (`COUNTS_ONLY`: `feasibility_`, `feasprofile_`), so the study home
    (`/home?view=studies`, with `layout.home_today` off) shows no task link, pseudonym or PI note; its tasks, clinic
    visits and SAE banners are empty and the closed line is shown. `console.dataops_page.steps_shown` withholds every
    batch step's reason (a steward's free text, "Duplicate chart 70000054", the review's item 6) on the page and in
    `GET /api/v1/data/batches/{bid}` (`reason: null`, `reason_closed: true`); states, who and when stay.
  - **Every place that can emit a patient-linked field, and how it is closed** (a pseudonym, a screening or chart
    number, a name, a birth date, a clinical note or quote, free text about a patient; the templates were searched
    for these fields and the handlers for their helpers): (1) the 67 templates that name such a field render, during
    a session, only behind a closed row (the patient, candidate, week, registry, SAE, SDV, data-entry, audit, EDC
    review, team-candidate and site-patient pages, the screening log and the break-glass list: `permit`), with these
    exceptions, each closed as said: `home_crc.html` (the study home: `load` and the closed line), `job.html` and
    `approval.html` (the job allow-list), `dataops_batch.html` (the reasons withheld), `registry_ruleset.html`
    (rendered with no row: its rows ask a closed row), `base.html` and `_feedback.html` (a refusal is rendered as if
    at `/`, so no refused URL is repeated), `home_admin.html` and `admin.html` (a job's id, type, requester and time,
    no patient field); (2) files: a job's files and views (the download allow-list), the sponsor pack, a job's reveal
    and release, a cascade run's files, `/feedback/export.csv` (refused), every registry, screening-log, SAE and audit
    export (closed rows); `/site/templates/{name}.xlsx` (blank setup sheets) and `/about/NOTICE.txt` stay open, with
    no patient; (3) JSON: the `/api/v1` twins of the pages above, closed by the same rows and helpers; (4) mail (below).
    The guard is `test_no_open_route_shows_a_seeded_patient_token_during_a_session`: synthetic patients of every kind
    (a SCREEN list with a quote, a PI's note, a CASE sheet, a SUBMIT job's pid, a NAV draft named by a pseudonym, an
    ingest report naming a patient, a feedback entry given on a patient page with a chart number) are seeded, a session
    is started, and every route of the router table is asked as every column of the role-route walk (GET, then each
    changing method with a valid CSRF token) plus every page and file of every seeded job (2,000 and more answers);
    no answer may hold any of the 25 seeded tokens. It runs twice, with the flag `layout.home_today` off and on (on is
    what ships; the PI's mark is made 4 days back, so its task is overdue on "Needs you today", which shows it outside
    a session). On aeb978e6 it found 143 leaks (the study home, the SUBMIT and NAV
    job pages and files, the ingest report); now none. A new open route that leaks fails it.
  - **An answer begun before the start (the review of aeb978e6, H4).** The switch was read only at a request's
    entry, so a patient page waiting on the backend when the session started could still be sent after the
    administrator saw "on". Now (a) an answer begun outside a session is read against the switch again when it is
    ready: if a session started meanwhile (in any process: the state is the database's) it is replaced by the
    refusal before a byte of it leaves; (b) the console counts, per process, the answers begun outside a session whose
    body is not yet sent; a start waits until they are sent or refused, at most 15 s (`DRAIN_S`), before its
    confirmation is shown, and a body still being sent stops at its next part when a session started in this
    process. The confirmation says it ("every page asked before the start was finished or refused before this line
    was shown"), and if the wait ran out it says so and asks for a minute before sharing. The console runs as one
    process (`deploy/docker-compose.yml`, no `--workers`), so the count is the console's. **Residual windows**, in the
    confirmation's fine print and here: what is already on a screen or in another window (closed by the person;
    reload and back are `no-store`); a body already handed to the client; a long download of another console process
    (none in the shipped compose) that passed its end check before the start; mail already sent. The confirmation is
    shown only while a session is open (the review's item 9): the old `?done=start` URL after the end shows nothing.
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
- **Mail during a session (the review of aeb978e6, H5).** The card closes patient pages; mail goes to the
  recipients' mailboxes, not to the screen the support person watches, but a mailbox can be open on the shared
  hospital PC, so mail with patient details waits. The mail gateway, the one door of every mail, asks the
  orchestrator before every send (`GET /support-session`, a yes or no read from the console's own store, SELECT as
  for the grants); while a session runs every mail is held: queued, the try not counted, the audit event
  `mail.deferred` with the reason "held: a support session is running", asked again every 5 minutes, and sent once
  after the end (the send key keeps it once). Three kinds are not held, by the key the orchestrator gives them
  (`SUPPORT_MAIL_PREFIX`): the serious adverse event copy to the office (`service:console-sae-sync`; safety mail is
  never delayed, and it carries a pseudonym), the box's health mail and the account notice (no patient in either).
  Held: N1 and N2 (pseudonyms and visit times, the SAE counts and overdue SAE reports among them: at most 2 hours
  late, and the serious AE itself has gone out at once), a break-glass notice (none can be opened during a session),
  and every job's mail (a CASE sheet, a list, a receipt). A state that cannot be read holds too; nothing is dropped.
  On the first day a mail of the three kinds may go twice (its key changed with this card), never zero times.
- **The start form** uses the shared field macro (9k-6a, D-1376; typed fields, D-1384): a wrong ticket or no tick
  answers 400 with the error summary tied to each field (`support-start` in `tests/console/form_cases_9k6a.py`); the
  form-fields ratchet list is not raised.
- **Not in this card, said plainly:** the switch marks console requests only. Code outside a request is not marked:
  the morning-mail timer still builds its notices (they wait at the gateway, above), the nightly REDCap read
  (`rc_read`) and the orchestrator's own jobs still run. The orchestrator refuses a patient read the console did not
  sign, and the console signs none during a session. A terminal on the box (runbook 21 rule 3) is
  outside the switch: what it shows is the hospital person's care. The support bundle's Docker drill (runbook 21) is
  not part of the new drill. `python -m console.cli` (on the box's terminal) can still issue an enrolment code.
- **Known limits:**
  - A `support_sessions` row deleted by hand (in the database) ends the session with no end event: the trail holds a
    start with no end. The console cannot write an event for a row it no longer sees; the steward's review of the
    trail is where it shows.
  - A clock moved forward ends a session early (the pages open while support may still watch); one moved back is
    re-anchored and audited (above). Both are the clock's, not the switch's.
  - `/jobs` and the administrator's home list every job's row (its id, type, ruleset, requester and time) during a
    session. It is not patient-level: the id is a random job id the box makes, and it holds no pseudonym, chart
    number or clinical fact; every page and file of a closed job is refused during a session with no job id in the
    body. A signed-in account that knows a job's id learns from the refusal that it is not of a counts-only type.
  - Cancelling a job waits for the end of a session (the review's item 11): the cancel signs `request.prepare`,
    closed, so it is refused before its confirmation, audited; the mail command's row `command.CANCEL` is closed too.
  - A damaged start whose time parses but whose UTC time or end underflows (`0001-01-01T00:00:00+14:00`, the
    review's item 7) is a start that cannot be read: on until ended by hand, and the end works.
  - A one-time password held back by a session and read later is gone after its 10 minutes (the review's item 10).
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
  one audit event; a FEAS job's file of counts stays open and its patient-level file, downloadable by its named
  recipient outside a session, is refused during one; the review of aeb978e6: the walk with seeded patient data,
  the study home (three languages), a SUBMIT and a NAV job, an ingest report tagged aggregate, an answer begun before
  the start and a start that cannot wait, the batch reasons, a start that underflows, a signed-out request for a
  closed job, the confirmation after the end, an old one-time password, the cancel);
  `tests/unit/test_10k15_mail_during_a_support_session.py` (mail held during a session and sent once after it, the
  safety, health and account notices not held, a state that cannot be read holds, the orchestrator's answer); `tests/console/test_role_route_matrix.py` (the three new routes, the
  administrator's only); `tests/unit/test_migrations.py` (breakglass version 3).
