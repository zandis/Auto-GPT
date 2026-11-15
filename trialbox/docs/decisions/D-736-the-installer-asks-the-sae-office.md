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

1. `deploy/install.sh` asks for the mailbox next to the TLS name, at a terminal and without `--yes`; a value already
   in `deploy/.env` is kept.
2. The answer must be one mail address; anything else stops the install, in any environment.
3. A PRODUCTION install stops without one and says why in a plain line. A box installed by `box-install.sh`
   (`TB_BOX=1`) starts on provisional answers before the owner gives any, so there it is a warning line (R2 stays
   unblocked); the first-run page asking it is lane C2's and W's to add. Other environments say that nobody is
   mailed and go on.
4. No new setting (`TB_SAE_OFFICE_MAILBOX` is declared); no change to what the console sends.

## Test

`tests/unit/test_install_asks_the_sae_office.py` runs the installer's block as it stands: before, 13 failed; after,
13 passed.
