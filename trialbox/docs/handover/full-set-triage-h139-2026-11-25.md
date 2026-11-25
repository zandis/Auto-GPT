# H-139: full-set triage, why the bench host is red where CI is green

**Reader:** the integrator, the walk and the people who build TrialBox (lanes B2, D and J: their files are named below)

Lane H, 2026-11-25. Card H-139 (the integrator's 7150296048 on #639), from the walk's full-set run 2 on master
cf7c1917 (7150288454) and its detail (7150513283). The same tests pass in CI and fail on the bench host, so the
difference is the host. Each failing file was run again on master 6c73db64 in a container set up the way the walk
described the bench host. The cause was found by turning one condition on at a time. The data is synthetic only.

Round 2 follows the integrator's ruling (7151161624). Items 3 and 4 (the client tools, lane D's files included) are
built, then item 1 (no XML), then item 2 (lane J's node check). Item 5 (the umask fixtures) was built in round 1 and is kept as it
is. It waits for the integrator's ruling, made once the (b) list is complete. A "no" takes it out in a later commit.
Item 7 is triaged below.

## The bench host's conditions, recreated

| Condition (the walk's report) | How it was recreated here |
| --- | --- |
| an ordinary user (uid 1003), HOME set | `setpriv --reuid=1003 --regid=1003 --init-groups env -i HOME=… PATH=…`, a git worktree that user owns, every folder above `TB_TEST_ROOT` 0755 |
| umask 0002 | `umask 0002` in the runner, compared with `umask 0022` |
| no `psql` on PATH; PostgreSQL server binaries from a package of their own | a PATH folder holding every system tool except `psql`, `pg_dump`, `pg_restore`, `pg_dumpall` (the server still from `pglocal.bindir()`) |
| `node` through a wrapper in a container (slow) | a `node` on PATH that waits 65 s before it runs the real one |
| a PostgreSQL without libxml (the walk's first reading) | **not recreated**: the source build of one was refused in this session. The reading was wrong: the bench host's server had an older vector extension (7155060416) |
| `-n auto`, a long `TB_TEST_ROOT` marked with `python -m tools.pglocal mark`, `TMPDIR` 0700 inside it | `-n 4 --dist worksteal`, a test root of over 100 characters, marked; `TMPDIR` 0700 inside it |

## The sorted list

(a) a host difference the product must handle; (b) a test that assumes CI's environment (fixed under H-135's rules:
no assertion changed, nothing skipped); (c) the bench host's own setup (the walk's to fix, as it said).

| File (walk's count) | Reproduced here | Cause | Kind | Fix | Lane |
| --- | --- | --- | --- | --- | --- |
| `tests/unit/test_erasure_reach.py` (226) | not here: the module passes on master (55 passed, 183 skipped, 21 xfailed). The integrator's 7155060416: the bench host's test server had an older vector extension (`public.halfvec` missing); the walk had read the setup error as "unsupported XML feature" | the test server's vector extension older than the db image's pin (0.8.7, `deploy/images.lock`) | (b)/(c) | push 2: the test cluster's fixture stops the run once, plainly, when the server's vector is older than the pin (`tools/pglocal.py` `vector_check`, `tests/conftest.py`; `tests/unit/test_vector_pin_h139.py`); the bench host installs pgvector 0.8.7 or newer | H |
| `tools/trialbox/update.py` `SCHEMA_SQL`, `tools/rehearse_box/box.sh:794` | — | they read through `query_to_xml` and `xpath`, which a server without libxml refuses | **dropped** in push 2 | the product's server has libxml: the db image is `postgres:16-trixie` (`deploy/docker/db.Dockerfile`), the official Debian image of the PGDG packages, built `--with-libxml` (the Debian-family package here shows `--with-libxml` and links `libxml2.so.2`); and the erasure reds were not XML. Push 1's change and its test are taken out in a forward commit | — |
| `tests/console/test_button_targets_9k3.py` (112 errors) | yes | `node` takes over 60 s; `_node_playwright()` (`tests/console/test_cjk_layout.py:44`) runs at import inside a `skipif`, so collecting the module raises `TimeoutExpired`, once per xdist worker (112 is the bench host's worker count) | (c); a (b) part | the walk installs node and Playwright as CI has them. Built here (item 2): the check is made once per test process (`tests/node_check.py`, kept there because a module whose import fails is not kept), and a timeout is one plain line, never a skip | J (band 9k), bodies only |
| `tests/unit/test_backup.py` (27), `test_backup_restic.py` (19), `test_backup_busy_night.py` (12) | yes, the same counts | the backup runs the bare `psql` and `pg_dump` from PATH (`TB_PSQL_CMD`, `TB_PG_DUMP_CMD` unset) | (b); an (a) part | built (item 3): the tests hand in the test cluster's own client tools (`tests/pg_client.py`, also to the CLI forms through the process environment, and in test_backup.py's late-write wrapper). `backup.py` refuses a client tool it cannot run, naming the tool and its setting, before any change: a restore had emptied the schemas before it found `pg_restore` missing (`tests/unit/test_backup_client_tools_h139.py`) | D, bodies only |
| `tests/unit/test_restore_drill.py` (10) | yes | the same | (b) | built (item 4): the same, and the docker stand-in runs the db image's client tool as the cluster's copy | D, bodies only |
| `tests/unit/test_backup_schedule.py` (12) | 10 of 12 | the same | (b) | fixed here: `tests/pg_client.py` | H |
| `tests/unit/test_restore_from_the_host_h100.py` (17) | 16 + 1 | 16: the same; 1: umask (below) | (b) | the 16: fixed here (item 4); the 1: item 5, built in round 1, waiting for the ruling | H |
| `tests/unit/test_host_commands_own_environment.py` (39) | yes, 39 of 39 | umask 0002: the box tree the fixture builds, `deploy/.env` among it, is group-writable and the product rightly refuses it ("can be written by group or others (chmod 600 it): nothing was run"); with psql off PATH one more | (b) | the psql one: fixed here (item 4); the 39: item 5, `as_root_makes_it` (H-115's `tests/host_modes.py`) on the built trees, built in round 1, waiting for the ruling | H |
| `tests/unit/test_serving_engine_h112.py` (14, unit and pure) | 13 of 14 | umask 0002: "deploy/site is not root's or this user's alone (chmod go-w)" | (b) | item 5: `as_root_makes_it` in `_box`, waiting for the ruling | H |
| `tests/unit/test_kek_env_refused_h97.py` (1) | yes | umask 0002: the test's passphrase folder is 0775 and `keys init` rightly refuses it | (b) | item 5: `as_root_makes_it` in `_passphrase_box`, waiting for the ruling | H |
| `tests/unit/test_lifecycle_keys_h133.py` (5) | no (passes at both umasks as uid 1003) | the walk's "assert 0 >= 8" is `test_lifecycle_keys_h133.py:396`: `rotate-kek` refused before its first rename | open | wait for the walk's captured stderr | H |
| `tests/unit/test_release_dirty_refused.py` (1), `tests/unit/test_first_run_code_h97.py` (1) | no | first-run: the output had begun, so probably the test's 60 s pty deadline on a loaded host | open | wait for the walk's captured stderr | H |
| `tests/e2e/test_mail_compose.py` (5), `tests/integration/test_compose_data.py` (4), `tests/integration/test_compile_compose.py` (2) | not run (no Docker daemon in this container) | the 401s: services that answer an unauthenticated call with 401 are PRODUCTION or hold a token, unlike CI's TEST stack; mail_compose iterates the 401's JSON body (`test_mail_compose.py:112-115`), hence `'str' object has no attribute 'get'`. Hypothesis: `deploy/docker-compose.yml:9` pins `name: trialbox`, so `make up-test` shares the project, the container names and the ports of a box installed on the same host | (a)/(b), to rule on | the test stack under a project name of its own, or `make up-test` refusing while another stack holds the name | to be found (git log: 9i-1 for mail_compose) |
| `tests/e2e/test_planted_faults.py` (1) | not run | `'backup': 'red'` in the health answer: on the reading above, the installed box's backup state | the same | the same | the same |
| `tests/integration/test_db_image.py` (1) | not run | `test_db_image.py:243` skips without `pg_dump` on PATH, and `TB_STRICT_SKIPS=1` makes that skip a failure. Hypothesis | (b) | `tests/pg_client.py` | H (H-93) |
| `tests/e2e/test_module_walks.py` (12), `test_life_cycle_walk.py` (3), `test_life_cycle_walk_390.py` (3), `test_phone_walk.py` (3) | from the code | `assert []` is `assert lines`: `node` printed nothing (`test_module_walks.py:116`, `test_life_cycle_walk.py:90`); 390's missing JSON is the file node writes | (c) | the node wrapper (the walk's) | — |
| `tests/console/test_ops_pages.py` (2), `tests/console/test_admin_screens_209c.py` (1) | yes: both backup tests fail with psql off PATH and pass with it | the console's backup runs the bare `psql` | (b) | `tests/pg_client.py` | the console's (to be found) |
| the other console reds, `tests/e2e/test_console_poc.py` (7) | from the code | browser tests through `node` ("waiting until load") | (c) | the node wrapper | — |
| `tests/unit/test_backup_verifies_itself.py`, `test_backup_without_pause.py`, `test_rehearsal_restic.py`, `test_refdata.py`, `test_update_path.py` | yes (below) | the bare `psql` | (b) | `tests/pg_client.py` | to be found |
| gpu (2) | not run | the suites' own path | — | stays with J-R20 and E2-11 (the integrator) | J, E2 |

## The skips of test_erasure_reach, by design

Run on master here: 55 passed, 183 skipped, 21 xfailed (the bench host's run: 182 skipped). Each skip says why. 169
are "the patient never reached this store in the unit box: its absence proves nothing". 14 are "not searched in the
unit box (compose only, or the store is not made here)". Both are the module's design (its docstring: "A store P
never reached is skipped as 'not reached'"). The unit box stands up only what the unit tier can. A store the patient
never reached proves nothing by being clean. The compose-only stores are searched on a live box (`tools/erasure_reach.py live`).

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

### Round 2 (items 3, 4, 1 and 2)

- The policy set (the integrator's: the unit files that name `.github`, a workflow, a Dockerfile, the Makefile, a
  `.sh` file or shellcheck; 241 files) and every touched file's tests (276 files in all), CI's conditions: as root
  6011 passed, 20 skipped, 1 xfailed.
- The same as uid 1003: 120 failed, 3 errors, all "detected dubious ownership". That account's git worktree had
  root's `.git`. The same 21 files on master give the same 120 failures and 3 errors. In a clone that uid 1003 owns,
  those files pass, except one: `test_cloud_run.py::test_a_part_records_its_run_and_a_new_run_runs_it_again`, which
  fails the same way on master in such a clone ("0/1 screenshots").
- The bench host's conditions (uid 1003 in its own clone, umask 0002, psql off PATH) over the touched files (81).
  Master: 182 failed, 11 errors. Head: 33 failed, 1 error. No failing id is new, and 159 are fixed. Each of the 34
  left is now the plain refusal ("the PostgreSQL client tool pg_dump cannot be run here"), in files this round does
  not change: `test_backup_without_pause` (5), `test_refdata` (1), `test_update_path` (1), and seven more:
  `test_backup_vector_store` (7), `test_t728_asof_restore_optouts` (7), `test_restore_hold` (4), `test_restore_roles`
  (4), `test_lane_b_on_the_train` (3), `test_backup_licensed_terminology` (1), `test_erasure_reach_restore` (1 error).
- The new tests on master's code: `test_schema_versions_no_xml_h139` (dropped in push 2) 3 of 4 fail, `test_backup_client_tools_h139`
  4 of 4 fail. With a node that waits 61 s, collecting the six console files that ask the check: master calls node 6
  times in 363 s, with a TimeoutExpired traceback per module; head calls it once in 62 s, with one plain line per
  module and no skip.
- The console files that use the check, as root with node and Playwright: 101 passed. The whole `tests/console`
  was not run this round: the lead asked for the touched files and the policy set only.
- `make lint`, doclint, data-scan, security-scan, limits_lint, `decisions_index --check`,
  `findings_register --check`, collect-only: clean. `make guard` 1198 passed, 1 skipped, 11 xfailed;
  `make cross-card` 329 passed. `--add-from` on a copy of the register: 9 rows.

### Push 2 (the integrator's 7151749260 and 7152069220)

- **Item 5, ruled (b).** The fixtures make their own folders with explicit modes and never rely on the run's umask.
  test_host_commands_own_environment: `_explicit_modes` (the folders the fixture makes 0755, `deploy/.env` 0600, as
  install.sh writes it; the tree copied from the checkout keeps its files' modes). test_serving_engine_h112's `_box`:
  `deploy` and `deploy/site` 0755. test_kek_env_refused_h97's `_passphrase_box`: its two folders 0700. One test per
  guard shows that a folder or file the group alone can write is still refused: `tests/unit/test_group_writable_refused_h139.py`
  (`deploy/.env` at 0620, 0660 and 0664; the settings folder at 0775, 0770 and 2775; the passphrase folder at 0775
  and 0770).
- **Item 7, client tools.** `tests/console/test_ops_pages.py`'s `ob` fixture hands the app the cluster's client tools;
  that also fixes `test_admin_screens_209c`, which takes the same fixture. Both pass with psql off PATH.
  `tests/integration/test_db_image.py`: first the skip was shown. A test with its line 243's skip, run under this
  repository's conftest with `TB_STRICT_SKIPS=1` and pg_dump off PATH, fails with "skipped under TB_STRICT_SKIPS=1,
  which allows no skip: Skipped: pg_dump not on this host", and passes with pg_dump on PATH. Whether the bench host
  met exactly this needs the walk's line. The fix: the test looks for the cluster's pg_dump and hands it to
  `dump` and `restore_db`. The skip is neither removed nor added to.
- **Item 7, the compose project, ruled (a).** `TEST_PROJECT := trialbox-test` in the Makefile, `-p $(TEST_PROJECT)` in
  `COMPOSE_TEST`; `tools/failure_drill_box.py` builds the same command. Rendered, the project and every network are
  `trialbox-test*`. `make up-test` first pipes the stack's rendered configuration to `tools/test_stack_free.py`. It
  refuses, by name, a container of another project that publishes a port the stack would publish. It also refuses a
  container that has a test-stack container's name in another project, and a port held by something that is not the
  stack's. The stack's own containers from an earlier run are no reason to refuse. Test:
  `tests/unit/test_test_stack_project_h139.py`. With no Docker daemon here, the check refuses plainly ("what runs on
  this host could not be read").
- **The five other unit files** (the go 7152069220). `test_backup_without_pause` (5) and `test_update_path` (1) take
  the client tools; the CLI forms take them through the process environment. Both pass with psql off PATH.
  `test_backup_verifies_itself` and `test_rehearsal_restic` already pass through test_backup's fixtures. They are
  unchanged. `test_refdata`'s red is not psql: it is `test_the_tar_is_deterministic_and_safe` at umask 0002, the case
  H-115 left as H115-18 (`pack_tar` keeps each file's mode). It is left for its own card. At umask 022 it passes: in
  push 2's run as uid 1003 in its own clone (CI's conditions), test_refdata passed, so the corrected bench (umask 022)
  does not meet it. It fails only at umask 0002.

### Push 3 (the integrator's 7155439799, 7156055986 and 7156065500)

- **H139-10, the key and KEK group.** Which environment value made a unit test see a PRODUCTION box on the bench host
  and not in CI: no process variable, but the checkout's own `deploy/.env`. `make up-test` copies it from
  `.env.example`, which names no `TB_ENV`, and `rc1_refusals.host_env` reads it as the box's, taking the stricter of
  the box's and the caller's. The bench host's unit stage ran after its compose stage; CI's unit jobs never run
  up-test. On master, `cp .env.example deploy/.env` makes 29 of the twelve named files' 324 tests fail (test_key_escrow
  11, test_rc1_refusal_sites 5, test_lifecycle_keys_h133 4, test_restic_password 4, test_kek 2, test_sign_keys_kek 2,
  test_nightly_restic 1). The fix (the ruling: a test sets what it depends on): `tests/own_deploy.py` points
  `tools.keys`' deploy folder at a folder of the test's own, with no `.env`. For the ceremony it also points
  `tools.backup_key_ceremony`'s, and `trialbox backup-keygen`'s beside its file, as `test_restore_drill.py` points
  it. Each of the seven files has an autouse fixture. At this head, 324 passed with the file and without it. The rule
  stays under test: `tests/unit/test_box_env_production_h139.py`, one case per group, shows that a box file naming no
  `TB_ENV` still makes the key commands, the ceremony and `backup-keygen` refuse as on a PRODUCTION box though the
  caller says TEST. No assertion changed.
- **Seven more files, client tools** (the go 7156065500): `test_backup_vector_store`, `test_t728_asof_restore_optouts`,
  `test_restore_hold`, `test_restore_roles`, `test_lane_b_on_the_train`, `test_backup_licensed_terminology`,
  `test_erasure_reach_restore`. The CLI forms and the backup drill's restore take the tools through the process
  environment (`tests/pg_client.py` `setenv`): the drill puts the cluster's folder on its own PATH, but
  `backup.dump` runs with the process's. With psql off PATH: 57 passed, 1 xfailed.
- **H139-12** (Low): `test_the_command_runs` (its `cmd2`, in the unit test of the runbook's install commands) ran the installer with the
  caller's PATH. On a host with a card that cannot run the model server's image, the installer refuses ("this GPU
  host cannot run the vLLM image"), rightly. The step now runs with the host's own graphics tool off its PATH. With a
  stand-in `nvidia-smi` that reports another card: master fails cmd2, head passes all 35; without one, 35 passed.

### Push 4 (CI on push 2; the integrator's 7158058588)

- **The CI red `tests/console/test_ctgov_mode_text.py::test_only_the_one_sentence_depends_on_the_mode`** (unit shard 6/8,
  job 139070865985, "AssertionError: /home … assert 2 == 1") is a timing flake that master has too. `/home` is the
  console route under test. Every signed-in page carries the idle warning's seconds left (`data-idle-left`,
  `data-abs-left`, `_idle_warn.html`, from `UserStore.session_left` and its clock). Two renders of `/home` 1.1 s apart
  differ only there (28799, then 28798). The test's twenty renders, on a loaded worker, crossed a second. The fix
  (body only, no assertion change): the test holds the session's clock still (`box["users"].clock` fixed after
  sign-in). With a scratch plugin making every store's clock advance a second per read: master fails "/home", the
  fixed test passes. Alone, the file passes (30 passed).
- **The same form elsewhere, looked for once.** These compare renders of signed-in pages taken at different moments:
  `test_console_timing`, `test_people_lists` (its with/without comparison) and `test_home_today` already strip
  `data-*-left`, and so do the tests that go through `tests/console/j7_master_bytes.py`.
  `tests/console/test_tier_status_words.py`'s `_pages` strips only the CSRF value and compares `/home`. It has the same
  latent flake and is not failing now, so it is listed, not changed. `test_people_lists.py:226` compares two 404
  answers byte for byte. It is listed as possible (not checked whether a 404 carries the timer).
- **A second instance, already failing on CI** (#1489, job 139105640093, unit shard 1/8):
  `tests/console/test_dates_setting_and_nendo.py::test_an_upgraded_japanese_site_and_a_site_elsewhere_count_by_calendar_year_as_before`
  compares a signed-in page rendered from master's template with the same page rendered now, byte for byte. It is
  the same countdown. It is fixed the same way (the store's clock held still; body only, no assertion change), and
  the file is lane H's now. With the ticking clock: master fails, the fixed test passes. Alone, the file passes (9
  passed).
- **H139-13 (the integrator's 7158672355): a skipped stage read as passed.** In the walk's diagnostic run node could
  not load the browser driver. The walks stage (TB_STRICT_SKIPS=1) failed at once. The poc stage "passed" with its 7
  tests skipped, and the console stage with 15 skipped. `make test-console` and `make test-console-e2e`, which the full
  set's console and poc stages run, now set `TB_STRICT_SKIPS=1` as `test-compose` and `test-walks` do (CI's own poc
  step already did). A browser test without its driver is a plain failure there ("skipped under TB_STRICT_SKIPS=1,
  which allows no skip: Node Playwright is not available"). The unit shards keep lane J's terms: with no node, the
  browser tests skip with their own reasons. Test: `tests/unit/test_browser_stages_strict_h139.py` (the recipes, and a
  probe run with no node on PATH, strict and plain). On master's Makefile its two console and poc cases fail.
- master c3a5b2b2 (train 176) merged once.

### Push 5 (the walk's ids, the integrator's 7159506328)

- **H139-14, compose: the test stack's TB_ENV came from the caller's shell.** The walk saw no name or port conflict,
  so the 401s at the adapter (`test_compose_data` ×4 errors: its module fixture posts `/run` with no token) and at the
  orchestrator (`test_mail_compose` 5, `test_compile_compose` 2) are re-read. No token can come from the stack's
  files: tokens come only from `deploy/docker-compose.secrets.yml`, which `COMPOSE_TEST` does not name, and
  `.env.example`'s `TB_SERVICE_TOKEN` is a placeholder counted as none. Without a token, a service takes
  unauthenticated calls only on DEV or TEST. Every test-stack service takes `TB_ENV: "${TB_ENV:-TEST}"`, which
  compose fills from the caller's shell first, and the full set runs every stage with the walk's whole environment.
  A shell that exports the TB_ENV of the host's own box makes the whole test stack non-TEST. This is the likely
  cause, not confirmed on the bench. Class (a), the owner's rule (no caller's environment variable decides it).
  The fix: `COMPOSE_TEST` sets `TB_ENV=TEST` and `TB_DATA_CLASS=D0` before its command, as it already sets
  `TB_SETTINGS_FILE`, and `tools/failure_drill_box.py` does the same. Test: rendered with a caller's
  `TB_ENV=PRODUCTION` and `TB_DATA_CLASS=D3`, every service is TEST and D0; without the settings, the caller's
  PRODUCTION reaches the services that take `${TB_ENV:-TEST}`. `test_planted_faults`, `test_role_walk` and
  `test_limits_edge_box` are likely the same cause, not confirmed.
- **Pure, three ids, not reproduced here** (root, with and without a controlling terminal, `/dev/tty0` writable). The
  hypotheses wait for the bench's error lines. `test_first_run_code_h97`: a write to a real virtual console that
  blocks or is held. `test_lifecycle_keys_h133` LR-3: the root test's uid-10001 child, or a fork under xdist.
  `test_release_dirty_refused`: a compose box that reaches the host's real Docker as root.

## Owners named in this card

The integrator's go 7152069220: `tests/unit/test_rehearsal_restic.py`, `tests/unit/test_refdata.py` and
`tests/unit/test_update_path.py` are lane H's from now on. `test_backup_verifies_itself` and
`test_backup_without_pause` stay lane D's; the same go covers their one-line client-tools fix (bodies only).
The go 7156065500: `tests/unit/test_restore_roles.py` is lane H's from now on.
The ruling 7158058588: `tests/console/test_ctgov_mode_text.py` and `tests/console/test_dates_setting_and_nendo.py` are lane H's
from now on.

## Files outside the card

Changed in bodies only, after each lane's go: lane D's `tests/unit/test_backup.py`, `tests/unit/test_backup_restic.py`,
`tests/unit/test_backup_busy_night.py`, `tests/unit/test_restore_drill.py` and `tools/trialbox/backup.py`; lane J's
`tests/console/test_cjk_layout.py` and `tests/unit/test_rc1_refusal_sites.py` (J-5); the console lane's
`tests/console/test_ops_pages.py`; `tests/integration/test_db_image.py` (H-93); lane D's `tests/unit/test_backup_without_pause.py`,
`test_backup_vector_store.py`, `test_t728_asof_restore_optouts.py`; lane B's `test_restore_hold.py`, `test_lane_b_on_the_train.py`;
lane V's `test_backup_licensed_terminology.py`, `test_erasure_reach_restore.py`; the Makefile's `COMPOSE_TEST` and `up-test`;
`tests/conftest.py`'s `pg_cluster_url`.

## Not verified

- The erasure module's red on the bench host: its cause is not found.
- The db image was not pulled (no Docker daemon here): its libxml is read from its base and its packaging.
- The compose stage was not run (no Docker daemon here); its rows are read from the code.
