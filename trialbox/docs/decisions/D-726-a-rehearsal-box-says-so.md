# D-726 A rehearsal box says so

- **Task:** REHEARSAL (the Windows P-0 rehearsal, stage B: a signed bundle with placeholder models on a PC that is
  not a site box). The owner's yes, typed in lane D's session on 2026-11-13, on five conditions.
- **PR:** this branch (`agent/REHEARSAL-a-test-box-that-says-so`)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** D-176 (the box rehearsal's model stand-ins), D-633 (a PRODUCTION box takes only a release from a
  commit), D-127 (TB_ENV, PRODUCTION when unset)

## Context

Stage B needs the model stand-ins and an unmeasured card's trial boot on a box that is plainly not a site's. Today
both are switched on by environment settings (`TB_COMPOSE_OVERRIDE`, `TB_ACCEPT_UNMEASURED_GPU=1`) that a box of
any environment honours, and nothing on the box or in the bundle says "rehearsal".

## The owner's five conditions

1. One explicit installer argument (`--rehearsal`).
2. The box is TEST before anything loads; refused on a PRODUCTION or VALIDATION box, or a box with site data.
3. The stand-ins and the unmeasured card are honoured only on TEST.
4. Console and doctor say "rehearsal box".
5. A rehearsal bundle is marked, and a PRODUCTION box refuses it.

## Decision

(written when the card is built)
