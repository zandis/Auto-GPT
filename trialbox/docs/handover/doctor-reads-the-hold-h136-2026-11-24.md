# trialbox doctor reads the hold after a restore through the box (2026-11-24)

**Reader:** the people who build TrialBox: lane H, the integrator and the walk.

Card H-136 (the integrator's card 7145902865 on #639, from the walk's report 7145893589). After a restore,
`trialbox doctor`'s `restore_hold` check could not read the hold `screening.after_restore` on an installed box. The
installed command said `WARN restore_hold: cannot read the hold after a restore (ModuleNotFoundError)`. With the
box's libraries it said `(OperationalError)`: there is no database address from the host. RUNBOOK §5 says doctor
shows the hold, so the operator's check was blind right after a restore. The walk read the hold on `/ops/flags`
instead and released it there.

## Cause

The check read the flag with `tb_common.flags.Flags(url=TB_DB_URL)` in the doctor's own process. On the box's host
that process is the host's `python3` (standard library and PyYAML, `launch.py`), which has no `psycopg`. The box
file's `TB_DB_URL` names `db:5432`, which exists only on the compose network. Any failure was a WARN, and a WARN
passes. The host check's doctor (`deploy/check_host.sh`) runs in the box image with `--network none`, so it hit the
same `OperationalError` on every install and passed.

