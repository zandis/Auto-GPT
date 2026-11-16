# D-942 The lake's guard keeps its verdict for a query it accepted

- **Task:** a red from lane D's nightly triage (#639, 2026-11-16, T-653): perf-5k had the cascade at 5,000 patients at 27.8 s in CI against a scaled baseline of 14.7 s, and 41.3 s against 17.4 s locally. Passed to lane A2 by the integrator. **Date:** 2026-11-16. **Status:** reserved.
- **Found:**
  - **The bisect.** Master's first-parent history at 2,000 patients, with a 10 s line between good and bad, named train 19 (#665): 5.6 s before it, 12.9 s after.
  - **The cause.** Train 19 brought D-748, which runs the cascade's S1 in batches of patients. Each batch sends the same compiled query to the lake (about 500 KB of SQL for GZQO), and `lake.sqlguard.check_select` parsed it with sqlglot every time.
  - **The profile.** On master at 5,000 patients it put 42 of 92 s in that parse.
- **Decision:**
  - **The cache.** `check_select` keeps its verdict for a text it accepted (`functools.lru_cache`, 256 texts): the same text is accepted without a second parse.
  - **Why it is safe.** The verdict depends on the text alone, so nothing is accepted that was not accepted before. A refusal is never kept: it is parsed and refused each time. A different text, however close, is parsed on its own. The read-only connection's locked configuration (the second defence) is unchanged.
- **Measured on one development host** (the cascade at 5,000 patients, the stub run of `make bench-gate`):

  | Run | Cascade |
  |---|---|
  | master 628f2ebb | 37.8 s |
  | with this card | 20.7 s |
  | with this card and S1 in one batch (`TB_CASCADE_S1_ROWS` very large) | 14.6 s |
  | the baseline commit 2e3f3434 | 8.6 s |

  - **S1 in batches** costs about 6 s at 5,000 patients: the compiled query is planned and run once per batch. That is D-748's trade of the lake's memory for time, on purpose. Its batch size (`TB_CASCADE_S1_ROWS`, 12,000 rows) is lane B2's to tune.
  - **The other 6 s** is the work cards since 2026-11-10 added on purpose: the kind-of-record checks (D-914), the coverage and carried-system checks (D-130, D-795), and the judge through the gateway.
  - **The baseline.** It is adopted from the next nightly's artifact (`tools/bench.py --adopt`, on the runner, as `tools/bench_baseline.json` asks), not from this host.
- **Test:** `tests/unit/test_sqlguard_keeps_its_verdict.py`.
