# D-1258 Off a study's delegation log, an investigator learns nothing of the study (10C-3c)

- **Task:** card 10C-3c of plan 10 (Track C), lane J. The integrator ruled on PR #639 (comments of 2026-11-19, 02:03
  and 22:40 UTC) that three gaps against the rule of D-147 and D-273 are fixed, as narrowing only. The pages touch
  permissions, so the coordinator runs two independent reviews. Lane J's block (D-1220 to D-1319) holds the number.
- **Date:** 2026-11-19
- **Status:** accepted. Gaps 1 and 2 narrow access under rules already ruled. Gap 3 and the sweep's 14 routes are
  closed by the owner's decision below. The coordinator read that decision as also covering the design table's
  matching cells and the walk's new row key, under conditions this change meets.
- **Builds on:** D-147 and D-273 (the delegation log decides an investigator's study rows on every page that shows one
  study's patients), D-380 (no PI named, nobody is PI), D-425 (one question per page), D-430 (one break-glass rule),
  D-125 (the API answers in JSON), D-1225 (J-6: the opening page reads only what the pages would show), D-1241
  (10C-3b: the header search)

## The owner's decision

Recorded by the lane J coordinator on PR #1239 (2026-11-19, about 23:32 UTC), answering the coordinator's direct
question "which pages should be closed to an investigator off the study's log?": **close all 14.**

> An investigator who is not on a study's delegation log is refused every one of these routes of that study, as its
> week and patient pages are refused today; the break-glass grant on the job page stays.

The permission covered `tests/console/data/route_actions.yaml`, for exactly those 14 rows and only to add the
delegation condition for the off-log investigator. It did not cover `authz_matrix.yaml`, `authz.py` or any other
row, cell or role. The coordinator's reading of the same decision (on PR #1239) also covers:
- the 14 matching cells of the design table `tests/console/data/role_route_matrix.md` (column `pi`, which the
  table defines as "an investigator the GZQO log does not name");
- one new optional row key in `tools/role_walk.py`, `log: on_log`, under three conditions, each held by a test:
  1. only these 14 rows carry it, and `on_log` is its only value;
  2. it can only make a row stricter;
  3. its rule is held equal to the console's.

## The rule

An investigator (principal or sub-investigator) who is not named on a study's delegation log is refused that study's
pages, as its week list, candidates and patient pages refuse them (403, `console.denied`). An API route gives its own
JSON refusal (D-125). Anywhere else, such as a list, a count, a link or a name, the study is answered as one that
does not exist to them.

The check is the one the neighbouring pages already ask: `Helpers.delegated` / `Helpers.delegated_ok`
(`services/console/home.py`). The study-level pages ask it with any study task (`Helpers.on_log`, `STUDY_TASKS`), so
a sub-investigator ticked for any task is on the log. Serious adverse events use `sae_pages.sae_scope`. No second
rule is written and no role name appears inline. The rule narrows only the roles whose `task.*` rows the log
decides; in the matrix that is the investigator. Every other role is answered as before.

## The three gaps

1. **The header search** (`/cmd?q=`, `services/console/step4.py`). Already closed on master by D-1241 (PR #1138).
   The proof test of PR #1132 is a plain passing test in `tests/console/test_header_search_off_log.py`. Run at
   `origin/master` d28f6c03: 9 passed. Nothing more is needed.
2. **The investigator's start page.** An investigator holds `list.mark`, so `/home` sends them to `/week`. On
   master, for every study in the account's scope, `/week` (`home.week_any`):
   - showed the unacknowledged serious AEs (participant record, study, AE term, onset day, a link to the
     participant) and the overdue or undated SAE reports (record, study, party, due day), because
     `lifecycle_pages.life_home(sess)` was called with no filter;
   - listed each trial with a screening run (a link to its week page) and each registry with one (its cohort page),
     and redirected (303) to the week page of the only screened trial;
   - showed the "criteria waiting for approval" lines.

   Now the list, the cohorts and the redirect ask `Helpers.delegated_ok`. The serious AEs and reports are read only
   where `reads_saes` admits the account, as the J-6 opening page reads them. The page shows no visit and reads
   none. The "criteria waiting" lines (`approvals()`, also on each study's week page) ask the approval page's rule.
3. **The job page and the state page**, and the sweep's other 12 routes (below): closed by the owner's decision.
   - Each asks `Helpers.on_log` after its existing checks.
   - The job page first lets through an account with an open break-glass grant for that job. `_job_page` records
     the grant's use as before (D-430). A job with no study is as before.
   - The approval page asks before it redirects a decided round to the job page.

The lists that pointed at these pages leave the study out for the same account:
- the J-6 opening page's Next line, which linked to the feasibility report;
- `/reports`, which showed each study's feasibility summary.

## The sweep: the 14 routes

The console's own role walk (`tools/role_walk.py`, `ROLE_WALK_OUT`) was run at `origin/master` d28f6c03. Column
`inv` is an investigator on no entry of GZQO's log, whose log names a PI. These are all the GET routes that take a
study, ruleset, job or patient and answered it with success. None showed a patient row; the walk's data check finds
no seeded pseudonym. All 14 are now refused.

| Route | Master | Now | What it showed the off-log investigator |
|---|---|---|---|
| `/pilot/jobs/{job_id}` | 200 | 403 | the job: command line, state, mail thread, audit rows, aggregate outputs (feasibility funnel, top barriers) |
| `/pilot/jobs/{job_id}/approval` | 303 | 403 | the criteria under review and the change since the approved version; a decided round redirects to the job |
| `/studies/{rs}/state` | 200 | 403 | the study's state and its history with reasons and actors, identifiers, the IRB-text record, committee status |
| `/studies/{rs}/feasibility` | 200 | 403 | the feasibility report (aggregate counts), site profile, competing trials, target and screen-fail rate |
| `/studies/{rs}/forms` | 200 | 403 | the study's form definitions and their owners |
| `/studies/{rs}/irb` | 200 | 403 | the IRB record: approval dates, protocol version, warnings |
| `/studies/{rs}/setup` | 200 | 403 | the study settings (list rules, reasons, contact) and the REDCap link and reads |
| `/studies/{rs}/sources` | 200 | 403 | the data sources and their fields |
| `/studies/{rs}/team` | 200 | 403 | the delegation log: names, roles, ticked tasks, dates, training |
| `/api/v1/studies/{rs}/delegation` | 200 | 403 JSON | the delegation log |
| `/api/v1/studies/{rs}/forms` | 200 | 403 JSON | the forms |
| `/api/v1/studies/{rs}/icf` | 200 | 403 JSON | the consent-form versions and their history |
| `/api/v1/studies/{rs}/irb` | 200 | 403 JSON | the IRB fields and warnings |
| `/api/v1/studies/{rs}/sources` | 200 | 403 JSON | the data sources |

The full walk, master against this change, covers 4452 cells. 15 differ, all in column `inv`: the 14 above and
`GET /week` (303 to GZQO's week, now 200: gap 2). The PI, the sub-investigator on the log, the coordinators, the
administrator, the steward, the privacy office, the viewer and the CRO accounts answer as before on every route.
Five more GET routes answer `inv` 404 because the walk seeds no such object: `/pilot/cascade/{run_id}` and its
files, `/pilot/jobs/{job_id}/files/{filename}`, `/pilot/jobs/{job_id}/view/{filename}`, `/site/templates/{name}.xlsx`.
The job's files and views already ask `Helpers.delegated` for every non-aggregate output.

## The tables

- `tests/console/data/route_actions.yaml`: the 14 rows keep their actions or kind and gain `log: on_log`. Their
  `why` names this decision.
- `tools/role_walk.py`: a row's `log: on_log` refuses a column that `on_log_of` refuses, before the row's own gate.
  `on_log_of(role, standing)` is read from the matrix and the column's standing, as the walk reads every gate; the
  walk does not import the console's code.
- `tests/console/data/role_route_matrix.md`: on the 14 rows, column `pi` changes from `Y` (`U` on the API forms and
  sources) to `-`. Every other cell is unchanged; `lpi`, the investigator the log names as PI, is still `Y`.

## Held by

- `tests/console/test_offlog_start_page_10c3c.py` (gap 2). The accounts are:
  - the coordinator, GZQO's PI and a sub-investigator on GZQO's log, who are served as before;
  - an investigator on RA-BIO's log only and an investigator on no log, who see no serious AE, report, record,
    term or GZQO link, and are not redirected to GZQO's week.
- `tests/console/test_offlog_study_pages_10c3c.py` (gap 3, the lists and the walk key):
  - the two off-log investigators are refused all 14 routes. The pages are refused word for word as the week
    page; the API routes with `{"error": "forbidden", "detail": {}}`. Each refusal has a `console.denied` row;
  - the PI and sub-investigators ticked "screen" or only "run" get the coordinator's status on all 14, with no
    refusal row;
  - a break-glass grant opens the job page and records its use, and the study's other pages still refuse;
  - `/week`, `/reports` and the J-6 opening page leave the study out for the off-log accounts and keep it for the
    on-log ones;
  - only the 14 rows carry `log:`, any other value is refused, and the key never widens a row (all rows and all
    columns, and rows whose actions refuse);
  - `on_log_of` equals `Helpers.delegated_ok` with every study task, for every role and every standing.
- Every test of a refusal fails on `origin/master`. Without the break-glass branch, the grant test fails.
- `tests/console/test_matrix_role_walk.py` and `test_role_route_matrix.py` hold every other role's answer.

## Remains

- On `/week`, the administrator, the steward and the privacy office are answered as before. The list does not ask
  `phi.view`, so with one screened study they are redirected to its week page, which refuses them. This is not this
  card's gap, and it is unchanged.
- The header search still names a study in the account's scope (D-1241 item 5: a study's name is not its rows).
