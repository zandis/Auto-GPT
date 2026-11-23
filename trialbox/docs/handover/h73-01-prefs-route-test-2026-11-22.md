# H73-01: the preferences route invariant, cheaper and blind to the clock

**Reader:** the people who build TrialBox: the lane K lead and the integrator. Findings for builders, so in one
language.

- **Card:** H73-01 (the integrator's card, lane K's; the finding H73-01 of
  [`unit-shard-1-fits-again-2026-11-22.md`](unit-shard-1-fits-again-2026-11-22.md), and train 123's red)
- **Date:** 2026-11-22
- **Decision:** [D-1387](../decisions/D-1387-a-persons-own-preferences-without-quiet-hours.md) (the invariant it
  holds; unchanged)
- **Findings:** [`h73-01-prefs-route-test-2026-11-22/findings.json`](h73-01-prefs-route-test-2026-11-22/findings.json)
  (H7301-01, H7301-02)
- **File:** `tests/console/test_prefs_10f1.py` only

## What was slow, and why

`test_no_preference_opens_a_route_or_shows_a_patient_value_the_defaults_do_not` had one case per role (seven). Each
case set up one box, walked the defaults three times, then, for each of the 96 combinations of the closed sets, saved
the combination and walked every GET route (166 for a coordinator) and every changing route the defaults could not
use (127 to 152). That is about 28,000 requests per role, all in one case on one worker. The set-up, the sign-in and
the defaults' walk were already done once per role and cost about 6 s of a case; the cost is the 96 walks.

Measured per walk (one combination, coordinator, idle machine): the GET routes 1.0 s through the test client, of which
a 404 on an unknown path, the floor of the client and the middleware, is 1.9 ms per request. The Starlette test
client starts a new event loop in a new thread for every request (`TestClient._portal_factory`) and crosses threads
for every ASGI message.

## What changed

1. **One event loop.** The walk's requests go through one event loop with httpx's own ASGI transport (`_OneLoop`):
   the page client's cookies, headers and client address, a server error answered as a 500 as `clients()` makes its
   page clients. One cross-thread call per request. The app's startup and shutdown are not run, as before. For each
   of the seven roles the defaults' GET walk (routes answering 200 and each route's measure) and the refused-POST walk
   (each answer's class) were the same through both clients (a scratch check, not kept).
2. **Cases the workers share.** Each role is four cases, one per language (`COMBO_GROUPS`, 24 combinations each):
   28 cases. Each case sets up its own seeded box and walks its own defaults, so every combination is still compared
   with the defaults on the same seeded state. `test_the_groups_hold_every_combination_once` holds that the groups
   are the 96 combinations, each once. A cache of the defaults' walk across cases was not used: a case's box is its
   own (function-scoped, its own store and audit trail), and the defaults' walk costs about 5 s of a case of 45 to 85.
3. **The same comparison.** The routes, the roles, the values and the refusals compared are as before: `ok <= ok0`,
   `_wider(shown0, shown) == {}`, and denied stays denied, for every combination.

## Seconds per role, before and after

Serial (`-n 0`), the whole parametrized test, on this 4-core machine shared with other jobs. Per role, after is the
sum of its four cases.

| Role | Before (s) | After (s) | Longest case after (s) |
| --- | --- | --- | --- |
| admin | 270.1 | 195.6 | 50.4 |
| crc | 245.3 | 179.6 | 47.0 |
| pi | 335.2 | 201.9 | 52.9 |
| viewer | 278.6 | 202.5 | 53.4 |
| cro_mon | 464.0 | 222.0 | 57.7 |
| steward | 330.5 | 216.4 | 54.9 |
| privacy | 325.2 | 273.8 | 83.6 |
| **all** | **2,248.0** (7 cases, 37:49 wall) | **1,491.8** (28 cases, 25:12 wall) | |

Load (`uptime`, 1/5/15 min): before, 0.36/0.11/0.03 at the start and 4.33/5.45/5.21 at the end; after,
0.77/1.39/2.35 at the start and 5.76/3.75/2.39 at the end. The loads differ, so the per-role figures carry that noise
(privacy's ja case ran under the heaviest load). An A/B of six combinations in one process (coordinator, CRO monitor;
load about 1.5) gave 2.61 and 2.96 s per combination through the plain test client, 2.20 and 2.21 with one shared
loop on the test client, and 1.52 and 2.15 through `_OneLoop`.

The CPU of the whole test falls by about a third. Under xdist the gain is in the wall time: the longest case is 84 s
instead of 464 s (on CI 150 to 260 s per role case, four of seven reaching the 900 s timeout on the bench), and 28
cases spread over the workers with `--dist worksteal` (D-1355). Every new console GET route still adds 96 requests
per role: the test keeps growing with the console, more slowly per case.

## The clock

Train 123's red (job 137165240799, `[steward]`): `{'/audit/patients/{pid}/report.csv': {'09:30': (0, 1)}} == {}`.
The patient value "09:30" (the seeded appointment, 2026-10-07 09:30) was counted inside the stamp of an audit row the
walk itself wrote at 10:09:30. Each walk writes its audit lines at another second, so the defaults' walk and a
preference's walk differed by the clock alone.

**Masked, not frozen.** `_measure` now masks, before counting, every stamp a page prints (a date with a time of
day: `2026-11-22 20:43`, `2026-11-22 20:43:47`, `2026-11-22T20:43:47.416+08:00`) whose instant falls within the run
(`RUN_STARTED`, taken when the module is imported, to now; a stamp without an offset is read with a slack of 14 hours
either side, any zone). A survey of every 2xx page of the seven roles found only these three forms of run time, all
with a date. Freezing the clock was not chosen: the run's time is read in many places (the audit log, the flags
store, the team log, the referrals, the sessions), each with its own clock, and freezing them all would reach into
other lanes' modules; masking needs only the test's own measure, and keeps every seeded value counted.

