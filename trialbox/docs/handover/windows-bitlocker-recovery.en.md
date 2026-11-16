# When Windows asks for a BitLocker recovery key

**Reader:** the box owner, and the person who keeps the recovery keys.

Before Windows starts, a blue screen titled "BitLocker recovery" may ask for "the recovery key for this drive". This
page says what to do (NEW-WIN-14, D-617). It replaces the locked-box page of the Linux form. The owner's other
pages: `windows-owner.en.md`.

Written before the first rehearsal on a real Windows PC: where this page and the screen differ, the screen is
right, and we want to hear it.

## What you see

- The title "BitLocker recovery" and a box for 48 digits, before the Windows sign-in. This screen is always for the
  system drive, C:.
- A key ID: eight letters and digits that name the key the screen wants.
- Nothing is lost while the screen waits. The PC can stay on it as long as needed.

## What to do

1. Find the key with the same key ID. On the set-up day the installer showed each drive's key with its key ID,
   and the printed page carries it too: here, the one for drive C:.
2. Type the 48 digits. The dashes come by themselves. If the number keys do nothing, the function keys F1 to F10
   type 1 to 9 and 0, as the screen says.
3. Windows starts, and TrialBox starts by itself. Wait five minutes, then look at the console's health line.
4. Tell us the day it happened and what happened just before (a firmware or BIOS update, a changed part, the PC
   moved). Never write the key itself in a message.

## When the data drive is locked

- The data drive opens by itself once Windows has started. If it does not, there is no blue screen: after sign-in
  the drive shows a padlock in File Explorer, and TrialBox does not start.
- Double-click the drive and choose to enter the recovery key. Any recovery key of that drive opens it: the one with
  the key ID the window shows, or, if none matches, the key you were given for the data drive on the set-up day.
- If no key you hold opens it, call us before anything else: the drive may still be opened another way.

## Why it happens

- A firmware or BIOS update, a boot-manager or security-chip update, or a change of the security settings (Secure
  Boot, the start order).
- A USB stick, a dock or another disk attached while the PC starts.
- A changed main board, the security chip cleared, or a drive taken to another PC.
- With a PIN at start (the `tpm_pin` setting): too many wrong PINs.
- If the screen comes at every start: first take out every USB stick and disk and undock the PC, then restart. If
  it still comes, the security chip no longer opens the drive: tell us before anything else.

## If no key opens the drive

1. Undo the last change, if there was one (the Secure Boot setting, the start order, an attached disk), and
   restart: often the security chip then opens the drive again by itself.
2. Ask hospital IT to look the key ID up: a PC joined to the hospital's domain or to Microsoft Entra, or signed in
   with a Microsoft account, often keeps a copy of the key there (Active Directory, Entra, the Microsoft account).
3. Call us.

Only when all three find nothing is the key lost. Then nobody can open the drive, we cannot either, and what was on
it is gone; what is left is the backup on the hospital's share or the outside disk: `WINDOWS-BACKUP-RESTORE.md`
says how it is put back on a rebuilt box. Never try to turn BitLocker off, or "repair" the drive with a tool, to
get past the screen: that loses the data for certain.
