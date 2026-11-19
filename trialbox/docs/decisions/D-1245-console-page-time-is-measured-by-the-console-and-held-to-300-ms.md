# D-1245 Console page time is measured by the console and held to 300 ms at the 95th percentile (10E-13)

- **Task:** card 10E-13 of plan 10, Track E (`docs/plan/47-plan-10-2026-11-18.md`), from review 13 item 13-14
  (`docs/reviews/2026-11-root/13-tiers-and-tuning.md` sections 6 and 7.1: "no per-page timing exists"; the user waits
  without progress on protocol parts and on the first load). Lane J (the card was lane C2's). · **Date:** 2026-11-19
- **Decision: the header.** The console's outermost middleware (`server_timing` in `console.app`, added last, so its
  time holds every other middleware's) writes `Server-Timing: total;dur=<ms>` (`console.timing`): the console's own
  milliseconds for the request, to one decimal, from the moment it received the request to the moment its answer,
  rendered page included, was ready. Numbers only: no path, account, study, patient or description field. No backend
  share: the console has no single seam where it waits on the orchestrator (the backend, the workspace's helpers and
  the study calls each call out), and a share timed at some calls and not others would mislead.
- **An allow-list, and refused and not found answer alike** (as D-1241 asks of the header search). The header is
  written only on a `200` answer to a `GET` of a route in `console.timing.TIMED`. The list names each route by its
  template (the matched route's path, never the request's path, never a prefix) and holds exactly the walk's ten
  pages. Every other route and method, and any route added later, carries no header until someone adds it on purpose
  with its reason. The rule a listed route meets: **the header adds nothing to what the status already says.** Either
  the route names no thing, or a thing that does not exist gets a 403, a 404 or a redirect (none carries the header)
  where an account that opens the thing gets a `200`. Who gets the `200` is the route's own rule, not this card's: a
  sub-investigator off a study's delegation log opens that study's state page and its jobs' pages, on master as here,
  and the list's reasons say so rather than claim a refusal. The header search (`/cmd`) answers `200` both for a thing
  that exists and for one that does not, so it stays out by construction. The first version kept only `/cmd`
  out (a deny-list). The whole-tree run on this card's merged head found the leak: D-1241's tests failed on the header's
  value. The coordinator asked for the allow-list. Tests: every registered route (FastAPI's, the plain ones and the
  `/static` mount), asked with every method by a coordinator, an administrator, a viewer and a signed-out client,
  carries the header only on a listed `GET`; a `POST` answered `200` on a listed path carries none; the list equals the
  walk's pages; each listed route with an identifier answers a missing one (the account may open the page) and
  another study's one (an account scoped to another study) with no `200`. Two independent reviews (340 routes, 12
  accounts, 8,172 requests) found no leak.
- **What the header tells a signed-in user.** It tells them how long the console took to build a page they were
  allowed to open, which their own clock already shows to within the network's delay. It tells them nothing about a
  page they were refused or that does not exist, because those answers carry no header.
