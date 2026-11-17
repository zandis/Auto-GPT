# D-1125 The GPU driver reads the orchestrator as a caller its own table allows, and takes no filter it cannot check

- **Task:** lane H, card H-13 (the integrator's red of 2026-11-17 04:48 UTC on PR #639; the fault is H-1's, D2)
- **Date:** 2026-11-17
- **Status:** accepted

## Context

Launch P2 (run `box-20261117T041407Z-fae5c1f7`, master `fae5c1f7`) stopped at step `07g-gate` after 5 seconds:
`TB-GATE-REFUSED: GET /models refused the box's own service token (HTTP 403)`. No accuracy set ran.

H-1's fix of the gate step (D2) read `GET /models` with a service token, as the review asked, but from the mail
gateway's container. The orchestrator's table of callers (`services/orchestrator/route_callers.yaml`, T-713, D-464)
gives the group `models_read` to the console and to the operator only. The mail gateway starts and reads mailed jobs
and nothing else. So the read was refused, correctly, and the step stopped the run at once, also correctly.

Nothing caught it before the VM: the rehearsal's stand-in for the box took any service's token, and the unit test
asserted the container's name, not the route's rule.

The same review of the driver found a second free check that checked nothing: for a set whose protocols are sampled
from source files the VM fetches (sigir, trec2023), the local listing knew only the id's prefix and accepted any id
that carried it. The VM then stops on such a filter after the install is paid for.

## Decision

1. `d_gate_read` runs in the console's container. The console is the box service the table lets onto `GET /models`,
   and it holds its own token.
2. Every call the driver makes into the orchestrator is held against the orchestrator's own table by a test, with no
   VM: `tests/unit/test_h13_driver_callers.py` reads each `in_svc` snippet of `deploy/gcp/box-install-run.sh` and
   each read of `tools/public_accuracy/onbox.py`, and checks the service, the method and the path against the app's
   routes and `route_callers.yaml`. The gate's read is also made in process with each service's own token: the
   console is let in, the mail gateway gets the 403 of launch P2. A call written in a form the test does not read
   fails the test.
3. The rehearsal's stand-in asks the same table (`may_call`): a snippet run in a service the route refuses gets the
   refusal the box would give.
4. The other calls were checked the same way and stand: `d_study_ready` (the console, `GET /rulesets/{ruleset}`),
   `d_screen_start` and `d_screen_status` (the mail gateway, `POST /jobs` as a mailed SCREEN and `GET /jobs/{job_id}`
   of a mailed job), and the accuracy set's `wait` and `fetch` (the mail gateway, `GET /jobs/{job_id}`).
   `d_identity` and `d_candidates` run in the orchestrator's own container and make no HTTP call.
5. A filter (`--acc-protocols`) on a set whose ids are not known locally is refused before anything starts: a
   filter that cannot be checked for free is not accepted for free (the integrator's ruling of 04:48 UTC). A set of
   fixed protocols (tcga, jmed), or a sampled set whose source files are in the local cache, is checked exactly as
   before.

## Not here

A set that ends on its own budget is not picked up by a plain `--resume`. That is its own card, after the launch
(the integrator's answer of 04:48 UTC).

## Cost

Launch P2 ran 13 minutes before the stop, about US$0.7 at US$2.74 an hour (the integrator's figure).
