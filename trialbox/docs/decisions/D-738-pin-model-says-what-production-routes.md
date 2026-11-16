# D-738 `pin_model --resolve` says which build PRODUCTION routes each role to

- **Task:** PIN-RESOLVE, lane G's blocker 6 for R4 (routing v5 on an installed box)
- **PR:** this branch (`agent/PIN-RESOLVE-which-build-production-routes`)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-276 (a patient role never falls back), D-358 and T-012b (champion only through qualify), D-568
  (no build without a context)

## Context

Whether a pair is routed in PRODUCTION depends on the routing table (route, candidates, the no-fallback rule) and on
the registry with the site's pins (status, pin, expected weights, qualification, context). Nothing printed the result:
lane G could only find out by sending a call.

## Decision

1. `tools.pin_model.resolve_roles` walks the gateway's own path for every role of `models/routing.yaml` (not the
   `shadow:` and wildcard ones) and the data classes D1 and D3: `RoutingPolicy.candidates` with the box's topology,
   profile and cloud opt-in (`GatewayConfig.from_env`, environment PRODUCTION), the no-fallback rule of a patient role
   (only the route's declared first build), then `Registry.resolve` of each candidate in order, as the gateway does.
   Nothing is sent to a model.
2. `python -m tools.pin_model --resolve [--env-file deploy/.env] [--out <site pins>] [--require ROLE]` prints one
   line a role and class: the build, alias, endpoint, served name and route, or the registry's refusal codes.
   `--require` exits 1 unless that role routes on D3.
3. No new setting; it reads the gateway's own `TB_TOPOLOGY`, `TB_PROFILE`, `TB_CLOUD_OPT_IN` and `TB_ROUTING_PATH`.

## Test

`tests/unit/test_pin_model_resolve.py`: before, 5 failed; after, 5 passed, with the existing pin_model and champion
tests unchanged.
