# Can the safety core's tests be trusted? (card V-4, 2026-11-17)

Plan 8, activity V19 and release criterion 3. Master commit `15108f46b8ea59e6676bc003000d5dcaa24c97a1`. Machine: 4
cores shared with other test runs; the mutation runs used 2 workers. Data: the folder `test-trust-2026-11-17/`. Every
figure of this page sits in a block between `test-trust` markers. `python -m tools.test_trust --write` writes the
blocks from the JSON files, and `--check` (run by `tests/unit/test_test_trust_page.py`) fails when one differs.
Figures marked "CI artifact, d117301f" were measured by the nightly on GitHub, not here.

## Verdict

<!-- test-trust:begin verdict -->
**Criterion 3's "writes the safety core's mutation score to the repository, at or above the agreed floor" does not hold today.** The nightly writes no score to the repository (V4-01).

* Measured here on `15108f46`: **60.4 %** (424 killed) over 702 scored mutants of about 1,237 the tool makes; `engine.py` one part of six. Floor 60 %, threshold 90 %.
* Under the floor alone: `engine.py` 57.4 %, `judge.py` 42.9 %, `evaluate.py` 46.5 %.
* The nightly of 2026-11-16 (CI artifact, d117301f, all cores, every mutant of its own commit): 61.65 %. It is not the same measurement and the two are not compared.
* Coverage (CI artifact, d117301f): 14 of 18 safety-core files meet 95 % line and 90 % branch; under: `services/orchestrator/scenarios/evaluate.py`, `services/criteria_compiler/compile_cql/translator.py`, `libs/tb_common/derived.py`, `services/gateway/core.py`.
* High findings: V4-05, V4-06.
<!-- test-trust:end verdict -->

V4-05 and V4-06 are High. A mutant that the listed tests let live is killed by a small example in
`tests/unit/test_v4_survivor_examples.py`. These examples are shown at the level of `refs()`: the mutant empties the
list of facts or rows that should make a FALSE unknown. The next step, where an empty list leaves the coded FALSE in
place and the patient fails an inclusion, is read from `orchestrator/scenarios/evaluate.py:157-170` and
`matching/cascade/engine.py:632-649` and `:682`. It was not run.

## What ran and what did not

<!-- test-trust:begin ran -->
| Run | Command | Started (UTC) | Ended (UTC) | Mutants | Not run |
| --- | --- | --- | --- | ---: | ---: |
| small | `python -m tools.mutation --target libs/tb_common/quotes.py --target libs/tb_common/pair.py --target services/matching/coverage.py --target services/matching/proposed.py --target services/matching/cascade/judge.py --workers 2` | 2026-11-17T16:19:54Z | 2026-11-17T18:06:36Z | 330 | 0 |
| engine-p1of6 | `python -m tools.mutation --target services/matching/cascade/engine.py --part 1/6 --budget-minutes 150 --workers 2` | 2026-11-17T18:06:36Z | 2026-11-17T20:14:13Z | 101 | 0 |
| evaluate | `python -m tools.mutation --target services/orchestrator/scenarios/evaluate.py --budget-minutes 150 --workers 2` | 2026-11-17T20:14:13Z | 2026-11-17T22:51:53Z | 303 | 32 |

Coverage of the target tests on `15108f46`: 371 passed, 5 skipped, 2 xfailed in 851 s, one core.

Nightly figures: CI artifacts of commit d117301f, not measured here: downloaded on 2026-11-17 into this card's cloud container with the GitHub CLI through the container's proxy: gh run download -R zandis/Auto-GPT 43912198355 -n mutation (and -n coverage-branch for coverage.json); the failed job's log with gh run view 43912198355 --log-failed.
Nightly run list: gh run list -R zandis/Auto-GPT --workflow trialbox-nightly-quality.yml -L 5 --json databaseId,conclusion,createdAt,headSha,event, run on 2026-11-17 in this card's cloud container.
<!-- test-trust:end ran -->

Not run: `engine.py` parts 2 to 6. One part took about two hours on 2 workers, so the other five would take about 11
more hours on this shared machine. Also not run: the 32 `evaluate.py` mutants left when the time budget ran out. The
whole unit suite with branch coverage was not run here, because the lane rules forbid it. A nightly of 2026-11-17
exists (see the run list below). Its artifacts were not fetched.

