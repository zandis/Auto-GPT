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
- **Refused and not found answer alike** (as D-1241 asks of the header search): the header is written on a `200`
  answer only. A refusal (401, 403), a not-found (404), a redirect (sign-in, a page sent home) and an error carry
  none, so the header says no more than the status code already says.
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
  `perf-5k` job (`trialbox-e2e.yml`), with its report in the step summary and the job's artifact. **The 300 ms budget
  is held nightly, not per pull request.**
- **Progress while a protocol is read** (review 13 section 7.1: "part 2 of 3 read"). While a FEAS job is parsing or
  compiling and its compile has started, the job page says how many answers the language model has given so far:
  the `llm.call` rows after the job's latest `compile.start`, among the audit rows the page already shows the same
  accounts. It says plainly that this is not a count of parts. **Known limit:** the page cannot say "part n of N".
  The audit rows the console keeps (`console.backend.read_audit`) do not carry a call's `prompt_version`, so an
  `ir_extract` call cannot be told from a `concept_map` call. The number of parts is known only inside
  `criteria_compiler.service._extract`. The one-integer change it would need: the compiler writes `parts: N` into the
  detail of its existing `compile.start` event, and the console keeps `parts` and the call's prompt. That is a follow-up
  for whoever holds the audit area; this card does not touch the compiler or an audit event.
- **Progress of the first load** (review 13: "first load: 1,840 of 60,000 patients, about 3 more nights"). A finished
  SCREEN or MICROBATCH run's page says how many new patients this run screened and how many are still waiting. It
  also gives, as an estimate from this run's night budget, about how many more nights that is (waiting / budget,
  rounded up). The page says the estimate changes with a night shared with other studies or with new patients
  arriving. The figures come from the run's own `microbatch.budget` event, which the page already reads for the
  re-check card. `read_recheck_share` now also keeps `budget`, `new_screened` and `new_carried`, whole numbers from
  the same event. The rule is the re-check card's: only the accounts that read the study's list. Nothing is shown when
  a figure is missing, when nobody waits, or before the run is done. The words are `job.firstload.*` and
  `job.compile.answers*` in en, ja and zh-TW (`console.i18n_progress`). **Not done:** the review wanted the first load
  on the **home page**. That would be a new reader of the event on another page, so it is left to the owner.
- **Not widened:** no new route, export, column or reader of existing data; no change to the permission matrix,
  sign-in, the audit schema or break-glass.
