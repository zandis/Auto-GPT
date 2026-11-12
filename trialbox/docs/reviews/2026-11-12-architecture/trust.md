# Architecture review, seam `trust`: identity, authority and patient identifiers across service boundaries

Reviewed: master at `3259fb2f` (2026-11-12), worktree `/home/user/wt-arch-trust`, code under `trialbox/`.
Marks: **[RUN]** confirmed by running a throwaway test or script; **[READ]** confirmed by reading the code;
**[GUESS]** not verified. Paths are relative to `trialbox/`.

## 1. The seam as it is

### 1.1 Who calls whom, and what each side assumes

| Call | Caller sends | Callee verifies | Callee assumes |
| --- | --- | --- | --- |
| browser → console | session cookie, CSRF | session, role, `permit(role, action, standing)` with standing from the delegation log (`services/console/home.py:183-190`), break-glass grant (`breakglass.py:314`) | nothing: this is the only place a person's right is fully checked |
| console → orchestrator, 6 call sites (`backend.py:287,304,452,467,490`, `edc_pages.py:257`) | service token + `X-TB-Actor`, signed assertion v2 over name, session, expiry, nonce and, when sent, role and scope (`libs/tb_common/service_auth.py:247-311`) | token (`http.py:72-90`), MAC, expiry, one use (`service_auth.py:366-400`); then per route: role in `ID_ROLES` and study in scope (reveal, registry export; `app.py:197-212`), `role_allowed(role, type)` at best standing (jobs; `core.py:283-285`, `authz.py:206-209`), `edc_role_may(role, action)` (EDC; `edc_api.py:192-198`) | the console checked the study, the delegation log, the grant, the patient |
| console → orchestrator, every other changing route (study, data core, lifecycle, sponsor, site set-up, registry) | service token; the person as `by` in the JSON body or query | the token only | the caller is the console and `by` is true |
| mail gateway → orchestrator | service token; `requested_by` = the mail's sender in the body (`mail_gateway/intake.py:188`) | token; mailbox rules of settings (`core.py:286`) | the mail gateway authenticated the sender |
| orchestrator → lake, doc-parser, compiler, adapter, mail gateway, gateway | service token (gateway: also `X-TB-Caller`, bound to the token's service since D-437) | token and `CALLERS` (`service_auth.py:87-96`) | the orchestrator checked everything about the person; no person travels |
| any service → audit | `audit.append(event, ts, fields)` over its own database role | the role may execute the function; `session_user` recorded (`30-service-roles.sh:160-172`) | event name, `actor`, `ts` are true |
| any service → PostgreSQL | its role's password | role membership | a role is held by one service only |

Two callers of the same thing with different contracts:

- **The orchestrator's actor.** The reveal, export, notice, cancel, job and EDC routes take the person from a signed
  assertion. The other routers of the same app take it from the body. Both are reached with the same service token.
- **The study scope.** `_claim` verifies the scope header's MAC on every route it is used on (`app.py:165-176`), but
  only `_id_authority` compares it with the study of the request. The EDC router receives the same `_claim`
  (`app.py:636`) and never looks at the scope.
- **The break-glass grant.** The console checks a row (`breakglass.py:227-237`); the orchestrator checks a word
  (`breakglass` in `ID_ROLES`, `app.py:194`).

### 1.2 Matrix A: trust

| Service | Proof of the caller service | Proof of the person | Where the person's right is re-checked | Database role: schemas it OWNS (member of the owning group) | Secrets it can read |
| --- | --- | --- | --- | --- | --- |
| console | session cookie (users); no inbound service calls | its own sign-in (password, TOTP, OIDC) | everything, here: `permit`, delegation log, grant | `tb_console`: app, auth, breakglass, datacore, dataops, derived, edc, feedback, library, mpi, omop, optout, orch, pidmap, recall, refdata, sae, site, sitesetup, study, team, terminology, wf (23) | its token (= the actor signing key); every `TB_DB_PW_*` (see F1) |
| orchestrator | token; callers console, mail-gateway, operator, legacy | assertion on 6 route groups; body `by` elsewhere; none for mail jobs | role only (never standing, never the grant); study scope on reveal and export only | `tb_orchestrator`: 19 schemas incl. edc, pidmap, optout, mpi, orch, study | its token, actor verification keys, the whole `tb-secrets` volume (site key, pid map key, EDC sign key, audit sign key, object key, REDCap tokens); every `TB_DB_PW_*` |
| data core, EDC, site set-up | libraries inside the orchestrator process (`app.py:504-636`); also imported by the console (`dataops_page.py:85`, `instruments_page.py:35`) | as the orchestrator | EDC: role again in `EdcService`; data core, lifecycle: none | the host process's role | the host process's |
| mail gateway | token; callers orchestrator, console | none (mail sender checks are its own) | n/a | `tb_mail_gateway`: app, mail | its token, IMAP/SMTP passwords; every `TB_DB_PW_*`; the `objects-data` volume |
| gateway | token + `X-TB-Caller` bound to the token (D-437) | none | n/a (`serving_control`: orchestrator, operator) | `tb_gateway`: app, trace | its token, model key, cloud key; every `TB_DB_PW_*` |
| lake | token; callers orchestrator, criteria-compiler, adapter | none | none: any allowed caller reads any patient of the hospital | `tb_lake`: app, omop, refdata, terminology, vec | its token; every `TB_DB_PW_*` |
| criteria-compiler | token; caller orchestrator | none (`/approve` trusts the body) | none | `tb_criteria_compiler`: app, derived, library, omop, refdata, terminology | its token; every `TB_DB_PW_*`; `objects-data` |
| doc-parser | token; caller orchestrator | none | n/a | none of its own (`TB_DB_URL` empty) | its token; every `TB_DB_PW_*`; `objects-data` |
| adapter | token; callers orchestrator, console | none | n/a | `tb_adapter`: app, dataops, derived, mpi, omop, pidmap, refdata, sitesetup, terminology | its token; the whole `tb-secrets` volume, read-write (`docker-compose.yml:219`); every `TB_DB_PW_*` |
| audit writer | none (no HTTP) | none | n/a | `tb_audit_writer`: SELECT on `audit.journal` only | every `TB_DB_PW_*` |
| host tools (`trialbox`) | n/a | the operator's shell | n/a | member of every group, every service role and `audit_writer` | `deploy/.env`, every key |

"Owns" is literal: the service role is a member of `tbs_<schema>`, which owns the schema and every table in it
(`30-service-roles.sh:7-10,51-58,82`), and `tb_common.db` runs `SET ROLE` to it on connect (`db.py:302-306`). An owner
can drop a table, a trigger or a constraint.

### 1.3 Matrix B: blast radius

"Any container" below means any Python service container on `trialbox-net`, the doc-parser and the mail gateway
included, because of F1.

| What leaks | Chart numbers | Forge a person or a grant | EDC signatures, audit lines | Lift an opt-out | Start jobs, swap models | Another study |
| --- | --- | --- | --- | --- | --- | --- |
| **doc-parser container** (parses outside files) | plain `phi` workbooks on `objects-data` if the store is not sealed (F6); via F1: pid map rows (encrypted; no key) | via F1 as `tb_console`: insert a break-glass grant, a session, a delegation row | via F1 as `tb_orchestrator`: insert a version-1 EDC signature that verifies (F5); drop the EDC triggers; audit lines under another role's name | yes, via F1 (`optout` schema) | flags in `app.flag` without a `flag.set` event (F4); no jobs over HTTP (token refused) | yes, the database has no study boundary |
| **mail gateway token** (parses hostile mail) | no reveal (cannot sign). Chart number → pseudonym for any number: `POST /setup/pseudonym`, `POST /registry/{rs}` with `mrn` (F3) | any name in `by` on about 40 routes (F2) | lifecycle steps, form entries, study settings, SAE acknowledgement under any name; audit `actor` = that name | not over HTTP (the register is console-side) | `POST /jobs` as any mailbox of settings, or as `scheduler` with no check (F7); `POST /models/canary` | reads every job, output list, registry, study record (`protect_reads` is token-only) |
| **console token** (faces users) | every listed patient of every finished screening job: sign `breakglass` or `coordinator`, scope `*`, any name; rate limit per name, so a new name per call (`app.py:186-188`) | everything: any name, role, scope; `reauth-` session for an EDC signature | EDC signature as any investigator; all of the mail gateway column | yes, directly in `optout` | yes, any job type any role may start | yes |
| **`tb_console` password** | pid map rows only encrypted; `pid_alias` writable (merge two patients: F4) | grants, sessions, password hashes, delegation log | owns `edc`: drop triggers, insert v1 signature; audit lines as `tb_console` | yes | insert into `orch` | yes |
| **`tb_orchestrator` password** | as above | no `auth`, `breakglass`, `team` | owns `edc`; audit lines as `tb_orchestrator` (reveal, export, sign events) | yes | yes | yes |
| **adapter container** (parses hospital files) | all: pid map key and rows | via F1 | EDC sign key and audit sign key are on its secrets volume (F8) | via F1 | via F1 | yes |
| **gateway token / role** | no | no | trace store; audit lines as `tb_gateway` | no (via F1: yes) | swap only as an allowed service; flags (F4) | n/a |
| **lake / compiler token** | no; lake notes of every patient (pseudonymous, D3 text) | no | no | no | no | lake is hospital-wide |

## 2. Findings

### HIGH

**F1. Every service container holds every database role's password.** [RUN: compose files merged by script;
READ: install.sh]
`deploy/install.sh:241-246` writes `TB_DB_PW_LAKE` ... `TB_DB_PW_CONSOLE`, `TB_DB_PW_AUDIT_WRITER` into `deploy/.env`.
Every Python service has `env_file: [.env]` (`deploy/docker-compose.yml:30`). The secrets overlay clears
`POSTGRES_PASSWORD` and `POSTGRES_WF_PASSWORD` only (`deploy/docker-compose.secrets.yml:27-32`); its header says "the
database passwords in every TrialBox service" are cleared. Merging the two files shows that no service's `environment`
overrides any `TB_DB_PW_*` name. All services share `trialbox-net` with `db`.
Sequence: a hostile PDF gives code execution in the doc-parser; it reads `TB_DB_PW_CONSOLE` from its environment and
connects to `db:5432` as `tb_console`; it now owns 23 schemas. D-378's acceptance ("a service role cannot read
another service's schema") holds for the role and not for the container. `tests/unit/test_db_roles.py` tests the
roles on a cluster; no test looks at what a container's environment holds. Plan card T-212d ("secrets out of
`env_file`") names this and is not built. `llm-stub` (no-GPU boxes) is not in the overlay at all, so it also keeps
`POSTGRES_WF_PASSWORD`, the `trialbox` admin, which is the one member of `audit_writer`.

