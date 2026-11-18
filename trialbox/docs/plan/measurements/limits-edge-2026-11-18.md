# Every stated limit at the limit, one over and far over (2026-11-18)

**Reader:** the people who build TrialBox: the lanes that own the enforcement points (C2, E, A2, B2, D), lane V (the
findings register) and the integrator. Findings for builders, so in one language.

Card H-35 (was lane V's V-16), decision D-1101. The integrator's words: "every stated limit at the limit, one over and
far over: refused before work starts, in plain words." This page reports and fixes nothing: no product file was
changed. The tool is `tools/limits_edge.py`; the run behind the tables is `limits-edge-2026-11-18/run.json`; the
findings in the register's `--add-from` form are `limits-edge-2026-11-18/findings.json`.

## The answer

- **35 stated limits** were found (the catalogue below), besides the limits register's 74 rows (waits and page sizes
  inside the box) and 23 declared settings whose name says a bound. **18 were driven** here, at the limit, one over
  and far over. **17 of the 18 hold as limits** in all three cases: the at-limit case was accepted and worked, and
  both over cases were refused before any work. The one that does not is the REDCap connector's **file export**: it
  downloads the whole file and only then refuses it (H35-01).
- **No limit accepted a request over it; nothing crashed, hung or left the box unhealthy.** The largest far-over
  cases (a 200 MiB protocol, a 250 MiB REDCap import, a 50 MB ODM file, a 20 MB sponsor sheet) were refused in under
  a second.
- **Words.** Of the 18, five refuse in words that do not name the limit somewhere a person reads them: the EDC pages
  for a long reason (H35-03) and for the connector's file limit (H35-02), and zh-TW and ja for a monitoring visit's
  findings (H35-04) and a local account's end date (H35-05). The console's upload refusal is plain in three languages
  but answers 400 where the interface specification says 413 (H35-06).
- **7 findings**, all Medium, none High: 4 for lane C2, 3 for lane E. One (H35-07) is from an unstated limit read in
  the code: the site set-up pages cut a code or site sheet at 20 MiB instead of refusing it.

## How the list was built (and is built again)

`TB_ENV=TEST PYTHONPATH=libs:services:. python -m tools.limits_edge --list` prints it. Three parts:

1. **The catalogue** (`STATED` in the tool): read by hand from the user guide, the runbook, the security pages, the
   decisions, the specification (`docs/plan/design/`), the data pages and the declared settings, for the limits a
   person, an operator or another service meets. Each row names its file and a phrase that must stand in it; the line
   is found again on every run (a row whose phrase is gone fails the list, and `tests/unit/test_limits_edge.py`).
   Each row says where the limit is enforced (`file:function`, or "not found"), who meets it, and either its driver
   or why it is not driven.
