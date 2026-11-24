# The update's rollback finishes whatever signal arrives (2026-11-24)

**Reader:** the people who build TrialBox: lane H, the integrator and the independent reviewer.

Card H-114 covers the external review's escape ESC-4 (Medium; `tools/trialbox/update.py:1298`, ledger 7122387629) and the
ledger's lane H rows that no open pull request held: 1409-2, 1409-3 and 1421-3. ESC-4 is the same class as H-100's
re-review R1 and R2 on the restore. The tests are in `tests/unit/test_update_signals_h114.py`.

## Pull request body (draft)

**ESC-4, the update path's signals (`tools/trialbox/update.py`).** Before this card, the rollback caught `Exception`
only, so a second Ctrl-C during the rollback escaped it. There was no "ROLLBACK FAILED" line, no `update.rolled_back`
audit event, and the box was left half restored. SIGTERM and SIGHUP had no handler, so the process died at once with
the marker left. Now, `Updater.run` and `Updater.recover` install one handler, `Stops`, for SIGINT, SIGTERM and
SIGHUP alike:

- the first signal stops the update. If it arrives inside a step the updater marks as stoppable (the preflight, the
  backup, the rollback point, the apply, the restart, the rulesets, the check, the reference data and the code
  systems), that step stops at once. A signal that arrives between two steps stops the next one at its start. So it
  always lands where a failure is caught. The signal is raised once and never again;
- from then on, and for the whole of any rollback (one that a failure started, or `tools/apply_update.sh rollback`),
  every signal is said on the terminal, ignored, and named in the audit event (`signal`, `signals_ignored`). The
  commands the update runs are already in a session of their own (`procgroup`), so the terminal's signals never reach
  them. Signals are ignored rather than blocked: one that arrives during the rollback is never acted on after it;
- `_rollback` catches `BaseException`. Whatever still ends a step is said as a failed rollback, and the marker stays
  at `rollback failed`;
- the box ends either fully on the new release or fully back on the old one:
  - a signal before the rollback point: nothing had changed, and the services are started again;
  - from the apply to the check: rolled back;
  - after the check: the checked release is finished, the remaining code systems are not loaded, and the history says
    so;
- the error line says which release the box is on ("the box is back on the release before B1", or "ROLLBACK FAILED
  ... the box may be between the two releases"). The audit event carries `state: previous release` or
  `between releases (rollback failed)`;
- a closed session (SIGHUP, then every write to the terminal fails) cannot end the rollback through its own progress
  lines. The terminal streams are wrapped once a signal arrives, and a history line whose terminal write fails is
  still written to `history.jsonl`.

**What finds an update cut short (unchanged, from D-210 and H-99 #1411).** Only `kill -9` or a power cut still
leaves an update between two releases. The marker `deploy/updates/IN_PROGRESS.json` names the step, and
`<bundle>/rollback/point.json` records everything that was changed. The next `tools/apply_update.sh` is refused
while the marker stands. `tools/apply_update.sh status` names it, and `tools/apply_update.sh rollback <bundle>`
(`Updater.recover`) does one of two things:

- finishes the clean-up when the step was `finished`;
- otherwise rolls the update back from `point.json`, now also from `rollback failed`, with every signal ignored.

H-99 kept the same rollback point for a PoC box that has no backup. Nothing finishes a cut-short update without an
operator: the box is refused new updates until `rollback` is run. That is not changed here.

**`tools/apply_update.sh`.** INT, TERM and HUP had one trap that removed the stage folder and let the script go on.
A signal sent to the shell before the update path started was followed by the next commands, the update path
included, on a stage that was gone. Now:

- a signal before the update path ends the script ("stopped by SIGTERM before the update started; nothing was
  changed"), with exit 130, 143 or 129;
- once the update path runs, the shell waits for it, adds no line of its own and ends with the update path's code.

**1409-2 (Low, `update.py` `streamed_payloads`).** The second read of the stick took each signed name out of its list
before it checked that the member was a file. A payload that had become a link since the verify was dropped in
silence, and was neither loaded nor checked. It is now refused (`UpdateFailed`, a signature/hash stop, H-94 (1)). The
same case is in the rehearsal's update-path step (`tools/rehearse_box/h95_probe.py`, step `swapped-stream`). The harm
it names: a signed payload dropped in silence. It needs no engine.

**1421-3 (Medium, `box_restore.py`).** The host restore took only its own `restore.lock`, so the nightly backup could
run over the folders it was restoring. The restore now also holds `deploy/site/backup.lock`, the lock every backup
run takes (`backup_schedule.run_backup`), for its whole run:

- a restore under a running backup is refused before anything stops;
- a backup under a running restore gets `BackupBusy`, so that night is said as "another backup run holds
  deploy/site/backup.lock".

`backup_schedule.py` is not changed (#1455 holds it).

**1409-3 (Medium, `tools/packs.py:123`): not done, a question.** The check is whether a `docker load` peaks at about
twice the image bytes in the engine's data root, as the review says, or at the largest archive plus the images, as
review F5 counted. That needs a measurement on a real engine with each image store (H95-02 is still not measured).
This container has the engine's client but no daemon. I do not rule it "not a fault": it stays open for the
integrator.

## What was run

- `tests/unit/test_update_signals_h114.py`: 72 cases:
  - two signals in every order of INT, TERM and HUP: the first during the apply and the second during the rollback
    (8); both during a rollback that a failure started (8);
  - INT, TERM and HUP at each step's start and inside each step (45);
  - a hang-up whose terminal is gone;
  - a rollback cut short, found and refused by the next run and finished by `recover` under two more signals;
  - the shell: a signal before the update path (3), and during it (3);
  - the handlers put back;
  - 1409-2 and 1421-3.
- On master's `update.py`, `apply_update.sh` and `box_restore.py`, 69 of the 72 fail. Some end the child process by
  the signal, and some fail on the missing state line. The three that pass on master are `test_s2_*`. They guard
  this card's own change: the shell must not mask the update path's code.
- Mutants planted, 9:
  - caught alone (8): the rollback catching `Exception` only; SIGHUP not handled; a second signal raising again; a
    recovery not held; a signal between steps never stopping the next one; a backup that ignores a signal; a failed
    update that does not hold; the shell going on after a signal;
  - caught only with its pair: the history's tolerant terminal write. The terminal stream wrapper covers the same
    harm, and removing both is caught by `test_h1_*`.
- Not run here: the rehearsal job (it needs the engine and runs in CI); the whole unit and integration suites.

## Findings

In `update-rollback-signals-h114-2026-11-24/findings.json`. H114-05 is open: when the console's update run reaches
its time limit, the group gets SIGTERM and then SIGKILL 10 s later (`procgroup.TERM_GRACE_S`). A rollback that the
SIGTERM starts is killed part way. The marker stays, and `rollback` finishes it. This is no worse than before (the
SIGTERM used to kill the update at once), but the box is between two releases until someone runs `rollback`. This is
a hypothesis: it was read, not run.