**F2. About 40 changing orchestrator routes take the acting person from the request body, with a production
token.** [RUN]
With `TB_ENV=PRODUCTION` and a service token, `PUT /studies/RS/settings` with only the token and
`"by": "dr_tanaka"` returns 200, stores `by=dr_tanaka` and writes the audit event `study.settings` with
`actor=dr_tanaka`. No `X-TB-Actor` is needed. The module docstring of `service_auth.py:3-6` says the callee takes the
actor "not from a body field"; that is true of 6 route groups.
Routes (all `[READ]`, one `[RUN]`): `study_api.py:383-490` (settings incl. `consent_scope`, screen scope, REDCap
connection and its API token, link, read); `datacore_api.py:201-407` (dictionary, data entry, sources, sync, sheet
import, conflict resolve, built-in forms, form entry, export with `by` defaulting to `"orchestrator"`);
`lifecycle_api.py:432-674` (subject refresh, step, undo, schedule, SAE rule, contact rule, deviation, SAE
acknowledgement, report); `sponsor_api.py:78-126`; `setup_api.py:240-393` (sheets, charts with a chart number, fact
decisions, code mapping, publish, remote help with `approved_by`); `app.py:677-692` (registry update and promote);
`app.py:260` (canary) and `app.py:643` take no person at all.
What the record ends up with: a subject enrolled, withdrawn or an SAE acknowledged under a name that never signed
in; the audit line is indistinguishable from a real one except for `journal.role`. The callers that can do this are
the console and the mail gateway (`CALLERS["orchestrator"]`); no route restricts which of the two.

