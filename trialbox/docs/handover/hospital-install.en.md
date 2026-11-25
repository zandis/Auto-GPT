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

## How much disk the install takes

- The stick holds two packs: the software and the models. The first install reads both; an update brings the
  software pack alone.
- Nothing on the stick is copied to the disk first: each part is checked on the stick, then loaded. Before it
  loads, the screen prints three sizes: the box after the install, the most the install takes while it loads (never
  more than the box after the install and a tenth of it again), and what the stick holds.
- The release of 23 November 2026 filled 60.7 GB of the stick. The 500 GB free asked above also leaves room for the
  data the box gathers.

## Hospital IT: from the stick to the sign-in

1. Plug the stick into the machine. Sign in as the administrator and open a terminal.
2. Type the line printed on the delivery sheet, exactly as printed. It looks like this:
   ```
   sudo install -m 0700 /media/<user>/TRIALBOX/install /root/trialbox-install && sudo sha256sum /root/trialbox-install | cut -c1-24 | sed 's/..../& /g' && read -r -p 'Same as the sheet? Type yes: ' a && [ "$a" = yes ] && sudo bash /root/trialbox-install /media/<user>/TRIALBOX
   ```
3. The screen shows a code in six groups of four. Compare it with the installer's code on the sheet. If they are
   the same, type yes. If not, press Enter and call the vendor.
4. The screen shows `Vendor key fingerprint:`. Compare it with the vendor key's code on the sheet. If they are the
   same, type yes. If not, type no and call the vendor.
5. The screen shows `this machine`: the graphics card, the memory, the free disk. Then it asks four things: the
   language, the time zone (press Enter when it is right), the first administrator's mail address and full name, and,
   only where the machine has no security chip, a passphrase of at least 12 characters, typed twice and not shown.
   Keep it in a safe place: the box asks for it after every restart.
6. Wait. Loading takes 10 to 20 minutes. Nothing more is asked. The screen lists what has a default now and can be
   given later.
7. The screen shows the first password and the enrolment code of the administrator, once, then `TrialBox is ready:`
   and the address. Hand all three to the administrator in person.

## The administrator: the first sign-in

1. On a computer on the hospital's network, open the address in a browser. The browser warns until hospital IT has
   made the computers trust the box; you can sign in all the same.
2. Sign in as admin with the first password, and choose your own.
3. Add the box to your authenticator app with the enrolment code. It works for 24 hours.
4. On the administration page, open "Information still needed".
5. Fill in what you know. Each item says why it is needed and who usually knows it. The box checks it, and the item
   leaves the list within a minute or two.
6. Leave the rest for later. Only the step that needs an item waits for it. A demonstration box never needs real
   patient data: it shows a sample hospital.

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
| `the questions were not answered (above): nothing was changed` | Type the sheet's line again, and answer the four questions |
| `the install stopped` | Call the vendor. Leave the machine as it is |
| `the code was voided (five wrong codes): a new one` | Use the new code the screen shows |
| `the set-up is not finished` | Call the vendor. Leave the machine as it is |
| Any other line that stops the install | Call the vendor. Leave the machine as it is |
