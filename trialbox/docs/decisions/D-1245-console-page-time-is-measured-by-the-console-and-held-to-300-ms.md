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
  because it lists its own reads.
- **Tier.** The rules and the planted page run on every pull request (`tests/console`, a few seconds). The walk itself,
  `tests/perf/test_console_timing_walk.py`, is marked `perf`, so it is not in `make test` or the pull-request shards;
  where it runs is in the PR's text, as agreed with the coordinator.
- **Progress for the protocol parts and the first load:** see the pull request; this section is completed with the
  card.
- **Not widened:** no new route, export, column or reader of existing data; no change to the permission matrix,
  sign-in, the audit schema or break-glass.
