# H147: run and publish ids the log's scrubber leaves whole

**Reader:** the people who build TrialBox: the lane H lead, lane J and the integrator. Findings for builders, so in
one language.

- **Card:** H-147 (Medium, before the freeze), from the integrator's 7164002927 and the external review's 7163988253
  on #1513: a run id that holds a phone-shaped digit run is masked by the log's scrubber, so the log line no longer
  holds the id (CI-1)
- **Date:** 2026-11-25
- **Base:** master 440089e8
- **Change:** one id helper, `libs/tb_common/ids.py`, used by the adapter's three draw sites, the criteria compiler's
  error id and the console's cascade run id; the scrubber is as it was
- **Findings:** [`h147-ids-unmasked-2026-11-25/findings.json`](h147-ids-unmasked-2026-11-25/findings.json)
  (H147-01 to H147-09)

## Files outside the card

Lane R had this defect; lane R is stopped and the integrator gave it to lane H (7164002927). Lane J's file, body
only:

- `services/adapter/app.py`: the three `os.urandom(8).hex()` draws (a run, a publish, a publish done already) are
  `ids.log_safe_id()`, and `tb_common.ids` is imported

Under the integrator's ruling 7166734383 (lane A2 is stopped), bodies only:

- `services/criteria_compiler/app.py`: a 500's `error_id` is `ids.log_safe_id()`, not `uuid.uuid4().hex[:12]`
  (H147-02)
- `tests/unit/test_compiler_answers_every_failure.py`: **a changed assertion**, under that ruling:
  `test_a_bug_is_a_500_with_an_id_and_its_trace_in_the_audit` asserts `len(detail["error_id"]) == 16`, not `== 12`
- `services/console/cascade.py`: a cascade run's id is `ids.log_safe_id()`, not `new_ulid()` (H147-03; the one line
  and its import)

The card's own: `libs/tb_common/ids.py` (new), `tests/unit/test_h147_ids_unmasked.py` (new), this page and its
findings. `tests/unit/test_adapter_failure_words.py` is not changed: the failing test keeps its assertion.

## Why

The run record sends its reader to the log by the run's id (`failure.words`: "...; run <id>"). Every log line goes
through `tb_common.logging.redact`. An 8-byte hex id holds a digit run the scrubber reads as a phone number about 1
draw in 130 (39 of 5,000 measured): CI's draw (job 139204992870) held a 10-digit run that starts `09`, a Taiwan mobile number to the
pattern `(?<!\d)(?:\+886[-\s]?|0)9\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)`, so the line said `d6d8b[PHONE]a`.

## The rule, from the scrubber's patterns

- The identifier rules (`_PHI_PATTERNS`: Taiwan ID, My Number, insurance numbers, postcodes, phone numbers) and the
  site's chart-number rule as shipped (`\d{8}`) each need a digit.
- The note masker's rules (`phi_guard.note_spans`) each need a digit, a capital letter (names, the Taiwan ID), an `@`
  (email) or a label word with its mark.
- The secret rules need a `:` or `=` after a secret's name, `bearer`/`basic` and a space, `://` with a password, or a
  value the process holds (8 characters or more).

An id of lower-case ASCII letters holds none of these. A site can still set a chart-number pattern that reads
letters, and the process holds its own secrets, so the helper asks the scrubber once per draw (`run <id> failed`)
and draws again when the line would change. In 1,000,000 draws with the shipped rules, none was drawn again.

The redraw stops after 32 draws (`ATTEMPTS`, from the review's 1515-1). A site pattern that reads letters, such as
`^[A-Za-z0-9]{6,20}$` (the settings take any pattern), changes every draw: without a bound `POST /run` and
`POST /publish` spun for ever while they held the adapter's run gate. After the bound the helper hands out the last
draw. It is a valid id, and on such a site its log line shows the rule's kind, as a hex id's did. The helper does
not try to find letters the site's pattern leaves alone: a pattern is free text, and the simple rule is enough. A
rule that refuses one draw in a million refuses 32 in a row with odds of 10^-192.

Strength: 16 letters of 26, 16 x log2(26) = 75.2 bits, against 64 for the hex id; the length is the same.

Ids already stored: the adapter keeps runs in memory and, for a run of an earlier life, reads `runs/<id>.json`
when the id is `str.isalnum()` (`app.run_state`, `runs.read`, `runs.all_runs`). Old hex ids and new letter ids both
pass. The orchestrator takes the id from the answer's `run` field and the `X-TB-Run` header and does not parse it.

## What ran (session container, Python 3.12)

- Failing first, the new test at master 440089e8: collection error (no `tb_common.ids`). Master with only the
  helper added (the adapter as on master): 2 failed, 5 passed; the failures are
  `test_every_id_the_adapter_hands_out_is_drawn_by_the_helper` and
  `test_the_log_line_of_a_failed_run_holds_the_whole_id_with_a_cut_draw_planted`. At the head: 7 passed.
- Draws: 100,000 seeded and 100,000 from the system generator, none changed by the scrubber in three line forms, all
  unique; 1,000,000 more with the shipped rules, none refused; the old hex draw, 39 of 5,000 changed.
- Other ids that reach a log line: the compiler's `error_id`, 1,251 of 200,000 changed (H147-02); the console's
  cascade ULID, 59 of 200,000 (H147-03).
- The repository's checks: `make lint`, `doclint`, `make data-scan`, `make security-scan`, `limits_lint`,
  `decisions_index --check`, `findings_register --check`, `make guard`: clean. `make cross-card`: 329 passed.
  Collection: 26,698 tests, rc 0.
- The policy set (247 files), the card's test and the 10 test files of `services/adapter/app.py` (257 files), in
  own clones at ac92c6f4 under CI's conditions (umask 022, `env -i`, `PYTEST_ADDOPTS="--cov --cov-report=
  --durations=30"`, `COVERAGE_CORE=sysmon`, `-n auto --dist worksteal`, a marked `TB_TEST_ROOT` of more than 100
  characters with `TMPDIR` 0700 inside it): as root 6,013 passed, 9 skipped; as an ordinary user (`nobody`) 6,009
  passed, 13 skipped.
