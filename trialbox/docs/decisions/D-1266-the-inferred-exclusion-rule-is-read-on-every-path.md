# D-1266 The inferred-exclusion rule of D-985 is read on every path, from one place (J-R16)

- **Task:** lane J, card J-R16, from review R22-16. · **Date:** 2026-11-23
- **The fault (on master `57aeb293`, still on `cfa04081`):** D-985 says an exclusion's "present" stands only on a
  quote that states the condition, never on a negated, family-history, rule-out or suspected quote. Its test
  `matching.inferred.inferred` was called in one place only, the cascade's S3 (`matching/cascade/engine.py`, `_map`).
  The v1 note verdict (`orchestrator/scenarios/evaluate.py` `note_verdict`, then `matching/decision.py` `answer_of`)
  never read it. That path serves re-checks of new patients, the navigation scenario, the single-case scenario and
  SCREEN when the pipeline is set to v1. With both models agreeing as a real pair at 0.9 and the quote verbatim in
  the record, these were `excluded` on v1 and `review` on the cascade:
  - "Known HIV infection" on "Mother has HIV." (record: "Mother has HIV. Patient tested negative for HIV.");
  - "History of myocardial infarction" on "Rule out myocardial infarction; troponin pending.";
  - "Active hepatitis C" on "Suspected hepatitis C, awaiting PCR.";
  - 「HIV感染が既知の患者」 and "Known HIV infection" on 「母親にHIV感染あり。」 (record: 「母親にHIV感染あり。患者本人のHIV検査は陰性。」).
- **Decision:**
  - The rule moves into `matching.decision`, the module both paths already tier through (`status_of`, `answer_of`):
    `inferred_exclusion(criterion, condition_present, quote)` returns the reason `INFERRED` ("inferred: the quote
    does not state the condition; review") or None. It is the only copy:
    - the cascade's S3 calls it in place of its own check (same place in `_map`, same order, same outcome);
    - `note_verdict` calls it: a v1 note answer that says an exclusion is present on such a quote is `unknown`, the
      quote, documents and confidence kept, its reason the code the cascade's row carries for the same outcome
      (`code_of(INFERRED, "unknown", True)`), so the two paths give the same verdict row;
    - `answer_of` reads it for a note `fail` that could otherwise exclude: a stored row from before this decision,
      re-tiered (MICROBATCH), says `unknown`, never `no`.
  - `tb_common.quotes.quote_in` also reads a quote without ONE pair of 「」, straight or curly double quotes around
    the whole of it (`unwrapped`). Before, 「母親にHIV感染あり。」 against a record without the brackets was
    `quote_not_found` and went to review. A quote with its own brackets inside (「高血圧」あり、「糖尿病」) is read as
    written; two pairs around one quote are not stripped.
- **Evidence:** `tests/unit/test_d985_every_path.py` (invariant: no evaluation path excludes on a negated,
  family-history, rule-out or suspected quote) runs the five inputs above on both paths, with `FakeModel` pairs of two
  different weights (`is_pair` true), the verified span and a run that may exclude on notes. On master's code the
  five v1 cases are `excluded`; the cascade's five are `unknown`, not hard, reason `inferred: …; review`, as here. One
  control, "Known HIV infection, on ART.", still excludes on both paths.
- **Not changed:** what `inferred` counts as stating a condition (`matching/inferred.py`); the cascade's outcome on an
  inferred quote (unknown, not hard, the same reason); every other outcome of `_map`, `note_verdict` and `answer_of`;
  an inclusion; a note `fail` without a quote (no D-985 question: on the cascade it never gets a span, on v1
  `postprocess` makes it `quote_not_found`); the cascade's own span check (`matching/cascade/judge.py` `verify_span`
  finds the quote with its own `find` and still does not verify a wrapped quote: that answer stays unknown,
  "insufficient", a person looks); the reason codes; what any role may do or read.
