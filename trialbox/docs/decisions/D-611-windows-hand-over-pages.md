# D-611 The Windows hand-over pages: a checklist in the box form, and the owner's pages

- **Task:** NEW-WIN-9, the documents (`docs/plan/33-plan-v7.md` section 2.3: "the two handover documents rewritten
  to the box form; the owner's handbook (T-735) written for Windows"; lane W; wave 3)
- **PR:** this branch (`agent/NEW-WIN-9-handbook`)
- **Date:** 2026-11-13
- **Status:** accepted as written before the first run on Windows. Every page says so; P-0 corrects them
- **Owner decisions:** OD-13 (the audience is the box owner and the trial teams, not hospital IT)
- **Builds on:** D-600 to D-610 (what the installer and the checks do), D-605 and D-609 (the media and its
  document, rewritten there), D-607 (the desktop-use rule)

## Context

`WINDOWS-INSTALL-CHECKLIST.md` was written for an engineer who does every step by hand: install WSL, import
Ubuntu, edit `wsl.conf`, register the task, set BitLocker with `manage-bde`. Since D-600 the installer does those
steps, and since D-603 to D-608 it also does BitLocker, the update window, the firewall rule and the drive record.
The old sheet said so in a note and kept the hand steps "as the fallback"; it also still told the reader to set
"TPM and PIN" and to put Windows Update on "download and notify", which the box form no longer does. The owner
had no page of their own for the Windows workstation: the RUNBOOK is written for IT and for Linux.

## Decision

1. **The checklist is rewritten to the box form.** It lists what a person brings (the right Windows, the card
   and its Windows driver, a checked media, the place the recovery keys will be kept), the one thing they start
   (`Install-TrialBox.cmd`) with what it does in order, the few options and when each is needed, what is done with
   hospital IT (the data connection, the backup key), the two checks to run and the proof that the box comes back
   with nobody there, and three things never to do. The hand steps are gone: a fallback nobody rehearsed is not
   one. Its reader is named at the top (the owner, or an engineer beside them).
2. **The owner's pages** are `docs/handover/windows-owner.{en,ja,zh-TW}.md`: the day you set it up (six steps),
   a normal day (five lines), when something is wrong (a table of what you see and what to do), and four things
   never to do. No command line except the file to double-click and the log to send. They are the Windows part
   of the owner's handbook; lane D's T-735 (the handbook as a whole, IT's one page) can take them in as they are.
3. **The media carries the pages** under `docs/`: the owner's, the desktop user's, the checklist, the backup
   page and the rehearsal sheet (`tools/windows_media.py`, `HANDOVER_DOCS`).
4. **Tests hold the pages to the code**, not to Windows: the three languages have the same parts and pass the
   wording rules; the update window the owner reads is the installer's default; every option, doctor line and
   file the checklist names exists; nothing tells a reader to remove the box.

**Reuse check.** Nothing to reuse: the pages describe this installer. The RUNBOOK's own sections stay lane D's.

## What is proven here, and what is not

Proven here: what point 4 says, and that a media built by the tool holds the pages. Not proven: that the pages
match what a Windows PC shows. They were written from the installer's code and messages before any run on
Windows; each says so, and the rehearsal (P-0) is where the owner's set-up page is first followed by a person,
which is T-735's own acceptance ("an owner can follow the set-up page in the rehearsal").

## Consequences

- `docs/runbook/01-install-a-new-site.md` (lane D's) points to the checklist; the pointer still holds.
- When P-0 has run, the pages are corrected from its Record column in one card.
