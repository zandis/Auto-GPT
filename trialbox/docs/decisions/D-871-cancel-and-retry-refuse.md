# D-871 Cancel and retry take the verified administrator (T-715 refuse mode, part 1)

- **Task:** T-715 refuse mode, a go-live item of lane C2's backlog. The `report` stage of `route_actors.yaml` is empty; five route groups still verified the older v2 assertion (a name, a role, a signature over them, and a `by` fallback). This card moves two of them. · **Date:** 2026-11-16
- **Decision:**
  - `POST /jobs/{job_id}/retry` (group `job_retry_scheduled`) takes a verified v3 person for `job.retry_scheduled`, its own row (D-474).
  - `POST /jobs/{job_id}/cancel` (group `job_cancel`) takes one for `request.prepare`, and the orchestrator also asks the row the console's jobs page asks (`need_admin`: `ops.view`, today the administrator's). Before this, any signed name could cancel any job on this route; a coordinator is now refused here. A requester's own cancel is the CANCEL command (`command.CANCEL`, a coordinator's row too), which goes through `POST /jobs` and `scenarios/admin.py`, unchanged. There is no row of its own because the guides are frozen.
  - Both groups move from `v2` to `refuse`. The `by` query parameter of cancel is gone.
  - The console's jobs page signs each call as the signed-in administrator for exactly that request, and the backend (and the demo box's) sends that header.
- **Left (T-715 refuse mode, part 2 and on):**
  - `jobs_start` (`POST /jobs`): the console with a person, the mail gateway with none. The review of D-871 noted that a console account with no mailbox submits a command under the box's `admin_email`, which the CANCEL check then trusts as the requester; part 2 should sign the person instead;
  - `notices` (`POST /notices`): sent by people and by timers, which need service principals;
  - `edc`: lane E's service, with the grant checks of T-716.
- **The adversarial review: SOUND.** It asked that the check read the matrix (`ops.view`) rather than a role name, as done.
- **Held by:**
  - `tests/unit/test_admin_retry_scheduled.py`: its calls are now signed v3. A new cancel test shows a v2 name, an unsigned call with `by`, a coordinator and another action all refused, and the administrator served.
  - The refuse-groups pin of `test_actor_routes` moves.