## Mutation score

This is the tool's score: killed and timed out, divided by the mutants run, less the accepted ones. "Not run here"
counts both the mutants of the parts that did not run and those cut off by the budget. A mutant on a line that the
target's listed tests never run counts as "no coverage", a survivor. Source: `mutation.json` (`runs`, the tool's own
reports).

<!-- test-trust:begin mutation -->
| File | Made | Run here | Not run here | Killed | Timeout | Survived | No coverage | Error | Accepted | Score over those run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `libs/tb_common/pair.py` | 71 | 71 | 0 | 62 | 0 | 9 | 0 | 0 | 0 | 87.3 % |
| `libs/tb_common/quotes.py` | 7 | 7 | 0 | 7 | 0 | 0 | 0 | 0 | 0 | 100.0 % |
| `services/matching/cascade/engine.py` | 604 | 101 | 503 | 58 | 0 | 35 | 8 | 0 | 0 | 57.4 % |
| `services/matching/cascade/judge.py` | 70 | 70 | 0 | 30 | 0 | 33 | 7 | 0 | 0 | 42.9 % |
| `services/matching/coverage.py` | 63 | 63 | 0 | 48 | 0 | 6 | 9 | 0 | 0 | 76.2 % |
| `services/matching/proposed.py` | 119 | 119 | 0 | 93 | 0 | 18 | 8 | 0 | 0 | 78.2 % |
| `services/orchestrator/scenarios/evaluate.py` | 303 | 271 | 32 | 126 | 0 | 57 | 88 | 0 | 0 | 46.5 % |
| **all** | 1237 | 702 | 535 | 424 | 0 | 158 | 120 | 0 | 0 | 60.4 % |
<!-- test-trust:end mutation -->

**Accepted mutants.** The tool accepts a mutant only when its id is listed under `[accepted]` in
`tools/mutation.toml`, with a reason. That list is empty today.

**The nightly's own record.** This is a CI artifact. It ran on all cores over every mutant of its own commit, so it
is not the same measurement as the table above. It is held only as an artifact that GitHub keeps 90 days. No file in
the repository holds a score (V4-01).

<!-- test-trust:begin nightly -->
| Target (CI artifact, d117301f) | Mutants | Baseline run (s) |
| --- | ---: | ---: |
| `services/matching/cascade/engine.py (part 1/2)` | 282 | 258.1 |
| `services/matching/cascade/engine.py (part 2/2)` | 281 | 183.9 |
| `services/orchestrator/scenarios/evaluate.py` | 289 | 132.2 |
| `libs/tb_common/pair.py` | 71 | 47.1 |
| `libs/tb_common/quotes.py` | 7 | 4.6 |
| `services/matching/coverage.py` | 63 | 30.4 |
| `services/matching/proposed.py` | 119 | 17.5 |
| `services/matching/cascade/judge.py` | 63 | 132.9 |

Score 61.65 % (killed 712, no-coverage 150, not-run 20, survived 293); run https://github.com/zandis/Auto-GPT/actions/runs/43912198355.
<!-- test-trust:end nightly -->

<!-- test-trust:begin nightly_runs -->
| Run | Created | Commit | Conclusion |
| --- | --- | --- | --- |
| 44130478177 | 2026-11-17T16:51:18Z | `ee1961e5` | failure |
| 43912198355 | 2026-11-16T16:52:03Z | `d117301f` | failure |
| 43737807053 | 2026-11-15T16:51:21Z | `b811f3e1` | failure |
| 43617896804 | 2026-11-14T16:51:35Z | `5ff9f813` | cancelled |
| 43466990977 | 2026-11-13T16:51:54Z | `63d9746e` | cancelled |
<!-- test-trust:end nightly_runs -->

**Safety-core files with no mutation target.** These lane A2 files have none (V4-03): `compile_sql/generator.py`,
`compile_cql/generator.py`, `compile_cql/translator.py`, `semantics.py`, `equivalence/gate.py`, `guard/guard.py`,
`guard/recognisers.py`, `gateway/core.py`, `gateway/policy.py`. Nor do `libs/tb_common/derived.py` and
`libs/tb_common/phi_guard.py` (lane B2, V4-04). The config gives one reason for its choice of targets: the hand-made
mutants of TB-DR-04 lived there.

