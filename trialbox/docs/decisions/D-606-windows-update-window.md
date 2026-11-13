# D-606 Windows Update in a declared window, no drivers from it, and nobody but administrators shuts down

- **Task:** NEW-WIN-5 (`docs/plan/33-plan-v7.md` section 2.3; lane W; wave 3)
- **PR:** this branch (`agent/NEW-WIN-5-windows-update`)
- **Date:** 2026-11-13
- **Status:** accepted for the form and the installer's logic. Nothing in it has run on Windows: every Windows
  behaviour below is by Microsoft's documentation, and is rehearsed at P-0 (lines 45 to 56)
- **Owner decisions:** D-494 (the workstation is also a desktop; Windows is patched by Windows Update), OD-10 (no
  figure in the installer that is not read from the hardware or a declared setting with its reason)
- **Builds on:** D-600 (the installer), D-602 (start without a person), D-421 (the host check of a Windows
  workstation: `host_facts.ps1` read by `wsl2_policy.py`), D-112 (the serving record)

## Context

The workstation runs the night with nobody there, and it is somebody's desktop by day. Three things can stop a
night or change what was measured without anyone deciding it: Windows Update restarts the PC when it likes (its
default is "outside active hours", which is the night); Windows Update replaces the NVIDIA driver with a newer
one, so the box no longer runs the driver its serving record was measured with; a desktop user shuts the PC down
on the way home. D-421 already judged Windows Update from inside WSL2 ("a policy must be set") but nothing set one.

## Decision

1. **The update window is two declared settings**: `TB_WIN_UPDATE_WINDOW_START` (default 19) and
   `TB_WIN_UPDATE_WINDOW_HOURS` (default 6), the installer's `-UpdateWindowStart` and `-UpdateWindowHours`; a test
   holds the installer's defaults to the declared ones. The reasons for the figures: 19:00 is after desk hours and
   seven hours before the default night (`nightly_at` 02:00); 6 hours is the shortest window Windows can hold,
   because Windows protects at most 18 hours of a day from restarts (Microsoft: "Configure active hours", maximum
   range 18 hours), and the shortest window leaves the night the most room.
2. **How Windows is told** (local policy values under `HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate`,
   written in step 12 with the boot task): `AU\AUOptions=4` with `ScheduledInstallDay=0` and
   `ScheduledInstallTime=<start>` (install every day at the window's first hour), `AU\NoAutoUpdate=0`, and
   `SetActiveHours=1` with the active hours running from the window's end to its start, so a restart can happen
   only inside the window. Updates are never switched off: the window says when, not whether.
3. **A policy that is already there is the site's IT's, and is kept.** When any of `NoAutoUpdate`, `AUOptions` or
   `SetActiveHours` is set and this installer did not set it (it records its own window in
   `HKLM\SOFTWARE\TrialBox`, `update_window`), nothing of the window is written; the owner is told, and the host
   check judges what IT set by the rules of D-421. A domain's group policy would overwrite local values anyway.
4. **Drivers are not taken from Windows Update**: `ExcludeWUDriversInQualityUpdate=1`, written also beside IT's
   policy. The NVIDIA driver changes only when a person installs one from the offline media.
5. **`trialbox doctor` judges both from inside WSL2** (PASS on a plain Linux host):
   - `update_window`: the window (the two settings, from `deploy/.env` or the declared defaults) against the
     night's start (`data_source.nightly_at`). FAIL when the night starts inside the window. PASS names the hours
     between the night's start and the window. The plan says "placed outside the night from the night's measured
     length": no record of a night's length exists on the box yet, so the check states the room and does not claim
     the night fits it. When the night's length is recorded (lane B), this check compares the two.
   - `wsl2_versions`: the driver the card answers with (`nvidia-smi`) against the `card.driver` of that card's
     serving record (the site's own first, then the vendor's): FAIL when they differ or the card does not answer.
     The WSL2 kernel against the record's `wsl_kernel`: FAIL when they differ. No serving record carries
     `wsl_kernel` today (lane G's `tools/serving_config.py`), so until it does this part is a WARN that names the
     running kernel.
6. **The host check reads the Windows side** (`host_facts.ps1`, still read-only; `wsl2_policy.py`): the
   installer's window held by Windows is a PASS (before: any scheduled install was a WARN), a window Windows no
   longer holds is a policy FAIL; drivers not excluded is a policy FAIL; a sign-in screen that offers shutting
   down is a policy FAIL. Facts of a release before this card are judged as before.
7. **Only administrators shut the workstation down.** The user right "Shut down the system"
   (`SeShutdownPrivilege`) is set to the Administrators group with `secedit /configure`, and the sign-in screen
   stops offering it (`ShutdownWithoutLogon=0`). secedit's files are kept in the install's own folder
   (administrators only) and hold no secret; the installer still removes nothing. The right is read back with
   `secedit /export` by the installer at every start, and put right. It is **not** among the host check's facts:
   Windows gives the right only through an export to a file, and `host_facts.ps1` writes nothing. Sleep was
   already off (D-602); a standard user can still sign out and lock.
8. **Neither part stops the install.** A PC whose policy cannot be written still runs TrialBox; the owner is told
   what it means in plain words, and the host check fails it by name.
9. **A finished install gets all of this at its next start**, once, and is silent after that.

A box whose owner names another window must also carry it in `deploy/.env` (`TB_WIN_UPDATE_WINDOW_START`,
`TB_WIN_UPDATE_WINDOW_HOURS`), or `doctor` judges the default one. The Windows installer does not write
`deploy/.env` (lane D's `box-install.sh` does); named to the integrator.

**Reuse check.** Windows' own policy values and `secedit` cover it; nothing is added. PSWindowsUpdate (a
PowerShell module) drives installs by script, which is not wanted: Windows Update itself keeps installing, only
inside the window. A WSUS or Intune policy, where the hospital has one, is exactly point 3.

## What is proven here, and what is not

Proven here: the installer's logic with every Windows command behind a seam (Pester on PowerShell 7,
`tests/windows`: the values written for every start hour, the 18-hour limit, a second run, another window, IT's
policy kept, the shutdown right, a finished install); the two `doctor` checks on a fake `/proc`, a fake card and
written records; the host check's rules on written facts (`tests/unit/test_windows_update.py`).

Not proven, all on the P-0 sheet: that Windows 11 reads these policy values as documented (lines 46, 47); that a
restart really stays inside the window (line 51, which can take days); that the driver is not replaced (line 53);
that the user right takes and a standard user cannot shut down (lines 48 to 50); that `secedit /configure` with
this template changes only this right; what `nvidia-smi` inside WSL2 prints as the driver version next to the
version Windows shows (line 53).

## Consequences

- For lane G: `wsl_kernel` in the serving record (`tools/serving_config.py measured`, the kernel's release when
  measured under WSL2), so `wsl2_versions` can be red on a changed WSL.
- For lane B: a record of the night's measured length on the box, so `update_window` can compare it.
- For lane D: `deploy/check_host.sh` already runs `wsl2_policy.py`; nothing to change. `box-install.sh` could
  take the window into `deploy/.env`.
- RUNBOOK §24 (lane D's) still says hospital IT starts installs by hand; with this card that is the form only
  where IT's own policy is kept (point 3).
