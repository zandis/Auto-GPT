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

- `tests/unit/test_update_signals_h114.py`: 72 cases at fc620ca (80 with the review's 8 below):
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

## The external review of #1461 (7124127048, at fc620ca)

The verdict was fix first: High 0, Medium 3, Low 2. Each fix below has a test in
`tests/unit/test_update_signals_h114.py` that fails at fc620ca (8 cases fail there, all pass now).

- **1461-1 (Medium): fixed.** The first host tree on a copied install moves each copied file aside and links it.
  The rollback record learned what had moved only when `host_tree.install` returned, so a signal between two moves
  left the compose file a dangling link while the update said "back on the release before". The reviewer's patch is
  taken: `install`, `switch` and `sync` fill the caller's record as each file moves (`into`), each name is recorded
  before its move or link, and `restore` removes a link made before the stop. `tools/host_tree.py` is lane H's file
  and no open pull request holds it. Not covered: a `kill -9` part way through the switch still leaves `point.json`
  with the record as it was before the switch (it would need a `save_point` per move). Test: `test_1461_1_*`, with
  INT, TERM and HUP.
- **1461-2 (Medium): fixed.** `apply_update.sh ospatch` changes the host's packages before the update path's mark,
  so a signal then said "nothing was changed" and exited 130, 143 or 129. The mark is now set before the OS patch
  tool runs. Test: `test_1461_2_*`, with INT, TERM and HUP.
- **1461-3 (Medium): half fixed; the other half is a question.** When the console's time limit is reached, the
  updater gets SIGTERM and then SIGKILL 10 s later. The kill can land in the middle of the rollback, and the
  put-back's command (in a session of its own) runs on. `tools/apply_update.sh rollback` then started a second
  put-back beside it.
  - Fixed in `update.py`: `run_cmd` records each command's process group in `deploy/updates/running/<pgid>.json`
    while an update or a rollback runs. `recover` refuses while a recorded group is alive, names it, and changes
    nothing. The record of a dead group is removed. Test: `test_1461_3_*`. The updater is killed with SIGKILL during
    the put-back; `recover` refuses while the put-back runs, and finishes once it has ended.
  - Not fixed: the 10 s grace itself. Giving the update path's TERM time to finish its rollback needs
    `procgroup.run` (lane B2) to take a grace, and `ops.do_update_apply` (lane R) to pass one. These are other lanes'
    files, so the question is for the integrator. H114-05 is this half.
- **1461-4 (Low): fixed.** An update started under `nohup` (SIGHUP ignored by the caller) was rolled back when the
  session closed. `Stops` now leaves a signal the caller ignores ignored. Test: `test_1461_4_*`.
- **1461-5 (Low): not fixed here.** The nightly that meets a host restore says "another backup run holds" the lock.
  The wording is in `backup_schedule.py`, which #1455 holds; the reviewer's patch is listed for it.

Mutants for these fixes, 5, all caught:
- the host record not filled as files move;
- the OS patch not marked as started;
- `recover` not waiting for a running put-back;
- `nohup` overridden;
- a command not recorded while it runs.

## The second external review of #1461 (7125647317, at 766ec35)

The verdict was fix first: High 0, Medium 2, Low 5. The reviewer's patches are taken, and I own them. Each new test
fails at 766ec35 (5 new cases). The card's file now has 85 cases.

- **1461-1 (Medium, the part left): fixed (H114-11).** The switch's moves reached the in-memory record only. A
  rollback cut short by the console limit's SIGKILL, before the host put-back, left `rollback` a `point.json` without
  them. Now the rollback saves the rollback point before its put-back (a failed write is ignored). Test:
  `test_1461_1_a_rollback_killed_after_a_stop_in_the_switch_is_finished_by_recover`, a real TERM inside the switch,
  then a real SIGKILL during the rollback, then `recover`. Still not covered: a SIGKILL inside the switch itself,
  before any rollback runs (it needs a `save_point` per move).
- **1461-3 (Medium, partly fixed): the half left is the ten-second grace.** That is card H-114b (the integrator's
  ruling 7124945074). It is built on its own branch and is kept out of this pull request.
- **1461-6 (Low): fixed (H114-12).** A running-command record also names this boot's id and the group leader's start
  time, and a mismatch drops it. The folder is `deploy/updates/.running`, a dot name that no bundle id can take.
- **1461-7 (Low): fixed (H114-13).** `sync` sets a site's own link at a release path aside, as it does a file. After
  a switch back, `restore` also puts back what the new release had displaced.
- **1461-8 (Low): fixed (H114-14).** `test_1461_1_*` runs its case in a child process, so a regression fails that
  test and does not end the run.
- **1461-9 (Low): fixed (H114-15).** The record is written inside the `try` whose handler kills the command's group.
- **1461-5 (Low): left.** It is in `backup_schedule.py`, which #1455 holds (H114-10).
- Mutants, 5, all caught:
  - no `save_point` before the put-back;
  - the record folder back to `running`;
  - a record trusted by its group id alone;
  - `restore` after a switch ignoring `moved`;
  - the record written before the `try`.

Master 38a06e5 was merged once; it brought one page, with no conflict. The reviewer also noted that `run_cmd` keeps
its own copy of `procgroup.run`'s steps, so the two must be kept in step by hand. `test_t695_update_stop_boot.py`
pins the limit behaviour of both.
