# D-1325 The MedTxt Japanese pair score is a standing gate on recorded answers (10G-22)

- **Task:** lane H, plan 10 row 10G-22 (review 17, item 17-3): the MedTxt ja pair score as a standing gate for any
  model, prompt or quantisation change. · **Date:** 2026-11-19
- **Decision:**
  - The gate is review 17 §7.3 rules 1 and 2 (the decision rule written before the run), on the ja items, both models
    must block, against the control on the same items. No new threshold is set here:
    - rule 1: stated-absent findings blocked not higher than the control's by more than **1 point**, and the Wilson
      95 % upper bound **under 15 %**;
    - rule 2: present findings blocked **at least the control's**.
  - The control is the shipped pair as recorded (`google/gemma-4-26b-a4b-it@fp4` + `qwen/qwen3.5-9b`,
    `eval/medtxt/gate.json`): 455 of 659 present blocked (69.0 %), 38 of 349 stated absent blocked (10.9 %, upper
    bound 14.6 %), 149 unanswered, the figures of `eval/medtxt/results/scores.json` and of review 17 [M 1].
  - Same items: the candidate has a recorded answer for every item of the key and no more unanswered items (an
    error or no record) than the control. An unanswered item is never a block, so without this a build that fails
    more often would pass rule 1 by saying nothing.
  - The gate reads only files in the tree: the recorded answers (`eval/medtxt/results/raw/<model>__ja.jsonl.gz`) and
    the answer key `eval/medtxt/key.json` (annotation id -> certainty for the 1,677 items of
    `tools/medtxt_eval.dataset()`, with the sha256 of the corpus files it was built from; no report text; CC BY 4.0,
    Sociocom NAIST). The corpus itself stays in `.cache`, never committed. No model is called, nothing is fetched.
  - A model, prompt or quantisation change records its pair with `python -m tools.medtxt_eval run` and names it as
    the candidate in `eval/medtxt/gate.json`; the control changes only by a decision that names the new control.
  - `tools/medtxt_gate.py` (`python -m tools.medtxt_gate check`, `make medtxt-gate`; exit 1 on a fail, each failing
    rule named). CI: the guard test runs in the `checks` job's guard step on every tier (D-1119).
- **Not decided here:** review 17 §7.3 rules 3 to 6 (other languages, operations, licence, the gain worth a
  requalification) and the English items; whether the recorded verifier (the hosted 9B) must be replaced by the
  shipped AWQ build's answers (`models/registry.yaml` `qwen3.5-9b-rtxpro6000`).
- **Held by:** `tests/unit/test_medtxt_pair_gate.py` (today's candidate passes; planted worse builds fail on rule 1,
  rule 2 and the same-items rule; the command exits 1).