- `tests/unit/test_adapter_failure_words.py` 20 times under the same conditions: 23 passed each time, 20 of 20.

## The review of #1515 (b7fc5914), fixed at fab3329f

- 1515-1 (Medium, H147-07): the bound above. Two tests, both failing at b7fc5914 (2 failed: the scrubber was asked
  more than 1000 times; `POST /run` answered 500 from the counted scrubber instead of spinning) and passing at
  fab3329f: `test_a_site_rule_that_reads_letters_does_not_hang_the_draw` (32 asks, then an id) and
  `test_a_run_is_started_under_a_site_rule_that_reads_letters` (202). The card's file: 9 passed.
- 1515-2 (Low): the comment of `runs._path` is H147-05, Lane J's, open.
- 1515-3 (Low, H147-06): this page named the repository's agent-instructions file; it says "the repository's
  checks" now.

## H147-02 and H147-03, fixed at 4eb0c2b1

- The compiler's `error_id` was cut by the scrubber 1,251 of 200,000 times; the console's cascade ULID 59 of
  200,000. Both are logged and are what a reader finds the line by.
- Old ids still read back: `CascadeRuns.get` takes any `str.isalnum()` id and the list sorts by its start; the
  compiler's id is not stored or parsed (the audit event carries it as text).
- One test each, with a cut draw planted where the old id came from: at fab3329f 2 failed, at 4eb0c2b1 2 passed.

## What ran for the review and the ruling (head 3d5f6ee9)

- The card's file: 11 tests. The four new ones fail before their change: 1515-1's two at b7fc5914 (2 failed),
  H147-02's and H147-03's at fab3329f (2 failed); all pass at the head.
- The repository's checks again at the head: clean. `make cross-card`: 329 passed. Collection: 26,702 tests, rc 0.
  `-k "findings or doclint or handover"`: 391 passed.
- The set under CI's conditions, as above, with the test files of the two new files added (264 files: the 257, the
  compiler's 5 and the cascade's 3, less one already in): as root 6,266 passed, 10 skipped; as an ordinary user
  (`nobody`) 6,262 passed, 14 skipped.
- A first run of that set at 4eb0c2b1 had 1 failed in both: `test_the_compilers_error_id_is_logged_whole` read the
  service's stdout, and under `-n auto` an earlier test in the worker had bound the service's handler to another
  stream (empty stdout). The test now reads the line through the service's own formatter (3d5f6ee9); the earlier
  set at fab3329f (257 files) was green: root 6,015 passed, ordinary user 6,011 passed.

## The review of #1515 at 6229578d, fixed at ae92db6a

- 1515-4 (Medium, H147-09): `tests/e2e/console_poc.js` waited for `/pilot/cascade/[0-9A-Z]+`; the wait now takes
  `[0-9A-Za-z]+`, the letter id and a ULID kept from before. A unit test reads the wait from the script and checks
  a letter id, a ULID and the bare list page: 1 failed at 6229578d, passing at ae92db6a. The script parses
  (`node --check`). The walk itself needs the compose stack: `tests/e2e/test_console_poc.py` skips here (7 skipped).
- Searched for other shapes: the walks, `tests/console`, `tests/e2e` and the e2e helpers. The
  `[0-9A-HJKMNP-TV-Z]{26}` patterns are job ids (still ULIDs); the hex patterns are boot ids, key ids, pids, account
  requests and not-matched samples. None reads a cascade run id, an adapter run id or a compiler error id by shape.
- 1515-5 (Low, H147-08): the changed assertion pins the length only. Open, not in this push.

- At ae92db6a under CI's conditions (as above), the card's file and `tests/e2e/test_console_poc.py`: as root 12
  passed, as an ordinary user (`nobody`) 12 passed; the walk's test is deselected there (`not e2e`) and skips
  without the stack.

## What was not run or not verified

- The whole unit and integration run: not run. `services/` changes at three lines and `libs/` gains one new
  module; no existing function changed.
- The ordinary-user run used the account `nobody` (creating a user was refused in this container); its venv was
  built by that user from the lock.
- The 20-run loop of `test_adapter_failure_words.py` was run at ac92c6f4, not again at the head (the adapter's draw
  is the same; only the bound was added).
- The 20 runs cannot show a 1-in-140 flake gone; the draw tests (200,000 draws) and the planted draw are the proof.
- The publish-done-already path under a letter-reading site rule (thread pile-up) was reasoned, not reproduced;
  the bound covers it, as every draw site goes through the helper.
