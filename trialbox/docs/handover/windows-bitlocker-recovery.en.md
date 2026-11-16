# When Windows asks for a BitLocker recovery key

**Reader:** the box owner, and the person who keeps the recovery keys.

Before Windows starts, a blue screen titled "BitLocker recovery" asks for "the recovery key for this drive". This
page says what to do (NEW-WIN-14, D-617). It replaces the locked-box page of the Linux form. The owner's other
pages: `windows-owner.en.md`.

Written before the first rehearsal on a real Windows PC: where this page and the screen differ, the screen is
right, and we want to hear it.

## What you see

- The title "BitLocker recovery" and a box for 48 digits, before the Windows sign-in.
- A key ID: eight letters and digits that name the key the screen wants.
- Nothing is lost while the screen waits. The PC can stay on it as long as needed.

## What to do

1. Find the key with the same key ID. On the set-up day the installer showed each drive's key with its key ID,
   and the printed page carries it too.
2. Type the 48 digits. The dashes come by themselves. If the number keys do nothing, the function keys F1 to F10
   type 1 to 9 and 0, as the screen says.
3. Windows starts, and TrialBox starts by itself. Wait five minutes, then look at the console's health line.
4. Tell us the day it happened and what happened just before (a firmware or BIOS update, a changed part, the PC
   moved). Never write the key itself in a message.

## Why it happens

- A firmware or BIOS update, or a change of its security settings (Secure Boot).
- A changed main board, or the security chip cleared.
- A drive taken to another PC.
- If the screen comes at every start, the security chip no longer opens the drive: tell us before anything else.

## If the key is lost

Without the key nobody can open the drive, we cannot either, and what was on it is gone. What is left is the
backup on the hospital's share or the outside disk: `WINDOWS-BACKUP-RESTORE.md` says how it is put back on a
rebuilt box. Never try to turn BitLocker off, or "repair" the drive with a tool, to get past this screen: that
loses the data for certain.
