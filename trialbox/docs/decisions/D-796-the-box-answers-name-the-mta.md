# D-796 A box's answers can name the hospital MTA; left empty, mail stays closed and doctor says so

- **Task:** BOX-MAIL-ID, the owner's blocker 9 of 2026-11-15 (a box made by the wizard has no mail identity, so
  every mailed FEAS or SCREEN is refused); the integrator accepted lane D's proposal on #639
- **PR:** this branch (`agent/BOX-MAIL-ID-the-box-answers-name-the-mta`), stacked on BOX-VALIDATION (D-793)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-369 (SEC-11: the mail gateway trusts sender results only from the MTA it names; empty: fails closed)

## Decision

1. The owner's answers take `mta_authserv_id`, optional: one host name (labels of letters, digits and inner hyphens,
   at least one dot), lower-cased; anything else is a problem of the form. No default is ever guessed: a value
   nobody checked would weaken sender checking.
2. The box plan hands it to the settings wizard, which writes `TB_MAIL_AUTHSERV_ID` (as for the IT form).
3. Left empty, mail stays closed, and `doctor` `mail_auth` WARNs on a VALIDATION or PRODUCTION box, saying that every
   mailed FEAS or SCREEN is refused until it is set.
4. The first-run page does not ask it yet (lanes C2 and W); an answers file gives it.

## Test

`tests/unit/test_box_mail_identity.py`: before, 11 failed; after, 11 passed.
