# TB-DR-02b User journeys of the non-clinical roles, hands-on, and authorisation

| Item | Value |
| --- | --- |
| Date | 2026-11-10 |
| Code read | `ca8f287` (origin/master, the deep-review branch) |
| Method | Ran the console locally without Docker and drove it over HTTP (Python `httpx`) and in Chromium (Playwright, deviceScaleFactor 1). Built a role × route matrix from the live router (228 routes enumerated from `create_app().routes`). Read the code behind every surprise. |
| What was run | `tools.role_demo` on port 18250 (accounts admin, crc, pi, smo, cra, viewer; one shared password); `tools.demo` (the image's default tool) on port 18251, three times; a separate in-process console with `TB_CONSOLE_MFA=totp` (TestClient) for the second-factor tests; 228 routes × 7 identities (anonymous + 6 roles) for GET, every POST/PUT/DELETE without CSRF, with a valid CSRF, and as bearer for `/api/v1`; IDOR on 4 other studies and on non-candidate pseudonyms; session, cookie, header, lockout and throttle probes; 150 screenshots in ja, zh-TW and en (desktop 1280 px and phone 390 px); memory and start-up timing. |
| What was not run | Docker build of `demo/Dockerfile` (no Docker here; the image's start command was reproduced with the same Python entry point and environment). Render and Cloud Run (no cloud spending). HTTPS through Caddy. OIDC/Authelia. Idle expiry was tested with a simulated clock, not by waiting. There is no steward, privacy-office, site-IT-without-PHI or monitor role in the code, so those journeys were walked with the closest existing account (crc for steward and privacy office, admin for site IT, cra for monitor). |
| Evidence folder | the reviewer scratch folder `scratchpad/02b-role/` (not in the repo) (`matrix_get.json`, `matrix_post_*.json`, `matrix.md`, `journeys.json`, `shots/`, the scripts) |

## 2. Summary

The console's basic web security is good: every form POST refuses a missing CSRF token (108 of 108), cookies are
HttpOnly and SameSite=Strict, the session token changes at sign-in, logout kills the session server-side, idle expiry
works for web and API sessions, and the headers (CSP with a hashed script, frame-ancestors none, no-store) are on every
response. The role model is the problem. The code has five roles; the URS has eight. There is no data steward, privacy
office, IT-only administrator or monitor; their work is spread over `admin` and `coordinator`, so an IT administrator
reveals chart numbers without break-glass and an external SMO coordinator can lift a hospital-wide opt-out. Two new
holes matter beyond the role model: **the JSON sign-in skips the second factor** and its token works as the web
cookie, and **the demo image does not start with its own defaults** and needs 3.6 times the memory its README says.

Counts: Blocker 2, Critical 1, High 9, Medium 9, Low 7 (28 findings; 4 of them registered already in whole or part: ROLE-006, -009, -010, -014).

Top 5:
1. ROLE-001 Blocker: `POST /api/v1/session` gives a full session with a password only when TOTP is on; the token
   works as the `tb_console` cookie (admin console without a second factor).
2. ROLE-002 Blocker: the demo image cannot start as built: `TB_CONSOLE_SECURE_COOKIE=1` (Dockerfile default) breaks the
   seeding sign-in; from a clean clone the CQL jars are missing and the first FEAS job fails.
3. ROLE-003 Critical: the default demo peaks at 1.87 GB and idles at 725 MB, starts in 154 s; the README says 250 MB
   and 30–70 s and points to a 512 MB free plan that also sleeps and wipes every account after 15 minutes.
4. ROLE-005 High: an SMO coordinator (external, study-scoped) reads the whole site's opt-out register and lifts an
   opt-out in one click, with no reason and no confirmation; so does any coordinator.
5. ROLE-008 High: any investigator account becomes PI of any study whose delegation log has no PI, and can write
   itself in as PI (done on RA-BIO with an account unrelated to the study).

## 3. Findings

`PoC path` = would a clinician (PI, sub-I, CRC) testing synthetic flows in the hosted demo hit it.

### 3.1 Identity, sessions, the hosted demo

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| ROLE-001 | Blocker | Second-factor bypass. `POST /api/v1/session` calls `users.authenticate()` and `new_session()` directly: with `TB_CONSOLE_MFA=totp` a password alone returns a bearer token. The token is the same kind as the web session, so setting it as the `tb_console` cookie opens `/ops/users` and `/admin`. It also clears the failure count (`clear_failures=True`), undoing the D-192 rule that a right password does not reset wrong-code failures. | By reading: `services/console/home.py:1008-1017`, `services/console/auth.py:450-469`. By a run (`scratchpad/02b-role/mfa_bypass.py`): web password → `303 /login/totp`, no cookie; API password → `200 {"token":…,"role":"admin"}`; token as cookie → `/ops/users 200`, `/admin 200`. | API sign-in must follow the same two-step flow: password → `mfa_pending` token; `POST /api/v1/session/totp` with the code → session. Mark sessions with `via` (web/api) and refuse an API token as a cookie. Keep `clear_failures=False` until the code passes. Test: with MFA on, the API returns no session for a password alone; an API token sent as the cookie is refused. | new | no (demo has MFA off; becomes yes once the hosted demo turns MFA on) |
| ROLE-002 | Blocker | The demo image does not start as built. (a) `demo/Dockerfile` sets `TB_CONSOLE_SECURE_COOKIE=1`; `tools.demo` seeds the box through an in-process `TestClient` on `http://testserver`, the Secure sign-in cookie is not sent back, and the CRC's seeding sign-in gets 400: the process exits. (b) From a clean clone, `.cache/jvm/cql-translator/lib` is absent (it comes from `make jvm-deps`, not named in `demo/README.md`), so the first pasted-protocol FEAS job fails with `FHIRHelpers-4.0.1.cql not found` and the process exits. Render (`render.yaml`) sets neither. | By a run: `TB_CONSOLE_SECURE_COOKIE=1 … python -m tools.demo` → `AssertionError: ('crc', 400)` at `tools/list_demo.py:110`. Without jars → `AssertionError: ('GOUT-COH', 'failed')` at `tools/list_demo.py:153`, traceback `criteria_compiler/compile_cql/translator.py:54`. With jars fetched to scratch and the cookie off: `e2e_simple PASSED in 148.1 s`, console answers at 154 s. `demo/Dockerfile` lines 10, 37; `.dockerignore` keeps `.cache/jvm/cql-translator`. | Seed with `TestClient(app, base_url="https://testserver")` (or seed through the stores, not HTTP). Make `demo/Dockerfile` fetch the CQL jars in a build stage (or fail the build when they are missing). Add a CI job that builds the demo image and waits for `/login` 200. Test: `docker run` with no `-e` answers on 8080. | new | yes |
| ROLE-003 | Critical | Memory and start-up are far above what the README and the hosting plan assume. Default tool (`tools.demo`): peak RSS 1,867 MB, steady 725 MB, first answer at 154 s. `tools.role_demo`: peak 591 MB, steady 444 MB + PostgreSQL 40 MB, 18 s. README: "about 250 MB", "about 30 seconds" / "about 70 s"; `render.yaml` uses `plan: free` (512 MB) and the Cloud Run line uses `--memory 1Gi`. Render's free plan sleeps after 15 minutes and every start rebuilds the data, so every tester's work and every added account is wiped each time the service sleeps. | By a run: `/proc/<pid>/status` VmHWM 1866804 kB, VmRSS 725232 kB (tools.demo); VmHWM 591448 kB, VmRSS 444048 kB (role_demo). `demo/README.md:19-23`, `../render.yaml:6`. | Host on a paid instance with ≥ 2 GB (tools.demo) or ≥ 1 GB (role_demo), min-instances 1, max-instances 1. Correct the README numbers. Add a persistent mode (ROLE-004). Test: a start-up budget check in CI (peak RSS and time to `/login` 200). | new | yes |
| ROLE-004 | High | No per-tester accounts and no persistence in the demo. All accounts share `TB_DEMO_PASSWORD`; the account list is hard-coded (`tools/feas_demo.py:46-52`, `tools/role_demo.py:277-284`); every start deletes the work dir; the demo passes a fixed env dict to `create_app`, so `TB_CONSOLE_MFA`, `TB_CONSOLE_IDLE_MINUTES` and the TLS settings from the container are ignored and `TB_ENV=DEV` turns TOTP off. No forced password change: a new account created by the admin lands on its home with the admin-issued password (registered CR-033/CR-034). | By reading as cited, `tools/list_demo.py:90-98`. By a run: admin created `tester.makoto` and `tester.wenn` in ja in 2 clicks (`shots/admin_ja_create_user_result.jpg`); `tester.makoto` signed in and landed on `/home` with no change prompt (`shots/newuser_first_login.jpg`). | A demo accounts file (`TB_DEMO_ACCOUNTS`: user, role, language, studies, end date) seeded only when the account store is empty; a persistent volume (`TB_DEMO_DIR` on a disk) with `--keep` instead of `--fresh`; a reset command for the owner; pass `TB_CONSOLE_*` through from the environment; TOTP on in the hosted demo; forced change at first sign-in (T-109). Test: restart keeps `tester.makoto`; his first sign-in asks for a new password and enrols TOTP; his session shows ja by default. | new (forced change: registered CR-033, CR-034) | yes |
| ROLE-005 | High | Opt-out register: who may keep it is `role in ("coordinator","admin")` (`can_keep`), so an SMO coordinator (affiliation smo, scoped to GZQO, external) sees every opted-out pseudonym of the site with source and recorder, adds opt-outs, and lifts any opt-out ("Patient takes it back") in one click, with no reason, no confirmation and no second person. The same lift is one click for every hospital coordinator. | By a run: `smo` `GET /site/opt-outs` 200 listing the site register; `smo` POST lift → `303 /site/opt-outs?done=lifted`; the register's history shows `smo · taken back`. Code `services/console/team.py:551-554`, `641-651`. | Make opt-out keeping a privacy-office/steward right only (T-102); a lift needs a written reason, the source document reference, a confirmation sheet and is listed in the steward's weekly review; never for affiliation smo/cro. Test: smo gets 403 on GET and POST `/site/opt-outs`; a lift without reason is refused. | new | yes (a CRC can lift without confirmation) |
| ROLE-006 | Low | No per-IP throttle on sign-in: 30 wrong sign-ins in 4.85 s all answered 401; anyone who can reach the demo can lock `admin` for 15 minutes. Lockout itself is per account and does not reveal whether an account exists (an unknown name locks the same way). | By a run: 30 POST `/api/v1/session` in 4.85 s, all 401; `viewer` locked after 6 mixed web/API failures. | Per-IP backoff and a captcha-free delay; admin unlock by CLI is documented. | registered CR-116 | yes (public demo) |
| ROLE-007 | Low | `GET /healthz` without sign-in returns the environment and the database schema name (`"db:w6f7b4c10a3_auth"`). | By a run. | Return only `{"status":"ok"}` to unauthenticated callers. | new | no |

### 3.2 Roles and authorisation

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| ROLE-008 | High | Delegation bootstrap fails open: while a study's log names no PI, every investigator account on the site acts as its PI ("every investigator of this study acts as its PI until the PI adds themselves") and may add itself as PI. Any doctor account can claim any study that has no PI on its log. | By a run: `pi` POST `/studies/RA-BIO/team` role=pi → `303 ?done=add`; RA-BIO is not one of `pi`'s studies. Page text in ja/zh-TW states the rule (`shots/pi_ja_studies_GZQO_team.jpg`). Code `services/console/team.py:444-451`. | The first PI entry of a study is written by the study set-up (steward or trial office) from the signed log, not by the investigator; until then investigators have no study rights. Test: an investigator with no log entry gets 403 on the study's candidate list and on `POST /team`. | new | yes |
| ROLE-009 | High | The role model has five roles (`admin, coordinator, investigator, viewer, cro`). There is no data steward, privacy office, IT-only administrator, sub-investigator role or monitor; their URS rights (§5.1, §5.6–5.8) are spread over admin and coordinator. | `services/console/auth.py:32-33`. The role list on `/ops/users`. | T-102 (steward, one permission function, admin without PHI); add `privacy` and `monitor` roles to the same matrix. | registered CR-024 (card T-102 covers) | no |
| ROLE-010 | High | Admin sees and exports PHI with no break-glass: reveals a chart number (`Chart number: 10000294`), opens any candidate with a purpose, downloads the registry workbook with every MRN, downloads candidate JSON from job pages, confirms site facts, flips a study's EDC prefill switch, sets IRB dates. | By a run: admin POST `/studies/GZQO/patients/{pid}/reveal` reason=other → 200 with the MRN; `/pilot/registry/GZQO/export.xlsx` 11 rows, header `MRN, pid, …`; POST `/studies/GZQO/edc/switch` → `303 ?done=switch`; POST `/site/facts/1` → 303. | T-102 and T-309: admin loses `can_view_phi`; break-glass with a second person and 24 h expiry; EDC switch for PI only. | registered CR-023, CR-029, CR-020 | no |
| ROLE-011 | High | CRO accounts see every study by default. `sees_study()` returns True when `studies` is empty and `/ops/users` creates a CRO account with "all studies" unless the admin types them; a sponsor's CRO reads the feasibility reports of other sponsors' studies. The same default applies to SMO. | By a run: `cra` GET `/studies/RA-BIO|GOUT-COH|ONC-OSI|RA-COH/feasibility` → 200 each. `services/console/auth.py:216-217`. | Require a non-empty study list for affiliation cro or smo (refuse create/save without it). Test: creating a CRO account with no study is refused; an existing one with none sees no report. | new | no |
| ROLE-012 | High | Monitor (CRA) has no source-data verification: the `cro` role is the sponsor's feasibility reader (reports and the sponsor pack only) and is refused every subject, EDC trail and visit page. URS-CRA-01..03 have no page. | Matrix: cra 403 on `/studies/GZQO/subjects`, `/edc/trail/*`, `/visits`; 200 only on `/reports`, `/studies/*/feasibility`, sponsor-pack of a FEAS job. | T-303 (monitor SDV): a `monitor` role bound to one study, enrolled subjects only, CRF value → cited record, audit trail per record. | card T-303 covers | no |
| ROLE-013 | High | Audit viewing does not serve a privacy office: `/audit` is open to every signed-in role the scope guard does not block (admin, crc, pi see the whole site's events: every login, reveal, denial, export); it shows only the newest 1,000 events (50 × 20 pages; the demo held 1,123 on its first day), with no filter by patient, actor, event or date, no "who read which chart" report, no chain verification and no export; event names and details are raw codes (`console.reveal_patient`, `role=admin`) in ja and zh-TW; on a phone only time and event are visible. | By a run: crc `/audit` 200; raw file 1,123 lines; `shots/admin_zh-TW_390_audit.jpg`. Code `services/console/app.py:79,882-892`. | T-211 audit browser: privacy/steward roles only; filters; per-patient report; verify button calling `tools/audit_verify.py`; translated event labels; CSV export audited. Test: crc 403; privacy officer finds every reveal of one pseudonym in two steps. | card T-211 covers (access by crc/pi: new) | no |
| ROLE-014 | High | Privacy-office requests have no feature: no access/disclosure request (APPI 開示, PDPA 查詢), no erasure request, no disclosure log of what left the box per patient. Only the opt-out register exists; and an opted-out patient still shows on the registry page and the screening job page. | By a run: after recording an opt-out, the pseudonym is still in `/pilot/registry/GZQO` and `/pilot/jobs/{SCREEN}` for admin, pi and smo (not in week, candidates, excluded, screening log). No route matches access, erasure or disclosure in the 228. | A privacy-office page: request log (type, received, due date per law, outcome), a per-patient "what TrialBox holds and where it went" report from the flow ledger (WS-08.3), erasure through the opt-out worker (T-206). | opt-out leak: registered CR-019; requests: new | no |
| ROLE-015 | Medium | SMO and admin may set a study's IRB approval and ICF dates; saving a date silences the IRB warning; no evidence reference, no reason, and the API accepts a partial body. | By a run: smo `POST /api/v1/studies/GZQO/irb {"approved_on":"2026-01-01"}` → 200, warning `irb_missing` gone. `services/console/team.py:515-527`. | Restrict to PI and trial office; require approval number and document reference; reason for change; audit old and new values. | new | no |
| ROLE-016 | Medium | Reveal reasons: "other (study work)" passes with no written text; purpose prompts are a closed list. Weak for the "why" in the who-read-which-chart record. | By a run: reveal with `reason=other` → 200; audit detail `reason=other`. | "Other" requires a free-text reason (≥ 10 characters) stored in the audit. Part of T-103. | card T-103 covers | yes |
| ROLE-017 | Medium | Page and API disagree: the PI is refused `/studies/GZQO/screening-log.xlsx` (403) but gets `/api/v1/studies/GZQO/screening-log` (200); the viewer gets research-office counts (page and XLSX) that the PI is refused. | Matrix rows `screening-log.xlsx`, `api/v1/…/screening-log`, `reports/research-office(.xlsx)`. | One permission function (T-102) decides both; add the pair to the walk's 403 matrix. | card T-102 covers | yes |
| ROLE-018 | Medium | Role descriptions on `/ops/users` are wrong: "viewer: read jobs, aggregate results and the audit trail" (viewer gets 403 on `/jobs` and `/audit`); "administrator: everything" (contradicts URS-ADM-01). The SMO's menu lists Runs, Cascade and Audit trail, which answer 403. | By a run, `/ops/users` text; matrix. | Generate the descriptions and the menu from the permission table. | new | no |
| ROLE-019 | Low | The JSON API validates the body before it checks the session: anonymous POSTs get 422 with the schema error instead of 401. | Matrix (nocsrf run): 26 `/api/v1` POST/PUT answer 422 to anonymous. | Read the bearer token in a dependency that runs before body validation. | new | no |
| ROLE-020 | Low | A study-scoped account asking another study through `/api/v1/site/*?study=X` silently gets its own study's data (`"study":"GZQO"` for `study=RA-BIO`). Safe, but confusing; a 404 is clearer. | By a run. | Return 404 for a study outside the scope. | new | no |

Checked and holding (no finding): SMO's study scope on `/studies/*`, `/pilot/jobs/*`, `/pilot/registry/*` (404 for the four
other studies); a non-candidate pseudonym under `/studies/GZQO/patients|candidates/{pid}` is 404 after the purpose step
(no record shown); CRA and viewer are refused every patient-level page and API; admin is refused EDC data entry.

### 3.3 Missing screens for the non-clinical roles

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| ROLE-021 | Medium | `/ops/identity` (unlock, enrolment code, TOTP reset) and `/ops/flags` are orphan pages: no link on `/admin`, `/ops/users`, the header or any menu. An admin who does not know the URL cannot unlock a locked colleague. | By a run: none of `/admin`, `/ops/users`, `/home`, `/` contains `/ops/identity`; grep shows no template link to either page. | Links from `/admin` (Accounts tile) and from each row of `/ops/users`. | new | no |
| ROLE-022 | Medium | Site administrator has no backup, update, disk, audit-chain or ingest-history screen; `/admin` says "GPU, disk, backup and audit-chain tiles come with the hospital installation". The steward has no data-quality-per-source page; "Ingest synthetic site A" is a button with no history. | By a run, `shots/admin_ja_admin.jpg`. | T-209 (admin screens) and T-112 (data-operations console). | card T-209, T-112 cover | no |

### 3.4 Wording, error and empty states (ja, zh-TW)

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| ROLE-023 | Medium | zh-TW: the opt-out register is titled 「退出登錄」 and the action 「登錄退出」; both read as "log out" next to the 「登出」 button. The lift button 「病人撤回」 ("patient withdraws") reads as a study withdrawal. | `shots/crc_zh-TW_site_opt-outs.jpg`. | 「拒絕研究使用登記」/「登記拒絕」; lift: 「取消拒絕（病人改變意願）」. Have a CGMH research-office reader confirm. | new | yes |
| ROLE-024 | Medium | The opt-out table's first column header is the form's second label: 「或假名代碼」 / 「または仮名ID」 / "or pseudonym". | Same screenshot; ja and en the same. | Header 「假名代碼」/「仮名ID」/"Pseudonym". | new | yes |
| ROLE-025 | Medium | Creating an account whose name is taken gives a generic refusal (ja 「拒否されました：この依頼は実行できませんでした。続く場合は管理者に連絡してください」) to the administrator. | `shots/admin_ja_create_user_duplicate_error.jpg`. | Say "this user name is taken" in the form, keep the typed values. | new | no |
| ROLE-026 | Low | Untranslated pieces: 「第二要素：off」/「第二因子：off」, the flag history reason "seeded at the first start from the default", the demo health detail "in process, no outside mail", "encounter in the last" on the feasibility page; flag times in UTC ISO while the rest is site time. | `journeys.json` (leftover-English scan over 150 pages; these are the only hits outside user-typed notes). | Translate; use the `local` filter on flag times. | new | yes (feasibility line) |
| ROLE-027 | Low | ja 「委任リスト」 and zh-TW mixed 「研究協調員」/「研究護理師／CRC」 for the same role. The JP GCP document is 「治験分担医師・治験協力者リスト」 (WS-06.2 names it). | `shots/pi_ja_studies_GZQO_team.jpg`, `/ops/users` zh-TW. | Use the site's term per country; one term per role. | new | yes |
| ROLE-028 | Low | README and docs disagree with the image: the default tool has accounts admin, crc, pi, subpi, cra, viewer (no smo); README lists smo and 30 s. Demo logs label orchestrator and console lines `"service":"llm-stub"`. | By a run (`/ops/identity` on 18251), `demo/README.md:3-5`, `scratchpad/02b-role/roledemo.log`. | Correct README; set the service name per logger. | new | no |

Error and denied states that are good: the 403 page in ja and zh-TW says the role cannot open the page, whom to ask, and offers
home/back/help; the 404 says "not one of yours"; the lockout message gives the minutes left and the time.

### 3.5 Clicks per task (measured in the run)

| Role | Task | Clicks | Note |
| --- | --- | --- | --- |
| Site admin | Create an account, read the one-time password | 2 (+ typing) | Good: the password is read out in 4-letter groups. |
| Site admin | Unlock a locked account / issue an enrolment code | URL typed + 1 | ROLE-021 |
| Site admin | Turn a flag | URL typed + 2 (value, reason, confirm) | ROLE-021 |
| Privacy (as crc) | Record an opt-out | 2 (More → Opt-out register) + typing + 1 | |
| Privacy (as crc) | Lift an opt-out | 1, no confirmation | ROLE-005 |
| Privacy | Find who saw one patient's chart number | not possible in the console beyond 1,000 events; no filter | ROLE-013 |
| PI | Add a delegate | 2 (study nav → Delegation log) + form + 1 | ROLE-008 |
| Any PHI role | Reveal a chart number | 2 (reason, button) | ROLE-016 |
| CRA | Open a feasibility report / sponsor pack | 1 / 2 | |

## 4. Role × route matrix (run on `tools.role_demo`, 2026-11-10)

Legend: `Y` = allowed (200 or a redirect inside the console); `y4xx` = authorisation passed, the empty test body was
refused (400/409/410/422), so the role **is allowed**; `-` = 403; `n` = 404; `L` = sent to sign-in. Path parameters:
`rs=GZQO`, a real candidate pid, the SCREEN job, record/event `1`. POST rows were sent with the role's valid CSRF
token (API rows with its bearer token and `{}`). Anonymous: every non-public route answered `303 /login` or 401 (not
shown). Without a CSRF token every form POST was refused (400) for every role. Rows in **bold** below the table are the
deviations from SECURITY.md §3 and the URS.

| Method | Route | admin | crc | pi | smo | cra | viewer |
|---|---|---|---|---|---|---|---|
| GET | `/ops/identity` | Y | - | - | - | - | - |
| GET | `/` | Y | Y | Y | Y | Y | Y |
| GET | `/jobs` | Y | Y | Y | - | - | - |
| GET | `/audit` | Y | Y | Y | - | - | - |
| GET | `/ops/users` | Y | - | - | - | - | - |
| GET | `/home` | Y | Y | Y | Y | Y | Y |
| GET | `/reports` | Y | Y | Y | Y | Y | Y |
| GET | `/week` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/feasibility` | Y | Y | Y | Y | Y | Y |
| GET | `/studies/{rs}/week` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/excluded` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/patients/{pid}` | Y | Y | Y | Y | - | - |
| GET | `/api/v1/studies` | Y | Y | Y | Y | Y | Y |
| GET | `/api/v1/studies/{rs}/patients` | Y | Y | Y | Y | - | - |
| GET | `/api/v1/studies/{rs}/screening-log` | Y | Y | Y | Y | - | - |
| GET | `/pilot/jobs/{job_id}/approval` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/screening-log` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/screening-log.xlsx` | Y | Y | - | Y | - | - |
| GET | `/studies/{rs}/cohort` | Y | Y | Y | Y | - | - |
| GET | `/reports/research-office` | Y | Y | - | Y | - | Y |
| GET | `/reports/research-office.xlsx` | Y | Y | - | Y | - | Y |
| GET | `/settings/notices` | Y | Y | Y | Y | - | Y |
| GET | `/studies/{rs}/setup` | Y | Y | Y | Y | - | - |
| GET | `/admin/redcap` | Y | - | - | - | - | - |
| GET | `/studies/{rs}/sources` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/conflicts` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/forms` | Y | Y | Y | Y | - | - |
| GET | `/api/v1/studies/{rs}/sources` | Y | Y | Y | Y | - | - |
| GET | `/api/v1/studies/{rs}/conflicts` | Y | Y | Y | Y | - | - |
| GET | `/api/v1/studies/{rs}/forms` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/entry` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/entry/{form}.css` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/history` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/export.{fmt}` | Y | Y | Y | Y | - | - |
| GET | `/api/v1/studies/{rs}/records` | Y | Y | Y | Y | - | - |
| GET | `/api/v1/studies/{rs}/records/{record}` | y400 | y400 | y400 | y400 | - | - |
| GET | `/api/v1/studies/{rs}/export/{fmt}` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/subjects` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/subjects/{record}` | n | n | n | n | - | - |
| GET | `/studies/{rs}/visits` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/schedule` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/enrolment` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/enrolment.{fmt}` | Y | Y | Y | Y | - | - |
| GET | `/api/v1/studies/{rs}/subjects` | Y | Y | Y | Y | - | - |
| GET | `/api/v1/studies/{rs}/subjects/{record}` | n | n | n | n | - | - |
| GET | `/api/v1/studies/{rs}/visits` | Y | Y | Y | Y | - | - |
| GET | `/api/v1/studies/{rs}/schedule` | Y | Y | Y | Y | - | - |
| GET | `/api/v1/studies/{rs}/enrolment` | Y | Y | Y | Y | - | - |
| GET | `/api/v1/studies/{rs}/enrolment/{fmt}` | Y | Y | Y | Y | - | - |
| GET | `/site` | Y | Y | Y | Y | - | - |
| GET | `/site/start` | Y | Y | Y | Y | - | - |
| GET | `/site/charts` | Y | Y | Y | Y | - | - |
| GET | `/site/facts` | Y | Y | Y | Y | - | - |
| GET | `/site/codes` | Y | Y | Y | Y | - | - |
| GET | `/site/checks` | Y | Y | Y | Y | - | - |
| GET | `/site/sheets` | Y | Y | Y | Y | - | - |
| GET | `/site/people` | Y | Y | Y | Y | - | - |
| GET | `/site/patients` | Y | Y | Y | Y | - | - |
| GET | `/site/help` | Y | Y | Y | Y | - | - |
| GET | `/site/templates/{name}.xlsx` | n | n | n | n | - | - |
| GET | `/ask` | Y | Y | Y | Y | Y | Y |
| GET | `/api/v1/site/readiness` | y400 | y400 | y400 | Y | - | - |
| GET | `/api/v1/site/facts` | Y | Y | Y | Y | - | - |
| GET | `/api/v1/site/codes` | Y | Y | Y | Y | - | - |
| GET | `/api/v1/site/checks` | Y | Y | Y | Y | - | - |
| GET | `/api/v1/ask` | Y | Y | Y | Y | - | Y |
| GET | `/cmd` | Y | Y | Y | Y | Y | Y |
| GET | `/account` | Y | Y | Y | Y | Y | Y |
| GET | `/help` | Y | Y | Y | Y | Y | Y |
| GET | `/notices/received` | Y | Y | Y | Y | - | Y |
| GET | `/admin` | Y | - | - | - | - | - |
| GET | `/admin/notice` | Y | - | - | - | - | - |
| GET | `/studies/{rs}/candidates` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/candidates/{pid}` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/referrals` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/team` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/irb` | Y | Y | Y | Y | - | - |
| GET | `/site/staff` | Y | Y | Y | Y | - | - |
| GET | `/site/opt-outs` | Y | Y | - | Y | - | - |
| GET | `/api/v1/studies/{rs}/delegation` | Y | Y | Y | Y | - | - |
| GET | `/api/v1/studies/{rs}/candidates` | Y | Y | Y | Y | - | - |
| GET | `/api/v1/studies/{rs}/candidates/{pid}` | y400 | y400 | y400 | y400 | - | - |
| GET | `/api/v1/studies/{rs}/referrals` | Y | Y | Y | Y | - | - |
| GET | `/api/v1/studies/{rs}/irb` | Y | Y | Y | Y | - | - |
| GET | `/api/v1/site/opt-outs` | Y | Y | - | Y | - | - |
| GET | `/ops/flags` | Y | - | - | - | - | - |
| GET | `/studies/{rs}/edc` | - | Y | Y | Y | - | - |
| GET | `/studies/{rs}/edc/export.odm.xml` | - | y409 | - | y409 | - | - |
| GET | `/studies/{rs}/edc/map` | - | Y | - | Y | - | - |
| GET | `/studies/{rs}/edc/review/{record}` | - | n | - | n | - | - |
| GET | `/studies/{rs}/edc/trail/{record}` | - | n | n | n | - | - |
| GET | `/api/v1/studies/{rs}/edc` | - | Y | Y | Y | - | - |
| GET | `/api/v1/studies/{rs}/edc/map` | - | Y | - | Y | - | - |
| GET | `/api/v1/studies/{rs}/edc/drafts` | - | y400 | - | y400 | - | - |
| GET | `/api/v1/studies/{rs}/edc/export/odm` | - | y409 | - | y409 | - | - |
| GET | `/api/v1/studies/{rs}/edc/trail/{record}` | - | n | n | n | - | - |
| GET | `/sae` | Y | Y | Y | Y | - | - |
| GET | `/studies/{rs}/sae/{record}/{event}` | n | n | n | n | - | - |
| GET | `/pilot/jobs/{job_id}/view/{filename}` | n | n | n | n | - | - |
| GET | `/pilot/jobs/{job_id}` | Y | Y | Y | Y | - | - |
| GET | `/pilot/jobs/{job_id}/files/{filename}` | Y | Y | Y | Y | - | - |
| GET | `/pilot/request` | Y | Y | Y | Y | - | Y |
| GET | `/pilot/protocol` | Y | Y | Y | Y | - | Y |
| GET | `/pilot/consent` | Y | Y | Y | Y | - | Y |
| GET | `/pilot/case` | Y | Y | Y | Y | - | Y |
| GET | `/pilot/registry` | Y | Y | Y | Y | - | - |
| GET | `/pilot/registry/{ruleset}` | Y | Y | Y | Y | - | - |
| GET | `/pilot/jobs/{job_id}/sponsor-pack.zip` | n | n | - | n | - | - |
| GET | `/pilot/registry/{ruleset}/export.xlsx` | Y | Y | Y | Y | - | - |
| GET | `/pilot/cascade` | Y | Y | Y | - | - | - |
| GET | `/pilot/cascade/{run_id}` | n | n | n | - | - | - |
| GET | `/pilot/cascade/{run_id}/files/{name}` | n | n | n | - | - | - |
| GET | `/pilot/mailbox` | n | n | n | - | - | - |
| POST | `/ops/identity` | y400 | - | - | - | - | - |
| POST | `/ops/ingest` | Y | - | - | - | - | - |
| POST | `/ops/users` | y400 | - | - | - | - | - |
| POST | `/studies/{rs}/feasibility/refresh` | Y | Y | - | Y | - | - |
| POST | `/studies/{rs}/profile` | Y | Y | - | Y | - | - |
| POST | `/studies/{rs}/excluded/{pid}/review` | n | n | n | n | - | - |
| POST | `/studies/{rs}/patients/{pid}/reveal` | y400 | y400 | y400 | y400 | - | - |
| POST | `/studies/{rs}/patients/{pid}/mark` | - | - | y400 | - | - | - |
| POST | `/studies/{rs}/patients/{pid}/outcome` | y400 | y400 | - | y400 | - | - |
| POST | `/api/v1/studies/{rs}/patients/{pid}/mark` | y422 | y422 | y422 | y422 | y422 | y422 |
| POST | `/api/v1/studies/{rs}/patients/{pid}/outcome` | y422 | y422 | y422 | y422 | y422 | y422 |
| POST | `/api/v1/studies/{rs}/patients/{pid}/reveal` | y400 | y400 | y400 | y400 | - | - |
| POST | `/pilot/jobs/{job_id}/approval/tick` | - | - | y409 | - | - | - |
| POST | `/pilot/jobs/{job_id}/approval/label` | y400 | y400 | y400 | y400 | - | - |
| POST | `/pilot/jobs/{job_id}/approve` | - | - | y409 | - | - | - |
| POST | `/settings/notices` | Y | Y | Y | Y | - | Y |
| POST | `/ops/notices` | Y | - | - | - | - | - |
| POST | `/studies/{rs}/setup/study` | - | Y | - | Y | - | - |
| POST | `/studies/{rs}/setup/log` | - | Y | - | Y | - | - |
| POST | `/studies/{rs}/setup/scope` | - | y400 | - | y400 | - | - |
| POST | `/studies/{rs}/setup` | - | Y | - | Y | - | - |
| POST | `/studies/{rs}/setup/redcap` | - | Y | - | Y | - | - |
| POST | `/studies/{rs}/setup/redcap/test` | Y | Y | - | Y | - | - |
| POST | `/studies/{rs}/redcap-read` | Y | Y | - | Y | - | - |
| POST | `/admin/redcap` | Y | - | - | - | - | - |
| POST | `/admin/redcap/{ref}/test` | Y | - | - | - | - | - |
| POST | `/studies/{rs}/sources/redcap` | - | Y | - | Y | - | - |
| POST | `/studies/{rs}/sources/redcap/detach` | - | Y | - | Y | - | - |
| POST | `/studies/{rs}/sources/{name}/sync` | - | n | - | n | - | - |
| POST | `/studies/{rs}/conflicts/{cid}` | - | y400 | - | y400 | - | - |
| POST | `/studies/{rs}/forms/dictionary` | - | Y | - | Y | - | - |
| PUT | `/api/v1/studies/{rs}/sources/redcap` | y422 | y422 | y422 | y422 | y422 | y422 |
| DELETE | `/api/v1/studies/{rs}/sources/redcap` | - | Y | - | Y | - | - |
| POST | `/api/v1/studies/{rs}/sources/{name}/sync` | - | n | - | n | - | - |
| POST | `/api/v1/studies/{rs}/conflicts/{cid}` | y422 | y422 | y422 | y422 | y422 | y422 |
| POST | `/api/v1/studies/{rs}/forms/dictionary` | y422 | y422 | y422 | y422 | y422 | y422 |
| POST | `/studies/{rs}/entry` | - | Y | - | Y | - | - |
| POST | `/studies/{rs}/forms/builtin` | - | Y | - | Y | - | - |
| POST | `/api/v1/studies/{rs}/forms/builtin` | - | Y | - | Y | - | - |
| PUT | `/api/v1/studies/{rs}/records/{record}/forms/{form}` | y422 | y422 | y422 | y422 | y422 | y422 |
| POST | `/studies/{rs}/subjects/{record}/step` | - | n | - | n | - | - |
| POST | `/studies/{rs}/subjects/{record}/undo` | - | n | - | n | - | - |
| POST | `/studies/{rs}/subjects/{record}/aes/{event}/ack` | - | - | n | - | - | - |
| POST | `/studies/{rs}/schedule` | - | Y | - | Y | - | - |
| POST | `/api/v1/studies/{rs}/subjects/{record}/step` | y422 | y422 | y422 | y422 | y422 | y422 |
| POST | `/api/v1/studies/{rs}/aes/{record}/{event}/ack` | - | - | n | - | - | - |
| PUT | `/api/v1/studies/{rs}/schedule` | y422 | y422 | y422 | y422 | y422 | y422 |
| POST | `/site/charts` | Y | Y | - | Y | - | - |
| POST | `/site/facts/{fid}` | Y | Y | - | Y | - | - |
| POST | `/site/codes` | Y | Y | - | Y | - | - |
| POST | `/site/checks/{cid}` | Y | Y | - | Y | - | - |
| POST | `/site/sheets` | Y | Y | - | Y | - | - |
| POST | `/site/people/resolve` | Y | Y | - | Y | - | - |
| POST | `/site/practice` | Y | Y | - | Y | - | - |
| POST | `/site/remote` | Y | - | - | - | - | - |
| POST | `/api/v1/site/facts/{fid}` | y422 | y422 | y422 | y422 | y422 | y422 |
| POST | `/api/v1/site/charts` | y422 | y422 | y422 | y422 | y422 | y422 |
| POST | `/api/v1/site/codes` | y422 | y422 | y422 | y422 | y422 | y422 |
| POST | `/api/v1/site/checks/{cid}` | y422 | y422 | y422 | y422 | y422 | y422 |
| POST | `/account/password` | y400 | y400 | y400 | y400 | y400 | y400 |
| POST | `/admin/jobs/{job_id}/cancel` | y409 | - | - | - | - | - |
| POST | `/admin/jobs/{job_id}/retry` | y409 | - | - | - | - | - |
| POST | `/admin/models/canary` | Y | - | - | - | - | - |
| POST | `/studies/{rs}/candidates/{pid}/reveal` | y400 | y400 | y400 | y400 | - | - |
| POST | `/studies/{rs}/candidates/{pid}/referral` | - | - | Y | - | - | - |
| POST | `/studies/{rs}/referrals/{ref_id}/answer` | - | y400 | y400 | y400 | - | - |
| POST | `/studies/{rs}/team` | - | - | y400 | - | - | - |
| POST | `/studies/{rs}/team/check` | - | y400 | y400 | y400 | - | - |
| POST | `/studies/{rs}/team/{eid}` | - | - | y400 | - | - | - |
| POST | `/studies/{rs}/irb` | Y | Y | Y | Y | - | - |
| POST | `/site/staff` | y400 | y400 | - | y400 | - | - |
| POST | `/site/opt-outs` | y400 | y400 | - | y400 | - | - |
| POST | `/api/v1/studies/{rs}/candidates/{pid}/referral` | - | - | Y | - | - | - |
| POST | `/api/v1/studies/{rs}/referrals/{ref_id}/answer` | y422 | y422 | y422 | y422 | y422 | y422 |
| POST | `/api/v1/studies/{rs}/irb` | Y | Y | Y | Y | - | - |
| POST | `/api/v1/site/opt-outs` | y400 | y400 | - | y400 | - | - |
| POST | `/ops/flags` | y400 | - | - | - | - | - |
| POST | `/studies/{rs}/edc/switch` | Y | - | Y | - | - | - |
| POST | `/studies/{rs}/edc/drafts` | - | y400 | - | y400 | - | - |
| POST | `/studies/{rs}/edc/send` | - | y409 | - | y409 | - | - |
| POST | `/studies/{rs}/edc/dictionary` | - | y409 | - | y409 | - | - |
| POST | `/studies/{rs}/edc/map` | - | Y | - | Y | - | - |
| POST | `/studies/{rs}/edc/decide/{draft_id}` | - | n | - | n | - | - |
| POST | `/studies/{rs}/edc/sign` | - | y400 | - | y400 | - | - |
| POST | `/api/v1/studies/{rs}/edc/switch` | y422 | y422 | y422 | y422 | y422 | y422 |
| POST | `/api/v1/studies/{rs}/edc/dictionary` | y422 | y422 | y422 | y422 | y422 | y422 |
| PUT | `/api/v1/studies/{rs}/edc/map` | y422 | y422 | y422 | y422 | y422 | y422 |
| POST | `/api/v1/studies/{rs}/edc/drafts` | y422 | y422 | y422 | y422 | y422 | y422 |
| POST | `/api/v1/studies/{rs}/edc/drafts/{draft_id}/decide` | y422 | y422 | y422 | y422 | y422 | y422 |
| POST | `/api/v1/studies/{rs}/edc/sign` | y422 | y422 | y422 | y422 | y422 | y422 |
| POST | `/api/v1/studies/{rs}/edc/send` | - | y409 | - | y409 | - | - |
| POST | `/studies/{rs}/sae/{record}/{event}/{what}` | n | n | n | n | - | - |
| POST | `/pilot/jobs/{job_id}/release` | y409 | y409 | - | y409 | - | - |
| POST | `/pilot/jobs/{job_id}/reveal` | y400 | y400 | y400 | y400 | - | - |
| POST | `/pilot/request` | y400 | y400 | - | y400 | - | - |
| POST | `/pilot/propose` | y422 | y422 | - | y422 | - | - |
| POST | `/pilot/propose/{pid}/confirm` | y410 | y410 | - | y410 | - | - |
| POST | `/pilot/protocol` | y400 | y400 | - | y400 | - | - |
| POST | `/pilot/consent` | y400 | y400 | - | y400 | - | - |
| POST | `/pilot/case` | y400 | y400 | - | y400 | - | - |
| POST | `/pilot/registry/{ruleset}` | y400 | y400 | - | y400 | - | - |
| POST | `/pilot/registry/{ruleset}/promote` | Y | Y | - | Y | - | - |
| POST | `/pilot/cascade` | y409 | y409 | - | - | - | - |
| POST | `/pilot/mailbox` | n | n | - | - | - | - |

Deviations from the URS (§5 of TB-PLAN-05) and SECURITY.md §3, read from the matrix:

- **admin** reaches every patient-level read and export (week, excluded, patient, candidates, registry export with
  MRNs, job files, site patients, `/ask`) and reveals chart numbers: URS-ADM-01 says no patient data (ROLE-010).
- **smo** (external) reaches site-wide pages: `/site/*`, `/site/staff`, `/site/opt-outs` (read and write),
  `/reports/research-office` with all studies' counts: URS-PRV-01 puts the opt-out register with the privacy office
  (ROLE-005).
- **crc, pi** reach the site's audit trail; **admin** too: URS-ADM-12/PRV-07 want a privacy-office report (ROLE-013).
- **cra** has no subject or SDV route: URS-CRA-01..03 (ROLE-012); it reads every study's feasibility (ROLE-011).
- **pi** may add a PI to a study it is not on (ROLE-008); `screening-log.xlsx` and its API disagree (ROLE-017).
- **viewer** reads research-office counts the PI cannot (ROLE-017).
- No route exists for a steward, privacy-office request, break-glass, backup or update status (ROLE-009, -014, -022).

## 5. The demo as a hosted PoC environment

What it is today: one Python process with an in-process box and a local PostgreSQL; synthetic data only; one shared
password; TB_ENV=DEV (no TOTP); data rebuilt on every start. Measured here (4 cores, no other load from me):

| Tool | Time to `/login` 200 | Peak RSS | Steady RSS | Accounts |
| --- | --- | --- | --- | --- |
| `tools.demo` (image default) | 154 s | 1,867 MB | 725 MB | admin, crc, pi, subpi, cra, viewer |
| `tools.role_demo` | 18 s | 591 MB | 444 MB (+40 MB PostgreSQL) | admin, crc, pi, smo, cra, viewer |

HTTPS: the Render and Cloud Run front ends give TLS; the Secure cookie must then stay on, which today stops the image
from starting (ROLE-002). To give Dr Makoto and Dr Wenn their own accounts, in ja and zh-TW, the work is:

1. Fix the boot (ROLE-002) and the API second-factor bypass (ROLE-001) before anything is on the internet.
2. Host on a paid instance: 2 GB for `tools.demo` (1 GB for `role_demo`), min and max instances 1, a persistent
   disk; not the 512 MB free plan that sleeps.
3. Accounts file: one account per tester (e.g. `makoto.pi` investigator ja, `wenn.pi` investigator zh-TW, a CRC each,
   and the owner as admin), passwords issued once out of band, forced change, TOTP on (TB_ENV=TEST with
   `TB_CONSOLE_MFA=totp`, or pass the env through), the account's default language stored on the account (today the
   language is a session setting and the sign-in page follows the browser).
4. Persistence switch: `--keep` keeps the box and the console store across restarts; the owner resets with one command
   (or a nightly reset at a fixed hour announced in the banner). Today a restart wipes everything.
5. Per-IP throttle on sign-in (ROLE-006) and an alert to the owner on lockouts; the hosted demo is reachable by anyone.
6. One study per site in the seed (a JP-language and a zh-TW protocol), so each tester sees their own language end to
   end; the seeded PI notes are English today.

## 6. What is good (keep it)

- CSRF on every form, a separate sign-in CSRF, SameSite=Strict HttpOnly cookies, token rotation at sign-in, server-side
  logout, idle (10 min) and absolute expiry for web and API sessions.
- Security headers on every response, including errors, static files and API answers.
- Lockout that does not reveal whether an account exists, with a clear countdown message.
- The scope guard: CRA and viewer are masked everywhere; SMO cannot reach another study's study, job or registry page.
- The admin is separated from EDC data entry; the PI alone switches prefill on (in the e2e run).
- The 403/404 pages, the one-time password hand-over text, and translation coverage (only a handful of untranslated
  strings in 150 ja/zh-TW pages); no horizontal scroll at 390 px.

## 7. Proposed task cards for TB-PLAN-06

| Id | Goal | Files | Acceptance tests | Depends on | Size | PoC prerequisite |
| --- | --- | --- | --- | --- | --- | --- |
| T-109 (add) | API sign-in with the second factor; API tokens not valid as cookies; forced first change; per-IP throttle | `services/console/home.py`, `auth.py`, `identity.py` | ROLE-001 test; first sign-in forces a change; 30 wrong tries from one IP are slowed | — | S | yes |
| T-DEMO-1 (new) | Hosted PoC demo: boot fix, jars in the image, CI boot check, persistence, accounts file, env pass-through, memory budget | `demo/Dockerfile`, `demo/README.md`, `tools/demo.py`, `tools/list_demo.py`, `tools/role_demo.py`, `render.yaml` | image starts with no `-e`; restart keeps accounts; peak RSS and start time within the README's numbers; ja and zh-TW testers sign in with TOTP | T-109 add | M | yes |
| T-102 (add) | Roles: steward, privacy, monitor, IT admin without PHI; opt-out and staff keeping only for steward/privacy; CRO/SMO must have studies; delegation bootstrap closed; generated role descriptions and menus; page/API parity | `services/console/auth.py`, `team.py`, `app.py`, `libs/tb_common/authz.py` | the matrix of §4 regenerated as a test and equal to the design table; ROLE-005, -008, -011, -015, -017, -018 tests | — | L | partly (ROLE-008, -017) |
| T-211 (add) | Audit browser for privacy and steward only, filters, per-patient report, verify, translated labels | `services/console/app.py`, templates, i18n | crc gets 403; one patient's reveals found in two steps; verify shows the chain state | T-102 | M | no |
| T-PRV-1 (new) | Privacy-office requests: access, erasure, disclosure log with legal clocks per country | new `services/console/privacy.py`, flow ledger | a request is logged, due date shown, the per-patient report lists exports | T-206, WS-08.3 | M | no |
| T-209 (add) | Links to `/ops/identity` and `/ops/flags`; backup and update tiles | `templates/admin.html` | admin reaches unlock in two clicks from `/admin` | — | S | no |
| T-317 (add) | zh-TW and ja wording of the opt-out page, the delegation log term, untranslated strings, error text for a taken user name | `i18n_team.py`, `i18n_identity.py`, `i18n_flags.py` | a CGMH and a JP reader sign off the pages listed in ROLE-023..027 | — | S | yes |

## 8. Questions only the owner can decide

1. May an SMO coordinator ever keep the site's opt-out register or staff directory? Recommended: no; read nothing
   site-wide; only the study's own lists.
2. Who records a study's first PI on the delegation log? Recommended: the trial office (or the steward) from the signed
   log; investigators get study rights only from an entry.
3. Hosted PoC: keep data between sessions, or reset nightly? Recommended: keep, with an owner reset button and a nightly
   backup of the demo volume; announce any reset in the banner.
4. Hosted PoC budget: a paid 2 GB instance (about the price of a small VM a month) versus the free plan? Recommended:
   paid, single instance, Tokyo or Taiwan region, TOTP on.

## 9. Assumptions

- `tools.role_demo` is a fair stand-in for the console's authorisation (same `create_app`, same role table as the product);
  the default image tool differs only in seeded data and accounts.
- The crc account stands for the steward and the privacy office, admin for site IT, cra for the monitor, because the code
  has no such roles.
- The PostgreSQL cluster ran under `/var/tmp/tb-02b-role` (the scratchpad is not traversable by the `postgres` user); it was
  stopped and removed at the end. The CQL jars were fetched with Maven into that folder for one run and removed.
- Memory figures are from one machine shared with other agents; the order of magnitude, not the last megabyte, matters.
