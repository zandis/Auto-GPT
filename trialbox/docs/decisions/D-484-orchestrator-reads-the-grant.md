# D-484 The orchestrator reads the break-glass grant and the delegation log itself and writes the use; `breakglass` is no longer a role

- **Card:** T-716 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.2, TB-PLAN-06.1; wave T, safety core)
- **PR:** this branch (`agent/T-716-orchestrator-reads-the-grant`); built on T-715's branch (PR #317), which is
  built on T-714's (PR #312): it shows their commits until they merge
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-280 / D-430 (break-glass: one rule, 60 minutes, each use recorded), D-273 (chart numbers only to a
  signed role and study), D-438 (one reveal path in the console), D-483 (actor assertion v3)
- **Closes:** finding F5 (a) and (c) and proposal TR-4 of `docs/reviews/2026-11-12-architecture/trust.md`

## The problem

The console checks a break-glass grant: a row, for this person, this patient or this job, open now. It then signs
the word `breakglass` as the person's role, and the orchestrator gives a chart number to that word. The
orchestrator never sees the grant: a caller that can sign (the console's token) gets every listed patient's chart
number with the word alone, and the grant's use counter, which the console writes before the call, stays at zero.
The same holds for an investigator's standing in a study: the console reads the delegation log, the orchestrator
is told the result.

## The decision

1. **The reveal is a v3 claim** (D-483). `POST /jobs/{job_id}/reveal` has `require_actor("id.reveal",
   study_in_handler=True, grant=True)`: the verified person, for this request and this body. Its group moves from
   stage `v2` to `refuse` in `route_actors.yaml`; the request model has no `by`. The route's path has no study, so
   the handler compares the claim's study with the job's (`study scope`).
2. **Under break-glass the orchestrator reads the grant** (`services/orchestrator/grants.py: verify_grant`). The
   claim carries the account's own role and the grant's id. The dependency lets a claim that names a grant pass
   only when the role may hold one (`breakglass.open`) and never by the action's own row; the handler then reads
   the row: it exists, is this person's, is open now (not ended, before its 60-minute end, by the orchestrator's
   clock), and covers this patient of this study (a patient grant) or this job (a job grant). Nothing in the
   claim's `grant` but the id is believed. A refusal is 403 and one `screen.reveal_refused` with the reason
   (`break-glass grant: no such grant`, `another person's grant`, `the grant is not open`, `the grant is for
   another patient`, `the grant is for another job`) and the grant id.
3. **The orchestrator writes the use** (`record_use`), when it gives the chart number: one row of
   `breakglass.uses` (what `reveal`, the patient, the job) and the grant's counter. A reveal that never passed a
   console page is on the steward's review list. The console no longer writes that row for a reveal (it finds
   the grant without using it, `Helpers.breakglass_find`); it still writes its audit event
   `console.breakglass_use` after the number was given, so the trail has every use. Page views under a grant are
   the console's own uses, as before.
4. **By the person's own rights the orchestrator reads the delegation log** (`log_standing`, `own_right`): the
   `id.reveal` row, and for a role whose screening task the log decides (the investigator), that task with the
   standing the log gives the person in this study today (the PI the log names, the ticked tasks). The standing
   in the claim is not what is asked here: an investigator the log does not name is refused (`delegation`)
   whatever the claim says.
5. **`breakglass` is not a role.** `orchestrator.app.id_authority` is the `id.reveal` row and nothing else; the
   console signs no such word (`console.reveal`); the whole-list export refuses it as any unknown role, and takes
   no grant at all. `authz.BREAK_GLASS_ROLE` remains only as the label of a twin read under a grant in the
   console's own audit detail (`console.twin_api`); nothing accepts it.
6. **The console signs through its one minting place.** `Backend.reveal(job_id, pid, sign, purpose, reason)`:
   the backend builds the request and asks `sign(method, path, body)`, which is `console.actor.assert_for` with
   the grant; under a grant `assert_for` asks the `breakglass.open` row instead of the action's.
7. **The database role.** `tb_orchestrator` joins the groups of the schemas `breakglass` and `team`
   (`30-service-roles.sh`, both copies), because the stores open through `tb_common.db` as a member of the
   schema's group. That is more than it needs (see below).
8. **The stand-in follows.** `FakeBackend.reveal` reads the console's claim with `actor_v3.verify` and decides
   with the orchestrator's own functions (`actor.check`, `grants.verify_grant`, `log_standing`, `own_right`,
   `record_use`), with the console's clock; the contract test holds it against the real route for every role,
   three studies and a named and an unnamed person.

9. **An updated box.** `install.sh` runs the role script on every run; `trialbox update` does not. So the
   delegation log is read only for a role whose right it decides (a coordinator's reveal opens neither store),
   and a store that cannot be read refuses, with the reason on the record (`the grant store cannot be read`,
   `the delegation log cannot be read`): nothing is given, and the fix is one command of the runbook.

## What it does not do

- **`trialbox update` does not run the role script.** On a box updated that way, reveals under a grant and by an
  investigator are refused until the script is run once (above). Making `update` run it is a change to the update
  path that only a box can prove; listed as a finding.

- **The orchestrator's role owns `breakglass` and `team`** until T-718 splits owner, writer and reader: it needs
  SELECT on `breakglass.grants` and `team.delegation` and INSERT on `breakglass.uses` (and the counter). Today it
  could write a grant or a log entry. The orchestrator is the party that gives the chart number and holds the pid
  map and its key, so this adds no way to a chart number that the role did not have; it does add a way to forge
  the record of a right. T-718 removes it.
- **Standing on the other routes** (APPROVE, the EDC signature): the orchestrator still asks the matrix with the
  signed standing there (D-483). `log_standing` is ready for them.
- **The whole-list export, notices, cancel, retry and jobs** stay on the older assertion.
- **Two clocks.** The grant is open by the orchestrator's clock; the console found it open by its own. On one box
  they are one clock.
- **The twin API** under a grant does not go through the orchestrator (the console reads the twin itself): its
  use is still the console's row.

## Consequences

- A chart number under break-glass needs a grant row for that person and that patient or job, read where the
  number is given. The console's token with the word `breakglass`, or with a grant's id for another patient,
  gets nothing.
- An investigator needs a delegation-log entry the orchestrator can read; tests that revealed as an investigator
  with no log now name the PI.
- The test that pinned the weakness (`test_d280_breakglass.py`: the bare role gets a chart number) is inverted.

## Dropped (D-311)

No security sign-off or owner review step.