Constructed case (`test_the_invariant_is_blind_to_the_clock_and_still_sees_a_patient_time`, run window
2026-11-22 02:09:12 to 02:10:05 UTC), the old `_measure` from `HEAD` against the new:

| Page | Old | New |
| --- | --- | --- |
| audit CSV, a row at `2026-11-22T10:09:30.512+08:00` (the defaults' row at 10:09:12) | `{'09:30': (0, 1)}`: red | `{}` |
| the same, plus the appointment `2026-10-07T09:30:00+08:00` | `{'2026-10-07': (0, 1), '09:30': (0, 2)}` | `{'2026-10-07': (0, 1), '09:30': (0, 1)}`: red |

The test holds the four printed forms of a run stamp as masked and the appointment, in a CSV row and in a table cell,
as counted.

## The planted mistake

`services/console/app.py`, the page frame's `ui_attrs`: with density "compact", every page also carried
`data-planted="MRN-000123"` (the stand-in's chart number, a patient value). The case `[crc-ja]` went red at its first
compact combination, `{'density': 'compact', 'text_size': '100', 'mode': 'system', 'lang': 'ja'}`, with 58 routes
wider, e.g. `{'/account': {'MRN-000123': (0, 1)}}`. Restored: `cmp` with `git show HEAD:trialbox/services/console/app.py`
gives no difference. The plant was run on both versions of the walk (the shared-loop test client, then `_OneLoop`).

## Runs

From `trialbox/`, on the branch:

- each test of the file alone (`pytest <file>::<test>`, three processes at a time): 52 of 52 passed;
- the file in reverse order (`-n 0`, the 52 ids reversed): 52 passed in 1,655 s;
- the file normally as CI runs it (`-n 4 --dist worksteal`): 52 passed in 391 s, the longest case 57 s
  (load 0.95 at the start, 3.34 at the end);
- `tests/console/test_prefs_layout_10f1.py`: 1 passed;
- `pytest tests/unit -k "ratchet or error_text or decision_by"`: 46 passed;
- `make lint`, `tools/doclint.py`, `make data-scan`, `make security-scan`, `tools.limits_lint`,
  `tools.decisions_index --check`, `tools.findings_register --check`: clean; the findings file appended to a copy of
  the register with `--add-from` (348 rows, well formed; the register itself is not touched);
- `make cross-card PYTEST_N=1`: 326 passed; `make guard`: 1,191 passed, 1 skipped, 11 xfailed;
- `pytest tests --collect-only -q`: rc 0, 23,052 tests.

## Not verified

- CI: no CI job was run by the card; the CI seconds per case under `-n auto` are not measured.
- A planted route opening (a denial turned into a success under a preference) was not run against the live walk;
  `test_the_invariant_sees_an_extra_patient_column_and_a_denial_turned_into_a_success` holds the comparison as data.
- The masking trusts that a patient value is never an instant of the run: a seed that writes a patient time at the
  run's own time (within 14 hours, for a stamp without an offset) would be masked.
- A page that prints the run's time without a date, or split across tags, would not be masked; the survey found none.
