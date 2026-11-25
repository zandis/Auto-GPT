# A restore or an update ends 0, 1 or 130 and says its state, whatever signal comes (2026-11-25)

**Reader:** the people who build TrialBox: lane H, the integrator, OCR and the walk.

Card H-142 (High), from H-140's table 2a (7155313804 on #639) and the integrator's ruling (7155472105). It builds
on #1496 (H-138, train 176), merged into this branch first. Its rows, in the order of its commits: .i; H138-02, .a
and .b; .c to .g (and .j); .h; .k. Key: R = `tools/trialbox/box_restore.py`, M = `tools/trialbox/__main__.py`,
U = `tools/trialbox/update.py`, B = `tools/trialbox/backup.py`, S = `tools/trialbox/backup_schedule.py`,
G = `tools/trialbox/sigends.py` (new).

## The rule

No exit code other than 0, 1 and 130 leaves a restore or an update because of a signal, and every end says the
state line (RUNBOOK §5: "Every end says the box in one line"). The restore's own documented ends stay as RUNBOOK §5
gives them: 2 (refused before anything stopped), 3 (a reference pack missing), 4 (NOT complete). The restore now
maps any other code to 1 at its last line. Python's own start (before the entry's first line runs) still has the
defaults: a signal in those few milliseconds is the default's death. That window is not closed here.

## The changes, row by row

- **.i (first).** `tests/unit/test_restore_signal_ends_h142.py` runs the entry *file* as a script
  (`runpy.run_path(..., run_name="__main__")`: its own `__main__` block, `installed` as on the host), and the walk's
  second signal lands on the process's way out (an `atexit` step, after `main` returned). With M's `_exit_code` call
  taken out, H-138's tests still pass and this one fails (143).
