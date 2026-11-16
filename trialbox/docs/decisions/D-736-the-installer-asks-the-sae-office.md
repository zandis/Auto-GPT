# D-736 The installer asks for the trial office's mailbox; a PRODUCTION install stops without it

- **Task:** SAE-MAILBOX (review LIFE-007), lane D's small card as agreed with the integrator
- **PR:** this branch (`agent/SAE-MAILBOX-the-installer-asks-the-office`)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-277 (the SAE clock and register; the office copy), D-382 (T-632, site inputs at install)

## Context

When a serious adverse event is entered, the console mails the trial office at `TB_SAE_OFFICE_MAILBOX`, without the
AE term (`services/console/sae_pages.py`). The setting defaulted to empty and nothing asked for it (LIFE-007): an SAE
typed on Friday evening, its 24-hour sponsor report due Saturday, and the first mail on Monday.

## Decision

1. `deploy/install.sh` asks for the mailbox next to the TLS name, at a terminal and without `--yes`. The answers file
   gives it as `sae_office_mailbox` (the settings wizard asks it and writes `TB_SAE_OFFICE_MAILBOX`); a value already
   in `deploy/.env`, or exported for the run, is kept. Surrounding quotes and spaces are read as compose reads them,
   and the value is written plain.
2. The answer must be one plain mail address (`settings_wizard.MAILBOX_RE`, the same text in `install.sh`): no
   quote first, no `$`, backtick, backslash, space or comma that `deploy/.env` or compose would read otherwise, every
   domain label non-empty. Anything else stops the install, in any environment.
3. A fresh PRODUCTION install stops without one and says why in a plain line, naming `deploy/.env` and the answers
   file. A re-run on a site that already has its settings (an update that starts a stopped box) never stops a site
   for it; a box installed by `box-install.sh` (`TB_BOX=1`) starts on provisional answers. Both warn; adding the
   question to the first-run page is lane C2's and W's. Other environments say that nobody is mailed and go on.
4. `doctor` gains `sae_mailbox`: WARN on a PRODUCTION box without one plain address, so a box's last check shows it.
5. No new setting (`TB_SAE_OFFICE_MAILBOX` is declared); no change to what the console sends.

## Adversarial review

One fresh read-only review. Fixed test-first: the `--answers --yes` PRODUCTION path had no way to give the mailbox and
a re-run on an existing site would stop it (FIX FIRST); a quoted value was refused; the pattern let `$`, backtick,
backslash, a leading quote and empty domain labels through; a box never got it and nothing said so after install.

## Test

`tests/unit/test_install_asks_the_sae_office.py` runs the installer's block as it stands, the wizard and the doctor
check: before, 13 failed (and 16 more after the review); after, 29 passed.
