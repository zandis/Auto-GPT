# D-456 What a batch model call does on a refusal or an outage: it waits; the job keeps what it has judged

- **Task:** T-689 (`docs/plan/28-master-plan-v6.md` §6.2.10; `docs/plan/31-master-plan-v6.1-addendum.md` §3.4, the
  night and capacity lane)
- **PR:** this branch (`agent/T-689-batch-refusal-outage`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Closes:** F-04, F-16 (both parts), F-28, F-31, G1-2 (the job's half: judged pairs are kept), G1-3 of
  `docs/reviews/2026-11-11-scale-timeouts.md`
- **Builds on:** D-389 (T-108d: job cancel and the SCREEN breaker), D-445 (T-608: one timeout budget, the gateway's
  refusals `model_busy`, `model_unavailable`, `model_asleep` with `Retry-After`), D-142 (the explicit pair budget),
  D-383 and D-403 (a job reads one pinned snapshot and holds it), D-465 (the erasure registry), OD-10 (no limit that
  is not derived or declared)
- **Read by:** T-698 (the gateway's queue and read limits for batch roles), T-724 (the replay key gains the
  generation)

## Context

A screening job at 50,000 patients is hours of model calls. Four things made it fragile (review of 2026-11-11):

- A model server that restarts answers nothing for seconds to minutes. The client raised at once, the note judge
  wrote `unknown` / `model_down` and went on at full speed; the gateway's breaker then refused the next calls in
  milliseconds. One 5 s outage in the scale gate lost 60 of 74 judge calls (F-04). Above a 10 % share the job of
  hours was thrown away at its end, below it the pairs went to review unjudged (G1-3). Five failures "in a row"
  failed the job although 16 calls in flight fail together on one blip (F-31).
- A restart of the orchestrator ran every interrupted job again from zero, with no count: an out-of-memory kill
  caused by a job became a loop (F-28, G1-2).
- The pair budget was a fixed 20,000 and a hidden 10,000,000-token budget stopped a job earlier, under the wrong
  name (F-16).

## Decision

1. **A model fault is its own error.** `tb_common.llm.LlmModelFault` (an `LlmError`) is raised when the model did not
   answer for a reason that is not the request: the gateway's refusals `model_busy`, `model_unavailable`,
   `model_asleep`, `upstream_failed` and `upstream_timeout`, a gateway or model endpoint that cannot be reached, and
   an HTTP 5xx from either. It carries the refusal code and the gateway's `Retry-After` (which
   `tb_llm.GatewayRefused` now reads). Everything else stays what it was: a schema violation, an answer from the
   wrong build, a prompt that does not fit, a content refusal.

2. **A batch model call waits on a model fault and is sent again** (`tb_llm.outage.wait_and_retry`). It sleeps the
   gateway's `Retry-After`, else 5 s (the gateway's own value for a busy model), and sends the same call again. The
   wait is bounded **per job, not per call**: `TB_LLM_OUTAGE_WAIT_S` (default 1,800 s) is the time one job may spend
   in outages in total, over all its calls and both models (`tb_llm.outage.OutageBudget`). The reason for the
   default: a model server that restarts reloads its weights in minutes, and the one-card layout swaps two models;
   past half an hour a person is needed. `0` restores the old behaviour (no wait). When the allowance is used up the
   job fails at once with a message that says how long it waited and for which model; it never goes on to write
   `model_down` for the rest. Two callers use it, which are all the batch judge paths there are:
   - `orchestrator.jobs.GuardedLlm`, every queued job type's model clients (the fast lane has no model call). It
     reads the cancel flag before each try; the allowance used up is `ModelOutage`, a `StepFailed`. Each outage is
     one audit event when it ends (`llm.outage`: which model, the refusal code, seconds waited, resumed or gave up;
     no patient data).
   - `matching.cascade.judge.GatewayJudge`, the cascade's own judge on `tb_llm` (the tools and the scale gate): one
     allowance per judge, that is per run; used up, the run stops with `OutageExhausted`.
   An interactive role never waits: a person is there, and `model_busy` is its answer (D-445).

3. **The breaker counts what is left, and no blip opens it.** A model fault never counts in the SCREEN breaker of
   D-389. The breaker still stops a run whose model answers but not usably (wrong build, schema violations in a
   row); its threshold is the larger of `TB_SCREEN_BREAKER_FAILURES` and twice the calls in flight
   (`TB_SCREEN_LLM_CONCURRENCY`), so one event that fails every call in flight cannot open it.

4. **The failure share is checked while the job runs.** The note judge checks the rule of `check_judge` (more than
   10 % of the checks unanswered) after every failure, once it has at least `ceil(2 x calls in flight / share)`
   checks behind it: the number at which two full rounds of in-flight failures are exactly the share. Above it the
   job stops then, with the same message, instead of spending the remaining hours. The end-of-run check stays.

5. **Judged pairs are kept and replayed.** Every answer a job's model client gives is written to
   `orch.judge_answers` under (job, key), where the key is the SHA-256 of the client's role (judge or verifier), the
   job's pinned snapshot, the prompt id, the prompt file's sha and the variables. When the job runs again after a
   restart, a call with the same key gets the stored answer and no model is asked; the job's counters include it
   (`llm_calls` does not start at 0). Only answers are kept, never failures. The rows hold what the model answered
   (a verdict and a quote from a note: D3) and no pseudonym column; they exist only while the job is unfinished: they
   are deleted when the job ends in any state, and the rows of jobs that are finished or gone are deleted when the
   orchestrator starts. The registry entry is `erase`, owed by T-206b for the one case left: a patient who opts out
   while a job that judged them is still running (the job ends within its own run, hours at most). T-724 adds the
   lake generation to the key; until then the pinned snapshot date is the nearest thing.

6. **A restart is counted.** `orch.jobs.attempts` counts how often the orchestrator found the job interrupted at its
   start. `TB_JOB_MAX_RESTARTS` (default 3) is how many restarts one job may survive: the restart may be the job's own
   doing (an out-of-memory kill), and without a count the box loops on it. One more and the job fails with a message
   that says so, its hold is released and its kept answers go. `job.requeued` carries the count.

7. **The budgets come from the population.** SCREEN's pair budget is the job option `max_pairs`, else
   `TB_SCREEN_MAX_PAIRS`, else **none: the population's own pairs** (scoped patients x note criteria), so by default
   nothing is left unprocessed. The fixed 20,000 is gone. The hidden token budget is gone too: the cascade has a token
   budget only when a caller sets one (`CascadeConfig.max_tokens`, default none), so nothing stops a job before the
   pair budget does. When a budget does stop a job (an operator set one), the report and the job record name which
   (`budget.stopped_by`: `pairs` or `tokens`) and where the pair budget came from (`budget.source`: `set` or
   `population`).

## Consequences

- An outage shorter than the allowance costs its own length in wall time and no pair. The nightly scale gate's check
  `screen.outage_no_unknown` passes; its `EXPECTED` line "F-04 (T-689)" is removed with this card.
- A job whose model stays down fails after the allowance, not after its last pair, and says why.
- The gateway is unchanged: its breaker still refuses in milliseconds, which is what makes the caller's poll cheap.
  Its queue and read limits for batch roles are T-698.
- A resumed job repeats its cheap stages (scope, SQL, lexicon, ranking) and replays the model stage; a job of hours
  loses minutes to a restart.

## Not decided here

- Resuming a *failed* job under a new request (the kept answers go with the job).
- A person "pausing" a job by hand.
