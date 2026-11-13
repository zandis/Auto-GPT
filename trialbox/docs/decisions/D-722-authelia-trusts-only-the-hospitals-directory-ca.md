# D-722 Authelia trusts only the hospital's directory CA

- **Task:** AUTHELIA-CA (the owner's condition of 2026-11-13 on the entry for CVE-2026-111943, D-574)
- **PR:** this branch (`agent/AUTHELIA-CA-only-the-hospitals-directory-ca`), stacked on #381 (OPS-004b)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-574 (the login front against the gates), D-192 (the hospital account through Authelia)

## Context

Authelia's one outbound connection on a box is LDAPS to the hospital's directory. Its client verifies the
directory's certificate against the image's 121 public roots. CVE-2026-111943 (intermediates that `crypto/x509`
should no longer trust) is therefore reachable, narrowly: from inside the hospital's network, with a certificate
under such an intermediate. The owner allowed one dated entry on the condition that the real fix is built now and
removes the entry.

## Decision

(written when the card is built)
