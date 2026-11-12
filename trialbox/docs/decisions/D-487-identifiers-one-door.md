# D-487 One identifiers module in the orchestrator; a chart number becomes a pseudonym over HTTP only for a verified person with a right, audited and capped

- **Card:** T-719 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.2, TB-PLAN-06.1; wave T, safety core)
- **PR:** this branch (`agent/T-719-identifiers-one-door`); built on T-717's branch (PR #332) and so on #326, #317
  and #312: it shows their commits until they merge
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-438 (one reveal path in the console), D-464 (callers per route), D-483 (actor assertion v3)
- **Closes:** proposal TR-8, stage a, and finding F3 except the data-core sheet import (see "Not done"), of `docs/reviews/2026-11-12-architecture/trust.md` (see
  "Not done" for stages b and c)

## The problem

`POST /setup/pseudonym {"chart_no": ...}` and `POST /registry/{rs}` with `mrn` return the pseudonym of any chart
number to any admitted token, with no person and no audit. Chart numbers are short and often sequential: a loop
over the number space rebuilds pseudonym to chart number for the whole hospital without the pid map, its key, the
reveal cap or one audit event. The pseudonym is only as secret as these two routes. And the code that turns one
into the other is in eight places of the orchestrator.

## The decision

1. **One module.** `services/orchestrator/identifiers.py` is the only file of `services/orchestrator` and
   `services/console` that imports the hash (`pid_for_mrn`), opens the pid map (`PidMap`) or names `site_hmac.key`
   and `pid_map.key`. The registry (`candidates.py`), the screening, case and TWPAS scenarios, the sheet import and
   the two key loaders of `app.py` call it. `tests/unit/test_identifiers_door.py` is the import lint: a new use
   elsewhere fails, with an exception list that is empty and may only shrink.
2. **A pseudonym is given back for a chart number only to a verified person.** `identifiers.admit` is called by the
   two routes before they hash:
   - the person is the v3 claim (D-483) that `report_actor` verified for exactly this request and body; a call
     with none, whatever its service token, is refused (403, `actor.refused`, "a chart number needs a verified
     person");
   - the claim's action is one of two matrix rows and the matrix allows it to the signed role: `optout.keep` (the
     opt-out register, `POST /setup/pseudonym`) or `request.prepare` (a registry row typed by chart number, for
     the route's study only);
   - a cap per signed name and rolling hour, counted in the orchestrator's store as the reveal cap is
     (`orch.id_limits`, kind `to_pid`). The setting is `TB_TO_PID_MAX_PER_HOUR`; unset, it is the value of
     `TB_REVEAL_MAX_PER_HOUR` (the cap of the opposite direction: both walk the same number space), so no new
     number is fixed here. At the cap: 429 and `actor.refused` with reason `rate limit`;
   - one audit event `screen.to_pid` per answer: the person, the role, the action, the route and the pseudonym.
     The chart number is never written.
3. **The console signs its three calls.** The opt-out register (`team.py`) and the registry form (`app.py`,
   `Backend.registry_update(..., sign)`) sign as the signed-in person through the one minting place
   (`console.actor`). The third caller has no person: a job page asks whether a running case's subject is on the
   opt-out register, for any reader of the job, who never sees the pseudonym. It signs as the principal
   `service:console-optout-check` (a row of `route_actors.yaml`, action `optout.keep`, admitted on
   `POST /setup/pseudonym` only), under the same cap and with the same event, and the console keeps the answer
   per job so a page refresh costs nothing.

## What it does not do

- It is not a defence against a taken-over console: the console holds the key that signs people (D-485). It closes
  the route for every other holder of an admitted token, and it makes every lookup attributable and bounded.
- `services/sitesetup` (another package) still hashes with the key the orchestrator hands it. Its callers with a
  chart number from HTTP are four routes, and all four are behind the door: `POST /setup/pseudonym`
  (`optout.keep`; also the console's opt-out check, the one service principal) and, since the adversarial review,
  `POST /setup/{ws}/charts`, `POST /setup/{ws}/sheets` and `POST /setup/{ws}/sheets/{iid}/roles` (`site.setup`).
  The first version of this record said the first route was the only one; a pasted chart and an uploaded sheet
  hash chart numbers too, and the set-up read routes give the pseudonyms back, so a bare console token could walk
  the number space there (the review's H1, confirmed on the real box).
- **One route, one purpose** (the review's M1): each route tells the door which matrix row it admits. The opt-out
  lookup takes `optout.keep` only, a registry row `request.prepare` only and for that row's study, site set-up
  `site.setup` only; a claim for a study is refused on a route of the whole box; a service principal is admitted
  only on the opt-out lookup.
- A chart or a sheet given to site set-up writes one `screen.to_pid` event that names the input, not a list of
  pseudonyms (a sheet holds many).

## Not done

- **TR-8 stage b:** workbooks stored with pseudonyms and filled with chart numbers at download.
- **TR-8 stage c:** the identifiers module as its own container and database role (`pidmap` readable by it alone).
- `POST /studies/{rs}/import/sheet` with a chart-number column hashes a whole sheet with no person required
  (group `datacore`, stage `report`), and `GET /studies/{rs}/data` reads the records back by pseudonym: with one
  more call it is the same oracle as the set-up routes were. **Open**: it requires its person when the data-core
  router moves to `refuse` (T-715 stage b, plan wave 2); F3 is not fully closed until then.
- The lint (`tests/unit/test_identifiers_door.py`) reads `services/orchestrator` and `services/console`; a new
  route that reaches the key through another package (`services/sitesetup`) or through the module's own helpers
  is not seen by it. Nothing enumerates which routes must call `admit`.
- A failed lookup (a blank chart number) uses a unit of the cap; the cap is per signed name with no total per
  service; the console's opt-out check is one bucket for the whole console and its event names neither the job
  nor the reader.
- On a box with one shared token and no registry, every holder of the token can derive the signing key (D-485),
  so the door stops nobody there.
- A console of the release before this one does not sign these calls: its opt-out desk, registry row by chart
  number and site set-up uploads are refused (403) until both are updated; `trialbox update` replaces both.
