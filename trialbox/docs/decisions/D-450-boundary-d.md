# D-450 Boundary, part d: one SSRF guard, the scrubber on in every service, secrets out of the shared env file, the mTLS position

- **Task:** T-212d (`docs/plan/28-master-plan-v6.md` §6.2, "as TB-ASSESS-01" T-212)
- **PR:** this branch (`agent/T-212d-boundary-d`)
- **Date:** 2026-11-11
- **Status:** proposed (merges on green CI)
- **Closes:** OPS-057; PV-10 (the scrubber's chart-number rule); D-114 and D-138 "Not done" items (plan §6.2.9)
- **Builds on:** T-212b / D-437 (the model key file), T-212c / D-378 (a database role per service), T-604 / D-388
  (the perimeter check, `deploy/egress.py`), T-654 (secret and static scans in CI), T-608 / D-445 (the two model
  key copies must agree), D-128 / D-138 (one token per service), T-109b (signed actor assertions with a nonce)

## Decision

(written as the card is built)