**F3. A chart number becomes a pseudonym for any token holder, with no person and no audit.** [RUN]
`POST /setup/pseudonym {"chart_no": ...}` with only the token returns the pid (`setup_api.py:323-330`); so does
`POST /registry/{rs}` with `mrn` (`candidates.py:58-70`). The mail gateway's token is accepted. Chart numbers are
short and often sequential, so a loop over the number space rebuilds pid → chart number for the whole hospital
without the pid map, its key, the reveal cap or one `screen.reveal` event. The pseudonym is only as secret as this
route. (How fast the route answers under a loop: not measured.)

**F4. Stores are append-only against their own code, not against their writers.** [READ]
Every reader or writer of a schema is its owner (matrix A). So:
- `edc` trail tables: triggers made at run time by the service itself (`edc/store.py:249-268`); `tb_console` and
  `tb_orchestrator` can drop them. The code's own comment says so (`store.py:251-252`).
- `dataops.batch_step`: the same (`datacore/dataops.py:79-89`), owners `tb_adapter`, `tb_orchestrator`, `tb_console`.
- `pidmap.pid_alias` ("append-only", `adapter/pidmap.py:24-26`): no trigger. One inserted row makes two patients one
  for the opt-out filter (`tb_common/optout.py:97-113`) and for the next ingest; the console holds ownership of
  `pidmap` only to read this table.
