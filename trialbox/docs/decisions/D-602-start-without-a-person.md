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
   A task that is there, enabled and for this distribution is kept as it is: it is not registered or started
   again beside a live keep-alive. A task that is missing, disabled or for another distribution is registered
   again, also on a finished install (with `.wslconfig`, D-601, the only things a second start of a finished
   install may change).
   `register_keepalive.ps1` now defaults to the distribution `TrialBox`, and the host check's judge
   (`wsl2_policy.py`) fails a task whose command starts another distribution.
2. **Hibernation off and no sleep by itself, by the installer.** `powercfg /hibernate off` (which also turns Fast
   Startup off) and the sleep and hibernate timers of the current power plan set to never, on mains and on
   battery. A workstation that sleeps serves nobody, and `hiberfil.sys` would hold WSL2's memory (D-421). What
   this does not cover: the Sleep button of the Start menu, which a standard account may press; the lid of a
   laptop; a power plan changed later. Those belong to NEW-WIN-5 (what a standard account may do to the machine),
   and the host check judges hibernation and Fast Startup only. The installer says in its window what it changed.
   Nothing undoes it: the tree has no uninstall; to put it back, the owner sets the timers in Windows' power
   settings. A setting Windows refuses (a machine with no hibernation support) is told and does not stop the
   install.
3. **Inside WSL2 systemd does the rest.** `docker.service` is enabled by the installer's `packages` step and
   `trialbox.service` by `deploy/install.sh` (D-377). The install is not counted as finished until
   `wsl-setup.sh boot-check` finds both enabled; otherwise it stops and names the unit. `boot-check` proves
   "enabled", not "returns": before NEW-WIN-8 the site keys under WSL2 wait for a passphrase after every restart
   (WSL2 has no security chip), so the stack does not come back whole by itself yet. P-0 keeps the two apart
   (line 26a: WSL2 started by the task; line 26b: what is up). When `install.sh` could not enable the units (its
   network step failed and it only warned), every start stops at step 13 naming the unit; the remedy is lane
   D's network step under WSL2 (NEW-WIN-4), not this card.
4. **If S4U cannot start WSL2** (P-0 line 26a answers it), the fallback is decided with NEW-WIN-8, which has the
   same question for the key hand-over: a task that stores no password may not be allowed what WSL needs. The
   candidates are a stored password for the task (a secret Windows keeps) or a service; neither is built here.

5. **What an abandoned install leaves.** Steps 1 to 12 done and step 13 never finished: the task and the power
   changes stay, and at every boot WSL2 and Docker start (the stack too, if `install.sh` got that far). The
   installer's stop message says to start it again; nothing else tells the owner. If Windows restarts while the
   first-run wizard waits, the code is gone with the restart (it lives in memory only) and no window opens: the
   owner starts `Install-TrialBox.cmd` again and gets a new code. Both go into the owner's handbook (NEW-WIN-9).

## What is proven here, and what is not

Proven (Pester, stubs): the step's order, the task's account, distribution and name, the power commands, the stop
when the task cannot be registered, the unfinished state while a unit is not enabled; that the task's name is the
one `host_facts.ps1` and `wsl2_policy.py` look for.

Not proven, by Microsoft's documentation and not run: that a task at boot with the sign-in type S4U may start a
WSL2 distribution that belongs to that account with nobody signed in (Microsoft Learn, `New-ScheduledTaskPrincipal`;
WSL documents no statement either way); that the distribution stays up while that one `wsl.exe` runs; that
`powercfg /change ... 0` holds on a machine with a vendor power plan; that the task is started again within a
minute when it ends; that a standard account cannot read, stop or disable the task; that the task runs for a
domain account with no domain controller in reach; what `powercfg` answers on a machine with no hibernation
support. `register_keepalive.ps1` itself runs in no test here (it is Windows cmdlets only). P-0 lines 24 to 27e;
P-13 on the reference workstation, with a job running.
