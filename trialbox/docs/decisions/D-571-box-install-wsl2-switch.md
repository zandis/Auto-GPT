# D-571 The box installer knows when it runs under WSL2

- **Task:** BOX-WSL2 (TB-PLAN-07 v7.2, `docs/plan/33-plan-v7.md` section 2.3, row "box-install.sh ... reused with a
  WSL2 switch"; asked for by lane W for NEW-WIN-1, pull request #362, which does not depend on it)
- **PR:** this branch (`agent/BOX-WSL2-switch`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-466 (the box form: `box-install.sh`, the first-run code on the box's own screen), D-566
- **Read by:** lane W (the Windows installer runs this script inside WSL2 and shows its output in its own window)

## Context

`box-install.sh` shows the first-run address and code on the box's own screen by writing
`/etc/issue.d/trialbox-firstrun.issue`, and sets the host's time zone with `timedatectl`. Under WSL2 no screen
shows that file, and Windows keeps the clock and the zone.

## Decision

1. **The script detects WSL2** from the kernel's release (`uname -r` names Microsoft). `TB_BOX_WSL2=1` or `0`
   sets it for a test; any other value is refused.
2. **The address and the code are built once and printed.** They are written to the issue file only when the
   script does not run under WSL2, and the file is removed after the wizard only then. Under WSL2 the Windows
   installer's window shows the script's output.
3. **Under WSL2 the host's time zone is not set**; one line says that Windows keeps the clock and the zone. The
   site's zone is still written to the settings and to `deploy/.env` as on a box.
4. **Two lines are a contract with the Windows installer** and are not reworded without lane W: the last line
   `TrialBox is ready` of `box-install.sh` and `TrialBox is running` of `install.sh`.

## Consequences

- Nothing changes on a box that is not WSL2.
- `TB_BOX_WSL2` is a knob of the shell script, like its other test knobs (`TB_BOX_NO_ROOT`, `TB_ISSUE_DIR`); no
  Python reads it, so it has no row in the declared settings.
- No limit, no new store.