- `breakglass.grants` and `uses`, the delegation log (`team`), the opt-out register, sponsor layouts, EDC `decision`,
  the recall ledger: convention only.
- `app.flag`: all seven roles own schema `app`. The gateway or the mail gateway can change a flag row without the
  `flag.set` audit event that `/ops/flags` writes. PR #262 puts a matching-behaviour switch behind a flag.
- `audit.journal` is the one store that is append-only in fact: owner `audit_writer`, no member but `trialbox`,
  triggers, `SECURITY DEFINER` insert (`30-service-roles.sh:106-181`).

**F5. The orchestrator gives chart numbers on a signed word, and the two audit sides cannot be joined.** [READ; the
acceptance is pinned by `tests/console/test_d280_breakglass.py:205-229`]
Known: `breakglass` is in `ID_ROLES`. What the seam adds: (a) the console signs the administrator's own scope
(`home.py:1088`, `scope_of(sess.user.studies)`), `*` for an account with no study list, so the scope check adds
nothing under a grant; (b) the orchestrator's `screen.reveal` event has no grant id, no reason, and the console's
`console.reveal_patient` has no orchestrator id (`app.py:416-422`, `home.py:1069-1085`); the only shared fields are
actor, pid and job, within a time window; (c) the grant's `uses` counter is written by the console before the call
(`breakglass.py:232-237`), so a reveal sent with the console token and no page leaves `uses = 0` and a steward
review list with nothing on it. The same holds for the EDC signature: "this person typed the password again" is the
prefix `reauth-` in the session field (`edc_api.py:160-171`), signed by the same key as everything else.

### MED

**F6. Chart numbers also live in job outputs on a volume five containers mount.** [READ]
SCREEN and NAV render chart numbers into the `phi` workbook (`scenarios/screen.py:682-684`, `nav.py:222`) and
publish it to `outputs/` on `objects-data`, mounted read-write by doc-parser, criteria-compiler, orchestrator, mail
gateway and console (`docker-compose.yml:176,196,264,281,328`). The object key (`objects.key`) is on `tb-secrets`,
which only the adapter and the orchestrator mount (`:219,:265`). So one of two things holds on a compose box, and I
did not determine which: the store is not sealed and the doc-parser can read every workbook; or it is sealed and the
console's `get_object` and the mail gateway's attachments fail closed (`tb_common/objstore.py:10-12`). Either way
the pid map is not the one place a chart number is kept.

**F7. A job with `requested_by: "scheduler"` skips authorisation.** [READ]
`core.py:60,282`: a sender in `SYSTEM_SENDERS` is not checked and not rate limited, and `requested_by` is a body
field of `POST /jobs` (`app.py:303-314`). The route accepts the mail gateway's token with no actor header.

**F8. One secrets volume for the adapter and the orchestrator.** [READ]
The adapter needs the site key and the pid map key. It also mounts, read-write, the EDC signature key, the audit
signing key, the object key and the REDCap tokens (`kek.py:69`, `docker-compose.yml:219`). The adapter parses
hospital exports.

**F9. The study scope and the standing do not reach the callee.** [RUN for EDC]
An assertion for a coordinator with scope `OTHER` sends REDCap data of study `RS`: `POST /studies/RS/edc/send/redcap`
returns 200 (`edc_api.py:192-198,295-298`). For jobs, the orchestrator checks the role at `BEST_STANDING`
(`authz.py:206-209`): an investigator who is not this study's PI passes for APPROVE; only the console's
`may_approve` stops it. The console does not sign a scope on job, cancel, notice or EDC calls
(`backend.py:287,304,467`, `edc_pages.py:257`).

**F10. The audit records who connected, and nothing checks it.** [READ]
`audit.append` stores `session_user`; the event name, `actor` and `ts` are the service's. `tb_mail_gateway` can
append `screen.reveal` with `actor=dr_tanaka` and a `ts` of last week. The chain line carries
`journal.role=tb_mail_gateway`, but no reader looks at it: not `tools/audit_verify.py`, not the console's audit
reader (`backend.py:190`); the only use of `journal` outside the writer is `datacore/dataops.py:147`. With F1 the
role itself is forgeable. Cross-service calls are audited on both sides for reveal and export only; for the F2
routes only the orchestrator writes an event, with the body's name.

### LOW

**F11. The replay guard and both rate limits are process memory** (`service_auth.py:279`, `app.py:337-361`);
already known (T-103, T-109b). The seam aspect: the reveal cap is keyed by caller and name, and the name is the
caller's to choose.

**F12. `legacy` and `operator` are accepted by every callee** (`service_auth.py:97`). A box that still lists a
legacy hash gives every container the console's signing ability (`actor_keys()` falls back to the shared token only
without a registry, so this needs the pre-step-8 state; not checked on a real box).

