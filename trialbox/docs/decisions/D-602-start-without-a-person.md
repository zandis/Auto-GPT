# D-602 Start without a person: the boot task, and Docker and the stack enabled inside WSL2

- **Task:** NEW-WIN-2 (`docs/plan/33-plan-v7.md` section 2.3; lane W)
- **PR:** this branch (`agent/NEW-WIN-2-start-without-a-person`), stacked on NEW-WIN-3 (D-601) and NEW-WIN-1 (D-600)
- **Date:** 2026-11-12
- **Status:** accepted for what the installer does; whether WSL2 starts from the task with nobody signed in has not
  been seen. It is the first question of test P-0 and of P-13
- **Owner decisions:** D-494 (plan section 2.3 rule 7: a restart at any hour is safe, the stack returns with nobody
  signed in; sleep and hibernation stay off)
- **Builds on:** D-421 (`register_keepalive.ps1`, the task `TrialBox-WSL2`, the checks of `wsl2_policy.py`), D-377
  (`trialbox.service` starts the stack after a restart), D-600

## Decision

1. **The installer registers the task.** Step 12 `boot-task`, before the Linux installer waits for the owner, runs
   `register_keepalive.ps1` for the installing account and the distribution `TrialBox`: the task `TrialBox-WSL2`
   starts at boot, with the sign-in type S4U (no password is stored), keeps one `wsl.exe` open and is started
   again within a minute when it ends. The task has one definition, `register_keepalive.ps1`; the installer does
   not repeat it. Registered before step 13, a restart while the owner is still in the set-up brings WSL2 back.
2. **Sleep and hibernation off, by the installer.** `powercfg /hibernate off` (which also turns Fast Startup off)
   and the sleep and hibernate timers on mains power set to never. A workstation that sleeps serves nobody, and
   `hiberfil.sys` would hold WSL2's memory (D-421). A failure of `powercfg` stops the step.
3. **Inside WSL2 systemd does the rest.** `docker.service` is enabled by the installer's `packages` step and
   `trialbox.service` by `deploy/install.sh` (D-377). The install is not counted as finished until
   `wsl-setup.sh boot-check` finds both enabled; otherwise it stops and names the unit.
4. **If S4U cannot start WSL2** (P-0 line 25 answers it), the fallback is decided with NEW-WIN-8, which has the
   same question for the key hand-over: a task that stores no password may not be allowed what WSL needs. The
   candidates are a stored password for the task (a secret Windows keeps) or a service; neither is built here.

## What is proven here, and what is not

Proven (Pester, stubs): the step's order, the task's account, distribution and name, the power commands, the stop
when the task cannot be registered, the unfinished state while a unit is not enabled; that the task's name is the
one `host_facts.ps1` and `wsl2_policy.py` look for.

Not proven, by Microsoft's documentation and not run: that a task at boot with the sign-in type S4U may start a
WSL2 distribution that belongs to that account with nobody signed in (Microsoft Learn, `New-ScheduledTaskPrincipal`;
WSL documents no statement either way); that the distribution stays up while that one `wsl.exe` runs; that
`powercfg /change ... 0` holds on a machine with a vendor power plan. P-0 lines 24 to 27; P-13 on the reference
workstation, with a job running.
