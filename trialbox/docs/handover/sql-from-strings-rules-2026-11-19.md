# The SQL-from-strings rules over the tree (10G-42 (b), lane H, 2026-11-19)

**Reader:** the people who build TrialBox: the lane lead and the integrator, lane J (the fixes), the lanes that own
the files (B2, C2, D) and lane V (the findings register). For builders, so in one language.

Plan 10 row 10G-42 ([plan 10](../plan/47-plan-10-2026-11-18.md), Track G, defect (g)), part (b): "about 15 rules
written here (no registry rule copied in)", under decision 115 (ruled "ok"). Part (a) is D-928 (ruff's S608 counted
per file, a new site fails: `tests/unit/test_sql_from_strings_ratchet.py`); part (c) is the page of 164 classified
sites ([sql-sites-classified-2026-11-18.md](sql-sites-classified-2026-11-18.md), card `H10G42`), whose test warns
rather than fails (the integrator's ruling of 2026-11-18). This page changes no product file. Decision:
[D-1344](../decisions/D-1344-sql-from-strings-rules-run-as-our-own-ast-check.md).

## The engine

The row names Semgrep CE (review 21, OT-4). Semgrep's pip package resolves to 67 packages for Python 3.12, the
OpenTelemetry stack among them: a second hashed tool lock and its own lock check in `tools/supply_chain/lock.py`, and
rule tests that could not run in the `.venv` that `uv.lock` makes. The same rules therefore run on Python's own `ast`
in `tools/sql_rules.py`: no new dependency, no lock change, no network, nothing sent anywhere. Like Semgrep CE, the
analysis stays inside one function (a name is followed back to its assignments in that function only).

    python -m tools.sql_rules --rules                 # the fifteen rules
    python -m tools.sql_rules --json OUT.json         # services/ libs/ deploy/, report-only (exit 0)
    python -m tools.sql_rules --check                 # exit 1 on a new hit or a stale ledger line

## The rules

Written from how this code builds SQL (`execute`, `fetchval`, `fetchall`, the stores' `query`, `_all`, `_run`; psycopg
`copy`; DuckDB `SET` and `LOAD`; sqlalchemy `text`; psycopg `sql.SQL`). A value is safe by its form when it is a
literal, `int()` or `len()` of anything, a run of `?` or `%s` marks, an UPPER_CASE constant, `sql.Identifier`, or a
local name whose every assignment (or loop) is one of these. Each rule has a positive and a negative fixture in
`tests/fixtures/sql_rules/`.

| Rule | What it hits | Starts at |
| --- | --- | --- |
| SQLS01 | an f-string with a non-constant value as the SQL text of an execute-like call | Medium |
| SQLS02 | a `%`-formatted string as that SQL text | Medium |
| SQLS03 | a `str.format()` string as that SQL text (not psycopg's `sql.SQL(...).format`) | Medium |
| SQLS04 | a concatenation with a non-constant part as that SQL text | Medium |
| SQLS05 | a `str.join()` of non-constant parts as that SQL text | Medium |
| SQLS06 | a local variable built from strings, then passed as SQL text | Medium |
| SQLS07 | SQL text grown with `+=` by a non-constant part, then passed | Medium |
| SQLS08 | sqlalchemy `text()` given SQL built from strings | Medium |
| SQLS09 | psycopg `sql.SQL()` given a built string | Medium |
| SQLS10 | a COPY statement built from strings | Medium |
| SQLS11 | a value written as a quoted SQL literal (`'{x}'`), not escaped | High |
| SQLS12 | an identifier quoted by hand (`"{x}"`), embedded quotes not doubled | Medium |
| SQLS13 | an `IN (...)` list made by joining values, not placeholders | High |
| SQLS14 | a `LIMIT` or `OFFSET` value without `int()` | Low |
| SQLS15 | an environment variable reaches SQL text | Low |

"Starts at" is the severity before review; each finding below gives its own, with its basis.

## The run (master f6c42230, `services/`, `libs/`, `deploy/`)

107 hits in 24 files. Ruff's S608 finds 164 sites on the same tree; most are safe by their form here (placeholders,
constants, `int()`), and some hits are not S608 sites at all (DDL, `SET`, `GRANT`, `COPY`, which S608 does not read).

| Rule | Hits | Reviewed safe (ledger) | Open findings |
| --- | --- | --- | --- |
| SQLS01 | 50 | 36 | 14 |
| SQLS04 | 6 | 6 | 0 |
| SQLS06 | 2 | 1 | 1 |
| SQLS08 | 2 | 2 | 0 |
| SQLS10 | 1 | 1 | 0 |
| SQLS11 | 18 | 7 | 11 |
| SQLS12 | 25 | 20 | 5 |
| SQLS13 | 1 | 1 | 0 |
| SQLS14 | 2 | 0 | 2 |
| SQLS02, 03, 05, 07, 09, 15 | 0 | 0 | 0 |
| **All** | **107** | **74** | **33** |

Every safe hit has its reason in `tools/sql_rules_ledger.yaml` (`reviewed`: file, rule, count, reason; the form of
`tools/security_scan_ignores.yaml`, kept separate from any other ledger). A hit on a place that part (c) classed
1 or 2 carries that class as its reason; the 69 hits on places part (c) did not class were read here. `tools/` is not
in the scope (80 hits; build-time tools, outside D-928's trees) and was not reviewed.

## Findings

New (card `H10G42B`, [findings.json](sql-from-strings-rules-2026-11-19/findings.json)); the fixes go to lane J.

| Id | Place | Severity | Basis | What |
| --- | --- | --- | --- | --- |
| H10G42B-01 | `services/lake/store.py:1641` (and 1642, 1643) | Low | shown | `TB_LAKE_MEMORY_LIMIT`, `TB_LAKE_TEMP_DIR` (or `TB_LAKE_DIR`) and `TB_LAKE_MAX_TEMP` go into DuckDB `SET ... = '{value}'` unescaped, before `lock_configuration`; DuckDB's `execute` runs every statement of a text (a synthetic value with a quote then `CREATE TABLE` ran on duckdb 1.5.5) |
| H10G42B-02 | `services/lake/store.py:1434` (and 1435) | Low | shown | the same values in the lake build's `SET` lines |
| H10G42B-03 | `libs/tb_common/db.py:500` | Low | hypothesis | `Database.adopt` writes `pg_class.relname` into `ALTER ... OWNER TO` in hand-made double quotes, as the admin; a restored dump with a quote in a relation name would end the identifier |
| H10G42B-04 | `services/datacore/pgfunc.py:42` | Low | hypothesis | the table name of a disabled trigger, read from the catalogue, in hand-made double quotes |

Low because the actor already holds what the value comes from: the service's environment (01, 02) or a database
restore (03, 04).

Open hits that are part (c)'s findings, counted under their ids in the ledger's `findings` list and not repeated:
H10G42-01 (`services/console/demo_guard.py:298`, 4 hits), H10G42-16 (`services/lake/store.py:630`), H10G42-17
(`services/omop/export.py:276`), H10G42-18 (`services/omop/partitions.py:108`; the rules also hit 106, 112 and 114 of
the same loop, the same int year in the partition name and bounds: 8 hits), H10G42-19 (`partitions.py:123`), H10G42-23
and H10G42-24 (`services/vec/store.py:117`, `:122`: the model literal and `LIMIT k`, 4 hits).

## Wiring and what is not covered

* CI: the `security` job runs the rules with `--json` after bandit and keeps the result as an artefact; the step
  never fails (report-only). `make sql-rules` runs the same. `--check` passes on this tree; making it a gate is the
  integrator's call, since part (c)'s test warns and D-928's ratchet already fails a new f-string into `execute`.
* `tests/unit/test_sql_rules.py`: each rule on its two fixtures (30 cases), the ledger's form and finding ids, the
  exit codes, and the tree against the ledger as a warning.
* Not covered: SQL text a function returns instead of running (the criteria compiler's generator, H10G42-02 to -15;
  ruff's S608 reads it); a value that reaches SQL through another function (single-function analysis); the other
  classes review 21 lists for its Semgrep rules (`|safe`, `shell=True`, `yaml.load`, `tarfile`, timeouts, `pickle`).
