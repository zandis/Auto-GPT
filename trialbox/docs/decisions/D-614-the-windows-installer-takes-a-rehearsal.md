# D-614 The Windows installer takes a rehearsal (`-Rehearsal`) and hands it on

- **Task:** NEW-WIN-11 (lane W): Stage B of P-0 on Windows (R3), on lane D's rehearsal profile D-726
- **PR:** this branch (`agent/NEW-WIN-11-rehearsal`), stacked on NEW-WIN-10 (D-613, #600)
- **Date:** 2026-11-15
- **Status:** accepted. Nothing in it has run on Windows: the proof is the P-0 sheet's Part 10 (lines 84 and 85)
- **Builds on:** D-726 (a rehearsal box says so: `deploy/box-install.sh --rehearsal`), D-600 (the installer),
  D-605 (the media)

## Context

Stage B of P-0 needs the stack up on a PC whose card has no serving record, with placeholder models. Lane D's
D-726 makes that a rehearsal box: one explicit argument, `--rehearsal`, to `deploy/box-install.sh`; the box is TEST
and says so; the model stand-ins and an unmeasured card are honoured on it only; a bundle built with
`make_bundle.sh --rehearsal` is refused by a site box. The Windows installer starts `box-install.sh` through
`wsl-setup.sh install` and had no way to pass the argument on.

## Decision

1. `box-install.ps1 -Rehearsal` records `rehearsal: true` in its state (`state.json`, administrators only) and
   step 14 adds `--rehearsal` to `wsl-setup.sh install`, which hands it to `box-install.sh`. The window says it is
   a rehearsal install, and the log says so, before step 1 changes anything.
2. **Asked for every time, never assumed.** The resume task's command line carries `-Rehearsal` over the step-5
   restart. A run started by hand without the switch on an unfinished rehearsal stops before it changes anything and
   says how to go on (start it with `-Rehearsal`) or how to start a site's install (empty the box, remove the state,
   install anew): the state outlives the box inside WSL2, and an emptied box with no mark would otherwise be made a
   rehearsal with a site's media unasked (review finding 3). A run never turns a rehearsal off. A finished install
   that was no rehearsal is not made one: `-Rehearsal` is then ignored, on screen and in the log. An unfinished
   install that began without the switch may be started with it (Stage B after Stage A): the Linux installer
   refuses a box that holds a site's install from no rehearsal (D-726).
3. **Not on the first run.** When an earlier run installed the stack and stopped before the owner finished the
   set-up, `wsl-setup.sh install` goes on with `box-install.sh --firstrun` alone: `box-install.sh` refuses
   `--rehearsal` with `--firstrun`, and the first run finishes the box as it was installed.
4. Everything else is D-726's: the Windows side decides nothing about TEST, the stand-ins or the bundle. A
   rehearsal bundle started without `-Rehearsal` is refused by the Linux installer, inside step 14.
5. `wsl-setup.sh install` takes its options by name (`--yes`, `--rehearsal`) and refuses one it does not know.

**Reuse check.** D-726's argument is used as it is; the Windows side adds one switch and one word in a command line.

## What is proven here, and what is not

Proven here: Pester (153 tests with the rest): the switch reaches the Linux installer's command line and is said
and logged before step 1; never without the switch; named in the resume task's command line and carried over the
restart; a run by hand without it on an unfinished rehearsal stops with nothing changed, and goes on with it;
ignored, on screen, on a finished install that was no rehearsal. Python tests on a fake WSL2 system: `wsl-setup.sh
install` hands `--rehearsal` on with or without `--yes`, refuses an unknown option, and leaves it off the first run.

Not proven (P-0 Part 10): that the Linux installer, started this way inside WSL2, makes the box TEST with the mark
and doctor's WARN "rehearsal box"; that after Stage A on the same PC the Linux installer takes the box as a
rehearsal (by reading, Stage A's stop comes before it writes anything of a site; if it refuses, the box is emptied
as `docs/runbook/16-box-install-rehearsal.md` says).

## After the review

One fresh reviewer, verdict "fix first", no HIGH: the Stage B command did not run on a PC whose execution policy
is the default (now started through `powershell.exe -ExecutionPolicy Bypass -File`); Stage B on the same PC would
have run Stage A's Linux installer (the page now removes Stage A's tree first); the kept state could make an emptied
box a rehearsal unasked (point 2); the ignored switch was said in the log only; the test checked "before the import",
not "before step 1". All fixed, test first.

## Consequences

- `docs/handover/P-0-BUILD-THE-MEDIA.md` gives Stage B's exact commands: the bundle built with `--rehearsal`, and the
  installer started with `-Rehearsal`.
- The P-0 sheet gains Part 10 (lines 84 and 85).
