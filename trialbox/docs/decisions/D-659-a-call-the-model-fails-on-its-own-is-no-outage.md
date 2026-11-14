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

A refusal in `CALL_FAULTS` that follows an answer of the same model (the client's label) to another call since this
call's previous fault is a **strike**: the model works, this call does not. A strike is waited out without charging
the job's allowance and without opening an outage. Six strikes in a row (`CALL_STRIKES`, about 30 s at the poll)
raise the refusal as it is, exactly as with no allowance, so the caller answers that one call as it always answered a
model fault (the pair is `model_down`, unknown).

- `CALL_FAULTS` are the faults a request can provoke itself: `upstream_down` (a 5xx) and the callers' `unreachable`
  (a connection it kills). `model_busy`, `model_asleep` and `model_unavailable` are load or state and keep waiting
  while others are answered (D-445).
- A fault with no answer since the call's previous fault is an outage, as before, and ends a run of strikes: an
  answer before an outage never turns the outage's refusals into strikes.
- Another model's answers do not count: the verifier answering says nothing about the judge's model.
- The breaker in `orchestrator.jobs` is not tripped by a call given up this way (it releases while the job waits).

The adversarial review broke the first version: its raise left the label's outage open (the wait was charged later
and a blip an hour on stopped the job), it counted strikes from the call's first fault (a healthy call was given up
15 s into a real outage), and it missed `unreachable`. All three are fixed and tested. Its estimate for a flapping
restart (a share p of calls refused for a while after an outage): about p^7 of the calls in that window are given up
with six strikes, each answered unknown, never a wrong verdict.

## Test

`tests/unit/test_outage_poisoned_call.py`: a poisoned call is raised after six strikes and charges nothing, also
beside calls that are answered (no endless loop); a given-up call leaves no outage open; answers before a real outage
do not give up a healthy call; a call that kills its connection is given up too; a real outage still waits and
resumes; a load refusal still waits; another model's answers do not count. `tests/unit/test_t689_outage_restart.py` passes unchanged (three runs).
