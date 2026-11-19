# D-927 The log scrubber masks what the note masker masks

- **Task:** LOG-JA (lane J's proposed card on #639, from #1091's "not covered"), lane B2 · **PR:** `agent/LOG-JA-scrubber-runs-the-maskers-rules` · **Date:** 2026-11-19 · **Status:** accepted · **Builds on:** D-450, D-923, #1091

1. **The gap:** `tb_common.logging.redact`, the scrubber every service's JSON log runs, kept its own short list (a Taiwan ID, My Number, insurance and phone numbers, a postcode, the chart number). A name, an address or a date of birth went out as written.
2. **The masker's spans:** the scrubber now also reads `phi_guard.note_spans`, so names, addresses, dates of birth, IDs, beds and rooms in Chinese, Japanese and English are masked, each replaced by its kind (`[NAME]`, `[ADDRESS]`, ...). A rule added to the masker reaches the logs too.
   - Every rule (the secrets, the identifier patterns, the chart number, the masker) reads the line as written. The spans are joined and replaced once, and a secret's span says `[SECRET]`.
   - Applied one after another, a secret's token took the label a name was found by, and a secret with an identifier inside it could lose its exact match.
3. **Which fields:** the message, every extra field (texts inside dicts, lists and tuples too) and the traceback.
4. **Limits on failure and length:**
   - A scrubber that raises withholds the line and names the error's type; it is never written unscrubbed.
   - A masker that cannot be loaded stops `setup_logging`.
   - A line longer than `TB_LOG_SCRUB_MAX_CHARS` (65,536; the masker reads about 1 µs a character under the handler's lock) keeps its first and last halves; the middle is never written.
5. **Review, tests and known limits:**
   - An adversarial review found two leaks (non-text fields; the order of the rules), the silent withholding on a failed import, and the cost; each is fixed and in the tests.
   - Tests: `tests/unit/test_log_scrubber_runs_the_maskers_rules.py`.
   - Known: a `key=value` line (`name=` or `dob=` and its value) is not masked, because the masker has no such label (a masker card, proposed). A 12-digit count, a service mailbox and a number after `Bed` are masked (under 1 % of the operational lines the review filled).