**What the tool mutates:**

- comparisons flipped or moved by one;
- `and` and `or` swapped;
- a dropped `not`;
- `True` and `False` swapped;
- an integer plus one;
- a value returned as `None`;
- `break` and `continue` swapped;
- `+` and `-` swapped.

**What it does not:**

- remove a call, a statement or a `raise`;
- swap arguments;
- change a string;
- replace a condition by `True` or `False`;
- mutate chained comparisons, `*`, `/`, `min` or `max`, or an `except` clause.

A `return None` for a bool that is read as a truth value is an equivalent mutant (V4-10).

## The survivors on the invariant paths

U: unknown never excludes. P: a proposed fact never counts. "safe": the mutant moves an answer toward unknown. "tier"
and "pair": not one of the two invariants. `--check` fails when one of these is not a survivor of `mutation.json`.
The example tests were each run on the code and under their mutant, with the line changed by hand and then restored:
each passed on the code and failed under the mutant. `engine.py:1417` changes a tier, not an exclusion, so no example
was built for it. No example was tried for the other rows.

<!-- test-trust:begin survivors -->
| Mutant | Inv. | What no test checks | Finding | Example test |
| --- | --- | --- | --- | --- |
| `services/matching/proposed.py:159:70:cmp:Eq->NotEq` | P | a proposed sex under a sex criterion | V4-06 | test_v4_06_a_proposed_sex_makes_a_decided_sex_answer_unknown |
| `services/matching/proposed.py:159:90:cmp:IsNot->Is` | P | the same | V4-06 | - |
| `services/matching/proposed.py:187:16:flow:continue->break` | P | an atom of the wrong sign before the one that matters | V4-06 | test_v4_06_an_atom_of_the_wrong_sign_does_not_stop_the_scan |
| `services/matching/proposed.py:166:16:bool:or->and` | P | a value set with families only | V4-06 | - |
| `services/matching/proposed.py:175:13:binop:Add->Sub` | P | a window that ends after the index date | V4-06 | - |
| `services/matching/proposed.py:97:11:cmp:Eq->NotEq` | P | the WHO family extension of a value set | V4-06 | - |
| `services/matching/coverage.py:146:20:flow:continue->break` | U | a gap row after a row of another domain | V4-05 | test_v4_05_a_row_of_another_domain_does_not_stop_the_gap_scan |
| `services/matching/coverage.py:148:20:flow:continue->break` | U | a gap row after a row outside the window | V4-05 | test_v4_05_a_row_outside_the_window_does_not_stop_the_gap_scan |
| `services/matching/coverage.py:143:17:binop:Add->Sub` | U | a window that ends after the index date | V4-05 | - |
| `services/matching/cascade/judge.py:212:11:not:drop` | U | a reply that fails its schema | V4-07 | - |
| `services/matching/cascade/judge.py:212:11:bool:or->and` | U | the same | V4-07 | - |
| `services/matching/cascade/judge.py:231:29:bool:or->and` | U | a reply with no confidence | V4-07 | - |
| `services/matching/cascade/judge.py:326:11:bool:or->and` | U | a quote that is not in the excerpt | V4-07 | - |
| `services/matching/cascade/judge.py:330:12:flow:continue->break` | U | a quote in the second excerpt | V4-07 | - |
| `services/matching/cascade/judge.py:336:19:binop:Add->Sub` | U | the span's end | V4-07 | - |
| `services/matching/cascade/judge.py:162:11:cmp:Is->IsNot` | U | the gateway outage switch | V4-07 | - |
| `services/matching/cascade/engine.py:1417:15:cmp:IsNot->Is` | tier | a judged met under the floor is not strong (a tier, not an exclusion) | V4-08 | - |
| `services/matching/cascade/engine.py:333:13:binop:Add->Sub` | U | a note window narrower than a year | V4-08 | - |
| `services/matching/cascade/engine.py:1432:49:cmp:Eq->NotEq` | U | which unknowns the review queue calls a data gap | V4-08 | - |
| `services/orchestrator/scenarios/evaluate.py:626:30:not:drop` | U | a note fail given when note answers may not exclude carries final: false | V4-02 | - |
| `libs/tb_common/pair.py:61:32:cmp:Lt->LtE` | safe | a confidence exactly on the floor (the mutant makes it unknown: the safe direction) | V4-09 | - |
| `libs/tb_common/pair.py:162:7:bool:or->and` | pair | a pair where only one endpoint names its weights (the two-model check, not an invariant) | V4-09 | - |
<!-- test-trust:end survivors -->

