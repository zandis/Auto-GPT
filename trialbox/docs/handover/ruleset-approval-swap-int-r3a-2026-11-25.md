# INT-R3A: an approval swaps the rulesets' working copy whole, and the reader refuses a read that is not whole

**Reader:** the people who build TrialBox: the integrator, lane J (the criteria compiler) and the ruleset loader's
owner. Findings for builders, so in one language.

- **Card:** INT-R3A (ordered by the owner; a ring-0 condition)
- **Date:** 2026-11-25
- **Findings:** [`ruleset-approval-swap-int-r3a-2026-11-25/findings.json`](ruleset-approval-swap-int-r3a-2026-11-25/findings.json)
  (INTR3A-01 to INTR3A-05)
- **Tests:** `tests/unit/test_ruleset_swap_int_r3a.py`

## The fault

The deep check of master 6c73db64 (row R3 (a)): `RulesetRepo.materialize` (`services/criteria_compiler/repo.py`,
lines 190-200 on master) built the new copy in `.<ruleset>.tmp`, then removed the working copy (`shutil.rmtree`) and
renamed the new one in. A reader (`tb_common.ruleset.load_approved`, `Ruleset.load`, lines 119-124) lists the folder
and reads file by file, so a reader that met an approval found no folder, a folder going away or half of one. It
returned whatever it had read: a partial ruleset, which a service can screen on.

## The change

**The writer** (`materialize`): the new copy is written beside the old one, every file in a write loop of its own
with an fsync, every folder fsynced; then the two folders are exchanged in one rename (`renameat2` with
`RENAME_EXCHANGE`); the old copy, now under the temporary name, is removed after the swap; the rulesets folder is
fsynced. A first copy (no working copy yet) is renamed in. A kill at any step leaves the whole old copy or the whole
new one; the temporary folder it leaves is removed, with a warning in the log, when the repository is next opened
(`RulesetRepo.__init__`, the compiler's start). The atomic-write helper of `tools/update_status.py` is not used
(it is being fixed by H-142).

**The reader** (`load_approved`): what it read is held against the tree of the ruleset's approval tag
(`<ruleset>/v<version>`, the version the manifest read names): the git hash of every file, and the set of files. A
read that differs is read again (five reads); then it raises `RulesetReadIncomplete`, its own type, not a
`RulesetNotApproved` (which callers read as "no approved version"), not an `OSError` and not a `ValueError`. A file
changed, cut, emptied, removed or added on disk is refused the same way. Not held, as before: a copy with no
repository (`seed_working_copy`; a site box refuses it, D-640), a version with no tag and a manifest that does not
parse (both refused after the read), and a tag that points at nothing (a site box refuses it in `seeded_approval`; a
DEV or TEST box runs it, as `test_a_broken_repository_stops_no_timer` asks; see the question below).

## A question for the integrator

`tests/unit/test_new_life_1_no_preapproved_ruleset.py::test_a_broken_repository_stops_no_timer` asserts that a TEST
box still lists a ruleset whose approval tag points at nothing. The first form of this card refused it there too
(the read cannot be held against a tag that is not there), and that test failed. The card keeps the old behaviour so
the test passes unchanged. The proposed change, if the integrator rules for failing closed: `_differs_from_tag`
returns a reason instead of "" for such a tag, and the test's last assertion becomes `== ["RA-BIO"]` on the TEST
box as well.

## The callers, before and after

| Caller | Before | After |
| --- | --- | --- |
| `orchestrator.scenarios.review.approved_or_none` (FEAS, SCREEN, NAV runs, `require_approved`) | a partial ruleset was returned and run; a missing manifest was "not approved" (None: a FEAS job with a protocol compiled a new draft) | the refusal propagates; the job fails (`Orchestrator.run`: a Failed reply, the error logged), nothing is screened, no draft is compiled |
| `scenarios.retention` (via `approved_or_none`, `run=False`) | a missing manifest made the study "not approved", so its pool could be pruned | the refusal propagates; the retention job fails, nothing is pruned |
| `scenarios.calibration` (via `approved_or_none`) | a partial manifest's routing was used | the job fails |
| `scenarios.approve._approved` | a partial ruleset was compared | the refusal propagates; the approval job fails |
| `tb_common.ruleset.approved_here` (the timers) | a partial ruleset counted as approved | `False` with a warning (it catches every error); the next tick asks again |
| `orchestrator.app` `/rulesets/{id}`, `study_info`, `approved_of`, `/registry/{id}/promote` | `FileNotFoundError` gave 404 / none; a partial ruleset was shown | the refusal is not caught: an error answer (500) after five reads; nothing is promoted |
| `console.backend` `criteria_of`, `approval_state_of`, `ruleset_infos` | a partial ruleset was shown | an error answer (500) after five reads; the page is not run on |
| `tools.restore_drill`, `tools.public_e2e` | as their own handlers | `restore_drill` names the error type; `public_e2e` stops on it |

No caller screens on a refused read: the screening scenarios reach a ruleset only through `approved_or_none`.

## The proof

`TB_ENV=TEST PYTHONPATH=libs:services:. .venv/bin/python -m pytest tests/unit/test_ruleset_swap_int_r3a.py -p no:cacheprovider -n 0 -q -rP`

| Tree | Result | The readers' loads in 200 approvals (two reader processes) |
| --- | --- | --- |
| master 6c73db64 (the test file copied in) | 9 failed | whole 1120, missing 20, partial 15, other 16 ("no approved version"); a second run: whole 1136, missing 30, partial 15, other 49 |
| the card's head | 9 passed | whole 547, 562, 701 in three runs; missing, partial, other and refused 0 |

On master the kill test fails on the left-over temporary folder after a kill before the working copy's removal
(it stops at the first failing step); the reader test raises a JSON error or loads a partial ruleset; the caller
test reaches "running".

## Not done

- No fallback where `renameat2` exchange is missing (another OS, a file system without it): the approval fails and
  the old copy stays whole (INTR3A-02).
- The other forms of fault type 2 found are reported, not fixed (INTR3A-03 to INTR3A-05).
