# D-1266 The inferred-exclusion rule of D-985 holds on every path, and a test says so (J-R16)

- **Task:** lane J, card J-R16, from review R22-16. · **Date:** 2026-11-24
- **The fault (on master `57aeb293`, still on `cfa04081`):** D-985 says an exclusion's "present" stands only on a
  quote that states the condition, never on a negated, family-history, rule-out or suspected quote. Its test
  `matching.inferred.inferred` was called by the cascade's S3 only. The v1 note verdict
  (`orchestrator/scenarios/evaluate.py` `note_verdict`, then `matching/decision.py` `answer_of`) never read it. That
  path serves re-checks of new patients, the navigation scenario, the single-case scenario and SCREEN when the
  pipeline is set to v1. With both models agreeing as a real pair at 0.9 and the quote verbatim in the record, these
  were `excluded` on v1 and `review` on the cascade:
  - "Known HIV infection" on "Mother has HIV." (record: "Mother has HIV. Patient tested negative for HIV.");
  - "History of myocardial infarction" on "Rule out myocardial infarction; troponin pending.";
  - "Active hepatitis C" on "Suspected hepatitis C, awaiting PCR.";
  - 「HIV感染が既知の患者」 and "Known HIV infection" on 「母親にHIV感染あり。」 (record: 「母親にHIV感染あり。患者本人のHIV検査は陰性。」).
- **Where the fix is:** R22-16 (commit `05359e75` and its train-162 merges) made
  `matching.note_answer.note_answer_may` the one rule of what a note answer may do, under D-1069 and D-985. The
  cascade's S3 (`engine._map`), the v1 `note_verdict` and `decision.answer_of` over a stored row all call it. An
  exclusion's "present" on a quote `inferred` flags is `review` with the reason `INFERRED_REASON` ("inferred: the
  quote does not state the condition; review"): unknown and not hard on the cascade; on v1 the row is `unknown` with
  the same reason's code. `tb_common.quotes.unwrap` and `as_in` read a quote the model wrapped in one pair of 「」 or
  double quotes. J-R16 first built its own copy of the rule (`decision.inferred_exclusion`). When R22-16 landed, the
  lane J coordinator ruled that master keeps exactly one rule (#1435 7136130938), so that copy was dropped and this
  card keeps the test.
- **Decision:** `tests/unit/test_d985_every_path.py` holds every path to the rule. Its docstring starts "invariant: no
  evaluation path excludes on a negated, family-history, rule-out or suspected quote". It runs:
  - the five inputs above on both paths, with `FakeModel` pairs of two different weights (`is_pair` true), the
    verified span and a run that may exclude on notes. Neither path gives `excluded`; the cascade gives unknown, not
    hard, `INFERRED_REASON`;
  - the same inputs through `note_answer_may` directly: `review`, with that reason;
  - one control: "Known HIV infection, on ART." still excludes on both paths;
  - a stored pair's final, sure fail on "Mother has HIV." re-tiered by `answer_of`: `unknown`, never `no`;
  - a quote wrapped in 「」, straight or curly double quotes found by `as_in`, and the wrapped Japanese quote never
    excluding on v1; a quote with its own marks inside it read as written.
- **Evidence:** the file passes on master as it stands (23 passed). On `cfa04081`, before R22-16, the five v1 inputs
  were `excluded` (#1435, the first report).
- **Not changed:** any code. `note_answer_may`, `inferred`, `answer_of`, the cascade, `note_verdict` and the quote
  helpers are R22-16's as on master. The cascade's `verify_span` still finds a quote with its own `find`, so a
  wrapped quote gets no span there and goes to review ("insufficient"), a known gap left as is by the coordinator's
  ruling. What any role may do or read is not changed.