## 3. Answers to the five questions

1. **Checked once, then carried unverified.** Standing (PI, ticked tasks), the grant, the patient, the reason and
   the study are checked at the console only. Signed and verified at the callee: name, session, role (6 route
   groups), scope (2 routes). Routes taking the actor from a header and what they verify: `POST /jobs` (assertion,
   role; only when both headers are present, else mailbox), `POST /jobs/{id}/reveal` and
   `GET /registry/{rs}/export.xlsx` (assertion, role, scope, listed pid, opt-out, rate), `POST /notices` and
   `POST /jobs/{id}/cancel` (assertion, name only), the 10 changing EDC routes (assertion, role; `reauth-` for sign and
   unlock). Routes taking it from the body: F2. The data core and the EDC have no routes of their own; they are
   libraries in the orchestrator and, for `DataOps` and `SetupStore`, in the console.
2. **One place for pseudonym → chart number: no.** Code paths: `app.py:415` (reveal), `candidates.py:72-79,162`
   (registry export), `scenarios/screen.py:369-384,682` and `nav.py:222` (into workbooks), `scenarios/twpas.py:55-57`,
   `adapter/pipeline.py:85,115,581`, `adapter/backfill.py:202`, `adapter/cli.py:227`, `tools/keys.py:361`,
   `tools/trialbox/doctor.py:770`. Forward (chart → pid): `candidates.py:66-69`, `setup_api.py:323`, `case.py:184`,
   site set-up chart upload. Database roles that own `pidmap`: `tb_adapter`, `tb_orchestrator`, `tb_console`,
   `trialbox`. Key holders: adapter and orchestrator containers.
3. **Append-only in fact:** `audit.journal` only. By trigger that every writer can drop: `edc` trail tables,
   `dataops.batch_step`. By convention: the rest (F4).
4. **Audit:** yes, a service can write an event that names another service's event and any person; the database
   role is recorded and unread (F10). Both-sides audit with the same identity exists for reveal and export only,
   and even there without a shared id (F5).
5. **Fakes.**
   - `tests/console/test_console_app.py:91-264` `FakeBackend`: `reveal` returns a chart number for any role, scope
     and pid; it never refuses for role, scope, an unlisted pid, an opted-out patient or the rate. Console tests
     therefore cannot fail when the console sends the wrong role or scope; they record what was sent
     (`self.signed`).
   - Page tests mount the real routers on a bare `FastAPI()` (`tests/console/test_lifecycle_pages.py:51-63`,
     `test_edc_pages.py:41-58`): no `make_app`, so no token middleware and no token. The EDC page tests run the
     DEV fallback (`by` from the body), the path that is off in production; the lifecycle fake `study_api` has no
     `headers` parameter at all.
   - Per-service tokens with a registry and an actor-keys file, the production configuration, appear in 3 test
     files (`test_gateway_box_phi.py`, `test_gateway_verified_caller.py`, `test_edc_signing_t205.py`); the
     orchestrator route tests use one shared token, where every service can sign (`test_d273_orchestrator_guards.py:36`).
   - `test_d280_breakglass.py:228-229` asserts that the bare `breakglass` role gets a chart number: the test pins
     the weakness as the contract.
   - `test_db_roles.py` proves role separation on a cluster and never reads the compose environment (F1).

## 4. Architecture verdict

Three root causes; each is structural, not an accident of one file.

- **R1. The service token is the unit of trust, and the person is a note attached to it.** One middleware admits a
  caller service to every route of the callee; whether a route then asks for a person is each handler's choice.
  F2, F3, F7, F9, F12 follow. The assertion fixed six handlers; the design did not change. Structural.
- **R2. A right is a word the console says, not a fact the callee can see.** Role, scope, `breakglass`, `reauth-`
  are strings under one key held by the service that faces users. Grants, standing and re-authentication live in
  console-owned stores the orchestrator cannot read. F5, F9 and the unjoinable audit follow. Structural.
- **R3. Reach equals ownership, and secrets are shared by default.** One group role per schema is both owner and
  writer; one `.env` goes to every container; one secrets volume to two services; one objects volume to five. F1,
  F4, F6, F8, F10 follow. F1 alone is an implementation accident (a missing clear list) that cancels D-378 and
  weakens D-394; the owner-equals-writer part is the design of D-378.

## 5. Proposed change

The proposal in the brief is right in direction. What it takes in today's code, what breaks, and the order.

### Stage 0: make the merged cards true (before anything else)

