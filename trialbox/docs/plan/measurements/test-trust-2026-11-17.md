# Can the safety core's tests be trusted? (card V-4, 2026-11-17)

Plan 8, activity V19 and release criterion 3. Master commit `15108f46b8ea59e6676bc003000d5dcaa24c97a1`. Machine: 4
cores shared with other test runs; the mutation runs used 2 workers. Data: `test-trust-2026-11-17/` (`mutation.json`,
`coverage.json`, `findings.json`). The tables between the `test-trust` markers are written by
`python -m tools.test_trust --write` and checked by `--check` (the unit test `tests/unit/test_test_trust_page.py`).

## Verdict

**Criterion 3's "writes the safety core's mutation score to the repository, at or above the agreed floor" does not
hold today.** The nightly writes no score to the repository (V4-01), and the score is at the floor, not above it with
room: 60.4 % over the mutants run here (floor 60 %, threshold 90 %), and 61.65 % in the last nightly. engine.py
(57.4 %, a sixth of it) and evaluate.py (46.5 %) are under the floor alone; judge.py is at 42.9 %. 11 of the 18
safety-core files have no mutation target (V4-03, V4-04).

**Coverage.** 14 of the 18 files meet 95 % line and 90 % branch in the last nightly; `evaluate.py`,
`gateway/core.py`, `compile_cql/translator.py` and `derived.py` do not, and the nightly's ratchet failed. The tests
of the safety core never run against the HTTP lake, and nothing can make them (V4-17). No finding is High: no
surviving mutant was shown to change an eligibility answer in a runnable example.

## What ran and what did not

| Run | Command | Started (UTC) | Ended (UTC) | Result |
| --- | --- | --- | --- | --- |
| small targets | `python -m tools.mutation --target` quotes, pair, coverage, proposed, judge `--workers 2` | 16:19:54 | 18:06:36 | 330 mutants, all run |
| engine, part 1 of 6 | `--target services/matching/cascade/engine.py --part 1/6 --budget-minutes 150 --workers 2` | 18:06:36 | 20:14:13 | 101 mutants, all run |
| evaluate | `--target services/orchestrator/scenarios/evaluate.py --budget-minutes 150 --workers 2` | 20:14:13 | 22:51:53 | 303 mutants, 32 not run (budget) |
| coverage, target tests | `pytest <the 22 listed test files> -n 0 --cov --cov-branch` | 16:20:36 | 16:34:51 | 371 passed, 5 skipped, 2 xfailed |

Not run: engine.py parts 2 to 6 (503 mutants). One part took 128 minutes on 2 workers; the five others would take
about 11 hours more on this shared machine. The nightly's own shards were not copied: they use every core. Not run:
the whole unit suite with branches (lane rules); its figures come from the nightly artifact. No mutant timed out and
none ended in an error.

## Mutation score