## Branch coverage of the safety core

There are two measures. The first is the nightly's: the unit suite with branches, a CI artifact of `d117301f`. Since
that commit, `engine.py`, `judge.py`, `evaluate.py`, `phi_guard.py` and `semantics.py` have changed. The second was
measured here, with only the mutation targets' listed tests. It is a floor, not the suite's figure. The arcs that were
missed are listed in `coverage.json`. On an invariant path, the main one is `derived.py:216`: a missing component
gives no value (V4-15).

<!-- test-trust:begin coverage -->
| File | Line (CI artifact, d117301f) | Branch (CI artifact, d117301f) | Arcs missed (CI artifact, d117301f) | Line (target tests, here) | Branch (target tests, here) | Baseline line | Baseline branch | Against target |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `services/matching/cascade/engine.py` | 98.3 % | 95.1 % | 15 | 94.2 % | 86.1 % | 96.0 % | 90.8 % | met |
| `services/matching/proposed.py` | 95.0 % | 95.8 % | 2 | 94.2 % | 91.7 % | 93.5 % | 91.7 % | met |
| `services/matching/coverage.py` | 95.6 % | 91.7 % | 3 | 86.7 % | 77.8 % | 95.6 % | 91.7 % | met |
| `services/matching/cascade/judge.py` | 100.0 % | 100.0 % | 0 | 92.3 % | 83.3 % | 100.0 % | 100.0 % | met |
| `libs/tb_common/pair.py` | 100.0 % | 100.0 % | 0 | 100.0 % | 100.0 % | 100.0 % | 100.0 % | met |
| `libs/tb_common/quotes.py` | 100.0 % | 100.0 % | 0 | 95.0 % | 75.0 % | 100.0 % | 100.0 % | met |
| `services/orchestrator/scenarios/evaluate.py` | 93.0 % | 88.6 % | 15 | 86.0 % | 78.8 % | 93.1 % | 91.8 % | UNDER |
| `services/criteria_compiler/compile_sql/generator.py` | 96.7 % | 91.0 % | 9 | 92.7 % | 83.0 % | 96.3 % | 90.4 % | met |
| `services/criteria_compiler/compile_cql/generator.py` | 96.5 % | 90.8 % | 11 | 80.7 % | 61.7 % | 95.8 % | 90.0 % | met |
| `services/criteria_compiler/compile_cql/translator.py` | 97.8 % | 89.3 % | 3 | 36.7 % | 3.6 % | 91.1 % | 77.3 % | UNDER |
| `services/criteria_compiler/semantics.py` | 98.2 % | 97.0 % | 2 | 76.7 % | 63.2 % | 98.0 % | 96.7 % | met |
| `services/criteria_compiler/equivalence/gate.py` | 100.0 % | 100.0 % | 0 | 23.8 % | 0.0 % | 26.8 % | 0.0 % | met |
| `libs/tb_common/derived.py` | 94.4 % | 89.7 % | 8 | 86.4 % | 71.8 % | 93.7 % | 86.5 % | UNDER |
| `services/guard/guard.py` | 96.9 % | 100.0 % | 0 | 60.0 % | 18.8 % | 96.8 % | 100.0 % | met |
| `services/guard/recognisers.py` | 98.0 % | 93.3 % | 2 | 63.0 % | 26.7 % | 96.8 % | 89.3 % | met |
| `libs/tb_common/phi_guard.py` | 98.7 % | 98.5 % | 1 | 85.3 % | 47.1 % | 100.0 % | 96.7 % | met |
| `services/gateway/core.py` | 96.5 % | 87.4 % | 25 | 65.1 % | 39.4 % | 94.3 % | 89.7 % | UNDER |
| `services/gateway/policy.py` | 95.9 % | 90.0 % | 13 | 81.1 % | 63.1 % | 93.9 % | 87.5 % | met |
<!-- test-trust:end coverage -->

