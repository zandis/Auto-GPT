# Bandit weekly and the inline-suppression ledger (2026-11-19)

**Reader:** the people who build TrialBox: lane H, the security officer who signs the ledger, and the integrator.
For builders, so in one language.

Plan 10 row 10G-39 (OT-1 of review 21), decision D-1338, under decision 115 as ruled ("ok": build-time open tools in
CI, each pinned, each writing SARIF or JSON). Base: master f6c42230.

## What changed

- `tools/inline_suppressions.yaml` (new): one reviewed entry per `# nosec` and per `# noqa: S...` line of code
  today: file, rule, the line's code, verdict (`safe`, or `finding` with its id), reason, reviewer, reviewed date and
  review-by date (at most 180 days ahead, as the supply-chain allow-list dates its entries).
- `tools/inline_suppressions.py` (new): reads the comments of every tracked Python file (with `tokenize`, so a string
  is never a comment) and fails on a suppressed line with no entry, on an entry that matches no line, on a malformed
  entry and on a lapsed review date. `make lint`, `make ci` and the `checks` job of `trialbox-ci.yml` run it.
- `tools/bandit_weekly.py` (new), `make bandit-weekly`, `.github/workflows/trialbox-bandit-weekly.yml` (new): bandit
  over every tracked `.py` of trialbox/ (tests included) with no severity or confidence filter and `--ignore-nosec`;
  SARIF 2.1.0, bandit's JSON without code excerpts and a summary, kept 90 days. Weekly and by hand only, never on a
  pull request or a train; the scan step may not fail the run. Bandit is the uv.lock pin (1.9.4 with its sha256),
  installed by `make venv`. Bandit's own `-f sarif` needs two packages that are not in the lock, so the tool writes
  the SARIF from bandit's JSON.
- Not changed: `make security-scan` and `tools/security_scan_ignores.yaml` (the gate), and every suppressed line.

## The counts

| What | Review 21 | Today |
| --- | --- | --- |
| `# nosec` lines | 16 in 10 files | 14 in 8 files |
| `# noqa: S...` lines | 8 in 8 files | 8 in 8 files |

The review's 16 were a case-insensitive text search: two of them are the word "nanoseconds" in comments of
`tools/supply_chain/vulns.py` and `tools/trialbox/logs.py`, not suppressions. Read as comments, there are 14.

Bandit 1.9.4, one local run, no filter, `--ignore-nosec`, 2,054 tracked files, 61 s: **36,747 findings**,
HIGH 8 (all high confidence), MEDIUM 379 (53 high, 114 medium, 212 low confidence), LOW 36,360 (B101 assert alone is
34,896). The 8 HIGH: B701 twice (`libs/tb_common/llm.py:60`, the prompt renderer, ledgered safe;
`compile_cql/generator.py:50`), B602 twice (`tools/complete_run.py`), B324 four times (two in tests, `tools/jpcore_rules.py`,
`tools/pglocal.py`); the six outside tests are those review 21 counted, all in the reviewed ignores of the gate.

## The review of the 22 lines

21 are safe as written; the reasons are in the ledger. One is not:

| Id | Severity | Basis | Line | What |
| --- | --- | --- | --- | --- |
| H10G39-01 | Low | shown | `services/criteria_compiler/terminology/installed.py:145` (`_xml`) | the guard looks for `<!DOCTYPE` and `<!ENTITY` in the raw bytes; a UTF-16 document holds neither as bytes, passes, and ElementTree expands its internal entity (shown with expat 2.9.0). External entities are not fetched and expat's amplification limits still apply, so the reach is small; the fix (decode first, or `defusedxml`) is the terminology owner's |

`services/rc_sim/app.py:312` has the same guard but reads a decoded `str`, where it holds; it is ledgered safe.

## What is not verified

- The workflow has not run on GitHub: actionlint and the runner were not available here (no Docker). Its shape is
  held by `tests/unit/test_bandit_weekly.py`.
- The ledger's reviewer is lane H's reading of the code; the security officer's signature (review 21 section 5.2)
  is still owed.
- `docs/security/11-secure-development-mapping.md` and `docs/validation/ssdf-iec81001.csv` still say the nosec lines
  are outside the ledger; their rows move when the owner of those pages updates them.
