# D-1338 Every inline security suppression has a reviewed ledger line, and bandit runs weekly with no filter

- **Task:** 10G-39 (plan 10, track G; OT-1 of review 21), lane H · **Date:** 2026-11-19 · **Status:** accepted ·
  **Builds on:** decision 115 (ruled "ok"), T-654, D-928

1. Every line that carries a `# nosec` (bandit) or a `# noqa: S...` (ruff's security rules) has one entry in
   `tools/inline_suppressions.yaml`: file, rule, the line's code, verdict (`safe`, or `finding` with its id), reason,
   reviewer, reviewed date and a review-by date at most 180 days ahead. A defect is never filed as safe.
2. `python -m tools.inline_suppressions --check` (in `make lint`, `make ci` and the `checks` job) fails on a
   suppressed line without an entry (a planted `# nosec`), on an entry that matches no line, on a malformed entry and
   on a lapsed review date. It reads comments with `tokenize`, so text in a string is never counted.
3. `make bandit-weekly` and `.github/workflows/trialbox-bandit-weekly.yml`: bandit over every tracked Python file of
   trialbox/ with no severity or confidence filter and `--ignore-nosec`, SARIF 2.1.0 and JSON without code excerpts,
   kept 90 days; weekly and by hand only, report only (exit 0 on findings; the step may not fail the run). Bandit is
   the uv.lock pin with its hash, installed by `make venv`; the SARIF is written from bandit's JSON because bandit's
   own SARIF formatter needs packages outside the lock.
4. The gate is unchanged: `make security-scan` with `tools/security_scan_ignores.yaml`. The ledger is the reviewed
   record of the inline suppressions, not an allow-list of the gate.
5. On master f6c42230: 14 `nosec` lines (review 21's 16 counted "nanoseconds" twice) and 8 `noqa: S` lines; 21 safe,
   one finding (H10G39-01, the ICD-10 XML guard read in UTF-16).
6. Tests: `tests/unit/test_inline_suppressions.py`, `tests/unit/test_bandit_weekly.py`.
