# H147: run and publish ids the log's scrubber leaves whole

**Reader:** the people who build TrialBox: the lane H lead, lane J and the integrator. Findings for builders, so in
one language.

- **Card:** H-147 (Medium, before the freeze), from the integrator's 7164002927 and the external review's 7163988253
  on #1513: a run id that holds a phone-shaped digit run is masked by the log's scrubber, so the log line no longer
  holds the id (CI-1)
- **Date:** 2026-11-25
- **Base:** master 440089e8
- **Change:** one id helper, `libs/tb_common/ids.py`, used by the adapter's three draw sites; the scrubber is as it was
- **Findings:** [`h147-ids-unmasked-2026-11-25/findings.json`](h147-ids-unmasked-2026-11-25/findings.json)
  (H147-01 to H147-05)

## Files outside the card

Lane R had this defect; lane R is stopped and the integrator gave it to lane H (7164002927). Lane J's file, body
only:

- `services/adapter/app.py`: the three `os.urandom(8).hex()` draws (a run, a publish, a publish done already) are
  `ids.log_safe_id()`, and `tb_common.ids` is imported

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
- The checks of CLAUDE.md: `make lint`, `doclint`, `make data-scan`, `make security-scan`, `limits_lint`,
  `decisions_index --check`, `findings_register --check`, `make guard`: clean. `make cross-card`: 329 passed.
  Collection: 26,698 tests, rc 0.
- The policy set (247 files), the card's test and the 10 test files of `services/adapter/app.py` (257 files), in
  own clones at ac92c6f4 under CI's conditions (umask 022, `env -i`, `PYTEST_ADDOPTS="--cov --cov-report=
  --durations=30"`, `COVERAGE_CORE=sysmon`, `-n auto --dist worksteal`, a marked `TB_TEST_ROOT` of more than 100
  characters with `TMPDIR` 0700 inside it): as root 6,013 passed, 9 skipped; as an ordinary user (`nobody`) 6,009
  passed, 13 skipped.
- `tests/unit/test_adapter_failure_words.py` 20 times under the same conditions: 23 passed each time, 20 of 20.

## What was not run or not verified

- The whole unit and integration run: not run. `services/` changes at three lines and `libs/` gains one new
  module; no existing function changed.
- The ordinary-user run used the account `nobody` (creating a user was refused in this container); its venv was
  built by that user from the lock.
- The 20 runs cannot show a 1-in-140 flake gone; the draw tests (200,000 draws) and the planted draw are the proof.
- The compiler's `error_id` and the cascade ULID are not changed: other lanes' files (question to the integrator).