**TR-1. Database passwords out of `env_file`.** Size S. Absorbs the "secrets out of `env_file`" clause of T-212d;
it is the condition for T-212c/D-378 and T-211b/D-394 to mean what they say.
- Goal: a container's environment holds its own database URL and no other role's password.
- Files: `deploy/docker-compose.secrets.yml` (clear every `TB_DB_PW_*`; add `llm-stub`), better
  `deploy/docker-compose.yml` (password as a compose secret file per role, URL built at start),
  `deploy/install.sh`, `tools/trialbox/svc_secrets.py` (rotation), `deploy/platform/base/apps.yaml`.
- Acceptance: a unit test merges the compose files as compose does and fails if any service's resolved environment
  contains a `TB_DB_PW_*`, `POSTGRES_*PASSWORD` or a URL with another role's name; `trialbox doctor` runs the same
  check against the running containers.
- Breaks: nothing at run time. Depends on: none.

**TR-2. Close the token-only doors.** Size S.
- Goal: the mail gateway's token reaches `POST /jobs`, `GET /jobs/{id}` and nothing else; `scheduler` and `system`
  are not accepted as `requested_by` from HTTP; `/setup/pseudonym` and registry-by-`mrn` need a verified person.
- Files: `libs/tb_common/service_auth.py` (`CALLERS` becomes callee → caller → route prefixes),
  `libs/tb_common/http.py`, `services/orchestrator/{app,core,setup_api}.py`.
- Acceptance: a test walks `app.routes` with the mail gateway's token in registry mode and gets 403 on every route
  but the two; `POST /jobs` with `requested_by=scheduler` is 403.
- Breaks: nothing known (the scheduler creates jobs in process). Depends on: none.

### Stage 1: one actor, on every route

**TR-3. Assertion v3 and one dependency.** Size L. Changes T-109b/D-447 (replay guard moves to a table, nonce is
the join id), T-103 (rate limit keyed on the verified person, in the store), T-205 (`reauth` becomes a signed
field with a time, not a session prefix); absorbs the `by` fields of T-102c's handlers.
- Goal: every changing route of the orchestrator takes the person from a verified assertion; `by` leaves every
  request body.
- Content of v3 (JSON, HMAC now, see TR-5 for the key): `sub`, `role`, `session`, `study` (exactly one, or none
  for box-wide actions), `standing` (`is_pi`, `tasks`), `action` (the `authz_matrix.yaml` row the console
  permitted), `target` (pid, job or record), `grant` (id, kind, pid or job, end), `reauth_at`, `body_sha256`,
  `nonce`, `exp`.
- One minting function in the console, `identity.assert_for(sess, action, rid, target)`, which calls `h.permit`
  and so cannot sign what the console would refuse; `sign_actor` is removed from every other import
  (`tests/unit/test_service_secrets.py` already scans clients; extend it).
- One FastAPI dependency `require_actor(action)` on the orchestrator's routers; it re-runs
  `permit(role, action, standing)` from the same matrix, checks `study` against the path, `body_sha256` against
  the body, and writes the nonce into every audit event of the request.
- Acceptance (the wrong thing impossible, not detected): a test walks `app.routes` and fails if a route with a
  method other than GET lacks the dependency or if any request model has a field named `by`, `signer`,
  `approved_by`; a second test sends each route a v3 assertion for another study and expects 403.
- Breaks: every console call through `backend.study_api` (many call sites, not counted, in `services/console/*_pages.py`,
  `team.py`, `study_setup.py`, `home.py`) must pass headers; console timers (N1, N2, REDCap 03:00, HEALTH notices)
  have no session and need a `service:console-timer` principal with its own short action list; CLI tools that post
  `by` (`tools/role_demo.py`, `tools/e2e_simple.py`, scenarios) must use the operator token and an operator
  principal; every page test that mounts a bare router (TR-7).
- Staging: (a) add the dependency in "report" mode that audits `actor.unsigned` and lets the call through; run the
  walk; (b) convert the console call sites router by router (lifecycle and sponsor first: they change subject
  state); (c) switch to refuse; (d) delete `by`. Depends on: TR-2.

**TR-4. The callee sees the grant.** Size M. Changes T-309/D-430 (the grant store gets a second reader, the use
is written by the callee) and T-103; pairs with PR #259.
- Goal: the orchestrator gives a chart number under break-glass only when it reads an open grant row that covers
  this person, this patient or job, now; it writes the use.
- Simplest form: the orchestrator gets SELECT on `breakglass.grants` and INSERT on `breakglass.uses` (after TR-6);
  `_id_authority` looks the grant id of the assertion up. `breakglass` leaves `ID_ROLES`; the assertion carries the
  account's real role plus the grant.
