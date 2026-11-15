# D-790 The PHI tripwire guards the routes that leave the box

- **Task:** blocker 4 of lane G's first real-model accuracy run (the owner's ruling D-506, relayed by the integrator
  on #639, 2026-11-15)
- **PR:** see the REGISTRY row
- **Date:** 2026-11-15
- **Status:** reserved
- **Builds on:** D-142 (data that never leaves the box), the gateway's tripwire (LLM-15, PRIV-29)

## Decision

The gateway's PHI tripwire (step 4 of a call) guards only the candidates outside the box. On the box means a
`perimeter` endpoint on topology A: on topology B the perimeter is the tenant's serving router, which is not on the
box (D-142, `RoutingPolicy.perimeter_checked`), and on topology C nothing is. On a D0-D2 call whose text it hits, the
candidates outside the box are dropped and the call goes on to an on-box model; it is refused (`phi_tripwire`) only
when no on-box candidate is left. `TB_GATEWAY_PHI_TRIPWIRE` (declared, default `on`) turns it off with `off` (`0`,
`false`, `no`); any value other than these and `on` keeps it on and is logged. The ruling allows `off` in every
environment; a gateway that starts with it off logs a warning naming its environment, and every call's audit line
says `off`. The audit line's `guard` says what happened: `hit:<kinds>:on_box` (answered on the box), `hit:<kinds>`
(refused), `clear`, or `off`.

Before, a hit refused every D0-D2 call whatever its route: 2 of 16 public protocols were refused at compile (a
sponsor compound code read as a passport number, a zh-Hant protocol as a name) though the call stayed on the box.

## Not changed

The compose file does not pass `TB_GATEWAY_PHI_TRIPWIRE` to the gateway container yet (lane D's file, asked on #639):
until it does, the deployed gateway keeps the default, on. No shipped route puts a build outside the box before an
on-box one, so the expected build after a hit is the route's first on-box build only in a defensive branch.

D3 and D4 calls still go to on-box models only (D-142); the tripwire does not apply to them. The locator's masking of
contact lines (T-606) stays: it is what lets a protocol through on a route that leaves the box.

## Test

`tests/unit/test_phi_tripwire_leaves_box.py`; `test_gateway.py`, `test_injection_hardening.py` and the testbench test
now check the refusal on a route that leaves the box, and the answer on the box.
