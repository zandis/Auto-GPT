# D-1258 Off a study's delegation log, an investigator learns nothing of the study's patients from other pages (10C-3c)

- **Task:** card 10C-3c of plan 10 (Track C), lane J. The integrator ruled on PR #639 (comments of 2026-11-19, 02:03
  and 22:40 UTC) that three gaps against the rule of D-147 and D-273 are fixed. Each fix only narrows access, so no
  owner question is needed for the code. The pages touch permissions, so the coordinator runs two independent
  reviews. Lane J's block (D-1220 to D-1319) holds the number.
- **Date:** 2026-11-19
- **Status:** accepted for gaps 1 and 2. Gap 3 and the sweep's list wait for a change to the role walk's declared
  table, which the owner holds (see "Remains").
- **Builds on:** D-147 and D-273 (the delegation log decides an investigator's study rows on every page that shows one
  study's patients), D-380 (no PI named, nobody is PI), D-425 (one question per page), D-430 (one break-glass rule),
  D-1225 (J-6: the opening page reads only what the pages would show), D-1241 (10C-3b: the header search)

## The rule

An investigator (principal or sub-investigator) who is not named on a study's delegation log is refused that study's
week list, candidates and every patient page (403, or 404 where the existing page answers so). Anywhere else, that
investigator is answered exactly as for a study, number or job that does not exist to them. The check is the one the
neighbouring pages already ask: `Helpers.delegated` / `Helpers.delegated_ok` (`services/console/home.py`), and,
for serious adverse events, `sae_pages.sae_scope`. No second rule is written and no role name appears inline. The
rule narrows only the roles whose `task.*` rows the log decides (in the matrix: the investigator). Every other role
is answered as before.

## The three gaps

1. **The header search** (`/cmd?q=`, `services/console/step4.py`). Already closed on master by D-1241 (PR #1138).
   The proof test of PR #1132 is a plain passing test in `tests/console/test_header_search_off_log.py`. Run at
   `origin/master` d28f6c03: 9 passed. Nothing more is needed here.
2. **The investigator's start page.** An investigator holds `list.mark`, so `/home` sends them to `/week`
   (`HOME_STARTS`). On master, `/week` (`home.week_any`) read every study in the account's scope:
   - it called `lifecycle_pages.life_home(sess)` with no study filter, so it showed every study's unacknowledged
     serious AEs (participant record, study, AE term, onset day, with a link to the participant) and the study's
     overdue or undated SAE reports (record, study, party, due day);
   - it listed every trial with a screening run (a link to its week page), and every registry with one (a link to
     its cohort page). When exactly one trial had a run, it answered 303 with `Location: /studies/<it>/week`;
   - so an investigator off a study's log learned that the study has serious AEs, of which participants, with
     their terms and onset days, and that it has had a screening run.

   Now the list, the cohorts and the redirect ask the week page's delegation check (`Helpers.delegated_ok`, the
   check `Helpers.delegated` raises on, D-147, D-273). The serious AEs and reports are read only for the studies
   whose SAE pages show them to the account (`Helpers.reads_saes`, i.e. `sae_scope`, as the J-6 opening page
   already reads them, D-1225). The page shows no visit, so it now reads none. An investigator off every log with
   a run gets the page that says no study has a list yet, as an account with no screened study does.

   Left as is (an existing ruling, not narrowed here):
   - the coordinator's view of every study (D-147 item 1);
   - the "criteria waiting for approval" lines (`approvals`): the approval page admits any investigator who sees the
     study (route row `!report.aggregate_only`), and they show protocol criteria, not patients;
   - the J-6 "Needs you today" page (`today_home`, behind `layout.home_today`): it already reads a study's
     patient-level sources only where `reads_participants` and `reads_saes` admit the account. For other studies
     its Next line comes from the feasibility report's existence or a monitor grant, which the feasibility page
     already shows to the account (`study_or_404` only).
3. **The job page and the study's state page** (`GET /pilot/jobs/{job_id}`, `GET /studies/{rs}/state`). A
   sub-investigator off a study's log gets 200 on both. The fix is `Helpers.delegated(sess, rid, path, STUDY_TASKS)`
   (any study task on the log; the job page keeps an open break-glass grant, D-430). It turns those 200s into the
   week page's 403, with its `console.denied` row. But the role walk's declared table
   (`tests/console/data/route_actions.yaml`, the owner's) declares both routes allowed for the off-log investigator
   (`"GET /pilot/jobs/{job_id}": !report.aggregate_only`, line 170; `"GET /studies/{rs}/state": phi.view`, line
   311). With the fix, `tests/console/test_matrix_role_walk.py::test_every_console_route_answers_every_column_as_its_declared_row`
   fails on exactly two cells, both `REFUSED-BUT-MATRIX-ALLOWS` for column `inv`. Per the card, the work stopped
   there and the rows went to the coordinator. The code is not in this change.

## The sweep

The console's own role walk (`tools/role_walk.py`, the test above, `ROLE_WALK_OUT`) was run at `origin/master`
d28f6c03. Column `inv` is an investigator on no entry of GZQO's log, whose log names a PI. These GET routes take a
study, ruleset, job or patient and answer that column with success:

| Route | `inv` | Declared row | What it shows of the study |
|---|---|---|---|
| `/pilot/jobs/{job_id}` | 200 | `!report.aggregate_only` | the job: its line, state, mail thread, audit rows, aggregate outputs, the feasibility funnel; the patient-level cards ask `Helpers.reads` themselves (gap 3) |
| `/studies/{rs}/state` | 200 | `phi.view` | the study's state, history with reasons, identifiers, committee and IRB-text records (gap 3) |
| `/pilot/jobs/{job_id}/approval` | 303 | `!report.aggregate_only` | the criteria under review (a decided round redirects to the job page) |
| `/studies/{rs}/feasibility` | 200 | (aggregate) | the feasibility report: counts and the site profile |
| `/studies/{rs}/forms`, `/api/v1/studies/{rs}/forms` | 200 | (study set-up) | the study's form definitions |
| `/studies/{rs}/irb`, `/api/v1/studies/{rs}/irb` | 200 | (study set-up) | the IRB record |
| `/api/v1/studies/{rs}/icf` | 200 | (study set-up) | the consent form versions |
| `/studies/{rs}/setup` | 200 | (study set-up) | the study's set-up page |
| `/studies/{rs}/sources`, `/api/v1/studies/{rs}/sources` | 200 | (study set-up) | the study's data sources |
| `/studies/{rs}/team`, `/api/v1/studies/{rs}/delegation` | 200 | (delegation log) | the delegation log itself: names, roles, ticks, dates |

None of them shows a patient row to this column: the walk's data check finds no seeded pseudonym. The two pages of
gap 3 are the study-scoped pages the card names. The others are study-level (protocol, set-up, the log, aggregate
counts), and every one of them is declared allowed for `inv` in the owner's table, so each would hit the same stop.
They are listed for the coordinator and not changed here. Five more GET routes answer `inv` 404 because the walk
seeds no such object (`/pilot/cascade/{run_id}`, its files, `/pilot/jobs/{job_id}/files/{filename}`,
`/pilot/jobs/{job_id}/view/{filename}`, `/site/templates/{name}.xlsx`). The job's files and views ask
`Helpers.delegated` for every non-aggregate output already.

## Held by

`tests/console/test_offlog_start_page_10c3c.py` checks the start page for five accounts: the coordinator, GZQO's
PI, a sub-investigator on GZQO's log, an investigator on RA-BIO's log only, and an investigator on no log. With no
screening run, the two off-log investigators see no serious AE, report, record, term or GZQO link, and the three
on-log accounts see both banners with the participant. With a screening run, the off-log investigators get the page
(200, no GZQO week link) instead of a 303 to GZQO's week, and the three on-log accounts are still sent there and
served. Both tests fail on `origin/master`. The role walk passes unchanged: no status of any route changes for any
column. `tests/console/test_header_search_off_log.py` holds gap 1.

## Remains

- Gap 3 and the sweep's list: the owner's rows in `tests/console/data/route_actions.yaml` (lines 170 and 311, and
  the rows of the table above, if the owner wants those narrowed too).
- The administrator, the steward and the privacy office on `/week` are answered as before. The list does not ask
  `phi.view`, so with one screened study they are redirected to its week page, which refuses them. This is not this
  card's gap, and it is unchanged.
