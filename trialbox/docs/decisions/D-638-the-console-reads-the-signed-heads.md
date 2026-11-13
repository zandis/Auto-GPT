# D-638 The console reads the signed heads: the anchor folders are mounted read-only

- **Task:** ANCHOR-MOUNT (lane C2's reading of D-562, through the integrator, 2026-11-13)
- **PR:** this branch (`agent/ANCHOR-MOUNT-the-console-reads-the-signed-heads`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-562 (the night signs the audit head into the anchor folders), D-394 (only the audit writer writes the audit volume)

## Context

The console's audit page verifies the chain against the signed heads of every anchor folder when
`TB_AUDIT_ANCHOR_TARGETS` is set. On an installed box it never is: the anchor folders are host paths the console
does not mount, so compose clears the name for the console (D-562). The page's Verify therefore checks the chain
against itself only; the signed heads are checked by the night and by `tools/audit_verify.py --heads`, not where the
auditor looks.

## Decision

(written when the card is built)
