# D-1258 Off a study's delegation log, an investigator is refused the study's 18 doors and its lines in the lists that point at them (10C-3c)

- **Task:** card 10C-3c of plan 10 (Track C), lane J: three gaps against the rule of D-147 and D-273, closed as
  narrowing only, and the doors the sweep found, closed by the owner's decisions recorded on PR #1239 (three comments
  of the lane J coordinator, 2026-11-19 and 2026-11-20). The pages touch permissions, so the coordinator runs two
  independent reviews. Lane J's block (D-1220 to D-1319) holds the number.
- **Date:** 2026-11-19 (the owner's decisions of 2026-11-19 and 2026-11-20)
- **Status:** accepted
- **Builds on:** D-147 and D-273 (the delegation log decides an investigator's study rows on every page that shows one
  study's patients), D-380 (no PI named, nobody is PI), D-425 (one question per page), D-430 (one break-glass rule),
  D-125 (the API answers in JSON), D-1225 (J-6: the opening page reads only what the pages would show), D-1241
  (10C-3b: the header search)

## The owner's decisions

All three were recorded by the lane J coordinator on PR #1239.

1. **2026-11-19, about 23:32 UTC: "close all 14".** "An investigator who is not on a study's delegation log is
   refused every one of these routes of that study, as its week and patient pages are refused today; the
   break-glass grant on the job page stays."
2. **2026-11-20: "close all 4".** Ticking and labelling criteria in the study's approval round, and downloading or
   viewing the study's job output files.
3. **2026-11-20: "empty log open, listed = in".** "While a study's log names nobody, investigators see the study as
   today (a doctor can read the feasibility report before agreeing to be its investigator). Once anyone is named,
   an investigator gets in only with an active entry of their own, with or without a ticked task. An ended entry is
   out. What a task tick itself allows elsewhere does not change."

Decisions 1 and 2 allow these edits: the 18 rows of `tests/console/data/route_actions.yaml` gain the delegation
condition, and their investigator cells change in the design table `tests/console/data/role_route_matrix.md`. The
coordinator's rulings on the same PR allow one new row key, `log: on_log`, in `tools/role_walk.py`, under three
conditions:
- a test pins the rows that carry it;
- it only makes a row stricter;
- its rule is held equal to the console's.

## The rule

On the study's doors, an investigator gets in while the study's delegation log names nobody (no entry at all). Once
the log has any entry, an investigator gets in only with an active entry of their own on it, as PI, sub-investigator
(ticked for any task or for none) or monitor. An ended entry is out. An investigator kept out is refused as the
study's week and patient pages refuse them: 403 with one `console.denied` row, or on an API route the API's own JSON
refusal (D-125). The lists that pointed at those doors leave the study out for them (below). Nothing else changes
here: other pages still name the study (its id, version or kind) to such an investigator (see "What still names a
study").

The rule applies to the roles whose `task.*` rows the log decides (the matrix's conditions; in the matrix, the
investigator). Every other role passes it and meets its own rows on the page. It decides who reaches the doors,
never what a task tick allows. Patient rows, screening, marking, data entry and serious-AE pages stay on their own
task checks (`Helpers.delegated`, `sae_scope`, the `task.*` rows), exactly as before.

In code:
- `console.team.listed(team, user, rs, today)` reads the log;
- `Helpers.on_log_ok(user, rid)` answers yes or no;
- `Helpers.on_log(sess, rid, path)` refuses and audits;
- the job's doors ask `_on_log_or_grant`, which lets an open break-glass grant for that job through (D-430). The
  page or file records the use as before.

The study id is read in upper case, as the log keeps it, so a job filed under `gzqo` asks GZQO's log, not an empty
one.

## The three gaps

1. **The header search** (`/cmd?q=`, `services/console/step4.py`). Already closed on master by D-1241 (PR #1138).
   The proof test of PR #1132 is a plain passing test in `tests/console/test_header_search_off_log.py`. Run at
   `origin/master` d28f6c03: 9 passed.
2. **The investigator's start page.** An investigator holds `list.mark`, so `/home` sends them to `/week`. On
   master, for every study in the account's scope, `/week`:
   - showed the unacknowledged serious AEs (participant record, study, AE term, onset day, a link to the
     participant) and the overdue or undated SAE reports;
   - linked each trial's week page and each registry's cohort page, and redirected to the only screened trial's week
     page;
   - showed the "criteria waiting for approval" lines.

   Now:
   - the list, the cohorts and the redirect ask the week page's own check (`Helpers.delegated_ok`);
   - the serious AEs and reports are read only where `reads_saes` admits the account;
   - the "criteria waiting" lines ask `Helpers.on_log_ok`.

   A sub-investigator ticked only for `run`, `refer` or `enter_data` gets the page with no study listed, since the
   week page itself refuses them. Their serious-AE banners appear only where the SAE pages show them (the review's
   F5, accepted).
3. **The job page and the state page**, with the sweep's other routes: the 18 doors below.

Exactly what is closed, then:
- the 18 doors below;
- the lines of the study in these lists, for the same account:
  - `/week`: its week or cohort link, the redirect to its week page, its serious AEs and SAE reports, its "criteria
    waiting" lines (the "criteria waiting" lines on each study's week page too);
  - the J-6 opening page: its Next line, which linked to the feasibility report;
  - `/reports`: its row, the feasibility summary;
  - `/jobs`: its jobs' rows (ids and links). The page's own answer is unchanged (200), so it needs no row.

## The 18 doors

The console's own role walk (`tools/role_walk.py`, `ROLE_WALK_OUT`) was run at `origin/master` d28f6c03 and on this
change. Column `inv` is an investigator on no entry of GZQO's log, which names a PI; it is the walk's only off-log
investigator column. "Master" is that column's answer on master.

| Route | Master | Now | What it showed or let the off-log investigator do |
|---|---|---|---|
| `GET /pilot/jobs/{job_id}` | 200 | 403 | the job: command line, state, mail thread, audit rows, aggregate outputs (feasibility funnel, top barriers) |
| `GET /pilot/jobs/{job_id}/approval` | 303 | 403 | the criteria under review and the change since the approved version |
| `GET /studies/{rs}/state` | 200 | 403 | the study's state and history with reasons and actors, identifiers, the IRB-text record, committee status |
| `GET /studies/{rs}/feasibility` | 200 | 403 | the feasibility report (aggregate counts), site profile, competing trials, target and screen-fail rate |
| `GET /studies/{rs}/forms` | 200 | 403 | the form definitions and their owners |
| `GET /studies/{rs}/irb` | 200 | 403 | the IRB record: approval dates, protocol version, warnings |
| `GET /studies/{rs}/setup` | 200 | 403 | the study settings (list rules, reasons, contact) and the REDCap link and reads |
| `GET /studies/{rs}/sources` | 200 | 403 | the data sources and their fields |
| `GET /studies/{rs}/team` | 200 | 403 | the delegation log: names, roles, ticked tasks, dates, training |
| `GET /api/v1/studies/{rs}/delegation` | 200 | 403 JSON | the delegation log |
| `GET /api/v1/studies/{rs}/forms` | 200 | 403 JSON | the forms |
| `GET /api/v1/studies/{rs}/icf` | 200 | 403 JSON | the consent-form versions and their history |
| `GET /api/v1/studies/{rs}/irb` | 200 | 403 JSON | the IRB fields and warnings |
| `GET /api/v1/studies/{rs}/sources` | 200 | 403 JSON | the data sources |
| `POST /pilot/jobs/{job_id}/approval/tick` | 409 (walk) | 409 (walk) | a tick on a criterion of the study's round, counted toward it, audited as `console.code_tick` |
| `POST /pilot/jobs/{job_id}/approval/label` | 400 (walk) | 400 (walk) | a label stored for the study's criterion (`console.criterion_label`) |
| `GET /pilot/jobs/{job_id}/files/{filename}` | 404 (walk) | 403 | the job's aggregate files: the feasibility PDF and JSON, the criteria review workbook (`console.download`) |
| `GET /pilot/jobs/{job_id}/view/{filename}` | 404 (walk) | 403 | the job's aggregate pages in the browser |

The walk does not reach the last four with a real target:
- the walk's job is not waiting for approval, so the round answers 409 or 400 before the log check, on master and
  here;
- the walk seeds no file named `1`, so a file answered 404 on master; it is now refused (403) before the lookup, so
  a refused account cannot tell which file names exist.

`tests/console/test_offlog_study_pages_10c3c.py` reaches all four with a waiting round and real files. None of the
18 showed a patient row to this column: the walk's data check finds no seeded pseudonym.

## The tables

- `tests/console/data/route_actions.yaml`: the 18 rows keep their actions or kind and gain `log: on_log`. Their
  `why` names the decision.
- `tools/role_walk.py`: a row's `log: on_log` refuses a column `on_log` refuses, before the row's own gate.
  `on_log_of(role, log_empty=, listed=)` is decision 3, read from the matrix's conditions. The walk does not import
  the console's code; a test holds the two equal.
- `tests/console/data/role_route_matrix.md`: on 16 of the 18 rows, column `pi` changes. That column is defined in
  the test's docstring as "an investigator the GZQO log does not name". The changes are `Y` → `-` on the 14, `U` →
  `-` on the two API rows forms and sources, and `n` → `-` on files and view. Tick and label do not move (the empty
  test body is answered before the log). `lpi`, the logged PI, and every other cell are unchanged.

## What still names a study to an off-log investigator (not in this card; the owner to decide)

These answer the same as on master. They show a study's id, version or kind to any account that sees the study:
- `/api/v1/studies`, `/pilot/registry`, `/pilot/mailbox`, `/pilot/consent`, `/pilot/protocol`, `/pilot/case`,
  `/pilot/cascade`, `/site` and its pages: their study pickers and lists;
- the header search: a study's name (D-1241 item 5);
- the assistant (`/ask`, `/api/v1/ask`), checked for this card:
  - a "why" question about a patient already asks the week page's log check (`trail`, D-273), so it answers nothing
    for a study off the log;
  - a "next" question (also what an empty question gets) is answered for any account that marks lists or sets up
    the site, investigators included. It reads the named study's set-up readiness (`/setup/{ws}/readiness`) and
    says which set-up steps are missing, with their counts, and links to the study's week page (which refuses
    them);
  - so an off-log investigator can learn a study's set-up readiness from `/ask?study=<id>`, but not its feasibility
    figures or criteria text. Not changed without the coordinator's word.

## Held by

- `tests/console/test_offlog_start_page_10c3c.py` (gap 2):
  - the coordinator, GZQO's PI and a sub-investigator on the log are served as before;
  - an investigator on RA-BIO's log only and one on no log see no serious AE, report, record, term or GZQO link,
    and are not sent to GZQO's week.
- `tests/console/test_offlog_study_pages_10c3c.py`:
  - three accounts are refused all 18 doors with the week page's refusal word for word, or the JSON refusal, each
    with its `console.denied` row and no download: on RA-BIO's log only, on no log, an ended entry on GZQO's log;
  - the PI and sub-investigators ticked "screen", only "run", or nothing get the coordinator's status on every door;
  - with GZQO's log empty, every investigator gets the coordinator's status (decision 3 (i));
  - a break-glass grant opens the job page and its files and records the use; the study's other doors and other jobs
    still refuse;
  - off the log, a tick or a label is refused, nothing is stored or counted, and no tick or label row is written;
    the PI ticks and labels as before;
  - a job filed under `gzqo` asks GZQO's log;
  - `/week`, `/reports`, `/jobs` and the J-6 page leave the study out for the off-log accounts and keep it for the
    on-log ones;
  - the walk key: the 18 rows pinned by a literal list; any value but `on_log` is refused; it never widens any row
    for any column; and `on_log_of` equals `Helpers.on_log_ok` over `console.team.listed` for every role and every
    state of a log (empty; others only; one's own active entry as PI, sub ticked or not, monitor; one's own ended
    entry, with or without a PI).
- Every test of a refusal fails on `origin/master`. Without the break-glass branch, the grant test fails.
- Existing tests:
  - `test_t102b_roles::test_role_008` is as on master: GZQO's log is empty there, so the investigator sees the log
    page and its "no PI" note;
  - in `test_home_today`, "other", an investigator off GZQO's log (which names a PI and a sub-investigator), now
    sees no GZQO line or link. In `test_a_refused_investigator_s_home_reads_no_patient_level_row` and
    `test_no_link_of_the_home_opens_a_refusal_for_any_kind_of_account` that assertion is stricter than master;
  - in `test_home_today`, the PI's line for OTHER1 (a study whose log names nobody) is as on master.

## Remains

- On `/week`, the administrator, the steward and the privacy office are answered as before. With one screened study
  they are redirected to its week page, which refuses them.
- What still names a study to an off-log investigator (the section above: `/api/v1/studies`, `/pilot/registry`,
  `/pilot/mailbox`, `/pilot/consent`, `/pilot/protocol`, `/pilot/case`, `/pilot/cascade`, `/site`, the header
  search: id, version, kind) and the assistant's readiness answer: the owner's.
