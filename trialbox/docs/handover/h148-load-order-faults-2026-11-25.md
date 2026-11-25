# H148: six load and order faults of the bench's full set, and one midnight

**Reader:** the people who build TrialBox: the lane H lead, lanes K and N and the integrator. Findings for builders,
so in one language.

- **Card:** H-148 (the integrator's 7164913377 on #1504): six ids failed in some of three parallel full-set runs at
  6e502f578, so load or order faults; one more added by 7167784716 (a run that crossed the site's midnight)
- **Ruling:** 7167587625 (after the external review's advice 7167335243) for the three test changes of ids 1, 4, 5
- **Date:** 2026-11-25
- **Base:** master 440089e8, merged with master 6d8ad1a6
- **Findings:** [`h148-load-order-faults-2026-11-25/findings.json`](h148-load-order-faults-2026-11-25/findings.json)
  (H148-01 to H148-11)

## The ids

"Load" below is this container (4 CPUs) with 8 to 16 Python busy loops and a disk writer beside the tests. The
bench ran three full sets at once; none of its failing lines reached this card, so a cause is shown here by a probe or
a planted fault, never by the bench's own run.

| Id | Test | Cause | Evidence | Fix or explanation | Runs before / after |
| --- | --- | --- | --- | --- | --- |
| 1 | `test_console_timing::test_a_planted_slow_page_fails_the_walk_and_the_ten_pages_pass` | the ten real pages were walked at warm-up 1, repeat 3: a page's p95 is the slowest of 3 answers, so one slow answer in each of its two walks fails a page whose own work is fast | idle: answers 3.8 to 57 ms; 16 busy loops: single answers up to 248 ms (week) and 200 ms (audit trail) against the 300 ms budget. Planted (a 400 ms answer, `total;dur=400`): one slow answer in each walk fails the old walk and passes the new; every 10th answer slow passes the old and fails the new; slow every time fails both | ruled (item 2): the ten pages at the shipped walk's 10/60, the planted page alone at 1/3, one joined report; assertions unchanged | not reproduced to failure here: 0 of 15 under 16 busy loops before; after: see "What ran" |
| 2 | `test_cloud_run::test_a_part_records_its_run_and_a_new_run_runs_it_again` (`complete_run` rc 1) | not found | 0 of 42 failed: 10 under 16 busy loops, 32 in four concurrent loops under 12; rc 1 comes from a FAILED verdict, which a lost screenshot (node, Chromium) alone gives (`tools/complete_run.py` report: `shots_ok != shots`) | ruled: no more work; reopens only if the bench shows a failing tail | 0 failed of 42 + 1 under CI's conditions |
| 3 | `test_criteria_safety::test_guarded_sql_only_ever_turns_an_answer_into_unknown` | not found | 0 of 10 alone under 12 busy loops; the file whole twice under load (22 passed each); after each of the file's 21 other tests, in that order: 21 of 21 passed (no order fault); `IDX` is a fixed date | ruled: no more work; reopens only if the bench shows a failing tail | 0 failed of 33 + 1 under CI's conditions |
| 4 | `test_g1_box_install_run::test_rehearsal_case[session-stop]` | a rehearsal minute was 1 s: with the cap of 60 and its margin of 10, the bring-up had 50 s to open the session and 58 had 10 s to close it before the cap | 12 busy loops, minute 1: open at +35 s, stop +50, closed +52, off +53 (cap at +60). Planted 26 s slower bring-up (the case's own `images-seconds` knob): minute 1 fails (no account opened), minute 2 passes (open +45, stop +100); 20 s: both pass | ruled (item 3): `standins/boot.sh` reads the minute from the knob `minute-s` (default 1), session-stop sets 2, check.py's `< 60` is `< 60 * minute` | passed under 12 and 16 busy loops before and after; the planted runs above |
| 5 | `test_gateway_under_load::test_an_interactive_call_without_a_slot_is_busy_at_once` | the call waits the product's slot wait on purpose (`INTERACTIVE_SLOT_WAIT_S` 0.5 s), so `< 1.0` left 0.5 s for the runner | `gw.chat` timed: idle 0.511 to 0.521 s (20); 16 busy loops 0.533 to 0.764 s (30), with sysmon coverage up to 0.758 s | ruled (item 1): the slot waits the call asked for are `[INTERACTIVE_SLOT_WAIT_S]` and the call ends within the scaled call budget (3.0 s, `bound`); 503, `model_busy`, Retry-After 5 kept. Planted: a 3 s overwait in the slot wait, a 3 s stall before it and a 3 s slot wait each fail the new test; the product as it is passes | 0 of 20 under 8 busy loops before; after: see "What ran" |
| 6 | `test_poc_real_embedder::test_without_the_switch_nothing_changes` (subprocess timeout) | a product race: `alive_start` (`deploy/poc.sh`, `deploy/install.sh`) runs `sleep N &` in a subshell; `alive_stop`'s TERM that lands before `s=$!` leaves the sleep alive with the script's stdout and stderr, so the caller's pipe stays open for N s (600 s in the test, its timeout 120 s) | the bare pair `alive_start; alive_stop`, 200 times: 2 held the pipe | the sleep's streams go to `/dev/null`; failing-first `tests/unit/test_alive_sleep_holds_no_pipe_h148.py` (the subshell killed while its sleep sleeps): 2 failed before, 2 passed after | the new test: 2 failed before (both scripts), 2 passed after; `test_poc_real_embedder` and the install tests pass with the fix |
| added | `test_list_demo::test_the_demo_day_is_the_real_day` (integration) | its run takes minutes; one that crossed the site's midnight seeded yesterday and was read against today (#1518) | the integrator's line: seed 15:59:29Z, checks at 16:0xZ | the day is read before and after the run; a run that crossed it is made once more in its own folder; assertions unchanged. Demonstration: the first attempt made to look rolled over (the time read before it moved back a day) ran the second and passed (408 s) | passed as written (223 s) |
| added | box rehearsal (test), train 180, `[18] screen`: "ingest of synthetic hospital A failed" (the integrator's 7170464780) | `tools/rehearse_box/box.sh` ingested under `date -u +%F`; at 18:00Z it is 02:00 the next day at the site, so the box's own nightly ingest had made the site's newer snapshot | held clock (a stand-in `date` at 2026-11-25T18:00:00Z) running the SCREEN step's own ingest lines with the box's compose stood in: Asia/Taipei and Asia/Tokyo got 2026-11-25 before, a missing zone still ingested | the day is the site's: `site_day` reads `TB_TZ` from the box's `deploy/.env` (the product's `site_tz` with no settings object; compose requires it to be `site.tz`, D-315) and refuses no zone; failing-first `tests/unit/test_rehearse_box_site_day_h148.py`: 3 failed, 1 passed before, 4 passed after. The other rehearsal and walk scripts: their `date -u` are timestamps, `imperfect_feed` uses fixed nights, the box-run VM script already takes `TB_TZ` (`acc_today`) | the rehearsal itself was not run here (it needs the box's images and a VM) |

## The review of #1524 (OCR 7176387852 at fcf1ff8a)

- **1524-1 (H148-10):** id 5's ceiling read `SCALED`, which `bound()` makes 9.0 s in every run that measures
  coverage, so CI's unit shards are one: there a 3 s stall, a 3 s slot wait and a 3 s overwait each passed the test
  (shown here with `COVERAGE_CORE=sysmon` and `--cov`: 3 of 3 passed). The ceiling is now the call budget as written
  (`_SECONDS`, 3.0 s), OCR's patch: with coverage on, the three each fail and the product as is passes.
- **1524-2 (H148-11):** the heartbeat subshell of `alive_start` (both scripts) held the script's output and looked
  for the script with `kill -0`, which finds a zombie: a script that ended without `alive_stop` (`set -e`, TERM,
  KILL) and whose caller reads to the end before reaping kept the caller waiting for ever. The heartbeat now looks
  every second and reads the script's state in `/proc` (a zombie is ended), OCR's patch; the minute line stays a
  minute. Failing-first `tests/unit/test_alive_ends_with_its_script_1524.py` (OCR's): 6 failed before (each timed
  out at 30 s), 6 passed after; shellcheck clean.
- **1524-3 (Low):** not taken here: its follow-up is lane K's box-rehearsal card (a `TB_TZ` that is not a zone).

One more, seen once and not explained: in the policy set as root under CI's conditions,
`test_g1_box_install_run::test_rehearsal_case[session-ssh]` waited 180 s for its console to answer. It passed three
times alone under the same conditions (about 10 s each), and in the ordinary user's run; the failed run's folder was
gone before it was read (H148-08).

## Files outside the card

Changed under the ruling 7167587625 (the gateway, console and rehearsal tests) and the integrator's go 7167784716
(the list demo), bodies only:

- `tests/unit/test_gateway_under_load.py` (lane N): id 5
- `tests/console/test_console_timing.py` (lane K): id 1
- `tests/rehearsal/box-run/rehearse-box-run.sh` (lane K): id 4, the session-stop line sets the knob
- `tests/integration/test_list_demo.py`: the added id
- `tools/rehearse_box/box.sh` (lane K): the box rehearsal's ingest day (the integrator's go 7170464780)
- `deploy/poc.sh`, `deploy/install.sh`: id 6, one line each (the lead's go for the product fix), and the heartbeat's
  loop (1524-2, the lead's relay of OCR 7176387852)

Lane H's own: `tests/rehearsal/box-run/check.py` and `standins/boot.sh` (id 4), the three new tests, this page and its
findings.

## What ran

- `make lint`, `tools/doclint.py`, `make data-scan`, `make security-scan`, `tools.limits_lint`,
  `tools.decisions_index --check`, `tools.findings_register --check`, `make guard`: rc 0; `make cross-card`: 329
  passed; `pytest tests --collect-only`: rc 0, 26,860 tests.
- The policy set, the card's files and the tests of every touched file (278 files) under CI's conditions at
  8d31c201: as root 6,385 passed, 25 skipped, 7 xfailed; as an ordinary user 6,381 passed, 29 skipped, 7 xfailed.
- With shellcheck present (it was skipped above): SC2217 on the first form of id 6's fix (`</dev/null` on `sleep`),
  fixed in 07b6821f; then the 112 files that name `poc.sh`, `install.sh` or shellcheck, and the new test: as root
  3,224 passed, 5 skipped, 7 xfailed; as an ordinary user 3,222 passed, 7 skipped, 7 xfailed.
- Under 16 busy loops after the change: the gateway test 20 of 20, the console walk test 5 of 5, session-stop passed.

Under CI's conditions here means `env -i`, umask
022, `COVERAGE_CORE=sysmon`, `PYTEST_ADDOPTS="--cov --cov-report= --durations=30"`, `-n auto --dist worksteal`, a
long `TB_TEST_ROOT` marked with `tools.pglocal mark` and a 0700 `TMPDIR` inside it, SIGHUP at its default, as root in
the session's checkout and as an ordinary user in a clone of their own.

## Not verified

- The bench itself: no failing line of its runs was read; ids 2 and 3 are not explained.
- id 1 and id 5 were never made to fail by load here; their cause is shown by the probes and the arithmetic above.
- The demonstration of the added id changes the time read before the run; no run here crossed a real midnight.