The score is the tool's: killed and timed out, divided by all mutants less the accepted ones and those not run. A
mutant on a line the target's listed tests never run counts as "no coverage", a survivor. Source: `mutation.json`
(`runs`, the tool's own reports).

<!-- test-trust:begin mutation -->
| File | Made | Run here | Killed | Timeout | Survived | No coverage | Error | Accepted | Not run | Score |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `libs/tb_common/pair.py` | 71 | 71 | 62 | 0 | 9 | 0 | 0 | 0 | 0 | 87.3 % |
| `libs/tb_common/quotes.py` | 7 | 7 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 100.0 % |
| `services/matching/cascade/engine.py` | 604 | 101 | 58 | 0 | 35 | 8 | 0 | 0 | 0 | 57.4 % |
| `services/matching/cascade/judge.py` | 70 | 70 | 30 | 0 | 33 | 7 | 0 | 0 | 0 | 42.9 % |
| `services/matching/coverage.py` | 63 | 63 | 48 | 0 | 6 | 9 | 0 | 0 | 0 | 76.2 % |
| `services/matching/proposed.py` | 119 | 119 | 93 | 0 | 18 | 8 | 0 | 0 | 0 | 78.2 % |
| `services/orchestrator/scenarios/evaluate.py` | 303 | 303 | 126 | 0 | 57 | 88 | 0 | 0 | 32 | 46.5 % |
| **all run here** | 1237 | 734 | 424 | 0 | 158 | 120 | 0 | 0 | 32 | 60.4 % |
<!-- test-trust:end mutation -->

"Made" is what `python -m tools.mutation --list` makes from the file today. The engine row is part 1 of 6 (every
sixth mutant); the other five parts did not run.

**Accepted mutants.** The tool accepts a mutant only when its id is listed under `[accepted]` in
`tools/mutation.toml`, with a reason (an equivalent change). That list is empty today, so nothing is accepted.

**The nightly's own record.** The last full nightly (run 43912198355, 2026-11-16, commit `d117301f`) scored
61.65 %: 712 killed, 293 survived, 150 no coverage, 20 not run. That figure exists only as a CI artifact, which
GitHub keeps 90 days. The workflow commits nothing: no file in the repository holds a score with its commit and
date (V4-01).

**Safety-core files with no mutation target.** 11 of the 18: `compile_sql/generator.py`, `compile_cql/generator.py`,
`compile_cql/translator.py`, `semantics.py`, `equivalence/gate.py`, `guard/guard.py`, `guard/recognisers.py`,
`gateway/core.py`, `gateway/policy.py` (A2, V4-03), `libs/tb_common/derived.py` and `libs/tb_common/phi_guard.py`
(B2, V4-04). The config says why the targets are the seven they are: the 28 hand-made mutants of TB-DR-04 lived
there. No decision rules the other 11 out.

**What the tool mutates.** Nine kinds: a comparison flipped or moved by one (`==`/`!=`, `<`/`<=`, `>`/`>=`,
`in`/`not in`, `is`/`is not`), `and`/`or`, a `not` dropped, `True`/`False`, an integer plus one, a value returned as
`None`, `break`/`continue`, `+`/`-`. **What it does not:** remove a call or a statement, remove a `raise`, swap
arguments, change a string, replace a condition by `True` or `False`, mutate a chained comparison, `*` or `/`,
`min`/`max`, an `except` clause, or `<` into `>`. A `return None` for a bool read as a truth value is an equivalent
mutant (`proposed.py:158`, `:163`, `:167`), and these are not accepted. The score therefore proves less than it
seems to (V4-10).

## The survivors on the two invariant paths

From `mutation.json`. "Unknown never excludes" (U) and "a proposed fact never counts" (P). None was turned into a
runnable example that changes an eligibility answer, so each is Medium.

| Place | Mutation | Inv. | What no test checks |
| --- | --- | --- | --- |
| `services/matching/coverage.py:146` | continue -> break | U | a gap row after a row of another domain |
| `services/matching/coverage.py:148` | continue -> break | U | a gap row after a row outside the window |
| `services/matching/coverage.py:143` | `+` -> `-` (window end) | U | a window that ends after the index date |
| `services/matching/proposed.py:159` | `==` -> `!=` (sex) | P | a proposed sex under a sex criterion |
| `services/matching/proposed.py:159` | `is not` -> `is` | P | the same |
| `services/matching/proposed.py:166` | or -> and | P | a value set with families only |
| `services/matching/proposed.py:187` | continue -> break | P | an atom of the wrong sign before the one that matters |
| `services/matching/proposed.py:175` | `+` -> `-` (window end) | P | a window that ends after the index date |
| `services/matching/proposed.py:97` | `==` -> `!=`, `in` -> `not in` | P | the WHO family extension of a value set |
| `services/matching/cascade/judge.py:212` | not dropped; or -> and | U | a reply that fails its schema |
| `services/matching/cascade/judge.py:231` | or -> and | U | a reply with no confidence |
| `services/matching/cascade/judge.py:326` | or -> and | U | a quote that is not in the excerpt |
| `services/matching/cascade/judge.py:330` | continue -> break | U | a quote in the second excerpt |
| `services/matching/cascade/judge.py:336` | `+` -> `-` (span end) | U | the span's end |
| `services/matching/cascade/judge.py:162` | `is` -> `is not` | U | the gateway outage switch |
| `services/matching/cascade/engine.py:1417` | `is not` -> `is` | U | a judged "met" under the floor is not strong |
| `services/matching/cascade/engine.py:333` | `+` -> `-` (window start) | U | a note window narrower than a year |
| `services/matching/cascade/engine.py:1432` | `==` -> `!=` | U | which unknowns the review queue calls a data gap |
| `libs/tb_common/pair.py:61` | `<` -> `<=` | U | a confidence exactly on the floor |
| `libs/tb_common/pair.py:162` | or -> and | U | a pair where only one endpoint names its weights |

In `evaluate.py` (57 survivors), the ones on an invariant path: `:626` (or -> and, `!=` -> `==`, not dropped) in
`not_final`, so no listed test checks that a note "fail" given when note answers may not exclude carries
`final: false`; `:521` and `:293` (`>` -> `>=`, the judge failure share on its boundary); `:571` (how a structured
verdict finds its evidence); `:587` (`!=` -> `==`, the basis "coded"). These are part of V4-02.

## Branch coverage of the safety core

Two measures. "Nightly": the repository's own set-up (the unit suite with branches, 12 shards, then
`tools/coverage_ratchet.py`), from the artifact `coverage-branch` of the nightly of 2026-11-16 on commit `d117301f`.
Since then `engine.py`, `judge.py`, `evaluate.py`, `phi_guard.py` and `semantics.py` have changed, so their nightly
figures are a day old. "Target tests": measured here on `15108f46` with only the mutation targets' listed tests (one
core, 851 s); it is a floor, not the suite's figure. The whole unit suite was not run here (lane rules). Source:
`coverage.json`.

