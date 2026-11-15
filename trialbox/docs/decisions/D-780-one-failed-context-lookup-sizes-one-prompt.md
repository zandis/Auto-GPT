# D-780 One failed context lookup sizes one prompt, not a whole run; the run counts the prompts it sized on the default

- **Task:** SCR-18, the part the deep review of 2026-11-13 left for lane A2 (`engine.budget_of`); the owner's order
- **PR:** #578 (merged with train 15)
- **Date:** 2026-11-14
- **Status:** merged
- **Builds on:** T-603 / OD-10 (the excerpt budget from the models' context), T-689 / D-456 (the cascade metrics)

## Decision

`matching.cascade.engine._Run.budget_of` keeps a criterion's excerpt budget for the run only once the judge has told
it. When the judge cannot tell (a failed `GET /v1/models`), that prompt gets `EXCERPT_TOKENS` (2,500) and the next
prompt asks again; it used to keep the default for the rest of the run, so later patients got another excerpt set,
other `left_out` counts and other tiers. `LlmClient` already keeps an unknown context for up to 300 s, so the gateway
is asked about twice per 300 s per client at most. `CascadeMetrics.context_unknown` counts, per criterion, the prompts
sized on the default; it is in the run manifest's cascade block and the screen summary, sorted. A boolean from
`excerpt_budget` is no budget; a told 0 is kept and a judge that raises raises, as before.

## Test

`tests/unit/test_budget_of_context_unknown.py`.
