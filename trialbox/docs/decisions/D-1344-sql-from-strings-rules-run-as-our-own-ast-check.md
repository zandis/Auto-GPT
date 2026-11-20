# D-1344 The SQL-from-strings rules run as our own AST check, report-only (10G-42 (b))

- **Task:** lane H, plan 10 row 10G-42 part (b) (defect (g); review 21, item OT-4b) · **Date:** 2026-11-19 ·
  **Status:** accepted · **Builds on:** D-928 (part (a), the ruff ratchet), decision 115 of plan 10 (the CI
  open-tools approval, ruled "ok")
- **Decision:**
  - Fifteen rules for SQL built from strings, written here from how `services/` and `libs/` build SQL; no registry
    rule is copied in. They are `tools/sql_rules.py` (`RULES`, `SEVERITY`), each with a positive and a negative
    fixture under `tests/fixtures/sql_rules/` and a test that runs it on both (`tests/unit/test_sql_rules.py`).
  - **Engine.** The row names Semgrep CE. Its pip package resolves to 67 packages for Python 3.12 (the OpenTelemetry
    stack among them), so it would be a second hashed tool lock beside `tools/supply_chain/pip-audit.lock`, with its
    own lock check in `tools/supply_chain/lock.py`, and the rule tests could not run in the `.venv` that `uv.lock`
    makes. The rules run on Python's `ast` instead: no new dependency, no lock change, no network, no metrics, and
    the tests run in every shard. Like Semgrep CE, the analysis stays inside one function. Decision 115's conditions
    (build-time only, pinned, JSON out) hold: nothing ships, the code is in the repository, `--json` writes the
    result.
  - **Ledger.** `tools/sql_rules_ledger.yaml`, the form of `tools/security_scan_ignores.yaml`: per file and rule a
    count and a reason (`reviewed`), and the hits that are open findings counted by finding id (`findings`). A file
    with more hits than its lines account for reports all of them; a file with fewer names the stale line.
  - **Wiring: report-only.** The `security` job runs it with `--json` and keeps the result; it does not fail. Plan
    10's ruling for 10G-42 is that the page test warns, and D-928's ratchet already fails a new f-string into
    `execute`. `--check` (exit 1 on a new hit or a stale line) exists for the day the integrator makes it a gate;
    the tree passes it today. The tree test warns on a difference.
  - **Scope:** `services/`, `libs/` and `deploy/`, the trees D-928 counts. `tools/` is not reviewed (80 hits on
    master f6c42230; build-time tools).
  - **Findings:** card `H10G42B` ([page](../handover/sql-from-strings-rules-2026-11-19.md)): four new Low findings;
    the other open hits are H10G42's.
- **Not done here:** the other classes review 21 lists for its Semgrep rules (`|safe`, `shell=True`, `yaml.load`,
  `tarfile`, `requests` without a timeout, `pickle`); SQL text returned rather than executed (the criteria
  compiler's generator) is left to ruff's S608, which D-928 gates.
