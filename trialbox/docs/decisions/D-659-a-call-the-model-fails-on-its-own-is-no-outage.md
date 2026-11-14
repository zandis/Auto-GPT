# D-659 A call the model fails on its own is not an outage: it is given up, never charged to the job

- **Task:** the owner's order after the deep review of 2026-11-13 (`libs/tb_llm/outage.py:141`), lane A2
- **PR:** this branch (`agent/OUTAGE-poisoned-call-gives-up`), cut from master `d2d74f30` (train 14)
- **Date:** 2026-11-14
- **Status:** proposed (merges on a green train)
- **Builds on:** T-689 / D-456 (a batch call waits through a model outage within the job's allowance), D-445 (a busy
  model is load, not the call's fault)

## Context

`tb_llm.outage.wait_and_retry` sends a batch model call again after a wait for as long as the job's outage
allowance lasts (`TB_LLM_OUTAGE_WAIT_S`, 1,800 s). A call that always fails with `upstream_down` because of what it
sends (a 5xx this request provokes, while the same model answers every other call) was sent again and again:

- alone, it spent the job's whole allowance and stopped the job (`OutageExhausted`), losing a run of hours to one
  request;
- beside calls that are answered, each answer ended the outage, so the call was sent again without end.

Confirmed by running before the change: `tests/unit/test_outage_poisoned_call.py`, both cases fail (the second
reaches its guard of 50 sends).

## Decision

Once the same model (the client's label) has answered another call since this call first failed, the call's third
`upstream_down` counted from then is its own failure. `wait_and_retry` raises it as it is, exactly as with no
allowance, so the caller answers that one call as it always answered a model fault (the pair is `model_down`,
unknown). Nothing is charged to the job's allowance.

- Only `upstream_down` (`CALL_FAULTS`) can be the call's own fault. `model_busy`, `model_asleep` and
  `model_unavailable` are load or state and keep waiting while others are answered (D-445).
- Three strikes, not one (`CALL_STRIKES`): a model coming back from a restart can refuse a call a last time just
  after it answered another one (T-689's sixteen calls in flight).
- Another model's answers do not count: the verifier answering says nothing about the judge's model.
- With no call answered meanwhile it is an outage, as before.

## Test

`tests/unit/test_outage_poisoned_call.py`: a poisoned call is raised soon and charges nothing, also beside calls that
are answered (no endless loop); a real outage still waits and resumes; a load refusal still waits; another model's
answers do not count. `tests/unit/test_t689_outage_restart.py` passes unchanged (three runs).
