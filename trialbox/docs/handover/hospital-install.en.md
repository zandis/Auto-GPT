# TrialBox: install it at your hospital

**Reader:** hospital IT, then the box owner.

This page is the whole install. There is one line to type. The box does the rest, and asks only what it cannot
find out itself. If the screen and this page differ, the screen is right: tell the vendor.

## What you need before you start

- The machine, prepared by the vendor, on power and on the hospital's network.
- The vendor's USB stick.
- The delivery sheet, on paper. It came apart from the stick.
- An administrator's login on the machine.
- 500 GB free on the machine's disk.
- The box owner, for the second part. The owner is the person who will look after the box and its data.

## Hospital IT: from the stick to the code

1. Plug the stick into the machine. Sign in as the administrator and open a terminal.
2. Type the line printed on the delivery sheet, exactly as printed. It looks like this:
   ```
   sudo install -m 0700 /media/<user>/TRIALBOX/install /root/trialbox-install && sudo sha256sum /root/trialbox-install | cut -c1-24 | sed 's/..../& /g' && read -r -p 'Same as the sheet? Type yes: ' a && [ "$a" = yes ] && sudo bash /root/trialbox-install /media/<user>/TRIALBOX
   ```
3. The screen shows a code in six groups of four. Compare it with the installer's code on the sheet. If they are
   the same, type yes. If not, press Enter and call the vendor.
4. The screen shows `Vendor key fingerprint:`. Compare it with the vendor key's code on the sheet. If they are the
   same, type yes. If not, type no and call the vendor.
5. The screen shows the machine's graphics card, memory and free disk, and asks
   `Is this the machine to install TrialBox on? [Y/n]`. If it is, press Enter.
6. Wait. Loading takes 10 to 20 minutes. Nothing is asked.
7. The screen shows `TrialBox set-up:` with an address, and `One-time code:`. Give both to the box owner.

## The box owner: the set-up page

1. On a computer on the hospital's network, open the address in a browser.
2. Type the code from the box's screen.
3. Answer the questions on the page. A demonstration box never needs real patient data.
4. If the page asks for a passphrase, the machine has no security chip. Choose one of at least 12 characters. Keep
   it in a safe place: the box asks for it after every restart. Type it only on this page, never in the terminal.
5. Press "Make my accounts and finish". Wait a few minutes.
6. The box's screen shows `TrialBox is ready:` and the address. Sign in with the account you just made.

## When the screen stops

Each line below is what the screen says, then what to do. "Nothing was changed" means the machine is as it was.

| The screen says | What to do |
| --- | --- |
| `run it as the administrator` | Sign in as the administrator and type the sheet's line again |
| `the fingerprint was not confirmed: stopped. Nothing was changed.` | Call the vendor |
| `the vendor key on the stick is not the key this installer was made for` | Call the vendor |
| `the installer on the stick is not signed by this key` | Call the vendor |
| `the stick's name has a space or a sign the installer cannot use` | Rename the stick TRIALBOX, then type the sheet's line again |
| `the stick must hold exactly one TrialBox release` | Call the vendor |
| `no answer: stopped. Nothing was changed.` | Type the sheet's line again, and answer yes or no |
| `the bundle's signature does not check with the vendor key` | Call the vendor |
| `Docker is missing on this machine` | The machine was not prepared. Call the vendor |
| `stopped: nothing was changed` | You answered n to the machine question. Type the sheet's line again on the right machine |
| `the install stopped` | Call the vendor. Leave the machine as it is |
| `the code was voided (five wrong codes): a new one` | Use the new code the screen shows |
| `the set-up is not finished` | Call the vendor. Leave the machine as it is |
| Any other line that stops the install | Call the vendor. Leave the machine as it is |
