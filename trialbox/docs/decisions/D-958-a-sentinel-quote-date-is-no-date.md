# D-958 A sentinel quote date is no date, and the reply is an answer

- **Task:** G8 of the integrator's second review of the P1b run (#639, 2026-11-16). On NCT00277680 the judge answered "unknown" with `quote_date: "0000-01-01"`, its way of saying it had no date, on both the attempt and the retry. The run's traces hold four such `judge@5` replies.
  - The judge schema's `format: date` refused the reply, so it counted as no answer.
  - One failure in 7 checks is above the 10 % share (`evaluate.MAX_JUDGE_FAILURE_SHARE`), so the whole SCREEN job failed.

  **Date:** 2026-11-16. **Status:** reserved.
- **Decision** (`matching.cascade.judge.no_sentinel_date`, before the schema check). A quote date that is no real date is null: not ISO, or a year before 1900. The reply is then an answer, and an "unknown" stays unknown.
  - A real date is unchanged.
  - A reply that is truly outside the schema is still no answer (LLM-022).
- **The share rule is unchanged, and that is the rule asked for.** A job fails when more than 10 % of its note checks got no answer, however few checks it has. A model that is down must stop even a job of three checks; three tests hold this (`test_screen_cascade`, `test_gateway_one_role_one_model`, `test_gateway_no_fallback`).
  - What failed NCT00277680 was not a lost answer. It was an answer the schema misread, and that is what this card fixes.
  - A minimum number of failures was considered and not chosen: it would let a model that is down pass a small job as a list of "unknown" answers.
- **Test:** `tests/unit/test_judge_sentinel_date.py`, using the run's own reply.
