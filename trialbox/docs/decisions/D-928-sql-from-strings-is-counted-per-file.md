# D-928 SQL built from strings is counted per file, and a new site fails CI

- **Task:** 10G-42 part (a) (plan 10, defect (g); OT-4 of the open-tool security review), lane B2 · **PR:** `agent/10G-42a-sql-from-strings-per-file` · **Date:** 2026-11-19 · **Status:** accepted · **Builds on:** D-206

1. Ruff's S608 (SQL built from an f-string or a concatenation), S105 and S106 (a password-like name given a literal) were in the global ignore list. A new f-string into `execute` passed every gate.
2. They are off the global list. Each of the 44 files that has such a site today is ignored per file in `pyproject.toml`, with its count in a comment: 164 S608 in `services/` and `libs/` and 2 in `deploy/`, plus 6 S105.
3. `tools/sql_from_strings.json` holds every file's count. `tests/unit/test_sql_from_strings_ratchet.py` runs ruff with the three rules alone and no configuration over `services/`, `libs/` and `deploy/`, and requires exactly those counts. A new site fails, naming every site of its file; a fixed site lowers its count, so the table stays the list part (c) reviews.
4. Part (c), the review of each site ("identifier from code" or fixed), is lane B2's next card. Part (b), the Semgrep rules, waits for decision 115.
5. Tests: the counts as the table holds them; the three rules out of the global list; the rule firing on a new f-string into `execute`.
