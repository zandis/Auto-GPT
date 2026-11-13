# Deep review 2026-11-13: the console, the API and the users' journeys

| Field | Value |
| --- | --- |
| Area | The console (`services/console`), `/api/v1`, every role's journey, the demo path for Tuesday 2026-11-17 |
| Slug | `console` |
| Tree | `master` at `c7dcd5e7`; fixes on branch `claude/deep-review-console` |
| Run | `python -m tools.demo --keep` (stub model, synthetic hospital, PostgreSQL 16) on 127.0.0.1, seed passed in 376 s; Chromium through Node Playwright: a crawl of 7 roles × ja, zh-TW, en at 1366×768 (19 runs, 45 pages each, axe-core on every page) and 3 roles at 390×844 (ja); scripted journeys (sign-in language, the PI's week list and mark bar, a referral end to end, a coordinator's screening run, the audit browser, a phone header); page times on a quiet machine; three helper reviewers (API, closed findings, adversarial) |
| Only read | The hosted demo scripts (`deploy/gcp/*`), `demo/Dockerfile`, the OIDC and TOTP sign-in, mail texts, PDFs |
| Not possible here | The demo VM, Docker, a real phone, a screen reader, real Excel |

Terms. **Demo**: the one-process console `tools.demo` serves, with a synthetic hospital. **Seed day**: the day the demo's
data is moved to (D-496). **Site day**: the calendar date in the site's time zone (Asia/Taipei here; the run crossed
midnight there, so "today" was 2026-11-14 while UTC was 2026-11-13, a useful test). **Verified** means reproduced by
running (command, test or screenshot); **read** means found in the code only.

## 1. Reading in ten lines

1. Nothing in my area wrongly includes or excludes a patient, loses data, exposes a secret or breaks who may act. No
   Critical.
2. **The demo's first screen will tell the guest the data is stale** (CON-DEMO-1). On Tuesday 2026-11-17 the PI's list
   says "Data as of 2026-11-10: more than two days old. Ask for a new run before you act on this list." A new run
   does not change it: the demo's data never moves. Owner's decision (section 5).
3. **The hosted demo never switches demo mode on** (CON-DEMO-2): uploads are accepted and nobody is asked to confirm
   "synthetic data only" unless the owner remembers `/ops/flags`. A step for Tuesday.
4. **A guest who picks English on the sign-in page lands in Japanese** (CON-DEMO-3). The demo's language wrapper wins
   over the guest's choice.