- **H138-02, .a, .b.** `BoxRestore.restore()` takes SIGINT, SIGTERM and SIGHUP at its first line, before the lock,
  the key, the hash and the space check (R:417). A signal there is said ("nothing was changed"), audited, and ends
  130; the space check's `deploy/.restore-*` folder goes with it. The state line is the restore's end. Once compose
  has answered, the three signals are ignored to the end of `restore()`. On the process's own way out
  (`sigends.own_exit()`, called by M's `__main__` block) they stay ignored to the exit, never the defaults, for
  every exit code. In-process callers get their handlers back. Every end says the line, now including a complete
  restore and a restore without `--restart`.
- **.j.** A signal the caller ignored when the command started (`nohup`, a job started with `&`) stays ignored
  (`sigends.take`, as `update.Stops` already did). It landed with the row above, where the taking moved.
- **.c.** An engine client that died of a signal (a negative code; never SIGKILL), or the engine's 125 to 127,
  with no result, is "the restore's container did not run: nothing was changed by it". The services this run
  stopped are started again (LR-14) and the restore ends 130 (1 for 125 to 127 with no signal). A container that
  died of a signal (128 + n) with no result may have been changing the box: unknown, as before, and 130. Never a
  raw or negative code.
- **.d.** `backup.restore` takes raising handlers for all three signals first, SIGINT included (in the container
  the tool is PID 1 with no init: a signal it does not take is dropped). One that comes before the first change
  ends as a refusal: `state: unchanged`, "before any change: nothing was changed", exit 1. The first signal raises
  once and the rest are ignored, so the put-back is never cut short. A host told to stop whose container did not
  restore ends 130.
- **.e.** The container's stdout goes to an unlinked temp file. The wait is `communicate()` with no pipe, which
  can be re-entered with nothing lost. (A pipe's read cut by the interrupt lost what it had read: the JSON.) If the
  container had already ended when the signal came, nothing is sent to it and the line says so.
- **.f.** One outer handler in `restore()` says the state for where the restore was: before the container, while
  it runs, or after it ended. It ignores further signals and returns 130. Clean-ups in a `finally` (the work
  folder, the lock's two closes) run whole: a signal that comes meanwhile is kept and handed to the handler after
  them (`sigends.held`). Not by blocking it: with other threads in the process the kernel gives a blocked signal to
  another thread.
- **.g.** From the first signal the streams are tolerant (`sigends.Tolerant`, U's `_Tolerant` moved there). A line
  that cannot be written is not said, the host waits for its container, and the exit's flush never makes 120.
- **The entry's own window.** For `restore` and `update`, M's block notes a signal that comes before the command
  takes its handlers (the parsing, the imports). The command's `sigends.replay()` hands it on, so it ends as a
  signal before any change ends.
- **.h.** `update.main_apply` takes the update's `Stops` at its first line and hands them to the run.
  `Stops` is entered twice (the command, the run) and given back once. A signal before the run's first step is said
  and refused ("update REFUSED: stopped by SIGTERM before anything was changed; nothing was changed"), 1. On the
  process's own way out the signals stay ignored after `Stops` ends, and the streams stay tolerant, flushed first.
  An update's 0 or 1 is never 143, and its buffered lines are not lost. The first load (`TB_SKIP_AUDIT`) holds the
  signals: it runs to its end.
- **.k.** `write_atomic` at S's kept audit events (`deploy/site/backup-audit-pending.jsonl`) and at the event file
  it hands the orchestrator. Also at U's history, its audit event file, the pending copy of that file (was
  `shutil.copy2`) and the first load's pending summary. Each keeps its mode. The rehearsal's `box.sh` (Low) writes
  `deploy/.env` through a file renamed over it: `envset` keeps the file's owner and mode, and the live-restore
  put-back uses `cp -p` and then `mv`.

## The invariant and its mutants

`test_a_signal_at_any_phase_ends_0_1_or_130_and_says_the_state` runs the real entry as a script. The box's engine
and compose are one stand-in script, named by `TB_DOCKER` in the box file. It sends a real signal (SIGTERM, SIGINT,
SIGHUP) at each phase mark the stand-in writes: the space check, the stop, the container's start, its handlers, its
change, the services' start, the health check. Each mark is swept at three delays, with the walk's second SIGTERM
30 ms after and a third SIGTERM on the way out. Each run must end 0, 1 or 130. It must say `restore: the box now:`
and print no traceback. It must not say "healthy" on data it changed and did not finish. It must leave no scratch
folder it did not name. That makes 21 cases and 63 runs.

The mutants (each fix taken out alone, against the card's three test files) are listed in the pull request with
the tests that catch each. The sweep runs a stand-in container, so .d, .e and .g are caught by their own tests,
not by the sweep.

## The walk's run on the bench (the two things H-140 did not run)

From the release folder of the bench's box (`trialbox/` in the repository; repo-relative paths, as root):

1. The sweep and the card's tests, on the box's own python:

       .venv/bin/python -m pytest -p no:cacheprovider -n auto tests/unit/test_restore_signal_ends_h142.py \
           tests/unit/test_update_signal_ends_h142.py tests/unit/test_kept_writes_whole_h142.py \
           tests/unit/test_restore_second_signal_exit_h138.py

2. The real restore in the backup image, signalled at swept delays (the key as RUNBOOK §5 says, copied to a
   root-only file first; the box restored from its own newest good backup each time):

       key=/root/trialbox-backup.key
       for d in 0 1 3 8 20 60; do
         trialbox restore --last --key "$key" --yes --restart > "restore-$d.json" 2> "restore-$d.err" & pid=$!
         sleep "$d"; kill -TERM "$pid"; sleep 0.2; kill -TERM "$pid"; rc=0; wait "$pid" || rc=$?
         echo "delay $d: exit $rc; state lines: $(grep -c 'restore: the box now:' "restore-$d.err")"
         case "$rc" in 0|1|130) ;; *) echo "FAIL: delay $d ended $rc"; break ;; esac
         grep -q 'restore: the box now:' "restore-$d.err" || { echo "FAIL: delay $d said no state"; break; }
         rc=0; trialbox restore --last --key "$key" --yes --restart > rerun.json 2> rerun.err || rc=$?
         case "$rc" in 0|4) ;; *) echo "FAIL: the re-run after delay $d ended $rc"; break ;; esac
         grep -Eq 'are healthy: ([0-9]+) of \1 \(' rerun.err || { echo "FAIL: the re-run said no N of N"; break; }
       done

   Each delay must end 0, 1 or 130 and say the state; each re-run ends 0 (or 4 with the hold) with "N of N".
   With SIGINT and SIGHUP in place of SIGTERM, the same.

## What was run

Here, in this container (no engine, no bench), the counts for root and for an ordinary user under CI's conditions
are in the pull request body.

- On master+#1496 (49a256de) with the card's test files copied into a worktree: 31 of the 38 restore tests, 7 of
  the 8 update tests and the 3 `.k` tests fail (143, 129, 241, 120; the kill -9 left an empty file: 0 of 20000
  kept events). The ones that pass there are the .i test (#1496's 130 holds) and sweep cases whose signal only
  reaches the services' stop or start.
- At this branch's head, all of them pass.

## Not run, not verified

- The real restore in the backup image against a database, the engine's real client, the bench host: the walk
  runs them (above).
- The rehearsal (CI only).
- Python's start before the entry's first line: a signal there still has the default action.
- The whole unit and integration suites (the card runs the policy set and every test file naming the modules it
  touches).

## Findings

In `restore-signal-ends-h142-2026-11-25/findings.json` (card H142). H142-01 closes H138-02.
