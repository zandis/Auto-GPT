# D-803 The setup router refuses a call without a verified person; no orchestrator route is in stage `report` (T-715g)

- **Task:** T-715, the remaining routers in stage `report`; the code-complete sprint, item 5, part 2 · **Date:** 2026-11-15
- **The routes:** the setup router's 13 changing routes are in stage `refuse` (`route_actors.yaml`).
  - The workspace's sheets, charts, facts, codes, checks and people, publishing and the practice space ask for `site.setup`. A fact, a chart or a person to resolve also needs the signed role to see patient data (`phi.view`), as the console's page asks; the administrator holds `site.setup` but not that.
  - A pseudonym by chart number asks for `optout.keep` (the opt-out desk, and the console's opt-out check timer).
  - The remote help switch asks for the administrator's box network row, `ops.network`: it opens the box to the vendor's connection. A row of its own would change the generated admin guide, and the guides are frozen.
  - No request model takes a `by`. The remote switch's approval field is now `hospital_approval`: who at the hospital approved, never the caller.
  - `POST /assist` stores nothing; it does append the model call's `llm.call` audit event (hashes, no patient data). It is in its own group, callable by the console service only, in stage `no_person`.
- **The console:** every set-up change goes through `signed_post` (`site.setup`), and the remote switch is signed as `ops.network` (its page still asks `is_admin`). The opt-out desk and the opt-out check already signed.
- **The stage `report`:** no route is left in it. It is kept in `orchestrator.actor` for a router that moves there first, and its tests hold it on routes of their own. The `v2` routers wait on T-716's grant work.
- **Held by:** `tests/unit/test_actor_routes.py` (the refuse walk; the report list empty), `tests/unit/test_orchestrator_callers.py`, and the new `phi.view` test in `tests/console/test_site_setup_pages.py`. Moved with the rule, as the adversarial review found: the site set-up fixture (no report stage), `test_identifiers_box` (the stage's reasons come before the door's; no typed person) and `test_din3_known_patient` (the desk's signed call).
