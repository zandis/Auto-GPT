# D-823 A VALIDATION box screens on its own models and qualifies the pair it runs

- **Task:** VALIDATION-ROUTES, the owner's blockers 1 and 2 of 2026-11-15 (lane G's first real-model accuracy run;
  "fixed" means lane G's `python -m tools.box_run validation-check` passes)
- **PR:** this branch (`agent/VALIDATION-ROUTES-a-validation-box-screens-and-qualifies`)
- **Date:** 2026-11-15
- **Status:** accepted (the owner's direction of 2026-11-15, relayed by the integrator; one adversarial review)
- **Builds on:** D-276 (a patient role never falls back), T-012b (champion only through qualify), D-313 (qualify),
  D-734 and D-737 (qualify on an installed box)

## Context

1. The screen's judge call is labelled D3 (`libs/tb_llm/client.py`); VALIDATION's ceiling is D2
   (`tb_common.policy.classes.ENV_CEILING`) and the patient route was PRODUCTION only: a VALIDATION box refused
   every screening call.
2. VALIDATION and PRODUCTION routed a judge or verifier only as champion (`registry._status_ok`); the pair ships as
   candidate and becomes champion only by `pin_model --promote` from a passing qualification record; qualify's
   calls are D0 and had no route in VALIDATION or PRODUCTION. No box could make the record, so no box could route
   the pair, PRODUCTION included.

## Decision

1. **In VALIDATION the screen's D3 calls go to the box's own model servers only.** For a patient role or its
   vectors, on topology A, the gateway (`RoutingPolicy.candidates`) does not apply the ceiling and keeps only
   perimeter endpoints; the patient route lists VALIDATION, and `phi_on_box` (the step rule for D3 on the box) lists
   VALIDATION. The box's model addresses are checked as in PRODUCTION (`perimeter_checked`, T-604): a gateway whose
   model URL resolves off the box does not start. Everything else keeps VALIDATION's D2 ceiling: front-desk
   conversation, protocol work, topology B and C, what a VALIDATION box may hold, doctor, testbench and eval; D4 stays
   refused. A VALIDATION box is for public or synthetic data (D-127); the D3 label is what the screen puts on any
   note, not a widening of what the box may receive.
2. **VALIDATION routes a candidate, qualified, shadow or champion build** (retired and suspended never; the pin and
   the expected weights are still required). PRODUCTION is unchanged: champion only, with a record for exactly the
   pinned weights.
3. **qualify's calls have a route in VALIDATION** (`qualify`, the last row: every role at D0 on topology A, to the
   box's model servers, after every row above has kept its own roles): its schema step sends every active prompt
   with that prompt's role. A record qualifies PRODUCTION when it passed with real weights (`qualifies_production`),
   whatever environment it was made in. The path on a box: install it VALIDATION (D-822), `trialbox eval qualify
   --box` (D-734, D-737), `pin_model --promote` each build with the record, set `TB_ENV=PRODUCTION`.
4. PRODUCTION still has no D0 route for the judge: qualify never runs against a PRODUCTION gateway.

## Adversarial review

One fresh read-only review. Fixed test-first: the screen's D3 call was still refused on a VALIDATION box, because
the gateway checks the study step before routing and `phi_on_box` was PRODUCTION only (FIX FIRST; now a test
through the gateway, which failed before with `step_unconfirmed`); qualify's schema step uses roles other than the
judge, which had no D0 route (FIX FIRST); the D3 exception covered every role, front-desk conversation included, and
topology B; the box's model addresses were not checked in VALIDATION. Two tests that encoded the old VALIDATION rule
moved with it: the perimeter test now expects a VALIDATION gateway with an off-box model URL to refuse to start (TEST
still starts), and the doctor's judge-route case for `step_unconfirmed` is VALIDATION on topology B. Left as notes: in
VALIDATION the first pinned, routable build of an alias in registry order answers (the shipped order puts the
profile builds first); a candidate without `context_length` has no prompt-length guard in VALIDATION (a server 400,
not a leak).

## Test

`tests/unit/test_validation_box_routes.py` (lane G's probes and the review's): before, 5 failed; after, 16 passed.
`tests/unit/test_validation_box_screens.py` (through the gateway of a VALIDATION box): failed before with
`step_unconfirmed`, passes after. The test files that read the routing table, the registry or VALIDATION pass.