<!-- test-trust:begin coverage -->
| File | Line (nightly) | Branch (nightly) | Branch arcs missed | Line (target tests) | Branch (target tests) | Baseline line | Baseline branch | Against target |
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

Under target in the nightly: `evaluate.py` (V4-12), `gateway/core.py` (V4-13), `compile_cql/translator.py` (V4-14),
`derived.py` (V4-15). Uncovered branches on an invariant path: `derived.py:216` (a missing component gives no value:
the unknown path of a derived value), `derived.py:236`, `evaluate.py:94`, `:107`, `:116`, `:133` (commit
`d117301f`), `proposed.py:97`, `coverage.py:163`. The full arc lists are in `coverage.json`.

## The in-process lake and the HTTP one

| Path | How a test reaches the lake | Files |
| --- | --- | --- |
| In process | `lake.client.LakeLocal` (directly, or through `tests/inproc_box.make_box`) | 57 test files name `LakeLocal`; 25 name `inproc_box` |
| Over HTTP | `lake.client.LakeHttp` or the lake's FastAPI app (`services/lake/app.py`) | 13 test files, all about the lake client or service |
| Neither | a fake lake object | several cascade tests |

Every test file listed for a mutation target reaches the lake in process or through a fake. These behaviours exist
only on the HTTP path, so those tests never exercise them: the service token on reads (`protect_reads=True`), the
`LakeQuery` contract and its `timeout_s`, the generation header and its 400, the status mapping into
`LakeQueryFailed`, `LakeBadAnswer` and `LakeUnhealthy`, the Arrow IPC answer, the 503 on a lake limit, and the
client's read margin. There is no switch to run them against the HTTP lake (V4-17). It would take a fixture that
puts the test's `Lake` into `lake.app` and hands the tests a `LakeHttp` whose client is the app's test client, then a
`--lake=http` option in `tests/conftest.py`. That touches the shared conftest and the fixtures of other lanes' tests,
so it was not added here.

## The weakest tests

Tests of the safety core that would pass with a wrong answer in the case they name. The tool records no test that
killed a mutant, so "never the first to fail" could not be measured (V4-11). No listed test is skipped in CI's
tiers; four skip without the CQL jars and one without `TB_JUDGE_LLM_URL`. None of these was changed.