## The in-process lake and the HTTP one

Every test file listed for a mutation target reaches the lake in process or through a fake. These behaviours exist
only on the HTTP path:

- the service token on reads (`protect_reads=True`);
- the `LakeQuery` contract and its `timeout_s`;
- the generation header and its 400;
- the mapping of statuses into `LakeQueryFailed`, `LakeBadAnswer` and `LakeUnhealthy`;
- the Arrow IPC answer;
- the 503 on a lake limit.

There is no switch to run the in-process tests against the HTTP lake (V4-17). Adding one needs a fixture that puts
the test's `Lake` into `lake.app` and hands over a `LakeHttp` whose client is the app's test client, plus an option in
the shared `tests/conftest.py`. That touches other lanes' fixtures, so it was not done here. The lists follow, from
`lake.json`.

<!-- test-trust:begin lake -->
Rule: git grep -l -F on commit 15108f46 over tests/*.py: a file is listed when its text holds the string, anywhere (code, import or comment).

<details><summary>In process, naming LakeLocal: 57 files</summary>

- `tests/console/test_site_setup_pages.py`
- `tests/inproc_box.py`
- `tests/integration/test_ad_mab.py`
- `tests/integration/test_compile_compose.py`
- `tests/integration/test_feas_lake.py`
- `tests/integration/test_nav_retro.py`
- `tests/integration/test_ra_jak.py`
- `tests/integration/test_ssmix2_path.py`
- `tests/integration/test_vec_s2b_pg.py`
- `tests/judge_kit.py`
- `tests/property/test_judge_in_loop.py`
- `tests/property/test_path_independence.py`
- `tests/unit/test_atc_class_and_disputed_read_unknown.py`
- `tests/unit/test_cascade_exclusion_rules.py`
- `tests/unit/test_cascade_pipeline.py`
- `tests/unit/test_clinical_status.py`
- `tests/unit/test_code_coverage.py`
- `tests/unit/test_coded_values.py`
- `tests/unit/test_criteria_safety.py`
- `tests/unit/test_criteria_safety_review.py`
- `tests/unit/test_derived_definitions.py`
- `tests/unit/test_derived_rest.py`
- `tests/unit/test_derived_scores.py`
- `tests/unit/test_derived_store.py`
- `tests/unit/test_edc_020_lakefacts_on_a_lake.py`
- `tests/unit/test_exclusion_age_lines.py`
- `tests/unit/test_g1_b1_chart_fact_dates.py`
- `tests/unit/test_journey_rules.py`
- `tests/unit/test_judge_key_and_s2b_numpy.py`
- `tests/unit/test_lab_value_unknown.py`
- `tests/unit/test_lake_query_limit_per_job.py`
- `tests/unit/test_lake_query_status.py`
- `tests/unit/test_lake_rebuild_lock.py`
- `tests/unit/test_negated_exclusion_and_empty_lists.py`
- `tests/unit/test_no_record_of_kind.py`
- `tests/unit/test_note_stage_batches.py`
- `tests/unit/test_notes_only_ruleset.py`
- `tests/unit/test_omop_core.py`
- `tests/unit/test_one_rule.py`
- `tests/unit/test_proposed_old_snapshot.py`
- `tests/unit/test_s2b_skipped_when_the_window_fits.py`
- `tests/unit/test_safety_properties.py`
- `tests/unit/test_scenario_findings.py`
- `tests/unit/test_screen_exclusion_pair.py`
- `tests/unit/test_screen_not_at_index.py`
- `tests/unit/test_site_setup.py`
- `tests/unit/test_snapshot_holds.py`
- `tests/unit/test_snapshot_pin.py`
- `tests/unit/test_suspected_diagnosis.py`
- `tests/unit/test_system_not_carried.py`
- `tests/unit/test_t724_generations.py`
- `tests/unit/test_twin.py`
- `tests/unit/test_twin_lake_failure.py`
- `tests/unit/test_undated_lab_quantifiers.py`
- `tests/unit/test_undated_lab_values.py`
- `tests/unit/test_unit_scales.py`
- `tests/unit/test_vec_s2b.py`

</details>

<details><summary>In process, naming inproc_box: 25 files</summary>

- `tests/e2e/journeys/steps.py`
- `tests/e2e/test_mail_compose.py`
- `tests/integration/test_ad_mab.py`
- `tests/integration/test_case_inproc.py`
- `tests/integration/test_coded_values_inproc.py`
- `tests/integration/test_cohort_inproc.py`
- `tests/integration/test_consent_inproc.py`
- `tests/integration/test_ingest_inproc.py`
- `tests/integration/test_mail_feas_inproc.py`
- `tests/integration/test_nav_inproc.py`
- `tests/integration/test_onboarding.py`
- `tests/integration/test_phi_at_rest_inproc.py`
- `tests/integration/test_ra_jak.py`
- `tests/integration/test_rerun.py`
- `tests/integration/test_screen_inproc.py`
- `tests/integration/test_twpas_inproc.py`
- `tests/orch_box.py`
- `tests/property/test_path_independence.py`
- `tests/unit/test_demo_seed_case.py`
- `tests/unit/test_log_retention.py`
- `tests/unit/test_mail_resolve.py`
- `tests/unit/test_new_life_1_no_preapproved_ruleset.py`
- `tests/unit/test_per_study_retention_after_close.py`
- `tests/unit/test_retention.py`
- `tests/unit/test_retention_holds_a_running_study.py`

</details>

<details><summary>Over HTTP, naming LakeHttp or lake.app: 21 files</summary>

- `tests/integration/test_compile_compose.py`
- `tests/unit/test_dataflow_lake_p0.py`
- `tests/unit/test_lake_build_process.py`
- `tests/unit/test_lake_client_answers.py`
- `tests/unit/test_lake_client_snapshot.py`
- `tests/unit/test_lake_error_answers.py`
- `tests/unit/test_lake_open_limit.py`
- `tests/unit/test_lake_query_limit_per_job.py`
- `tests/unit/test_lake_query_status.py`
- `tests/unit/test_lake_rebuild_lock.py`
- `tests/unit/test_log_scrubber_on.py`
- `tests/unit/test_polled_jobs.py`
- `tests/unit/test_publish_promotes_its_generation.py`
- `tests/unit/test_s1_whole_or_batches.py`
- `tests/unit/test_service_secrets.py`
- `tests/unit/test_service_token_everywhere.py`
- `tests/unit/test_snapshot_holds.py`
- `tests/unit/test_t724_generations.py`
- `tests/unit/test_t724_review.py`
- `tests/unit/test_twin_lake_failure.py`
- `tests/unit/test_vec_s2b.py`

</details>
<!-- test-trust:end lake -->

## The weakest tests

These tests of the safety core would pass with a wrong answer in the case they name. The tool records no test that
killed a mutant, so "never the first to fail" could not be measured (V4-11). None of these tests was changed.

<!-- test-trust:begin weak -->
| Test | Why it is weak | The change that would make it bite | Basis | Evidence |
| --- | --- | --- | --- | --- |
| `tests/unit/test_cascade_units.py::test_span_must_verify_text_window_and_date` | never checks the span's start or end | `assert span["end"] - span["start"] == len("on dialysis since 2025")` | shown | judge.py:336 start + len(q) to start - len(q): 1 passed |
| `tests/unit/test_one_rule.py::test_a_proposed_fact_on_a_window_bound_counts` | every case's window ends on the index date | `add a case whose window ends after the index date` | shown | proposed.py:175 index_date + timedelta to index_date - timedelta: 5 passed |
| `tests/unit/test_one_rule.py::test_a_proposed_birth_date_or_sex_matters_to_a_derived_value` | asks eGFR and a lab value only; never a sex criterion | `for what == "sex", assert p.refs(<a Female criterion>, "P", INDEX, False) == ["f-demo"]` | shown | proposed.py:159 f.code == "sex" to !=: 2 passed |
| `tests/unit/test_code_coverage.py::test_coverage_counts_and_windows` | no patient has a row of another domain before the matching one | `give UNK-OLD a medication row before its condition row` | shown | coverage.py:146 continue to break: 1 passed |
| `tests/unit/test_cascade_exclusion_rules.py::test_a_not_met_below_the_confidence_floor_is_unknown` | tries a not met at 0.74 and 0.95, never a met under the floor | `add a met at 0.74 and assert its tier is not strong` | shown | engine.py:1417 conf is not None to conf is None: 1 passed |
| `tests/unit/test_safety_properties.py::test_p4_a_fact_that_would_change_an_answer_once_confirmed_already_makes_it_unknown` | assert not missed holds when every evaluated answer is unknown | `also assert some evaluated answers are decided` | hypothesis | - |
| `tests/unit/test_cascade_pipeline.py::test_end_to_end_passes` | all(e2e.checks.values()) holds for no checks; the assert e2e.passed before it carries the test | `assert e2e.checks and all(e2e.checks.values())` | hypothesis | - |
<!-- test-trust:end weak -->

## Findings

<!-- test-trust:begin findings -->
| Id | Severity | Lane | Basis | Place | Claim |
| --- | --- | --- | --- | --- | --- |
| V4-01 | Medium | D | shown | `.github/workflows/trialbox-nightly-quality.yml:124` | The nightly writes no mutation score to the repository: the score is only a CI artifact (kept 90 days) and the job summary. No committed file holds a score with its commit and date. The only figure, 61.65 % (run 43912198355, 2026-11-16, commit d117301f), rests on that CI artifact alone; it was not measured here. |
| V4-02 | Medium | A2 | shown | `tools/mutation.toml:8` | Measured on 15108f46: 60.4 % over 702 scored of about 1,237 mutants (engine.py one part of six; 32 of evaluate.py not run), under the threshold of 90 %. By file: quotes.py 100 %, pair.py 87.3 %, proposed.py 78.2 %, coverage.py 76.2 %, engine.py 57.4 %, evaluate.py 46.5 %, judge.py 42.9 %: three are under the floor of 60 % alone. |
| V4-03 | Medium | A2 | shown | `tools/mutation.toml:38` | 9 safety-core files of lane A2 are no mutation target (compile_sql/generator.py, compile_cql/generator.py, compile_cql/translator.py, semantics.py, equivalence/gate.py, guard/guard.py, guard/recognisers.py, gateway/core.py, gateway/policy.py; 1,232 mutants the tool would make). The only reason written is that the targets are where the 28 hand-made mutants of TB-DR-04 lived. |
| V4-04 | Medium | B2 | shown | `tools/mutation.toml:38` | libs/tb_common/derived.py (177 mutants) and libs/tb_common/phi_guard.py (148) are no mutation target. derived.py is on the 'a proposed fact never counts' path (a proposed birth date or sex under eGFR). |
| V4-05 | High | A2 | shown | `services/matching/coverage.py:143` | coverage.py:146 and :148 continue->break survive the listed tests and are shown to change an answer: tests/unit/test_v4_survivor_examples.py::test_v4_05_* pass on the code and fail under each mutant (refs() level). An empty refs() leaves the inclusion's coded FALSE in place (evaluate.py:157-160, engine.py:682), so a patient with an unreadable record is excluded instead of unknown. :143 (window end) has no example. |
| V4-06 | High | A2 | shown | `services/matching/proposed.py:159` | proposed.py:159 (== to != on sex) and :187 (continue->break) survive the listed tests and are shown to change an answer: tests/unit/test_v4_survivor_examples.py::test_v4_06_* pass on the code and fail under each mutant (refs() level). An empty refs() leaves the coded FALSE in place (evaluate.py:164-170, engine.py:632-649): a patient coded male with a proposed sex of female fails 'Female' instead of being unknown. :166, :175, :97 have no example. |
| V4-07 | Medium | A2 | shown | `services/matching/cascade/judge.py:212` | judge.py scores 42.9 % (30 of 70 killed). Survivors on the decision path: :212 the schema check (not dropped; or->and), :231/:233/:234 the defaults of a reply with a missing field, :326/:330/:332/:336 how a quote is located in the excerpts, :162 the outage switch. The listed tests never send a malformed reply. |
| V4-08 | Medium | A2 | shown | `services/matching/cascade/engine.py:1417` | In the engine sample (part 1 of 6) 35 of 101 survive. :1417 IsNot->Is lets a weak 'met' count as strong (a tier, not an exclusion, so no example was built); :333 (a note window narrower than a year), :1432 (the review queue's data gaps): no example tried for lack of time. |
| V4-09 | Medium | A2 | shown | `libs/tb_common/pair.py:61` | pair.py:61 < to <= survives: a decision exactly on the floor becomes unknown, the safe direction, so it does not threaten 'unknown never excludes'; it shows only that no test sits on the boundary. :162 (the two-model check with one endpoint that does not name its weights) survives too. |
| V4-10 | Medium | D | hypothesis | `tools/mutation.py:146` | The tool has 9 operator classes. It never removes a call, a statement or a raise, never swaps arguments, never changes a string, never replaces a condition by True or False, never mutates chained comparisons, * or /, min or max, or an except clause. return:None is equivalent for a bool used as a truth value (proposed.py:158, :163, :167 survive for that reason) and the accepted list is empty. |
| V4-11 | Medium | D | shown | `tools/mutation.py:387` | A mutant runs only the target's listed tests, and a line those tests never run counts as a survivor. The lists cover less than the suite (engine.py branches 86.1 % by its listed tests, 95.1 % by the suite). The tool records no test that killed a mutant, so no test can be shown never to be the first to fail. |
| V4-12 | Medium | A2 | shown | `services/orchestrator/scenarios/evaluate.py:94` | evaluate.py: 93.0 % line and 88.6 % branch in the nightly of 2026-11-16, under target and under its own baseline (91.8 %): the nightly's ratchet failed on it. 15 arcs missed (commit d117301f). |
| V4-13 | Medium | A2 | shown | `services/gateway/core.py:1` | gateway/core.py: 87.4 % branch (25 arcs missed), under target and under its baseline floor 89.16 %: the nightly's ratchet failed on it. |
| V4-14 | Medium | A2 | shown | `services/criteria_compiler/compile_cql/translator.py:1` | compile_cql/translator.py: 89.3 % branch, under target (above its baseline of 77.3 %, so the ratchet passes it). |
| V4-15 | Medium | B2 | shown | `libs/tb_common/derived.py:216` | derived.py: 94.4 % line and 89.7 % branch. The branch derived.py:216->217 (a missing component gives no value) is never taken by the unit suite, nor :236 (a non-finite value) nor the basdai and asdas lines :450-:455. |
| V4-16 | Medium | D | shown | `.github/workflows/trialbox-nightly-quality.yml:12` | nightly_runs.json (gh run list, fetched 2026-11-17): of the last 5 nightly quality runs (2026-11-13 to 2026-11-17) 3 failed and 2 were cancelled. On 2026-11-16 the branch-coverage job failed (model_guard, evaluate.py, gateway/core.py; the job log, fetched the same way). |
| V4-17 | Medium | B2 | hypothesis | `services/lake/client.py:303` | No switch exists. lake.json lists the files: 57 name LakeLocal, 25 name inproc_box, 21 reach the lake over HTTP. Every mutation target's tests reach it in process or through a fake, so they never pass the service token on reads, the LakeQuery contract, the generation header, the status mapping to LakeQueryFailed, LakeBadAnswer and LakeUnhealthy, the Arrow IPC answer, or the 503 on a lake limit. |
| V4-18 | Medium | A2 | shown | `tests/unit/test_cascade_units.py:32` | Seven weak tests are named (ten were asked); five are shown to pass with the product code broken (weak_tests.json), two are read only. |
| V4-19 | Low | D | shown | `tools/coverage_baseline.json:1` | The baseline still holds equivalence/gate.py at 26.8 % line and 0 % branch; the nightly measures 100 % and 100 %. The review's L-2 rests on the old figure. |
<!-- test-trust:end findings -->

Basis: *shown* means a run of this card or a named CI artifact wrote it. *Hypothesis* means it was read from the code
and not run.
