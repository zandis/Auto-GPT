# D-865 The clinical conflicts go over the orchestrator's routes (NEW-ARCH-3, slice 2)

- **Task:** NEW-ARCH-3 (D-761, the deep review's ARCH-005), the code-complete sprint's item 6, slice 2. The console's `/data/conflicts` page (T-201, D-426) opened the OMOP store of record itself to list the clinical conflicts (`tb_conflict`) and to settle one. · **Date:** 2026-11-16
- **Decision:** the orchestrator holds the conflicts behind two routes (`orchestrator.conflicts_api`, group `omop_conflicts`, stage `refuse`; the console is its caller):
  - `GET /omop/conflicts` (`?all=1`: the trail) returns each conflict with the patient's pseudonym and the open count per item. It is a patient read (`tb_common.patient_reads`) of the whole site, for the matrix's `conflicts.resolve`, the right that has always guarded the page; the console signs it.
  - `POST /omop/conflicts/{cid}/resolve` is the steward's choice with a reason, by the verified person (`require_actor("conflicts.resolve")`). It answers 404, 409 (settled), and 400 (`choice`, `reason`), and the console maps them to its old redirects.
  - The console keeps writing `console.conflict_resolved`, and a small view type of its own replaces the OMOP `Conflict`.
- **Why:** with slice 3 (D-864) the console opens no domain store: the `OWED` list of `tests/unit/test_the_console_opens_no_domain_store.py` is empty. Moved tests:
  - the refuse-stage pin in `tests/unit/test_actor_routes.py` names the new group;
  - `tests/unit/test_patient_reads_check_person_and_study.py` lists this route as the one whole-site patient read outside a set-up workspace, and checks each read with its own action and a role holding it (the steward here);
  - the generated role x route table moves one cell (`GET /data/conflicts`, steward `Y` to `U`), since the walk's box has no orchestrator. No new matrix row: the guides are frozen.
- **Held by:** `tests/console/test_conflicts_page.py`, now run against the orchestrator's routes in process through a client that signs nothing itself, so the console's own signing is what is checked. The refuse-route walk of `test_actor_routes` covers an unsigned call and a role without the right.
- **Left:** the console's database role still lists the `omop` and `sitesetup` schemas (`deploy/docker/db-init/30-service-roles.sh`); taking them off is the role card's step, not this one.