| Test | Why it is weak | The change that would make it bite |
| --- | --- | --- |
| `tests/unit/test_cascade_pipeline.py::test_gateway_refusal_fails_closed` | builds `judged` and never asserts on it; the one check holds when nobody reaches S3 | `assert judged and all(o.status != "fail" for o in judged)` |
| `tests/unit/test_cascade_units.py::test_span_must_verify_text_window_and_date` | never checks the span's end (`judge.py:336` survives) | `assert span["end"] - span["start"] == len("on dialysis since 2025")` |
| `tests/unit/test_one_rule.py::test_a_proposed_fact_on_a_window_bound_counts` | every case's window ends on the index date (`proposed.py:175` survives) | add a case whose window ends after the index date |
| `tests/unit/test_one_rule.py::test_a_proposed_birth_date_or_sex_matters_to_a_derived_value` | covers eGFR only; a sex criterion is never asked (`proposed.py:159` survives) | assert `p.refs(<sex criterion>, ...) == ["f-demo"]` for `sex` |
| `tests/unit/test_safety_properties.py::test_p4_a_fact_that_would_change_an_answer_once_confirmed_already_makes_it_unknown` | `assert not missed` holds when every answer is unknown | also assert some answers are decided |
| `tests/unit/test_code_coverage.py::test_coverage_counts_and_windows` | no fixture row order where the scan's order matters (`coverage.py:146`, `:148` survive) | put a row of another domain before the matching one |
| `tests/unit/test_cascade_exclusion_rules.py::test_a_not_met_below_the_confidence_floor_is_unknown` | 0.74 and 0.95 against 0.75, never on the floor; a weak "met" is never tried (`engine.py:1417`, `pair.py:61` survive) | add 0.75 and a "met" at 0.74 that must not be strong |
| `tests/unit/test_cascade_pipeline.py::test_end_to_end_passes` | `all(e2e.checks.values())` holds for no checks | `assert e2e.checks and all(e2e.checks.values())` |

## Findings