- Same pattern for standing: the orchestrator reads the delegation log (`team`) read-only and compares it with the
  signed `standing` on APPROVE, EDC sign and reveal.
- Acceptance: the test at `test_d280_breakglass.py:228` is inverted (a grant id with no open row is 403); a reveal
  with a valid grant for patient A and pid B is 403; `uses` has one row per chart number given, written by
  `tb_orchestrator`.
- Breaks: the console's `use()` no longer counts reveals (it keeps counting page views). Depends on: TR-3, TR-6.

### Stage 2: roles reduced to need, owners apart from writers

**TR-6. Owner, writer and reader roles per schema.** Size L. Reopens T-212c/D-378; absorbs the left-over of D-378
§"restore" and SEC-4 of D-281.
- Goal: no service role owns a table. `tbo_<schema>` (NOLOGIN, member: `trialbox` only) owns; `tbw_<schema>` has
  the table rights the writing service needs (INSERT and SELECT only on trail tables); `tbr_<schema>` has SELECT.
- What it takes: migrations stop running at service start. Today every store calls `Database.migrate` in its
  constructor as the service role (`pidmap.py:142`, `edc/store.py:247`, each store), and `tb_common.db` does
  `SET ROLE` to the owning group. A `trialbox migrate` step in `install.sh` and `update` runs them as `trialbox`;
  services start with `migrate(check_only=True)` and refuse an old schema. The EDC and data-ops triggers move into
  that step. `GRANT CREATE ON DATABASE` (`30-service-roles.sh:80`, for a re-run's scratch schema) stays or moves to
  a named scratch role.
- Need, from the code: `tb_console` needs `pidmap` only for `SELECT` on `pid_alias` (`optout.py:103-113`): reader.
  `edc`: orchestrator writer, console none (it goes over HTTP). `app.flag`: console writer, all others reader.
  `breakglass`, `team`: console writer, orchestrator reader (TR-4). `optout`: console writer, orchestrator reader
  (the worker's needs: check `datacore/optout_worker.py`, not read). `pidmap`: TR-8.
- Acceptance: `test_db_roles.py` gains, per sensitive schema, "the service role cannot DROP, ALTER, TRUNCATE,
  DISABLE TRIGGER, UPDATE or DELETE a trail table"; a test fails if a service role is a member of any `tbo_*`.
- Breaks: the test suite's `pglocal` cluster connects as `trialbox` and migrates on connect (keep for DEV/TEST);
  `rerun.py` scratch schemas; backup restore with `--no-owner` must re-run the role script (already noted in
  D-378). Staging: one schema at a time, in the order `app`, `pidmap`, `edc`, `breakglass`/`team`/`optout`, the rest.
  Depends on: TR-1.

**TR-5. The signing key leaves the service token; keys per purpose.** Size M. Changes T-212b/D-437's secret layout
and T-205.
- Goal: the console's token (sent on every call) is not the key that signs people; the EDC re-authentication is a
  separate key; the adapter mounts only its two keys.
- Files: `tools/trialbox/svc_secrets.py`, `deploy/docker-compose.secrets.yml`, `libs/tb_common/service_auth.py`
  (`actor_key`), `deploy/docker-compose.yml` (split `tb-secrets` into `tb-secrets-ident` and `tb-secrets-orch`).
  Optionally Ed25519 so that callees hold a public key only.
- Acceptance: `test_service_secrets.py` asserts which key file each service mounts; the adapter container cannot
  open `edc_sign.key` or `audit_sign.key`. Depends on: none; do with TR-3.

### Stage 3: one identifier service

**TR-8. `identifiers`: the one door between chart numbers and pseudonyms.** Size L (stage a: M). Changes
T-103/D-438 (the one reveal path becomes this module's `to_chart`), T-320a, T-681 (erasure and the per-patient
report call it), T-682 (workbooks).
- Stage a (module, in the orchestrator): `services/orchestrator/identifiers.py` with `to_pid(chart, actor)`,
  `to_chart(pids, actor, purpose, grant)`, `merge(...)`; it is the only importer of `PidMap`, `pid_for_mrn` and
  `site_hmac.key` outside the adapter's ingest. Rate limit and one audit event per call inside it. Acceptance: an
  import-lint test fails on `PidMap(` or `pid_for_mrn(` anywhere else in `services/orchestrator` and
  `services/console`; `/setup/pseudonym` and registry-by-`mrn` go through `to_pid` with a verified actor.
- Stage b (workbooks): the `phi` workbook is stored with pseudonyms; chart numbers are put in when the file is
  sent or downloaded, by `to_chart`, for the recipients of the study's list. Removes F6 and gives T-682 one place
  for the `flow.export` row. Breaks: `candidate_xlsx.render` callers, `rerun` byte-identity of the stored file
  (it gets better: the stored file no longer depends on the pid map).
- Stage c (own container and role): the service alone holds `pid_map.key`; role `tb_ident` is the only writer and
  reader of `pidmap`. The adapter keeps the site key for the forward hash (ingest volume) and writes map rows
  through a sealed-box public key, so it can add and not read. Not needed for the PoC; decide at G1.
- Depends on: TR-3 (actor), TR-6 (roles).

### Alongside

**TR-7. The boundary under test as it runs.** Size M. Changes T-315a (journeys), T-116.
- One fixture `orch_box` that serves the real orchestrator app through `make_app` with a token registry, an actor
  keys file and the mail gateway's and console's own tokens; `FakeBackend.reveal`, `registry_export`, `create_job`,
  `study_api` are replaced by it. A contract test compares, for each method a fake still has, the reply's shape
  and refusals with the real route (same statuses for wrong role, wrong study, opted out).
- Acceptance: with the fixture, removing `scope=` from `backend.reveal`'s call makes a console test fail (today it
  does not).

**TR-9. EDC version-1 signatures.** Size S. Part of T-115.
- At migration, record the ids and `content_sha` of the existing v1 rows in a list signed with the EDC key;
  `intact()` accepts a v1 row only if it is on that list (`edc/store.py:676-681`). After TR-6 the orchestrator has
  INSERT only, so the list cannot be extended.

**TR-10. The audit says who may say what.** Size S. Changes T-211b/D-394, feeds T-211c and T-681/T-682.
- The drain checks each journal row's event prefix against a table role → prefixes (`console.*` from `tb_console`;
  `screen.*`, `registry.*`, `edc.*`, `life.*`, `data.*` from `tb_orchestrator`; `llm.gateway.*` from
  `tb_gateway`; ...) and writes `audit.foreign_event` beside a row that breaks it; it refuses a `ts` more than a
  few minutes from the journal's `at`. Every event of a request carries the assertion nonce (TR-3), so the
  console's and the orchestrator's records of one act join on it. `tools/audit_verify.py` reports foreign events.
