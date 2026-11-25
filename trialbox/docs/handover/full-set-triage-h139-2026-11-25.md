# H-139: full-set triage, why the bench host is red where CI is green

**Reader:** the integrator, the walk and the people who build TrialBox (lanes B2, D and J: their files are named below, not changed)

Lane H, 2026-11-25. Card H-139 (the integrator's 7150296048 on #639), from the walk's full-set run 2 on master
cf7c1917 (7150288454) and its detail (7150513283). The same tests pass in CI and fail on the bench host, so the
difference is the host. Each failing file was run again on master 6c73db64 in a container set up the way the walk
described the bench host. The cause was found by turning one condition on at a time. The data is synthetic only.

## The bench host's conditions, recreated

| Condition (the walk's report) | How it was recreated here |
| --- | --- |
| an ordinary user (uid 1003), HOME set | `setpriv --reuid=1003 --regid=1003 --init-groups env -i HOME=… PATH=…`, a git worktree that user owns, every folder above `TB_TEST_ROOT` 0755 |
| umask 0002 | `umask 0002` in the runner, compared with `umask 0022` |
| no `psql` on PATH; PostgreSQL server binaries from a package of their own | a PATH folder holding every system tool except `psql`, `pg_dump`, `pg_restore`, `pg_dumpall` (the server still from `pglocal.bindir()`) |
| `node` through a wrapper in a container (slow) | a `node` on PATH that waits 65 s before it runs the real one |
| a PostgreSQL without libxml | **not recreated**: the source build of one was refused in this session; a stand-in instead (below) |
| `-n auto`, a long `TB_TEST_ROOT` marked with `python -m tools.pglocal mark`, `TMPDIR` 0700 inside it | `-n 4 --dist worksteal`, a test root of over 100 characters, marked; `TMPDIR` 0700 inside it |

## The sorted list

(a) a host difference the product must handle; (b) a test that assumes CI's environment (fixed under H-135's rules:
no assertion changed, nothing skipped); (c) the bench host's own setup (the walk's to fix, as it said).

