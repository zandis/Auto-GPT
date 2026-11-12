# D-601 `.wslconfig` from the hardware, and the memory caps held to WSL2's share

- **Task:** NEW-WIN-3 (`docs/plan/33-plan-v7.md` section 2.3; lane W)
- **PR:** this branch (`agent/NEW-WIN-3-wslconfig-from-hardware`), stacked on NEW-WIN-1 (D-600)
- **Date:** 2026-11-12
- **Status:** accepted for the arithmetic and the check built here; that the models load and answer under the
  share is measurement P-12 on the reference workstation, and the figure of point 2 is corrected from it
- **Owner decisions:** OD-10 (no figure that is not from the hardware or a declared setting with a reason), D-494
  point 7 (WSL2's share is computed from the installed hardware and one declared setting, the desktop's share)
- **Builds on:** D-600 (the installer), D-421 (`swap=0`, `sparseVhd`), D-466 and D-360 (`tools/box plan` shares
  the memory it sees among the compose caps)

## Context

`wslconfig.example` held a fixed 64 GB. `tools/box plan` runs inside WSL2 and sees only what `.wslconfig` gave
WSL2, so the file must exist, with the right figures, before WSL2 first starts. The workstation is also a desktop:
Windows and the person at it need a part of the memory and the processors.

## Decision

1. **Two readings and one setting.** The installer reads the installed memory (the sum of the memory modules;
   what Windows can use when the firmware lists none) and the logical processors on the Windows side
   (`Get-TbHardware`; the same two facts are added to `host_facts.ps1` as `installed_memory_gb` and
   `logical_processors`). WSL2 gets each, less the desktop's share, rounded down to a whole GB and a whole
   processor. A share that leaves less than 1 GB or one processor stops the installer.
2. **The desktop's share is the declared setting `TB_WSL_DESKTOP_SHARE_PCT`, default 25.** The installer's
   `-DesktopSharePercent` has the same default (a test holds the two together). Reason for 25: on the reference
   workstation (192 to 256 GB, 16 cores or more) it leaves Windows 48 to 64 GB and four cores or more for office
   work, a browser and video calls (plan section 2.3 rule 6), and WSL2 144 to 192 GB. No measurement stands
   behind it yet: P-12 records the peak memory in WSL2 and the free memory in Windows, and the default is
   corrected from that record.
3. **The file.** `[wsl2] memory=`, `processors=`, `swap=0`, `defaultVhdSize=` the data drive's size in bytes (the
   virtual disk may grow to the drive, not to WSL's own default limit), `[experimental] sparseVhd=true`. Its
   first line starts with `# TrialBox`. It is written at step 6, before the distribution is imported.
4. **Whose file it is.** A `.wslconfig` whose first line starts with `# TrialBox` is the installer's: it is
   written again on every run, so a hardware change is taken up by starting the installer again (the file
   NEW-WIN-1 wrote is replaced the same way). Any other `.wslconfig` is the account's own and is kept; the
   installer says so, and says when it lacks `swap=0`.
5. **The caps must fit the share.** `trialbox doctor` gets the line `wsl2_memory`: on a WSL2 kernel it sums the
   memory caps of the box's compose files (`COMPOSE_FILE`; each `TB_MEM_*` from `deploy/.env`, else its default;
   the literal caps) and FAILs when the sum is above WSL2's `MemTotal`. On a plain Linux host it passes with
   "not WSL2". The model servers are counted at their caps: no serving record carries their measured host memory
   yet. When one does, the line takes the measured figure for them (a later card, with the cloud-run lane).

## What is proven here, and what is not

Proven: the arithmetic and the file's lines (Pester); that the file is written before the import; that a foreign
file is kept and the installer's own is rewritten; the doctor line on a fake `/proc`, including the real compose
set capped by `tools/box plan` at 144 GiB.

Not proven, by Microsoft's documentation and not run ("Advanced settings configuration in WSL"): that WSL2 honours
`memory`, `processors`, `swap=0` and `defaultVhdSize` as written and that `defaultVhdSize` applies to a
distribution imported after the file exists; that `Win32_PhysicalMemory` lists the modules on the workstation's
board. These are P-0 lines 20 to 23. That the models load and the dense night runs under the share is P-12.