Shown on master a3739fca with the box file's address: `Check(name='restore_hold', status='WARN',
detail='cannot read the hold after a restore (OperationalError)')`.

## Pull request body (draft)

**1. The hold is read through the box.** `tools/trialbox/box_hold.py` uses the standard library only. It asks the
box's `db` container the way the host's other steps ask it (the backup's job count, the databases' sizes):
`docker compose --project-directory <deploy> exec -T db psql -U trialbox -d trialbox_wf -f -`. The query runs in a
read-only transaction and creates nothing. A store that is not installed yet reads as "never set".

Only the box decides where it reads:

- the box file `deploy/.env`, checked by `launch.box_file` (a file another user owns or others can write is no
  reading);
- the box file's `TB_COMPOSE` or `TB_DOCKER`, else `docker compose`;
- the engine gets a clean environment: `PATH`, `HOME` and the engine variables the box file names, as the restore
  runs compose (`box_restore.engine_env`).

A caller's `TB_DB_URL`, `TB_DOCKER`, `TB_COMPOSE`, `COMPOSE_PROJECT_NAME`, `COMPOSE_FILE`, `DOCKER_HOST` or
`TB_DOCTOR_RESTORE_HOLD` never decides it.

**2. Where doctor runs.**

- *On the box's host* (the installed `trialbox doctor`): through the box, at `--env-file`'s folder. Without
  `--env-file` it uses the install folder's own `deploy/.env`, the file the launcher already took the settings from.
- *In the box image* (the host check, the rehearsal): the image has no engine. The host reads the hold through the
  box with `python3 -m tools.trialbox.box_hold <deploy>` and hands in one JSON line (`TB_DOCTOR_RESTORE_HOLD`), as it
  already hands in the pid map's row. This value is read only inside the box image (`launch.in_box_image`), whose
  environment the launcher, compose or the host check set.
- *In the image with no hand-in* (a hospital platform's doctor job, on the database's network): the image's own
  `TB_DB_URL`, read the way the console reads it (`Flags.row`).
- *A process with no box at all* (no `deploy/.env`: a developer's tree, the test cluster): its own `TB_DB_URL`, as
  before. Lane B's `test_restore_hold.py::test_doctor_shows_the_hold` drives the check this way and holds unchanged.
  Wherever there is a box, its compose project decides (on the host) or the host's reading does (in the image). A
  hand-in on a host is never read.

**3. Three lines, and unreadable never passes.**

- `WARN restore_hold HELD since <time> by <who>: ... (<reason>)`, with the release path;
- `PASS restore_hold released (last change <time> by <who>)`, or `released: ... never set on this box`;
- `FAIL restore_hold UNREADABLE: ... (<cause>)`. The cause is named: `service "db" is not running`, the box file can
  be written by group or others, the engine cannot be started, a value the box does not declare, no reading.

**4. Runbook page 05.** Step 4 keeps its three lines and points to a new paragraph below the steps, "The hold after
a restore". That paragraph gives the command (`sudo trialbox doctor --env-file deploy/.env` on the host), the
three lines and what each kind of box sees. It names the release path: on `/ops/flags`, choose `released`, type the
reason, press Change. The second page, "Please confirm", makes the change only with its button "Yes, do it". There is
no release command; `trialbox model release` is for the models' flag.

## What each kind of box sees (D-1091)

The doctor is a check, not an install stop. Nothing here adds or changes a stop on the install, start or update path.

- **A PoC box (DEV, TEST, VALIDATION):** the same three lines. In the host check that install.sh runs (step 6, after
  the stack starts), a FAIL is a FAIL line of the host check, and on a PoC box the install's FAIL lines warn and the
  step goes on, as before. Before this change that line was a WARN that hid the unread hold.
- **A PRODUCTION box:** the same lines. The host check's FAIL lines are the install's FAIL lines, as before. The step
  starts the stack first, so `db` runs and the hold reads. Only a box whose database does not answer gets a FAIL,
  and that box is the one the line warns about.

The guard on the real path rides in the rehearsal job (`tools/rehearse_box/box.sh`), naming the harm: an operator
told nothing is held while the screening hold is on.

- the `doctor` step: the image's doctor is handed the host's reading and must say `PASS restore_hold released` on the
  fresh box;
- the `live-restore` step, after its restores: the installed `trialbox doctor --env-file deploy/.env`, typed on the
  host as root (the walk's command), must print the line the flag on the box holds (`WARN ... HELD` when it is
  `held`, `PASS ... released` otherwise), never "cannot read".

## Ctrl-C, SIGTERM and writes

The reader writes nothing. Its transaction is read-only (`SET default_transaction_read_only = on`) and it creates no
schema or table. Ctrl-C or SIGTERM during the read ends `psql` in the `db` container with nothing to undo. The doctor
writes no file. `check_host.sh` and `box.sh` keep the reading in a shell variable only, never in a file. A reader
that is killed or times out (30 s) is a FAIL with its cause, never a pass. Nothing is written in place.

## Tests

`tests/unit/test_doctor_reads_the_hold.py`, 13 tests. The stand-in engine is a `docker` named in the box file
(`TB_DOCKER`). It logs its argv and environment and runs the reader's SQL with the real `psql` 16 on the test
cluster, where `tb_common.flags.Flags.set` sets the hold as a restore and `/ops/flags` set it.

- `test_held_released_and_unreadable_each_give_their_own_line`: never set, held, released (PASS / WARN / PASS) and an
  engine that says `service "db" is not running` (FAIL) give four different lines, with three statuses;
- `test_an_unreadable_hold_is_a_fail_naming_its_cause_never_a_warn` (8 cases): no engine, a group-writable box
  file, no box file, a value the box does not declare, no reading, a hand-in that says unread, a hand-in that is not
  a reading, a refused database in the image. Each is a FAIL naming its cause, and `doctor.ok` is false;
- `test_the_host_reads_through_the_box_never_its_own_database_or_a_callers_variable`: the host's database says
  released, a caller's hand-in says released, and the caller's engine variables name another engine and project.
  The box says held, and the line is the box's. The engine was asked exactly
  `compose --project-directory <deploy> exec -T db psql ...`, and none of the caller's variables reached it;
- the same test, a host with no box: a caller's hand-in that says held is no reading;
- `test_in_the_box_image_the_doctor_takes_the_hosts_reading`, and the platform form without a hand-in;
- `test_the_reader_needs_only_the_hosts_standard_library_and_says_one_line`:
  `python -S -m tools.trialbox.box_hold` (no site-packages) from a bare environment prints one JSON line;
- `test_the_host_check_and_the_rehearsal_hand_the_hosts_reading_to_the_image`.

**Each fails on master a3739fca:** 13 failed, 0 passed (the copied file run in a master worktree).

**Planted mutants**, each run in its own worktree against the file and restored, with this file and
`test_restore_hold.py` (21 tests; none planted: 21 passed):

| Mutant | Tests that fail |
| --- | --- |
| M1 unreadable is a WARN | 9 (8 unreadable cases, the three-lines test) |
| M2 the host reads from the host (the image path on the host: `TB_DB_URL`, the caller's hand-in) | 7 |
| M3 a caller's `TB_DOCKER` decides the engine | 1 (the host test) |
| M4 the caller's environment reaches compose | 1 (the host test) |
| M5 held says released | 4 (with `test_restore_hold::test_doctor_shows_the_hold`) |
| M6 the image ignores the host's reading | 3 |
| M7 a host takes a caller's hand-in | 1 (the host test, its no-box case, added after M7 survived the first pass) |

## Runs

All on the branch at c733d39c, merged with master a3739fca (master is its base). Output in files; failing lines
read. CI's conditions throughout: umask 022, `PYTEST_ADDOPTS="--cov --cov-report= --durations=30"`,
`COVERAGE_CORE=sysmon`, `-n auto --dist worksteal`, `-m "not integration and not e2e and not llm and not perf"`, a
`TB_TEST_ROOT` of about 100 characters marked with `python -m tools.pglocal mark`, `TMPDIR` 0700 inside it, fonts and
JVM dependencies fetched (`make fonts`, `make jvm-deps`).

**The set** (319 test files): the policy set (`grep -lE '\.github|WORKFLOWS|...|shellcheck' tests/unit/*.py`), every
test file naming doctor or the hold (`doctor|restore_hold|after_restore|box_hold`, under `tests/`), and this card's.

| Run | Passed | Failed | Skipped | Xfailed |
| --- | --- | --- | --- | --- |
| root, from the session's tree | 8879 | 0 | 7 | 27 |
| tbci (uid 30033) by `setpriv`, `env -i`, its own clone, folders above the root not group or other writable | 8873 | 1 | 12 | 27 |

- The one ordinary-user failure, `tests/unit/test_cloud_run.py::test_a_part_records_its_run_and_a_new_run_runs_it_again`
  ("complete run FAILED: 1/1 checks, 0/1 screenshots"), fails the same way on master a3739fca as the same user, from
  its own clone (`test_cloud_run.py`: 1 failed, 20 passed on master and on the branch). It is outside this diff.
- Skipped as root (7): `test_security_contact` (the owner has set the contact), `test_platform_manifests` x2 (no
  kustomize), `test_poc_host` (no caddy), `test_supply_chain` x3 (needs uv 0.13.7). As tbci, 5 more:
  `test_seal_keys_order` (needs root), `test_db_no_gosu` x2 (needs root and setpriv), `test_phone_first` (no Node
  Playwright), `test_host_baseline` (no nft). Xfailed (27, both users): `test_ssmix2_10b1_reader_on_spec` 21,
  `test_audit_tamper` 5, `test_erasure_reach_restore` 1, all known gaps, none in this card's files.
- Runs I threw away, and why:
  - A first root run used the same tree while the mutants were being planted in it. A worker imported `doctor.py`
    with M6 in place, so three of this card's tests failed. It also had no fonts, so the report tests failed.
    After that the mutants ran in a worktree of their own.
  - A first ordinary-user run used a worktree of the root-owned repository, and git refused it ("dubious
    ownership"): 122 failed. The run above used tbci's own clone.
  - A container restart lost one ordinary-user run, which was then run again.
  - The first root run did show two real gaps, both fixed in 917fcb25: `test_config_declared` asked for
    `TB_DOCTOR_RESTORE_HOLD` to be declared, and lane B's `test_restore_hold::test_doctor_shows_the_hold` drives
    the check with no box (now read as before).

**Checks** (root, from `trialbox/`): `make lint` rc 0; `tools/doclint.py` rc 0; `make data-scan` rc 0;
`make security-scan` rc 0; `tools.limits_lint` rc 0; `tools.text_keys` rc 0; `tools.decisions_index --check` rc 0;
`tools.findings_register --check` rc 0; `pytest tests --collect-only -q` rc 0, 26242 tests, unique basenames;
`make guard` 1199 passed, 11 xfailed (all `test_phi_guard_ja.py` known gaps), no skip; `make cross-card` 329 passed;
`shellcheck --severity=warning` over all 79 `*.sh` files: no finding (shellcheck 0.9.0 from the distribution).
The runbook page changed, so: `pytest tests -k "runbook or planted or restore or findings"` 1197 passed, 4 skipped
(compose services: `test_planted_faults`, `test_db_image` x3), 276 xfailed. Its first run failed
`test_restore_by_the_runbook::test_the_committed_findings_fit_the_register_and_quote_the_page`: the restore drill's
H33-06 quotes page 05 at line 244, and the first text grew step 4 by 20 lines. Step 4 now keeps its three lines and
points to a paragraph after line 244 ("The hold after a restore"). H33's record is not edited. `findings.json` was
taken by `findings_register --add-from` in a throwaway copy of master (4 rows; `--check` rc 0), then discarded.

## Files outside the card

One row in a shared registry: `libs/tb_common/config.py` declares `TB_DOCTOR_RESTORE_HOLD` beside
`TB_DOCTOR_PIDMAP_ROW` (`test_config_declared` asks for it). Lane H declared its doctor hand-ins there before
(H-89, H-106). Nothing else outside the card: `tools/trialbox/doctor.py`, `deploy/check_host.sh`, `tools/rehearse_box/box.sh` and runbook page 05 are lane
H's by `git log` (H-92, H-94, H-96, H-97, H-100, H-106, H-112, H-126). `tools/trialbox/box_hold.py`, the test file
and this page are new.

## Not run, not verified

- The rehearsal job (`tools/rehearse_box/box.sh doctor` and `live-restore`) was not run: there is no container
  engine in this session. Its new assertions and the host check's hand-in are checked by shellcheck and by the static
  test only. Whether `psql -U trialbox` over the `db` container's local socket answers is taken from the same form
  the backup already uses (`backup_schedule.running_job_list`), not shown here.
- The reader's SQL (`\gset`, `\if`, a read-only transaction) ran against PostgreSQL 16.15. The box's `db` image is
  `trialbox-postgres:16-1`.
- The whole unit and integration run was not run.
