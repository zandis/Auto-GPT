# A restore that said its interrupt ends 130, whatever signal comes next (2026-11-25)

**Reader:** the people who build TrialBox: lane H, the integrator and the independent reviewer.

Card H-138, as changed by the integrator's 7149128872 on #639 on OCR's diagnosis (#1494, 7149124260), answers train
176's red. In `rehearse (test)`, job 138877998556, step [28] live-restore failed with "REHEARSAL FAIL: the restore
signalled after its data part ended 143, not 130 or 1". The first card text (7148918381: a marker wait in the
rehearsal, "not tested") is withdrawn. The rehearsal step `tools/rehearse_box/box.sh` is unchanged.

## The fault

The walk's double signal reaches `trialbox restore --last ... --restart` in its start of the services. The job's
log shows the restore took the first TERM and handled it in full: the state line, "the services did not all come
back healthy: signal SIGTERM", the hold line, and then 130 returned. Its `_restore` then runs `finally:
stop_signals()` (`tools/trialbox/box_restore.py`), which puts back the process's original handlers. For the
installed command those are the defaults. A second TERM that lands between there and the process's exit kills it by
the default action, so the shell sees 143. Whether it lands there depends on how fast the state line asks compose.
That is why the fault showed up only on some runs.

## The change

- **`tools/trialbox/__main__.py`, the `__main__` block only (OCR's patch):** `_exit_code(code)`. When the command
  ends 130 (an interrupt it has said), it sets SIGINT, SIGTERM and SIGHUP to ignored for the rest of the process's
  own way out. The exit code is the one it said. Any other code leaves the handlers alone. In-process callers
  (`cli.main(..., installed=True)` in the tests) never reach it, so they keep their handlers.
- **`tests/unit/test_restore_second_signal_exit_h138.py`**, 3 tests: OCR's 2 and one added here.
  - A child process takes the host step's handlers, takes a TERM and returns 130, then puts its handlers back.
    It then goes through `_exit_code` and a 0.5 s way out, and a second TERM 0.2 s after the first does not change
    its 130.
  - `_exit_code` leaves the handlers alone for 0 and 1.
  - Added here: an in-process `cli.main` restore that ends 130 leaves its caller's SIGINT, SIGTERM and SIGHUP as
    they were.
- **One change to OCR's test, with no assertion changed.** The child prints a `ready` line inside its `try`, once its
  handlers are in, and the first TERM is sent after that line. OCR's version waited a fixed 3 s first, and a slow
  child start under `-n auto` would take that TERM before its handlers. With the line printed before the `try`, one
  `-n 4` run here failed with exit 1: the TERM came during the `print`, outside the `try`. Inside the `try` it
  passes.

## What was run

The counts for root and for an ordinary user, under CI's conditions, are in the pull request body.

- On master 6c73db64 (the test file only, added in a worktree of master), both of OCR's tests fail. The first
  child exits 1 on the missing `_exit_code`. The second fails with an AttributeError.
- Mutants, each planted alone and run against the card's file:
  - the ignore removed (`_exit_code` returns the code with the handlers as they are): the double-signal test fails
    with -15, that is the 143 of CI;
  - the ignore for every code: `test_the_exit_code_keeps_handlers_for_any_other_code` fails;
  - the ignore applied for in-process callers, in each of three places (`box_restore.main`, `_restore_cmd`,
    `cli.main`): the added in-process test fails each time. OCR's two tests alone do not catch it here, and
    `test_restore_from_the_host_h100.py` and `test_restore_rerun_h126.py` pass with it under `-n 4`. OCR saw 3
    reds of `test_r2_*`, which depend on test order in the worker.

## Not run, not verified

- The rehearsal. It runs only in CI, so this card's push is its first run.
- OCR's residual window: from `stop_signals()` to `_exit_code` (the lock's release and the returns) a second signal
  still gets the default action. That window is microseconds to milliseconds against the walk's 0.2 s. Closing it
  would need `_restore` to know it runs as the process (an `installed` flag passed down). That is not done here.
- The whole unit and integration suites.

## Findings

In `live-restore-signal-h138-2026-11-25/findings.json`: H138-01 (the fault, fixed), H138-02 (the residual window,
open, a hypothesis).