- T-681's per-patient report and T-682's ledger then rest on verified actors; today `data.export` and
  `life.report` rows carry `by` from the query string, default `"orchestrator"` (`datacore_api.py:407-425`,
  `lifecycle_api.py:674-681`).

### Order and effect on existing cards

Order: TR-1, TR-2 (days) → TR-7 fixture → TR-3 with TR-5 → TR-4, TR-9, TR-10 → TR-6 → TR-8.

| Card | Effect |
| --- | --- |
| T-212b / D-437 | stands; its pattern (bind the claim to the verified token) is what TR-2 and TR-3 extend to the orchestrator |
| T-212c / D-378 | merged but not effective until TR-1; reopened by TR-6 (owner ≠ writer) |
| T-212d | its `env_file` clause moves to wave 1 as TR-1 |
| T-103 / D-438 (PR #259) | not read (not on master). One reveal path in the console is necessary and not sufficient: the path must end in TR-8's `to_chart` and the limit must key on a verified person |
| T-109b / D-447 | replay guard and nonce kept; nonce becomes the audit join id; the guard moves to a table in TR-3 |
| T-309 / D-430 | the grant must be visible to the callee (TR-4); `breakglass` as a role word is removed |
| T-211b / D-394 | stands; needs TR-1 to be true and TR-10 to be used |
| T-115, T-205, EDC v1 | TR-9; `reauth` becomes a signed, timed field (TR-3), keyed apart (TR-5) |
| T-681, T-682 | depend on TR-3 and TR-10 for a trustworthy actor and on TR-8 for one place where a chart number leaves |

## 6. What I did not read

- `services/console/{auth,identity,team,oidc,totp}.py` beyond the reveal, permit and grant paths; the sign-in
  itself is outside this review.
- `services/gateway/{core,policy}.py` beyond the caller binding and `activate`; `services/lake/*`,
  `services/mail_gateway/*` beyond their route lists; `services/datacore/*` and `services/edc/service.py` bodies.
- `datacore/optout_worker.py` (which rights the orchestrator needs on `optout`).
- `tools/trialbox/svc_secrets.py` beyond its header; `deploy/platform/base/*` (the Kubernetes form may differ from
  compose in F1, F6, F8); the GPU and monitoring compose overlays.
- PR #259, PR #262, PR #275 and the scale review (not on master).
- No real box: F1 and F6 are read from the compose files and the install script, not from running containers.
- I never read `deploy/.env`, `secrets.env` or any key file.
