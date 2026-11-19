# The MedTxt Japanese pair gate (2026-11-19)

**Reader:** the people who build TrialBox: lane H, the lanes that change a model, a prompt or a quantisation, and the
integrator. For builders, so in one language.

Plan 10 row 10G-22 (review 17, item 17-3), decision D-1325. No findings.

## What changed

`tools/medtxt_gate.py` scores a judge + verifier pair on its recorded MedTxt ja answers and holds it to review 17
§7.3 rules 1 and 2 against the control pair, on the same items. Nothing is called or fetched: it reads the recorded
answers (`eval/medtxt/results/raw/`), the new answer key `eval/medtxt/key.json` (annotation id -> certainty, 1,677
items, no report text) and `eval/medtxt/gate.json` (the control and the candidate).

| | Figure | Where it comes from |
| --- | --- | --- |
| Control | the shipped pair as recorded: `google/gemma-4-26b-a4b-it@fp4` + `qwen/qwen3.5-9b` | review 17 §2 and §13 row 1; `eval/medtxt/results/scores.json` |
| Present blocked (both) | 455 of 659, 69.0 % | recomputed from the key and the recorded answers; equal to `scores.json` (tested) |
| Stated absent blocked (both) | 38 of 349, 10.9 %, Wilson 95 % upper bound 14.6 % | same |
| Rule 1 | stated absent blocked at most the control's + 1 point, and upper bound under 15 % | review 17 §7.3 rule 1 |
| Rule 2 | present blocked at least the control's | review 17 §7.3 rule 2 |
| Same items | every key item recorded; unanswered (error or no record) not more than the control's 149 | review 17 §7.3 "on the same items"; an unanswered item is never a block |

With today's control one more stated-absent block passes (39 of 349, upper bound 14.9 %); three more fail on the
upper bound alone (41, 15.5 %); five more fail both parts of rule 1 (43, 12.3 %). One present finding fewer fails
rule 2.

## How to use it

A change of model, prompt or quantisation: record the pair (`python -m tools.medtxt_eval run --models ...`), name it
as `candidate` in `eval/medtxt/gate.json`, run `make medtxt-gate` (exit 1 names each failing rule). CI runs
`tests/unit/test_medtxt_pair_gate.py` in the `checks` job's guard step on every tier (it is marked `guard`, D-1119),
so a candidate that fails the gate fails CI. The proof, a planted worse build failing, is the same test file: the
builds are written from today's recorded answers with a few answers changed.

## Open questions

1. The recorded verifier is the hosted 9B through a provider; the shipped verifier is the AWQ 4-bit build
   (`models/registry.yaml` `qwen3.5-9b-rtxpro6000`). Review 17 §12 says the MedTxt numbers are not the box's. When the
   box's own pair is recorded (`--base-url`), should it become the control?
2. The gate is not tied to `models/registry.yaml`: a registry change without a new candidate in `gate.json` is not
   caught. Tying them needs a mapping from build ids to recorded names, which the repository does not have.
3. Rules 3 to 6 of §7.3 and the English items are not gated here.