| File (walk's count) | Reproduced here | Cause | Kind | Fix | Lane |
| --- | --- | --- | --- | --- | --- |
| `tests/unit/test_erasure_reach.py` (226) | **no**: the module passes on master (55 passed, 183 skipped, 21 xfailed); a log of every statement its fixture sends, from a fresh database, holds no XML function or type | the walk reads its setup error as "unsupported XML feature" (a server without libxml); the statement that raised it is not known | open | wait for the walk's traceback frames and its server's `pg_config --configure` | B2 (erasure) |
| `tools/trialbox/update.py` `SCHEMA_SQL` (found in the search for the above) | yes, with a stand-in | `installed_state` (both boxes) read every store's version through `query_to_xml` and `xpath`, which a server without libxml refuses | (a) | the first read lists, per schema, the statement that reads its version (quoted by the server's `format`); the second runs them as one `UNION ALL`; no XML | H (this card) |
| `tools/rehearse_box/box.sh` (the failing restore's row count) | by its text | the same `query_to_xml`/`xpath` way of counting each table's rows | (a) | psql's `\gexec` runs each table's count statement, made by the server's `format`; the output is the same as before (checked on a test schema with a quote in a table's name) | H (this card) |
| `tests/console/test_button_targets_9k3.py` (112 errors) | yes | `node` takes over 60 s; `_node_playwright()` (`tests/console/test_cjk_layout.py:44`) runs at import inside a `skipif`, so collecting the module raises `TimeoutExpired`, once per xdist worker (112 is the bench host's worker count) | (c); a (b) part | the walk installs node and Playwright as CI has them; for lane J to decide: the check made once per session, with a timeout reported as one plain line (never a skip) | J (band 9k); not changed |
| `tests/unit/test_backup.py` (27), `test_backup_restic.py` (19), `test_backup_busy_night.py` (12) | yes, the same counts | the backup runs the bare `psql` and `pg_dump` from PATH (`TB_PSQL_CMD`, `TB_PG_DUMP_CMD` unset) | (b); an (a) part | the tests hand in the test cluster's own client tools (`tests/pg_client.py`); `backup.py` refuses plainly when a client tool is missing, naming it, instead of a bare `FileNotFoundError` | D; held for its go |
| `tests/unit/test_restore_drill.py` (10) | yes | the same | (b) | the same | D; held |
| `tests/unit/test_backup_schedule.py` (12) | 10 of 12 | the same | (b) | fixed here: `tests/pg_client.py` | H |
| `tests/unit/test_restore_from_the_host_h100.py` (17) | 16 + 1 | 16: the same; 1: umask (below) | (b) | fixed here: both | H |
| `tests/unit/test_host_commands_own_environment.py` (39) | yes, 39 of 39 | umask 0002: the box tree the fixture builds, `deploy/.env` among it, is group-writable and the product rightly refuses it ("can be written by group or others (chmod 600 it): nothing was run"); with psql off PATH one more | (b) | fixed here: `as_root_makes_it` (H-115's `tests/host_modes.py`) on the built trees; `tests/pg_client.py` | H |
| `tests/unit/test_serving_engine_h112.py` (14, unit and pure) | 13 of 14 | umask 0002: "deploy/site is not root's or this user's alone (chmod go-w)" | (b) | fixed here: `as_root_makes_it` in `_box` | H |
| `tests/unit/test_kek_env_refused_h97.py` (1) | yes | umask 0002: the test's passphrase folder is 0775 and `keys init` rightly refuses it | (b) | fixed here: `as_root_makes_it` in `_passphrase_box` | H |
| `tests/unit/test_lifecycle_keys_h133.py` (5) | no (passes at both umasks as uid 1003) | the walk's "assert 0 >= 8" is `test_lifecycle_keys_h133.py:396`: `rotate-kek` refused before its first rename | open | wait for the walk's captured stderr | H |
| `tests/unit/test_release_dirty_refused.py` (1), `tests/unit/test_first_run_code_h97.py` (1) | no | first-run: the output had begun, so probably the test's 60 s pty deadline on a loaded host | open | wait for the walk's captured stderr | H |
| compose, walks, console beyond the node wrapper, poc | not run | the console and poc "waiting until load" lines match the node wrapper | (c) probably | — | — |
| gpu (2) | not run | the suites' own path | — | stays with J-R20 and E2-11 (the integrator) | J, E2 |

## The stand-in for a server without libxml

PostgreSQL built without libxml raises `unsupported XML feature` (SQLSTATE 0A000) from the XML type's input and
every XML function. `tests/unit/test_schema_versions_no_xml_h139.py` refuses any statement that names one, as that
server would, and passes every other statement to the test cluster. The in-process box gets it on its `_pg`. The
compose box gets it on its runner, where the test cluster plays `psql` in the db container. Both boxes must read each
store's version. On master's `update.py` and `box.sh`, three of the four tests fail (`unsupported XML feature` twice,
and the rehearsal's count names `xpath`). At this head all four pass. A real server without libxml was not run.

## What was run

On master 6c73db64, then at this branch's head, the same commands:

- Ordinary user (uid 1003), umask 0002, psql off PATH, over the five lane H files: master 79 failed, 220 passed,
  10 errors (the errors are `test_restore_drill`, lane D). Head, with the new test: 252 passed, none failed.
- The same at umask 0022 with psql on PATH: master 309 passed (nine files).
- The new test as root, on master's `update.py` and `box.sh`: 3 failed, 1 passed. At head: 4 passed.
- The tests of every touched file (59 files), CI's conditions (umask 022, `--cov`, `COVERAGE_CORE=sysmon`,
  `-n auto --dist worksteal`, a long marked `TB_TEST_ROOT`, `TMPDIR` 0700): as root 1533 passed; as the ordinary
  user 1531 passed, 2 skipped (`test_db_no_gosu`'s two root-only cases).
- The same 59 files as the ordinary user at umask 0002 with psql off PATH. Master: 108 failed, 10 errors. Head:
  28 failed, 10 errors. No failing id is new at head, and 80 pass that fail on master. All 38 that are left name
  the missing `psql`, in files this card does not change: `test_backup_busy_night` (12) and `test_restore_drill` (10),
  lane D's, held; `test_backup_verifies_itself` (7), `test_backup_without_pause` (5), `test_rehearsal_restic` (2),
  `test_refdata` (1), `test_update_path` (1), which the walk's top ten did not list. They take the same fix
  (`tests/pg_client.py`) once their lanes say go.
- `make lint`, `tools/doclint.py`, `make data-scan`, `make security-scan`, `tools.limits_lint`,
  `tools.decisions_index --check`, `tools.findings_register --check`, `make guard` (1198 passed, 1 skipped,
  11 xfailed), `make cross-card` (329 passed), `pytest tests --collect-only` (rc 0): all clean. `--add-from` of this
  card's findings, tried on a copy of the register, adds its 7 rows.

## Not verified

- The erasure module's red on the bench host: its cause is not found.
- A PostgreSQL built without libxml was not run; a stand-in was.
- Lanes D's and J's fixes are not built: they wait for their lanes' go.
- `box.sh`'s new count runs only on a real rehearsal box, and was not run on one. Its statement was compared with the
  old one on the test cluster.