<!-- test-trust:begin findings -->
| Id | Severity | Lane | Basis | Place | Claim |
| --- | --- | --- | --- | --- | --- |
| V4-01 | Medium | D | shown | `.github/workflows/trialbox-nightly-quality.yml:124` | The nightly writes no mutation score to the repository: the score is only a CI artifact (kept 90 days) and the job summary. No committed file holds a score with its commit and date. The last artifact (run 43912198355, 2026-11-16, commit d117301f) says 61.65 %. |
| V4-02 | Medium | A2 | shown | `tools/mutation.toml:8` | Measured on 15108f46: 60.4 % over the 702 scored mutants run here (424 killed), under the threshold of 90 % and just over the floor of 60 %. By file: quotes.py 100 %, pair.py 87.3 %, proposed.py 78.2 %, coverage.py 76.2 %, engine.py 57.4 % (part 1 of 6 only), evaluate.py 46.5 % (32 not run), judge.py 42.9 %. engine.py alone and evaluate.py alone are under the floor. |
| V4-03 | Medium | A2 | shown | `tools/mutation.toml:38` | 9 safety-core files of lane A2 are no mutation target (compile_sql/generator.py, compile_cql/generator.py, compile_cql/translator.py, semantics.py, equivalence/gate.py, guard/guard.py, guard/recognisers.py, gateway/core.py, gateway/policy.py; 1,232 mutants the tool would make). The only reason written is that the targets are where the 28 hand-made mutants of TB-DR-04 lived. |
| V4-04 | Medium | B2 | shown | `tools/mutation.toml:38` | libs/tb_common/derived.py (177 mutants) and libs/tb_common/phi_guard.py (148) are no mutation target. derived.py is on the 'a proposed fact never counts' path (a proposed birth date or sex under eGFR). |
| V4-05 | Medium | A2 | shown | `services/matching/coverage.py:143` | Mutants on the gap-row scan survive: coverage.py:146 and :148 continue->break (the scan stops at the first row of another domain or out of the window) and :143 the window's end moved the wrong way. No listed test has two rows where order matters, or a window that ends after the index date. Not shown to change an eligibility answer in a runnable example. |
| V4-06 | Medium | A2 | shown | `services/matching/proposed.py:159` | 18 survivors in proposed.py. On the invariant path: :159 a proposed sex under a sex criterion (Eq->NotEq, IsNot->Is), :166 the value-set filter (or->and), :187 continue->break over signed atoms, :175 the window end (all test windows end on the index date), :97-98 the WHO family extension. No test asks refs() for a demographic sex atom. |
| V4-07 | Medium | A2 | shown | `services/matching/cascade/judge.py:212` | judge.py scores 42.9 % (30 of 70 killed). Survivors on the decision path: :212 the schema check (not dropped; or->and), :231/:233/:234 the defaults of a reply with a missing field, :326/:330/:332/:336 how a quote is located in the excerpts, :162 the outage switch. The listed tests never send a malformed reply. |
| V4-08 | Medium | A2 | shown | `services/matching/cascade/engine.py:1417` | In the engine sample (part 1 of 6) 35 of 101 survive. On the invariant path: :1417 IsNot->Is (a weak 'met' then counts as strong), :333 Add->Sub (a note window narrower than a year opens after the index date), :1428/:1432 how the review queue sorts 'uncertain' and 'data gap', :612 the unknown-code-system count. |
| V4-09 | Medium | A2 | shown | `libs/tb_common/pair.py:61` | pair.py: the boundary of the confidence floor (< to <=) survives, and so do :162/:163 (one endpoint of the pair that does not name its weights). No test sits on the boundary. |
| V4-10 | Medium | D | hypothesis | `tools/mutation.py:146` | The tool has 9 operator classes. It never removes a call, a statement or a raise, never swaps arguments, never changes a string, never replaces a condition by True or False, never mutates chained comparisons, * or /, min or max, or an except clause. return:None is equivalent for a bool used as a truth value (proposed.py:158, :163, :167 survive for that reason) and the accepted list is empty. |
| V4-11 | Medium | D | shown | `tools/mutation.py:387` | A mutant runs only the target's listed tests, and a line those tests never run counts as a survivor. The lists cover less than the suite (engine.py branches 86.1 % by its listed tests, 95.1 % by the suite). The tool records no test that killed a mutant, so no test can be shown never to be the first to fail. |
| V4-12 | Medium | A2 | shown | `services/orchestrator/scenarios/evaluate.py:94` | evaluate.py: 93.0 % line and 88.6 % branch in the nightly of 2026-11-16, under target and under its own baseline (91.8 %): the nightly's ratchet failed on it. 15 arcs missed (commit d117301f). |
| V4-13 | Medium | A2 | shown | `services/gateway/core.py:1` | gateway/core.py: 87.4 % branch (25 arcs missed), under target and under its baseline floor 89.16 %: the nightly's ratchet failed on it. |
| V4-14 | Medium | A2 | shown | `services/criteria_compiler/compile_cql/translator.py:1` | compile_cql/translator.py: 89.3 % branch, under target (above its baseline of 77.3 %, so the ratchet passes it). |
| V4-15 | Medium | B2 | shown | `libs/tb_common/derived.py:216` | derived.py: 94.4 % line and 89.7 % branch. The branch derived.py:216->217 (a missing component gives no value) is never taken by the unit suite, nor :236 (a non-finite value) nor the basdai and asdas lines :450-:455. |
| V4-16 | Medium | D | shown | `.github/workflows/trialbox-nightly-quality.yml:12` | The last five nightly quality runs (2026-11-12 to 2026-11-16) are 3 cancelled and 2 failed; on 2026-11-16 the branch-coverage job failed (model_guard, evaluate.py, gateway/core.py). |
| V4-17 | Medium | B2 | hypothesis | `services/lake/client.py:303` | No switch exists. Every mutation target's tests reach the lake through LakeLocal or a fake, so they never pass the service token check on reads, the LakeQuery contract, the generation header, the status mapping to LakeQueryFailed, LakeBadAnswer and LakeUnhealthy, the Arrow IPC answer, or the 503 on a lake limit. |
| V4-18 | Medium | A2 | hypothesis | `tests/unit/test_cascade_pipeline.py:207` | Eight safety-core tests would pass with a wrong answer in the case they name (the table 'The weakest tests' of the page): an unused computed value, assertions an empty result satisfies, cases that never sit on a boundary. |
| V4-19 | Low | D | shown | `tools/coverage_baseline.json:1` | The baseline still holds equivalence/gate.py at 26.8 % line and 0 % branch; the nightly measures 100 % and 100 %. The review's L-2 rests on the old figure. |
<!-- test-trust:end findings -->

Basis: *shown* means a run of this card wrote it (`mutation.json`, `coverage.json`, or the named nightly run);
*hypothesis* means read from the code, not run.
