# Your TrialBox workstation: the owner's pages

**Reader:** the box owner.

For the person who owns the box: the research lead, not hospital IT. Three parts: the day you set it up, a normal
day, and what to do when something is wrong (NEW-WIN-9, D-611). This PC runs Windows; TrialBox runs inside it and
works at night with nobody there.

Written before the first rehearsal on a real Windows PC: where this page and the PC differ, the PC is right, and
we want to hear it.

## The day you set it up

1. Sign in with the Windows administrator account that will own the box. Use this account for TrialBox from now on.
2. If the PC has no NVIDIA driver yet, install the one on the USB disk (`windows\nvidia`).
3. On the USB disk, double-click `Install-TrialBox.cmd` and allow it. If Windows needs a restart, sign in again
   with the same account: the installer goes on by itself.
4. For each drive the window shows a BitLocker recovery key of 48 digits. Write it down or print it, give it to
   the person who keeps it (hospital IT, in a sealed envelope), and type its last six digits. The installer keeps
   no copy. Without that key the drive's contents are lost if the PC's security chip fails.
5. The window then shows a code and an address. Open the address in the browser on this PC, type the code, and
   answer the set-up pages. When the window says "TrialBox is ready", it is done.
6. Create an ordinary (standard) Windows account for each person who will use this PC as a desktop, and give them
   the page "Using the TrialBox workstation as a desktop".

## A normal day

- Leave the PC on. Sign out or lock the screen; do not shut it down. TrialBox reads the charts at night.
- After a power cut or a restart TrialBox starts by itself, before anyone signs in.
- Windows installs its updates in the evening and may restart the PC by itself between 19:00 and 01:00. Do not
  put the nightly run in those hours.
- Look at the console's health line once a day. Green needs nothing.
- Backups go to the hospital's share or to an outside USB disk, never only to this PC.

## When something is wrong

| What you see | What to do |
| --- | --- |
| The console does not open | Is the PC on? Wait five minutes after a restart. Then open it on this PC itself (`https://localhost/`). If it opens there and not from other computers, tell hospital IT: the network changed |
| The health line is red and names the graphics card | A program on the desktop is using the card. Close it (the desktop-use page lists which). Do not restart the PC for this |
| The health line is red and names the backup | Is the outside disk plugged in, or the share reachable? Then wait for the next night |
| Windows asks for a BitLocker recovery key at start | Type the key with the same key ID as the screen: `windows-bitlocker-recovery.en.md`. If that happens again, tell us |
| Memory, a disk or the graphics card was changed | Double-click `Install-TrialBox.cmd` once more. It changes nothing that is right |
| Anything else | Do not reinstall. Send us the file `C:\ProgramData\TrialBox\box-install\box-install.log` and what the health line says |

Never do these, whoever suggests them: remove or "reset" the Windows feature called WSL or the system named
`TrialBox` in it; install Docker Desktop; install an NVIDIA driver for Linux; copy the box's disk file somewhere
"as a backup". Each of them loses data or stops the box.