2. **The limits register** (`tools/limits_allow.yaml`, the limits lint's list): every row, with its line (74 rows: 42
   counts, 32 waits). They are the box's own waits and page sizes, not refusals a person meets; they are listed in
   `run.json` and not driven (scale is H-23's: `docs/plan/measurements/size-test-2026-11-17.md`).
3. **The declared settings** (`libs/tb_common/config.py`) whose name holds `MAX`, `LIMIT`, `PER_HOUR`, `PER_DAY` or
   `BUDGET` and that no catalogue row covers: 23, listed below, not driven.

A bound in code that none of these states is **unstated**: every module-level constant with `MAX` in its name and a
number, in `services/` and `libs/`, that no catalogue row claims (by file and name). 69 today, listed below. They are
not tested (D-1101).

## How the limits were driven

On this machine, in process, with the stub model and no GPU; **compose was not used** (Docker is installed, but the
compose box was not started). Three kinds of driver, each row says which:

- **console page**: the console app (`console.app.create_app`) on the console tests' stand-in orchestrator
  (`FakeBackend`), with its own PostgreSQL from `tools.pglocal`, driven by HTTP through the test client, in en, zh-TW
  and ja (the account's language set on `/lang`, or `Accept-Language` at sign-in). "Before work" is read from the
  stand-in's created jobs and stored objects and from the audit folder;
- **the real orchestrator's `create`** (`tests.inproc_box.make_box`: the job database, the audit) for the daily
  limit, with the console's own mapping of the orchestrator's refusal to its page words;
- **function or store**: the enforcement function itself (`edc.odm_import.read`, `datacore.sponsor.read_weekly`,
  `edc.store.said`, `console.admin_accounts.end_date`, `console.auth.check_password_policy`, the identity settings,
  `tb_llm.budget.over_context`), or the store on PostgreSQL (`TeamStore.add_monitor_visit`, `BreakGlassStore.open`).
  Where a page shows the words, they are made by the page's own functions (`console.refusals.localize_reason` and the
  catalogue's `request.refused`, or the page's message key); for the EDC pages, by the rule of
  `templates/_edc_err.html`, read and applied, the page not rendered (marked). The REDCap connector runs against a
  stand-in client that records each call; the reveal note against `Reveal._reason_ok` with a stand-in for its audit
  write; the prompt length against the gateway's comparison (`over_context`), not its token estimate.

The three cases: exactly at the limit (it must be accepted and work), one over (one under for a floor: the password,
the break-glass note's 10 characters, the reveal note), and far over: ten times, except the console upload (4x,
200 MiB: the test client holds the whole body in memory) and the REDCap export (4x, 100 MiB, for the same reason).

    make limits-edge                     # the box's drivers; fails only on a verdict the page does not record
    TB_ENV=TEST TB_TZ=<the site's zone> PYTHONPATH=libs:services:. python -m tools.limits_edge --drive --out run.json
    python -m tools.limits_edge --markdown run.json      # the table below

## The table

"Refused before work?": yes when every refused case left no job, file, row, call or audit of work. "Words": whether
the refusal a person or caller reads names the limit's value, per language (– where it is not a page: an API, a
mail, a setting at start-up). The verdict is about the limit (accepted, refused, when), not the words; the words'
findings are below.

