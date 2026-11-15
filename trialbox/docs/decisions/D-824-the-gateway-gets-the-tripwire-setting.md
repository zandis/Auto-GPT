# D-824 The gateway's container gets the PHI tripwire setting, on by default

- **Task:** COMPOSE-TRIPWIRE, the owner's blocker 4 of 2026-11-15, with lane A2's #654 (the tripwire guards the
  routes that leave the box; its setting `TB_GATEWAY_PHI_TRIPWIRE`)
- **PR:** this branch (`agent/COMPOSE-TRIPWIRE-the-gateway-gets-its-setting`), stacked on #654
- **Date:** 2026-11-15
- **Status:** accepted

## Decision

`deploy/docker-compose.yml` passes `TB_GATEWAY_PHI_TRIPWIRE: "${TB_GATEWAY_PHI_TRIPWIRE:-on}"` to the gateway and to
no other service: a site turns it off in `deploy/.env` on purpose; unset, it is on (fails safe).

## Test

`tests/unit/test_compose_phi_tripwire.py`: before, 1 failed; after, 2 passed.
