# D-731 An update asked for "in the quiet hour" waits for it

- **Task:** T-730b, a part of T-730 ("The box looks after itself": signed updates applied in a quiet hour with
  rollback; lane D's queue in `docs/plan/37-remaining-work-split.md`)
- **PR:** this branch (`agent/T-730b-an-update-in-the-quiet-hour`)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** D-178 and review J-09 (the operations runner: a person asks, an old request is never run), D-210
  (the signed update, its backup and rollback), D-455 (the running-jobs count)

## Context

An update runs when the administrator presses "Apply" on the Operations page, and a request older than an hour is
not run (`MAX_AGE_MIN`), so that an update never starts without the person by it. On a box with no IT, the owner
would have to stay until no job runs and apply it then; T-730 asks for updates applied in a quiet hour.

## Decision

1. An `update_apply` request may carry `when: quiet`. The operations runner leaves it pending until the box's quiet
   hour (`TB_UPDATE_QUIET_AT`, default 05:00, for `TB_UPDATE_QUIET_HOURS`, default 2, in `TB_TZ`; a window may run
   over midnight) and until the orchestrator runs no job (D-455's count). A box that cannot say how many jobs run,
   a setting that does not read, or a box with no zone, is not quiet: the update waits.
2. A quiet request is not expired after the usual hour: it waits for the next quiet hour, and expires after
   `QUIET_WAIT_H` (26 hours: the next quiet hour always comes within a day, two hours more for a night that ran
   long). An expired one is never run; the person asks again.
3. When it runs, it is the same `apply_update.sh`: the backup first, the rollback point, the automatic rollback.
   A person still asks for every update; only the time moves.
4. Only an update waits: any other request with `when: quiet` is refused with that sentence.
5. `status.json` lists the waiting updates under `waiting`, each with why it waits. The console's button and its
   rendering are lane C2's (asked in the PR).

**The exception to D-178/J-09, stated.** J-09 keeps an update from starting without the person by it: a request
older than an hour is not run. A quiet request is the one exception: an explicit instruction, confirmed for a time
when the person is not there, and bounded (26 hours, then never). The console's confirmation must say so (C2), and a
rollback must reach the owner (T-730's alert question).

**After the review** (FIX FIRST; each fixed test-first):
- a request whose `args` is not an object is a failed result, never a crash of the root runner that blocks the
  queue (`_args`);
- the wait is counted from the runner's own first-seen stamp (`seen/<id>.json`, root's), never from the request
  file's time, which the console's user can move;
- a `when` other than exactly `quiet` (or left out) is refused, never run at once;
- the staged bundle's sha256 is kept at first sight: a different file of that name is refused ("ask again");
- an update that ran closes the quiet updates still waiting as `superseded`: none is applied again on its own;
- the window is compared in real time (UTC), so a day the clocks change keeps its hours;
- a setting that does not read says which (`TB_TZ`, `TB_UPDATE_QUIET_AT`, `TB_UPDATE_QUIET_HOURS`);
- a job count that raises is "not known", so it waits.

The quiet hour's default (05:00 to 07:00, after the night and before the first morning notice) is this card's
proposal; a site sets its own. On a Windows box the Windows Update window (D-606) is another setting; the site may
set both to one window.

## Not covered

- The console's "Apply in the quiet hour" button and the `waiting` list on the Operations page (lane C2).
- A message to the owner when a quiet update failed and was rolled back: the result and the audit say it; the
  owner's message path is T-730's alert question (owner's decision pending).