| Id | Limit | Source | Value | Enforced | Driven on | At | One over | Far over | Refused before work? | Words name the limit (en / zh-TW / ja) | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| L01 | heavy jobs one account may start a day, each kind on its own (console) | `docs/user-guide/03-the-everyday-work.md:12` | 20 jobs / 24 h | `services/orchestrator/core.py:Orchestrator.create` | the real orchestrator's create (orchestrator.core.Orchestrator.create, tests.inproc_box) and the console's words for its refusal (the console's own mapping of the orchestrator's sentence) | accepted | refused 403 Rejected | refused 403 Rejected | yes | yes / yes / yes | holds |
| L02 | heavy job requests one mailbox may send a day (mail) | `docs/DECISIONS.md:3145` | 20 requests / 24 h | `services/mail_gateway/intake.py:decide` | function: mail_gateway.intake.decide, the day's count from a stand-in of MailDB | accepted | refused reject | refused reject | yes | yes / – / – | holds |
| L03 | a daily limit of 0 is no limit | `libs/tb_common/config.py:765` | 0 jobs / 24 h (0 = none) | `libs/tb_common/authz.py:daily_limit` | function: tb_common.authz.daily_limit with settings.yaml's limit set to 0 | accepted | – | – | – | – | holds |
| L04 | an uploaded protocol, consent form, chart or attachment on the console | `docs/plan/design/08-interface-control.md:91` | 50 MB | `services/console/app.py:protocol_submit` | console page: POST /pilot/protocol on the in-process console (stand-in orchestrator) | accepted | refused 400 | refused 400 | yes | yes / yes / yes | holds |
| L05 | an ODM file imported into the EDC | `docs/decisions/D-435-odm-import-sponsor-readers.md:35` | 5000000 bytes | `services/edc/odm_import.py:read` | function: edc.odm_import.read (the orchestrator's bound; the page's own 6 MiB cap is above it) | accepted | refused odm.size | refused odm.size | yes | yes / yes / yes | holds |
| L06 | the sponsor's weekly sheet | `docs/decisions/D-435-odm-import-sponsor-readers.md:64` | 2000000 bytes | `services/datacore/sponsor.py:read_weekly` | function: datacore.sponsor.read_weekly | accepted | refused sponsor.size | refused sponsor.size | yes | yes / – / – | holds |
| L07 | a file through the REDCap connector | `docs/data/13-redcap-and-the-edc-backend.md:45` | 26214400 bytes | `services/edc_backend/connection.py:EdcConnection.import_file / export_file` | function: edc_backend.connection.EdcConnection.import_file / export_file, a stand-in REDCap | accepted | refused RC-UPSTREAM | refused RC-UPSTREAM | no | no / no / no | one_over refused after work; far_over refused after work |
| L08 | the reason for a feature-flag change | `docs/decisions/D-207-feature-flags.md:56` | 500 characters | `services/console/admin_flags.py:flags_set` | console page: POST /ops/flags on the in-process console | accepted | refused 400 | refused 400 | yes | yes / yes / yes | holds |
| L09 | an EDC reason or citation text (refused, never cut) | `docs/decisions/D-854-a-long-reason-is-refused-never-cut.md:1` | 300 characters | `services/edc/store.py:said` | function: edc.store.said (EDC-022) | accepted | refused 400 edc.too_long | refused 400 edc.too_long | yes | no / no / no | holds |
| L10 | a monitoring visit's findings | `docs/decisions/D-436-monitor-sdv.md:45` | 2000 characters | `services/console/teamstore.py:TeamStore.add_monitor_visit` | store: console.teamstore.TeamStore.add_monitor_visit on PostgreSQL; words through the monitoring page's refusal path (request.refused with the store's sentence) | accepted | refused 400 request.refused | refused 400 request.refused | yes | yes / no / no | holds |
| L11 | a break-glass note | `docs/decisions/D-280-steward-and-break-glass.md:25` | 10 to 300 characters | `services/console/breakglass_store.py:BreakGlassStore.open` | store: console.breakglass_store.BreakGlassStore.open on PostgreSQL; words by the page's keys (bg.err.long, bg.err.note) | accepted | refused bg.err.long | refused bg.err.long | yes | yes / yes / yes | holds |
| L12 | a local account's end date | `docs/runbook/25-leavers.md:21` | 365 days ahead | `services/console/admin_accounts.py:end_date` | function: console.admin_accounts.end_date; words through the console's refusal path | accepted | refused AuthError | refused AuthError | yes | yes / no / no | holds |
| L13 | failed sign-ins before an account is locked for 15 minutes | `docs/security/03-who-may-call-what.md:73` | 5 failures | `services/console/auth.py:UserStore.locked_until` | console page: POST /login on the in-process console | accepted | refused 401 | refused 429 | yes | yes / yes / yes | holds |
| L14 | a password's least length | `docs/runbook/12-identity-and-tls.md:59` | 12 characters (a floor) | `services/console/auth.py:check_password_policy` | function: console.auth.check_password_policy; words through the console's refusal path | accepted | refused 400 account.err.policy | refused 400 account.err.policy | yes | yes / yes / yes | holds |
| L15 | minutes idle before a console session ends (setting range) | `docs/runbook/12-identity-and-tls.md:54` | 1 to 60 minutes | `services/console/identity.py:_int_in` | function: console.identity.IdentitySettings.from_env (the console's start) | accepted | refused IdentityConfigError (the console does not start) | refused IdentityConfigError (the console does not start) | yes | yes / – / – | holds |
| L16 | hours a console session lasts in all (setting range) | `docs/security/03-who-may-call-what.md:86` | 1 to 12 hours | `services/console/identity.py:_int_in` | function: console.identity.IdentitySettings.from_env (the console's start) | accepted | refused IdentityConfigError (the console does not start) | refused IdentityConfigError (the console does not start) | yes | yes / – / – | holds |
| L17 | a reveal for purpose 'other' needs a written why | `docs/security/03-who-may-call-what.md:99` | 10 characters (a floor) | `services/console/reveal.py:_reason_ok` | method: console.reveal.Reveal._reason_ok with a stand-in for its refusal (the audit write); words by the page's key reveal.note_needed | accepted | refused 400 reveal.note_needed | refused 400 reveal.note_needed | yes | yes / yes / yes | holds |
| L18 | a model call's prompt plus answer budget | `docs/decisions/D-357-context-aware-budgets.md:12` | 32768 tokens (the RTX PRO 6000 builds) | `services/gateway/core.py:Gateway._try (tb_llm.budget.over_context)` | function: tb_llm.budget.over_context, the gateway's check before dispatch (stand-in for the gateway's call: a true test of the comparison, not of the token estimate) | accepted | refused 413 prompt_too_long (raised before dispatch) | refused 413 prompt_too_long (raised before dispatch) | yes | yes (not plain) / – / – | holds |
| L19 | chart numbers one person may reveal an hour | `docs/security/03-who-may-call-what.md:55` | 60 reveals / hour | `services/console/reveal.py:cap; services/orchestrator/app.py:reveal` | not driven | – | – | – | – | – | not driven |
| L20 | screening-log exports with chart numbers an hour | `docs/security/03-who-may-call-what.md:111` | 10 exports / hour | `services/orchestrator/app.py:registry_export` | not driven | – | – | – | – | – | not driven |
| L21 | pseudonym lookups by chart number an hour | `docs/decisions/D-487-identifiers-one-door.md:36` | TB_REVEAL_MAX_PER_HOUR lookups / hour | `services/orchestrator/identifiers.py:admit` | not driven | – | – | – | – | – | not driven |
| L22 | model calls on threads at once in the gateway | `docs/decisions/D-445-gateway-under-load.md:32` | 64 calls | `services/gateway/app.py:chat` | not driven | – | – | – | – | – | not driven |
| L23 | refusal replies one sender gets a day | `docs/runbook/04-morning-mail-missing.md:40` | 10 replies / day | `services/mail_gateway/gateway.py:Gateway._reject` | not driven | – | – | – | – | – | not driven |
| L24 | mails to one address in 24 hours | `docs/decisions/D-401-mail-outbox.md:37` | 200 mails / 24 h | `services/mail_gateway/gateway.py:Gateway._over_limit` | not driven | – | – | – | – | – | not driven |
| L25 | restarts a job survives before it is failed | `docs/runbook/04-troubleshooting.md:36` | 3 restarts | `services/orchestrator/core.py:Orchestrator._recover` | not driven | – | – | – | – | – | not driven |
| L26 | patients screened a night by the microbatch | `docs/runbook/04-troubleshooting.md:24` | 2000 patients / night | `services/orchestrator/scenarios/microbatch.py:reserve` | not driven | – | – | – | – | – | not driven |
| L27 | a break-glass grant's length | `docs/user-guide/02-roles.md:15` | 60 minutes | `libs/tb_common/authz.py; services/console/breakglass_store.py:open` | not driven | – | – | – | – | – | not driven |
| L28 | the lake's spill to disk | `docs/runbook/04-troubleshooting.md:14` | 50 GB at most | `services/lake/store.py (TB_LAKE_MAX_TEMP)` | not driven | – | – | – | – | – | not driven |
| L29 | container log files per service | `docs/runbook/02-daily-operation.md:44` | 100m x 10 size x files | `deploy compose logging (TB_LOG_MAX_SIZE, TB_LOG_MAX_FILE)` | not driven | – | – | – | – | – | not driven |
| L30 | studies per standard site | `docs/plan/design/01-SRS.md:1177` | 20 studies (CGMH 50) | `not found (a capacity target, not a cap)` | not driven | – | – | – | – | – | not driven |
| L31 | a site's rule book for the judge | `docs/plan/design/01-SRS.md:809` | 2000 characters | `not found (FR-JP-09 is not built: status N)` | not driven | – | – | – | – | – | not driven |
| L32 | a CASE answer within 60 s for at most 200 notes and 20 note criteria | `docs/plan/design/01-SRS.md:434` | 200 / 20 notes / note criteria | `not found (a performance condition, not a cap)` | not driven | – | – | – | – | – | not driven |
| L33 | raw extracts kept in the landing area | `docs/plan/design/01-SRS.md:307` | 7 days at most | `not checked here (retention)` | not driven | – | – | – | – | – | not driven |
| L34 | a feed load's largest row drop | `docs/decisions/D-271-data-pipeline-integrity.md:5` | 20 percent (default) | `libs/tb_common/feedguard.py` | not driven | – | – | – | – | – | not driven |
| L35 | mail retries before a mail is failed | `docs/runbook/04-morning-mail-missing.md:32` | 12 tries, at most an hour apart | `services/mail_gateway/gateway.py (MAX_ATTEMPTS, RETRY_MAX_S)` | not driven | – | – | – | – | – | not driven |

Notes on the driven rows:

- **L01**: the 20th FEAS of the day was stored and queued; the 21st and the next 179 were refused by the orchestrator
  before any row (`job.state` and `mail.sent` recorded only for the accepted one; the refusals are not audited). The
  console's page words name 20 and FEAS in three languages.
- **L02**: the mail path refuses in English ("daily limit of 20 FEAS requests reached; try again tomorrow"); a reply
  mail is in English only.
- **L03**: a limit of 0 is no limit for `rate_limits_per_day` and `TB_JOBS_PER_SENDER_PER_DAY`, as stated. The global
  `rate_limit_per_sender_per_day: 0` becomes 20 (`authz.py`: `... or 20`); no document says what 0 means there, so it
  is an unstated behaviour, not a finding.
- **L04**: the 50 MiB protocol made one job (`console.request`); one over and 200 MiB made none, stored nothing and
  wrote no audit record. The refusal is the same for the consent form, the CASE chart and a mail attachment (one
  constant, four handlers; only the protocol was driven).
- **L05**: the orchestrator's bound (5,000,000 bytes, `TB_EDC_ODM_MAX_BYTES`). The EDC import page reads up to 6 MiB
  itself and sends a file between the two to the orchestrator, which refuses it with the same words.
- **L06**: an API caller's limit (no console page sends the weekly sheet); the at-limit sheet is 19,000 rows
  (the reader's own row bound, 20,000, is unstated).
- **L07**: see H35-01 and H35-02. The import side refuses before any call to REDCap.
- **L11**: both ends of "10 to 300 characters" driven: 300 and 10 accepted; 301, 3,000, 9 and 0 refused.
- **L13**: four wrong passwords and then the right one signs in; five lock the account for 15 minutes, and the page
  says so with the time in three languages (`console.lockout`). Fifty wrong passwords from one address are slowed by
  the per-address limit (D-279, ten failures) before the account's count reaches five: the page says "wait 1
  second(s) ... no account was locked by this", which is true; it names the wait, not the five.
- **L15**: unset, the idle limit is 10 minutes, as the runbook and the security page say. (The specification's table
  at `01-SRS.md:63`, "sessions 30 min idle", describes the baseline at commit a1e55fa; not a finding.)
- **L18**: the gateway's own sentence is for another service and names the context; the request is refused before
  dispatch (413).

## Findings

Severity by the register's rule (plan 8, section 5b; `docs/handover/findings-register.md`): Medium is a person slowed
or misled, or a document's claim not true. The owning lane is the lane of the file that enforces the limit or shows
the words.

| Id | Limit | Case | What happened | Expected (and its source) | Severity | Lane | Basis |
| --- | --- | --- | --- | --- | --- | --- | --- |
| H35-01 | L07 | one over, far over (export) | refused after the whole file was read from REDCap into memory | refused before the download (the size from REDCap's metadata, or a read cut at the limit plus one) (docs/data/13-redcap-and-the-edc-backend.md:45 ("A file larger than TB_REDCAP_FILE_MAX_BYTES ... is refused"); D-1101 rule 3) | Medium | E | shown |
| H35-02 | L07 | one over, far over | RC-UPSTREAM; page words point at the address and the API key | words that name the limit (25 MB) and say to send a smaller file (docs/data/13-redcap-and-the-edc-backend.md:45; D-1101 rule 4) | Medium | E | hypothesis |
| H35-03 | L09 | one over, far over | edc.err.other on the page in three languages | the page names the 300-character limit and says to shorten the text (D-854 (refused with edc.too_long); D-1101 rule 4) | Medium | C2 | hypothesis |
| H35-04 | L10 | one over, far over | zh-TW 已拒絕：無法執行此請求；若持續發生，請聯絡管理員; ja the same generic sentence | the limit (2,000 characters) and "shorten the findings" in zh-TW and ja (D-436 (findings, at most 2,000 characters); D-119 (every refusal in the page's language)) | Medium | C2 | shown |
| H35-05 | L12 | one over, far over | the generic sentence in zh-TW and ja on Users | the limit (365 days, the latest date) in zh-TW and ja (docs/runbook/25-leavers.md:21; D-119) | Medium | C2 | shown |
| H35-06 | L04 | one over, far over | 400 request.refused | 413, as UP-SIZE states (or the specification changed to 400) (docs/plan/design/08-interface-control.md:91 (UP-SIZE 413)) | Medium | C2 | shown |
| H35-07 | unstated: services/console/site_pages.py:52 MAX_UPLOAD | read, not driven | read from the code: up.read(MAX_UPLOAD + 1) with no comparison before the signed post | a stated limit, and a file over it refused whole before it is sent (D-854's rule: refused, never cut) (D-1101 rule 1 (an unstated limit is listed, not tested); this row because a cut file is not a refusal) | Medium | C2 | hypothesis |

## Could not be driven here

| Id | What it needs |
| --- | --- |
| L19 (chart numbers one person may reveal an hour) | needs listed candidates on the real orchestrator (the orch_box of the console tests, an ingested lake) and 61 reveals; not built in this card's time |
| L20 (screening-log exports with chart numbers an hour) | needs the real orchestrator with a finished SCREEN (orch_box); not built in this card's time |
| L21 (pseudonym lookups by chart number an hour) | needs the real orchestrator with a site key and a lake (orch_box); not built in this card's time |
| L22 (model calls on threads at once in the gateway) | needs 64 model calls held open at once; the stub answers at once, so a stand-in would test a counter, not the box |
| L23 (refusal replies one sender gets a day) | needs the mail gateway's outbox over a day of refused mail; not built in this card's time |
| L24 (mails to one address in 24 hours) | the limit waits (the mail stays queued an hour), it does not refuse; needs 201 queued mails and the outbox's clock; not built in this card's time |
| L25 (restarts a job survives before it is failed) | needs the box restarted under a running job: the failure drills (tools/failure_drill*.py) are another lane H card's |
| L26 (patients screened a night by the microbatch) | not a refusal: the rest is carried to the next night; needs a night of 2,001 changed patients (scale: H-23) |
| L27 (a break-glass grant's length) | a time limit, not a size: needs the clock moved past the grant; no refusal at the start |
| L28 (the lake's spill to disk) | needs a query that spills 50 GB: hours of data on a large disk |
| L29 (container log files per service) | compose's own log rotation; compose was not run (a box under Docker was not started) |
| L30 (studies per standard site) | a capacity target (NFR-CAP-02), not a refusal; enforced nowhere |
| L31 (a site's rule book for the judge) | the feature is not built (FR-JP-09, status N); nothing to drive |
| L32 (a CASE answer within 60 s for at most 200 notes and 20 note criteria) | a performance target with the judge loaded: needs a GPU and the real model |
| L33 (raw extracts kept in the landing area) | a retention time: needs a week of the clock; not a refusal |
| L34 (a feed load's largest row drop) | a night's guard on a second load of the hospital's feed; the bad-file card H-34 owns bad feeds |
| L35 (mail retries before a mail is failed) | needs twelve hours of a refusing mail server |

## Declared settings that state a bound, not in the catalogue (listed, not driven)

| Where | Setting | Default |
| --- | --- | --- |
| `libs/tb_common/config.py:382` | `TB_AUDIT_HEAD_MAX_AGE_H` | 36 |
| `libs/tb_common/config.py:385` | `TB_AUDIT_TS_MAX_SKEW_S` | 300 |
| `libs/tb_common/config.py:407` | `TB_BACKUP_MAX_AGE_HOURS` | (empty) |
| `libs/tb_common/config.py:431` | `TB_CANARY_MAX_AGE_H` | (empty) |
| `libs/tb_common/config.py:433` | `TB_CANARY_RETRY_MAX_S` | 600 |
| `libs/tb_common/config.py:441` | `TB_CANDIDATE_VIEWS_PER_HOUR` | (empty) |
| `libs/tb_common/config.py:456` | `TB_CLOCK_MAX_SKEW_S` | (empty) |
| `libs/tb_common/config.py:601` | `TB_EMBED_BATCH_BUDGET` | 8192 |
| `libs/tb_common/config.py:615` | `TB_EVAL_LIMIT` | (empty) |
| `libs/tb_common/config.py:617` | `TB_EXPORT_MAX_PER_HOUR_PER_SERVICE` | 60 |
| `libs/tb_common/config.py:639` | `TB_GATEWAY_CALL_BUDGET_S` | 210 |
| `libs/tb_common/config.py:729` | `TB_LAKE_BUDGET_MB` | (empty) |
| `libs/tb_common/config.py:735` | `TB_LAKE_MAX_TEMP` | (empty) |
| `libs/tb_common/config.py:736` | `TB_LAKE_MAX_SNAPSHOT_AGE_DAYS` | 0 |
| `libs/tb_common/config.py:737` | `TB_LAKE_MEMORY_LIMIT` | (empty) |
| `libs/tb_common/config.py:740` | `TB_LAKE_QUERY_LIMITS` | FEAS=1800,COHORT=1800 |
| `libs/tb_common/config.py:801` | `TB_NTP_MAX_OFFSET_S` | (empty) |
| `libs/tb_common/config.py:835` | `TB_OPTOUT_LOOKUPS_PER_HOUR` | (empty) |
| `libs/tb_common/config.py:848` | `TB_PG_MAX_WAL_SIZE` | 1GB |
| `libs/tb_common/config.py:897` | `TB_REDCAP_MAX_PER_MINUTE` | 0 |
| `libs/tb_common/config.py:928` | `TB_REVEAL_MAX_PER_HOUR_PER_SERVICE` | 600 |
| `libs/tb_common/config.py:966` | `TB_SCALE_LIMIT_S` | (empty) |
| `libs/tb_common/config.py:993` | `TB_SCREEN_MAX_PAIRS` | (empty) |

## Unstated limits in code (listed, not tested)

Module-level constants with `MAX` in their name and a number, in `services/` and `libs/`, that no catalogue row
claims. Some are bounds a person meets that no document states: the feedback comment (1,000), an SAE receiver's
reference (60), a site's sponsor name (120) and note (200), a data dictionary (2 MiB), the site set-up upload
(20 MiB, see H35-07), the reasons on the conflicts and data-operations pages (500, cut, not refused), a mail's
subject (998) and attachments (20, 50 MB each), a chart for CASE (200,000 characters) and an ICF (60,000). Others are
internal (depths, retries, a header's length).

| Where | Name | Value |
| --- | --- | --- |
35 74 23 69
| `services/adapter/mapping/engine.py:249` | CODE_MAX | 40 |
| `services/adapter/mapping/sharereport.py:31` | DIGITS_MAX | 5 |
| `services/adapter/mapping/sharereport.py:39` | SHAPE_MAX | 40 |
| `services/adapter/mapping/sharereport.py:42` | UNIT_MAX | 20 |
| `services/adapter/pipeline.py:1510` | REJECT_MAX_PCT | 1.0 |
| `services/adapter/sources/ssmix2/source.py:144` | QUARANTINE_MAX_PCT | 1.0 |
| `services/console/conflicts_page.py:39` | MAX_REASON | 500 |
| `services/console/data_pages.py:50` | MAX_DICTIONARY | 2097152 |
| `services/console/dataops_page.py:57` | MAX_REASON | 500 |
| `services/console/feedback.py:47` | COMMENT_MAX | 1000 |
| `services/console/feedback.py:48` | PATH_MAX | 200 |
| `services/console/next_page.py:18` | MAX_AGE | 900 |
| `services/console/notify.py:57` | MAX_ROWS | 10 |
| `services/console/saerecord.py:62` | REF_MAX | 60 |
| `services/console/site_pages.py:52` | MAX_UPLOAD | 20971520 |
| `services/console/sitestore.py:263` | SPONSOR_MAX | 120 |
| `services/console/sitestore.py:288` | NOTE_MAX | 200 |
| `services/criteria_compiler/service.py:62` | MAX_ROUNDS | 3 |
| `services/criteria_compiler/service.py:145` | MAX_HALVINGS | 2 |
| `services/criteria_compiler/service.py:324` | REFUSED_REASON_MAX | 600 |
| `services/criteria_compiler/terminology/mapper.py:270` | FHIR_ID_MAX | 64 |
| `services/datacore/dataops.py:86` | MAX_PAGE | 200 |
| `services/datacore/sponsor.py:63` | MAX_ROWS | 20000 |
| `services/edc/logic.py:37` | MAX_TEXT | 4000 |
| `services/edc/logic.py:38` | MAX_TOKENS | 1000 |
| `services/edc/logic.py:39` | MAX_DEPTH | 40 |
| `services/edc/mapping.py:64` | MAX_WINDOW | 3650 |
| `services/edc/odm_import.py:39` | MAX_DEPTH | 16 |
| `services/edc/odm_import.py:40` | MAX_ELEMENTS | 500000 |
| `services/edc/odm_import.py:41` | MAX_VALUE | 4000 |
| `services/edc/store.py:143` | DETAIL_MAX | 300 |
| `services/embed_service/embedder.py:120` | MAX_TOKENS | 512 |
| `services/lake/store.py:754` | MAX_QUERY_LIMIT_S | 86400 |
| `services/mail_gateway/intake.py:23` | MAX_ATTACHMENTS | 20 |
| `services/mail_gateway/intake.py:24` | MAX_ATTACHMENT_BYTES | 52428800 |
| `services/mail_gateway/intake.py:25` | MAX_SUBJECT_CHARS | 998 |
| `services/matching/stored_scores.py:46` | MAX_FREE | 8 |
| `services/model_guard/__init__.py:50` | MAX_BODY | 16777216 |
| `services/omop/conflicts.py:31` | MAX_ROWS | 500 |
| `services/omop/schema.py:125` | INT4_MAX | 2147483647 |
| `services/orchestrator/canary_gate.py:46` | MAX_AGE_H | 36.0 |
| `services/orchestrator/canary_gate.py:316` | RETRY_MAX_S | 600.0 |
| `services/orchestrator/conflicts_api.py:35` | MAX_REASON | 500 |
| `services/orchestrator/core.py:819` | WORKER_RETRY_MAX | 30.0 |
| `services/orchestrator/scenarios/case.py:74` | MAX_CHART_CHARS | 200000 |
| `services/orchestrator/scenarios/case.py:75` | MAX_EXCERPT_CHARS | 1800 |
| `services/orchestrator/scenarios/consent.py:59` | MAX_ICF_CHARS | 60000 |
| `services/orchestrator/scenarios/evaluate.py:496` | MAX_JUDGE_FAILURE_SHARE | 0.1 |
| `services/orchestrator/scenarios/submit.py:31` | MAX_AGE_DAYS | 14 |
| `services/orchestrator/selftest.py:47` | MAX_FLIPS | 1 |
| `services/orchestrator/selftest.py:52` | MAX_PAIR_WRONG | 0 |
| `services/orchestrator/twophase.py:48` | MAX_ROUNDS | 3 |
| `services/rc_bridge/client.py:30` | MAX_WAIT_S | 30.0 |
| `services/rc_bridge/client.py:86` | _MAX_NAMES | 20 |
| `services/sitesetup/charts.py:40` | MAX_CHART_BYTES | 20971520 |
| `services/sitesetup/charts.py:41` | MAX_CHART_CHARS | 60000 |
| `services/vec/store.py:32` | MAX_HNSW_DIM | 4000 |
| `libs/tb_common/actor_v3.py:57` | MAX_LEN | 8192 |
| `libs/tb_common/audit.py:815` | DEFAULT_MAX_SKEW_S | 60.0 |
| `libs/tb_common/firstrun.py:36` | MAX_TRIES | 5 |
| `libs/tb_common/instruments.py:29` | MAX_REF | 200 |
| `libs/tb_common/labunit.py:156` | MAX_SCALE | 1000.0 |
| `libs/tb_common/notmatched.py:43` | NOTE_MAX | 300 |
| `libs/tb_common/notmatched.py:44` | RECORD_MAX | 80 |
| `libs/tb_common/opportunity.py:67` | MAX_COUNT | 10000000 |
| `libs/tb_common/opportunity.py:68` | MAX_ROWS | 2000 |
| `libs/tb_common/opportunity.py:69` | MAX_CONDITIONS | 50 |
| `libs/tb_common/opportunity.py:70` | MAX_CAP | 200 |
| `libs/tb_common/retention.py:47` | STUDY_YEARS_MAX | 30 |

## What this page did not verify

- No page of the EDC was rendered: the words of H35-02 and H35-03 come from the template's rule applied to the
  catalogue. The console's own refusal words (L10, L12, L14) come from the functions the problem page calls, not from
  a rendered page, except L04, L08 and L13, which were driven through the pages.
- Only the protocol upload was driven of the four 50 MB uploads.
- Nothing ran under compose, on a GPU, or with a real model; the gateway's token estimate was not driven.
- L19 to L35 were not driven (the table above says why).
