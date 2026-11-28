# INT-R3A: an approval swaps the rulesets' working copy whole, and the reader refuses a read that is not whole

**Reader:** the people who build TrialBox: the integrator, lane J (the criteria compiler) and the ruleset loader's
owner. Findings for builders, so in one language.

- **Card:** INT-R3A (ordered by the owner; a ring-0 condition)
- **Date:** 2026-11-25
- **Findings:** [`ruleset-approval-swap-int-r3a-2026-11-25/findings.json`](ruleset-approval-swap-int-r3a-2026-11-25/findings.json)
  (INTR3A-01 to INTR3A-10)
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

**One writer at a time.** The doctor, an offline install and an update's restore open the same repository. The
temporary folders are held under a lock on the repository's `.git` folder: a clean-up never removes a copy another
process is building, and it leaves (and logs) a folder it may not write. The card's first head cleaned without the
lock: a second process opening the repository removed the copy being built (INTR3A-07).

**Before an approval writes** (INTR3A-02, the integrator's ruling): `RulesetRepo.check_swap` exchanges two empty
folders in the rulesets folder. The approval (`Compiler._approve`) asks before its FHIR load, its commit and its tag,
and an offline install (`import_ruleset.install`) before its commit and tag. A folder whose file system cannot
exchange is refused (`CompileFailed`, step `approve`, from `SwapUnsupported`) with nothing written.

**An approval cut short after its tag** (INTR3A-08, -09, the integrator's ruling): approving the same version again
builds it from the draft the tag approved, at the tagged approval's time. The same tree finishes the swap (the tag
and its commit stay), and replaces a damaged copy; a different tree is refused with nothing written, and so is a
version with a later one tagged. An offline install of the same content finishes its swap the same way.

**The list** (INTR3A-04, the integrator's ruling): `list_rulesets` never lists a dot-name, so `.<ruleset>.tmp` is
not a ruleset while a copy is built or swapped out.

**The reader** (`load_approved`): what it read is held against the tree of the ruleset's approval tag
(`<ruleset>/v<version>`, the version the manifest read names): the git hash of every file, and the set of files. A
read that differs is read again (five reads); then it raises `RulesetReadIncomplete`, its own type, not a
`RulesetNotApproved` (which callers read as "no approved version"), not an `OSError` and not a `ValueError`. A file
changed, cut, emptied, removed or added on disk is refused the same way. Not held, as before: a copy with no
repository (`seed_working_copy`; a site box refuses it, D-640, a DEV or TEST box runs it), a version with no tag and
a manifest that does not parse (both refused after the read), and a tag that points at nothing (a site box refuses it in `seeded_approval`; a
DEV or TEST box runs it, as `tests/unit/test_new_life_1_no_preapproved_ruleset.py::test_a_broken_repository_stops_no_timer`
asks). The first form of this card refused it there too and that test failed; the integrator ruled to keep the old
behaviour, recorded as INTR3A-06.

## The callers, before and after

| Caller | Before | After |
| --- | --- | --- |
| `orchestrator.scenarios.review.approved_or_none` (FEAS; `require_approved`: SCREEN, microbatch, NAV, SUBMIT, CASE, COHORT) | a partial ruleset was returned and run; a missing manifest was "not approved" (None: a FEAS job with a protocol compiled a new draft) | the refusal propagates; the job fails (`Orchestrator.run`: a Failed reply, the error logged), nothing is screened, no draft is compiled |
| `scenarios.retention` (via `approved_or_none`, `run=False`) | a missing manifest made the study "not approved", so its pool could be pruned | the refusal propagates; the retention job fails, nothing is pruned |
| `scenarios.calibration` (via `approved_or_none`) | a partial manifest's routing was used | the job fails |
| `scenarios.approve._approved` | a partial ruleset was compared | a refused read is "not approved yet": the compiler decides, and replaces the copy |
| `tb_common.ruleset.approved_here` (the timers) | a partial ruleset counted as approved | `False` with a warning (it catches every error); the next tick asks again |
| `orchestrator.app` `/rulesets/{id}`, `study_info`, `approved_of`, `/registry/{id}/promote` | `FileNotFoundError` gave 404 / none; a partial ruleset was shown | the refusal answers as an unreadable ruleset did: 404, no version, none; nothing is promoted |
| `console.backend` `criteria_of`, `approval_state_of`, `ruleset_infos` | a partial ruleset was shown; a file that did not parse was "draft" | the damaged ruleset is shown as not approved; the other rulesets of the list are shown |
| `omop.vocab_load.mark_rulesets` (`Ruleset.load`) | unchecked; reads the manifest only, screens nothing | unchanged (INTR3A-05) |
| `scenarios.cohort` line 600 (`Ruleset.load`) | a draft package unpacked to a private folder, not the working copy | unchanged |
| `tools.restore_drill`, `tools.public_e2e` | as their own handlers | `restore_drill` names the error type; `public_e2e` stops on it |

No caller screens on a refused read: every run of an approved ruleset goes through `approved_or_none`, which lets
the refusal through (an uncut search of `services/` and `libs/`).

## The proof

`TB_ENV=TEST PYTHONPATH=libs:services:. .venv/bin/python -m pytest tests/unit/test_ruleset_swap_int_r3a.py -p no:cacheprovider -n 0 -q -rP`

| Tree | Result | The readers' loads in 200 approvals (two reader processes) |
| --- | --- | --- |
| master 6c73db64 (the test file copied in), 4 runs | 9 failed (the 9 tests of the first head) | missing 20, 30, 21, 17; partial 15, 15, 17, 16; other ("no approved version") 16, 49, 54, 779 |
| the first head 514aa32, 7 runs | 9 passed | missing, partial, other and refused 0 in each (whole 369 to 712) |
| 3dc9395d | 14 passed | whole 613; missing, partial, other and refused 0 |

The five later tests (`-k "swap_writes_nothing or cannot_swap or dot_name or being_built or damaged_ruleset"`): at
514aa32 5 failed (the approval failed with a bare `OSError` after its writes; an install the same; `list_rulesets`
listed `.RA-JAK.tmp`; a second process removed the copy being built; one damaged ruleset took the list down); at
29242cbc 2 failed (the last two); at the head 5 passed.

On master the kill test fails on the left-over temporary folder after a kill before the working copy's removal
(it stops at the first failing step); the reader test raises a JSON error or loads a partial ruleset; the caller
test reaches "running".

## Not done

- No fallback swap where `renameat2` exchange is missing (another OS, a file system without it): the approval is
  refused before it writes (INTR3A-02).
- The other forms of fault type 2 found are reported, not fixed (INTR3A-03, INTR3A-05).
- A kill between the approval's commit on the draft's branch and its tag: no tag names it and no draft waits, so the
  protocol is compiled again (INTR3A-10).
