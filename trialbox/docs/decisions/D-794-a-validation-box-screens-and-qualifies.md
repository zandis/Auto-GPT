# D-794 A VALIDATION box screens on its own models and qualifies the pair it runs

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

1. **In VALIDATION a D3 model call goes to the box's own model servers only.** The gateway
   (`RoutingPolicy.candidates`) does not apply the ceiling to a VALIDATION D3 call and keeps only perimeter
   endpoints; a route with none refuses. The patient route lists VALIDATION. The ceiling itself is unchanged: what a
   VALIDATION box may hold, and doctor, testbench and eval, stay at D2; D4 stays refused. A VALIDATION box is for
   public or synthetic data (D-127); the D3 label is what the screen puts on any note, not a widening of what the
   box may receive.
2. **VALIDATION routes a candidate, qualified, shadow or champion build** (retired and suspended never).
   PRODUCTION is unchanged: champion only, and champion only with a record for exactly the pinned weights.
3. **qualify's calls have a route in VALIDATION** (`qualify`: role judge, class D0, the pair on the box). A record
   qualifies PRODUCTION when it passed with real weights (`qualifies_production`), whatever environment it was made
   in. The path on a box: install it VALIDATION (D-793), `trialbox eval qualify --box` (D-734, D-737),
   `pin_model --promote` each build with the record, set `TB_ENV=PRODUCTION`.
4. PRODUCTION still has no D0 route for the judge: qualify never runs against a PRODUCTION gateway.

## Test

`tests/unit/test_validation_box_routes.py` (lane G's probes): before, 5 failed; after, 11 passed. The 48 test files
that read the routing table, the registry or VALIDATION: 954 passed, 2 skipped.