- **The walk** (`tools.console_timing`). These ten pages, opened by an account that may open each one (all taken
  from the life-cycle walks, `tests/e2e/life_cycle_walk_plan.py`, and review 13's list):
  1. the home page (`/home`, coordinator);
  2. the weekly page (`/studies/GZQO/week`, coordinator; the life-cycle walk's most visited page);
  3. the patient sheet (`/studies/GZQO/patients/{pid}`, coordinator);
  4. the candidates (`/studies/GZQO/candidates`, coordinator);
  5. the participants (`/studies/GZQO/subjects`, coordinator);
  6. the study's state (`/studies/GZQO/state`, coordinator);
  7. a job page (`/pilot/jobs/{job}`, coordinator, a finished screening run);
  8. the protocol upload (`/pilot/protocol`, coordinator);
  9. the audit trail (`/audit`, privacy officer);
  10. the Health tab (`/admin/ops`, administrator).

  Each page is asked 10 times first (not counted), then 60 times. Each time is read from the header, never from the
  client's clock. A page fails when an answer is not a `200` with the header, or when the nearest-rank p95 of its 60
  times exceeds **300 ms**. A page over the budget is walked once more, whole, and fails only when it is over a second
  time.
- **Why these numbers (a loaded CI runner).** *The header, not the client:* the time between the test client and the
  console's outermost middleware (the client's work, the event loop's queue, a neighbour's CPU) is not the page's.
  *Warm-up 10:* the first answer of a page compiles its templates and fills the console's caches. Measured on the
  test box: 6 to 91 ms for the first answer against 3 to 12 ms for the later ones, which were steady from the second
  answer on. A box serves pages warm for hours. *60 answers:* the nearest-rank p95 is the 57th, so three slow answers
  per page (a garbage collection, a runner's burst; the probe saw one of 83 ms among a job page's 4 ms answers) are
  absorbed and a fourth counts. *Once more when over:* a runner's burst lasts seconds and passes; a slow page is slow
  again. The whole walk takes about 12 seconds on the test box (p95 between 4.6 and 13.7 ms).
- **The planted slow page.** `tests/console/test_console_timing.py` adds a route to its own test app (never to the
  console's routes; nothing shipped holds it) that holds the event loop for 310 ms, as a slow render would. The walk
  over the ten pages and it fails on that page alone, walked twice and slow both times. The same test file checks the
  walk's rules on every pull request with a short warm-up and repeat: the rule is tested, not the statistics.
- **What a pass proves, and what it does not.** On a synthetic box (the console with its in-memory stand-in
  orchestrator, synthetic studies and patients, no model), each of the ten pages answers in under 300 ms of the
  console's own time at the 95th percentile. A pass says nothing about:
  - the orchestrator's or the lake's time on a real box (the stand-in answers at once);
  - a real data volume (the stand-in holds a handful of patients, not review 13's 50,000);
  - the network or the browser.

  It catches a page whose own work got slow: its rendering, or the console's reads and the loops over them. Review
  13's S-1 (the walk with `curl` on the compose stub at 5,000 and 50,000 patients) is still owed by its own row.
- **Page bodies unchanged.** The header changes no body: `test_the_header_changes_no_page_body` takes the timing
  middleware out of the app and compares the ten bodies byte for byte. The audit trail is compared without its rows,
  because it lists its own reads. The job page's two new blocks add nothing when there is no progress to say
  (`test_a_job_page_without_progress_is_byte_for_byte_the_page_without_the_new_blocks`). Rendered on master and on
  this branch, the ten pages and a weekly run's page with the re-check card were byte for byte the same (csrf values
  normalised; only the audit row's wall-clock time and hash differed).
- **Tier** (the coordinator's ruling). Every pull request runs the rules and the planted page
  (`tests/console/test_console_timing.py`, a few seconds; no pull request gets slower). The walk itself
  (`tests/perf/test_console_timing_walk.py`, marker `perf`, `make console-timing`) is one more step of the nightly
  `perf-5k` job (`trialbox-e2e.yml`), with its report in the step summary and its own artifact `console-timing` (the
  `bench-gate` artifact keeps its layout, so `bench.py --adopt` on a downloaded one is unchanged). **The 300 ms budget
  is held nightly, not per pull request.**
- **Progress while a protocol is read** (review 13 section 7.1: "part 2 of 3 read"). While a FEAS job is parsing or
  compiling and its compile has started, the job page says how many answers the language model has given so far:
  the `llm.call` rows after the job's latest `compile.start`, among the job's own audit rows (the rows the page's
  table shows, the same accounts). While a protocol is read those rows are read up to 5,000 back
  (`console.app.COMPILE_ROWS`), so a long compile's line does not vanish when its start leaves the table's window of
  200; the table still shows the newest 200. If the start is not among them, the page shows no line rather than a
  wrong count. It says plainly that this is not a count of parts. **Known limit:** the page cannot say "part n of N".
  The audit rows the console keeps (`console.backend.read_audit`) do not carry a call's `prompt_version`, so an
  `ir_extract` call cannot be told from a `concept_map` call. The number of parts is known only inside
  `criteria_compiler.service._extract`. The one-integer change it would need: the compiler writes `parts: N` into the
  detail of its existing `compile.start` event, and the console keeps `parts` and the call's prompt. That is a follow-up
  for whoever holds the audit area; this card does not touch the compiler or an audit event.
- **Progress of the first load** (review 13: "first load: 1,840 of 60,000 patients, about 3 more nights"). A finished
  SCREEN or MICROBATCH run's page says how many new patients this run screened and how many are still waiting. It
  also gives an estimate of the nights left **at this run's own pace** (waiting / new patients this run screened,
  rounded up), and says it is an estimate from this run alone. It does not use the event's `budget`. That figure is
  the whole box's budget for one night (`night_budget`), which the night's micro-batches share after re-checks,
  version re-screens and the excluded share (D-646), so an estimate from it was too low. The review's probe was a
  budget of 100 with 10 reached and 500 waiting: the budget gives 5 nights, the pace 50. When the run screened no new
  patient there is no pace, so the page gives no estimate. The figures come from the run's own `microbatch.budget` event, which the page already reads for the
  re-check card. **What the page keeps changed:** `read_recheck_share` (`RECHECK_SHARE`) now also keeps `new_screened`
  and `new_carried`, two whole numbers from the same event; the event is read once a page for both cards. **Who sees them** (the coordinator's ruling):
  only an account that the study's own candidate list admits, by that page's own check (`console.team`:
  `study_seen` and the `screen` task, the two questions of `study_or_404` and `need_task`, now also asked without a
  refusal as `Helpers.admits_candidates`). No break-glass grant opens them. The check comes before the event is read,
  so for a refused account (an investigator off the delegation log, a viewer, the privacy officer) the page makes no
  extra read. Nothing is shown when a figure is missing, when nobody waits, or before the run is done. The words are `job.firstload.*` and
  `job.compile.answers*` in en, ja and zh-TW (`console.i18n_progress`). **Not done:** the review wanted the first load
  on the **home page**. That would be a new reader of the event on another page, so it is left to the owner.
- **Not widened:** no new route, export, column or reader of existing data; no change to the permission matrix,
  sign-in, the audit schema or break-glass.

## Correction (2026-11-19, 10E-13b)

The count of the model's answers ordered the job's audit rows by their timestamp to find "after the latest
`compile.start`". Audit timestamps keep milliseconds, and a `compile.start` and the `llm.call` rows after it can
share one: then the order was undecided and the page could show too few answers (CI saw 2 for 3). The count now
follows the audit log's own order: the reader already returns the rows newest first in the order they were written
(day file, then line), so the console reverses that list and the timestamp no longer decides. No change to the audit
schema, its events, the reader or what any role reads. The test pins every row it writes to one millisecond, in en,
ja and zh-TW (`tests/console/test_job_page_progress.py`).