5. The desktop mark bar (UX-001, open since 2026-11-12) was 2,373 px down the panel. **Fixed** here.
6. Four role leaks of the "link that answers 403" kind, two fixed (administrator's patient tasks, CRO's account link),
   one recorded (investigators' study lists follow the account, not the delegation log), one from the API reviewer.
7. The steward's and privacy office's Help showed a raw key; the viewer's Help claimed a right it lacks. **Fixed.**
8. `/api/v1` has a sound guard, but a 503 answers in HTML, error bodies have three shapes and no test checks any
   answer's shape (from the API reviewer, verified).
9. Accessibility holds: one axe violation (`scrollable-region-focusable`) in 760 page loads; the CSP is strict enough
   to block an injected script (my test harness had to bypass it).
10. Speed on a quiet machine is as on 2026-11-12 (PI week list 0.76 s, coordinator home 0.95 s); under the load of
    three browsers it was 3 to 6 s. No new speed finding.

Counts: Critical 0, High 5, Medium 10, Low 11. Fixed on this branch: 8.

## 2. Findings

Owner lanes: **C2** trust and console, **D** box, serving, demo image, **G** cloud runs and the demo VM, **A2**
decision and model. "Fixed" means fixed on this branch with a test that failed before.

### 2.1 High

| ID | Finding | Evidence | Root cause | Fix | Lane | State |
| --- | --- | --- | --- | --- | --- | --- |
| CON-DEMO-1 | On the demo the PI's first screen and every patient page show an amber line: data more than two days old, ask for a new run. On Tuesday 2026-11-17 the data will be 7 days old. Asking for a run does not help. | Verified: PI week page `data-testid="data-asof" data-stale="yes"` "Data as of 2026-11-10…"; a coordinator's SCREEN of GZQO and the scheduler's MICROBATCH at 00:04 both finished `done`, the line still says 2026-11-10. Screenshot `pi-home-ja.png` (scratch). | `home.py:75` `STALE_DAYS = 2` (a fixed limit that is not a declared setting) against D-496, which seeds the demo on the Tuesday before the last Wednesday, so its data is 1 to 7 days old by design and never moves. | Owner decision (section 5). Either the line names the demo ("demonstration data, fixed on 2026-11-10") when the lake has no feed, or the threshold comes from the site's data cadence and is declared in `tb_common.config.DECLARED`. | C2, D | open |
| CON-DEMO-2 | The hosted demo starts with demo mode off: uploads and pasted chart text are accepted and no account confirms "synthetic data only". | Read: `TB_DEMO_MODE` is set nowhere (`deploy/gcp/hosted-demo-startup.sh:187-194`, `demo/Dockerfile`, `demo/README.md`); `tb_common/flags.py:105-111` default `off`. The intent is in `tests/integration/test_poc_scripts.py:11-12,169` (the owner switches it on after seeding) but no document tells him. | A manual step that lives only in a test. | Tuesday: the owner sets `demo.mode` on `/ops/flags` after the seed. Lasting: set `TB_DEMO_MODE=on` in the hosted start script and say so in `demo/README.md` (both files are in open PR #246: not edited here). | D, G | open |
| CON-DEMO-3 | The sign-in page's language choice is overridden: picking English or 繁體中文 lands the PI in Japanese. | Verified: `journey.json` `signin_pick_en {loginLang: en, lang: ja}`, same for zh-TW. | `tools/demo.py:309-345` `DefaultLanguage` resets every new session of a built-in account to `--lang`; the product itself does not keep a language per user (UX-008, still open). | Short term: the wrapper applies only when the sign-in carried no explicit choice. Lasting: UX-008 (a `users.lang` column) and delete the wrapper. `tools/demo.py` is in open PR #246: not edited here. | D, C2 | open |
| CON-API-1 | `GET /api/v1/studies/{rs}/reconsent` answers 503 as an HTML page, not JSON. | Verified by the API reviewer: `503 text/html <!doctype html>` with `Accept: application/json`. | `app.py:744-748` `Unavailable` handler always renders `problem.html`; `team.py:952` does not catch `Unavailable` as the other modules do. | Add the `/api/` branch to the handler, as `_Problem` has (`app.py:726-735`). `app.py` is in open PR #486: not edited here. | C2 | open |
| UX-001 | The desktop mark bar sat under all criteria, 2,373 px from the top of a 768 px screen. | Verified: `journey.json` `approach top 2373 inView false` in ja, zh-TW, en. | `.chartp { overflow: hidden }` made the panel its own scroll container, so a sticky bar stuck inside it. | `overflow: clip` and one sticky dock (`.chartdock`) holding the bar and its IRB and referral warnings. Test: `tests/console/test_cjk_layout.py` (a desktop sheet page in each language). | C2 | **fixed** |

### 2.2 Medium

| ID | Finding | Evidence | Root cause | Fix | Lane | State |
| --- | --- | --- | --- | --- | --- | --- |
| CON-DEMO-4 | The demo's PI first screen also says the delegation log was not compared with the office's signed log this month. | Verified: `data-testid="team-due"` on the week page. | The seed records no monthly comparison. | Tuesday: the PI ticks the comparison on `/studies/GZQO/team#check` before the guest arrives (a `--keep` demo keeps it). Lasting: the seed records one. | D | open |
| CON-ROLE-1 | The administrator's study view (`/home?view=studies`) listed each patient a PI had marked, by pseudonym, linking a panel that answers 403. | Verified: link `患者 61c68617（GZQO）の情報を確認` → 403. | D-280 removed the clinic rows there, not the tasks (`home.py` `study_card` tasks). | Patient tasks (call, info, prepare, refer) are left out where `can_view_phi` is false. Test: `test_the_administrators_study_view_lists_no_patient_task`. | C2 | **fixed** |
| CON-ROLE-3 | An investigator's study lists follow the account's study scope, not the delegation log: the sub-investigator's Ask examples default to study AD-MAB and the registry index links AD-MAB; both answer 403. | Verified: `/ask` example → `/site/patients?ws=main&study=AD-MAB` 403; `/pilot/registry` → `/pilot/registry/AD-MAB` 403. | Two scopes: `User.sees_study` (account) in `site_pages.py:148-162` and `home.py:261-266`; `Helpers.delegated` (log) on the pages. | One helper "studies this person may work in" (account scope ∩ delegation for investigators) used by every list. Who-may-see logic: not patched here. | C2 | open |
| CON-I18N-1 | The steward's and privacy office's Help showed the raw key `help.role.steward`; the viewer's Help said it reads the audit trail (only the steward and the privacy office do, D-451); the CRO's did not mention the monitor grant. | Verified: `/help` as `stw` printed `<p>help.role.steward</p>`. | Keys never written for the two newer roles. | Texts in three languages. Test: `test_every_role_has_its_own_help_text_in_every_language`. | C2 | **fixed** |
| CON-API-3 | No test checks the shape of any `/api/v1` answer; about 25 GET routes only ever answer 503 in the role walk. | Read and run by the API reviewer (`test_role_route_matrix.py` scores the status class only). | Routes declare `dict[str, Any]`; `schemas/` covers jobs, not the console API. | A response model or JSON schema per route and one shape test per route on a box with the study store. | C2 | open |
| CON-API-4 | Error bodies come in three shapes: `{"error","detail":{}}`, `{"detail":"Not Found"}`, `{"detail":[…]}`; an unknown `/api/v1/…` URL with `Accept: text/html` gets the HTML 404 page (against D-125). | Verified by the API reviewer. | 404, 405 and 422 on `/api/` go through FastAPI's defaults. | Answer them in the `{"error","detail"}` form on `/api/`. | C2 | open |
| CON-API-5 | `GET /api/v1/ask` refuses a CRO account that `/ask` lets in. | Read: `app.py:590` allow-list has `/ask`, not `/api/v1/ask`; `SAME_ANSWER` does not pair them. | Two lists. | Add the API twin, pair them in the matrix test. | C2 | open |
| JRN-004 | Closing a study is still one POST with no confirmation and no check (participants on study, open SAEs). | Verified by the closed-findings reviewer: pause then close GZQO as a coordinator, each one POST, 303. | `study_setup.py:539-565`; `authz_matrix.yaml:158-162`. | As in the 2026-11-12 review. | C2 | open (was open) |
| JRN-005 | An EDC item map over 76 items cannot be saved: raw JSON "Too many fields. Maximum number of fields is 1000." | Verified by the closed-findings reviewer. | `edc_pages.py:483-484` plain `request.form()`. | As in the 2026-11-12 review. | C2 | open (was open) |
| UX-007, UX-008, UX-011 | Session expiry says nothing and loses the note; the language is not remembered; an empty box's sign-in page names a `docker compose` command, not the wizard. | Verified by the closed-findings reviewer (probes). | As in the 2026-11-12 review. | As in the 2026-11-12 review. | C2 | open (were open) |

### 2.3 Low

| ID | Finding | Evidence | Fix | Lane | State |
| --- | --- | --- | --- | --- | --- |
| CON-TZ-1 | The feasibility report (and its sponsor copy) dated the site profile with the first ten characters of a UTC time: a profile saved on a Taipei or Tokyo morning showed the day before. | Read `studies.py:313`; test fails before. | `feas_report(..., zone=)`, the page passes the site's zone. Test `test_the_feasibility_report_dates_the_site_profile_on_the_site_day`. | C2 | **fixed** |
| CON-API-2 | `POST /api/v1/session` answered `"expires": null` for every session. | Verified (API reviewer, then test). | The absolute end (UTC) and `idle_minutes`. Test `test_the_api_sign_in_says_when_its_session_ends`. | C2 | **fixed** |
| CON-ROLE-2 | "My account" offered a CRO account the notification settings, which answer 403. | Verified in the crawl. | Hidden for sponsor-form accounts; a test opens every link of the page for each of seven roles. | C2 | **fixed** |
| CON-UX-2 | The steward's audit browser scrolled sideways by 188 to 713 px at 1366 px. | Verified: `scrollWidth 2079`, the filter row. | The filter row wraps. Test `test_the_audit_filter_row_wraps`; live page 1366. | C2 | **fixed** |
| CON-UX-3 | The PI's evidence line printed UCUM codes: `187 mm[Hg]`. | Verified on `/studies/GZQO/not-matched`. | Printed form on screen (`mmHg`, `10^9/L`, `IU/L`); the stored unit is unchanged. | C2 | **fixed** |
| CON-UX-4 | The week list shows the treating doctor as an id (`P23456`) and the department as a code with an "original" mark (`RHEU (原文)`), while the referral page shows the name (佐藤 健一). | Screenshot `pi-home-ja.png`; candidate page text. | Use the staff directory's name on the list as on the referral page. | C2 | open |
| CON-UX-5 | On the not-matched list each coded row says "the coded records" twice (column and evidence). | Verified, en. | Drop the evidence cell's prefix. | C2 | open |
| CON-UX-6 | Built-in form labels stay English on ja and zh-TW pages (`Serum uric acid (mg/dL)` on `/forms` and `/sources`). | Verified in the crawl. | UX-015 of 2026-11-12, still open. | C2 | open |
| CON-UX-7 | On a phone the first screen of the PI's list shows no patient: four banners and the link row fill it. | Screenshot `phone-pi-home.png` (390×844). | Fold the banners on a phone as on the desktop (T-684). | C2 | open |
| CON-DOC-1 | `tools/demo.py`'s module text (lines 40-44) still describes D-329 (weekend → Friday, data of the day before); D-496 and `demo/README.md` describe the Tuesday rule. | Read. | One sentence; the file is in open PR #246. | D | open |
| CON-DOC-2 | `REGISTRY.md` lists D-540, D-542, D-545 as reserved although their code is merged and tested; UX-004 is called done, but CASE and CONSENT text uploads still decode blindly (`orchestrator/scenarios/case.py:149`, `consent.py:177`; open PR #479 covers them). | Read and run by the closed-findings reviewer. | Integrator's registry pass; land #479. | integrator, C2 | open |

### 2.4 Closed findings re-checked

The closed-findings reviewer re-ran the tests that hold them. Really fixed: JRN-001 (a new study's first approval,
`test_first_approval.py`, 6 pass), JRN-002 (opt-out by the whole pseudonym only, `test_optout_whole_pseudonym.py`),
UX-017 (BOM on CSV), CR-017 to CR-024, CR-029, CR-034, CR-049, CR-050, CR-055, CR-116, CR-117 (105 and 57 tests pass).
Mostly fixed: UX-006 (no date after today: the unit test holds the arithmetic, but the page check in
`tools/e2e_simple.py:1420` runs only on a live-day demo). Still open as recorded: JRN-003, 004, 005, 006, 007, 008,
011, 013, 014, 022; UX-002, 003, 005, 007, 008, 011, 012.

## 3. The demo on Tuesday 2026-11-17: what would embarrass, and the checklist

What the guest would see in the first five minutes without preparation, in order:

1. The sign-in page in one language and the console in another (CON-DEMO-3).
2. The amber "data more than two days old, ask for a new run" line on the first screen and on every patient page
   (CON-DEMO-1), and a second amber line about the delegation log (CON-DEMO-4).
3. The word `MICROBATCH` in the run line ("2026-11-11 の MICROBATCH 実行結果"), UX-021, still open.
4. The mark buttons out of sight on a desktop (UX-001; fixed on this branch, only if this branch is in the image).
5. A doctor shown as `P23456` on the list (CON-UX-4).

Checklist for the owner (no code needed):

| Step | Where | Why |
| --- | --- | --- |
| Seed with the guest's language: `TB_DEMO_LANG` (built-in accounts) or `"language"` per account in the accounts file | the demo's start | CON-DEMO-3 |
| Sign in as admin, set `demo.mode` on with a reason | `/ops/flags` | CON-DEMO-2 |
| Sign in as the PI, record this month's delegation-log comparison | `/studies/GZQO/team#check` | CON-DEMO-4 |
| Say in one sentence that the data is fixed synthetic data from 2026-11-10 | spoken | CON-DEMO-1 until the owner decides |
| Stay off `/pilot/*`, `/jobs` and the API: builder screens with English words | the walk | UX-015, UX-021 |
| Use a desktop at 1366 px or wider for the PI; a phone works for the week list | | UX-001, CON-UX-7 |

## 4. What is good and should not be changed

* The guard of `/api/v1`: the session and the declared permission are checked before the body is read; bearer only;
  every one of 82 routes answers an anonymous call with JSON 401; refusals repeat no value of the request.
* The strict content security policy: an injected inline script is refused.
* Accessibility basics: one axe violation in 760 page loads, labels on every input but one, one `h1` per page.
* The evidence lines: value, date and code system for each coded fact; the original protocol text one click away and
  tagged with its language; the test-model pill.
* The referral journey: clear choices, nothing required, the doctor needs no account, the letter in the doctor's
  language.
* Site-day handling in the console (`timefmt.local_today`, `local_date`): the run crossed midnight in Taipei and every
  run, job and list date was the site's date.

## 5. Decisions for the owner

| Question | Options | Recommendation |
| --- | --- | --- |
| D-TBD: what the "data as of" line says when the data cannot move (the demo) | (a) a demo line "demonstration data, fixed on <day>", no amber; (b) the threshold from the site's data cadence, declared in `DECLARED`; (c) leave it and explain at the demo | (a) for Tuesday, (b) for the box: `STALE_DAYS = 2` is also an undeclared fixed limit |
| Should this branch's UX-001 fix be in Tuesday's image | yes / no | yes: it is CSS and one template block, tested in three languages |

## 6. Where the project carries needless weight

* Three ideas of "the studies a person sees": the account's list, the delegation log, and a CRO allow-list of paths
  (`app.py:588-597`). They disagree (CON-ROLE-3, CON-API-5). One helper would remove a class of 403 links.
* About forty `i18n_*.py` catalogues merged into one dictionary at import time by the modules that use them. A probe
  that imports `console.i18n` alone sees a different catalogue from the app (it misled this review once); the parity
  tests must import the app.
* The demo's `DefaultLanguage` wrapper stands in for a product feature (UX-008) and now overrides the user.
* The `/pilot/*` builder pages are still reachable from the coordinator's menu with English labels ("Ruleset",
  "practitioner ids").

## 7. How the review ran (for repeating it)

`make venv fonts`; `make jvm-deps` needed `~/.m2/settings.xml` to name the session's HTTPS proxy (Maven does not read
`JAVA_TOOL_OPTIONS` proxy properties): a fact of this machine, not of the product. The demo:
`TB_DEMO_PASSWORD=… TB_ENV=DEV TB_FONTS_DIR=$PWD/.cache/fonts TB_CQL_TRANSLATOR_LIB=$PWD/.cache/jvm/cql-translator/lib
TB_CONSOLE_SECURE_COOKIE=0 PYTHONPATH=libs:services:. .venv/bin/python -m tools.demo --dir /var/tmp/tbdemo/d1 --keep
--port 18200` (a folder the `postgres` user can reach). The crawl and journey scripts and their JSON output are in the
session's scratch folder, not in the repository.
