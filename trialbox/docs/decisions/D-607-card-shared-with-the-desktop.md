# D-607 The card shared with the desktop: a health line, the programs by name, and the rule for desktop users

- **Task:** NEW-WIN-6 (`docs/plan/33-plan-v7.md` section 2.3, rules 5 and 6; lane W; wave 3)
- **PR:** this branch (`agent/NEW-WIN-6-shared-card`), stacked on NEW-WIN-5 (D-606)
- **Date:** 2026-11-13
- **Status:** accepted for the form. No reading in it has been taken on a Windows workstation: the proof is test
  P-11 on the reference workstation, rehearsed at P-0 (lines 57 to 62). The two thresholds are placeholders until
  P-11 (point 3)
- **Owner decisions:** D-494 (the workstation is also a desktop), OD-10 (no figure that is not read from the
  hardware or a declared setting with its reason)
- **Builds on:** D-379 (the health line), D-112 (the serving record), D-421 (the host check of a Windows
  workstation), D-606 (only administrators shut down)

## Context

Rule 6 of the Windows form: a desktop user may run office work, a browser, video calls and the console; not
another model, training, rendering or a game. The pair holds 62.6 of 95.6 GiB of the card; about 33 GiB is spare,
and the display and the desktop take from that. The plan asks for a health line that "reads, on the Windows side,
the card memory held by programs outside TrialBox and turns red when the models' share is at risk", for the driver
"set not to spill model memory into system memory", for standard accounts for desktop staff, and for the rule in
the handbook in three languages.

## Decision

1. **The health line `desktop_gpu` is read from inside WSL2, every minute, with the other host facts.** The
   Windows driver reports the whole card's memory to WSL2 (`nvidia-smi`: used and total), Windows programs'
   included, but not by which program. What is outside TrialBox is therefore: the memory in use less the models'
   measured share (`memory_used_mib` of the box's serving record) while the models are up (the self-test passed),
   and all of it while they are not. It is set against the card's spare memory, the card less the models' share.
   Why not "on the Windows side", as the plan words it: the health facts are written each minute by a timer that
   runs as root inside WSL2, and starting Windows PowerShell from there sixty times an hour, with nobody signed
   in, is a path nobody has run; the amount is what turns the line, and WSL2 has the amount. If P-0 line 57 shows
   WSL2 does not see Windows programs' memory, the line moves to the Windows counters of point 4.
2. **Red means "the model servers may not fit after a restart"**, in those words, with what to do (close the
   program). While the models are loaded their memory is theirs; the harm comes when they must load again and the
   desktop has taken the room. A card that cannot be read, or a box with no serving record (or two and no
   `TB_GPU_PROFILE`), is a warning that says so, never "ok". On any host that is not WSL2 there is no such line.
3. **The thresholds are two declared settings**, `TB_HEALTH_DESKTOP_GPU_WARN` (70) and
   `TB_HEALTH_DESKTOP_GPU_RED` (85), percent of the spare memory. Their reason is stated as what it is: the same
   two figures as the disk line (D-379), taken so that the line exists and can be seen to turn; nothing has
   measured what the display, a browser with video and a video call really hold beside the pair. P-11 measures
   it and the settings are corrected from the figure, as the plan says of rule 6.
4. **The host check names the programs** (`host_facts.ps1`, read-only; `wsl2_policy.py`): Windows' own
   per-program card memory (the CIM class `Win32_PerfFormattedData_GPUPerformanceCounters_GPUProcessMemory`, the
   same name in every display language; localised counter paths are not used), summed for WSL2's virtual machine
   (`vmmem`, `vmmemWSL`) and for everything else, with the five largest by name. It gives no verdict on the
   amount (the health line does): it answers "which program" when the line is red.
5. **Standard accounts for desktop staff**: the host check counts the enabled accounts in the Administrators
   group (a number, no names) and warns above one. The installer creates no accounts: an account needs a
   password, and the installer handles no secret but the recovery key it shows. The rule for staff says how they
   sign in.
6. **The NVIDIA setting "CUDA - Sysmem Fallback Policy: Prefer No Sysmem Fallback" is a step by hand**, written
   in the desktop-use rule for the box owner. The installer does not set it: by NVIDIA's documentation it is a
   setting of the NVIDIA Control Panel (Manage 3D settings), and NVIDIA documents no command or registry value
   for it. A third-party tool (NVIDIA Profile Inspector) can write driver profiles; that would be a new
   dependency on the media for one switch, and it is not proposed. **Whether the setting governs programs inside
   WSL2 at all is not known**; P-0 line 60 records it, and the step is struck if it has no effect.
7. **The rule for desktop users** is `docs/handover/desktop-use.{en,ja,zh-TW}.md`: what may run, what may not and
   why, do not turn the PC off (D-606), your account, what to do when the health line is red. A test holds the
   three to the same parts and to the product's wording rules. It goes into the owner's handbook (NEW-WIN-9) and
   onto the media.

**Reuse check.** `nvidia-smi` and Windows' own GPU counters cover the readings; the health line, its thresholds
and the page that shows it are the existing ones (`tb_common.metrics`, D-379). Nothing is added. NVIDIA Profile
Inspector covers point 6 and is not taken (above).

## What is proven here, and what is not

Proven here (`tests/unit/test_desktop_gpu.py`, written figures): the arithmetic of the line at the declared
shares, with the models up and down; a card that cannot be read and a missing or ambiguous record; that no other
host gets the line; the host check's two lines on written facts; that `host_facts.ps1` stays read-only and lists
no account names; the three language versions of the rule.

Not proven, all on the P-0 sheet (Part 7) and in P-11: that `nvidia-smi` inside WSL2 reports memory held by
Windows programs (line 57); that the timer inside WSL2 can call it with nobody signed in (line 58); that the
Windows counter class exists on the site's build and attributes WSL2's card memory to `vmmem*` (line 59); what
the sysmem setting does for WSL2 (line 60); that the line turns red under a real program and how fast (line 61);
that a standard account cannot stop the owner's WSL2 (line 62, rule 5 of the plan); every figure of rule 6.

## Consequences

- `libs/tb_common/metrics.py` (the health module) gains one check and one fact; `tools/trialbox/ops.py` writes
  it without change (it calls `host_facts`). Named to the integrator, since the module is shared.
- The console shows the new line in English like the other checks; its level word is translated by the console.
- P-11 corrects the two settings; a site record of the pair on the workstation's own card corrects the models'
  share (the shipped record was measured on the cloud machine's card of the same size).
