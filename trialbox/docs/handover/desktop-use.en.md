# Using the TrialBox workstation as a desktop

**Reader:** the trial team, who also use this PC as a desktop.

This PC is also the hospital's TrialBox. It reads charts every night and answers the TrialBox console all day,
on the same graphics card your screen uses (NEW-WIN-6, D-607; plan v7 section 2.3, rules 5 and 6).

## What you may run

- Office work: documents, spreadsheets, mail.
- A web browser, including video.
- Video calls.
- The TrialBox console.

## What you may not run on this PC

- Another AI model or model server (for example a local chat model).
- Training of a model.
- 3D rendering or video encoding on the graphics card.
- Games.
- Any other long computing job on the graphics card.

The reason: TrialBox's two models hold about two thirds of the graphics card's memory, all the time. The rest is
for the screen and for the programs in the first list. A program from the second list takes that rest, and then
the models cannot start again after a restart; the night's reading stops.

## Do not turn the PC off

Sign out or lock the screen when you leave. Do not shut the PC down and do not unplug it: the night's work runs
while nobody is there. Shutting down is switched off for your account for this reason. Windows installs its
updates and restarts by itself in the evening; TrialBox starts again without anyone.

## Your account

You sign in with your own standard account. Only the box owner and the hospital's IT have an administrator
account. Do not ask for the administrator password to install a program; ask the box owner.

## When TrialBox's health line is red and names the graphics card

The console's health line says how much of the card programs outside TrialBox hold. When it is red:

1. Close the program that uses the card (see the second list).
2. If you do not know which one, tell the box owner. The box owner's host check names the programs.
3. Do not restart the PC to fix it.

## For the box owner: one setting in the NVIDIA Control Panel

Set it once, by hand, signed in as the administrator (the installer cannot set it: NVIDIA gives no command for
it): NVIDIA Control Panel, Manage 3D settings, Global Settings, "CUDA - Sysmem Fallback Policy", choose
"Prefer No Sysmem Fallback". With it a program that asks for more card memory than is free gets an error at once;
without it Windows moves memory to ordinary system memory and everything on the card becomes slow. Whether this
setting also governs programs inside WSL2 is not known yet; the rehearsal on a real workstation records it (P-0
line 60).
