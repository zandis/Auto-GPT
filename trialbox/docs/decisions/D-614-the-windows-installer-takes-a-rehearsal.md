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
2. **Kept to the end.** The state carries it over the step-5 restart and over a run started again by hand without
   the switch: a run never turns a rehearsal off (a site's box is a new install, as D-726 says). A finished install
   that was no rehearsal is not made one: `-Rehearsal` is then ignored and logged.
3. **Not on the first run.** When an earlier run installed the stack and stopped before the owner finished the
   set-up, `wsl-setup.sh install` goes on with `box-install.sh --firstrun` alone: `box-install.sh` refuses
   `--rehearsal` with `--firstrun`, and the first run finishes the box as it was installed.
4. Everything else is D-726's: the Windows side decides nothing about TEST, the stand-ins or the bundle. A
   rehearsal bundle started without `-Rehearsal` is refused by the Linux installer, inside step 14.
5. `wsl-setup.sh install` takes its options by name (`--yes`, `--rehearsal`) and refuses one it does not know.

**Reuse check.** D-726's argument is used as it is; the Windows side adds one switch and one word in a command line.

## What is proven here, and what is not

Proven here: Pester (151 tests with the rest): the switch reaches the Linux installer's command line and is said
and logged before the import; never without the switch; kept over the restart and over a run started again without
it; ignored on a finished install that was no rehearsal. Python tests on a fake WSL2 system: `wsl-setup.sh install`
hands `--rehearsal` on with or without `--yes`, refuses an unknown option, and leaves it off the first run.

Not proven (P-0 Part 10): that the Linux installer, started this way inside WSL2, makes the box TEST with the mark
and doctor's WARN "rehearsal box"; that after Stage A on the same PC the Linux installer takes the box as a
rehearsal (by reading, Stage A's stop comes before it writes anything of a site; if it refuses, the box is emptied
as `docs/runbook/16-box-install-rehearsal.md` says).

## Consequences

- `docs/handover/P-0-BUILD-THE-MEDIA.md` gives Stage B's exact commands: the bundle built with `--rehearsal`, and the
  installer started with `-Rehearsal`.
- The P-0 sheet gains Part 10 (lines 84 and 85).
