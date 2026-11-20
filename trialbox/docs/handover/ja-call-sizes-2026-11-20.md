# H-10E-38: Japanese judge-call sizes at 8k and 32k

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** 10E-38 (plan 10, track E; review 19 card 19-19, run O-6, acceptance A6; lane H since the integrator's
  ruling of 2026-11-19)
- **Date:** 2026-11-20
- **Decision:** [D-1346](../decisions/D-1346-japanese-judge-call-sizes-are-counted-offline-with-the-box-own-budget.md)
- **Record:** [`ja-call-sizes-2026-11-20/record.json`](ja-call-sizes-2026-11-20/record.json)
- **Findings:** [`ja-call-sizes-2026-11-20/findings.json`](ja-call-sizes-2026-11-20/findings.json)
  (H10E38-01 to H10E38-04)
- **Tool and tests:** `tools/ja_call_sizes.py`, `tests/unit/test_ja_call_sizes.py`

No GPU, no model, no gateway, no Docker daemon and no network were used. The charts are the repository's own
synthetic Japanese hospital.

## 1. The result

| | 8k (site box, `rtx5090`) | 32k (head box, `rtxpro6000`) |
| --- | --- | --- |
| Context of the judge and the verifier (registry) | 8,192 | 32,768 |
| Excerpt budget per prompt (box estimate) | 5,494 to 5,510 | 26,383 to 26,399 |
| Judge calls | 352 | 352 (the same questions) |
| Calls with a note left out or cut | 0 | 0 |
| Share | 0 % | 0 % |
| Prompt size, median / p95 / max (box estimate) | 916 / 2,182 / 2,855 | the same |
| Largest prompt as a share of the context | 34.9 % | 8.7 % |

**A6: pass, +0 points** (the limit is +2). Charts: `tools.synth_hospital`, seed 42, sites
`jp-a:JP:2500,jp-ad:JP:2500:mix_jp_ad`, every note in Japanese (5,000 patients, 8,781 notes). Studies: the eight
shipped rulesets. Only GZQO (121 calls) and ONC-OSI (231) asked the judge anything.

**True count or estimate.** The share is a true count of what the box does. The box decides `left_out` with its own
estimate (`tb_llm.budget`), and the tool runs that code. The prompt sizes are the estimate, not the judge's
tokenizer. That tokenizer is not in the repository and not installed here, and no other tokenizer stands in for it.
The repository holds the judge's counts for 200 synthetic Japanese excerpts (D-645's set). On them the judge counted
0.53 to 0.91 of the estimate (median 0.73). So for the Japanese text of an excerpt, the estimate is an upper bound on
that set. The English template is not in that set. It is the same in both arms, so it cannot change the difference.
The largest call would still be under half of 8k even if the judge counted the whole prompt at 1.4 times the
estimate.

Run it again:

```sh
TB_ENV=DEV PYTHONPATH=libs:services:. python -m tools.ja_call_sizes --out <record.json>
```

It took 3.5 minutes on this container.

## 2. Why the builders' branch was not kept

Draft #1222 (`agent/10E-38-measure-japanese-context`, head `5260e5bd`) captured O-6 on a live box. It read the gateway,
the ballast container and the GPU, and its record from this kind of workspace held zero judge calls. The lead's
rulings bind this card to an offline count. Every finding of its review sits in the capture code (`tools/
japanese_context_rehearsal.py`) or in the reader of its live counts. So this branch starts from master, and none of
that code is carried.

## 3. The review's findings and how each is closed

| Finding (integrator, 2026-11-19) | Closed by |
| --- | --- |
| High: the 8k arm enables two-phase screening; its deferred placeholders count as model failures and stop the run | No two-phase pass and no failure count. The stand-in judge answers "unknown" with no refusal. Tests: `test_the_judge_opens_no_socket_and_reports_no_failure`; `test_the_tool_imports_no_gateway_client_no_two_phase_and_no_test_suite` (no `orchestrator.twophase`). |
| High: an advertised context is taken as proof of the head-box profile | No served context is read. Each arm's context comes from the registered builds of the named profile. The record names alias, profile and context. A profile with no recorded context is refused. Tests: `test_the_arms_contexts_are_the_registered_builds_of_each_profile`, `test_a_profile_with_no_registered_context_is_refused`. |
| High: the orchestrator credential is sent to a container IP that may have changed | No gateway, no credential, no connection. Test: `test_the_judge_opens_no_socket_and_reports_no_failure` (any `connect` fails the test). |
| Medium: any running ballast container qualifies the 8k arm | No ballast. The 8k arm is the 8k registered context, not a memory state. |
| Medium: the reader accepts impossible totals (calls with zero tokens) | A call with no size, a size under its fixed part, a non-S3 call, a question asked twice, or a tampered count is refused. A call that no outcome names is refused too. Tests: `test_an_impossible_call_is_refused` (4 cases), `test_a_question_asked_twice_is_refused`, `test_a_tampered_count_is_refused`, `test_s3_calls_refuse_a_call_no_outcome_names`. |
| Medium: a SIGTERM leaves chart scratch in the report folder | All scratch is in a private folder under the scratch root, never the output's folder. It is removed however the run ends. SIGTERM becomes `SystemExit`. The record is written whole or not at all. Tests: `test_a_sigterm_leaves_no_scratch_and_restores_the_environment`, `test_a_failed_run_files_an_incomplete_record_and_nothing_else`. |
| Medium: the scratch PostgreSQL as root widens a home folder's mode | The ingest's folder is under `pglocal.scratch_root()`, never under the output folder. Its schemas are dropped afterwards. Test: `test_a_failed_run_files_an_incomplete_record_and_nothing_else` (a 0700 folder keeps its mode). This shows only that the tool never roots a cluster under the output. What `pglocal.ensure` does to the scratch root's own parents is unchanged and is not this card's. |
| Medium: capture imports its ingest from the test suite | The tool imports `tools.ingest_local` only. Tests: the import scan, and `test_the_tool_runs_without_the_test_suite_importable` (a subprocess where `tests` and `pytest` cannot be imported). |
| Medium: upstream retries are counted from successful bodies only | Not applicable. No upstream call is made, so nothing is retried. |
| Low: the paired test plants omissions from the profile name | The budget is tested against contexts with the profile name held fixed and changed. The same window is cut at the 8k budget and whole at the 32k one. A run with a 2,048-token arm cuts real synthetic calls, so the count can see a cut. Tests: `test_the_excerpt_budget_follows_the_context_not_the_profile_name`, `test_the_same_window_is_cut_at_8k_and_whole_at_32k`, `test_a_small_context_is_seen_to_cut`. |

The "fails before" half of each test was not run against #1222's code. None of the new tests can import that code,
and the tool has a different shape. The findings were closed by leaving that code out, and the tests pin the
property each one names.

## 4. What was not done

- No true token count. The judge's tokenizer is not here (H10E38-03).
- No tier record and no serving record was written or changed (D-1322).
- The six rulesets that asked nothing were not traced (H10E38-02).
- No real or public Japanese chart was used.
