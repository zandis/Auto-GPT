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
- Check (3) of the new process rules (7125828711), on this round's diff:
  - a running-command record was written in place. A torn record reads as malformed and is dropped, so a put-back
    still running would no longer hold the recovery. It is now written whole, through `update_status.write_atomic`
    (temp file, fsync, rename). Test: `test_a_running_record_is_written_whole_never_in_place`; it fails on the
    in-place write;
  - the other writes this card adds (the rollback point, the host-tree record) already go through `save_point`;
  - every signal path is covered by the cases above.
- The runs before the push, from `trialbox/`:
  - the set: the policy tests (every unit test that reads the workflows, image files, shell scripts or the
    Makefile) plus the card's tests and the tests of every touched file, 118 files:
    `sort -u <(grep -lE 'rglob\("\*\.sh"\)|glob\("\*\*/\*\.sh"\)|glob\("\*\.sh"\)|\.github/workflows|"Makefile"|Dockerfile' tests/unit/*.py) <(grep -lE 'trialbox import update|from tools.trialbox.update|host_tree|procgroup|update_status|apply_update|box_restore|h95_probe' tests/unit/*.py)`;
  - as root: `.venv/bin/python -m pytest -q -p no:cacheprovider -n 8 <the set>` gave 2614 passed, 8 skipped,
    0 failed;
  - as user nobody, with `HOME` and `TMPDIR` a 0700 folder of its own and git's `safe.directory` set:
    - the first pass, with a 0777 temp folder and no git setting, gave 88 failed, 4 errors and 2519 passed;
    - rerunning the 20 failing files gave 30 failed and 472 passed;
    - the same 20 files as nobody on master 38a06e5, in a worktree, gave 24 failed;
    - the 24 are the same failures on both, and none is in this card's files. Their causes: nobody has no home
      folder, and it cannot write into the root-owned repository tree;
    - the 6 more on the branch all read the main checkout's root-owned `trialbox/.cache`, which the master worktree
      does not have;
    - the card's own file and every update, host-tree, restore and procgroup test file pass as nobody;
  - `make lint` clean; `make guard` 1197 passed; `make cross-card` 329 passed; data-scan and security-scan clean;
    limits and decisions clean; collect-only 24817.

## H-114b: the console's update limit and the rollback (2026-11-24)

The integrator ruled (7124945074) that lane H takes H114-05 as card H-114b, with bodies only in two other lanes'
files. Files outside the card: `tools/trialbox/procgroup.py` (lane B2) and `tools/trialbox/ops.py` (lane R).

- `procgroup.run` takes an optional `grace`: the group's time between the SIGTERM and the SIGKILL. Its default is
  `TERM_GRACE_S`, ten seconds, as before, so every other caller is unchanged. `None` means no SIGKILL until the
  command has ended by itself.
- `ops.do_update_apply` passes the update's own limit (`apply_limit`) as the grace. A stand-in runner (the console's
  tests) is called as before.
- How the figure was chosen: no rollback time was measured, in the rehearsal or anywhere in the tree. A rollback
  redoes at most what the update did (the same database restores, models, host tree and restart), and each of its
  commands carries its own limit. The update's limit counts those steps and the restore of the dumps, so a rollback
  started by the limit's SIGTERM gets that much again before the SIGKILL. When the sizes cannot be read, the update
  has no limit, so there is no SIGTERM either.
- Tests, in `tests/unit/test_update_grace_h114b.py`; all 3 fail on the tip's files:
  - the default path: the limit, then ten seconds (measured: from 10 s up to 14 s), then the SIGKILL, with the TERM
    seen once, and the default named `TERM_GRACE_S` = 10;
  - the real updater under `procgroup.run` with a limit that lands in its apply and a rollback of 12 s (longer than
    the default grace): it runs to its end and is audited `rolled_back: true`;
  - the console passes its limit as both the timeout and the grace.
- Mutants, 3, all caught: the default moved to 20 s; `procgroup` ignoring the grace; the console passing no grace.

## H-114c: a SIGKILL inside the host-tree switch (2026-11-24)

The integrator ruled (7129325585) that the half of 1461-1 left open is card H-114c, High-class. The fault: on a
copied install, the first host tree's switch moves each copied file aside and links it. The record of those moves
reached `point.json` only when the install returned. A SIGKILL between two moves (a power cut, or the console
limit's SIGKILL) left the record of before the switch, and `tools/apply_update.sh rollback` then said "previous
release" with the compose file still set aside (H114-16).

- `host_tree.install`, `switch` and `sync` take `on_record`. The list of moved files saves the record each time a
  name is added, which `_aside` does before the file moves. `_aside` keeps its signature, which the existing tests'
  stand-ins use. `apply_host` passes a save of the rollback point (`save_point`, written whole with fsync).
- Undoing the first host tree of a copied install also removes the links through `current` that a cut-short switch
  made but never recorded. Only the release's own paths are looked at. Links are not saved one by one, which would
  cost one fsync per release path.
- Test: `tests/unit/test_host_tree_switch_kill_h114c.py`, 5 cases:
  - a copied install, killed after the 1st, 2nd and 4th move;
  - a copied install, killed right after linking a path only the release has, so the link is unrecorded;
  - a box already on a host tree, killed in its next switch.
  In each, a real SIGKILL ends the first child process, and a second child runs `recover`. All 5 fail at 27e8f0d8.
- Mutants, 3, all caught:
  - no save as each name is added;
  - no removal of the unrecorded links;
  - `apply_host` passing no save.
- A first version changed `_aside`'s signature. It broke the three existing `test_1461_1_*` cases, whose stand-in
  takes four arguments, so it was replaced by the saving list, and those tests stay unchanged. A separate save of the
  aside folder before the first move was removed: the first move's save already carries it, and no test could tell
  them apart.
- A kill between a name's save and its move leaves a name whose file was never moved; `restore` skips it, since the
  file is still in its place.
