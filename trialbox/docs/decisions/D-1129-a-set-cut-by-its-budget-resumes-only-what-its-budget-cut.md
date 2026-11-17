# D-1129 A set cut by its own budget resumes only what its budget cut, and its attempts are one record

- **Task:** lane H, card H-14 (the integrator on PR #639, 2026-11-17 05:35 UTC; the fault was found by card H-12)
- **Date:** 2026-11-17
- **Status:** accepted

## Context

An accuracy set (step `6x-acc-<set>`, `deploy/gcp/box_vm.py acc_set`) has its own time budget (`--acc-deadline`,
D4). When the budget runs out, the set cuts the protocols it has not started and any protocol whose job it was
waiting for. Each of these is `not_run_time_budget`. The set's step then ends `done`.

`box-run.sh --resume <run id>` keeps a `done` step. So the cut protocols were never run. `--resume --redo <step>`
ran the whole set again "from no work": approvals were reused (F29), but every protocol already screened was screened
again. `acc-score` could not merge the answers of two attempts.

Inside one attempt, `acc_set` already took a cut protocol up again when there was time left. A set stopped in the
middle of its step (a pre-emption, a cap) already resumed with its finished protocols kept. Only the step's state
and the clock stood in the way.

## Decision

1. **The step says what was cut.** A set's part carries `budget_cut`: the protocols its budget cut, or never
   started. The step stays `done`. A part written before this decision is read from its counts
   (`not_run_time_budget`).
2. **A resume with a budget opens it again.** On a resume (a new `tb-retry`), the VM opens again every set step
   with `budget_cut` above 0 for which `--acc-deadline` names a budget (one number, or `set:seconds`). It keeps the
   part as `logs/<step>.budget-<retry>.json`, keeps `79-acc-result`'s the same way, and marks the set
   `acc_reopen_<set>`. A set with nothing cut stays done. So does a cut set with no budget given: a plain resume of a
   finished run runs nothing again. The VM says which, first thing on its boot (`TB-RESUME-PLAN` lines). `--redo`
   keeps its meaning (from no work, new mail ids) and clears the mark.
3. **A new attempt runs only what was cut.** The opened set runs `acc-set --new-attempt <retry>`. The set's clock
   (`set-clock.json`) moves the attempt before into `attempts` (its seconds and its budget, kept) and starts the new
   attempt at 0. The new `--acc-deadline` is the new attempt's own budget, not a total over the attempts. This
   happens once per tag, so a pre-emption within the attempt keeps counting its boots, as before. Only the cut
   protocols and those never started run. A protocol cut while its job ran keeps the job and waits for it. A
   finished protocol is never sent to FEAS, APPROVE or SCREEN again. Its answers, job ids, screen JSON and traces
   stay as they are. The mail ids stay the run's, so nothing is mailed twice.
4. **One record.** `answers.json` holds each protocol once, with the attempt that answered it (`attempt`; none
   stored reads as 1). The gateway's audit and raw traces of the new attempt are read since the attempt's own start
   and added to the earlier ones (`acc-merge-attempt`). Each attempt's own read is kept under `attempts`, totals are
   summed, and rows are joined (a row stored twice is kept once). The attempt before was read at its end, and the
   new attempt starts after it, so the audit's `since` (D5) counts nothing twice. `services.log` starts with the
   earlier attempts' lines (`services.earlier.log`). `box-calls.log`, `embed-mem.tsv` and the checkpoints are
   appended, as before. `acc-partial/<set>.tgz` and `acc/<set>.tgz` are the work folder, so they hold the union.
   The part, the report and the score say `attempts: 2; protocols finished in attempt 1: a; in attempt 2: b; still
   cut: c`.
5. **The scorer reads the attempts as one.** `score.score_protocols` adds `attempts` to the `protocols` block (score
   layout 4; nothing renamed). Every denominator counts a protocol once. A protocol cut in attempt 1 and screened in
   attempt 2 is screened. `box_run.acc_score` and the replay (`replay.score_all`) carry the set's clock beside its
   answers. A two-attempt folder scores equal to the same protocols run in one attempt.
6. **The free look.** `box-run.sh --preflight --resume <run id> [--acc-deadline ...] [--redo ...]` makes no cloud
   call. It reads the run's last `--collect` (`tools.box_run resume-plan`). It says per set what the resume would do,
   names the sets that need `--acc-deadline`, and refuses (exit 6) a budget that is not seconds or names a set the
   run lacks. A run never collected here is said to be only in the bucket; the VM's `TB-RESUME-PLAN` lines are then
   the first word. A real `--resume` prints the same plan first.
7. A set run in two attempts measures no slowdown (F22), just as a set cut short measures none.

## Proof

- `tests/unit/test_h14_budget_resume_2026_11_17.py`: `acc_set` across two attempts with the stand-in box on a
  controlled clock (calls counted: no done protocol sent, waited for or fetched again), the merged answers and
  logs, the scorer on a two-attempt folder against one attempt (equal figures), the replay, the resume plan and the
  driver's free preflight.
- The rehearsal case `acc-cut-resume` (`tests/rehearsal/box-run`, run by `tests/unit/test_g1_box_install_run.py`):
  the real VM script and helper. jmed and sigir end on their budgets. The resume gives jmed 60 s and sigir nothing.
  jmed runs its cut protocol alone, every mail goes once, and the audit, the traces and the score are one record.
  sigir stays done, said. The box stand-in now answers the audit and the traces since the time asked, so a count
  made twice would show.

## Not here

Nothing ran on a real VM. A product change was not needed (`services/**` untouched).
